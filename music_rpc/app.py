"""Application loop: poll MPRIS, build presence, talk to Discord."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import signal
import threading
import time
from collections import deque
from pathlib import Path
from typing import Deque, Optional

from . import APP_NAME, __version__
from .artwork import ArtworkResolver
from .config import Config, runtime_dir
from .discord_ipc import DiscordIPC, DiscordIPCError
from .mpris import PlayerctlMonitor, PlayerctlNotFound, Track, select_track
from .presence import PresenceBuilder, activity_signature

LOGGER = logging.getLogger(__name__)


class InstanceLock:
    """Prevent two copies from fighting over the Discord presence."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or (runtime_dir() / f"{APP_NAME}-{os.getuid()}.lock")
        self._fd: Optional[int] = None

    def acquire(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as exc:
            LOGGER.warning("Cannot create instance lock %s: %s", self.path, exc)
            return True
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            try:
                pid = os.read(fd, 32).decode("ascii", "replace").strip()
            except OSError:
                pid = "?"
            os.close(fd)
            LOGGER.error(
                "Another Linux Music RPC instance is already running (pid %s).",
                pid or "?",
            )
            return False
        except OSError as exc:
            LOGGER.warning("Could not lock %s: %s", self.path, exc)
            os.close(fd)
            return True
        try:
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode("ascii"))
        except OSError:
            pass
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(self._fd)
        except OSError:
            pass
        self._fd = None


class MusicRPCApp:
    def __init__(self, config: Config, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.monitor = PlayerctlMonitor()
        self.artwork = ArtworkResolver(config)
        self.builder = PresenceBuilder(config, self.artwork)
        self.discord = (
            None
            if dry_run
            else DiscordIPC(config.client_id, config.ipc_path)
        )

        self._stop = threading.Event()
        self._lock = InstanceLock()
        self._last_player: Optional[str] = None
        self._last_desired_sig: Optional[str] = None
        self._pending_activity: Optional[dict] = None
        self._pending_clear = False
        self._last_sent_sig: Optional[str] = None
        self._update_times: Deque[float] = deque()
        self._next_discord_attempt = 0.0
        self._discord_warned = False
        self._last_logged: Optional[tuple] = None
        self._no_players_logged = False
        self._shut_down = False

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> int:
        if not self.dry_run:
            if not self._lock.acquire():
                return 1
        LOGGER.info("Linux Music RPC %s started", __version__)
        if self.dry_run:
            LOGGER.info("Dry-run mode: Discord is not contacted")
        else:
            LOGGER.info("Discord application ID: %s", self.config.client_id)
        if self.config.priority_players:
            LOGGER.info(
                "Player priority: %s", ", ".join(self.config.priority_players)
            )
        if self.config.ignore_players:
            LOGGER.info("Ignored players: %s", ", ".join(self.config.ignore_players))

        try:
            while not self._stop.is_set():
                started = time.monotonic()
                try:
                    self.tick()
                except PlayerctlNotFound:
                    raise
                except Exception:
                    LOGGER.exception("Unexpected error in polling loop")
                elapsed = time.monotonic() - started
                self._stop.wait(max(0.05, self.config.poll_interval - elapsed))
        finally:
            self.shutdown()
        return 0

    def tick(self) -> None:
        now_mono = time.monotonic()
        now_wall = time.time()
        tracks = self.monitor.poll()
        active = select_track(
            tracks,
            self._last_player,
            self.config.priority_players,
            self.config.show_paused,
            self.config.ignore_players,
        )
        if active is not None:
            self._last_player = active.player
            self._no_players_logged = False
            self._log_track(active)
            activity = self.builder.build(active, now=now_wall)
            signature = activity_signature(activity)
            if signature != self._last_desired_sig:
                self._last_desired_sig = signature
                self._pending_activity = activity
                self._pending_clear = False
                LOGGER.debug("Activity changed: %s", signature)
        else:
            if not self._no_players_logged:
                LOGGER.info("No active MPRIS players/tracks")
                self._no_players_logged = True

            changed = self._last_desired_sig != "none"
            self._last_desired_sig = "none"
            if changed:
                # Only clear something that was actually shown. This avoids
                # pointless connection attempts when the app starts with no
                # music playing.
                self._pending_activity = None
                if (
                    self.config.clear_when_stopped
                    and self._last_sent_sig not in (None, "null")
                ):
                    self._pending_clear = True
                else:
                    self._pending_clear = False
        self._flush(now_mono)

    def _log_track(self, track: Track) -> None:
        key = (track.key, track.status)
        if key == self._last_logged:
            return
        self._last_logged = key
        title = track.title or "(unknown track)"
        artist = track.artist_text or "(unknown artist)"
        label = "Playing" if track.is_playing else "Paused"
        LOGGER.info("%s: %s — %s [%s]", label, artist, title, track.player)

    def _flush(self, now_mono: float) -> None:
        if self.dry_run:
            if self._pending_activity is not None or self._pending_clear:
                LOGGER.debug(
                    "Dry-run activity: %s",
                    json.dumps(
                        self._pending_activity,
                        ensure_ascii=False,
                        indent=2,
                    )
                    if self._pending_activity is not None
                    else "clear",
                )
            self._pending_activity = None
            self._pending_clear = False
            return

        if self._pending_activity is None and not self._pending_clear:
            return
        if now_mono < self._next_discord_attempt:
            return
        if not self._rate_ok(now_mono):
            LOGGER.debug("Rate limit: waiting before next Discord update")
            return

        assert self.discord is not None
        try:
            if not self.discord.is_connected():
                self.discord.connect()
            if self._pending_clear:
                self.discord.clear()
                self._last_sent_sig = "null"
                self._pending_clear = False
                LOGGER.info("Discord presence cleared")
            else:
                activity = self._pending_activity
                assert activity is not None
                self.discord.set_activity(activity)
                self._last_sent_sig = activity_signature(activity)
                self._pending_activity = None
                LOGGER.debug("Discord presence updated")
            self._update_times.append(now_mono)
            self._discord_warned = False
        except DiscordIPCError as exc:
            if self.discord is not None:
                self.discord.close(send_close=False)
            self._next_discord_attempt = now_mono + self.config.reconnect_interval
            if not self._discord_warned:
                LOGGER.warning(
                    "Discord is unavailable: %s. Retrying in %.0f s.",
                    exc,
                    self.config.reconnect_interval,
                )
                self._discord_warned = True
            else:
                LOGGER.debug("Discord reconnect failed: %s", exc)
        except OSError as exc:
            if self.discord is not None:
                self.discord.close(send_close=False)
            self._next_discord_attempt = now_mono + self.config.reconnect_interval
            if not self._discord_warned:
                LOGGER.warning(
                    "Discord IPC error: %s. Retrying in %.0f s.",
                    exc,
                    self.config.reconnect_interval,
                )
                self._discord_warned = True

    def _rate_ok(self, now_mono: float) -> bool:
        cutoff = now_mono - 20.0
        while self._update_times and self._update_times[0] < cutoff:
            self._update_times.popleft()
        if len(self._update_times) >= 5:
            return False
        if (
            self._update_times
            and now_mono - self._update_times[-1] < self.config.min_update_interval
        ):
            return False
        return True

    def shutdown(self) -> None:
        if self._shut_down:
            return
        self._shut_down = True
        if self.discord is not None:
            try:
                if (
                    self.config.clear_on_exit
                    and self.discord.is_connected()
                    and self._last_sent_sig not in (None, "null")
                ):
                    self.discord.timeout = 2.0
                    self.discord.clear()
                    LOGGER.info("Discord presence cleared on exit")
            except (DiscordIPCError, OSError) as exc:
                LOGGER.debug("Could not clear presence on exit: %s", exc)
            self.discord.close()
        self.artwork.close()
        self._lock.release()


def install_signal_handlers(app: MusicRPCApp) -> None:
    def handler(signum, _frame):
        LOGGER.info("Received signal %s, shutting down", signum)
        app.stop()

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(signum, handler)
        except (ValueError, OSError):
            pass

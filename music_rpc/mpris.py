"""MPRIS access through playerctl.

MPRIS is the standard D-Bus interface exposed by Spotify, browsers, VLC,
mpv (with a script), Rhythmbox, Elisa, Strawberry and many other players.
Using ``playerctl`` keeps this project free of Python D-Bus dependencies and
works on every distribution that packages playerctl.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

LOGGER = logging.getLogger(__name__)

# ASCII Unit Separator. A literal control character is passed to playerctl so
# titles containing tabs, pipes or semicolons cannot break parsing.
SEP = "\x1f"

FORMAT = SEP.join(
    [
        "{{playerInstance}}",
        "{{playerName}}",
        "{{status}}",
        "{{title}}",
        "{{artist}}",
        "{{album}}",
        "{{albumArtist}}",
        "{{mpris:length}}",
        "{{mpris:artUrl}}",
        "{{position}}",
        "{{xesam:url}}",
    ]
)

PLAYER_NAMES = {
    "spotify": "Spotify",
    "chromium": "Chromium",
    "chrome": "Google Chrome",
    "brave": "Brave",
    "msedge": "Microsoft Edge",
    "firefox": "Firefox",
    "yandexmusic": "Яндекс Музыка",
    "yandex-music": "Яндекс Музыка",
    "yandex": "Яндекс Музыка",
    "vlc": "VLC",
    "mpv": "mpv",
    "rhythmbox": "Rhythmbox",
    "elisa": "Elisa",
    "strawberry": "Strawberry",
    "amberol": "Amberol",
    "audacious": "Audacious",
    "clementine": "Clementine",
    "deadbeef": "DeaDBeeF",
    "museeks": "Museeks",
    "cider": "Cider",
    "apple-music": "Apple Music",
    "tidal": "TIDAL",
    "deezer": "Deezer",
    "qobuz": "Qobuz",
}

PLAYING = "playing"
PAUSED = "paused"
STOPPED = "stopped"


class PlayerctlNotFound(RuntimeError):
    pass


@dataclass(frozen=True)
class Track:
    player: str
    status: str
    title: str
    artists: Tuple[str, ...]
    album: str
    length_us: int
    art_url: str
    position_us: int
    url: str

    @property
    def artist_text(self) -> str:
        return ", ".join(self.artists)

    @property
    def key(self) -> Tuple[str, str, Tuple[str, ...], str, int, str]:
        """Identity of a track. Position is deliberately not included."""
        return (
            self.player,
            self.title,
            self.artists,
            self.album,
            self.length_us,
            self.url,
        )

    @property
    def is_playing(self) -> bool:
        return self.status == PLAYING

    @property
    def is_paused(self) -> bool:
        return self.status == PAUSED

    @property
    def position_seconds(self) -> float:
        return max(0.0, self.position_us / 1_000_000.0)

    @property
    def length_seconds(self) -> float:
        return max(0.0, self.length_us / 1_000_000.0)


def _clean(value: str) -> str:
    return value.replace("\x00", "").strip()


def _to_int(value: str) -> int:
    value = value.strip()
    if not value:
        return 0
    try:
        number = int(float(value))
    except ValueError:
        return 0
    return max(0, number)


def _title_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme not in {"file", "http", "https"}:
        return ""
    name = Path(unquote(parsed.path)).name
    if not name or name in {"/", "."}:
        return ""
    if parsed.scheme != "file" and "." not in name:
        # Avoid turning https://www.youtube.com/watch?v=... into "watch".
        return ""
    stem = Path(name).stem
    return stem.replace("_", " ").strip()


def _parse_artists(raw: str) -> Tuple[str, ...]:
    raw = _clean(raw)
    if not raw:
        return ()
    # playerctl turns the MPRIS xesam:artist array into a ;-separated string.
    # Do not split on commas: a single artist can legitimately contain one.
    artists = tuple(part.strip() for part in raw.split(";") if part.strip())
    return artists or (raw,)


def parse_metadata_lines(output: str) -> List[Track]:
    """Parse ``playerctl -a metadata -f`` output.

    This function is separated from the subprocess call so it can be tested
    without a running media player.
    """
    tracks: List[Track] = []
    seen_players = set()
    for raw_line in output.splitlines():
        if not raw_line.strip():
            continue
        fields = raw_line.split(SEP)
        if len(fields) < 11:
            LOGGER.debug("Ignoring malformed playerctl line: %r", raw_line)
            continue
        (
            player_instance,
            player_name,
            status,
            title,
            artists,
            album,
            _album_artist,
            length,
            art_url,
            position,
            url,
        ) = fields[:11]

        player_instance = _clean(player_instance)
        player_name = _clean(player_name)
        player = player_instance or player_name
        if not player or player in seen_players:
            continue
        seen_players.add(player)

        status = _clean(status).lower()
        if status not in {PLAYING, PAUSED, STOPPED}:
            # Some players report states like "Buffering". Treat them as
            # playing so useful metadata is not hidden.
            status = PLAYING if status else STOPPED

        url = _clean(url)
        title = _clean(title) or _title_from_url(url)
        tracks.append(
            Track(
                player=player,
                status=status,
                title=title,
                artists=_parse_artists(artists),
                album=_clean(album),
                length_us=_to_int(length),
                art_url=_clean(art_url),
                position_us=_to_int(position),
                url=url,
            )
        )
    return tracks


def player_matches(pattern: str, name: str) -> bool:
    """Match a player name against a config pattern.

    ``spotify`` matches ``spotify``; ``chromium`` matches
    ``chromium.instance1234``; glob patterns such as ``firefox*`` work too.
    """
    pattern = pattern.strip().lower()
    name = name.strip().lower()
    if not pattern:
        return False
    return (
        fnmatch.fnmatchcase(name, pattern)
        or name == pattern
        or name.startswith(pattern + ".")
    )


def display_player_name(name: str) -> str:
    base = name.split(".", 1)[0].lower()
    return PLAYER_NAMES.get(base, base)


def select_track(
    tracks: Sequence[Track],
    last_player: Optional[str],
    priority_players: Sequence[str],
    show_paused: bool,
    ignore_players: Sequence[str] = (),
) -> Optional[Track]:
    """Choose the player whose track should be shown.

    Rules, in order:
    0. Players matching ``ignore_players`` are discarded.
    1. A playing player always wins over a paused one.
    2. With ``priority_players`` configured, the first matching player wins.
    3. Otherwise the previously selected player is kept while it is active,
       which prevents jumping between players.
    4. Fallback: the first player in playerctl's list.
    """
    if ignore_players:
        tracks = [
            track
            for track in tracks
            if not any(
                player_matches(pattern, track.player)
                for pattern in ignore_players
            )
        ]

    playing = [track for track in tracks if track.is_playing]
    paused = [track for track in tracks if track.is_paused]

    def by_priority(items: Iterable[Track]) -> Optional[Track]:
        for pattern in priority_players:
            for track in items:
                if player_matches(pattern, track.player):
                    return track
        return None

    if playing:
        chosen = by_priority(playing)
        if chosen:
            return chosen
        if last_player:
            for track in playing:
                if track.player == last_player:
                    return track
        return playing[0]

    if paused and show_paused:
        chosen = by_priority(paused)
        if chosen:
            return chosen
        if last_player:
            for track in paused:
                if track.player == last_player:
                    return track
        return paused[0]

    return None


class PlayerctlMonitor:
    """Polls all MPRIS players through playerctl."""

    def __init__(self, executable: Optional[str] = None, timeout: float = 4.0):
        self.executable = executable or shutil.which("playerctl")
        if not self.executable:
            raise PlayerctlNotFound(
                "playerctl not found. Install it with your package manager "
                "(Arch: pacman -S playerctl, Debian/Ubuntu: apt install playerctl, "
                "Fedora: dnf install playerctl)."
            )
        self.timeout = timeout

    def _run(self, args: Sequence[str]) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.setdefault("LANG", "C.UTF-8")
        return subprocess.run(
            [self.executable, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout,
            env=env,
            check=False,
        )

    def list_players(self) -> List[str]:
        try:
            result = self._run(["-l"])
        except (OSError, subprocess.SubprocessError) as exc:
            LOGGER.debug("playerctl -l failed: %s", exc)
            return []
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def poll(self) -> List[Track]:
        try:
            result = self._run(["-a", "--no-messages", "metadata", "-f", FORMAT])
        except (OSError, subprocess.SubprocessError) as exc:
            LOGGER.debug("playerctl metadata failed: %s", exc)
            return []

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            if "no players" in stderr.lower() or not result.stdout.strip():
                return []
            LOGGER.debug("playerctl exited with %s: %s", result.returncode, stderr)
        return parse_metadata_lines(result.stdout)

    def version(self) -> str:
        try:
            result = self._run(["--version"])
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        return (result.stdout or result.stderr).strip() or "unknown"

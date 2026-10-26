"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import APP_NAME, __version__
from .app import MusicRPCApp, install_signal_handlers
from .artwork import ArtworkResolver
from .config import (
    Config,
    ConfigError,
    default_config_path,
    ensure_config,
    load_config,
)
from .discord_ipc import DiscordIPC, DiscordIPCError, discover_sockets
from .mpris import PlayerctlMonitor, PlayerctlNotFound, select_track
from .presence import PresenceBuilder

LOGGER = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
        force=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=(
            "Показывает текущий трек из любого MPRIS-плеера "
            "в статусе Discord (Listening)."
        ),
    )
    parser.add_argument(
        "-c",
        "--config",
        metavar="PATH",
        help="путь к config.ini (по умолчанию ~/.config/linux-music-rpc/config.ini)",
    )
    parser.add_argument(
        "--client-id",
        metavar="ID",
        help="переопределить Application ID из конфига (для проверки)",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="создать конфиг и выйти",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="перезаписать конфиг при --init",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="не подключаться к Discord, только показывать выбранный трек",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="опросить плееры один раз и напечатать JSON активности",
    )
    parser.add_argument(
        "--list-players",
        action="store_true",
        help="показать доступные MPRIS-плееры",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="проверить playerctl, конфиг, сокеты Discord и handshake",
    )
    parser.add_argument(
        "--print-config-path",
        action="store_true",
        help="напечатать путь к конфигу и выйти",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="подробный журнал (debug)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{APP_NAME} {__version__}",
    )
    return parser


def run_once(config: Config) -> int:
    monitor = PlayerctlMonitor()
    tracks = monitor.poll()
    active = select_track(
        tracks,
        None,
        config.priority_players,
        config.show_paused,
        config.ignore_players,
    )
    if active is None:
        LOGGER.info("No active MPRIS players/tracks")
        print("null")
        return 0

    LOGGER.info(
        "Selected: %s (%s) — %s",
        active.player,
        active.status,
        active.title or "(unknown track)",
    )
    artwork = ArtworkResolver(config)
    try:
        artwork.resolve_now(active)
        builder = PresenceBuilder(config, artwork)
        activity = builder.build(active)
        print(json.dumps(activity, ensure_ascii=False, indent=2))
    finally:
        artwork.close()
    return 0


def list_players() -> int:
    monitor = PlayerctlMonitor()
    names = monitor.list_players()
    tracks = {track.player: track for track in monitor.poll()}
    if not names:
        print("No MPRIS players found.")
        print("Start a player (Spotify, a browser with a playing tab, VLC, ...).")
        return 0
    for name in names:
        track = tracks.get(name)
        if track:
            title = track.title or "(unknown track)"
            artist = track.artist_text or "(unknown artist)"
            print(f"{name}\t{track.status}\t{artist} — {title}")
        else:
            print(f"{name}\t(no metadata)")
    return 0


def check(config: Config) -> int:
    ok = True
    print(f"{APP_NAME} {__version__}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Config: {config.path}")
    if config.client_id:
        print(f"Discord client ID: {config.client_id}")
    else:
        print("Discord client ID: NOT SET")
        ok = False

    try:
        monitor = PlayerctlMonitor()
    except PlayerctlNotFound as exc:
        print(f"playerctl: NOT FOUND ({exc})")
        ok = False
    else:
        print(f"playerctl: {monitor.executable} ({monitor.version()})")
        players = monitor.list_players()
        if players:
            print("MPRIS players:")
            tracks = {track.player: track for track in monitor.poll()}
            for name in players:
                track = tracks.get(name)
                if track:
                    print(
                        f"  - {name}: {track.status}, "
                        f"{track.title or '(unknown track)'}"
                    )
                else:
                    print(f"  - {name}: (no metadata)")
        else:
            print("MPRIS players: none (start a player to test)")

    sockets = discover_sockets(config.ipc_path)
    print("Discord IPC sockets:")
    if sockets:
        for path in sockets:
            print(f"  - {path}")
    else:
        print("  (none found; is Discord running?)")

    if config.client_id:
        ipc = DiscordIPC(config.client_id, config.ipc_path, timeout=3.0)
        try:
            ipc.connect()
            print(f"Discord handshake: OK ({ipc.path})")
        except DiscordIPCError as exc:
            print(f"Discord handshake: FAILED — {exc}")
            ok = False
        finally:
            ipc.close()
    else:
        print("Discord handshake: skipped (client ID is not configured)")

    print(
        "Artwork: "
        + (
            f"{config.artwork_provider}"
            if config.artwork_active
            else "disabled"
        )
    )
    return 0 if ok else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config_path = (
        Path(args.config).expanduser() if args.config else default_config_path()
    )

    if args.print_config_path:
        print(config_path)
        return 0

    if args.init:
        try:
            created = ensure_config(config_path, force=args.force)
        except ConfigError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        if created:
            print(f"Created config: {config_path}")
        elif args.force:
            print(f"Overwrote config: {config_path}")
        else:
            print(f"Config already exists: {config_path}")
        print("Set [discord] client_id to your Discord Application ID.")
        return 0

    try:
        config = load_config(config_path, create=True)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    if args.client_id:
        client_id = args.client_id.strip()
        if not client_id.isdigit():
            print(
                "Error: --client-id must be the numeric Application ID.",
                file=sys.stderr,
            )
            return 2
        config.client_id = client_id

    setup_logging("debug" if args.verbose else config.log_level)

    if config.created:
        LOGGER.info("Created config file: %s", config.path)
        if not (
            args.once
            or args.dry_run
            or args.list_players
            or args.check
        ):
            LOGGER.error(
                "Set [discord] client_id in %s, then run the program again.",
                config.path,
            )
            return 2

    if args.list_players:
        return list_players()
    if args.check:
        return check(config)
    if args.once:
        return run_once(config)
    if not config.discord_configured and not args.dry_run:
        LOGGER.error(
            "Discord client ID is not configured. Edit %s and set "
            "[discord] client_id, or pass --client-id for a quick test.",
            config.path,
        )
        return 2

    app = MusicRPCApp(config, dry_run=args.dry_run)
    install_signal_handlers(app)
    try:
        return app.run()
    except PlayerctlNotFound as exc:
        LOGGER.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        app.stop()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

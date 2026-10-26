"""Configuration loading for Linux Music RPC.

The format is INI (stdlib :mod:`configparser`) so the program works on any
modern distribution with Python 3.9+, without third-party modules.
"""

from __future__ import annotations

import configparser
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import APP_NAME

CONFIG_FILENAME = "config.ini"
DEFAULT_CONFIG_TEMPLATE = Path(__file__).with_name("config.example.ini")

LOG_LEVELS = {"debug", "info", "warning", "error"}
ARTWORK_PROVIDERS = {"auto", "direct", "itunes", "none"}

# Used only if the packaged example file is missing (e.g. a broken package).
_MINIMAL_CONFIG = """\
[discord]
client_id =

[presence]
poll_interval = 1.0
show_paused = true
clear_when_stopped = true
clear_on_exit = true
paused_text = ⏸ Пауза
fallback_state = Неизвестный исполнитель
details_format = {title}
state_format = {artist} — {album}
show_progress = true
button_label = Открыть трек
min_update_interval = 2.0

[players]
priority_players =
ignore_players =

[artwork]
enabled = true
provider = auto
fallback_image =
playing_image =
paused_image =

[logging]
level = info
"""


class ConfigError(Exception):
    """Raised when the configuration file cannot be read or is invalid."""


def config_home() -> Path:
    value = os.environ.get("XDG_CONFIG_HOME")
    return Path(value).expanduser() if value else Path.home() / ".config"


def cache_home() -> Path:
    value = os.environ.get("XDG_CACHE_HOME")
    return Path(value).expanduser() if value else Path.home() / ".cache"


def runtime_dir() -> Path:
    value = os.environ.get("XDG_RUNTIME_DIR")
    if value:
        return Path(value).expanduser()
    return Path("/tmp")


def default_config_path() -> Path:
    return config_home() / APP_NAME / CONFIG_FILENAME


@dataclass
class Config:
    path: Path
    created: bool = False

    # [discord]
    client_id: str = ""
    ipc_path: Optional[str] = None
    reconnect_interval: float = 10.0

    # [presence]
    poll_interval: float = 1.0
    show_paused: bool = True
    clear_when_stopped: bool = True
    clear_on_exit: bool = True
    paused_text: str = "⏸ Пауза"
    fallback_state: str = "Неизвестный исполнитель"
    details_format: str = "{title}"
    state_format: str = "{artist} — {album}"
    show_progress: bool = True
    button_label: str = "Открыть трек"
    min_update_interval: float = 2.0

    # [players]
    priority_players: List[str] = field(default_factory=list)
    ignore_players: List[str] = field(default_factory=list)

    # [artwork]
    artwork_enabled: bool = True
    artwork_provider: str = "auto"
    fallback_image: str = ""
    playing_image: str = ""
    paused_image: str = ""

    # [logging]
    log_level: str = "info"

    @property
    def discord_configured(self) -> bool:
        return bool(self.client_id)

    @property
    def artwork_active(self) -> bool:
        return self.artwork_enabled and self.artwork_provider != "none"


def _read_template() -> str:
    try:
        return DEFAULT_CONFIG_TEMPLATE.read_text(encoding="utf-8")
    except OSError:
        return _MINIMAL_CONFIG


def ensure_config(path: Path, force: bool = False) -> bool:
    """Create the config file from the example if it does not exist.

    Returns ``True`` if a file was created.
    """
    path = path.expanduser()
    if path.exists() and not force:
        if not path.is_file():
            raise ConfigError(f"Config path is not a file: {path}")
        return False

    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(_read_template(), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except OSError as exc:
        raise ConfigError(f"Cannot create config {path}: {exc}") from exc
    return True


def _get(parser: configparser.ConfigParser, section: str, option: str,
         fallback: str = "") -> str:
    try:
        return parser.get(section, option, fallback=fallback).strip()
    except (configparser.NoSectionError, configparser.NoOptionError):
        return fallback.strip()


def _get_float(parser: configparser.ConfigParser, section: str, option: str,
               fallback: float) -> float:
    raw = _get(parser, section, option, str(fallback))
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(
            f"[{section}] {option}: expected a number, got {raw!r}"
        ) from exc


def _get_int(parser: configparser.ConfigParser, section: str, option: str,
             fallback: int) -> int:
    raw = _get(parser, section, option, str(fallback))
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(
            f"[{section}] {option}: expected an integer, got {raw!r}"
        ) from exc


def _get_bool(parser: configparser.ConfigParser, section: str, option: str,
              fallback: bool) -> bool:
    raw = _get(parser, section, option, "true" if fallback else "false").lower()
    if raw in {"1", "yes", "true", "on"}:
        return True
    if raw in {"0", "no", "false", "off"}:
        return False
    raise ConfigError(
        f"[{section}] {option}: expected true/false, got {raw!r}"
    )


def _get_list(parser: configparser.ConfigParser, section: str,
              option: str) -> List[str]:
    raw = _get(parser, section, option, "")
    if not raw:
        return []
    return [part for part in re.split(r"[,\s]+", raw) if part]


def load_config(path: Optional[Path] = None, *, create: bool = True,
                force_create: bool = False) -> Config:
    """Load the INI configuration, creating a template when needed."""
    path = (Path(path) if path else default_config_path()).expanduser()
    created = ensure_config(path, force=force_create) if create else False
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    if not path.is_file():
        raise ConfigError(f"Config path is not a file: {path}")

    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, UnicodeError, configparser.Error) as exc:
        raise ConfigError(f"Cannot read config {path}: {exc}") from exc

    client_id = _get(parser, "discord", "client_id", "")
    if client_id and not client_id.isdigit():
        raise ConfigError(
            "[discord] client_id must be the numeric Application ID "
            "from https://discord.com/developers/applications"
        )

    ipc_path = _get(parser, "discord", "ipc_path", "") or None
    if ipc_path:
        ipc_path = str(Path(ipc_path).expanduser())

    poll_interval = _get_float(parser, "presence", "poll_interval", 1.0)
    if not 0.2 <= poll_interval <= 30.0:
        raise ConfigError("[presence] poll_interval must be between 0.2 and 30")

    reconnect_interval = _get_float(parser, "discord", "reconnect_interval", 10.0)
    if not 1.0 <= reconnect_interval <= 600.0:
        raise ConfigError(
            "[discord] reconnect_interval must be between 1 and 600"
        )

    min_update_interval = _get_float(
        parser, "presence", "min_update_interval", 2.0
    )
    if not 0.0 <= min_update_interval <= 60.0:
        raise ConfigError(
            "[presence] min_update_interval must be between 0 and 60"
        )

    log_level = _get(parser, "logging", "level", "info").lower()
    if log_level not in LOG_LEVELS:
        raise ConfigError(
            f"[logging] level must be one of: {', '.join(sorted(LOG_LEVELS))}"
        )

    artwork_enabled = _get_bool(parser, "artwork", "enabled", True)
    artwork_provider = _get(parser, "artwork", "provider", "auto").lower()
    if artwork_provider not in ARTWORK_PROVIDERS:
        raise ConfigError(
            "[artwork] provider must be one of: "
            + ", ".join(sorted(ARTWORK_PROVIDERS))
        )
    if not artwork_enabled:
        artwork_provider = "none"

    return Config(
        path=path,
        created=created,
        client_id=client_id,
        ipc_path=ipc_path,
        reconnect_interval=reconnect_interval,
        poll_interval=poll_interval,
        show_paused=_get_bool(parser, "presence", "show_paused", True),
        clear_when_stopped=_get_bool(
            parser, "presence", "clear_when_stopped", True
        ),
        clear_on_exit=_get_bool(parser, "presence", "clear_on_exit", True),
        paused_text=_get(parser, "presence", "paused_text", "⏸ Пауза"),
        fallback_state=_get(
            parser, "presence", "fallback_state", "Неизвестный исполнитель"
        ),
        details_format=_get(parser, "presence", "details_format", "{title}")
        or "{title}",
        state_format=_get(
            parser, "presence", "state_format", "{artist} — {album}"
        )
        or "{artist} — {album}",
        show_progress=_get_bool(parser, "presence", "show_progress", True),
        button_label=_get(
            parser, "presence", "button_label", "Открыть трек"
        ),
        min_update_interval=min_update_interval,
        priority_players=_get_list(parser, "players", "priority_players"),
        ignore_players=_get_list(parser, "players", "ignore_players"),
        artwork_enabled=artwork_enabled,
        artwork_provider=artwork_provider,
        fallback_image=_get(parser, "artwork", "fallback_image", ""),
        playing_image=_get(parser, "artwork", "playing_image", ""),
        paused_image=_get(parser, "artwork", "paused_image", ""),
        log_level=log_level,
    )

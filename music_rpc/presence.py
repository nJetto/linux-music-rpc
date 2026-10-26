"""Build Discord Rich Presence activity objects from MPRIS metadata."""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .artwork import ArtworkResolver, is_http_url
from .config import Config
from .mpris import Track, display_player_name


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def utf16_len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def truncate(value: str, limit: int) -> str:
    """Truncate to Discord's UTF-16 code-unit limit."""
    value = value.strip()
    if limit <= 0:
        return ""
    if utf16_len(value) <= limit:
        return value
    if limit == 1:
        return "…"
    result = []
    used = 0
    for character in value:
        width = 2 if ord(character) > 0xFFFF else 1
        if used + width > limit - 1:
            break
        result.append(character)
        used += width
    return "".join(result).rstrip() + "…"


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _clean_template_result(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    # Remove separators that became orphaned because a field was empty.
    value = re.sub(r"^[\s—–•|,;\-]+", "", value)
    value = re.sub(r"[\s—–•|,;\-]+$", "", value)
    value = re.sub(r"(\s*[—–•|]\s*){2,}", " — ", value)
    return value.strip()


def render_template(template: str, track: Track) -> str:
    values = {
        "title": track.title,
        "artist": track.artist_text,
        "album": track.album,
        "player": display_player_name(track.player),
        "player_raw": track.player,
        "status": track.status,
        "duration": format_duration(track.length_seconds),
        "position": format_duration(track.position_seconds),
    }
    try:
        rendered = template.format_map(_SafeDict(values))
    except (KeyError, ValueError, IndexError):
        # A malformed custom template should not take down the app.
        rendered = template
    return _clean_template_result(rendered)


def valid_track_url(url: str) -> bool:
    if not is_http_url(url):
        return False
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    # Firefox often exposes only https://www.youtube.com/ for a video.
    # A link to the site root is not useful as a "track" button.
    if parsed.path in {"", "/"} and not parsed.query:
        return False
    return True


@dataclass
class _Timing:
    key: Tuple
    start: int
    end: Optional[int]


class PresenceBuilder:
    def __init__(self, config: Config, artwork: ArtworkResolver):
        self.config = config
        self.artwork = artwork
        self._timing: Optional[_Timing] = None

    def build(self, track: Track, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now

        details = render_template(self.config.details_format, track)
        state = render_template(self.config.state_format, track)
        if not details:
            details = track.title or self.config.fallback_state or "Unknown track"
        if not state:
            state = (
                track.artist_text
                or track.album
                or self.config.fallback_state
                or "Unknown artist"
            )

        if track.is_paused and self.config.paused_text:
            state = f"{self.config.paused_text} • {state}"

        details = truncate(details, 128)
        state = truncate(state, 128)

        activity: Dict[str, object] = {
            "type": 2,  # ActivityType.LISTENING
            "status_display_type": 2,  # show the track title in the member list
            "details": details,
            "state": state,
            "instance": False,
        }

        track_url = track.url if valid_track_url(track.url) else ""
        if track_url:
            activity["details_url"] = track_url[:512]

        timestamps = self._timestamps(track, now)
        if timestamps:
            activity["timestamps"] = timestamps

        artwork_url = self.artwork.get(track)
        large_image = artwork_url or self.config.fallback_image.strip()
        assets: Dict[str, str] = {}
        if large_image:
            assets["large_image"] = large_image[:512]
            large_text = track.album or track.title or "Music"
            assets["large_text"] = truncate(large_text, 128)
        small_image = (
            self.config.playing_image if track.is_playing else self.config.paused_image
        ).strip()
        if small_image:
            assets["small_image"] = small_image
            assets["small_text"] = "Playing" if track.is_playing else "Paused"
        if assets:
            activity["assets"] = assets

        if track_url and self.config.button_label.strip():
            label = truncate(self.config.button_label, 32)
            if label:
                activity["buttons"] = [{"label": label, "url": track_url[:512]}]

        return activity

    def _timestamps(self, track: Track, now: float) -> Dict[str, int]:
        if not self.config.show_progress or not track.is_playing:
            self._timing = None
            return {}

        length = track.length_seconds
        position = track.position_seconds
        if length > 0:
            position = min(position, length)

        timing = self._timing
        if timing is not None and timing.key == track.key:
            expected = now - timing.start
            # A position of zero often means the player doesn't implement the
            # MPRIS Position property. Don't fight it; wall-clock progress is
            # still correct. A real seek produces a non-zero jump.
            if track.position_us > 0 and abs(position - expected) > 5.0:
                timing = None
        else:
            timing = None

        if timing is None:
            start = int(now - position)
            end = int(start + length) if length > 0 else None
            if end is not None and end <= start:
                end = None
            timing = _Timing(key=track.key, start=start, end=end)
            self._timing = timing

        result = {"start": timing.start}
        if timing.end is not None:
            result["end"] = timing.end
        return result

    def reset(self) -> None:
        self._timing = None


def activity_signature(activity: Optional[dict]) -> str:
    if activity is None:
        return "null"
    return json.dumps(
        activity, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )

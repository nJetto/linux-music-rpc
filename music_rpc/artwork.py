"""Album artwork resolution.

Two sources are supported:

* a direct ``http(s)`` URL from MPRIS (Spotify, Yandex Music, some players);
* the public iTunes Search API, used when a player only exposes local
  ``file://`` artwork (Chromium/Firefox) or no artwork at all.

Discord accepts an external URL in the **large** image asset field. Only the
large image supports URLs, therefore small playing/paused icons must be
uploaded as regular assets to the Discord application.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import APP_NAME, __version__
from .config import Config, cache_home
from .mpris import Track

LOGGER = logging.getLogger(__name__)

ITUNES_URL = "https://itunes.apple.com/search"
USER_AGENT = f"{APP_NAME}/{__version__} (Linux; MPRIS-to-Discord-RPC)"
MAX_CACHE_ENTRIES = 500
FAILURE_TTL = 600.0


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+", value))


def cache_key(track: Track) -> str:
    return "\x1f".join(
        (
            _norm(track.title),
            _norm(track.artist_text),
            _norm(track.album),
        )
    )


def is_http_url(value: str) -> bool:
    if not value or len(value) > 512:
        return False
    try:
        parsed = urllib.parse.urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def apple_artwork_url(result: dict) -> Optional[str]:
    raw = (
        result.get("artworkUrl600")
        or result.get("artworkUrl100")
        or result.get("artworkUrl60")
        or result.get("artworkUrl30")
    )
    if not isinstance(raw, str):
        return None
    # Apple's image CDN accepts any of the documented sizes.
    raw = re.sub(r"/\d+x\d+bb", "/600x600bb", raw)
    return raw if is_http_url(raw) else None


def choose_itunes_result(results: list, track: Track) -> Optional[dict]:
    """Pick the result that best matches the MPRIS metadata."""
    title = _norm(track.title)
    artist = _norm(track.artist_text)
    album = _norm(track.album)
    if not title:
        return None

    best: Optional[dict] = None
    best_score = -1
    for result in results:
        if not isinstance(result, dict):
            continue
        item_title = _norm(str(result.get("trackName", "")))
        item_artist = _norm(str(result.get("artistName", "")))
        item_album = _norm(str(result.get("collectionName", "")))
        if not item_title:
            continue

        score = 0
        if item_title == title:
            score += 5
        elif title in item_title or item_title in title:
            score += 2
        else:
            continue

        if artist:
            if item_artist == artist:
                score += 4
            elif artist in item_artist or item_artist in artist:
                score += 1

        if album:
            if item_album == album:
                score += 3
            elif album in item_album or item_album in album:
                score += 1

        if score > best_score:
            best_score = score
            best = result

    return best if best_score >= 4 else None


class ArtworkResolver:
    """Threaded artwork lookup with an on-disk URL cache."""

    def __init__(self, config: Config, cache_file: Optional[Path] = None):
        self.enabled = config.artwork_active
        self.provider = config.artwork_provider
        self.cache_file = (
            cache_file
            if cache_file
            else cache_home() / APP_NAME / "artwork.json"
        )
        self._lock = threading.Lock()
        self._save_lock = threading.Lock()
        self._cache: Dict[str, dict] = {}
        self._failed: Dict[str, float] = {}
        self._pending = set()
        self._queue: "queue.Queue[Optional[Tuple[str, Track]]]" = queue.Queue(
            maxsize=16
        )
        self._closed = False
        self._thread: Optional[threading.Thread] = None

        if self.enabled and self.provider in {"auto", "itunes"}:
            self._load_cache()
            self._thread = threading.Thread(
                target=self._worker,
                name="artwork-lookup",
                daemon=True,
            )
            self._thread.start()

    def _load_cache(self) -> None:
        try:
            raw = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        entries = raw.get("entries", raw) if isinstance(raw, dict) else {}
        if not isinstance(entries, dict):
            return
        now = time.time()
        for key, value in entries.items():
            if isinstance(value, str):
                value = {"url": value, "ts": now}
            if not isinstance(value, dict):
                continue
            url = value.get("url")
            if isinstance(url, str) and is_http_url(url):
                self._cache[key] = {
                    "url": url,
                    "ts": float(value.get("ts", now)),
                }
        self._prune_locked()

    def _prune_locked(self) -> None:
        if len(self._cache) <= MAX_CACHE_ENTRIES:
            return
        ordered = sorted(
            self._cache.items(), key=lambda item: item[1].get("ts", 0.0)
        )
        for key, _ in ordered[: len(self._cache) - MAX_CACHE_ENTRIES]:
            self._cache.pop(key, None)

    def _save_cache(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with self._save_lock:
                temp = self.cache_file.with_suffix(".tmp")
                with self._lock:
                    payload = {"version": 1, "entries": dict(self._cache)}
                temp.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                try:
                    temp.chmod(0o600)
                except OSError:
                    pass
                os.replace(str(temp), str(self.cache_file))
        except OSError as exc:
            LOGGER.debug("Could not save artwork cache: %s", exc)

    def _cached(self, key: str) -> Optional[str]:
        with self._lock:
            entry = self._cache.get(key)
        if not entry:
            return None
        url = entry.get("url")
        return url if isinstance(url, str) and is_http_url(url) else None

    def _remember(self, key: str, url: str) -> None:
        with self._lock:
            self._cache[key] = {"url": url, "ts": time.time()}
            self._failed.pop(key, None)
            self._prune_locked()
        self._save_cache()

    def get(self, track: Track) -> Optional[str]:
        """Return artwork immediately; schedule a lookup when needed."""
        if not self.enabled:
            return None

        direct = track.art_url if is_http_url(track.art_url) else None
        if self.provider == "direct":
            return direct
        if self.provider == "auto" and direct:
            return direct

        key = cache_key(track)
        cached = self._cached(key)
        if cached:
            return cached

        with self._lock:
            failed_at = self._failed.get(key)
            if failed_at is not None and time.time() - failed_at < FAILURE_TTL:
                return None
            if key in self._pending:
                return None
            self._pending.add(key)
        try:
            self._queue.put_nowait((key, track))
        except queue.Full:
            with self._lock:
                self._pending.discard(key)
        return None

    def resolve_now(self, track: Track) -> Optional[str]:
        """Synchronous lookup, used by ``--once`` and diagnostics."""
        if not self.enabled:
            return None

        direct = track.art_url if is_http_url(track.art_url) else None
        if self.provider == "direct":
            return direct
        if self.provider == "auto" and direct:
            return direct

        key = cache_key(track)
        cached = self._cached(key)
        if cached:
            return cached
        try:
            url = self._lookup(track)
        except Exception as exc:  # network errors must never stop playback
            LOGGER.debug("Artwork lookup failed: %s", exc)
            url = None
        if url:
            self._remember(key, url)
        else:
            with self._lock:
                self._failed[key] = time.time()
        return url

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            key, track = item
            url = None
            try:
                url = self._lookup(track)
            except Exception as exc:
                LOGGER.debug("Artwork lookup failed: %s", exc)
            if url:
                self._remember(key, url)
            else:
                with self._lock:
                    self._failed[key] = time.time()
            with self._lock:
                self._pending.discard(key)

    def _lookup(self, track: Track) -> Optional[str]:
        if self.provider not in {"auto", "itunes"}:
            return None
        if not track.title:
            return None

        terms = [track.artist_text, track.title, track.album]
        query = " ".join(part for part in terms if part)
        params = urllib.parse.urlencode(
            {
                "term": query,
                "media": "music",
                "entity": "song",
                "limit": 8,
            }
        )
        request = urllib.request.Request(
            f"{ITUNES_URL}?{params}",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": "en",
            },
        )
        with urllib.request.urlopen(request, timeout=4.0) as response:
            raw = response.read(512 * 1024)
        payload = json.loads(raw.decode("utf-8"))
        results = payload.get("results", [])
        if not isinstance(results, list):
            return None
        result = choose_itunes_result(results, track)
        return apple_artwork_url(result) if result else None

    def close(self) -> None:
        self._closed = True
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

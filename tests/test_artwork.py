from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from music_rpc.artwork import (
    ArtworkResolver,
    apple_artwork_url,
    cache_key,
    choose_itunes_result,
    is_http_url,
)
from music_rpc.config import Config
from music_rpc.mpris import Track


def make_track(**overrides):
    values = dict(
        player="spotify.instance1",
        status="playing",
        title="Death by Cup",
        artists=("Mom Jeans.",),
        album="Bear Market",
        length_us=200_000_000,
        art_url="",
        position_us=0,
        url="",
    )
    values.update(overrides)
    return Track(**values)


class ArtworkTests(unittest.TestCase):
    def test_http_url_validation(self):
        self.assertTrue(is_http_url("https://example.com/a.jpg"))
        self.assertTrue(is_http_url("http://example.com/a.jpg"))
        self.assertFalse(is_http_url("file:///tmp/a.jpg"))
        self.assertFalse(is_http_url(""))

    def test_apple_url_size(self):
        result = {
            "artworkUrl100": "https://cdn.example.com/a/100x100bb.jpg"
        }
        self.assertEqual(
            apple_artwork_url(result),
            "https://cdn.example.com/a/600x600bb.jpg",
        )

    def test_choose_itunes_result(self):
        results = [
            {
                "trackName": "Death by Cup",
                "artistName": "Mom Jeans.",
                "collectionName": "Bear Market",
                "artworkUrl100": "https://example.com/right.jpg",
            },
            {
                "trackName": "Death by Cup (Live)",
                "artistName": "Someone Else",
                "collectionName": "Other",
                "artworkUrl100": "https://example.com/wrong.jpg",
            },
        ]
        chosen = choose_itunes_result(results, make_track())
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["artworkUrl100"], "https://example.com/right.jpg")

    def test_choose_ignores_unrelated(self):
        results = [
            {
                "trackName": "Completely Different",
                "artistName": "Nobody",
                "collectionName": "Nowhere",
                "artworkUrl100": "https://example.com/wrong.jpg",
            }
        ]
        self.assertIsNone(choose_itunes_result(results, make_track()))

    def test_cache_key_normalizes(self):
        self.assertEqual(
            cache_key(make_track(title="  Death   by Cup ")),
            cache_key(make_track(title="death by cup")),
        )

    def test_direct_provider(self):
        config = Config(
            path=Path("/tmp/test.ini"),
            artwork_enabled=True,
            artwork_provider="direct",
        )
        resolver = ArtworkResolver(config, cache_file=Path("/tmp/no-cache.json"))
        track = make_track(art_url="https://example.com/cover.jpg")
        self.assertEqual(resolver.get(track), "https://example.com/cover.jpg")
        resolver.close()

    def test_disabled_provider(self):
        config = Config(
            path=Path("/tmp/test.ini"),
            artwork_enabled=False,
            artwork_provider="none",
        )
        resolver = ArtworkResolver(config, cache_file=Path("/tmp/no-cache.json"))
        self.assertIsNone(resolver.get(make_track(art_url="https://example.com/a.jpg")))
        resolver.close()

    def test_manual_cache(self):
        config = Config(
            path=Path("/tmp/test.ini"),
            artwork_enabled=True,
            artwork_provider="auto",
        )
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "artwork.json"
            resolver = ArtworkResolver(config, cache_file=cache)
            resolver._remember(cache_key(make_track()), "https://example.com/a.jpg")
            self.assertTrue(cache.exists())
            second = ArtworkResolver(config, cache_file=cache)
            self.assertEqual(
                second.get(make_track()), "https://example.com/a.jpg"
            )
            second.close()
            resolver.close()


if __name__ == "__main__":
    unittest.main()

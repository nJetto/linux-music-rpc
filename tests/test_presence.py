from __future__ import annotations

import dataclasses
import unittest
from pathlib import Path

from music_rpc.artwork import ArtworkResolver
from music_rpc.config import Config
from music_rpc.mpris import Track
from music_rpc.presence import (
    PresenceBuilder,
    activity_signature,
    format_duration,
    truncate,
    valid_track_url,
)


def make_config(**overrides):
    values = dict(
        path=Path("/tmp/linux-music-rpc-test.ini"),
        artwork_enabled=False,
        artwork_provider="none",
        fallback_image="music",
        playing_image="play",
        paused_image="pause",
        button_label="Open track",
        state_format="{artist} — {album}",
        details_format="{title}",
    )
    values.update(overrides)
    return Config(**values)


def make_track(**overrides):
    values = dict(
        player="spotify.instance1",
        status="playing",
        title="Song",
        artists=("Artist",),
        album="Album",
        length_us=200_000_000,
        art_url="",
        position_us=10_000_000,
        url="https://open.spotify.com/track/1",
    )
    values.update(overrides)
    return Track(**values)


class PresenceTests(unittest.TestCase):
    def builder(self, config=None, track=None):
        config = config or make_config()
        return PresenceBuilder(config, ArtworkResolver(config))

    def test_playing_activity(self):
        activity = self.builder().build(make_track(), now=1000.0)
        self.assertEqual(activity["type"], 2)
        self.assertEqual(activity["status_display_type"], 2)
        self.assertEqual(activity["details"], "Song")
        self.assertEqual(activity["state"], "Artist — Album")
        self.assertEqual(activity["timestamps"], {"start": 990, "end": 1190})
        self.assertEqual(activity["assets"]["small_image"], "play")
        self.assertEqual(activity["buttons"][0]["url"], "https://open.spotify.com/track/1")
        self.assertEqual(activity["details_url"], "https://open.spotify.com/track/1")

    def test_paused_activity_has_no_progress(self):
        activity = self.builder().build(
            make_track(status="paused"), now=1000.0
        )
        self.assertNotIn("timestamps", activity)
        self.assertTrue(activity["state"].startswith("⏸ Пауза"))
        self.assertEqual(activity["assets"]["small_image"], "pause")

    def test_same_track_keeps_timestamps(self):
        builder = self.builder()
        first = builder.build(make_track(), now=1000.0)
        second = builder.build(
            dataclasses.replace(make_track(), position_us=11_000_000),
            now=1001.0,
        )
        self.assertEqual(first["timestamps"], second["timestamps"])

    def test_seek_resets_timestamps(self):
        builder = self.builder()
        builder.build(make_track(), now=1000.0)
        after_seek = builder.build(
            dataclasses.replace(make_track(), position_us=50_000_000),
            now=1001.0,
        )
        self.assertEqual(after_seek["timestamps"]["start"], 951)

    def test_zero_position_is_not_treated_as_seek(self):
        builder = self.builder()
        first = builder.build(
            dataclasses.replace(make_track(), position_us=0), now=1000.0
        )
        second = builder.build(
            dataclasses.replace(make_track(), position_us=0), now=1010.0
        )
        self.assertEqual(first["timestamps"], second["timestamps"])

    def test_unknown_length_has_start_only(self):
        activity = self.builder().build(
            make_track(length_us=0), now=1000.0
        )
        self.assertEqual(activity["timestamps"], {"start": 990})

    def test_paused_text_can_be_empty(self):
        config = make_config(paused_text="")
        activity = self.builder(config).build(
            make_track(status="paused"), now=1000.0
        )
        self.assertEqual(activity["state"], "Artist — Album")

    def test_external_artwork_only_uses_large_image(self):
        config = make_config(artwork_enabled=True, artwork_provider="direct")
        track = make_track(art_url="https://example.com/cover.jpg")
        activity = self.builder(config).build(track, now=1000.0)
        self.assertEqual(
            activity["assets"]["large_image"], "https://example.com/cover.jpg"
        )
        self.assertEqual(activity["assets"]["small_image"], "play")

    def test_fallback_image_when_no_artwork(self):
        activity = self.builder().build(make_track(), now=1000.0)
        self.assertEqual(activity["assets"]["large_image"], "music")

    def test_root_url_has_no_button(self):
        activity = self.builder().build(
            make_track(url="https://www.youtube.com/"), now=1000.0
        )
        self.assertNotIn("buttons", activity)
        self.assertNotIn("details_url", activity)

    def test_local_file_url_has_no_button(self):
        self.assertFalse(valid_track_url("file:///tmp/song.flac"))

    def test_empty_metadata_falls_back(self):
        activity = self.builder().build(
            make_track(title="", artists=(), album=""), now=1000.0
        )
        self.assertEqual(activity["details"], "Неизвестный исполнитель")
        self.assertEqual(activity["state"], "Неизвестный исполнитель")

    def test_truncation(self):
        value = "x" * 200
        self.assertLessEqual(len(truncate(value, 128)), 128)
        self.assertTrue(truncate(value, 128).endswith("…"))
        # Astral characters take two UTF-16 code units.
        self.assertEqual(truncate("😀" * 100, 10), "😀😀😀😀…")

    def test_format_duration(self):
        self.assertEqual(format_duration(0), "0:00")
        self.assertEqual(format_duration(59), "0:59")
        self.assertEqual(format_duration(61), "1:01")
        self.assertEqual(format_duration(3661), "1:01:01")

    def test_signature(self):
        builder = self.builder()
        a = builder.build(make_track(), now=1000.0)
        b = builder.build(make_track(), now=1000.0)
        self.assertEqual(activity_signature(a), activity_signature(b))
        c = builder.build(make_track(title="Other"), now=1000.0)
        self.assertNotEqual(activity_signature(a), activity_signature(c))


if __name__ == "__main__":
    unittest.main()

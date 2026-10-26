from __future__ import annotations

import unittest

from music_rpc.mpris import (
    FORMAT,
    SEP,
    Track,
    display_player_name,
    parse_metadata_lines,
    player_matches,
    select_track,
)


def line(
    instance="spotify.instance1",
    name="spotify",
    status="Playing",
    title="Song",
    artist="Artist",
    album="Album",
    length="200000000",
    art="https://example.com/art.jpg",
    position="10000000",
    url="https://open.spotify.com/track/1",
):
    return SEP.join(
        [instance, name, status, title, artist, album, "", length, art, position, url]
    )


def track(
    player="spotify.instance1",
    status="playing",
    title="Song",
    artists=("Artist",),
    album="Album",
    length_us=200_000_000,
    position_us=10_000_000,
    url="https://open.spotify.com/track/1",
):
    return Track(
        player=player,
        status=status,
        title=title,
        artists=artists,
        album=album,
        length_us=length_us,
        art_url="",
        position_us=position_us,
        url=url,
    )


class ParseTests(unittest.TestCase):
    def test_parse_full_line(self):
        tracks = parse_metadata_lines(line())
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].player, "spotify.instance1")
        self.assertEqual(tracks[0].title, "Song")
        self.assertEqual(tracks[0].artists, ("Artist",))
        self.assertEqual(tracks[0].status, "playing")
        self.assertEqual(tracks[0].length_us, 200_000_000)
        self.assertEqual(tracks[0].position_us, 10_000_000)
        self.assertEqual(tracks[0].position_seconds, 10.0)

    def test_artists_are_split_on_semicolon_only(self):
        tracks = parse_metadata_lines(line(artist="A; B, C"))
        self.assertEqual(tracks[0].artists, ("A", "B, C"))
        self.assertEqual(tracks[0].artist_text, "A, B, C")

    def test_player_instance_fallback(self):
        tracks = parse_metadata_lines(line(instance="", name="vlc"))
        self.assertEqual(tracks[0].player, "vlc")

    def test_title_from_file_url(self):
        tracks = parse_metadata_lines(line(title="", url="file:///music/My_Song.flac"))
        self.assertEqual(tracks[0].title, "My Song")

    def test_duplicate_players_are_ignored(self):
        output = line() + "\n" + line(title="Other")
        tracks = parse_metadata_lines(output)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].title, "Song")

    def test_malformed_line_is_ignored(self):
        self.assertEqual(parse_metadata_lines("garbage"), [])
        self.assertEqual(parse_metadata_lines(""), [])

    def test_status_fallback(self):
        tracks = parse_metadata_lines(line(status="Buffering"))
        self.assertEqual(tracks[0].status, "playing")


class MatchingTests(unittest.TestCase):
    def test_prefix_match(self):
        self.assertTrue(player_matches("spotify", "spotify.instance1"))
        self.assertTrue(player_matches("firefox.instance_1_*", "firefox.instance_1_840"))
        self.assertFalse(player_matches("vlc", "spotify.instance1"))

    def test_display_name(self):
        self.assertEqual(display_player_name("chromium.instance123"), "Chromium")
        self.assertEqual(display_player_name("unknown"), "unknown")


class SelectionTests(unittest.TestCase):
    def test_playing_wins_over_paused(self):
        paused = track(player="vlc", status="paused")
        playing = track(player="spotify.instance1", status="playing")
        self.assertEqual(select_track([paused, playing], None, [], True), playing)

    def test_priority_wins(self):
        a = track(player="chromium.instance1", status="playing")
        b = track(player="spotify.instance1", status="playing")
        self.assertEqual(
            select_track([a, b], "chromium.instance1", ["spotify"], True), b
        )

    def test_last_player_is_kept(self):
        a = track(player="chromium.instance1", status="playing")
        b = track(player="spotify.instance1", status="playing")
        self.assertEqual(
            select_track([a, b], "chromium.instance1", [], True), a
        )

    def test_paused_can_be_hidden(self):
        paused = track(status="paused")
        self.assertIsNone(select_track([paused], None, [], False))

    def test_ignored_player_is_skipped(self):
        a = track(player="chromium.instance1", status="playing")
        b = track(player="spotify.instance1", status="playing")
        self.assertEqual(
            select_track([a, b], None, [], True, ["chromium"]), b
        )
        self.assertIsNone(
            select_track([a], "chromium.instance1", [], True, ["chromium*"])
        )

    def test_no_players(self):
        self.assertIsNone(select_track([], None, [], True))


if __name__ == "__main__":
    unittest.main()

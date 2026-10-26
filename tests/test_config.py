from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from music_rpc.config import ConfigError, ensure_config, load_config


SAMPLE = """\
[discord]
client_id = 123456789012345678
ipc_path = ~/custom.sock
reconnect_interval = 5

[presence]
poll_interval = 0.5
show_paused = false
clear_when_stopped = false
clear_on_exit = false
paused_text = PAUSED
fallback_state = Unknown
details_format = {title}
state_format = {artist} — {album}
show_progress = false
button_label =
min_update_interval = 1.5

[players]
priority_players = spotify, chromium
ignore_players = vlc mpv

[artwork]
enabled = false
provider = auto
fallback_image = music
playing_image = play
paused_image = pause

[logging]
level = debug
"""


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "config.ini"

    def tearDown(self):
        self.temp.cleanup()

    def test_read_values(self):
        self.path.write_text(SAMPLE, encoding="utf-8")
        cfg = load_config(self.path, create=False)
        self.assertEqual(cfg.client_id, "123456789012345678")
        self.assertTrue(cfg.ipc_path.endswith("custom.sock"))
        self.assertEqual(cfg.reconnect_interval, 5.0)
        self.assertFalse(cfg.show_paused)
        self.assertFalse(cfg.clear_when_stopped)
        self.assertFalse(cfg.show_progress)
        self.assertEqual(cfg.button_label, "")
        self.assertEqual(cfg.priority_players, ["spotify", "chromium"])
        self.assertEqual(cfg.ignore_players, ["vlc", "mpv"])
        self.assertFalse(cfg.artwork_active)
        self.assertEqual(cfg.artwork_provider, "none")
        self.assertEqual(cfg.log_level, "debug")

    def test_create_from_template(self):
        created = ensure_config(self.path)
        self.assertTrue(created)
        self.assertTrue(self.path.exists())
        cfg = load_config(self.path, create=False)
        self.assertEqual(cfg.client_id, "")
        self.assertEqual(cfg.poll_interval, 1.0)

    def test_ensure_config_does_not_overwrite(self):
        self.path.write_text(SAMPLE, encoding="utf-8")
        self.assertFalse(ensure_config(self.path))
        self.assertIn("123456789012345678", self.path.read_text(encoding="utf-8"))

    def test_invalid_client_id(self):
        self.path.write_text("[discord]\nclient_id = not-a-number\n", encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_config(self.path, create=False)

    def test_invalid_poll_interval(self):
        self.path.write_text("[presence]\npoll_interval = 0.01\n", encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_config(self.path, create=False)

    def test_invalid_bool(self):
        self.path.write_text("[presence]\nshow_paused = maybe\n", encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_config(self.path, create=False)

    def test_invalid_artwork_provider(self):
        self.path.write_text(
            "[artwork]\nprovider = magic\n", encoding="utf-8"
        )
        with self.assertRaises(ConfigError):
            load_config(self.path, create=False)


if __name__ == "__main__":
    unittest.main()

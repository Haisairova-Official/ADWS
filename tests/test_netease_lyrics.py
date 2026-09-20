import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import io
import json

SOURCE = Path(__file__).resolve().parents[1] / "plugins/netease-lyrics/main.py"
spec = importlib.util.spec_from_file_location("lyrics", SOURCE)
lyrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lyrics)


class LyricsTests(unittest.TestCase):
    def setUp(self):
        self.settings = lyrics.SETTINGS.copy()

    def tearDown(self):
        lyrics.SETTINGS = self.settings

    def track(self, **changes):
        result = {"title": "Example", "artists": ["Artist"], "album": "Album",
                  "duration": 120, "status": "Playing", "position": 5}
        return result | changes

    def test_multiple_stamps_offset_blank_and_boundary(self):
        rows = lyrics.parse_lrc("[offset:500]\n[00:01.25][00:04.250]First\n[00:03.00]\n[00:05.0]Last")
        self.assertEqual(rows, [(0.75, "First"), (2.5, ""), (3.75, "First"), (4.5, "Last")])
        self.assertEqual(lyrics.current_line(rows, 0.74)[1], "")
        self.assertEqual(lyrics.current_line(rows, 0.75)[1], "First")
        self.assertEqual(lyrics.current_line(rows, 2.5)[1], "")
        # Seeking backwards must select from the supplied position, not a timer.
        self.assertEqual(lyrics.current_line(rows, 5)[1], "Last")
        self.assertEqual(lyrics.current_line(rows, 1)[1], "First")

    def test_matching_rejects_wrong_artist_version_duration(self):
        song = {"id": 1, "name": "Example", "artists": [{"name": "Artist"}],
                "album": {"name": "Album"}, "duration": 120500}
        for bad in (song | {"name": "Example (instrumental)"},
                    song | {"artists": [{"name": "Other"}]}, song | {"duration": 60000}):
            self.assertIsNone(lyrics.select_song([bad], self.track()))
        self.assertEqual(lyrics.select_song([song], self.track())["id"], 1)

    def test_browser_collapsed_collaboration_artists(self):
        song = {"id": 2, "name": "Example", "artists": [{"name": "Singer A"}, {"name": "Singer B"}],
                "album": {"name": "Album"}, "duration": 120100}
        track = self.track(artists=["Singer A/Singer B"])
        self.assertEqual(lyrics.select_song([song], track)["id"], 2)

    def test_mpris_discovery_supports_chrome_and_filters_by_netease_url(self):
        names = ["org.freedesktop.DBus", "org.mpris.MediaPlayer2.firefox.instance1",
                 "org.mpris.MediaPlayer2.chromium.instance42", "org.mpris.MediaPlayer2.vlc"]
        self.assertEqual(lyrics.mpris_player_names(names), [
            "org.mpris.MediaPlayer2.chromium.instance42",
            "org.mpris.MediaPlayer2.firefox.instance1",
            "org.mpris.MediaPlayer2.vlc",
        ])
        for url in ("https://music.163.com/#/song?id=1",
                    "https://sub.music.163.com/player"):
            self.assertTrue(lyrics.is_netease_url(url))
        for url in ("https://example.com/music.163.com", "https://music.163.com.evil.test/", "not a url", ""):
            self.assertFalse(lyrics.is_netease_url(url))

    def test_other_music_platforms_are_explicitly_opt_in(self):
        spotify = "https://open.spotify.com/track/123"
        youtube_music = "https://music.youtube.com/watch?v=123"
        self.assertFalse(lyrics.is_supported_source("org.mpris.MediaPlayer2.chromium.instance1", spotify))
        self.assertTrue(lyrics.is_supported_source("org.mpris.MediaPlayer2.chromium.instance1", spotify, True))
        self.assertTrue(lyrics.is_supported_source("org.mpris.MediaPlayer2.chromium.instance1", youtube_music, True))
        self.assertTrue(lyrics.is_supported_source("org.mpris.MediaPlayer2.spotify", "spotify:track:123", True))
        self.assertFalse(lyrics.is_supported_source("org.mpris.MediaPlayer2.chromium.instance1",
                                                    "https://www.youtube.com/watch?v=123", True))
        self.assertTrue(lyrics.is_supported_source("org.mpris.MediaPlayer2.firefox.instance1",
                                                   "https://music.163.com/#/song?id=1", False))

    def test_chromium_mpris_snapshot(self):
        player = lyrics.BrowserPlayer.__new__(lyrics.BrowserPlayer)
        player.players = []
        player.refresh_at = 0
        player.GLib = type("GLib", (), {"Error": RuntimeError})
        metadata = {"xesam:url": "https://music.163.com/#/song?id=123",
                    "xesam:title": "Chrome Song", "xesam:artist": ["Singer"],
                    "xesam:album": "Album", "mpris:length": 123_000_000}
        responses = iter([(["org.mpris.MediaPlayer2.chromium.instance42"],),
                          ({"Metadata": metadata, "Position": 5_000_000,
                            "PlaybackStatus": "Playing"},)])
        player.call = lambda *args: next(responses)
        track = player.snapshot()
        self.assertEqual(track["player"], "org.mpris.MediaPlayer2.chromium.instance42")
        self.assertEqual(track["title"], "Chrome Song")
        self.assertEqual(track["position"], 5)

    def test_experimental_spotify_snapshot(self):
        lyrics.SETTINGS = {"experimental_other_platforms": True}
        player = lyrics.BrowserPlayer.__new__(lyrics.BrowserPlayer)
        player.players = []
        player.refresh_at = 0
        player.GLib = type("GLib", (), {"Error": RuntimeError})
        metadata = {"xesam:url": "https://open.spotify.com/track/123",
                    "xesam:title": "Spotify Song", "xesam:artist": ["Singer"],
                    "xesam:album": "Album", "mpris:length": 180_000_000}
        responses = iter([(["org.mpris.MediaPlayer2.spotify"],),
                          ({"Metadata": metadata, "Position": 7_000_000,
                            "PlaybackStatus": "Playing"},)])
        player.call = lambda *args: next(responses)
        self.assertEqual(player.snapshot()["title"], "Spotify Song")

    def test_player_controls_selected_source(self):
        player = lyrics.BrowserPlayer.__new__(lyrics.BrowserPlayer)
        player.GLib = type("GLib", (), {"Error": RuntimeError})
        calls = []
        player.snapshot = lambda: {"player": "org.mpris.MediaPlayer2.chromium.instance42",
                                   "status": "Playing"}
        player.call = lambda *args: calls.append(args)
        self.assertTrue(player.control("play-pause"))
        self.assertEqual(calls[-1][3], "Pause")
        player.snapshot = lambda: {"player": "org.mpris.MediaPlayer2.chromium.instance42",
                                   "status": "Paused"}
        self.assertTrue(player.control("play-pause"))
        self.assertEqual(calls[-1][3], "Play")
        for action, method in (("previous", "Previous"), ("next", "Next")):
            self.assertTrue(player.control(action))
            self.assertEqual(calls[-1][3], method)

    def test_pause_and_translation_and_markup(self):
        data = {"state": "ready", "lines": [(1, "A < B & C")], "translation": [(1, "译文")]}
        result = lyrics.render(self.track(status="Paused"), data)
        self.assertEqual(result["class"], "paused")
        self.assertIn("A &lt; B &amp; C", result["text"])
        self.assertIn("译文", result["tooltip"])
        self.assertEqual(lyrics.render(self.track(position=0), data)["text"], "♫ Example")

    def test_idle_error_and_missing_position(self):
        self.assertEqual(lyrics.render(None, None)["class"], "idle")
        lyrics.SETTINGS = {"experimental_other_platforms": True}
        self.assertEqual(lyrics.render(None, None)["primary"], lyrics._tr("♫ 等待音乐"))
        self.assertIn("Example", lyrics.render(self.track(), {"state": "error"})["text"])
        result = lyrics.render(self.track(position=None), {"state": "ready"})
        self.assertIn(lyrics._tr("浏览器尚未提供播放进度"), result["tooltip"])

    def test_mixed_width_and_controls(self):
        self.assertEqual(lyrics.fit_text("中文abc", 5), "中文a…")
        self.assertEqual(lyrics.fit_text("a\u0301b", 2), "a\u0301b")
        self.assertEqual(lyrics.fit_text("a\x00b", 2), "ab")

    def test_custom_api_json_and_url_encoding(self):
        lyrics.SETTINGS = {"api_mode": "custom", "api_url": "https://example.test/get?title={title}&artist={artist}",
                           "lyric_path": "data.syncedLyrics", "translation_path": "data.translation"}
        response = {"data": {"syncedLyrics": "[00:01]Original", "translation": "[00:01]Translation"}}
        with patch.object(lyrics.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as call:
            result = lyrics.custom_lyrics(self.track(title="A&B"), "")
        self.assertEqual(result, ("[00:01]Original", "[00:01]Translation"))
        self.assertIn("title=A%26B", call.call_args.args[0].full_url)

    def test_custom_plain_lrc_and_cache_separation(self):
        original_key = lyrics.track_key(self.track())
        lyrics.SETTINGS = {"api_mode": "custom", "api_url": "http://127.0.0.1:1234/lyrics?name={title}"}
        self.assertNotEqual(lyrics.track_key(self.track()), original_key)
        with patch.object(lyrics.urllib.request, "urlopen", return_value=io.BytesIO(b"[00:01]Direct")):
            self.assertEqual(lyrics.custom_lyrics(self.track(), ""), ("[00:01]Direct", ""))

    def test_offset_and_invalid_api(self):
        lyrics.SETTINGS = {"offset_ms": 1000}
        result = lyrics.render(self.track(position=0), {"state": "ready", "lines": [(1, "Start")], "translation": []})
        self.assertEqual(result["primary"], "Start")
        lyrics.SETTINGS = {"api_url": "file:///etc/passwd"}
        with self.assertRaises(ValueError):
            lyrics.custom_lyrics(self.track(), "")


if __name__ == "__main__":
    unittest.main()

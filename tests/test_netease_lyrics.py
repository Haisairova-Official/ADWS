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

    def test_seek_checks_track_and_capability_and_clamps(self):
        from unittest.mock import Mock
        from types import SimpleNamespace
        player=object.__new__(lyrics.BrowserPlayer)
        player.GLib=SimpleNamespace(Error=RuntimeError)
        name='org.mpris.MediaPlayer2.firefox.test'
        player.snapshot=Mock(return_value={'track_id':'/track/one','can_seek':True,'duration':180})
        player.call=Mock()
        token=lyrics.playback_token(player.snapshot.return_value)
        self.assertTrue(player.seek(45,name,'/track/one',token))
        self.assertEqual(player.call.call_args.args[-3:],('SetPosition','(ox)',('/track/one',45000000)))
        self.assertTrue(player.seek(999,name,'/track/one',token))
        self.assertEqual(player.call.call_args.args[-1],('/track/one',180000000))
        self.assertTrue(player.seek(-3,name,'/track/one',token))
        self.assertEqual(player.call.call_args.args[-1],('/track/one',0))
        player.call.reset_mock()
        for position,track_id in [(float('nan'),'/track/one'),(1,'/track/stale'),(1,''),(1,'/bad path')]:
            self.assertFalse(player.seek(position,name,track_id,token))
        player.snapshot.return_value['title']='new song, reused track ID'
        self.assertFalse(player.seek(1,name,'/track/one',token))
        player.snapshot.return_value['can_seek']=False
        self.assertFalse(player.seek(1,name,'/track/one',token))
        player.call.assert_not_called()

    def test_furigana_conversion_and_unique_alignment(self):
        self.assertEqual(lyrics.romaji_kana("konnichiwa shin'you gakkou matcha"),'こんにちわしんようがっこうまっちゃ')
        self.assertEqual(lyrics.furigana_runs('君の夢','kimi no yume'),(('君','きみ'),('の',''),('夢','ゆめ')))
        self.assertEqual(lyrics.furigana_runs('世界は美しい','sekai wa utsukushii'),(('世界','せかい'),('は',''),('美','うつく'),('し',''),('い','')))
        self.assertEqual(lyrics.furigana_runs('信じて','shinjite'),(('信','しん'),('じ',''),('て','')))
        self.assertEqual(lyrics.furigana_runs('空へ！','sora e!'),(('空','そら'),('へ',''),('！','')))
        # Two possible placements of the kana anchor: do not invent a reading.
        self.assertEqual(lyrics.furigana_runs('君の夢','ki no mi no yume'),())
        for text,roman in [('君の夢','not matching'),('君の夢',''),('abc','abc'),('君'*201,'kimi')]:
            self.assertEqual(lyrics.furigana_runs(text,roman),())

    def test_furigana_independent_switch_and_pause(self):
        data={'state':'ready','lines':[(1,'君の夢')],'romanization':[(1,'kimi no yume')]}
        lyrics.SETTINGS={'show_furigana':True,'show_romanization':False}
        value=lyrics.render(self.track(status='Paused'),data)
        self.assertEqual(value['romanization'],'')
        self.assertEqual(value['ruby'][1],{'base':'君','reading':'きみ'})
        self.assertEqual(''.join(r['base'] for r in value['ruby']),value['primary'])
        lyrics.SETTINGS={'show_furigana':False,'show_romanization':True}
        self.assertEqual(lyrics.render(self.track(),data)['ruby'],[])
        self.assertEqual(lyrics.render(self.track(),data)['romanization'],'kimi no yume')
        lyrics.SETTINGS={'show_furigana':True}
        self.assertEqual(lyrics.render(self.track(),{**data,'romanization':[]})['ruby'],[])

    def fallback_fixture(self):
        track=self.track(title='夢の歌',artists=['歌手'])
        original=[(1,'君の夢'),(5,'空へ歩こう'),(10,'世界は美しい')]
        record={'id':123,'trackName':'夢の歌 (Romanized)','artistName':'歌手','duration':120,
                'syncedLyrics':'[00:01.2]kimi no yume\n[00:05]sora e arukou\n[00:10]sekai wa utsukushii'}
        return track,original,record

    def test_fallback_accepts_verified_readings_and_preserves_original_timing(self):
        track,original,record=self.fallback_fixture()
        rows,identity=lyrics.lrclib_romanization([record],track,original)
        self.assertEqual(identity,123);self.assertEqual([r[0] for r in rows],[1,5,10])
        for changes in ({'artistName':'Another singer'},{'trackName':'夢の歌 (Live)'},
                        {'duration':130},{'duration':None},{'duration':float('nan')},
                        {'syncedLyrics':'[00:01]This is English text'},
                        {'syncedLyrics':record['syncedLyrics'].replace('00:','01:')}):
            self.assertEqual(lyrics.lrclib_romanization([{**record,**changes}],track,original),([],None))
        self.assertEqual(lyrics.lrclib_romanization([record],{**track,'duration':0},original),([],None))

    def test_fallback_cache_upgrade_negative_cache_and_disable(self):
        import tempfile,time
        track,original,record=self.fallback_fixture()
        lyrics.SETTINGS={'show_furigana':True}
        initial={'state':'ready','lines':original,'translation':[(1,'translation')],
                 'romanization':[],'romanization_schema':2,'expires':time.time()+3600}
        with tempfile.TemporaryDirectory() as folder,patch.object(lyrics,'CACHE',Path(folder)):
            cache=Path(folder)/(lyrics.track_key(track)+'.json');cache.write_text(json.dumps(initial))
            with patch.object(lyrics,'request_lrclib',return_value=[record]) as provider:
                self.assertFalse(lyrics.fetch_lyrics(track,False)['romanization']);provider.assert_not_called()
                result=lyrics.fetch_lyrics(track);self.assertEqual(provider.call_count,1)
                self.assertEqual(result['romanization_source'],'LRCLIB')
                self.assertEqual(result['lines'],json.loads(json.dumps(original)))
                self.assertEqual(result['translation'],[[1,'translation']])
                lyrics.fetch_lyrics(track);self.assertEqual(provider.call_count,1)
            cache.write_text(json.dumps(initial))
            with patch.object(lyrics,'request_lrclib',return_value=[]) as provider:
                lyrics.fetch_lyrics(track);lyrics.fetch_lyrics(track);self.assertEqual(provider.call_count,2)
            cache.write_text(json.dumps(initial))
            with patch.object(lyrics,'request_lrclib',side_effect=TimeoutError) as provider:
                result=lyrics.fetch_lyrics(track);self.assertEqual(result['state'],'ready')
                lyrics.fetch_lyrics(track);self.assertEqual(provider.call_count,1)
                self.assertLess(result['romanization_retry_at']-time.time(),601)
            for settings in ({},{'show_furigana':True,'romanization_fallback':False}):
                lyrics.SETTINGS=settings;cache=Path(folder)/(lyrics.track_key(track)+'.json');cache.write_text(json.dumps(initial))
                with patch.object(lyrics,'request_lrclib') as provider:
                    lyrics.fetch_lyrics(track);provider.assert_not_called()

    def test_stream_displays_primary_before_background_fallback_finishes(self):
        from unittest.mock import MagicMock
        track,original,_=self.fallback_fixture();lyrics.SETTINGS={}
        result={'state':'ready','lines':original,'romanization':[],'expires':10**12}
        base_future=MagicMock();base_future.done.return_value=True;base_future.result.return_value=result
        slow_future=MagicMock();slow_future.done.return_value=False
        primary=MagicMock();primary.submit.return_value=base_future
        fallback=MagicMock();fallback.submit.return_value=slow_future
        output=io.StringIO()
        with patch.object(lyrics,'BrowserPlayer') as player,patch.object(lyrics.concurrent.futures,'ThreadPoolExecutor',side_effect=[primary,fallback]),patch.object(lyrics.time,'sleep',side_effect=KeyboardInterrupt),patch('sys.stdout',output):
            player.return_value.snapshot.return_value=track
            lyrics.main(['--settings-json','{"show_furigana":true}'])
        self.assertEqual(json.loads(output.getvalue())['primary'],'空へ歩こう')
        primary.submit.assert_called_once_with(lyrics.fetch_lyrics,track,False)
        fallback.submit.assert_called_once_with(lyrics.fetch_lyrics,track,True)

    def test_romalrc_field_repairs_previous_empty_cache(self):
        import tempfile,time
        lyrics.SETTINGS={'show_furigana':True}
        with tempfile.TemporaryDirectory() as folder,patch.object(lyrics,'CACHE',Path(folder)):
            track=self.track();cache=Path(folder)/(lyrics.track_key(track)+'.json')
            cache.write_text(json.dumps({'state':'ready','lines':[[1,'君の夢']],'romanization':[],
                                        'romanization_retry_at':time.time()+9999,'expires':time.time()+9999}))
            song={'id':1,'name':'Example','artists':[{'name':'Artist'}],'duration':120000,'album':{'name':'Album'}}
            with patch.object(lyrics,'request_json',side_effect=[{'result':{'songs':[song]}},
                    {'lrc':{'lyric':'[00:01]君の夢'},'romalrc':{'lyric':'[00:01]kimi no yume'}}]),patch.object(lyrics,'request_lrclib') as external:
                value=lyrics.fetch_lyrics(track,False)
                self.assertEqual(value['romanization'],[(1.0,'kimi no yume')])
                self.assertEqual(value['romanization_schema'],2);external.assert_not_called()
            with patch.object(lyrics,'request_json') as request:
                lyrics.fetch_lyrics(track);request.assert_not_called()

    def test_space_between_kanji_keeps_valid_group_reading(self):
        text='朝の光 眩しくて'
        runs=lyrics.furigana_runs(text,'a sa no hi ka ri ma bu shi ku te')
        self.assertEqual(runs,(('朝','あさ'),('の',''),('光 眩','ひかりまぶ'),('し',''),('く',''),('て','')))
        self.assertEqual(''.join(b for b,r in runs),text)
        self.assertEqual(lyrics.furigana_runs('君の夢','ki no mi no yume'),())

    def test_progress_uses_playback_not_lyric_offset(self):
        lyrics.SETTINGS={'show_progress':True,'offset_ms':5000}
        data=lyrics.render(self.track(position=7),None)
        self.assertEqual(data['position'],7);self.assertEqual(data['duration'],120)
        lyrics.SETTINGS={}
        self.assertIsNone(lyrics.render(self.track(position=7),None)['position'])

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

    def test_target_player_and_unsupported_action(self):
        player=lyrics.BrowserPlayer.__new__(lyrics.BrowserPlayer)
        player.GLib=type('GLib',(),{'Error':RuntimeError})
        calls=[];targets=[]
        def snapshot(target=None):
            targets.append(target)
            return {'player':target,'status':'Playing','capabilities':{'next':False,'play-pause':True}}
        player.snapshot=snapshot;player.call=lambda *args:calls.append(args)
        self.assertFalse(player.control('next','org.mpris.MediaPlayer2.selected'))
        self.assertFalse(calls)
        self.assertTrue(player.control('play-pause','org.mpris.MediaPlayer2.selected'))
        self.assertEqual(calls[0][0],'org.mpris.MediaPlayer2.selected')
        self.assertEqual(calls[0][3],'Pause')

    def test_old_cache_refetches_romaji_once_and_reuses_absent_result(self):
        import tempfile,time
        with tempfile.TemporaryDirectory() as folder, patch.object(lyrics,'CACHE',Path(folder)):
            lyrics.SETTINGS={'show_furigana':True}
            cache=Path(folder)/(lyrics.track_key(self.track())+'.json')
            cache.write_text(json.dumps({'expires':time.time()+100,'state':'ready','lines':[[1,'old']],'translation':[]}))
            song={'id':1,'name':'Example','artists':[{'name':'Artist'}],'duration':120000,'album':{'name':'Album'}}
            with patch.object(lyrics,'request_json',side_effect=[{'result':{'songs':[song]}},{'lrc':{'lyric':'[00:01]new'},'rlyric':{'lyric':'[00:01]roman'}}]) as request:
                value=lyrics.fetch_lyrics(self.track())
            self.assertEqual(value['romanization'],[(1.0,'roman')])
            self.assertEqual(request.call_args.args[1]['rv'],-1)
            with patch.object(lyrics,'request_json') as request:
                self.assertEqual(lyrics.fetch_lyrics(self.track())['romanization'],[[1.0,'roman']]);request.assert_not_called()

    def test_desktop_line_switches_and_missing_alignment(self):
        data={'state':'ready','lines':[(1,'one'),(4,'two'),(8,'three')],
              'translation':[(1,'first translation')], 'romanization':[(4.1,'romaji')]}
        lyrics.SETTINGS={'show_translation':True,'show_romanization':True,'show_context':True}
        result=lyrics.render(self.track(position=5),data)
        self.assertEqual((result['previous'],result['primary'],result['next']),('one','two','three'))
        self.assertEqual(result['romanization'],'romaji')
        self.assertEqual(result['secondary'],'','missing translation must not retain previous line')
        lyrics.SETTINGS={'show_translation':False,'show_romanization':False,'show_context':False}
        result=lyrics.render(self.track(position=5),data)
        for key in ('secondary','romanization','previous','next'):self.assertEqual(result[key],'')
        lyrics.SETTINGS={'show_context':True}
        self.assertEqual(lyrics.render(self.track(position=0),data)['next'],'one')
        self.assertEqual(lyrics.render(self.track(position=99),data)['next'],'')

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
        self.assertEqual(result, ("[00:01]Original", "[00:01]Translation", ""))
        self.assertIn("title=A%26B", call.call_args.args[0].full_url)

    def test_custom_plain_lrc_and_cache_separation(self):
        original_key = lyrics.track_key(self.track())
        lyrics.SETTINGS = {"api_mode": "custom", "api_url": "http://127.0.0.1:1234/lyrics?name={title}"}
        self.assertNotEqual(lyrics.track_key(self.track()), original_key)
        with patch.object(lyrics.urllib.request, "urlopen", return_value=io.BytesIO(b"[00:01]Direct")):
            self.assertEqual(lyrics.custom_lyrics(self.track(), ""), ("[00:01]Direct", "", ""))

    def test_offset_and_invalid_api(self):
        lyrics.SETTINGS = {"offset_ms": 1000}
        result = lyrics.render(self.track(position=0), {"state": "ready", "lines": [(1, "Start")], "translation": []})
        self.assertEqual(result["primary"], "Start")
        lyrics.SETTINGS = {"api_url": "file:///etc/passwd"}
        with self.assertRaises(ValueError):
            lyrics.custom_lyrics(self.track(), "")


if __name__ == "__main__":
    unittest.main()

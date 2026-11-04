import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_lyrics_media as media

class MediaTests(unittest.TestCase):
    def test_bounded_frames_and_progress(self):
        self.assertEqual(media.parse_frame(b'1000;'*32),(1.,)*32)
        self.assertEqual(media.parse_frame(b'-1;'*32),(0.,)*32)
        for frame in (b'bad',b'1;',b'1;'*33):self.assertIsNone(media.parse_frame(frame))
        self.assertEqual(media.progress_values(200,100),(100,100))
        self.assertEqual(media.progress_values(-1,100),(0,100))
        for values in ((None,100),(1,0),(float('nan'),100),(1,float('inf'))):self.assertIsNone(media.progress_values(*values))

    def test_shared_sampler_stops_last_subscriber_and_can_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            binpath=Path(directory)
            (binpath/'pactl').write_text('#!/bin/sh\necho test-output\n')
            (binpath/'cava').write_text('#!/usr/bin/python3\nimport time\nwhile True:\n print("500;"*32,flush=True);time.sleep(.02)\n')
            for p in binpath.iterdir():p.chmod(0o755)
            with patch.dict(os.environ,{'PATH':directory+':'+os.environ['PATH']}):
                source=media.SpectrumSource()
                def wait(condition):
                    deadline=time.monotonic()+4
                    while not condition():
                        if time.monotonic()>deadline:self.fail('Spectrum lifecycle timed out')
                        time.sleep(.02)
                try:
                    source.acquire('one');source.acquire('two')
                    wait(lambda:source.snapshot()[0][0]==.5)
                    process=source.process
                    self.assertIsNotNone(process);source.release('one')
                    time.sleep(.1);self.assertIs(source.process,process);self.assertIsNone(process.poll())
                    source.release('two');wait(lambda:process.poll() is not None)
                    source.acquire('three');wait(lambda:source.process is not None and source.process is not process)
                    replacement=source.process;source.close()
                    self.assertIsNotNone(replacement.poll());self.assertFalse(source.thread.is_alive())
                finally:source.close()

@unittest.skipUnless(os.environ.get('DESKTOP_LAYER_GUI_TEST')=='1','requires GTK display')
class SeekInteractionTests(unittest.TestCase):
    def test_drag_refresh_track_change_keyboard_and_cleanup(self):
        import gi
        gi.require_version('Gtk','3.0')
        from gi.repository import Gtk,GLib
        from types import SimpleNamespace
        calls=[]
        widget=media.media_widget({'show_spectrum':False},lambda *args:calls.append(args) or True)
        payload={'position':10,'duration':100,'player':'org.mpris.MediaPlayer2.test',
                 'track_id':'/track/reused','track_token':'song-one','can_seek':True}
        event=SimpleNamespace(button=1)
        try:
            widget.update(payload);self.assertTrue(widget.progress.get_sensitive())
            widget.press(widget.progress,event);widget.progress.set_value(.6)
            widget.update(dict(payload,position=11))
            self.assertEqual(widget.progress.get_value(),.6)
            self.assertEqual(widget.elapsed.get_text(),'1:00')
            self.assertFalse(calls)
            widget.release(widget.progress,event)
            self.assertEqual(calls,[(60.,payload['player'],'/track/reused','song-one')])
            widget.seek_finished(False)
            self.assertEqual(widget.progress.get_value(),.11)
            widget.press(widget.progress,event);widget.progress.set_value(.8)
            widget.update(dict(payload,track_token='song-two'))
            widget.progress.set_value(.9);widget.release(widget.progress,event)
            self.assertEqual(len(calls),1,'reused track IDs must not bypass stale drag checks')
            self.assertEqual(widget.seek_timer,0)
            widget.update(dict(payload,can_seek=False));self.assertFalse(widget.progress.get_sensitive())
            widget.update(payload);widget.progress.set_value(.4)
            self.assertNotEqual(widget.seek_timer,0)
            deadline=time.monotonic()+1
            while widget.seek_timer and time.monotonic()<deadline:
                GLib.MainContext.default().iteration(False);time.sleep(.01)
            self.assertEqual(calls[-1][0],40.)
            widget.progress.set_value(.5);widget.close()
            self.assertEqual(widget.seek_timer,0)
        finally:widget.destroy()

if __name__=='__main__':unittest.main()

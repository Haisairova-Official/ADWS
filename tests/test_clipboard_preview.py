import os,sys,time,subprocess,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_clipboard as backend
from adws_clipboard_preview import thumbnail,dimensions
from gi.repository import GdkPixbuf, GLib

class ClipboardPreviewTests(unittest.TestCase):
    def decode(self,script,**kwargs):
        spawn=subprocess.Popen
        with patch.object(backend.subprocess,'Popen',side_effect=lambda args,**kw:spawn([sys.executable,'-c',script],**kw)):
            return backend.preview_data('17\ttest',**kwargs)
    def test_exact_bytes_and_limit(self):
        self.assertEqual(self.decode("import sys; sys.stdout.buffer.write(b'a\\x00b')"),b'a\x00b')
        with self.assertRaises(ValueError):self.decode("import sys; sys.stdout.write('x'*10000)",limit=100)
    def test_timeout_and_exit_after_stdout_closes(self):
        for script in ('import time;time.sleep(5)','import os,time;os.close(1);time.sleep(5)'):
            start=time.monotonic()
            with self.assertRaises(TimeoutError):self.decode(script,timeout=.1)
            self.assertLess(time.monotonic()-start,1)
    def test_cancellation_during_decode(self):
        for script in ('import time;time.sleep(5)','import os,time;os.close(1);time.sleep(5)'):
            stop=threading.Event();timer=threading.Timer(.08,stop.set);timer.start()
            try:
                start=time.monotonic();self.assertEqual(self.decode(script,cancelled=stop),b'')
                self.assertLess(time.monotonic()-start,1)
            finally:timer.cancel()
    def test_png_and_jpeg_scaled_with_aspect_ratio(self):
        pix=GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB,False,8,1200,600);pix.fill(0x947bcaff)
        for kind in ('png','jpeg'):
            try:success,data=pix.save_to_bufferv(kind,[],[])
            except GLib.Error as exc:
                if 'Operation not permitted' in str(exc):self.skipTest('Image codec sandbox requires the isolated GUI test environment')
                raise
            self.assertTrue(success)
            image=thumbnail(data);self.assertIsNotNone(image)
            self.assertEqual((image.get_width(),image.get_height()),(320,160))
    def test_invalid_and_oversize_images_never_reach_decoder(self):
        header=b'\x89PNG\r\n\x1a\n'+b'\x00\x00\x00\rIHDR'+(100000).to_bytes(4,'big')*2
        with patch('adws_clipboard_preview.GdkPixbuf.PixbufLoader.new_with_type') as create:
            for value in (b'<svg/>',b'GIF89a',header,b'\xff\xd8\xff\xe0\x00\x00'):
                self.assertIsNone(thumbnail(value))
            create.assert_not_called()
    def test_empty_cancelled_decode_never_spawns(self):
        stop=threading.Event();stop.set()
        with patch.object(backend.subprocess,'Popen') as spawn:
            self.assertEqual(backend.preview_data('1\timage',cancelled=stop),b'');spawn.assert_not_called()

if __name__=='__main__':unittest.main()

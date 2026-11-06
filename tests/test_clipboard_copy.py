"""Exercise forked clipboard-owner descriptors without touching a real display."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_clipboard as backend


class ClipboardCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        env=patch.dict(os.environ,{'PATH':str(self.folder)+os.pathsep+os.environ.get('PATH',''),
                                  'ADWS_COPY_TEST_DIR':str(self.folder)})
        env.start();self.addCleanup(env.stop)

    def program(self,body):
        executable=self.folder/'wl-copy'
        executable.write_text('#!'+sys.executable+'\n'+body)
        executable.chmod(0o700)

    @unittest.skipUnless(hasattr(os,'fork'),'Unix descriptor inheritance test')
    def test_forked_owner_does_not_delay_copy_and_receives_exact_binary(self):
        self.program("""import os, pathlib, sys, time
folder=pathlib.Path(os.environ['ADWS_COPY_TEST_DIR'])
folder.joinpath('data').write_bytes(sys.stdin.buffer.read())
child=os.fork()
if child == 0:
    # Keep stdout/stderr open, as the real long-lived Wayland owner does.
    time.sleep(30)
    os._exit(0)
folder.joinpath('child.pid').write_text(str(child))
""")
        payload=b'\x89PNG\r\n\x1a\n\x00exact binary\xff'
        started=time.monotonic()
        try:
            backend.copy_data(payload)
            self.assertLess(time.monotonic()-started,3)
            self.assertEqual((self.folder/'data').read_bytes(),payload)
            os.kill(int((self.folder/'child.pid').read_text()),0)
        finally:
            marker=self.folder/'child.pid'
            if marker.exists():
                try:os.kill(int(marker.read_text()),signal.SIGTERM)
                except ProcessLookupError:pass

    def test_copy_failure_keeps_exit_code_and_stderr(self):
        self.program("import sys\nsys.stdin.buffer.read()\nsys.stderr.write('Wayland display is unavailable\\n')\nsys.exit(7)\n")
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            backend.copy_data(b'text')
        self.assertEqual(raised.exception.returncode,7)
        self.assertIn(b'Wayland display is unavailable',raised.exception.stderr)

    def test_history_decode_failure_never_starts_clipboard_owner(self):
        error=subprocess.CalledProcessError(1,['cliphist','decode'],stderr=b'unknown item')
        with patch.object(backend,'run',side_effect=error),patch.object(backend,'copy_data') as copy:
            with self.assertRaises(subprocess.CalledProcessError):backend.copy_entry('19\tmissing')
            copy.assert_not_called()


if __name__=='__main__':unittest.main()

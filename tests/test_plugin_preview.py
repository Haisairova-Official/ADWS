"""Live preview reads display-only snapshots of the original plugin process."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_plugin_preview as preview

class PreviewTests(unittest.TestCase):
    def test_display_is_bounded_private_and_stale_pid_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'XDG_RUNTIME_DIR':temp}):
            instance='org.Example.Lyrics-二'
            preview.publish({'primary':'🦊'*5000,'secondary':'translation','text':'line','class':'active','tooltip':'secret','settings':{'token':'secret'}},instance)
            path=Path(temp)/'adws/plugin-preview'/preview.filename(instance)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777,0o700)
            data=preview.read()[instance]
            self.assertEqual(len(data['primary']),4096)
            self.assertNotIn('secret',path.read_text())
            data['start']='stale'
            path.write_text(json.dumps(data))
            self.assertEqual(preview.read(),{})

    def test_missing_runtime_is_optional(self):
        with patch.dict(os.environ,{'XDG_RUNTIME_DIR':''}):
            preview.publish({'text':'hello'},'id')
            self.assertEqual(preview.read(),{})

if __name__=='__main__':unittest.main()

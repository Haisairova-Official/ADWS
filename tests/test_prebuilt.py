import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import mnws_prebuilt as prebuilt
from mnws_setup import atomic_install


class PrebuiltTests(unittest.TestCase):
    def test_verified_install_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); folder=root/'prebuilt'; folder.mkdir()
            hashes={}
            for name in prebuilt.NAMES:
                (folder/name).write_bytes(b'test artifact')
                hashes[name]=hashlib.sha256(b'test artifact').hexdigest()
            (folder/'manifest.json').write_text(json.dumps({'sha256':hashes}))
            with patch.object(prebuilt.platform,'freedesktop_os_release',return_value={'ID':'arch'}), patch.object(prebuilt.platform,'machine',return_value='x86_64'):
                confirm=Mock(return_value=True)
                self.assertTrue(prebuilt.install(root,root/'lib',confirm,atomic_install))
                self.assertEqual((root/'lib'/prebuilt.NAMES[0]).read_bytes(),b'test artifact')
                (folder/prebuilt.NAMES[0]).write_bytes(b'bad')
                writer=Mock()
                with self.assertRaises(RuntimeError): prebuilt.install(root,root/'lib',confirm,writer)
                writer.assert_not_called()

    def test_source_install_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(prebuilt.install(Path(directory),Path(directory),Mock(),Mock()))

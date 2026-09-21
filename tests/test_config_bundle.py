import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import adws_config_bundle as bundle


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.root/'config'), 'XDG_STATE_HOME': str(self.root/'state')})
        env.start();self.addCleanup(env.stop)

    def test_roundtrip_backup(self):
        target = bundle.locations()['adws/taskbar-layout.json']
        target.parent.mkdir(parents=True)
        target.write_text('{"options":{"window_animations":true}}')
        archive = self.root/'Config.ad-yml'
        bundle.export_bundle(archive)
        data = bundle.read_bundle(archive)
        target.write_text('{"options":{}}')
        backup = bundle.import_bundle(data)
        self.assertIn('true', target.read_text())
        self.assertEqual((backup/'adws/taskbar-layout.json').read_text(), '{"options":{}}')

    def test_rejects_unknown_paths_aliases_and_duplicate_fields(self):
        archive = self.root/'Config.ad-yml'
        for text in [
            'format: adws-config\nversion: 1\nfiles: {../escape: text}',
            'format: adws-config\nversion: 1\nfiles: &x {a: *x}',
            'format: adws-config\nversion: 1\nversion: 2\nfiles: {}',
            '!!python/object/apply:os.system [echo bad]',
        ]:
            archive.write_text(text)
            with self.assertRaises(ValueError): bundle.read_bundle(archive)

    def test_write_failure_restores_previous_files(self):
        targets = bundle.locations()
        first = targets['adws/setup.json']; first.parent.mkdir(parents=True); first.write_text('{"old":true}')
        write = bundle.atomic_write
        calls = [0]
        def fail_second(path, content):
            calls[0] += 1
            if calls[0] == 2: raise OSError('disk full')
            return write(path, content)
        data = {'files': {'adws/setup.json': '{}', 'adws/taskbar-pins.json': '{}'}}
        with patch.object(bundle, 'atomic_write', side_effect=fail_second):
            with self.assertRaises(OSError): bundle.import_bundle(data)
        self.assertEqual(first.read_text(), '{"old":true}')
        self.assertFalse(targets['adws/taskbar-pins.json'].exists())

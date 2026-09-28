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
        import adws_atomic
        targets = bundle.locations()
        first = targets['adws/setup.json']; first.parent.mkdir(parents=True); first.write_text('{"old":true}')
        replace = adws_atomic.os.replace
        calls = [0]
        def fail_second(source, target):
            calls[0] += 1
            if calls[0] == 2: raise OSError('disk full')
            return replace(source, target)
        data = {'files': {'adws/setup.json': '{}', 'adws/taskbar-pins.json': '{}'}}
        with patch.object(adws_atomic.os, 'replace', side_effect=fail_second):
            with self.assertRaises(OSError): bundle.import_bundle(data)
        self.assertEqual(first.read_text(), '{"old":true}')
        self.assertFalse(targets['adws/taskbar-pins.json'].exists())

    def test_interrupt_rolls_back_linked_files_and_keeps_backup_permissions(self):
        import adws_atomic
        targets=bundle.locations();first=targets['adws/setup.json'];second=targets['adws/taskbar-pins.json']
        first.parent.mkdir(parents=True);actual=self.root/'actual.json';actual.write_text('{"old":true}')
        actual.chmod(0o600);first.symlink_to(actual)
        replace=adws_atomic.os.replace
        def interrupted(source,target):
            if target==second:raise KeyboardInterrupt()
            replace(source,target)
        with patch.object(adws_atomic.os,'replace',side_effect=interrupted),self.assertRaises(KeyboardInterrupt):
            bundle.import_bundle({'files':{'adws/setup.json':'{}','adws/taskbar-pins.json':'{}'}})
        self.assertEqual(actual.read_text(),'{"old":true}')
        self.assertTrue(first.is_symlink());self.assertFalse(second.exists())
        backup=next((self.root/'state/adws/config-backups').glob('import-*/adws/setup.json'))
        self.assertEqual(backup.stat().st_mode & 0o777,0o600)

    def test_config_aliases_are_rejected_without_modifying_target(self):
        targets=bundle.locations();first=targets['adws/setup.json'];second=targets['adws/taskbar-pins.json']
        first.parent.mkdir(parents=True);first.write_text('{"old":true}');second.symlink_to(first)
        with self.assertRaises(ValueError):
            bundle.import_bundle({'files':{'adws/setup.json':'{}','adws/taskbar-pins.json':'{"pins":[]}'}})
        self.assertEqual(first.read_text(),'{"old":true}')

    def test_import_during_update_leaves_config_untouched(self):
        import adws_upgrade
        target=bundle.locations()['adws/setup.json'];target.parent.mkdir(parents=True);target.write_text('{"old":true}')
        with adws_upgrade.update_lock(),self.assertRaises(RuntimeError):
            bundle.import_bundle({'files':{'adws/setup.json':'{}'}})
        self.assertEqual(target.read_text(),'{"old":true}')

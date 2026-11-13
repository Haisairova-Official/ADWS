import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_sddm as sddm


class SddmSettingsTests(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory()
        self.addCleanup(fixture.cleanup)
        self.root = Path(fixture.name)
        self.manager = self.root / 'etc/systemd/system/display-manager.service'
        self.manager.parent.mkdir(parents=True)
        self.manager.symlink_to('/usr/lib/systemd/system/sddm.service')
        self.fragment = self.root / sddm.boot.SDDM_FRAGMENT.lstrip('/')
        self.user_file = self.write('etc/sddm.conf.d/10-desktop.conf',
                                    '[Theme]\nCurrent=original\n[General]\nNumlock=on\n')
        self.write('usr/share/sddm/themes/original/metadata.desktop', '[SddmGreeterTheme]\n')
        self.write('usr/share/sddm/themes/original/Main.qml', 'Item {}')
        self.write('usr/share/sddm/themes/alternative/metadata.desktop',
                   '[SddmGreeterTheme]\nMainScript=ui/Login.qml\n')
        self.write('usr/share/sddm/themes/alternative/ui/Login.qml', 'Item {}')

    def write(self, filename, text):
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def no_commands(self, *args, **kwargs):
        self.fail('The fixture attempted to start a subprocess')

    def state(self):
        return sddm.inspect(self.root, self.no_commands)

    def change(self, action, theme='', snapshot=None):
        snapshot = snapshot if snapshot is not None else self.state()
        request = {'action': action, 'theme': theme, 'revision': snapshot['revision']}
        return sddm._perform(request, self.root, self.no_commands)

    def test_takeover_edit_and_release_with_backup(self):
        state = self.state()
        self.assertEqual(state['themes'], ['alternative', 'original'])
        self.assertEqual(state['current'], 'original')
        self.assertFalse(state['managed'])
        original = self.user_file.read_bytes()
        first = self.change('apply', 'alternative')
        self.assertEqual(self.state()['current'], 'alternative')
        self.assertTrue(self.state()['can_restore'])
        self.assertTrue((Path(first['backup']) / 'journal.json').is_file())
        same = self.change('apply', 'alternative')
        self.assertEqual(same['status'], 'preserved')
        self.change('apply', 'original')
        self.change('apply', 'alternative')
        release = self.change('restore')
        self.assertFalse(self.fragment.exists())
        self.assertEqual(self.state()['current'], 'original')
        self.assertEqual(self.user_file.read_bytes(), original)
        self.assertEqual(sddm.boot.rollback(release['backup'])['conflicts'], [])
        self.assertEqual(self.state()['current'], 'alternative')

    def test_identifies_non_sddm_and_refuses_changes(self):
        for manager in ('gdm3', 'plasmalogin', 'lightdm'):
            with self.subTest(manager=manager):
                self.manager.unlink()
                self.manager.symlink_to('/usr/lib/systemd/system/' + manager + '.service')
                state = self.state()
                self.assertEqual(state['manager'], manager.replace('gdm3', 'gdm'))
                self.assertFalse(state['can_apply'])
                with self.assertRaises(ValueError):
                    self.change('apply', 'alternative')
                self.assertFalse(self.fragment.exists())

    def test_preserves_occupied_files_including_modified_managed_and_empty(self):
        for text in ('', '[Theme]\nCurrent=mine\n',
                     sddm.boot.MARKER + '\n[Theme]\nCurrent=original\n[General]\nNumlock=on\n'):
            with self.subTest(text=text):
                self.fragment.write_text(text)
                self.assertFalse(self.state()['can_apply'])
                self.assertFalse(self.state()['can_restore'])
                with self.assertRaises(ValueError):
                    self.change('restore')
                self.assertEqual(self.fragment.read_text(), text)

    def test_priority_conflict_allows_release_and_never_overwrites_user_override(self):
        self.change('apply', 'alternative')
        for path in ('etc/sddm.conf', 'etc/sddm.conf.d/zzz-user.conf'):
            with self.subTest(path=path):
                original = '[Theme]\nCurrent=my_override\n'
                override = self.write(path, original)
                state = self.state()
                self.assertEqual(state['current'], 'my_override')
                self.assertIn('/' + path, state['conflict'])
                self.assertFalse(state['can_apply'])
                self.assertTrue(state['can_restore'])
                self.change('restore')
                self.assertEqual(override.read_text(), original)
                self.assertFalse(self.state()['can_restore'])
                override.unlink()
                self.change('apply', 'alternative')

    def test_rejects_stale_review_and_noninstalled_names(self):
        before = self.state()
        self.user_file.write_text('[Theme]\nCurrent=changed\n')
        with self.assertRaises(ValueError):
            self.change('apply', 'alternative', before)
        for name in ('missing', '../tmp', '/some/path'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.change('apply', name)
        self.assertFalse(self.fragment.exists())

    def test_graphical_authorization_can_be_cancelled(self):
        state = self.state()
        with patch('adws_sddm.os.geteuid', return_value=1000), patch.object(Path, 'is_file', return_value=True), \
             patch('adws_sddm.subprocess.run', return_value=subprocess.CompletedProcess([], 126, '', '')) as run:
            with self.assertRaises(sddm.AuthorizationCancelled):
                sddm.apply('alternative', state)
        args, kwargs = run.call_args
        self.assertEqual(args[0][:4], ['/usr/bin/pkexec', '--disable-internal-agent', '/usr/bin/python3', '-I'])
        self.assertEqual(json.loads(kwargs['input']), {'action': 'apply', 'theme': 'alternative', 'revision': state['revision']})

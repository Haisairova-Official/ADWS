import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_keyboard as keys


class KeyboardProfiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.config = self.directory / 'config.kdl'
        self.original = 'include "binds.kdl"\n// user preferences\n'
        self.config.write_text(self.original)
        self.binds = self.directory / 'binds.kdl'
        self.binds.write_text('binds {\nMod { toggle-overview; }\nCtrl+C { spawn "true"; }\nMod+T { spawn "true"; }\n}\n')

    def test_all_profiles_validate_with_existing_binds_and_restore_waylander(self):
        import shutil
        if not shutil.which('niri'):
            self.skipTest('Niri not installed')
        if not keys.modifier_taps_supported():
            self.skipTest('Niri does not support modifier taps')
        old_binds = self.binds.read_bytes()
        for profile in ['traditional', 'reversed', 'waylander']:
            keys.apply_profile(profile, self.config)
            self.assertEqual(keys.current_profile(self.config), profile)
            self.assertEqual(self.binds.read_bytes(), old_binds)
            text = self.config.read_text()
            self.assertEqual(text.count(keys.BEGIN), 1)
            self.assertTrue(text.startswith(self.original))
            self.assertEqual(subprocess.run(['niri', 'validate', '-c', str(self.config)], capture_output=True).returncode, 0)
            before = self.config.read_bytes()
            keys.apply_profile(profile, self.config)
            self.assertEqual(before, self.config.read_bytes())
        self.assertEqual(keys.clean_block(self.config.read_text()).strip(), self.original.strip())

    def test_actions_are_taps_and_never_replace_combinations(self):
        for profile in keys.PROFILES:
            content = keys.bindings(profile, Path('/a path/ADWS'))
            self.assertNotIn('Ctrl+', content)
            self.assertNotIn('Super+', content)
            self.assertEqual(content.count('repeat=false'), 3)
            self.assertNotIn('Super_L', content)
        self.assertIn('Ctrl repeat=false hotkey-overlay-title=null { toggle-overview;', keys.bindings('traditional'))
        self.assertIn('Ctrl repeat=false hotkey-overlay-title=null { spawn "bash"', keys.bindings('reversed'))
        self.assertIn('Ctrl repeat=false hotkey-overlay-title=null { spawn;', keys.bindings('waylander'))

    @patch('adws_keyboard.shutil.which', return_value='/usr/bin/niri')
    @patch('adws_keyboard.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'unsupported'))
    def test_validation_failure_keeps_user_config(self, _run, _which):
        with self.assertRaises(ValueError):
            keys.apply_profile('traditional', self.config)
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual(list(self.directory.glob('.adws-keyboard-*')), [])
        self.assertFalse(self.config.with_suffix('.kdl.adws-keyboard-bak').exists())

    @patch('adws_keyboard.shutil.which', return_value='/usr/bin/niri')
    @patch('adws_keyboard.subprocess.run', side_effect=subprocess.TimeoutExpired('niri', 5))
    def test_timeout_keeps_config(self, _run, _which):
        with self.assertRaises(ValueError):
            keys.apply_profile('traditional', self.config)
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual(list(self.directory.glob('.adws-keyboard-*')), [])

    @patch('adws_keyboard.shutil.which', return_value='/usr/bin/niri')
    @patch('adws_keyboard.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', ''))
    def test_symlink_and_backup_preserved(self, _run, _which):
        link = self.directory / 'linked.kdl'
        link.symlink_to(self.config)
        keys.apply_profile('reversed', link)
        self.assertTrue(link.is_symlink())
        self.assertEqual(self.config.with_suffix('.kdl.adws-keyboard-bak').read_text(), self.original)

    @patch('adws_keyboard.shutil.which', return_value='/usr/bin/niri')
    @patch('adws_keyboard.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'unknown key'))
    def test_upstream_without_modifier_taps_is_detected(self, _run, _which):
        self.assertFalse(keys.modifier_taps_supported())
        self.assertEqual(self.config.read_text(), self.original)

    @patch('adws_keyboard.shutil.which', return_value=None)
    def test_missing_niri_is_unsupported(self, _which):
        self.assertFalse(keys.modifier_taps_supported())

    def test_malformed_markers_and_unknown_profile_rejected(self):
        with self.assertRaises(ValueError):
            keys.clean_block(keys.BEGIN + '\n')
        with self.assertRaises(ValueError):
            keys.bindings('invalid')

    @patch('adws_keyboard.shutil.which', return_value='/usr/bin/niri')
    @patch('adws_keyboard.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', ''))
    @patch('adws_atomic.replace_files', side_effect=OSError('disk full'))
    def test_failed_commit_removes_unreferenced_include(self, _replace, _run, _which):
        with self.assertRaises(OSError):
            keys.apply_profile('traditional', self.config)
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual(list(self.directory.glob('.adws-keyboard-*')), [])


if __name__ == '__main__':
    unittest.main()

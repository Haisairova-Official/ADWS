"""Input settings writes never replace unrelated compositor preferences."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_input_settings as settings


class InputSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.config = self.directory / 'config.kdl'
        self.original = ('input {\n'
                         '    mouse { accel-speed 0.3; natural-scroll; }\n'
                         '    keyboard { xkb { layout "us,de"; options "grp:alt_shift_toggle"; }; }\n'
                         '}\n')
        self.config.write_text(self.original)

    def test_real_niri_grammar_preserves_pointing_devices_and_layout(self):
        niri = shutil.which('niri')
        if not niri:
            self.skipTest('Niri is not installed')
        with patch('adws_niri_compat.niri_binary', return_value=niri):
            self.assertIsNone(settings.read_niri_repeat(self.config))
            settings.apply_niri_repeat(True, {'rate': 36, 'delay': 450}, self.config)
            self.assertTrue(self.config.read_text().startswith(self.original))
            self.assertEqual(settings.read_niri_repeat(self.config), {'rate': 36, 'delay': 450})
            before = self.config.read_bytes()
            settings.apply_niri_repeat(True, {'rate': 36, 'delay': 450}, self.config)
            self.assertEqual(self.config.read_bytes(), before)
            included = list(self.directory.glob('.adws-input-*.kdl'))
            self.assertEqual(len(included), 1)
            self.assertNotIn('mouse', included[0].read_text())
            self.assertNotIn('xkb', included[0].read_text())
            settings.apply_niri_repeat(False, {'rate': 36, 'delay': 450}, self.config)
            self.assertEqual(self.config.read_text().strip(), self.original.strip())
            self.assertIsNone(settings.read_niri_repeat(self.config))

    @patch('adws_niri_compat.niri_binary', return_value='/usr/bin/niri')
    @patch('adws_input_settings.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'invalid config'))
    def test_validation_failure_keeps_original_and_removes_new_include(self, *_):
        with self.assertRaisesRegex(ValueError, 'invalid config'):
            settings.apply_niri_repeat(True, {'rate': 40, 'delay': 500}, self.config)
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), ['config.kdl'])

    @patch('adws_niri_compat.niri_binary', return_value='/usr/bin/niri')
    @patch('adws_input_settings.subprocess.run', side_effect=subprocess.TimeoutExpired('niri', 5))
    def test_validation_timeout_keeps_original(self, *_):
        with self.assertRaises(subprocess.TimeoutExpired):
            settings.apply_niri_repeat(True, {'rate': 40, 'delay': 500}, self.config)
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), ['config.kdl'])

    @patch('adws_niri_compat.niri_binary', return_value='/usr/bin/niri')
    def test_concurrent_edit_is_not_overwritten(self, *_):
        def concurrent_edit(*args, **kwargs):
            self.config.write_text(self.original + '// Edited outside ADWS\n')
            return subprocess.CompletedProcess(args[0], 0, '', '')
        with patch.object(settings.subprocess, 'run', side_effect=concurrent_edit):
            with self.assertRaises(ValueError):
                settings.apply_niri_repeat(True, {'rate': 40, 'delay': 500}, self.config)
        self.assertIn('Edited outside ADWS', self.config.read_text())
        self.assertEqual(list(self.directory.glob('.adws-input-*.kdl')), [])

    @patch('adws_niri_compat.niri_binary', return_value='/usr/bin/niri')
    @patch('adws_input_settings.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', ''))
    @patch('adws_atomic.replace_files', side_effect=OSError('disk full'))
    def test_write_failure_keeps_original_and_cleans_include(self, *_):
        with self.assertRaisesRegex(OSError, 'disk full'):
            settings.apply_niri_repeat(True, {'rate': 40, 'delay': 500}, self.config)
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual(list(self.directory.glob('.adws-input-*.kdl')), [])

    @patch('adws_niri_compat.niri_binary', return_value='/usr/bin/niri')
    @patch('adws_input_settings.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', ''))
    def test_symlink_remains_a_symlink_and_managed_value_is_read(self, *_):
        links = self.directory / 'links'; links.mkdir()
        link = links / 'config.kdl'; link.symlink_to(self.config)
        settings.apply_niri_repeat(True, {'rate': 40, 'delay': 500}, link)
        self.assertTrue(link.is_symlink())
        self.assertEqual(settings.read_niri_repeat(link), {'rate': 40, 'delay': 500})
        self.assertEqual(self.config.with_suffix('.kdl.adws-input-bak').read_text(), self.original)

    def test_malformed_markers_and_values_are_rejected(self):
        with self.assertRaises(ValueError):
            settings.clean_block(settings.BEGIN + '\n')
        for rate, delay in [(-1, 600), (256, 600), (25, 0), (25, 5001), (True, 600), (25, 600.0)]:
            with self.subTest(rate=rate, delay=delay), self.assertRaises(ValueError):
                settings.validated_values(rate, delay)

    @patch('adws_input_settings.run')
    def test_hyprland_rolls_back_both_parameters_after_partial_failure(self, run):
        run.side_effect = ['{"int":25}', '{"int":600}', 'ok', 'bad value', 'ok', 'ok']
        with self.assertRaisesRegex(RuntimeError, 'bad value'):
            settings.apply_hyprland_repeat({'rate': 40, 'delay': 700})
        self.assertEqual(run.call_args_list[-2].args[0], ['hyprctl', 'keyword', 'input:repeat_delay', '600'])
        self.assertEqual(run.call_args_list[-1].args[0], ['hyprctl', 'keyword', 'input:repeat_rate', '25'])

    @patch('adws_input_settings.run', return_value='{"str":"missing"}')
    def test_unreadable_hyprland_value_is_not_replaced_with_a_default(self, _):
        with self.assertRaises(ValueError):
            settings.read_hyprland_repeat()

    @patch('adws_input_settings.run')
    def test_layout_switch_checks_current_list_and_uses_zero_based_index(self, run):
        run.side_effect = [json.dumps({'names': ['English', 'German'], 'current_idx': 0}), 'Handled']
        settings.switch_niri_layout(1, ['English', 'German'])
        self.assertEqual(run.call_args.args[0], ['niri', 'msg', 'action', 'switch-layout', '1'])
        run.reset_mock()
        run.side_effect = [json.dumps({'names': ['English'], 'current_idx': 0})]
        with self.assertRaises(ValueError):
            settings.switch_niri_layout(1, ['English', 'German'])
        self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()

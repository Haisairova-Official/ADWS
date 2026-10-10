import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_niri_compat as compat


class NiriCompatibilityTests(unittest.TestCase):
    def test_patch_integrity_and_scope(self):
        data, path = compat.spec()
        self.assertEqual(data['commit'], '8ed0da44d974c32c6877d2f4630c314da0717ecb')
        paths = [line.split(' b/', 1)[1] for line in path.read_text().splitlines() if line.startswith('diff --git ')]
        self.assertEqual(set(paths), {'niri-config/src/binds.rs', 'src/input/mod.rs', 'src/input/modifier_tap.rs', 'src/niri.rs', 'src/ui/hotkey_overlay.rs', 'src/utils/mod.rs'})
        self.assertEqual(data['patch_version'], '1.0.0')
        self.assertIn('ADWS modifier-taps 1.0.0', path.read_text())

    @patch.object(compat, 'run', return_value='wrong-commit')
    def test_wrong_source_revision_refused(self, run):
        with self.assertRaises(ValueError): compat.verify_source(Path('/unused'), 'expected')
        self.assertEqual(run.call_count, 1)

    @patch.object(compat, 'run', side_effect=['expected', ' M src/input/mod.rs'])
    def test_modified_source_refused(self, run):
        with self.assertRaises(ValueError): compat.verify_source(Path('/unused'), 'expected')

    @patch.object(compat, 'ask', return_value='n')
    @patch('adws_keyboard.modifier_taps_supported', return_value=False)
    @patch.object(compat, 'build')
    def test_optional_offer_decline_never_builds(self, build, supported, ask):
        self.assertEqual(compat.offer(), 0); build.assert_not_called()

    @patch.object(compat, 'ask')
    @patch('adws_keyboard.modifier_taps_supported', return_value=True)
    def test_supported_compositor_is_not_offered_replacement(self, supported, ask):
        self.assertEqual(compat.offer(), 0); ask.assert_not_called()

    @patch.object(compat, 'ask', return_value='y')
    @patch('adws_keyboard.modifier_taps_supported', return_value=False)
    @patch.object(compat, 'build', side_effect=OSError('test build failure'))
    def test_optional_failure_does_not_fail_adws_installation(self, build, supported, ask):
        self.assertEqual(compat.offer(), 0)

    def test_install_preserves_system_and_refuses_foreign_entry(self):
        data, _ = compat.spec()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); bundle = home/'bundle'; bundle.mkdir()
            binary = b'fixture binary, never executed'
            (bundle/'niri').write_bytes(binary)
            (bundle/'LICENSE').write_text('test license')
            (bundle/'manifest.json').write_text(json.dumps(dict(data, binary_sha256=hashlib.sha256(binary).hexdigest())))
            entry = home/'.local/bin/niri-adws'; entry.parent.mkdir(parents=True)
            original = home/'.local/bin/niri'; original.write_text('original')
            entry.write_text('user script')
            with patch.object(compat.Path, 'home', return_value=home):
                with self.assertRaises(ValueError): compat.install_bundle(bundle)
                self.assertEqual(entry.read_text(), 'user script')
                entry.unlink(); compat.install_bundle(bundle)
                self.assertIn('ADWS_NIRI_BINARY=', entry.read_text())
                compat.install_bundle(bundle)
                self.assertEqual(original.read_text(), 'original')
                (bundle/'niri').write_bytes(b'altered')
                with self.assertRaises(ValueError): compat.install_bundle(bundle)

    def test_restore_removes_only_managed_bindings(self):
        import adws_keyboard as keys
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/'config.kdl'
            original='// Keep my shortcuts\nbinds { Mod+T { spawn "true"; }; }\n'
            config.write_text(original+'\n'+keys.BEGIN+'\n// profile: traditional\ninclude "owned.kdl"\n'+keys.END+'\n')
            with patch('adws_windows.config_path', return_value=config), patch('adws_autostart.write_config') as write:
                compat.restore()
                self.assertEqual(write.call_args.args[1].strip(), original.strip())

if __name__ == '__main__': unittest.main()

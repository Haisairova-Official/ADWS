from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_install_workflow as workflow
from adws_install_startup import audit
from adws_install_features import distinct_wallpaper_instances
from adws_install_transaction import Snapshot


class Reinstall(unittest.TestCase):
    def test_delayed_start_audited_without_executing_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.kdl'
            path.write_text('spawn-sh-at-startup "sleep 1 && mako"\n')
            result = audit(directory, niri_path=path, enabled_units=[], autostart_dirs=[])
            self.assertEqual(result['unknown'], [])
            self.assertEqual(result['owners']['notifications'][0]['argv'], ['mako'])

    def test_wallpaper_namespaces(self):
        default = {'argv': ['awww-daemon']}
        overview = {'argv': ['awww-daemon', '-n', 'overview']}
        self.assertTrue(distinct_wallpaper_instances([default, overview]))
        self.assertFalse(distinct_wallpaper_instances([overview, overview]))
        self.assertFalse(distinct_wallpaper_instances([default, {'argv': ['swww-daemon']}]))

    def test_replacement_rollback_and_changed_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'waybar'
            config.mkdir()
            file = config / 'modules.jsonc'
            file.write_text('personal')
            backup = root / 'backup'
            backup.mkdir()
            snapshot = Snapshot(backup, [file])
            plan = {'config_home': directory, 'replace_waybar_defaults': {file.name: workflow.config_state(file)}}
            file.write_text('edited')
            with self.assertRaises(ValueError):
                workflow.replace_reviewed_defaults(plan)
            self.assertEqual(file.read_text(), 'edited')
            snapshot.restore()
            workflow.replace_reviewed_defaults(plan)
            self.assertFalse(file.exists())
            snapshot.restore()
            self.assertEqual(file.read_text(), 'personal')

    def test_failure_can_retry_without_exiting(self):
        with patch.object(workflow, 'main', side_effect=[ValueError('conflict'), 0]) as main, \
             patch.object(workflow, 'interactive', return_value=True), \
             patch.object(workflow, 'choose', return_value=0), patch.object(sys, 'argv', ['install.sh']):
            self.assertEqual(workflow.run_interactive(), 0)
            self.assertEqual(main.call_count, 2)

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_oobe as oobe


class SetupTests(unittest.TestCase):
    def test_first_run_and_existing_configuration(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_CONFIG_HOME': temp}):
            self.assertTrue(oobe.needed())
            oobe.write_json(oobe.folder()/'setup.json', {'completed': True})
            self.assertFalse(oobe.needed())
            (oobe.folder()/'setup.json').unlink()
            oobe.write_json(oobe.folder()/'taskbar-layout.json', {'options': {}})
            self.assertFalse(oobe.needed())

    def test_no_display_never_launches(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(oobe.subprocess, 'Popen') as spawn:
            oobe.launch()
            spawn.assert_not_called()

    def test_save_keeps_configuration_link_and_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);target=root/'actual.json';target.write_text('{}');target.chmod(0o600)
            link=root/'setup.json';link.symlink_to(target)
            oobe.write_json(link,{'completed':True})
            self.assertTrue(link.is_symlink())
            self.assertIn('true',target.read_text())
            self.assertEqual(target.stat().st_mode & 0o777,0o600)

    def test_automatic_setup_rechecks_after_acquiring_wizard_lock(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'XDG_RUNTIME_DIR':temp}),patch.object(sys,'argv',['adws-setup','--auto']),patch.object(oobe,'needed',side_effect=[True,False]),patch.object(oobe,'run') as run:
            oobe.main()
            run.assert_not_called()


class SaveSettingsTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        env=patch.dict(os.environ,{'XDG_CONFIG_HOME':str(self.root/'config'),'XDG_STATE_HOME':str(self.root/'state')})
        env.start();self.addCleanup(env.stop)
        self.processes=patch('adws_runtime.pids',return_value=[]);self.processes.start();self.addCleanup(self.processes.stop)
        self.restart=patch('adws_layout.restart_taskbar');self.restart_mock=self.restart.start();self.addCleanup(self.restart.stop)

    def save(self, selected=None, wallpaper=None, default=None):
        oobe.save_settings({'options':{}},'#123456',selected or {},wallpaper,default or Mock())

    def test_default_app_failure_restores_linked_file_and_allows_retry(self):
        path=self.root/'config/mimeapps.list';path.parent.mkdir(parents=True)
        target=self.root/'mimeapps.actual';target.write_text('original');target.chmod(0o600);path.symlink_to(target)
        def fail(mime,desktop_id):path.write_text('partially changed');raise RuntimeError('default app failure')
        with self.assertRaisesRegex(RuntimeError,'default app failure'):
            self.save({'text/plain':'test.desktop'},default=fail)
        self.assertTrue(path.is_symlink());self.assertEqual(target.read_text(),'original')
        self.assertEqual(target.stat().st_mode & 0o777,0o600)
        self.assertFalse((oobe.folder()/'setup.json').exists())
        self.save();self.assertTrue((oobe.folder()/'setup.json').is_file())
        self.restart_mock.assert_not_called()

    def test_wallpaper_failure_restores_preferences_and_dangling_link(self):
        path=oobe.folder()/'setup.json';path.parent.mkdir(parents=True)
        path.symlink_to(self.root/'missing.json')
        with patch('adws_wallpaper.apply',side_effect=RuntimeError('wallpaper failure')),self.assertRaisesRegex(RuntimeError,'wallpaper failure'):
            self.save(wallpaper={'engine':'awww','image':'/test.png'})
        self.assertTrue(path.is_symlink());self.assertFalse(path.exists())
        self.assertFalse((oobe.folder()/'wallpaper.json').exists())
        self.assertFalse((oobe.folder()/'taskbar-layout.json').exists())

    def test_recovery_failure_reports_persistent_backup(self):
        from adws_install_transaction import Snapshot
        with patch.object(Snapshot,'restore',side_effect=OSError('restore failure')),self.assertRaisesRegex(RuntimeError,'setup-backups') as raised:
            self.save({'text/plain':'test.desktop'},default=Mock(side_effect=RuntimeError('save failure')))
        self.assertIn('restore failure',str(raised.exception))
        self.assertIn('save failure',str(raised.exception))
        self.assertTrue(list((self.root/'state/adws/setup-backups').glob('setup-*/manifest.json')))

    def test_restart_exception_reports_settings_already_saved(self):
        self.restart_mock.side_effect=OSError('restart failure')
        with patch('adws_runtime.pids',return_value=[123]),self.assertRaisesRegex(RuntimeError,'restart failure'):
            self.save()
        self.assertTrue((oobe.folder()/'setup.json').is_file())
        self.assertFalse(oobe.needed())

    def test_wizard_save_respects_installation_lock(self):
        from adws_upgrade import update_lock
        default=Mock()
        with update_lock(),self.assertRaises(RuntimeError):self.save({'text/plain':'test.desktop'},default=default)
        default.assert_not_called();self.assertFalse(oobe.folder().exists())

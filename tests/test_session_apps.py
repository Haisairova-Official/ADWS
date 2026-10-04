from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from adws_session_apps import read_entries,set_enabled,delete_entry

class SessionAppsTests(unittest.TestCase):
    def test_user_override_preserves_command_and_does_not_change_system_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);system=root/'system/autostart';system.mkdir(parents=True)
            body='[Desktop Entry]\nType=Application\nName=Fixture\nExec=/usr/bin/true --unchanged\nOnlyShowIn=niri;\n'
            path=system/'fixture.desktop';path.write_text(body)
            with patch.dict(os.environ,{'XDG_CONFIG_HOME':str(root/'user'),'XDG_CONFIG_DIRS':str(root/'system'),'XDG_CURRENT_DESKTOP':'niri'}):
                name,title,enabled,data=read_entries()[0]
                self.assertTrue(enabled)
                set_enabled(name,data,False)
                self.assertFalse(read_entries()[0][2])
                self.assertEqual(path.read_text(),body)
                self.assertIn('Exec=/usr/bin/true --unchanged',(root/'user/autostart/fixture.desktop').read_text())
                set_enabled(name,data,True)
                self.assertTrue(read_entries()[0][2])
                with self.assertRaises(ValueError):set_enabled('../bad.desktop',data,True)

    def test_desktop_specific_entries_are_filtered(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);directory=root/'autostart';directory.mkdir()
            (directory/'other.desktop').write_text('[Desktop Entry]\nType=Application\nName=Other\nOnlyShowIn=GNOME;\nExec=true\n')
            with patch.dict(os.environ,{'XDG_CONFIG_HOME':str(root),'XDG_CONFIG_DIRS':str(root/'empty'),'XDG_CURRENT_DESKTOP':'niri'}):
                self.assertEqual(read_entries(),[])

    def test_linked_launcher_is_preserved_when_disabling_and_enabling_autostart(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            launcher = root / 'applications/fixture.desktop'
            launcher.parent.mkdir()
            body = '[Desktop Entry]\nType=Application\nName=链接应用\nExec=/usr/bin/true --unchanged\n'
            launcher.write_text(body)
            directory = root / 'config/autostart'
            directory.mkdir(parents=True)
            entry = directory / launcher.name
            entry.symlink_to(launcher)
            with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(root / 'config'),
                                         'XDG_CONFIG_DIRS': str(root / 'empty'),
                                         'XDG_CURRENT_DESKTOP': 'niri'}):
                name, _title, enabled, data = read_entries()[0]
                self.assertTrue(enabled)
                set_enabled(name, data, False)
                self.assertFalse(entry.is_symlink())
                self.assertEqual(launcher.read_text(), body)
                self.assertIn('Hidden=true', entry.read_text())
                self.assertFalse(read_entries()[0][2])
                set_enabled(name, data, True)
                self.assertTrue(read_entries()[0][2])
                self.assertEqual(launcher.read_text(), body)
                self.assertIn('Exec=/usr/bin/true --unchanged', entry.read_text())

    def test_failed_override_keeps_symlink_and_target_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            launcher = root / 'fixture.desktop'
            body = '[Desktop Entry]\nType=Application\nName=Fixture\nExec=true\n'
            launcher.write_text(body)
            directory = root / 'config/autostart'
            directory.mkdir(parents=True)
            entry = directory / launcher.name
            entry.symlink_to(launcher)
            with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(root / 'config'),
                                         'XDG_CONFIG_DIRS': str(root / 'empty'),
                                         'XDG_CURRENT_DESKTOP': 'niri'}):
                name, _title, _enabled, data = read_entries()[0]
                with patch('adws_session_apps.os.replace', side_effect=OSError('disk full')):
                    with self.assertRaisesRegex(OSError, 'disk full'):
                        set_enabled(name, data, False)
                self.assertTrue(entry.is_symlink())
                self.assertEqual(launcher.read_text(), body)
                self.assertEqual(list(directory.iterdir()), [entry])

    def test_delete_local_symlink_preserves_application(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);directory=root/'user/autostart';directory.mkdir(parents=True)
            app=root/'launcher.desktop'
            body='[Desktop Entry]\nType=Application\nName=音乐播放器\nExec=true\n'
            app.write_text(body)
            entry=directory/'music.desktop';entry.symlink_to(app)
            with patch.dict(os.environ,{'XDG_CONFIG_HOME':str(root/'user'),'XDG_CONFIG_DIRS':str(root/'system')}):
                name,_,_,data=read_entries()[0]
                with self.assertRaises(ValueError):delete_entry('../music.desktop',data)
                delete_entry(name,data)
                self.assertFalse(entry.is_symlink())
                self.assertEqual(app.read_text(),body)
                self.assertEqual(read_entries(),[])

    def test_delete_system_entry_stays_removed_and_can_be_added_again(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);directory=root/'system/autostart';directory.mkdir(parents=True)
            entry=directory/'music.desktop'
            body='[Desktop Entry]\nType=Application\nName=Music\nExec=true\n'
            entry.write_text(body)
            with patch.dict(os.environ,{'XDG_CONFIG_HOME':str(root/'user'),'XDG_CONFIG_DIRS':str(root/'system')}):
                name,_,_,data=read_entries()[0]
                set_enabled(name,data,True)  # A user override of a system entry.
                delete_entry(name,data)
                self.assertEqual(read_entries(),[])
                self.assertEqual(entry.read_text(),body)
                override=root/'user/autostart/music.desktop'
                self.assertIn('Hidden=true',override.read_text())
                set_enabled(name,data,True)
                self.assertTrue(read_entries()[0][2])
                self.assertNotIn('X-ADWS-Removed',override.read_text())

if __name__=='__main__':unittest.main()

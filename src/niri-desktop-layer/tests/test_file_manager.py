from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from desktop_layer import model


class FileManagerTests(unittest.TestCase):
    def test_folder_with_shell_characters_is_a_single_uri(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'a & b; c'
            target.mkdir()
            entry = model.scan_desktop(Path(folder))[0]
            with patch.object(model, 'open_in_file_manager', return_value=True) as opened:
                model.launch_entry(entry)
                opened.assert_called_once_with(target.as_uri(), None)

    def test_navigation_shortcuts_use_the_selected_manager_without_changing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for uri in ('computer:///', 'network:///', 'trash:///'):
                path = root / 'location.desktop'
                content = f'[Desktop Entry]\nType=Application\nName=Location\nExec=pcmanfm-qt {uri}\n'
                path.write_text(content)
                with patch.object(model.Gio.DesktopAppInfo, 'new_from_filename', return_value=Mock()), patch.object(model, 'open_in_file_manager', return_value=True) as opened:
                    model.launch_entry(model.scan_desktop(root)[0])
                    opened.assert_called_once_with(uri, None)
                self.assertEqual(path.read_text(), content)
                self.assertFalse(path.stat().st_mode & 0o111)

    def test_folder_opening_uses_current_directory_association_each_time(self):
        apps = [Mock(), Mock()]
        with patch.object(model.Gio.AppInfo, 'get_default_for_type', side_effect=apps) as lookup:
            for app in apps:
                model.open_in_file_manager('file:///tmp/a%20b')
                app.launch_uris.assert_called_once_with(['file:///tmp/a%20b'], None)
        self.assertEqual(lookup.call_count, 2)
        lookup.assert_called_with('inode/directory', False)

    def test_missing_manager_reports_actionable_error(self):
        on_error = Mock()
        with patch.object(model.Gio.AppInfo, 'get_default_for_type', return_value=None):
            with self.assertRaises(model.EntryLaunchError):
                model.open_in_file_manager('file:///tmp')
            model.reveal_in_file_manager([Path('/tmp/a')], None, on_error)
            on_error.assert_called_once()

    def test_reveal_only_contacts_chosen_service_and_falls_back_to_actual_parents(self):
        app = Mock()
        app.get_id.return_value = 'org.example.Files.desktop'
        context = Mock()
        connection = Mock()
        paths = [Path('/tmp/group a/1'),Path('/tmp/group a/2'),Path('/tmp/group b/3')]
        with patch.object(model, 'default_file_manager', return_value=app), \
             patch.object(model.Gio, 'bus_get') as bus, \
             patch.object(model.Gio, 'bus_get_finish', return_value=connection):
            model.reveal_in_file_manager(paths, context, self.fail)
            bus.call_args.args[-1](None, Mock())
            args = connection.call.call_args.args
            self.assertEqual(args[:4], ('org.example.Files', '/org/freedesktop/FileManager1',
                                        'org.freedesktop.FileManager1', 'ShowItems'))
            self.assertEqual(args[4].unpack(), ([p.as_uri() for p in paths], ''))
            args[-1](connection, Mock())
            app.launch_uris.assert_not_called()
            connection.call_finish.side_effect = model.GLib.Error('ShowItems unavailable')
            args[-1](connection, Mock())
            app.launch_uris.assert_called_once_with(['file:///tmp/group%20a', 'file:///tmp/group%20b'], context)

    def test_reveal_without_application_bus_name_opens_containing_folder(self):
        app = Mock()
        app.get_id.return_value = 'custom-manager.desktop'
        with patch.object(model, 'default_file_manager', return_value=app), patch.object(model.Gio, 'bus_get') as bus:
            model.reveal_in_file_manager([Path('/tmp/a & b.txt')], None, self.fail)
            bus.assert_not_called()
            app.launch_uris.assert_called_once_with(['file:///tmp'], None)

    def test_extra_launcher_arguments_are_not_reinterpreted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'custom.desktop'
            path.write_text('[Desktop Entry]\nType=Application\nName=Custom\nExec=pcmanfm-qt --some-option /tmp\n')
            self.assertIsNone(model._file_manager_location(path))

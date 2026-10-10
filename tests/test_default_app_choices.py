import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_settings_widgets as widgets


class ApplicationChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not widgets.Gtk.init_check()[0]:
            raise unittest.SkipTest('GTK display unavailable; run under Xvfb')

    def app(self, identity, name, visible=True):
        app = Mock()
        app.get_id.return_value = identity
        app.get_display_name.return_value = name
        app.get_commandline.return_value = '/usr/bin/' + name.lower()
        app.should_show.return_value = visible
        app.equal.side_effect = lambda other: app.get_id() == other.get_id()
        return app

    def choice(self, default, compatible, installed):
        with patch.object(widgets.Gio.AppInfo, 'get_default_for_type', return_value=default), \
             patch.object(widgets.Gio.AppInfo, 'get_all_for_type', return_value=compatible):
            choice = widgets.ApplicationChoice('text/plain', applications=installed)
        self.addCleanup(choice.destroy)
        return choice

    def test_repeated_groups_and_current_default_appear_once(self):
        default = self.app('editor.desktop', 'Editor')
        same_app = self.app('editor.desktop', 'Editor')
        alternative = self.app('other.desktop', 'Other')
        choice = self.choice(default, [same_app, alternative, same_app, alternative],
                             [same_app, alternative, default])
        self.assertEqual([app.get_id() for app in choice.apps.values()], ['editor.desktop', 'other.desktop'])
        self.assertIs(choice.get_app_info(), default)

    def test_default_absent_from_handlers_is_preserved(self):
        default = self.app('private.desktop', 'Private', visible=False)
        handler = self.app('handler.desktop', 'Handler')
        choice = self.choice(default, [handler], [handler])
        self.assertIs(choice.get_app_info(), default)
        self.assertEqual(len(choice.apps), 2)

    def test_distinct_installations_with_same_name_remain_selectable(self):
        native = self.app('chrome.desktop', 'Chrome')
        flatpak = self.app('com.google.Chrome.desktop', 'Chrome')
        flatpak.get_commandline.return_value = '/usr/bin/flatpak run com.google.Chrome'
        choice = self.choice(native, [native, flatpak], [native, flatpak])
        self.assertEqual(len(choice.apps), 2)
        choice.set_active(1)
        self.assertIs(choice.get_app_info(), flatpak)
        native.set_as_default_for_type.assert_not_called()
        flatpak.set_as_default_for_type.assert_not_called()

    def test_identical_launchers_with_different_ids_are_deduplicated(self):
        default = self.app('hidden-alias.desktop', 'Browser', visible=False)
        visible = self.app('browser.desktop', 'Browser')
        choice = self.choice(default, [default, visible], [default, visible])
        self.assertEqual(len(choice.apps), 1)
        self.assertIs(choice.get_app_info(), default)

    def test_hidden_nondefault_handlers_are_not_offered(self):
        visible = self.app('browser.desktop', 'Browser')
        helper = self.app('helper.desktop', 'Helper', visible=False)
        choice = self.choice(visible, [visible, helper], [visible, helper])
        self.assertEqual(list(choice.apps.values()), [visible])

    def test_unassociated_type_does_not_select_arbitrary_default(self):
        editor = self.app('editor.desktop', 'Editor')
        choice = self.choice(None, [editor], [editor])
        self.assertIsNone(choice.get_app_info())
        self.assertEqual(choice.get_active(), -1)
        editor.set_as_default_for_type.assert_not_called()

    def test_visible_installed_apps_available_without_declared_handler(self):
        visible = self.app('editor.desktop', 'Editor')
        hidden = self.app('helper.desktop', 'Helper', visible=False)
        choice = self.choice(None, [], [visible, hidden])
        self.assertEqual(list(choice.apps.values()), [visible])

    def test_empty_list_is_disabled(self):
        choice = self.choice(None, [], [])
        self.assertFalse(choice.get_sensitive())
        self.assertIsNone(choice.get_app_info())

    def test_application_without_desktop_id_is_deduplicated(self):
        first = self.app(None, 'Command')
        duplicate = self.app(None, 'Command')
        choice = self.choice(None, [first, duplicate], [first])
        self.assertEqual(len(choice.apps), 1)


if __name__ == '__main__':
    unittest.main()

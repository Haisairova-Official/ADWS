import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import mnws_app_launch as launch


class AppLaunchTests(unittest.TestCase):
    def info(self, command='/usr/bin/test-app %U', **values):
        info = Mock()
        data = {'Exec': command, **values}
        info.get_boolean.return_value = False
        info.get_string.side_effect = lambda key: data.get(key)
        info.get_name.return_value = '测试 App %U'
        info.get_filename.return_value = '/tmp/Test App.desktop'
        info.get_id.return_value = 'Test.desktop'
        info.list_actions.return_value = []
        return info

    def test_admin_argv_is_literal_and_has_no_user_credentials(self):
        info = self.info('/usr/bin/test-app --name %c %i %k %% "$(touch /tmp/not-executed)" %U', Icon='test-icon')
        with patch.object(launch.shutil, 'which', side_effect=lambda name: '/usr/bin/pkexec' if name == 'pkexec' else name), \
             patch.dict(launch.os.environ, {'HOME':'/private','DBUS_SESSION_BUS_ADDRESS':'private', 'WAYLAND_DISPLAY':'wayland-1'}, clear=True):
            argv = launch.admin_argv(info)
        self.assertEqual(argv[:5], ['/usr/bin/pkexec','--disable-internal-agent','/usr/bin/env','WAYLAND_DISPLAY=wayland-1','/usr/bin/test-app'])
        self.assertEqual(argv[5:], ['--name','测试 App %U','--icon','test-icon','/tmp/Test App.desktop','%','$(touch /tmp/not-executed)'])

    def test_invalid_or_unsupported_admin_launch(self):
        for info in (self.info('/bin/true %Z'), self.info(XFlatpak='ignored')):
            if info.get_string('XFlatpak'):
                info.get_boolean.return_value = True
            with self.assertRaises(ValueError):
                launch.admin_argv(info)
        with patch.object(launch.shutil,'which',return_value=None), self.assertRaises(ValueError):
            launch.admin_argv(self.info())

    def test_new_window_action_and_fallback(self):
        info = self.info()
        info.list_actions.return_value = ['new-window', 'new-private-window']
        with patch.object(launch, 'resolve_app', return_value=info):
            launch.launch('test')
        info.launch_action.assert_called_once()
        self.assertEqual(info.launch_action.call_args.args[0], 'new-window')
        info.launch.assert_not_called()
        info.list_actions.return_value = []
        with patch.object(launch, 'resolve_app', return_value=info):
            launch.launch('test')
        info.launch.assert_called_once()

    def test_admin_cancellation_and_failure(self):
        with patch.object(launch,'resolve_app',return_value=self.info()), \
             patch.object(launch,'admin_argv',return_value=['pkexec','test']), \
             patch.object(launch.subprocess,'run',return_value=Mock(returncode=126)) as run:
            launch.launch('test',True)
            run.assert_called_once()
            run.return_value = Mock(returncode=127, stderr='auth agent missing')
            with self.assertRaises(RuntimeError):
                launch.launch('test',True)

    def test_missing_exact_launcher_falls_back_to_window_class(self):
        app=self.info()
        app.get_is_hidden.return_value=False
        app.get_startup_wm_class.return_value='WindowClass'
        with patch.object(launch.Gio.DesktopAppInfo,'new',side_effect=TypeError('constructor returned NULL')), \
             patch.object(launch.Gio.AppInfo,'get_all',return_value=[app]), \
             patch('mnws_app_launch.isinstance',side_effect=lambda obj,cls: True):
            self.assertIs(launch.resolve_app('WindowClass'),app)
            with self.assertRaises(ValueError):launch.resolve_app('NotInstalled')

    def test_reject_app_id_path(self):
        with self.assertRaises(ValueError):
            launch.resolve_app('/tmp/evil.desktop')


class PinTests(unittest.TestCase):
    info = AppLaunchTests.info
    def test_pin_order_alias_deduplication_and_unpin_without_launcher(self):
        import tempfile, json
        with tempfile.TemporaryDirectory() as home, patch.dict(launch.os.environ, {'XDG_CONFIG_HOME':home}):
            info=self.info()
            with patch.object(launch,'resolve_app',return_value=info):
                launch.pin_application('TestWMClass', True)
                launch.pin_application('Test.desktop', True)
                info.get_id.return_value='Second.desktop'
                launch.pin_application('Second', True)
            path=Path(home)/'mnws/taskbar-pins.json'
            self.assertEqual([p['desktop_id'] for p in json.loads(path.read_text())['apps']],['Test.desktop','Second.desktop'])
            with patch.object(launch,'resolve_app',side_effect=AssertionError('must not resolve removed apps')):
                launch.pin_application('testwmclass', False)
            self.assertEqual([p['desktop_id'] for p in json.loads(path.read_text())['apps']],['Second.desktop'])

    def test_malformed_pin_file_is_never_overwritten(self):
        import tempfile
        with tempfile.TemporaryDirectory() as home, patch.dict(launch.os.environ, {'XDG_CONFIG_HOME':home}):
            path=Path(home)/'mnws/taskbar-pins.json'
            path.parent.mkdir()
            for contents in ('{', '[]', '{"version":1,"apps":[{}]}', '{"version":1,"apps":[{"app_id":null}]}'):
                path.write_text(contents)
                with patch.object(launch,'resolve_app',return_value=self.info()), self.assertRaises(ValueError):
                    launch.pin_application('Test',True)
                self.assertEqual(path.read_text(),contents)

"""Service-adapter tests; no real device, network, or session is modified."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import copy
import time

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import adws_system_pages as services


class SystemServiceTests(unittest.TestCase):
    def test_nmcli_escaping_preserves_network_names(self):
        self.assertEqual(services.terse_rows('eth0:ethernet:connected:Office\\: floor 2\\\\LAB\n', 4),
                         [['eth0', 'ethernet', 'connected', 'Office: floor 2\\LAB']])
        self.assertEqual(services.terse_rows('bad:row\nvalid:with:four:fields', 4),
                         [['valid', 'with', 'four', 'fields']])

    def test_network_snapshot_is_read_only(self):
        responses = ['enabled\n', 'wlan0:wifi:connected:Home\\: 2\n',
                     '61ad0dc1-cb5c-4e9b-852c-60f9c6ce69d9:Home\\: 2:802-11-wireless:wlan0\n']
        with patch.object(services.shutil, 'which', return_value='/usr/bin/nmcli'), \
             patch.object(services, 'command', side_effect=responses) as run:
            data = services.network_snapshot()
        self.assertTrue(data['wifi'])
        self.assertEqual(data['connections'][0][1], 'Home: 2')
        self.assertEqual(len(run.call_args_list), 3)
        self.assertTrue(all('show' in call.args[0] or 'status' in call.args[0] for call in run.call_args_list))

    def test_network_connection_only_accepts_uuid(self):
        with patch.object(services, 'command') as run:
            with self.assertRaises(ValueError):
                services.network_connection('--help', True)
            with self.assertRaises(ValueError):
                services.network_connection('61ad0dc1-cb5c-4e9b-852c-60f9c6ce69d9', 'yes')
            run.assert_not_called()
            services.network_connection('61AD0DC1-CB5C-4E9B-852C-60F9C6CE69D9', True)
            self.assertEqual(run.call_args.args[0][-3:], ['up', 'uuid', '61ad0dc1-cb5c-4e9b-852c-60f9c6ce69d9'])

    def test_wifi_toggle_validates_boolean(self):
        with patch.object(services, 'command') as run:
            with self.assertRaises(ValueError):
                services.wifi_enabled('off')
            run.assert_not_called()
            services.wifi_enabled(False)
            self.assertEqual(run.call_args.args[0], ['nmcli', '--wait', '8', 'radio', 'wifi', 'off'])

    def test_missing_providers_return_in_page_reason(self):
        with patch.object(services.shutil, 'which', return_value=None), patch.object(services, 'command') as run:
            for reader in (services.network_snapshot, services.bluetooth_snapshot, services.audio_snapshot):
                self.assertIn('missing', reader())
            run.assert_not_called()

    def test_bluetooth_names_and_case(self):
        data = services.bluetooth_devices('Device ab:cd:ef:01:02:03 Mouse: Left\nDevice XX:00:00:00:00:00 invalid\n')
        self.assertEqual(data, {'AB:CD:EF:01:02:03': 'Mouse: Left'})

    def test_bluetooth_reports_errors_even_when_exit_is_zero(self):
        with patch.object(services, 'command', return_value='Failed to connect: org.bluez.Error.Failed\n'):
            with self.assertRaisesRegex(RuntimeError, 'Failed to connect'):
                services.bluetooth_command('connect', 'AA:BB:CC:DD:EE:FF')

    def test_bluetooth_read_does_not_wait_for_cli_timeout(self):
        with patch.object(services, 'command', return_value='Powered: yes\n') as run:
            self.assertEqual(services.bluetooth_command('show'), 'Powered: yes\n')
        run.assert_called_once_with(['bluetoothctl', 'show'], timeout=4)

    def test_bluetooth_no_controller_is_empty_state(self):
        with patch.object(services.shutil, 'which', return_value='/usr/bin/bluetoothctl'), \
             patch.object(services, 'bluetooth_command', return_value='') as run:
            self.assertEqual(services.bluetooth_snapshot(), {'adapter': None, 'devices': []})
            run.assert_called_once_with('list')

    def test_bluetooth_controls_only_accept_addresses(self):
        with patch.object(services, 'bluetooth_command') as run:
            with self.assertRaises(ValueError):
                services.bluetooth_connect('--help', True)
            with self.assertRaises(ValueError):
                services.bluetooth_power(1)
            run.assert_not_called()
            services.bluetooth_connect('aa:bb:cc:dd:ee:ff', True)
            run.assert_called_once_with('connect', 'AA:BB:CC:DD:EE:FF', timeout=8)

    def test_bluetooth_connected_devices_are_first(self):
        responses = ['Controller AA:BB:CC:DD:EE:FF Controller', 'Alias: Controller\nPowered: yes\n',
                     'Device 01:02:03:04:05:06 Alpha\nDevice 01:02:03:04:05:07 Zulu\n',
                     'Device 01:02:03:04:05:07 Zulu\n']
        with patch.object(services.shutil, 'which', return_value='/usr/bin/bluetoothctl'), \
             patch.object(services, 'bluetooth_command', side_effect=responses):
            data = services.bluetooth_snapshot()
        self.assertTrue(data['powered'])
        self.assertEqual([item['name'] for item in data['devices']], ['Zulu', 'Alpha'])
        self.assertTrue(data['devices'][0]['connected'])

    def test_audio_parsing_handles_monitor_and_uneven_channels(self):
        raw = [{'index': 1, 'name': 'speaker.monitor', 'monitor_of_sink': 4},
               {'index': 2, 'name': 'microphone', 'description': 'USB mic', 'monitor_of_sink': 4294967295,
                'mute': True, 'volume': {'left': {'value': 32768}, 'right': {'value': 65536}}}]
        result = services.audio_devices(raw, 'source', 'microphone')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['volume'], 100)
        self.assertTrue(result[0]['default'])
        self.assertTrue(result[0]['mute'])

    def test_audio_actions_are_bounded_and_explicit(self):
        with patch.object(services, 'command') as run:
            for action, value in [('volume', 101), ('volume', float('nan')), ('volume', -1), ('mute', 'toggle'), ('default', '--help')]:
                with self.assertRaises(ValueError):
                    services.audio_change('sink', 4, action, value)
            run.assert_not_called()
            services.audio_change('sink', 4, 'volume', 37.4)
            run.assert_called_with(['pactl', 'set-sink-volume', '4', '37%'])
            services.audio_change('sink', 4, 'default', 'alsa_output.card.stereo')
            run.assert_called_with(['pactl', 'set-default-sink', 'alsa_output.card.stereo'])
            services.audio_change('source', 5, 'mute', True)
            run.assert_called_with(['pactl', 'set-source-mute', '5', '1'])

    def test_power_profiles_ignore_descriptions(self):
        output = '  performance:\n    Driver: cpu\n* balanced:\n    PlatformDriver: placeholder\n  power-saver:\n    Driver: cpu\n'
        self.assertEqual(services.parse_power_profiles(output), ['performance', 'balanced', 'power-saver'])
        with patch.object(services, 'command') as run:
            with self.assertRaises(ValueError):
                services.power_profile('balanced --foo')
            run.assert_not_called()
            services.power_profile('balanced')
            run.assert_called_once_with(['powerprofilesctl', 'set', 'balanced'])

    def test_batteries_ignore_mains_and_bad_sensors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, values in [('AC', {'type': 'Mains'}), ('BAT0', {'type': 'Battery', 'capacity': '71', 'status': 'Discharging'}),
                                 ('BAT1', {'type': 'Battery', 'capacity': 'bad', 'status': 'Unknown'})]:
                folder = root / name
                folder.mkdir()
                for key, value in values.items():
                    (folder / key).write_text(value)
            self.assertEqual(services.batteries(root), [{'name': 'BAT0', 'capacity': 71, 'status': 'Discharging'}])

    def test_power_daemon_failure_does_not_hide_battery(self):
        with patch.object(services.shutil, 'which', return_value='/usr/bin/powerprofilesctl'), \
             patch.object(services, 'batteries', return_value=[{'name': 'BAT0', 'capacity': 90}]), \
             patch.object(services, 'command', side_effect=RuntimeError('unavailable')):
            data = services.power_snapshot()
        self.assertEqual(data['batteries'][0]['capacity'], 90)
        self.assertEqual(data['profile_error'], 'unavailable')

    def test_command_is_noninteractive_and_locale_stable(self):
        complete = subprocess.CompletedProcess(['nmcli'], 0, 'hello', '')
        with patch.object(services.subprocess, 'run', return_value=complete) as run:
            self.assertEqual(services.command(['nmcli', 'status']), 'hello')
        self.assertEqual(run.call_args.kwargs['timeout'], 4)
        self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')
        self.assertEqual(run.call_args.kwargs['stdin'], subprocess.DEVNULL)
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_command_errors_are_bounded(self):
        complete = subprocess.CompletedProcess(['nmcli'], 2, '', 'x' * 5000)
        with patch.object(services.subprocess, 'run', return_value=complete):
            with self.assertRaises(RuntimeError) as error:
                services.command(['nmcli'])
        self.assertEqual(len(str(error.exception)), 1000)

    def test_settings_have_no_external_control_center_launchers(self):
        self.assertFalse(hasattr(services, 'EXTERNAL_TOOLS'))
        self.assertFalse(hasattr(services, 'launch_external'))

    def test_region_read_does_not_change_locale(self):
        with patch.dict(services.os.environ, {'LC_ALL': 'zh_CN.UTF-8', 'LC_MESSAGES': 'en_US.UTF-8', 'LC_TIME': 'en_GB.UTF-8', 'XDG_CURRENT_DESKTOP': 'niri'}), \
             patch.object(services, 'account_snapshot', return_value=None), \
             patch.object(services, 'available_locales', return_value=['zh_CN.utf8']):
            data = services.region_snapshot()
        self.assertEqual(data['language'], 'zh_CN.UTF-8')
        self.assertEqual(data['time'], 'zh_CN.UTF-8')
        self.assertEqual(data['desktop'], 'niri')

    def account(self, **changes):
        result = {'uid': services.os.getuid(), 'name': 'Name', 'language': 'en_US.UTF-8',
                  'formats': '', 'supported': ['name', 'language']}
        result.update(changes)
        return result

    def test_account_discovery_only_current_uid_and_supported_methods(self):
        props = {'type': 'a{sv}', 'data': [{'Uid': {'type': 't', 'data': services.os.getuid()},
                 'IconFile': {'type': 's', 'data': '/tmp/fixture-avatar.png'},
                 'RealName': {'type': 's', 'data': 'Name'}, 'Language': {'type': 's', 'data': 'en_US.UTF-8'}}]}
        xml = '<node><interface name="org.freedesktop.Accounts.User"><method name="SetRealName"><arg type="s" direction="in"/></method><method name="SetLanguage"><arg type="s" direction="in"/></method></interface></node>'
        with patch.object(services.shutil, 'which', return_value='/usr/bin/busctl'), \
             patch.object(services, 'command', side_effect=[json.dumps(props), xml]) as run:
            data = services.account_snapshot()
        self.assertEqual(data['supported'], ['name', 'language'])
        self.assertEqual(data['name'], 'Name')
        self.assertEqual(data['avatar'], '/tmp/fixture-avatar.png')
        self.assertTrue(all(services.account_path() in call.args[0] for call in run.call_args_list))
        self.assertNotIn('SetRealName', run.call_args_list[0].args[0])

    def test_account_wrong_uid_is_rejected(self):
        with patch.object(services, 'command') as run:
            with self.assertRaises(RuntimeError):
                services.apply_account(self.account(uid=services.os.getuid() + 1), {'name': 'Other'})
        run.assert_not_called()

    def test_account_locale_must_be_installed(self):
        with patch.object(services, 'available_locales', return_value=['en_US.utf8']), \
             patch.object(services, 'set_account_field') as write:
            with self.assertRaises(ValueError):
                services.apply_account(self.account(), {'language': 'en_FAKE.UTF-8'})
        write.assert_not_called()

    def test_account_name_rejects_control_characters(self):
        with patch.object(services, 'set_account_field') as write:
            for name in ['', ' ', 'New\nName', 'New\x00Name', 'n' * 129]:
                with self.assertRaises(ValueError):
                    services.apply_account(self.account(), {'name': name})
        write.assert_not_called()

    def test_account_update_accepts_utf8_alias_and_unicode(self):
        with patch.object(services, 'available_locales', return_value=['zh_CN.utf8']), \
             patch.object(services, 'account_snapshot', return_value=self.account()), \
             patch.object(services, 'set_account_field') as write:
            services.apply_account(self.account(), {'name': '秋月', 'language': 'zh_CN.UTF-8'})
        self.assertEqual([call.args for call in write.call_args_list], [('name', '秋月'), ('language', 'zh_CN.UTF-8')])

    def test_account_detects_concurrent_edit_before_write(self):
        with patch.object(services, 'account_snapshot', return_value=self.account(name='Someone changed this')), \
             patch.object(services, 'set_account_field') as write:
            with self.assertRaises(RuntimeError):
                services.apply_account(self.account(), {'name': 'New'})
        write.assert_not_called()

    def test_account_rolls_back_partial_apply(self):
        with patch.object(services, 'available_locales', return_value=['zh_CN.utf8']), \
             patch.object(services, 'account_snapshot', return_value=self.account()), \
             patch.object(services, 'set_account_field', side_effect=[None, RuntimeError('denied'), None]) as write:
            with self.assertRaises(RuntimeError):
                services.apply_account(self.account(), {'name': 'New', 'language': 'zh_CN.UTF-8'})
        self.assertEqual([call.args for call in write.call_args_list], [('name', 'New'), ('language', 'zh_CN.UTF-8'), ('name', 'Name')])

    def test_account_write_uses_current_uid_and_stops_option_parsing(self):
        with patch.object(services, 'command') as run:
            services.set_account_field('name', '--test name')
        args = run.call_args.args[0]
        self.assertEqual(args[args.index('--') + 1], 'call')
        self.assertIn(services.account_path(), args)
        self.assertIn('--allow-interactive-authorization=yes', args)
        self.assertEqual(args[-3:], ['SetRealName', 's', '--test name'])

    def test_current_account_snapshot_decodes_avatar_without_another_service_lookup(self):
        import adws_account_header as header
        with patch.object(services,'account_snapshot',return_value=self.account(avatar='/tmp/service-avatar.png')), \
             patch.object(services,'available_locales',return_value=[]), \
             patch.object(header,'avatar_for_user',return_value=b'fixture png') as decode, \
             patch.object(header,'query_properties') as query:
            data=services.region_snapshot()
        self.assertEqual(data['avatar_png'],b'fixture png')
        decode.assert_called_once_with(services.os.getuid(),'/tmp/service-avatar.png')
        query.assert_not_called()

    def test_region_survives_missing_services(self):
        with patch.object(services, 'account_snapshot', side_effect=RuntimeError('offline')), \
             patch.object(services, 'available_locales', side_effect=RuntimeError('no locale')):
            data = services.region_snapshot()
        self.assertTrue(data['username'])
        self.assertIsNone(data['account'])
        self.assertEqual(data['locales'], [])

    def test_navigation_entries_are_unique_and_translated(self):
        pages = services.available_pages()
        self.assertEqual(len({page[0] for page in pages}), len(pages))
        for _, title, description, _, group, _ in pages:
            self.assertIn(title, services.TRANSLATIONS)
            self.assertIn(description, services.TRANSLATIONS)
            self.assertIn(group, services.TRANSLATIONS)


class AccountPendingTests(unittest.TestCase):
    """Use only mocked AccountsService data; run with Xvfb for GUI coverage."""
    @classmethod
    def setUpClass(cls):
        try:
            import gi
            gi.require_version('Gtk', '3.0')
            from gi.repository import Gtk
            if not Gtk.init_check()[0]:
                raise unittest.SkipTest('GTK display unavailable; run under Xvfb')
            cls.Gtk = Gtk
        except ImportError as exc:
            raise unittest.SkipTest('GTK is unavailable') from exc

    def setUp(self):
        class Host:
            closed = False
            busy = False
            def __init__(self):
                self.dirty = set()
                self.update_footer = Mock()
                self.confirm = Mock(return_value=False)
                self.account_header = Mock()
                self.errors = []
            def mark_dirty(self, group):
                self.dirty.add(group)
                self.update_footer()
            def run_worker(self, job, done):
                try:
                    job()
                except Exception as exc:
                    self.errors.append(exc)
                else:
                    done()
        self.host = Host()
        self.snapshot = {'username': 'test', 'name': 'Test User', 'language': 'en_US.UTF-8',
                         'time': 'en_US.UTF-8', 'numeric': 'en_US.UTF-8', 'desktop': 'niri',
                         'account': {'uid': services.os.getuid(), 'name': 'Test User',
                                     'language': 'en_US.UTF-8', 'formats': '', 'supported': ['name', 'language']},
                         'locales': ['en_US.utf8', 'zh_CN.utf8']}
        self.reader = Mock(side_effect=lambda: copy.deepcopy(self.snapshot))
        self.patch_read = patch.dict(services.READERS, {'region': self.reader})
        self.patch_read.start()
        self.page = services.build_page('region', self.host)
        self.window = self.Gtk.Window()
        self.window.add(self.page)
        self.window.show_all()
        self.controller = self.page.system_service_page
        self.pump()

    def pump(self):
        until = time.monotonic() + .25
        while time.monotonic() < until:
            while self.Gtk.events_pending():
                self.Gtk.main_iteration_do(False)
            time.sleep(.002)

    def tearDown(self):
        self.window.destroy()
        self.pump()
        self.patch_read.stop()

    def test_account_edits_mark_and_restore_global_pending(self):
        self.assertNotIn('region', self.host.dirty)
        name = self.controller.account_inputs['name']
        name.set_text('Changed')
        self.assertIn('region', self.host.dirty)
        self.assertTrue(self.controller.account_apply_button.get_sensitive())
        name.set_text('Test User')
        self.assertNotIn('region', self.host.dirty)
        self.assertFalse(self.controller.account_apply_button.get_sensitive())
        language = self.controller.account_inputs['language']
        language.set_active_id('zh_CN.utf8')
        self.assertIn('region', self.host.dirty)
        language.set_active_id('en_US.utf8')
        self.assertNotIn('region', self.host.dirty)

    def test_refresh_requires_discard_and_preserves_cancelled_edits(self):
        name = self.controller.account_inputs['name']
        name.set_text('Changed')
        before = self.reader.call_count
        self.controller.refresh()
        self.host.confirm.assert_called_once()
        self.assertEqual(self.reader.call_count, before)
        self.assertEqual(name.get_text(), 'Changed')
        self.assertIn('region', self.host.dirty)
        self.host.confirm.return_value = True
        self.controller.refresh(); self.pump()
        self.assertEqual(self.controller.account_inputs['name'].get_text(), 'Test User')
        self.assertNotIn('region', self.host.dirty)

    def test_successful_global_apply_clears_pending_without_discard_prompt(self):
        self.controller.account_inputs['name'].set_text('Changed')
        self.controller.account_inputs['language'].set_active_id('zh_CN.utf8')
        def save(expected, changes):
            self.assertEqual(expected['uid'], services.os.getuid())
            self.snapshot['account'].update(changes)
        after = Mock()
        with patch.object(services, 'apply_account', side_effect=save) as apply:
            self.assertTrue(self.page.apply_pending(after=after))
            apply.assert_called_once()
        self.pump()
        self.assertNotIn('region', self.host.dirty)
        self.host.confirm.assert_not_called()
        self.host.account_header.refresh.assert_called_once_with(force=True)
        after.assert_called_once_with()
        self.assertEqual(self.controller.account_inputs['name'].get_text(), 'Changed')

    def test_failed_save_keeps_pending_and_does_not_run_after(self):
        self.controller.account_inputs['name'].set_text('Changed')
        after = Mock()
        with patch.object(services, 'apply_account', side_effect=RuntimeError('denied')):
            self.page.apply_pending(after=after)
        self.assertIn('region', self.host.dirty)
        self.assertEqual(self.controller.account_inputs['name'].get_text(), 'Changed')
        self.assertEqual(len(self.host.errors), 1)
        after.assert_not_called()
        self.host.confirm.assert_not_called()

    def test_failed_refresh_does_not_lose_pending_edits(self):
        self.controller.account_inputs['name'].set_text('Changed')
        self.host.confirm.return_value = True
        self.reader.side_effect = RuntimeError('service unavailable')
        self.controller.refresh(); self.pump()
        self.assertIn('region', self.host.dirty)
        self.assertEqual(self.controller.account_inputs['name'].get_text(), 'Changed')


class ServiceSwitchGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk
        if not Gtk.init_check()[0]:
            raise unittest.SkipTest('GTK display unavailable; run under Xvfb')
        cls.Gtk = Gtk

    def setUp(self):
        class Host:
            closed = False
            busy = False
            def __init__(self):
                self.confirm = Mock(return_value=True)
                self.errors = []
            def run_worker(self, job, done):
                try:
                    job()
                except Exception as error:
                    self.errors.append(error)
                else:
                    done()
        self.host = Host()
        self.window = self.Gtk.Window()
        commands = patch.object(services, 'command', side_effect=AssertionError('Test attempted a real system command'))
        commands.start(); self.addCleanup(commands.stop)

    def open_page(self, key, data):
        self.data = data
        reader = patch.dict(services.READERS, {key: lambda: copy.deepcopy(self.data)})
        reader.start(); self.addCleanup(reader.stop)
        page = services.build_page(key, self.host)
        self.window.add(page); self.window.show_all()
        self.controller = page.system_service_page
        self.pump()

    def pump(self):
        deadline = time.monotonic()+.25
        while time.monotonic() < deadline:
            while self.Gtk.events_pending():
                self.Gtk.main_iteration_do(False)
            time.sleep(.002)

    def tearDown(self):
        self.window.destroy(); self.pump()

    def network(self):
        self.open_page('network', {'wifi': True, 'devices': [['wlan0','wifi','connected','Home']], 'connections': []})

    def test_initial_wifi_switch_does_not_modify_system(self):
        with patch.object(services, 'wifi_enabled') as operation:
            self.network()
            operation.assert_not_called()
        self.assertTrue(self.controller.wifi_switch.get_active())
        self.assertTrue(self.controller.wifi_switch.get_state())

    def test_cancelled_wifi_disable_restores_both_switch_properties(self):
        self.network(); self.host.confirm.return_value = False
        with patch.object(services, 'wifi_enabled') as operation:
            self.controller.wifi_switch.set_active(False); self.pump()
            operation.assert_not_called()
        self.assertTrue(self.controller.wifi_switch.get_active())
        self.assertTrue(self.controller.wifi_switch.get_state())

    def test_confirmed_wifi_disable_uses_service_result(self):
        self.network()
        def disable(value):
            self.data['wifi'] = value
        with patch.object(services, 'wifi_enabled', side_effect=disable) as operation:
            self.controller.wifi_switch.set_active(False); self.pump()
            operation.assert_called_once_with(False)
        self.assertFalse(self.controller.wifi_switch.get_active())
        self.assertFalse(self.controller.wifi_switch.get_state())

    def test_failed_wifi_change_keeps_confirmed_state(self):
        self.network()
        with patch.object(services, 'wifi_enabled', side_effect=RuntimeError('Denied')):
            self.controller.wifi_switch.set_active(False); self.pump()
        self.assertTrue(self.controller.wifi_switch.get_active())
        self.assertTrue(self.controller.wifi_switch.get_state())
        self.assertEqual(len(self.host.errors), 1)

    def test_bluetooth_enable_does_not_ask_disconnect_confirmation(self):
        self.open_page('bluetooth', {'adapter':'Controller','powered':False,'devices':[]})
        def enable(value):
            self.data['powered'] = value
        with patch.object(services, 'bluetooth_power', side_effect=enable) as operation:
            self.controller.bluetooth_switch.set_active(True); self.pump()
            operation.assert_called_once_with(True)
        self.host.confirm.assert_not_called()
        self.assertTrue(self.controller.bluetooth_switch.get_active())
        self.assertTrue(self.controller.bluetooth_switch.get_state())


if __name__ == '__main__':
    unittest.main()

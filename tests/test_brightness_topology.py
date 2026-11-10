"""Per-output backlight routing against a synthetic Linux sysfs tree."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_quick_backend as backend


class DisplayTopology(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.classes = self.root / 'class'
        for name in ('drm', 'backlight'):
            (self.classes / name).mkdir(parents=True)

    def port(self, card, name, status='connected', enabled='enabled'):
        port = self.root / card / f'{card}-{name}'
        port.mkdir(parents=True)
        (port / 'status').write_text(status)
        (port / 'enabled').write_text(enabled)
        (self.classes / 'drm' / port.name).symlink_to(port)
        return port

    def backlight(self, name, parent):
        device = parent / name
        device.mkdir(parents=True)
        (device / 'brightness').write_text('45')
        (device / 'max_brightness').write_text('90')
        link = self.classes / 'backlight' / name
        link.symlink_to(device)
        return link

    def mapped(self):
        return backend._display_hardware(self.classes)[1]

    def test_two_nonstandard_ports_with_independent_backlights(self):
        second = self.port('card5', 'Bridge-7')
        first = self.port('card2', 'Panel-4')
        b = self.backlight('platform-panel', second)
        a = self.backlight('aux-light', first / 'aux-channel')
        self.assertEqual(self.mapped(), {'Panel-4': [a], 'Bridge-7': [b]})

    def test_platform_backlight_shares_firmware_identity(self):
        port = self.port('card6', 'Unknown-9')
        light = self.backlight('acpi_video3', self.root / 'platform')
        firmware = self.root / 'fw'
        firmware.mkdir()
        (light / 'firmware_node').symlink_to(firmware)
        (port / 'firmware_node').symlink_to(firmware)
        self.assertEqual(self.mapped(), {'Unknown-9': [light]})
        other = self.port('card6', 'LVDS-1')
        (other / 'firmware_node').symlink_to(firmware)
        self.assertEqual(self.mapped(), {})

    def test_external_only_never_inherits_unbound_backlight(self):
        self.port('card0', 'HDMI-A-2')
        self.backlight('platform-light', self.root / 'platform')
        self.assertEqual(self.mapped(), {})
        self.port('card1', 'LVDS-1', 'disconnected', 'disabled')
        self.assertEqual(self.mapped(), {})

    def test_legacy_panel_with_unlinked_backlight(self):
        self.port('card0', 'LVDS-2')
        self.port('card0', 'DP-3')
        light = self.backlight('vendor-light', self.root / 'platform')
        self.assertEqual(self.mapped(), {'LVDS-2': [light]})

    def test_same_connector_name_on_two_gpus_is_ambiguous(self):
        first = self.port('card0', 'DP-2')
        self.port('card9', 'DP-2')
        self.backlight('light-A', first)
        self.assertEqual(self.mapped(), {})

    def test_dock_change_discards_stale_ddc_mapping_even_if_detection_fails(self):
        backend.write_json(self.root / 'ddc.json', {
            'time': backend.time.time(), 'topology': ['card0-DP-2/i2c-4'],
            'devices': {'DP-2': {'display': 1, 'bus': 4}},
        })
        with (
            patch.object(backend, 'cache_root', return_value=self.root),
            patch.object(backend.shutil, 'which', return_value='ddcutil'),
            patch.object(backend, 'ddc_command', side_effect=RuntimeError('disconnected')) as detect,
        ):
            self.assertEqual(backend.ddc_devices(topology=['card0-DP-3/i2c-7']), {})
            detect.assert_called_once()

    def test_enabled_outputs_without_a_compositor_adapter(self):
        panel = self.port('card5', 'Panel-4')
        self.port('card5', 'DP-2', enabled='disabled')
        self.backlight('panel-light', panel)
        topology = backend._display_hardware(self.classes)
        with (
            patch('adws_display.detect_session', return_value=None),
            patch.object(backend, '_display_hardware', return_value=topology),
            patch.object(backend, 'ddc_devices', return_value={}),
            patch.object(backend, 'gamma_state', return_value=None),
            patch.object(backend.shutil, 'which', side_effect=lambda name: name == 'brightnessctl'),
            patch.object(backend, 'cache_root', return_value=self.root),
        ):
            item, = backend._read_brightness()
            self.assertEqual((item['name'], item['device'], item['value']), ('Panel-4', 'panel-light', 50))


if __name__ == '__main__':
    unittest.main()

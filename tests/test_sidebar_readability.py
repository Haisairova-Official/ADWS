import sys
from pathlib import Path
import unittest
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from adws_sidebar import SidebarStyle, ease_out
from adws_panel_options import validate
from adws_settings_style import ROLES


class SidebarReadabilityTests(unittest.TestCase):
    def test_reading_surface_is_translucent_but_readable(self):
        style = object.__new__(SidebarStyle)
        style.host = Mock()
        style.host.weather_surfaces = ()
        style.host.config.read_taskbar_overrides.return_value = (None, (0.1, 0.2, 0.3, 0.1), 16, 'sans', 12)
        roles = {key: fallback for key, (_, fallback) in ROLES.items()}
        options = validate({'surface_color': 'rgba(10,20,30,0.1)', 'window_animations': True})
        css = style.stylesheet(roles, options)
        sidebar = css[css.index('window.adws-sidebar {'):]
        self.assertIn('background-color: rgba(10,20,30,0.66)', sidebar)
        self.assertIn('background-image: none', sidebar)
        self.assertIn('background-color: alpha(@adws_settings_raised,.14)', sidebar)
        self.assertTrue(style.host.motion_settings[0])

    def test_bezier_is_monotonic_and_bounded(self):
        values = [ease_out(x/100) for x in range(101)]
        self.assertAlmostEqual(values[0], 0, places=6)
        self.assertAlmostEqual(values[-1], 1, places=6)
        self.assertEqual(values, sorted(values))
        self.assertGreater(values[50], .8)

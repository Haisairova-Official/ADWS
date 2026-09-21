import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_clock as clock
import adws_layout as layout


class ClockTests(unittest.TestCase):
    def test_time_region_is_independent_of_ui_language(self):
        env = {'LANG': 'zh_CN.UTF-8', 'LANGUAGE': 'zh_CN', 'LC_TIME': 'en_GB.UTF-8'}
        self.assertEqual(clock.time_locale(env), 'en_GB.UTF-8')
        env['LC_ALL'] = 'en_US.UTF-8'
        self.assertEqual(clock.time_locale(env), 'en_US.UTF-8')
        self.assertEqual(clock.time_locale({}), 'C')

    def test_installed_regional_formats_and_missing_locale_fallback(self):
        cases = [('en_US', '%m/%d/%Y', 'mdy'), ('en_GB', '%d/%m/%y', 'dmy'),
                 ('zh_CN', '%Y年%m月%d日', 'iso'), ('ja_JP', '%Y/%m/%d', 'ymd'),
                 ('de_DE', '%d.%m.%Y', 'dots')]
        for region, pattern, expected in cases:
            clock.recommended_format.cache_clear()
            with patch.object(clock.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, f'd_fmt="{pattern}"\n')):
                self.assertEqual(clock.recommended_format(region), expected)
        clock.recommended_format.cache_clear()
        with patch.object(clock.subprocess, 'run', side_effect=FileNotFoundError):
            for region, expected in [('en_US', 'mdy'), ('en_GB', 'dmy'), ('zh_CN', 'iso'), ('de_DE', 'dots'), ('unknown', 'iso')]:
                self.assertEqual(clock.recommended_format(region), expected)
        clock.recommended_format.cache_clear()

    def test_defaults_and_invalid_settings(self):
        for options in ({}, {'clock': []}, {'clock': {'date_format': 'malformed', 'show_seconds': 'false'}}):
            prefs = clock.preferences(options)
            self.assertEqual(clock.display_pattern(prefs), '%H:%M')
            self.assertEqual(prefs['date_format'], 'auto')

    def test_seconds_date_weekday_and_manual_override(self):
        prefs = clock.preferences({'clock': {'show_date': True, 'show_seconds': True,
                                            'show_weekday': True, 'date_format': 'dmy'}})
        with patch.object(clock, 'time_locale', return_value='zh_CN'):
            self.assertEqual(clock.display_pattern(prefs), '%H:%M:%S\n%d/%m/%Y %a')
            self.assertEqual(clock.definition({'clock': prefs}, {}, '/tmp/a path')['interval'], 1)
        prefs['two_lines'] = False
        self.assertEqual(clock.display_pattern(prefs), '%H:%M:%S %d/%m/%Y %a')
        prefs['show_seconds'] = False
        self.assertEqual(clock.definition({'clock': prefs}, {}, '/tmp/a path')['interval'], 60)

    def test_custom_tokens_refresh_and_validation(self):
        self.assertEqual(clock.custom_pattern('YYYYMMDDHHmmSS'), '%Y%m%d%H%M%S')
        self.assertEqual(clock.custom_pattern('HH:mm\nYYYY-MM-DD ddd'), '%H:%M\n%Y-%m-%d %a')
        self.assertEqual(clock.custom_pattern('YYYY年MM月DD日'), '%Y年%m月%d日')
        for text in ('', '\nHH:mm', 'HH\nmm\nSS', '{:%H}', '<b>HH</b>', 'hh:mm', 'Y' * 129):
            with self.assertRaises(ValueError): clock.custom_pattern(text)
        for text, interval in [('HH:mm:SS\nYYYY-MM-DD', 1), ('HH:mm', 60)]:
            options={'clock': {'custom_enabled': True, 'custom_format': text, 'show_seconds': True}}
            self.assertEqual(clock.definition(options, {}, '/tmp')['interval'], interval)

    def test_inherited_old_clicks_and_width_are_overridden(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inherited = {'clock': {'format': '󰥔 {:%H:%M}', 'on-click': 'kclock', 'on-click-right': 'korganizer',
                                   'format-alt': 'ALT', 'actions': {'on-click': 'calendar'},
                                   'menu': 'on-click', 'max-length': 8, 'timezone': 'UTC'}}
            (root/'modules.jsonc').write_text(json.dumps(inherited))
            state = {'options': {'position': 'left', 'clock': {'show_date': True, 'date_format': 'iso'}},
                     'builtins': [{'id': 'clock', 'enabled': True, 'slot': 'right', 'order': 0}], 'plugins': []}
            result = layout.render_waybar_config(state, available=[], base={'include': ['modules.jsonc']}, config_path=root/'config.jsonc')['clock']
            self.assertEqual(result['format'], '<span size="large" weight="bold">{0:%H:%M}</span>\n<span size="small">{0:%Y-%m-%d}</span>')
            self.assertEqual(result['on-click'], '')
            self.assertEqual(result['rotate'], 0)
            self.assertEqual(result['timezone'], 'UTC')
            for key in ('max-length', 'format-alt', 'actions', 'menu'): self.assertIsNone(result[key])
            command = shlex.split(result['on-click-right'])
            self.assertEqual(Path(command[1]).name, 'adws_clock.py')
            self.assertEqual(command[2], '--launch')
            self.assertNotIn('KDE', result['tooltip-format'])
            # Re-rendering must not duplicate the icon or lose the selected date.
            again = layout.render_waybar_config(state, available=[], base={'clock': result}, config_path=root/'config.jsonc')['clock']
            self.assertEqual(again, result)


if __name__ == '__main__': unittest.main()

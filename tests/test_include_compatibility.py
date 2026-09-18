from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from mnws_include import normalize_default_include, update_installed_config
import mnws_layout as layout
from mnws_health import validate_waybar


class IncludeCompatibilityTests(unittest.TestCase):
    def test_default_forms_use_install_location(self):
        with tempfile.TemporaryDirectory(prefix='mnws include ') as folder:
            config = Path(folder) / 'config-bottom.jsonc'
            for value in ('modules.jsonc', ['modules.jsonc'], ['./modules.jsonc'], [str(config.parent / 'modules.jsonc')]):
                with self.subTest(value=value):
                    data = {'include': value}
                    self.assertTrue(normalize_default_include(data, config))
                    self.assertEqual(data['include'], str(config.parent / 'modules.jsonc'))
                    self.assertFalse(normalize_default_include(data, config))

    def test_custom_and_multiple_includes_untouched(self):
        for value in (['modules.jsonc', 'extra.jsonc'], 'custom.jsonc', ['/other/modules.jsonc'], [], None):
            data = {'include': value}
            self.assertFalse(normalize_default_include(data, Path('/config/waybar/config-bottom.jsonc')))
            self.assertEqual(data['include'], value)

    def test_comments_symlink_and_backup_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            target = parent / 'source.jsonc'
            original = '{\n// keep comment\n"include": [/* explanation */ "modules.jsonc",],\n"height": 77, "clock": {"include": "do-not-touch"}\n}\n'
            target.write_text(original)
            config = parent / 'config-bottom.jsonc'
            config.symlink_to(target)
            self.assertTrue(update_installed_config(config))
            self.assertTrue(config.is_symlink())
            self.assertEqual(config.with_name(config.name + '.mnws-include-bak').read_text(), original)
            self.assertIn('// keep comment', config.read_text())
            self.assertIn('/* explanation */', config.read_text())
            parsed = layout.parse_jsonc(config.read_text())
            self.assertEqual(parsed['height'], 77)
            self.assertEqual(parsed['clock']['include'], 'do-not-touch')
            self.assertFalse(update_installed_config(config))

    def test_render_keeps_absolute_include_from_unrelated_cwd(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            config, style = parent / 'config-bottom.jsonc', parent / 'style.css'
            (parent / 'modules.jsonc').write_text('{"custom/applauncher":{"format":"Apps","on-click":"fuzzel"}}')
            style.write_text('')
            data = layout.load_layout()
            data['plugins'] = []
            data['builtins'] = [{'id': key, 'enabled': key == 'start'} for key in layout.BUILTIN_INFO]
            data['options'] = {'start_label': 'Start'}
            with patch.object(layout, 'desktop_space_library_path', return_value=Path('/dev/null')):
                rendered = layout.render_waybar_config(data, available=[], base={'include': ['modules.jsonc']}, config_path=config)
            self.assertEqual(rendered['include'], str(parent / 'modules.jsonc'))
            self.assertEqual(rendered['custom/applauncher']['on-click'], 'fuzzel')
            # Inspect include loading without depending on native component binaries.
            self.assertEqual(validate_waybar(config, style, {'include': rendered['include'], 'modules-left': ['custom/applauncher']}), [])

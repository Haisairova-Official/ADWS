import sys, unittest, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from adws_fonts import with_symbol_fallbacks
from adws_templates import preserve, hashes

class FontFallbacks(unittest.TestCase):
    def test_preserves_text_and_precedes_generic(self):
        css='a { font-family: "Custom Text", sans-serif; }'
        value=with_symbol_fallbacks(css)
        self.assertIn('"Custom Text", "Symbols Nerd Font", "Symbols Nerd Font Mono", sans-serif',value)
        self.assertEqual(value,with_symbol_fallbacks(value))
    def test_inheritance_is_not_a_family_list(self):
        self.assertEqual('a { font-family: inherit; }',with_symbol_fallbacks('a { font-family: inherit, "Symbols Nerd Font"; }'))
    def test_upgrade_keeps_custom_theme_and_migrates_fonts(self):
        with tempfile.TemporaryDirectory() as folder:
            old,new=Path(folder)/'old',Path(folder)/'new'
            for root in (old,new): (root/'config/waybar').mkdir(parents=True)
            file=old/'config/waybar/style-bottom.css'
            file.write_text('a { font-family: "Original"; }')
            baseline=hashes(old)
            file.write_text('a { color: red; font-family: "My Font"; }')
            preserve(old,new,baseline)
            result=(new/'config/waybar/style-bottom.css').read_text()
            self.assertIn('color: red',result);self.assertIn('"My Font", "Symbols Nerd Font"',result)

class CssPreservation(unittest.TestCase):
    def test_commented_inheritance_and_quoted_separators(self):
        for css in ['a {font-family: inherit /* parent */;}',
                    'a {font-family: unset /* global */;}',
                    '/* font-family: fake; */ a {content: "font-family: fake;"; font-family: "A; B", "C,D", sans-serif;}',
                    'a {font-family: "A\\,B", monospace}']:
            value=with_symbol_fallbacks(css)
            self.assertEqual(value,with_symbol_fallbacks(value))
            if '/* parent */' in css or '/* global */' in css:self.assertEqual(css,value)
            else:
                self.assertIn('Symbols Nerd Font',value)
                if '"A; B"' in css:
                    self.assertIn('"A; B", "C,D"',value)
                    self.assertIn('/* font-family: fake; */',value)
                    self.assertIn('content: "font-family: fake;"',value)
            try:
                import gi
                gi.require_version('Gtk','3.0')
                from gi.repository import Gtk
            except (ImportError,ValueError):continue
            # Exclude content, which is not supported by GTK3's CSS dialect.
            if 'content:' not in css:
                Gtk.CssProvider().load_from_data(value.encode())

    def test_concurrent_edit_is_not_overwritten(self):
        from unittest.mock import Mock, patch
        from adws_templates import live_font_changes, apply_font_changes
        import os
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);config=root/'config';folder=config/'waybar';folder.mkdir(parents=True)
            path=folder/'style-bottom.css';path.write_text('a {font-family: sans-serif;}')
            with patch.dict(os.environ,{'XDG_CONFIG_HOME':str(config)}):
                changes=live_font_changes(root/'project')
            path.write_text('a {font-family: "Edited";}')
            publish=Mock();backup=root/'backup';backup.mkdir()
            with self.assertRaises(RuntimeError):apply_font_changes(changes,backup,publish)
            publish.assert_not_called();self.assertEqual(path.read_text(),'a {font-family: "Edited";}')

if __name__=='__main__':unittest.main()

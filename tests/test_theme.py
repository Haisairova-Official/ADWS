import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from adws_theme import css_snapshot, Watch


class ThemeSnapshotTests(unittest.TestCase):
    def test_nested_import_atomic_write_and_symlink_retarget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            css = root / 'gtk.css'
            css.write_text('@import "palette.css";')
            first, second = root / 'a.css', root / 'b.css'
            first.write_text('@define-color accent #f00;')
            second.write_text('@define-color accent #00f;')
            link = root / 'palette.css'
            link.symlink_to(first)
            before = css_snapshot([css])
            link.unlink(); link.symlink_to(second)
            self.assertNotEqual(before, css_snapshot([css]))
            before = css_snapshot([css])
            replacement = root / 'new.css'
            replacement.write_text('@define-color accent #0f0;')
            replacement.replace(second)
            self.assertNotEqual(before, css_snapshot([css]))

    def test_missing_import_and_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            css = Path(tmp) / 'gtk.css'
            css.write_text('@import url("gtk.css"); @import "missing.css";')
            before = css_snapshot([css])
            self.assertEqual(len(before), 2)
            (css.parent / 'missing.css').write_text('@define-color accent #f00;')
            self.assertNotEqual(before, css_snapshot([css]))

    def test_watcher_retries_after_callback_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'colors.css';path.write_text('old')
            watcher=Watch.__new__(Watch);watcher.paths=[path];watcher.snapshot=css_snapshot([path]);watcher.source=1
            with patch.object(watcher,'callback',create=True,side_effect=[ValueError('temporary failure'),True]) as callback:
                path.write_text('new')
                before=watcher.snapshot
                self.assertTrue(watcher.poll())
                self.assertEqual(watcher.snapshot,before)
                self.assertTrue(watcher.poll())
                self.assertEqual(watcher.snapshot,css_snapshot([path]))
                self.assertEqual(callback.call_count,2)

    def test_missing_stylesheet_keeps_last_palette_until_it_returns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'colors.css';path.write_text('old')
            watcher=Watch.__new__(Watch);watcher.paths=[path];watcher.snapshot=css_snapshot([path]);watcher.source=1
            with patch.object(watcher,'callback',create=True,return_value=True) as callback:
                path.unlink();before=watcher.snapshot
                self.assertTrue(watcher.poll());callback.assert_not_called()
                self.assertEqual(watcher.snapshot,before)
                path.write_text('new');self.assertTrue(watcher.poll())
                callback.assert_called_once()

"""Exercise About and its bundled document reader under xvfb-run."""
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gtk, Pango

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import adws_about_page as about


def children(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            yield from children(child)


def view_of(dialog):
    return next(w for w in children(dialog) if isinstance(w, Gtk.TextView))


def text_of(view):
    buf = view.get_buffer()
    return buf.get_text(*buf.get_bounds(), False)


def text_iter(view, phrase):
    offset = text_of(view).index(phrase)
    return view.get_buffer().get_iter_at_offset(offset)


def child_dialog(parent):
    return next(w for w in Gtk.Window.list_toplevels()
                if isinstance(w, Gtk.Dialog) and w.get_transient_for() == parent)


class AboutDocumentTests(unittest.TestCase):
    def setUp(self):
        self.window = Gtk.Window()
        self.addCleanup(self.window.destroy)

    def assert_tag(self, view, phrase, name):
        tags = {tag.props.name: tag for tag in text_iter(view, phrase).get_tags()}
        self.assertIn(name, tags, phrase)
        return tags[name]

    def follow(self, view, phrase):
        view.get_buffer().place_cursor(text_iter(view, phrase))
        key = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        key.keyval = Gdk.KEY_Return
        self.assertTrue(view.emit('key-press-event', key), phrase)

    def open_from_page(self, page, caption):
        button = next(w for w in children(page) if isinstance(w, Gtk.Button) and w.get_label() == caption)
        button.clicked()
        dialog = child_dialog(self.window)
        self.assertEqual(dialog.get_title(), caption)
        self.assertFalse(view_of(dialog).get_editable())
        return dialog

    def close(self, dialog):
        dialog.response(Gtk.ResponseType.CLOSE)
        self.assertNotIn(dialog, Gtk.Window.list_toplevels())

    def test_chinese_documents(self):
        self.check_bundled_documents('zh_CN', '许可全文', '第三方声明', '更新记录')

    def test_english_documents(self):
        self.check_bundled_documents('en_US', 'Full license', 'Third-party notices', 'Changelog')

    def check_bundled_documents(self, locale, license_label, notices_label, changes_label):
        with patch.dict(os.environ, LC_ALL=locale + '.UTF-8', LANGUAGE=locale):
            page = about.build_page(self.window)
            self.window.add(page)
            self.window.show_all()
            labels = [w.get_text() for w in children(page) if isinstance(w, Gtk.Label)]
            self.assertIn('ADWS ' + about.version_text(about.build_info()), labels)
            for text in ('GPL-3.0-or-later', '南雲　あづき', 'Adam Harvey'):
                self.assertTrue(any(text in label for label in labels), text)

            license_text = (ROOT / 'LICENSE').read_text(encoding='utf-8')
            license_dialog = self.open_from_page(page, license_label)
            self.assertEqual(text_of(view_of(license_dialog)), license_text)
            self.close(license_dialog)

            notices = self.open_from_page(page, notices_label)
            view = view_of(notices)
            content = text_of(view)
            heading = self.assert_tag(view, 'Licensing and third-party notices', 'md-h1')
            self.assertGreaterEqual(heading.props.weight, Pango.Weight.BOLD)
            self.assert_tag(view, 'Optional Niri compatibility patch', 'md-h2')
            self.assert_tag(view, 'src/niri-taskbar', 'md-code')
            self.assertIn('components and optional compatibility patch documented above.', content)
            self.assert_tag(view, "derived from Adam Harvey", 'md-item')
            self.assert_tag(view, "LICENSE", 'md-link')
            self.assert_tag(view, "SHORiN-KiWATA/niri", 'md-link')
            for raw in ('# Licensing', '## Optional', '`', '[LICENSE](LICENSE)', '- src/niri-taskbar',
                        '](https://github.com/'):
                self.assertNotIn(raw, content)

            self.follow(view, 'LICENSE')
            nested = child_dialog(notices)
            self.assertEqual(text_of(view_of(nested)), license_text)
            self.close(nested)
            with patch.object(Gtk, 'show_uri_on_window') as launch:
                self.follow(view, 'SHORiN-KiWATA/niri')
                launch.assert_called_once()
                self.assertEqual(launch.call_args.args[1], 'https://github.com/SHORiN-KiWATA/niri')
            self.close(notices)

            changes = self.open_from_page(page, changes_label)
            view = view_of(changes)
            self.assert_tag(view, 'Changelog / 更新记录', 'md-h1')
            self.assert_tag(view, '1.37（构建', 'md-h2')
            self.assert_tag(view, '1.36-B 追加修复', 'md-h3')
            self.assertNotIn('[更新说明与验证范围]', text_of(view))
            self.follow(view, '更新说明与验证范围')
            release = child_dialog(changes)
            self.assert_tag(view_of(release), 'ADWS 1.37 Pre-Release', 'md-h1')
            self.follow(view_of(release), '1.37 被测产物')
            verification = child_dialog(release)
            self.assert_tag(view_of(verification), 'ADWS 1.37 验证记录', 'md-h1')
            self.close(verification)
            self.close(release)
            self.close(changes)
            page.destroy()

    def test_inline_emphasis_and_literal_code(self):
        with TemporaryDirectory() as directory, patch.object(about, 'ROOT', Path(directory)):
            path = Path(directory) / 'sample.md'
            path.write_text('**重要** / *emphasis* / `**literal**`\n', encoding='utf-8')
            dialog = about.show_document(self.window, '第三方声明', path.name)
            view = view_of(dialog)
            self.assertEqual(text_of(view).strip(), '重要 / emphasis / **literal**')
            self.assertGreaterEqual(self.assert_tag(view, '重要', 'md-strong').props.weight, Pango.Weight.BOLD)
            self.assertEqual(self.assert_tag(view, 'emphasis', 'md-emphasis').props.style, Pango.Style.ITALIC)
            self.assert_tag(view, '**literal**', 'md-code')
            self.close(dialog)

    def test_missing_document_uses_localized_error(self):
        with TemporaryDirectory() as directory, patch.object(about, 'ROOT', Path(directory)):
            for locale, expected in [('zh_CN', '无法读取'), ('en_US', 'Could not read')]:
                with self.subTest(locale=locale), patch.dict(os.environ, LC_ALL=locale + '.UTF-8', LANGUAGE=locale):
                    dialog = about.show_document(self.window, '第三方声明', 'missing.md')
                    content = text_of(view_of(dialog))
                    self.assertIn('missing.md', content)
                    self.assertIn(expected, content)
                    self.close(dialog)


if __name__ == '__main__':
    unittest.main()

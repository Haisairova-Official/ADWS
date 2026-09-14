"""Natural Explorer-style ordering and read-only desktop metadata tests."""

from desktop_layer.i18n import tr as _tr, chinese
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gi.repository import Gio

from desktop_layer.model import Entry, scan_desktop, sort_entries


class SortingTests(unittest.TestCase):
    def entry(self, name, *, kind="file", size=0, modified=0, type_name="文件", path=None):
        return Entry(Path(path or "/desktop/" + name), name, Gio.ThemedIcon.new("text-x-generic"),
                     kind, size=size, modified=modified, type_name=type_name)

    def test_numeric_names_sort_naturally_without_mutating_input(self):
        entries = [self.entry(name) for name in ["image10.png", "image2.png", "image1.png"]]
        original = list(entries)
        result = sort_entries(entries)
        self.assertEqual([entry.name for entry in result], ["image1.png", "image2.png", "image10.png"])
        self.assertEqual(entries, original)
        self.assertIsNot(result, entries)
        self.assertIs(result[0], entries[2])

    def test_unicode_casefold_decimal_digits_and_deterministic_ties(self):
        entries = [self.entry(name) for name in ["Straße10", "STRASSE2", "图１２", "图2", "图１", "file2", "file02"]]
        self.assertEqual([entry.name for entry in sort_entries(entries)],
                         ["file02", "file2", "STRASSE2", "Straße10", "图１", "图2", "图１２"])
        same_names = [self.entry("Same", path="/z"), self.entry("Same", path="/a")]
        self.assertEqual([str(entry.path) for entry in sort_entries(same_names)], ["/a", "/z"])

    def test_folder_priority_is_preserved_in_both_directions(self):
        entries = [self.entry("a1"), self.entry("z10", kind="directory"), self.entry("z2", kind="directory"), self.entry("a10")]
        self.assertEqual([entry.name for entry in sort_entries(entries)], ["z2", "z10", "a1", "a10"])
        self.assertEqual([entry.name for entry in sort_entries(entries, descending=True)], ["z10", "z2", "a10", "a1"])
        self.assertEqual([entry.name for entry in sort_entries(entries, folders_first=False)], ["a1", "a10", "z2", "z10"])

    def test_size_modified_and_type_order_with_name_ties(self):
        entries = [self.entry("b10", size=2, modified=40, type_name="文本"),
                   self.entry("a1", size=10, modified=20, type_name="图像"),
                   self.entry("b2", size=2, modified=30, type_name="文本")]
        self.assertEqual([entry.name for entry in sort_entries(entries, "size")], ["b2", "b10", "a1"])
        self.assertEqual([entry.name for entry in sort_entries(entries, "size", descending=True)], ["a1", "b10", "b2"])
        self.assertEqual([entry.name for entry in sort_entries(entries, "modified")], ["a1", "b2", "b10"])
        self.assertEqual([entry.name for entry in sort_entries(entries, "modified", descending=True)], ["b10", "b2", "a1"])
        self.assertEqual([entry.name for entry in sort_entries(entries, "type")], ["a1", "b2", "b10"])

    def test_folders_stay_first_with_descending_size(self):
        entries = [self.entry("large", size=1000), self.entry("folder", kind="directory", size=0), self.entry("small", size=1)]
        self.assertEqual([entry.name for entry in sort_entries(entries, "size", descending=True)], ["folder", "large", "small"])
        self.assertEqual([entry.name for entry in sort_entries(entries, "size", descending=True, folders_first=False)], ["large", "small", "folder"])

    def test_unknown_mode_rejected_and_empty_list_supported(self):
        self.assertEqual(sort_entries([]), [])
        with self.assertRaises(ValueError):
            sort_entries([], "created")


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.desktop = self.root / "Desktop"
        self.desktop.mkdir()

    def test_scan_populates_file_directory_and_launcher_metadata(self):
        text = self.desktop / "notes2.txt"
        text.write_text("hello", encoding="utf-8")
        os.utime(text, (1700000000, 1700000100))
        folder = self.desktop / "folder"
        folder.mkdir()
        (folder / "nested.txt").write_text("not counted")
        app = self.desktop / "app.desktop"
        app.write_text("[Desktop Entry]\nType=Application\nName=Example\nExec=/bin/true\n")
        link = self.desktop / "link.desktop"
        link.write_text("[Desktop Entry]\nType=Link\nName=Website\nURL=https://example.org/\n")
        entries = {entry.path.name: entry for entry in scan_desktop(self.desktop)}
        self.assertEqual(entries["notes2.txt"].size, 5)
        self.assertEqual(entries["notes2.txt"].modified, 1700000100)
        content_type, _ = Gio.content_type_guess("notes2.txt", None)
        self.assertEqual(entries["notes2.txt"].type_name, Gio.content_type_get_description(content_type))
        self.assertEqual(entries["folder"].size, 0)
        self.assertEqual(entries["folder"].type_name, _tr('文件夹'))
        self.assertEqual(entries["app.desktop"].type_name, _tr('应用快捷方式'))
        self.assertEqual(entries["app.desktop"].size, app.stat().st_size)
        self.assertEqual(entries["link.desktop"].type_name, _tr('链接'))
        self.assertEqual(entries["link.desktop"].size, link.stat().st_size)

    def test_symlinks_use_target_metadata_and_broken_links_remain_visible(self):
        target = self.root / "target.txt"
        target.write_bytes(b"x" * 99)
        os.utime(target, (1700000000, 1700000123))
        link = self.desktop / "linked.txt"
        link.symlink_to(target)
        broken = self.desktop / "broken.txt"
        broken.symlink_to(self.root / "absent.txt")
        broken_launcher = self.desktop / "missing.desktop"
        broken_launcher.symlink_to(self.root / "absent.desktop")
        entries = {entry.path.name: entry for entry in scan_desktop(self.desktop)}
        self.assertEqual(entries["linked.txt"].size, 99)
        self.assertEqual(entries["linked.txt"].modified, 1700000123)
        self.assertEqual(entries["broken.txt"].size, broken.lstat().st_size)
        self.assertEqual(entries["broken.txt"].modified, broken.lstat().st_mtime)
        self.assertTrue(entries["broken.txt"].error)
        self.assertTrue(entries["missing.desktop"].error)
        self.assertEqual(entries["missing.desktop"].type_name, _tr('应用快捷方式'))
        self.assertEqual(len(sort_entries(list(entries.values()), "size")), 3)

    def test_disappearing_file_metadata_keeps_safe_defaults(self):
        path = self.desktop / "vanished.txt"
        path.write_text("content")
        original_stat = Path.stat
        original_lstat = Path.lstat

        def stat(candidate, *args, **kwargs):
            if candidate == path:
                raise FileNotFoundError("file disappeared")
            return original_stat(candidate, *args, **kwargs)

        def lstat(candidate, *args, **kwargs):
            if candidate == path:
                raise FileNotFoundError("file disappeared")
            return original_lstat(candidate, *args, **kwargs)

        with patch.object(Path, "stat", stat), patch.object(Path, "lstat", lstat):
            entry = scan_desktop(self.desktop)[0]
        self.assertEqual(entry.size, 0)
        self.assertEqual(entry.modified, 0)
        self.assertTrue(entry.error)
        self.assertTrue(entry.type_name)

    def test_scanning_uses_natural_order_by_default(self):
        for name in ["item10.txt", "item2.txt", "item1.txt"]:
            (self.desktop / name).write_text(name)
        self.assertEqual([entry.name for entry in scan_desktop(self.desktop)], ["item1.txt", "item2.txt", "item10.txt"])


if __name__ == "__main__":
    unittest.main()

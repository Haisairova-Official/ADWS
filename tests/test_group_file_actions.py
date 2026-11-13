"""Check file actions against real temporary files, including concurrent renames."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'src/niri-desktop-layer')]
import gi
gi.require_version('Gtk', '3.0')
from desktop_layer.model import Entry
from adws_group_file_actions import matching_folders, rename_cells, rename_on_disk


class GroupFileActions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.group = Path(self.temp.name) / 'group'
        self.group.mkdir()

    @staticmethod
    def entry(path, kind='file'):
        return Entry(path, path.name, None, kind)

    def test_file_directory_and_symbolic_link_collisions(self):
        path = self.group / 'source'
        path.write_text('original')
        for target in ['taken', 'folder', 'broken']:
            destination = self.group / target
            if target == 'folder':
                destination.mkdir()
            elif target == 'broken':
                destination.symlink_to('missing')
            else:
                destination.write_text('other')
            with self.subTest(target=target), self.assertRaises(FileExistsError):
                rename_on_disk(self.entry(path), target)
            self.assertEqual(path.read_text(), 'original')
        self.assertEqual((self.group / 'taken').read_text(), 'other')
        self.assertTrue((self.group / 'broken').is_symlink())
        self.assertTrue(rename_on_disk(self.entry(self.group/'folder', 'directory'), 'new folder').is_dir())
        for name in ('', '..', '../escaped', '/outside'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                rename_on_disk(self.entry(path), name)

    def test_two_renames_competing_for_one_destination(self):
        entries = []
        for label in ['first', 'second']:
            path = self.group / label
            path.write_text(label)
            entries.append(self.entry(path))
        ready = threading.Barrier(2)
        def compete(entry):
            ready.wait()
            try:
                rename_on_disk(entry, 'destination')
            except FileExistsError:
                return False
            return True
        with ThreadPoolExecutor(2) as pool:
            success = list(pool.map(compete, entries))
        self.assertEqual(success.count(True), 1)
        self.assertEqual((self.group/'destination').read_text(), entries[success.index(True)].name)
        self.assertTrue(entries[success.index(False)].path.is_file())

    def test_restore_launcher_label_with_translations_and_preserve_links(self):
        target = self.group / 'sample.desktop'
        target.write_text('[Desktop Entry]\n# Keep this comment\nType=Application\nName=Sample\nName[zh_CN]=样本\nExec=true\n')
        target.chmod(0o751)
        entry = self.entry(target, 'application')
        self.assertEqual(rename_on_disk(entry, '新名称'), target)
        data = target.read_text()
        self.assertIn('Name=新名称', data)
        self.assertIn('Name[zh_CN]=新名称', data)
        self.assertIn('# Keep this comment', data)
        self.assertIn('Exec=true', data)
        self.assertEqual(target.stat().st_mode & 0o777, 0o751)
        link = self.group / 'shortcut.desktop'
        link.symlink_to(target)
        moved = rename_on_disk(self.entry(link, 'application'), 'renamed.desktop')
        self.assertTrue(moved.is_symlink())
        self.assertFalse(link.exists())
        self.assertEqual(target.read_text(), data)

    def test_each_group_keeps_its_own_cell(self):
        alias = self.group.parent/'alias'
        alias.symlink_to(self.group, target_is_directory=True)
        rows = [{'directory': str(self.group), 'cells': {'item': [1, 5]}},
                {'directory': str(self.group), 'cells': {'item': [0, 1], 'renamed': [5, 2]}},
                {'directory': str(self.group.parent), 'cells': {'item': [3, 6]}},
                {'directory': str(alias), 'cells': {'item': [8, 2]}}]
        folders = matching_folders({Path(row['directory']) for row in rows}, self.group)
        rename_cells(rows, self.group/'item', self.group/'renamed', folders)
        self.assertEqual([row['cells'] for row in rows],
                         [{'renamed': [1, 5]}, {'renamed': [0, 1]}, {'item': [3, 6]}, {'renamed': [8, 2]}])


if __name__ == '__main__':
    unittest.main()

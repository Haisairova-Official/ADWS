import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_install_migration as migration


class PersonalMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source, self.target = self.base/'old', self.base/'new'
        self.source.mkdir(); self.target.mkdir()

    def put(self, root, relative, content):
        path = root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def plan(self, categories=('avatar',), **kwargs):
        return migration.plan_migration(self.source, self.target, categories, **kwargs)

    def test_schema_manifest_and_hardware_session_exclusions(self):
        self.put(self.source, '.face', b'avatar')
        self.put(self.source, '.config/niri/config.kdl', b'output "DP-1" {}')
        self.put(self.source, '.profile', b'export GBM_BACKEND=nvidia-drm')
        self.put(self.source, '.bashrc', b'export DISPLAY=:1')
        manifest = migration.inventory(self.source)
        self.assertEqual(manifest['schema_version'], migration.SCHEMA_VERSION)
        self.assertEqual([x['path'] for x in manifest['files']], ['.face'])
        self.assertEqual({x['path'] for x in manifest['excluded']}, {'.config/niri', '.profile', '.bashrc'})
        self.assertEqual(manifest['account']['status'], 'requires_account_service_selection')
        self.assertIn('nickname', manifest['categories'])

    def test_shell_aliases_require_per_file_review_and_are_not_executed(self):
        marker = self.base/'should-not-exist'
        self.put(self.source, '.bash_aliases', f'touch {marker}\nalias ll="ls -l"'.encode())
        self.assertFalse(self.plan(('aliases',))['entries'])
        plan = self.plan(('aliases',), approved_paths=['.bash_aliases'])
        migration.apply_migration(plan, self.base/'backup')
        self.assertTrue((self.target/'.bash_aliases').exists())
        self.assertFalse(marker.exists())

    def test_preserve_existing_then_explicit_overwrite_and_rollback(self):
        self.put(self.source, '.face', b'new avatar')
        self.put(self.target, '.face', b'existing avatar')
        plan = self.plan()
        self.assertFalse(plan['entries']); self.assertEqual(len(plan['conflicts']), 1)
        plan = self.plan(overwrite_paths=['.face'])
        result = migration.apply_migration(plan, self.base/'backup')
        self.assertEqual(result['copied'], ['.face'])
        self.assertEqual((self.target/'.face').read_bytes(), b'new avatar')
        result = migration.rollback(self.base/'backup')
        self.assertEqual(result['status'], 'rolled_back')
        self.assertEqual((self.target/'.face').read_bytes(), b'existing avatar')
        self.assertFalse(migration.rollback(self.base/'backup')['conflicts'])

    def test_rollback_preserves_edits_after_migration(self):
        self.put(self.source, '.face', b'original import')
        migration.apply_migration(self.plan(), self.base/'backup')
        (self.target/'.face').write_bytes(b'user edit')
        report = migration.rollback(self.base/'backup')
        self.assertEqual(report['status'], 'rollback_conflicts')
        self.assertEqual((self.target/'.face').read_bytes(), b'user edit')

    def test_identical_files_skipped_and_new_directories_removed_on_rollback(self):
        relative = '.local/share/fonts/Personal.ttf'
        self.put(self.source, relative, b'font')
        plan = self.plan(('fonts',))
        migration.apply_migration(plan, self.base/'backup')
        self.assertEqual(self.plan(('fonts',))['skipped'][0]['reason'], 'identical')
        migration.rollback(self.base/'backup')
        self.assertFalse((self.target/'.local').exists())

    def test_symlink_source_or_destination_is_never_followed(self):
        outside = self.put(self.base, 'outside', b'secret')
        (self.source/'.face').symlink_to(outside)
        self.assertFalse(self.plan()['entries'])
        (self.source/'.face').unlink(); self.put(self.source, '.face', b'avatar')
        (self.target/'.face').symlink_to(outside)
        self.assertFalse(self.plan(overwrite_paths=['.face'])['entries'])
        self.assertEqual(outside.read_bytes(), b'secret')

    def test_symlink_ancestor_and_symlink_tree_rejected(self):
        outside = self.base/'outside'; outside.mkdir()
        self.put(outside, 'avatar.png', b'outside')
        (self.source/'.themes').symlink_to(outside)
        self.assertFalse(self.plan(('themes',))['entries'])
        (self.source/'.themes').unlink()
        self.put(self.source, '.themes/theme/style.css', b'css')
        (self.target/'.themes').symlink_to(outside)
        self.assertFalse(self.plan(('themes',))['entries'])

    def test_path_traversal_and_disallowed_paths_rejected(self):
        for path in ['../escape', '/tmp/escape', '.config/niri/config.kdl', '.themes/../escape']:
            with self.subTest(path=path):
                plan = self.plan(); plan['entries'] = [{'path': path}]
                with self.assertRaises(ValueError):
                    migration.apply_migration(plan, self.base/'backup')
        self.assertFalse((self.base/'backup').exists())

    def test_changes_since_review_stop_before_any_copy(self):
        self.put(self.source, '.face', b'avatar')
        plan = self.plan()
        (self.source/'.face').write_bytes(b'changed')
        with self.assertRaises(ValueError): migration.apply_migration(plan, self.base/'backup')
        self.assertFalse((self.target/'.face').exists())
        plan = self.plan(); self.put(self.target, '.face', b'unreviewed target')
        with self.assertRaises(ValueError): migration.apply_migration(plan, self.base/'backup')
        self.assertEqual((self.target/'.face').read_bytes(), b'unreviewed target')

    def test_backup_names_do_not_collide_or_reuse_directory(self):
        self.put(self.source, '.themes/a/same.css', b'one')
        self.put(self.source, '.themes/b/same.css', b'two')
        self.put(self.target, '.themes/a/same.css', b'previous one')
        self.put(self.target, '.themes/b/same.css', b'previous two')
        plan = self.plan(('themes',), overwrite_paths=['.themes/a/same.css', '.themes/b/same.css'])
        migration.apply_migration(plan, self.base/'backup')
        self.assertEqual((self.base/'backup/0.original').read_bytes(), b'previous one')
        self.assertEqual((self.base/'backup/1.original').read_bytes(), b'previous two')
        self.assertEqual(migration.rollback(self.base/'backup')['status'], 'rolled_back')
        with self.assertRaises(FileExistsError): migration.apply_migration(plan, self.base/'backup')

    def test_partial_failure_rolls_back_previous_writes(self):
        self.put(self.source, '.face', b'new')
        self.put(self.source, '.face.icon', b'second')
        self.put(self.target, '.face', b'old')
        real_write = migration._write_atomic
        def write(path, *args, **kwargs):
            if path == self.target/'.face.icon': raise OSError('fixture disk full')
            return real_write(path, *args, **kwargs)
        with patch.object(migration, '_write_atomic', side_effect=write):
            with self.assertRaises(OSError):
                migration.apply_migration(self.plan(overwrite_paths=['.face']), self.base/'backup')
        self.assertEqual((self.target/'.face').read_bytes(), b'old')
        self.assertFalse((self.target/'.face.icon').exists())
        journal = json.loads((self.base/'backup/migration.json').read_text())
        self.assertEqual(journal['status'], 'rolled_back')

    def test_conflicts_and_unreviewed_files_are_not_reported_complete(self):
        self.put(self.source, '.face', b'import')
        self.put(self.target, '.face', b'keep')
        report = migration.apply_migration(self.plan(), self.base/'backup')
        self.assertEqual(report['status'], 'needs_review')
        self.assertEqual((self.target/'.face').read_bytes(), b'keep')

    def test_large_batches_are_rejected_before_mutation(self):
        self.put(self.source, '.face', b'1234567890')
        with patch.object(migration, 'MAX_TOTAL_BYTES', 5):
            with self.assertRaises(ValueError): migration.apply_migration(self.plan(), self.base/'backup')
        self.assertFalse((self.target/'.face').exists())
        self.assertFalse((self.base/'backup').exists())

    def test_unknown_schema_or_category_is_rejected(self):
        with self.assertRaises(ValueError): self.plan(('niri-output',))
        plan = self.plan(); plan['schema_version'] = 100
        with self.assertRaises(ValueError): migration.apply_migration(plan, self.base/'backup')


if __name__ == '__main__': unittest.main()

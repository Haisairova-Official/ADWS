"""Real-file regressions for registered installation path changes."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import adws_install_source_migration as migration
from adws_install_transaction import Snapshot
from adws_desktop_groups_model import new_group


class SourceMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='adws-source-move-')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.old = self.home/'old source'; self.new = self.home/'新的 ADWS'
        for root in (self.old, self.new):
            (root/'src/niri-desktop-layer').mkdir(parents=True)
            (root/'adws').write_text('# fixture launcher\n')
            (root/'src/niri-desktop-layer/desktop-layer').write_text('# fixture desktop\n')
        self.state = self.home/'state'
        self.inventory = self.state/'adws/install-record.json'
        self.inventory.parent.mkdir(parents=True)
        self.inventory.write_text(json.dumps({'root': str(self.old), 'installation_role': 'installed'}))
        self.source = self.old/migration.STATE_RELATIVE
        self.source.mkdir()
        self.target = self.new/migration.STATE_RELATIVE
        self.desktop = self.home/'Desktop'; self.desktop.mkdir()
        self.layout = {'version': 1, 'positions': {'display:0': {str(self.desktop/'note.txt'): [2, 1]}},
                       'preferences': {'show_hidden': True, 'sort_descending': True}}
        self.group = new_group(self.desktop, name='Migration proof')
        self.group.update(x=.25, y=.15, width=400, height=280, columns=5, cells={'note.txt': [2, 1]})
        self.groups = {'version': 1, 'default_monitor': 'primary', 'groups': [self.group]}
        self.write_states()
        self.argv = ['python3', str(self.old/'src/niri-desktop-layer/desktop-layer'),
                     '--state', str(self.source/'layout.json')]

    def write_states(self):
        (self.source/'layout.json').write_text(json.dumps(self.layout, ensure_ascii=False))
        (self.source/'desktop-groups.json').write_text(json.dumps(self.groups, ensure_ascii=False))

    def plan(self, **kwargs):
        return migration.plan(self.new, state_home=self.state, runtime=kwargs.pop('runtime', []), **kwargs)

    def test_read_only_plan_lists_exact_runtime_files_and_keeps_originals(self):
        before = {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        proposal = self.plan(runtime=[{'pid': 42, 'argv': self.argv}])
        self.assertEqual(proposal['status'], 'ready')
        self.assertEqual(proposal['previous_root'], str(self.old))
        self.assertEqual({Path(r['source']).name for r in proposal['files']}, set(migration.STATE_NAMES))
        self.assertEqual(proposal['snapshot_targets'], [str(self.target)])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()})
        result = migration.apply(proposal, self.home/'backup', runtime=[])
        self.assertEqual(result['status'], 'copied')
        self.assertTrue(result['originals_retained'])
        for name in migration.STATE_NAMES:
            self.assertEqual((self.source/name).read_bytes(), (self.target/name).read_bytes())
            self.assertEqual((self.target/name).stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads((self.target/'desktop-groups.json').read_text())['groups'][0], self.group)

    def test_final_runtime_write_after_review_is_preserved(self):
        proposal = self.plan()
        self.layout['positions']['display:0'][str(self.desktop/'note.txt')] = [4, 2]
        self.group.update(x=.65, y=.75)
        self.write_states()
        result = migration.apply(proposal, self.home/'backup', runtime=[])
        self.assertEqual(json.loads((self.target/'layout.json').read_text()), self.layout)
        self.assertEqual(json.loads((self.target/'desktop-groups.json').read_text())['groups'][0]['x'], .65)
        self.assertEqual((self.home/'backup/layout.json').read_bytes(), (self.target/'layout.json').read_bytes())
        self.assertEqual(len(result['files']), 2)

    def test_group_first_created_during_shutdown_is_included(self):
        (self.source/'desktop-groups.json').unlink()
        proposal = self.plan()
        (self.source/'desktop-groups.json').write_text(json.dumps(self.groups))
        migration.apply(proposal, self.home/'backup', runtime=[])
        self.assertEqual(json.loads((self.target/'desktop-groups.json').read_text()), self.groups)

    def test_runtime_must_be_stopped_and_belong_to_registered_root(self):
        proposal = self.plan()
        with self.assertRaisesRegex(ValueError, 'must stop'):
            migration.apply(proposal, self.home/'backup', runtime=[{'argv': self.argv}])
        other = list(self.argv); other[1] = str(self.new/'src/niri-desktop-layer/desktop-layer')
        self.assertEqual(self.plan(runtime=[{'argv': other}])['status'], 'blocked')
        for state in (str(self.home/'custom.json'), ''):
            command = self.argv[:-2] + (['--state', state] if state else [])
            self.assertEqual(self.plan(runtime=[{'argv': command}])['status'], 'blocked')
        self.assertFalse(self.target.exists())

    def test_conflicting_or_new_target_is_never_overwritten(self):
        proposal = self.plan()
        self.target.mkdir(); (self.target/'layout.json').write_text('personal contents')
        with self.assertRaisesRegex(ValueError, 'target changed'):
            migration.apply(proposal, self.home/'backup', runtime=[])
        self.assertEqual((self.target/'layout.json').read_text(), 'personal contents')
        blocked = self.plan()
        self.assertEqual(blocked['status'], 'blocked')
        self.assertIn('different desktop state', blocked['conflicts'][0]['detail'])

    def test_identical_destination_may_receive_final_reviewed_source_state(self):
        self.target.mkdir()
        for name in migration.STATE_NAMES: (self.target/name).write_bytes((self.source/name).read_bytes())
        proposal = self.plan()
        self.group['x'] = .75; self.write_states()
        migration.apply(proposal, self.home/'backup', runtime=[])
        self.assertEqual(json.loads((self.target/'desktop-groups.json').read_text())['groups'][0]['x'], .75)

    def test_outer_failure_rollback_removes_new_state_and_resume_reuses_plan(self):
        proposal = self.plan()
        directory = self.home/'snapshot'; directory.mkdir()
        snapshot = Snapshot(directory, [Path(p) for p in proposal['snapshot_targets']])
        migration.apply(proposal, self.home/'backup', runtime=[])
        snapshot.restore()
        self.assertFalse(self.target.exists())
        self.assertEqual(json.loads((self.source/'desktop-groups.json').read_text()), self.groups)
        migration.apply(proposal, self.home/'retry', runtime=[])
        self.assertTrue((self.target/'desktop-groups.json').exists())

    def test_inventory_drift_invalidates_approval(self):
        proposal = self.plan()
        self.inventory.write_text(json.dumps({'root': str(self.new)}))
        with self.assertRaisesRegex(ValueError, 'inventory changed'):
            migration.apply(proposal, self.home/'backup', runtime=[])
        self.assertFalse(self.target.exists())

    def test_same_path_and_unregistered_clean_install_are_noops(self):
        proposal = migration.plan(self.old, state_home=self.state, runtime=[])
        self.assertEqual(proposal['status'], 'none')
        self.inventory.unlink()
        proposal = self.plan()
        self.assertEqual(migration.apply(proposal, self.home/'unused', runtime=[])['status'], 'unchanged')
        self.assertFalse((self.home/'unused').exists())
        self.assertEqual(self.plan(runtime=[{'argv': self.argv}])['status'], 'blocked')

    def test_missing_registered_root_blocks_silent_fresh_layout(self):
        (self.old/'adws').unlink()
        proposal = self.plan()
        self.assertEqual(proposal['status'], 'blocked')
        self.assertIn('unavailable', proposal['conflicts'][0]['detail'])

    def test_source_symlink_and_unknown_file_require_review(self):
        path = self.source/'layout.json'; data = path.read_bytes(); path.unlink()
        outside = self.home/'outside'; outside.write_bytes(data); path.symlink_to(outside)
        self.assertEqual(self.plan()['status'], 'blocked')
        path.unlink(); path.write_bytes(data)
        (self.source/'desktop-widgets.json').write_text('{"version":1,"instances":[]}')
        proposal = self.plan()
        self.assertEqual(proposal['status'], 'blocked')
        self.assertIn('Unrecognized files', proposal['conflicts'][0]['detail'])
        self.assertTrue(outside.exists())

    def test_resource_paths_within_old_source_need_separate_review(self):
        for field, value in (('background_image', str(self.old/'samples/wallpaper.png')),
                             ('directory', str(self.old/'my desktop'))):
            with self.subTest(field=field):
                original = self.group[field]; self.group[field] = value; self.write_states()
                proposal = self.plan()
                self.assertEqual(proposal['status'], 'blocked')
                self.assertIn('resource in old installation', proposal['conflicts'][0]['detail'])
                self.group[field] = original
        self.group['background_image'] = str(self.home/'Pictures/My picture.png'); self.write_states()
        proposal = self.plan()
        migration.apply(proposal, self.home/'backup', runtime=[])
        self.assertEqual(json.loads((self.target/'desktop-groups.json').read_text())['groups'][0]['background_image'], self.group['background_image'])

    def test_final_state_schema_and_resources_are_revalidated(self):
        proposal = self.plan()
        self.group['background_image'] = str(self.old/'new image.png'); self.write_states()
        with self.assertRaisesRegex(ValueError, 'resource in old installation'):
            migration.apply(proposal, self.home/'backup', runtime=[])
        self.group['background_image'] = ''; self.write_states()
        (self.source/'layout.json').write_text('{broken')
        with self.assertRaises(ValueError): migration.apply(proposal, self.home/'backup', runtime=[])
        self.assertFalse(self.target.exists())

    def test_preexisting_xdg_configuration_and_external_desktop_files_untouched(self):
        config = self.home/'config/adws'; config.mkdir(parents=True)
        paths = [config/'desktop-widgets.json', config/'desktop.json', self.desktop/'note.txt']
        for p in paths: p.write_text('user data; unchanged')
        migration.apply(self.plan(), self.home/'backup', runtime=[])
        for p in paths: self.assertEqual(p.read_text(), 'user data; unchanged')

    def test_final_source_edit_during_staging_is_not_silently_lost(self):
        import adws_atomic
        proposal = self.plan()
        original = adws_atomic.stage
        def changed_after_read(path, content, mode):
            temporary = original(path, content, mode)
            self.group['x'] = .99
            self.write_states()
            return temporary
        with patch.object(adws_atomic, 'stage', side_effect=changed_after_read):
            with self.assertRaisesRegex(ValueError, 'changed while staging'):
                migration.apply(proposal, self.home/'backup', runtime=[])
        self.assertFalse((self.target/'layout.json').exists())
        self.assertEqual(json.loads((self.source/'desktop-groups.json').read_text())['groups'][0]['x'], .99)

    def test_exclusive_creation_rejects_target_created_in_commit_gap(self):
        proposal = self.plan()
        original_link = os.link
        def racing_link(source, target):
            Path(target).write_text('concurrent target')
            return original_link(source, target)
        with patch.object(migration.os, 'link', side_effect=racing_link):
            with self.assertRaises(FileExistsError): migration.apply(proposal, self.home/'backup', runtime=[])
        self.assertEqual((self.target/'layout.json').read_text(), 'concurrent target')
        self.assertEqual(json.loads((self.source/'layout.json').read_text()), self.layout)


if __name__ == '__main__': unittest.main()

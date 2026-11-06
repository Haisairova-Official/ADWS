"""A source install must not keep loading its previous directory's library."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_layout as layout
import adws_install_source_migration as source
import adws_install_topbar_migration as relocation
from adws_install_transaction import Snapshot


class DesktopSpaceLibraryMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='adws-library-move-')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.old = self.home / '旧 source'
        self.new = self.home / 'new source'
        self.config = self.home / 'custom XDG config'
        self.state = self.home / 'custom XDG state'
        self.relative = Path('src/niri-desktop-layer/integration/libwaybar-space.so')
        self.installed = self.home / '.local/lib/waybar/libwaybar-space.so'
        for root in (self.old, self.new):
            (root / self.relative).parent.mkdir(parents=True)
            (root / self.relative).write_bytes(b'inert source artifact ' + root.name.encode())
            (root / 'adws').write_text('# fixture launcher')
            (root / 'src/niri-desktop-layer/desktop-layer').write_text('# fixture desktop')
        self.inventory = self.state / 'adws/install-record.json'
        self.inventory.parent.mkdir(parents=True)
        self.inventory.write_text(json.dumps({'root': str(self.old)}))
        self.migration = source.plan(self.new, state_home=self.state, runtime=[])
        self.live = self.config / 'waybar/config-bottom.jsonc'
        self.live.parent.mkdir(parents=True)
        self.saved_layout = self.config / 'adws/taskbar-layout.json'
        self.saved_layout.parent.mkdir(parents=True)
        self.saved_layout.write_text(json.dumps(layout.default_layout()))
        self.env = patch.dict(os.environ, {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.config),
                                          'XDG_STATE_HOME': str(self.state)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.root_patch = patch.object(layout, 'PROJECT_ROOT', self.new)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.base = {'height': 47, 'spacing': 8, 'custom/own': {'module_path': '/keep/this.so'},
                     layout.INTERNAL_SPACE_MODULE: {'module_path': str(self.old / self.relative), 'panel_mode': 'dock'}}
        self.write_base(self.base)

    def write_base(self, data):
        self.live.write_text('// user formatting stays\n' + json.dumps(data, ensure_ascii=False, indent=3) + '\n')

    def plan(self):
        return layout.desktop_space_relocation_plan(self.config, self.migration, home=self.home)

    def render(self, state=None):
        return layout.render_waybar_config(state or layout.default_layout(), available=[],
                                          base=layout.parse_jsonc(self.live.read_text()), config_path=self.live)

    def install_library(self):
        self.installed.parent.mkdir(parents=True, exist_ok=True)
        self.installed.write_bytes(b'inert newly installed artifact')

    def test_plan_apply_render_relocates_only_proven_default_then_old_tree_can_go(self):
        before = self.live.read_text()
        proposal = self.plan()
        self.assertEqual(proposal['status'], 'ready', proposal['conflicts'])
        self.assertEqual(self.live.read_text(), before)  # Preview is read-only.
        self.assertEqual(proposal['snapshot_targets'], [str(self.live)])
        self.assertEqual(proposal['restart_profiles'], [])  # Outer transaction owns the bottom bar.
        self.assertNotIn(str(self.installed), proposal['source_hashes'])
        self.assertIn(str(self.saved_layout), proposal['source_hashes'])
        self.install_library()  # Native preparation is allowed after plan approval.
        relocation.apply(proposal, self.home / 'migration-backup')
        expected = before.replace(json.dumps(str(self.old / self.relative), ensure_ascii=False),
                                  json.dumps(str(self.installed), ensure_ascii=False))
        self.assertEqual(self.live.read_text(), expected)
        self.assertTrue((self.home / 'migration-backup/plan.json').is_file())
        shutil.rmtree(self.old)
        rendered = self.render()
        self.assertEqual(rendered[layout.INTERNAL_SPACE_MODULE]['module_path'], str(self.installed))
        self.assertEqual(self.installed.read_bytes(), b'inert newly installed artifact')
        self.assertEqual(rendered['custom/own'], self.base['custom/own'])

    def test_explicit_layout_override_wins_over_base_during_real_render(self):
        for override in ('~/custom/my-space.so', '$MY_SPACE_LIBRARY', str(self.old / self.relative)):
            with self.subTest(override=override):
                state = layout.default_layout()
                state['options']['desktop_space_library'] = override
                self.saved_layout.write_text(json.dumps(state))
                before = self.live.read_bytes()
                proposal = self.plan()
                self.assertEqual(proposal['status'], 'none')
                self.assertEqual(proposal['files'], {})
                rendered = self.render(state)
                self.assertEqual(rendered[layout.INTERNAL_SPACE_MODULE]['module_path'], str(Path(override).expanduser()))
                self.assertEqual(self.live.read_bytes(), before)

    def test_custom_environment_unregistered_and_stable_paths_are_preserved(self):
        values = ['/opt/custom/libwaybar-space.so', '$ADWS_CUSTOM_LIB', '${HOME}/my-space.so',
                  str(self.home / 'unregistered' / self.relative), str(self.installed),
                  str(self.old / 'src/niri-desktop-layer/integration/custom-space.so')]
        for value in values:
            with self.subTest(value=value):
                base = copy.deepcopy(self.base)
                base[layout.INTERNAL_SPACE_MODULE]['module_path'] = value
                self.write_base(base)
                before = self.live.read_bytes()
                proposal = self.plan()
                self.assertEqual(proposal['status'], 'none')
                self.assertEqual(self.render()[layout.INTERNAL_SPACE_MODULE]['module_path'], value)
                self.assertEqual(self.live.read_bytes(), before)

    def test_runtime_does_not_reinterpret_old_source_without_review(self):
        self.install_library()
        self.assertEqual(self.render()[layout.INTERNAL_SPACE_MODULE]['module_path'], str(self.old / self.relative))
        self.assertEqual(layout.desktop_space_relocation_plan(self.config, None, home=self.home)['status'], 'none')

    def test_default_without_base_prefers_installed_library_for_both_build_methods(self):
        self.assertTrue((self.new / self.relative).exists())
        for contents in (b'source-built artifact', b'prebuilt artifact'):
            with self.subTest(build=contents):
                self.install_library()
                self.installed.write_bytes(contents)
                cfg = layout.render_waybar_config(layout.default_layout(), available=[], base={})
                self.assertEqual(cfg[layout.INTERNAL_SPACE_MODULE]['module_path'], str(self.installed))
        self.installed.unlink()
        self.assertEqual(layout.desktop_space_library_path({}, {}), self.new / self.relative)
        (self.new / self.relative).unlink()
        self.assertEqual(layout.desktop_space_library_path({}, {}), self.installed)

    def historical_baseline(self):
        directory = self.state / 'adws-install-backups/install-proven'
        directory.mkdir(parents=True)
        Snapshot(directory, [self.inventory])
        self.inventory.write_text(json.dumps({'root': str(self.new)}))
        self.migration = source.plan(self.new, state_home=self.state, runtime=[])
        return directory

    def test_same_root_reinstall_repairs_a_historical_source_reference(self):
        directory = self.historical_baseline()
        proposal = self.plan()
        self.assertEqual(proposal['status'], 'ready', proposal['conflicts'])
        self.assertEqual(proposal['reviewed_roots'][0]['kind'], 'installer-snapshot')
        self.assertIn(str(directory / 'manifest.json'), proposal['source_hashes'])
        self.assertIn(str(directory / '0'), proposal['source_hashes'])
        self.install_library()
        relocation.apply(proposal, self.home / 'historical-backup')
        self.assertEqual(self.render()[layout.INTERNAL_SPACE_MODULE]['module_path'], str(self.installed))

    def test_missing_or_forged_history_does_not_claim_custom_source(self):
        directory = self.historical_baseline()
        saved = directory / '0'
        outside = self.home / 'fake-record'
        outside.write_bytes(saved.read_bytes())
        rows = json.loads((directory / 'manifest.json').read_text())
        rows[0]['backup'] = str(outside)
        (directory / 'manifest.json').write_text(json.dumps(rows))
        self.assertEqual(self.plan()['status'], 'none')
        rows[0]['backup'] = str(saved)
        (directory / 'manifest.json').write_text(json.dumps(rows))
        saved.unlink()
        saved.symlink_to(outside)
        self.assertEqual(self.plan()['status'], 'none')

    def test_approved_file_and_override_drift_block_before_any_write(self):
        for changed in ('config', 'layout', 'inventory'):
            with self.subTest(changed=changed):
                proposal = self.plan()
                path = {'config': self.live, 'layout': self.saved_layout, 'inventory': self.inventory}[changed]
                before = path.read_bytes()
                path.write_bytes(before + b'\n')
                with self.assertRaises(ValueError):
                    relocation.apply(proposal, self.home / ('never-' + changed))
                self.assertFalse((self.home / ('never-' + changed)).exists())
                path.write_bytes(before)

    def test_historical_evidence_drift_blocks_before_write(self):
        directory = self.historical_baseline()
        proposal = self.plan()
        (directory / '0').write_text('{"root":"/other/source"}')
        with self.assertRaises(ValueError):
            relocation.apply(proposal, self.home / 'never')
        self.assertEqual(self.render()[layout.INTERNAL_SPACE_MODULE]['module_path'], str(self.old / self.relative))

    def test_links_invalid_layout_and_duplicate_keys_are_review_conflicts(self):
        original = self.live.read_text()
        outside = self.home / 'external-config'
        outside.write_text(original)
        self.live.unlink()
        self.live.symlink_to(outside)
        self.assertEqual(self.plan()['status'], 'blocked')
        self.live.unlink()
        self.live.write_text(original)
        self.saved_layout.write_text('{"options":[]}')
        self.assertEqual(self.plan()['status'], 'blocked')
        self.saved_layout.write_text('{}')
        self.live.write_text('{"cffi/desktop-space":{},"cffi/desktop-space":{}}')
        self.assertEqual(self.plan()['status'], 'blocked')
        self.assertEqual(outside.read_text(), original)

    def test_outer_snapshot_can_restore_exact_prior_config(self):
        proposal = self.plan()
        before = self.live.read_bytes()
        directory = self.home / 'outer-backup'
        directory.mkdir()
        snapshot = Snapshot(directory, [Path(name) for name in proposal['snapshot_targets']])
        self.install_library()
        relocation.apply(proposal, self.home / 'first')
        snapshot.restore()
        self.assertEqual(self.live.read_bytes(), before)
        relocation.apply(proposal, self.home / 'retry')
        self.assertEqual(self.render()[layout.INTERNAL_SPACE_MODULE]['module_path'], str(self.installed))


if __name__ == '__main__':
    unittest.main()

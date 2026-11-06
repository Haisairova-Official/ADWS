"""Legacy import boundaries, including launcher preservation and rollback."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import adws_install_legacy as legacy
import adws_install_session_config as session
import adws_install_transaction as transaction
import adws_launcher as launcher
import adws_migrate as migration


class LegacyInstallationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='adws-legacy-test-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config = self.root/'config'; self.config.mkdir()
        self.state, self.data, self.cache = (self.root/name for name in ('state','data','cache'))
        self.old, self.new = self.config/'mnws', self.config/'adws'
        self.niri = self.config/'niri/config.kdl'; self.niri.parent.mkdir()
        self.niri.write_text('// personal Niri configuration\n')
        self.source = self.root/'source'; self.source.mkdir()

    def plan(self):
        return legacy.plan(self.config, state_home=self.state, data_home=self.data,
                           cache_home=self.cache, niri_path=self.niri, root=self.source, home=self.root/'home')

    def old_config(self):
        self.old.mkdir()
        (self.old/'taskbar-pins.json').write_text('["personal.desktop"]\n')
        (self.old/'taskbar-layout.json').write_text(json.dumps({'options':{
            'start_launcher_mode':'custom','start_launcher_command':'personal-picker --compact'}}))

    def test_plan_is_read_only_and_previews_existing_custom_launcher(self):
        self.old_config(); before = sorted(self.root.rglob('*'))
        proposal = self.plan()
        self.assertEqual(proposal['status'],'ready')
        self.assertEqual(sorted(self.root.rglob('*')),before)
        self.assertFalse(self.new.exists())
        self.assertEqual(launcher.installation_plan(self.config)['policy'],'initialize')
        self.assertEqual(proposal['launcher_policy']['policy'],'preserve')
        self.assertEqual(proposal['launcher_policy']['existing'],[str(self.new/'taskbar-layout.json')])
        self.assertIn(str(self.old),proposal['snapshot_targets'])
        self.assertIn(str(self.new),proposal['snapshot_targets'])

    def test_import_then_session_generation_preserves_pins_and_launcher(self):
        self.old_config(); proposal = self.plan()
        planned_session = session.plan(self.config,{'features':[]},self.niri,environ={},which=lambda _:None,units={})
        legacy.apply(proposal,self.root/'backup')
        self.assertFalse(self.old.exists())
        self.assertEqual((self.new/'taskbar-pins.json').read_text(),'["personal.desktop"]\n')
        self.assertEqual(launcher.installation_plan(self.config)['policy'],'preserve')
        session.apply(planned_session,self.root/'session-backup',lambda _:None,which=lambda _:None,units={})
        self.assertTrue(legacy.verify_applied(proposal))
        self.assertEqual(json.loads((self.new/'taskbar-layout.json').read_text())['options']['start_launcher_command'],
                         'personal-picker --compact')
        self.assertTrue((self.root/'backup/source-0/taskbar-layout.json').exists())

    def test_outer_transaction_restores_old_active_tree_on_later_failure(self):
        self.old_config(); proposal = self.plan()
        folder = self.root/'snapshot'; folder.mkdir()
        snapshot = transaction.Snapshot(folder,[Path(p) for p in proposal['snapshot_targets']])
        legacy.apply(proposal,self.root/'backup')
        (self.new/'niri-session.kdl').write_text('// newly generated\n')
        snapshot.restore()
        self.assertTrue((self.old/'taskbar-pins.json').exists())
        self.assertFalse(self.new.exists())
        # Resume can reapply the same fully reviewed move after rollback.
        legacy.apply(proposal,self.root/'retry-backup')
        self.assertTrue(legacy.verify_applied(proposal))

    def test_existing_or_concurrent_target_never_displaces_old_configuration(self):
        self.old_config(); proposal = self.plan()
        self.new.mkdir(); (self.new/'niri-session.kdl').write_text('// previously generated\n')
        with self.assertRaisesRegex(ValueError,'target appeared'): legacy.apply(proposal,self.root/'backup')
        self.assertTrue((self.old/'taskbar-pins.json').exists())
        blocked = self.plan()
        self.assertEqual(blocked['status'],'blocked')
        self.assertEqual(blocked['conflicts'][0]['source'],str(self.old))
        self.assertEqual(blocked['conflicts'][0]['target'],str(self.new))
        with self.assertRaises(ValueError): legacy.apply(blocked,self.root/'other-backup')
        self.assertFalse(list(self.config.glob('mnws*.bak')))

    def test_edits_and_new_legacy_trees_after_review_stop_before_import(self):
        self.old_config(); proposal = self.plan()
        (self.old/'taskbar-pins.json').write_text('["new-personal.desktop"]\n')
        with self.assertRaisesRegex(ValueError,'source changed'): legacy.apply(proposal,self.root/'backup')
        self.assertFalse(self.new.exists())
        proposal = self.plan(); (self.data/'mnws').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,'Unreviewed legacy state'): legacy.apply(proposal,self.root/'backup')
        self.assertFalse(self.new.exists())

    def test_old_commands_plugins_state_and_session_need_explicit_review(self):
        self.old_config()
        (self.old/'niri-session.kdl').write_text('environment { QT_IM_MODULE "ibus"; }\n')
        (self.old/'wallpaper.json').write_text('{"command":"mnws -s"}')
        (self.data/'mnws/plugins').mkdir(parents=True)
        (self.state/'mnws').mkdir(parents=True)
        self.niri.write_text('spawn-at-startup "mnws" "-s"\n')
        proposal = self.plan()
        kinds = {row['kind'] for row in proposal['conflicts']}
        self.assertTrue({'legacy-session-requires-review','legacy-reference-requires-conversion',
                         'legacy-data-requires-review','legacy-state-requires-review',
                         'legacy-niri-command-requires-conversion'} <= kinds)
        with self.assertRaises(ValueError): legacy.apply(proposal,self.root/'backup')
        self.assertTrue(self.old.exists()); self.assertFalse(self.new.exists())

    def test_old_command_in_include_is_not_silently_rewritten(self):
        self.old_config()
        include=self.niri.parent/'startup.kdl';include.write_text('spawn-at-startup "/old/mnws" "-s"\n')
        self.niri.write_text('include "startup.kdl"\n')
        proposal=self.plan()
        self.assertEqual(proposal['status'],'blocked')
        self.assertIn(str(include),proposal['source_hashes'])
        self.assertTrue(any(row['source']==str(include) for row in proposal['conflicts']))

    def test_symlinked_personal_configs_are_not_moved_without_review(self):
        self.old_config()
        (self.old/'link.conf').symlink_to(self.root/'outside.conf')
        self.assertEqual(self.plan()['status'],'blocked')
        self.assertTrue(self.old.exists())

    def test_managed_stage_initializes_bundle_without_a_second_migration(self):
        self.old_config(); proposal = self.plan()
        legacy.apply(proposal,self.root/'backup')
        # Later generation adds files, without altering the imported subset.
        (self.new/'default-terminal.json').write_text('{"desktop_id":"foot.desktop"}')
        package = self.source/'plugins/org.AkiACG_Community.NCMLyricsBar_1.1.0.mplg'
        package.parent.mkdir(); package.write_bytes(b'fixture package')
        reviewed={'approved':True,'legacy_plan':proposal,'source_root':str(self.source),'data_home':str(self.data)}
        with patch.object(migration,'migrate',side_effect=AssertionError('must not run implicit migration')):
            legacy.initialize_managed_install(reviewed,root=self.source)
        self.assertEqual((self.data/'adws/plugins'/package.name).read_bytes(),b'fixture package')
        self.assertEqual((self.new/'taskbar-pins.json').read_text(),'["personal.desktop"]\n')
        with self.assertRaisesRegex(ValueError,'NEW_PLAN_REQUIRED'):
            legacy.initialize_managed_install({'approved':True},root=self.source)

    def test_standalone_migration_detects_all_conflicts_before_first_move(self):
        self.old_config()
        (self.data/'mnws').mkdir(parents=True); (self.data/'adws').mkdir()
        with self.assertRaisesRegex(ValueError,'both exist'):
            migration.migrate(self.config,self.state,self.data,self.cache,self.root/'bin',self.root/'lib',self.source)
        self.assertTrue((self.old/'taskbar-pins.json').exists())
        self.assertFalse(self.new.exists())
        self.assertFalse(list(self.data.glob('mnws*.bak')))


if __name__=='__main__': unittest.main()

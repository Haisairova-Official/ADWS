"""Path-only migration preserves real generated defaults and personal styling."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_install_topbar_migration as relocation
import adws_install_source_migration as source
import adws_topbar as topbar
import adws_waybar_presets as presets
import adws_palette_sync as palette
from adws_install_transaction import Snapshot

ROOT=Path(__file__).resolve().parents[1]


class TopbarMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='adws-topbar-move-');self.addCleanup(temporary.cleanup)
        self.home=Path(temporary.name);self.old=self.home/'旧 source';self.new=self.home/'new ADWS'
        self.config=self.home/'config';self.state=self.home/'state';self.data=self.home/'data'
        for root in (self.old,self.new):
            shutil.copytree(ROOT/'config/waybar',root/'config/waybar')
            (root/'src/niri-desktop-layer').mkdir(parents=True)
            (root/'src/niri-desktop-layer/desktop-layer').write_text('# test desktop')
            (root/'adws').write_text('#!/bin/sh\nprintf "'+root.name+'\\n"\n')
            (root/'tools').mkdir()
            for name in ('adws_launcher.py','adws_color_picker.py','adws_color_scheme.py','adws_cava.py','adws_clipboard.py',
                         'adws_gnome_menu.py','adws_topbar.py','adws_topbar_update.py','adws_topbar_controls.py','adws_quick_controls.py','adws_palette_sync.py'):
                (root/'tools'/name).write_text('# fixture helper')
        inventory=self.state/'adws/install-record.json';inventory.parent.mkdir(parents=True)
        inventory.write_text(json.dumps({'root':str(self.old)}))
        self.migration=source.plan(self.new,state_home=self.state,runtime=[])
        self.env=patch.dict(os.environ,{'HOME':str(self.home),'XDG_CONFIG_HOME':str(self.config),
            'XDG_STATE_HOME':str(self.state),'XDG_DATA_HOME':str(self.data),'XDG_RUNTIME_DIR':str(self.home/'run')})
        self.env.start();self.addCleanup(self.env.stop)
        self.config.mkdir();(self.config/'waybar').mkdir();shutil.copy2(ROOT/'config/waybar/colors.css',self.config/'waybar/colors.css')
        self.live=self.config/'waybar/config.jsonc';self.style=self.config/'waybar/style.css'

    def defaults(self,preset='standard'):
        self.assertTrue(topbar.install_defaults(self.old))
        if preset!='standard':
            text,css=presets.rendered(preset,root=self.old)
            self.live.write_text(text);self.style.write_text(css)

    def plan(self,**kwargs):return relocation.plan(self.config,self.migration,**kwargs)

    def test_existing_defaults_reproduce_old_command_then_relocate_only_paths(self):
        self.defaults();before=self.live.read_text();style=self.style.read_text()
        self.assertFalse(topbar.install_defaults(self.new));self.assertEqual(self.live.read_text(),before)
        proposal=self.plan();self.assertEqual(proposal['status'],'ready',proposal['conflicts'])
        self.assertEqual(proposal['restart_profiles'],[{'config':str(self.live),'style':str(self.style)}])
        relocation.apply(proposal,self.home/'backup')
        config=json.loads(self.live.read_text())
        command=config['custom/settings']['on-click']
        result=subprocess.run(['sh','-c',command],capture_output=True,text=True)
        self.assertEqual(result.returncode,0);self.assertEqual(result.stdout,'new ADWS\n')
        self.assertNotIn(str(self.old),command)
        self.assertEqual(self.style.read_text(),style.replace(str(self.old),str(self.new)))
        self.assertEqual(json.loads(before)['clock'],config['clock'])
        self.assertTrue((self.home/'backup/plan.json').is_file())

    def test_all_presets_keep_user_fonts_colors_comments_and_custom_actions(self):
        for preset in ('standard','simple','status','gnome'):
            with self.subTest(preset=preset):
                text,css=presets.rendered(preset,root=self.old)
                data=json.loads(text);data['height']=41;data['spacing']=7
                data['custom/user']={'on-click':'my-own-picker --round','format':'Custom'}
                self.live.write_text('// keep user comment\n'+json.dumps(data,ensure_ascii=False,indent=3)+'\n')
                self.style.write_text(css+'\n/* hand edited */\n#clock { font-family: "User Serif"; color: #123456; }\n')
                before=self.live.read_text();style=self.style.read_text();proposal=self.plan()
                self.assertFalse(proposal['conflicts'],proposal['conflicts'])
                relocation.apply(proposal,self.home/('backup-'+preset))
                now=json.loads(self.live.read_text().split('\n',1)[1]);self.assertEqual(now['height'],41)
                self.assertEqual(now['spacing'],7);self.assertEqual(now['custom/user'],data['custom/user'])
                self.assertTrue(self.live.read_text().startswith('// keep user comment\n'))
                self.assertEqual(self.style.read_text(),style.replace(str(self.old),str(self.new)))
                # Every changed JSON string is a reviewed command; untouched
                # whitespace and nested object formatting remain byte-identical.
                expected=before
                for row in proposal['replacements']:
                    if row['kind']=='command':expected=expected.replace(json.dumps(row['before'],ensure_ascii=False),json.dumps(row['after'],ensure_ascii=False))
                self.assertEqual(self.live.read_text(),expected)

    def test_includes_and_css_imports_preserve_each_file_structure(self):
        self.defaults();data=json.loads(self.live.read_text())
        included=self.config/'waybar/user-modules.jsonc';included.write_text('// external include\n'+json.dumps({'custom/settings':data.pop('custom/settings')}))
        data['include']=['user-modules.jsonc'];self.live.write_text(json.dumps(data))
        imported=self.config/'waybar/extra.css';imported.write_text(self.style.read_text())
        self.style.write_text('@import url("extra.css");\n#clock { font-size: 18pt; }\n')
        proposal=self.plan();self.assertFalse(proposal['conflicts'],proposal['conflicts'])
        self.assertIn(str(included),proposal['snapshot_targets']);self.assertIn(str(imported),proposal['snapshot_targets'])
        relocation.apply(proposal,self.home/'backup')
        self.assertTrue(included.read_text().startswith('// external include\n'))
        self.assertNotIn(str(self.old),imported.read_text())
        self.assertEqual(self.style.read_text(),'@import url("extra.css");\n#clock { font-size: 18pt; }\n')

    def test_custom_updater_payload_kept_as_opaque_literal(self):
        self.defaults()
        from adws_topbar_update import configure_module
        data=json.loads(self.live.read_text());custom='printf "$HOME"; yay -Syu'
        data['custom/updates']=configure_module(data['custom/updates'],'custom',custom,self.old)
        self.live.write_text(json.dumps(data));proposal=self.plan()
        self.assertFalse(proposal['conflicts'],proposal['conflicts'])
        relocation.apply(proposal,self.home/'backup')
        changed=json.loads(self.live.read_text())['custom/updates']
        self.assertEqual(changed['adws-update']['command'],custom)
        self.assertIn(custom,changed['on-click'])

    def test_unknown_shell_helper_resource_and_duplicate_key_block_before_edit(self):
        self.defaults();initial=self.live.read_text()
        commands=[f'bash "{self.old}/adws" config; notify-send done',
                  f'python3 "{self.old}/tools/my-helper.py"',
                  f'bash -lc "{self.old}/adws config"',
                  f'python3 "{self.old}/tools/adws_clipboard.py" --unreviewed']
        for command in commands:
            data=json.loads(initial);data['custom/settings']['on-click']=command
            self.live.write_text(json.dumps(data));before=self.live.read_bytes();proposal=self.plan()
            self.assertEqual(proposal['status'],'blocked',command)
            with self.assertRaises(ValueError):relocation.apply(proposal,self.home/'never')
            self.assertEqual(self.live.read_bytes(),before)
        self.live.write_text(initial);self.style.write_text('window { background-image:url("'+str(self.old/'pictures/user.png')+'"); }')
        self.assertEqual(self.plan()['status'],'blocked')
        self.style.write_text('');self.live.write_text('{"custom/settings":{},"custom/settings":{}}')
        self.assertEqual(self.plan()['status'],'blocked')

    def test_target_drift_symlink_and_inventory_change_are_not_overwritten(self):
        self.defaults();proposal=self.plan();original=self.style.read_text()
        self.style.write_text(original+'/* latest user edit */')
        with self.assertRaisesRegex(ValueError,'source changed'):relocation.apply(proposal,self.home/'backup')
        self.style.write_text(original);outside=self.home/'outside.css';outside.write_text(original);self.style.unlink();self.style.symlink_to(outside)
        self.assertEqual(self.plan()['status'],'blocked');self.style.unlink();self.style.write_text(original)
        proposal=self.plan();Path(self.migration['inventory_path']).write_text('{}')
        with self.assertRaises(ValueError):relocation.apply(proposal,self.home/'backup')
        self.assertEqual(outside.read_text(),original)

    def test_rollback_and_same_approved_retry_restore_user_content(self):
        self.defaults();proposal=self.plan();before={name:Path(name).read_bytes() for name in proposal['files']}
        folder=self.home/'snapshot';folder.mkdir();snapshot=Snapshot(folder,[Path(p) for p in proposal['snapshot_targets']])
        relocation.apply(proposal,self.home/'first');snapshot.restore()
        self.assertEqual(before,{name:Path(name).read_bytes() for name in proposal['files']})
        relocation.apply(proposal,self.home/'second');self.assertNotIn(str(self.old),self.live.read_text())

    def foot_hook(self):
        with patch.object(palette,'__file__',str(self.old/'tools/adws_palette_sync.py')):
            proposal=palette.registration_plan(['foot'],config_home=self.config,data_home=self.data,home=self.home,foot_shell='bash')
        result=palette.register(proposal,self.home/'palette-backup',foot_binary='/fixture/foot',
            runner=lambda *args,**kwargs:subprocess.CompletedProcess(args[0],0,'',''))
        return self.config/'adws/palette/foot-hook.sh'

    def test_registered_foot_hook_moves_script_only_and_never_restarts_bar(self):
        hook=self.foot_hook();before=hook.read_text();rc=(self.home/'.bashrc').read_text()
        proposal=self.plan();self.assertFalse(proposal['conflicts'],proposal['conflicts'])
        self.assertEqual(proposal['restart_profiles'],[])
        self.assertEqual(proposal['snapshot_targets'],[str(hook)])
        relocation.apply(proposal,self.home/'backup')
        self.assertEqual(hook.read_text(),before.replace(str(self.old),str(self.new)))
        self.assertEqual((self.home/'.bashrc').read_text(),rc)
        self.assertTrue(proposal['limitations'])

    def test_modified_foot_hook_is_not_treated_as_owned_template(self):
        hook=self.foot_hook();hook.write_text(hook.read_text()+'echo "my personal hook"\n')
        proposal=self.plan();self.assertEqual(proposal['status'],'blocked')
        with self.assertRaises(ValueError):relocation.apply(proposal,self.home/'backup')
        self.assertTrue(hook.read_text().endswith('echo "my personal hook"\n'))
        self.assertEqual(self.plan(include_foot=False)['status'],'none')

    def historical_baseline(self):
        inventory=Path(self.migration['inventory_path'])
        directory=self.state/'adws-install-backups/install-proven-history'
        directory.mkdir(parents=True)
        Snapshot(directory,[inventory])
        mid=self.home/'intermediate installed source'
        (mid/'src/niri-desktop-layer').mkdir(parents=True)
        (mid/'adws').write_text('# intermediate launcher')
        (mid/'src/niri-desktop-layer/desktop-layer').write_text('# intermediate desktop')
        inventory.write_text(json.dumps({'root':str(mid)}))
        self.migration=source.plan(self.new,state_home=self.state,runtime=[])
        return directory,inventory,mid

    def test_continuous_path_change_uses_proven_history_not_only_current_root(self):
        self.defaults();hook=self.foot_hook()
        directory,inventory,mid=self.historical_baseline()
        self.assertEqual(self.migration['previous_root'],str(mid))
        proposal=self.plan();self.assertEqual(proposal['status'],'ready',proposal['conflicts'])
        proof=next(row for row in proposal['reviewed_roots'] if row['root']==str(self.old))
        self.assertEqual(proof['kind'],'installer-snapshot')
        self.assertIn(str(directory/'manifest.json'),proposal['source_hashes'])
        self.assertIn(str(directory/'0'),proposal['source_hashes'])
        relocation.apply(proposal,self.home/'topbar-history-backup')
        self.assertNotIn(str(self.old),self.live.read_text());self.assertNotIn(str(self.old),hook.read_text())
        self.assertIn(str(self.new),self.style.read_text())
        self.assertEqual(json.loads(inventory.read_text())['root'],str(mid))

    def test_same_root_reinstall_can_repair_proven_older_bar(self):
        self.defaults();directory,inventory,mid=self.historical_baseline()
        inventory.write_text(json.dumps({'root':str(self.new)}))
        self.migration=source.plan(self.new,state_home=self.state,runtime=[])
        self.assertEqual(self.migration['status'],'none')
        proposal=self.plan();self.assertEqual(proposal['status'],'ready',proposal['conflicts'])
        relocation.apply(proposal,self.home/'same-root-backup')
        self.assertNotIn(str(self.old),self.live.read_text())

    def test_missing_or_forged_snapshot_does_not_prove_old_root(self):
        self.defaults();directory,inventory,mid=self.historical_baseline()
        manifest=directory/'manifest.json';rows=json.loads(manifest.read_text())
        outside=self.home/'unreviewed-record';outside.write_bytes((directory/'0').read_bytes())
        rows[0]['backup']=str(outside);manifest.write_text(json.dumps(rows))
        proposal=self.plan();self.assertEqual(proposal['status'],'blocked')
        self.assertIn('Unproven installation root',proposal['conflicts'][0]['detail'])
        (directory/'0').unlink();(directory/'0').symlink_to(outside)
        rows[0]['backup']=str(directory/'0');manifest.write_text(json.dumps(rows))
        self.assertEqual(self.plan()['status'],'blocked')

    def test_changed_historical_evidence_and_old_source_include_are_blocked(self):
        self.defaults();directory,inventory,mid=self.historical_baseline()
        proposal=self.plan();(directory/'0').write_text('{"root":"/different/source"}')
        with self.assertRaisesRegex(ValueError,'source changed'):relocation.apply(proposal,self.home/'backup')
        (directory/'0').write_text(json.dumps({'root':str(self.old)}))
        data=json.loads(self.live.read_text());data['include']=str(self.old/'config/waybar/modules.jsonc')
        self.live.write_text(json.dumps(data));before=(self.old/'config/waybar/modules.jsonc').read_bytes()
        proposal=self.plan();self.assertEqual(proposal['status'],'blocked')
        self.assertIn('include in installation source',proposal['conflicts'][0]['detail'])
        self.assertEqual((self.old/'config/waybar/modules.jsonc').read_bytes(),before)

    def test_missing_new_helper_and_future_profile_creation_need_new_review(self):
        self.defaults();(self.new/'tools/adws_clipboard.py').unlink()
        self.assertEqual(self.plan()['status'],'blocked')
        (self.new/'tools/adws_clipboard.py').write_text('# restored')
        # Optional absent files are watched too: a newly selected profile may
        # change the set that would otherwise be restarted during installation.
        profile=self.config/'adws/waybar-top.json';profile.unlink();proposal=self.plan()
        profile.write_text('{}')
        with self.assertRaisesRegex(ValueError,'source changed'):relocation.apply(proposal,self.home/'backup')


if __name__=='__main__':unittest.main()

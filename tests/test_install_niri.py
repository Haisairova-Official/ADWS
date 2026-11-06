import os
import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_install_niri as niri


class NiriInstallPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.config = self.folder / 'config.kdl'
        self.root = Path(__file__).resolve().parents[1]

    def plan(self, mode='fresh', **kw):
        with patch.object(niri, 'capabilities', return_value={'version': 'niri fixture', 'flavor': 'fork', 'capabilities': {'include': True, 'floating_rules': True}}), patch.object(niri, 'validate', return_value=(True, '')):
            return niri.plan(mode, config_path=self.config, applications={'terminal': ['true']}, binary='/fixture/niri', **kw)

    def test_fresh_is_read_only_and_no_hardware_or_development_path(self):
        result = self.plan()
        self.assertFalse(self.config.exists())
        text = result['files'][str(self.config)]
        self.assertIn('Mod+Return', text)
        self.assertIn('screenshot;', text)
        self.assertIn('move-column-to-workspace 9', text)
        self.assertNotIn('output "', text)
        self.assertNotIn('NVIDIA', text)
        self.assertEqual(result['bindings']['Mod+Return'], ['true'])
        self.assertTrue(result['validated'])

    def test_missing_apps_are_not_emitted_as_dead_bindings(self):
        with patch.object(niri, 'available', return_value=False):
            result = self.plan()
        self.assertNotIn('Mod+Return', result['files'][str(self.config)])
        self.assertIn({'item': 'terminal', 'reason': 'selected-program-not-installed'}, result['skipped'])

    def test_integrate_preserves_user_bindings_and_outputs(self):
        original = '// personal\noutput "User display" { scale 1.5; }\nbinds { Mod+D { spawn "user-launcher"; }; }\n'
        self.config.write_text(original)
        result = self.plan('integrate')
        self.assertEqual(self.config.read_text(), original)
        text = result['files'][str(self.config)]
        self.assertTrue(text.startswith(original))
        self.assertEqual(text.count('Mod+D'), 1)
        self.assertEqual(result['bindings'], {})
        self.assertEqual(len(result['files']), 2)

    def test_integrate_missing_config_and_unknown_modes_fail(self):
        self.assertTrue(self.plan('integrate')['conflicts'])
        with self.assertRaises(ValueError): self.plan('invalid')

    def test_migration_does_not_receive_old_hardware_configuration(self):
        result = self.plan('migrate')
        self.assertIn('never import', result['hardware_policy'])
        self.assertNotIn('output "', result['files'][str(self.config)])

    def test_invalid_config_never_writes(self):
        result = self.plan()
        result['validated'] = False
        with self.assertRaises(ValueError): niri.apply(result, self.folder/'backup')
        self.assertFalse(self.config.exists())

    def test_concurrent_edit_rejected(self):
        result = self.plan()
        self.config.write_text('// user edited during confirmation')
        with self.assertRaisesRegex(ValueError, 'changed after planning'): niri.apply(result, self.folder/'backup')
        self.assertEqual(self.config.read_text(), '// user edited during confirmation')

    def test_apply_validates_and_backs_up_preserving_symlink(self):
        actual = self.folder/'personal.kdl'; actual.write_text('// original\n')
        self.config.symlink_to(actual)
        result = self.plan('integrate')
        with patch.object(niri, 'validate', return_value=(True,'')):
            applied = niri.apply(result, self.folder/'backup')
        self.assertTrue(self.config.is_symlink())
        self.assertIn(niri.BEGIN, actual.read_text())
        self.assertTrue(Path(applied['backup']).exists())
        again = self.plan('integrate')
        self.assertEqual(again['files'][str(self.config)].count(niri.BEGIN), 1)

    def test_invalid_updated_user_include_rejected_at_apply(self):
        result = self.plan()
        with patch.object(niri, 'validate', return_value=(False, 'bad include')):
            with self.assertRaisesRegex(ValueError, 'validation failed'): niri.apply(result, self.folder/'backup')
        self.assertFalse(self.config.exists())

    def test_fresh_install_rerun_preserves_user_changes(self):
        first=self.plan()
        with patch.object(niri, 'validate', return_value=(True,'')):
            niri.apply(first,self.folder/'backup')
        self.config.write_text(self.config.read_text()+'// custom user additions\n')
        second=self.plan('fresh')
        self.assertEqual(second['conflicts'],[])
        self.assertIn('// custom user additions',second['files'][str(self.config)])
        self.assertEqual(second['files'][str(self.config)].count('Mod+Return'),1)

    def test_edited_managed_rules_report_conflict_instead_of_overwrite(self):
        first=self.plan()
        self.config.write_text(first['files'][str(self.config)].replace('open-floating true','open-floating false'))
        second=self.plan('fresh')
        self.assertTrue(second['conflicts'])
        self.assertIn('open-floating false',self.config.read_text())

    def test_action_selection_has_no_implicit_taskbar_features_or_hardware_probes(self):
        with patch.object(niri.subprocess, 'run', side_effect=AssertionError('must not touch devices')):
            taskbar = niri.action_commands(self.root, ['taskbar'], which=lambda name: '/usr/bin/'+name)
            self.assertEqual(taskbar['commands'], {})
            chosen = niri.action_commands(self.root, {'features': [{'id':'brightness'}, {'id':'audio'}]},
                                         which=lambda name: '/usr/bin/'+name)
        self.assertEqual(set(chosen['commands']), {'volume_up','volume_down','volume_mute','microphone_mute','brightness_up','brightness_down'})
        self.assertEqual(chosen['commands']['microphone_mute'], ['pactl','set-source-mute','@DEFAULT_SOURCE@','toggle'])
        self.assertEqual(chosen['commands']['brightness_up'][-3:], ['brightness','--step','5'])
        self.assertTrue(chosen['commands']['brightness_up'][1].endswith('/tools/adws_quick_controls.py'))
        self.assertNotIn('ddcutil', chosen['commands']['brightness_up'])
        self.assertIn('ddcutil', chosen['required_commands'])

    def test_planned_shortcuts_are_rechecked_after_dependencies_install(self):
        selected = ['clipboard','lock','audio','brightness','wallpaper']
        preview = niri.action_commands(self.root, selected, ['swaylock'], require_installed=False, which=lambda _: None)
        self.assertEqual(set(preview['commands']), set(niri.FEATURE_ACTIONS))
        actual = niri.action_commands(self.root, selected, ['swaylock'], which=lambda _: None)
        self.assertEqual(actual['commands'], {})
        self.assertEqual(len(actual['skipped']), len(niri.FEATURE_ACTIONS))
        self.assertEqual(preview['wallpaper_background']['color'], niri.NEUTRAL_BACKGROUND)
        self.assertEqual(preview['commands']['wallpaper'][-3:], ['config','--tab','wallpaper'])
        self.assertEqual(niri.action_commands(self.root,['lock'])['skipped'][0]['reason'], 'selected-command-not-provided')

    def test_available_checks_env_target_and_missing_script(self):
        which = lambda name: '/usr/bin/'+name if name in ('env','python3','bash','true') else None
        self.assertFalse(niri.available(['env','LANG=zh_CN.UTF-8','missing-locker'], which=which))
        self.assertTrue(niri.available(['env','LANG=zh_CN.UTF-8','true'], which=which))
        self.assertFalse(niri.available(['python3',str(self.folder/'missing.py')], which=which))
        self.assertFalse(niri.available(['env','PATH=/unknown','true'], which=which))
        script=self.folder/'installer path with spaces.py';script.write_text('pass\n')
        self.assertTrue(niri.available(['python3',str(script)], which=which))

    def test_fresh_selected_shortcuts_and_native_wallpaper_have_no_duplicate_binding(self):
        actions = {name:['true',name] for name in niri.FEATURE_ACTIONS}
        selected = {feature for feature,_ in niri.FEATURE_ACTIONS.values()}
        proposal = self.plan(actions=actions, features=selected)
        text = proposal['files'][str(self.config)]
        for name,(_,key) in niri.FEATURE_ACTIONS.items():
            self.assertEqual(proposal['bindings'][key], ['true',name])
        self.assertIn('Mod+Alt+L repeat=false', text)
        self.assertIn('XF86AudioMute repeat=false', text)
        self.assertIn('Mod+Alt+V repeat=false { spawn', text)
        self.assertIn('Mod+V { toggle-window-floating;', text)
        self.assertIn('background-color "#242936"', text)
        self.assertNotIn('spawn-at-startup', text)
        self.assertEqual(proposal['wallpaper_background']['status'], 'native-fallback')

    def test_disabled_features_do_not_emit_supplied_commands_or_override_existing_config(self):
        actions = {name:['true'] for name in niri.FEATURE_ACTIONS}
        proposal=self.plan(actions=actions,features=[])
        self.assertNotIn('Mod+Alt+L',proposal['bindings'])
        self.assertNotIn('background-color',proposal['files'][str(self.config)])
        self.config.write_text('layout { background-color "#123456"; }\nbinds { Mod+L { spawn "personal-lock"; }; }\n')
        updated=self.plan('integrate',actions=actions,features=['lock','wallpaper'])
        self.assertEqual(updated['bindings'],{})
        self.assertIn('background-color "#123456"',updated['files'][str(self.config)])
        self.assertIn('personal-lock',updated['files'][str(self.config)])
        self.assertNotIn('#242936',updated['files'][str(self.config)])

    def test_unsupported_background_and_shortcut_property_are_explicitly_skipped(self):
        def validate(_,text,**kwargs):
            return ('background-color' not in text and 'repeat=false' not in text, 'unsupported fixture')
        with patch.object(niri, 'capabilities', return_value={'version':'old fixture','capabilities':{'floating_rules':False}}), patch.object(niri,'validate',side_effect=validate):
            proposal=niri.plan('fresh',config_path=self.config,binary='fixture',actions={'lock':['true']},features=['wallpaper','lock'])
        self.assertTrue(proposal['validated'])
        self.assertEqual(proposal['conflicts'],[])
        self.assertIn({'item':'wallpaper-background','reason':'unsupported-niri-background-color'},proposal['skipped'])
        self.assertIn({'item':'lock','reason':'unsupported-niri-binding'},proposal['skipped'])

    def test_unknown_actions_and_string_feature_list_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unknown Niri feature action'): self.plan(actions={'typo':['true']})
        with self.assertRaisesRegex(ValueError,'iterable'): niri.action_commands(self.root,'wallpaper')

    def test_local_navigation_aliases_preserve_their_meaning_without_app_collisions(self):
        proposal = self.plan()
        binds = proposal['bindings']
        self.assertEqual(binds['Mod+L'], 'focus-column-right;')
        self.assertEqual(binds['Mod+D'], 'consume-or-expel-window-right;')
        self.assertEqual(binds['Mod+Comma'], 'consume-window-into-column;')
        self.assertEqual(binds['Mod+T'], binds['Mod+Return'])
        self.assertEqual(binds['Mod+Z'][-1], 'start-menu')
        self.assertEqual(binds['Mod+Alt+Comma'][-1], 'config')
        self.assertEqual(binds['Mod+Alt+F'], 'fullscreen-window;')
        self.assertEqual(binds['Ctrl+Print'], 'screenshot-window;')
        self.assertEqual(binds['Shift+Print'], 'screenshot-screen;')
        self.assertEqual(binds['Mod+Minus'], 'set-column-width "-5%";')
        for direction, arrow, vim, wasd in niri.DIRECTIONS:
            self.assertEqual(binds['Mod+'+arrow], binds['Mod+'+vim])
            for key in (arrow, vim, wasd):
                self.assertEqual(binds['Mod+Ctrl+Shift+'+key], f'move-column-to-monitor-{direction};')
                self.assertEqual(binds['Mod+Alt+Shift+'+key], f'move-workspace-to-monitor-{direction};')
        # Count actual configuration entries, not just dict keys which would
        # conceal an overwritten binding. Normalize modifier order as Niri does.
        import re
        text = proposal['files'][str(self.config)]
        keys = re.findall(r'^    ([A-Za-z0-9_+]+)(?:\s+[^{}\n]*)?\s*\{', text, re.M)
        normalized = [tuple(sorted(key.split('+')[:-1]))+(key.split('+')[-1].lower(),) for key in keys]
        self.assertEqual(len(normalized), len(set(normalized)))
        self.assertNotIn('Ctrl', binds)
        self.assertNotIn('Mod+Shift+T', binds)
        self.assertNotIn('~/.config/scripts', text)
        self.assertNotIn('niri-quick-switch-fuzzel', text)
        self.assertNotIn('Mod+F5', binds)
        self.assertIn('personal-snapshot-tools', [row['item'] for row in proposal['skipped']])

    def test_native_switcher_is_scoped_and_modifier_tap_waits_for_release(self):
        proposal = self.plan()
        text = proposal['files'][str(self.config)]
        self.assertIn('Super repeat=false { release { toggle-overview; }; }', text)
        self.assertIn('recent-windows {', text)
        self.assertEqual(proposal['bindings']['Mod+Tab'], 'next-window scope="workspace";')
        self.assertEqual(proposal['bindings']['Mod+Shift+Tab'], 'previous-window scope="workspace";')
        self.assertEqual(proposal['bindings']['Mod+grave'], 'next-window filter="app-id";')
        self.assertEqual(proposal['bindings']['Alt+Tab'], 'next-window;')

    def test_duplicate_binding_guard_handles_modifier_order_and_return_case(self):
        self.assertEqual(niri.binding_identity('Mod+Shift+Ctrl+Return'), niri.binding_identity('Ctrl+Mod+Shift+return'))
        self.assertNotEqual(niri.binding_identity('Mod+T'), niri.binding_identity('Super+T'))
        with patch.object(niri, 'ACTIONS', niri.ACTIONS+[('Ctrl+Mod+Shift+left', 'focus-monitor-left;')]):
            with self.assertRaisesRegex(ValueError, 'Duplicate default Niri binding'):
                self.plan()
        with patch.object(niri, 'ACTIONS', niri.ACTIONS+[('Mod+return', 'close-window;')]):
            with self.assertRaisesRegex(ValueError, 'Duplicate default Niri binding'):
                self.plan()

    def test_unsupported_modifier_release_and_switcher_are_not_replaced_with_unsafe_shortcuts(self):
        def validate(_, text, **kwargs):
            return ('release {' not in text and 'recent-windows {' not in text, 'unsupported fixture')
        with patch.object(niri, 'capabilities', return_value={'version':'old fixture','capabilities':{'floating_rules':False}}), patch.object(niri, 'validate', side_effect=validate):
            proposal = niri.plan('fresh', config_path=self.config, binary='fixture', applications={'terminal':['true']})
        self.assertTrue(proposal['validated'])
        self.assertNotIn('Super', proposal['bindings'])
        self.assertNotIn('Mod+Tab', proposal['bindings'])
        self.assertNotIn('Ctrl', proposal['bindings'])
        self.assertEqual(proposal['bindings']['Mod+O'], 'toggle-overview;')
        self.assertTrue(any(row['item']=='Super' and row['reason']=='unsupported-modifier-release' for row in proposal['skipped']))
        self.assertTrue(any(row['item']=='Mod+Tab' and row['reason']=='unsupported-native-window-switcher' for row in proposal['skipped']))

    def test_real_installed_niri_validates_portable_config_and_relative_includes(self):
        binary = shutil.which('niri')
        if not binary: self.skipTest('Niri validator not installed')
        result = niri.plan('fresh', config_path=self.config, binary=binary, applications={'terminal':['true']},
                           actions={name:['true',name] for name in niri.FEATURE_ACTIONS},
                           features={feature for feature,_ in niri.FEATURE_ACTIONS.values()})
        self.assertEqual(result['conflicts'], [])
        self.assertTrue(result['validated'])
        self.assertIn('XF86MonBrightnessUp', result['bindings'])
        self.assertEqual(result['bindings']['Mod+L'], 'focus-column-right;')
        self.assertIn('Mod+Alt+L', result['bindings'])
        self.assertIn('Mod+Alt+V', result['bindings'])
        self.assertEqual(result['bindings']['Mod+D'], 'consume-or-expel-window-right;')
        self.assertEqual(result['bindings']['Ctrl+Print'], 'screenshot-window;')
        self.assertEqual(result['bindings']['Shift+Print'], 'screenshot-screen;')
        niri.apply(result, self.folder/'backup')
        (self.folder/'personal.kdl').write_text('// existing relative include\n')
        self.config.write_text(self.config.read_text()+'include "personal.kdl"\n')
        second = niri.plan('integrate', config_path=self.config, binary=binary)
        if not second['capabilities']['include']:
            self.assertTrue(second['conflicts']); return
        self.assertEqual(second['conflicts'], [])
        niri.apply(second, self.folder/'backup2')
        checked = subprocess.run([binary,'validate','-c',str(self.config)],capture_output=True,text=True,timeout=10)
        self.assertEqual(checked.returncode,0,checked.stderr)



class NiriRelocationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.folder=Path(temp.name)
        self.old=self.folder/'old source';self.new=self.folder/'新安装 目录'
        for root in (self.old,self.new):
            for name in ('adws','tools/adws_clipboard.py','tools/adws_quick_controls.py'):
                file=root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('# fixture\n')
            (root/'config').mkdir();(root/'config/adws-windows.kdl').write_text('window-rule { match app-id="^adws-config$"; open-floating true; }\n')
        self.config=self.folder/'niri/config.kdl';self.config.parent.mkdir()
        self.inventory=self.folder/'install-record.json';self.inventory.write_text(json.dumps({'root':str(self.old)}))
        self.migration={'previous_root':str(self.old),'root':str(self.new),'inventory_path':str(self.inventory),
            'source_hashes':{str(self.inventory):hashlib.sha256(self.inventory.read_bytes()).hexdigest()},'conflicts':[]}
        self.cap={'version':'fixture','flavor':'fixture','capabilities':{'include':True,'floating_rules':True}}
        self.original=niri.DEFAULT_HEADER+'\n// personal key and comment\nbinds {\n  Mod+Y repeat=false { spawn "bash" '+json.dumps(str(self.old/'adws'))+' "start-menu"; } // leave this\n  XF86AudioRaiseVolume allow-when-locked=true { spawn "python3" '+json.dumps(str(self.old/'tools/adws_quick_controls.py'))+' "sound" "--step" "7"; }\n}\n'
        self.config.write_text(self.original)
    def review(self):return niri.relocation_plan(self.config,self.migration)
    def integrate(self,review):
        with patch.object(niri,'capabilities',return_value=self.cap),patch.object(niri,'validate',return_value=(True,'')):
            return niri.plan('integrate',root=self.new,config_path=self.config,binary='/fixture/niri',relocation=review)
    def test_exact_script_tokens_change_and_personal_keys_parameters_comments_survive(self):
        review=self.review();self.assertFalse(review['conflicts']);self.assertEqual(len(review['replacements']),2)
        self.assertEqual(self.config.read_text(),self.original)
        result=self.integrate(review)
        self.assertIn('Mod+Y repeat=false',result['files'][str(self.config)])
        self.assertIn('"--step" "7"',result['files'][str(self.config)])
        self.assertIn('// leave this',result['files'][str(self.config)])
        with patch.object(niri,'validate',return_value=(True,'')):niri.apply(result,self.folder/'backup')
        self.assertNotIn(str(self.old),self.config.read_text());self.assertIn(str(self.new),self.config.read_text())
        self.assertFalse(self.review()['replacements'])
    def test_included_bindings_validate_new_graph_even_when_managed_rules_shift_lines(self):
        child=self.config.parent/'bindings.kdl';child.write_text(self.original)
        rules='window-rule { match app-id="^old$"; open-floating true; }\n'
        block=niri.BEGIN+'\n// content-sha256: '+hashlib.sha256(rules.encode()).hexdigest()+'\n'+rules+niri.END+'\n'
        main=niri.DEFAULT_HEADER+'\n'+block+'include "bindings.kdl"\n';self.config.write_text(main)
        review=self.review();self.assertFalse(review['conflicts']);result=self.integrate(review)
        def validate(binary,text,directory=None):
            # Validation only may rewrite include paths. Every candidate include
            # is readable while the original files still point to the old source.
            self.assertEqual(self.config.read_text(),main);self.assertEqual(child.read_text(),self.original)
            includes=[]
            from adws_install_kdl import include
            for line in text.splitlines():
                if line.strip().startswith('include '):
                    name,_=include(line);target=Path(name);target=target if target.is_absolute() else Path(directory)/target
                    includes.append(target.read_text())
            self.assertTrue(any(str(self.new) in value for value in includes));return True,''
        with patch.object(niri,'validate',side_effect=validate):niri.apply(result,self.folder/'backup')
        self.assertIn('include "bindings.kdl"',self.config.read_text());self.assertNotIn(str(self.old),child.read_text())
    def test_unknown_shell_custom_resource_or_unmanaged_config_are_conflicts(self):
        examples=[self.original.replace(niri.DEFAULT_HEADER,'// custom config'),
            niri.DEFAULT_HEADER+'\nbinds {\nMod+Y { spawn-sh '+json.dumps('bash '+str(self.old/'adws')+' start-menu')+'; }\n}\n',
            self.original.replace('"start-menu"','"config" '+json.dumps(str(self.old/'personal.css'))),
            self.original.replace('"bash"','"custom-wrapper"')]
        for text in examples:
            with self.subTest(text=text):
                self.config.write_text(text);review=self.review();self.assertTrue(review['conflicts'])
                with self.assertRaises(ValueError):self.integrate(review)
                self.assertEqual(self.config.read_text(),text)
    def test_comment_references_are_not_relocated(self):
        text=self.original+'// this old path is documentation: '+str(self.old/'adws')+'\n'
        self.config.write_text(text);review=self.review();self.assertFalse(review['conflicts'])
        self.assertTrue(review['files'][str(self.config)].endswith('// this old path is documentation: '+str(self.old/'adws')+'\n'))
    def test_inventory_or_source_changed_after_review_is_rejected(self):
        for target in (self.inventory,self.config):
            with self.subTest(target=target):
                before=target.read_bytes();review=self.review();target.write_bytes(before+b'\n')
                with self.assertRaises(ValueError):self.integrate(review)
                target.write_bytes(before)
    def test_apply_validation_failure_preserves_source_and_includes(self):
        result=self.integrate(self.review())
        with patch.object(niri,'validate',return_value=(False,'bad include')):
            with self.assertRaisesRegex(ValueError,'validation failed'):niri.apply(result,self.folder/'backup')
        self.assertEqual(self.config.read_text(),self.original)
    def test_nested_same_basename_includes_relocate_distinct_commands(self):
        binary=shutil.which('niri')
        if not binary:self.skipTest('Niri is not installed')
        for name in ('left','right'):
            folder=self.config.parent/name;folder.mkdir()
            (folder/'entry.kdl').write_text('include "binds.kdl"\n')
            text=self.original if name=='left' else self.original.replace('Mod+Y','Mod+U').replace('XF86AudioRaiseVolume','XF86AudioLowerVolume').replace('"7"','"-9"')
            (folder/'binds.kdl').write_text(text)
        main=niri.DEFAULT_HEADER+'\ninclude "left/entry.kdl"\ninclude "right/entry.kdl"\n';self.config.write_text(main)
        review=self.review();self.assertEqual(len(review['files']),2)
        proposal=niri.plan('integrate',root=self.new,config_path=self.config,binary=binary,relocation=review)
        self.assertFalse(proposal['conflicts']);niri.apply(proposal,self.folder/'backup')
        subprocess.run([binary,'validate','-c',str(self.config)],check=True,capture_output=True)
        left=(self.config.parent/'left/binds.kdl').read_text();right=(self.config.parent/'right/binds.kdl').read_text()
        self.assertIn('"7"',left);self.assertIn('"-9"',right)
        self.assertNotIn(str(self.old),left+right);self.assertIn('include "left/entry.kdl"',self.config.read_text())
    def test_same_content_include_symlink_retarget_is_not_silently_accepted(self):
        old=self.config.parent/'first.kdl';old.write_text(self.original)
        other=self.config.parent/'second.kdl';other.write_text(self.original)
        link=self.config.parent/'bindings.kdl';link.symlink_to(old)
        self.config.write_text(niri.DEFAULT_HEADER+'\ninclude "bindings.kdl"\n')
        review=self.review();link.unlink();link.symlink_to(other)
        with self.assertRaisesRegex(ValueError,'include graph changed'):self.integrate(review)
        self.assertEqual(old.read_text(),self.original);self.assertEqual(other.read_text(),self.original)

    def test_actual_niri_validation_of_relocated_main_and_include(self):
        binary=shutil.which('niri')
        if not binary:self.skipTest('Niri is not installed')
        child=self.config.parent/'binding-中文.kdl';child.write_text(self.original)
        self.config.write_text(niri.DEFAULT_HEADER+'\ninclude '+json.dumps(child.name,ensure_ascii=False)+'\n')
        review=self.review()
        proposal=niri.plan('integrate',root=self.new,config_path=self.config,binary=binary,relocation=review)
        self.assertFalse(proposal['conflicts']);niri.apply(proposal,self.folder/'backup')
        subprocess.run([binary,'validate','-c',str(self.config)],check=True,capture_output=True)


if __name__ == '__main__': unittest.main()

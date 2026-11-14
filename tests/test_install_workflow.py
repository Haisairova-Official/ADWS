"""Installer contract checks using isolated homes; never install packages or start UI."""
import json
import contextlib
import subprocess
import os
import shlex
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_install_workflow as workflow
import adws_install_transaction as transaction


class InstallWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='adws-workflow-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root/'home'; self.home.mkdir()
        self.source = self.root/'source'; self.source.mkdir()
        (self.source/'install.sh').write_text('#!/bin/sh\n')
        (self.source/'build-info.json').write_text('{}')
        self.environment = patch.dict(os.environ, {
            'HOME':str(self.home), 'XDG_CONFIG_HOME':str(self.home/'.config'),
            'XDG_DATA_HOME':str(self.home/'.local/share'), 'XDG_STATE_HOME':str(self.home/'.local/state'),
            'XDG_DATA_DIRS':str(self.root/'system-data'), 'ADWS_INSTALL_PLAN':'',
            'NIRI_CONFIG':'', 'XDG_CACHE_HOME':str(self.home/'.cache'), 'ADWS_INSTALL_MANAGED':'',
        })
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.apps = {role:[{'desktop_id':role+'.desktop','name':role,'argv':['true']}] for role in workflow.APP_ROLES}
        self.apps['terminal'][0]['desktop_id'] = 'kitty.desktop'
        self.apps['file_manager'] = [
            {'desktop_id':'dolphin.desktop','name':'Dolphin','argv':['dolphin']},
            {'desktop_id':'thunar.desktop','name':'Thunar','argv':['thunar']},
        ]

    def selected(self, choices=None, *, mode='fresh'):
        with patch('adws_install_features.provider_hints',return_value={'providers':{},'evidence':{},'source_hashes':{},'conflicts':[]}), patch('adws_install_features.feature_plan',return_value={'manager':'pacman','packages':[],'features':[]}), patch('adws_setup.cargo_source_configuration',return_value=None), patch.object(workflow,'installed_apps',return_value=self.apps), patch.object(workflow.shutil,'which',return_value='/bin/fixture'):
            return workflow.selected_plan(mode,root=self.source,choices=choices)

    def test_clean_install_defaults_to_thunar_even_if_another_manager_sorts_first(self):
        self.assertEqual(self.selected()['applications']['file_manager'], self.apps['file_manager'][1])
        self.apps['file_manager'].pop()
        plan = self.selected()
        self.assertEqual(plan['applications']['file_manager']['install_package'], 'thunar')
        self.assertIn('thunar', plan['package_candidates'])

    def test_preserve_folder_association_across_integration_migration_and_reinstall(self):
        for mode in ('integrate', 'migrate', 'fresh'):
            with self.subTest(mode=mode):
                if mode == 'fresh':
                    record = self.home/'.local/state/adws/install-record.json'
                    workflow.write_json(record, {'root':str(self.source)})
                self.apps['file_manager'] = []  # A system handler may be hidden or D-Bus-only.
                plan = self.selected(mode=mode)
                self.assertEqual(plan['applications']['file_manager']['policy'], 'preserve')
                self.assertNotIn('thunar',plan['package_candidates'])
                associations = {'inode/directory':'personal-manager.desktop'}
                def assign(argv, **kwargs): associations[argv[-1]]=argv[-2]
                with patch.object(workflow,'installed_apps',return_value=self.apps), \
                     patch.object(workflow.subprocess,'run',side_effect=assign) as writes, \
                     patch.object(workflow.subprocess,'check_output',side_effect=lambda argv,**kw:associations[argv[-1]]):
                    workflow.configure_defaults(plan)
                self.assertTrue(all('inode/directory' not in call.args[0] for call in writes.call_args_list))
                self.assertEqual(associations['inode/directory'],'personal-manager.desktop')

    def test_folder_manager_interactive_return_and_explicit_choice(self):
        choices = {key:'selected.desktop' for key in workflow.APP_ROLES if key!='file_manager'}
        with patch.object(workflow,'installed_apps',return_value=self.apps), patch('builtins.input',return_value=''):
            workflow.choose_applications('integrate',choices)
        self.assertNotIn('file_manager', choices)
        with patch.object(workflow,'installed_apps',return_value=self.apps), patch('builtins.input',return_value='1'):
            workflow.choose_applications('integrate',choices)
        for mode in ('fresh','integrate','migrate'):
            self.assertEqual(self.selected({'file_manager':choices['file_manager']},mode=mode)['applications']['file_manager'],
                             self.apps['file_manager'][0])

    def test_fresh_after_uninstall_and_subsequent_reinstall(self):
        import adws_uninstall
        record = self.home/'.local/state/adws/install-record.json'
        workflow.write_json(record, {'root':str(self.source),'uninstalled':True})
        workflow.write_json(record.parent.parent/'mnws/install-record.json', {'root':'/previous'})
        self.assertEqual(self.selected()['applications']['file_manager']['desktop_id'], 'thunar.desktop')
        self.assertEqual(self.selected(mode='integrate')['applications']['file_manager']['policy'], 'preserve')
        with patch.object(adws_uninstall, 'library_sources', return_value={}):
            adws_uninstall.record()
        self.assertNotIn('uninstalled', json.loads(record.read_text()))
        self.assertEqual(self.selected()['applications']['file_manager']['policy'], 'preserve')

    def test_plan_passes_reviewed_provider_ownership_to_dependency_selection(self):
        hints={'providers':{'input':'ibus-daemon'},'evidence':{},'source_hashes':{},'conflicts':[]}
        with patch('adws_install_features.provider_hints',return_value=hints), patch('adws_install_features.feature_plan',return_value={'manager':'pacman','packages':[],'features':[],'conflicts':[{'feature':'input','kind':'fixture-conflict'}]}) as dependency, patch('adws_setup.cargo_source_configuration',return_value=None), patch.object(workflow,'installed_apps',return_value=self.apps), patch.object(workflow.shutil,'which',return_value='/bin/fixture'):
            result=workflow.selected_plan('integrate',root=self.source)
        self.assertEqual(dependency.call_args.kwargs['provider_hints'],hints)
        self.assertEqual(result['provider_plan'],hints)
        self.assertTrue(result['blocking'])

    def test_provider_configuration_drift_stops_before_transaction(self):
        with self.execution_fixture() as (plan,state,packages,native):
            import hashlib
            path=self.home/'.config/niri/config.kdl'
            plan['provider_plan']={'source_hashes':{str(path):hashlib.sha256(path.read_bytes()).hexdigest()},'evidence':{}}
            path.write_text('// changed owner after review\n')
            with self.assertRaisesRegex(ValueError,'服务归属'):workflow.execute(plan,self.root/'journal')
            native.assert_not_called()
            self.assertEqual(path.read_text(),'// changed owner after review\n')

    def test_provider_environment_drift_is_not_silently_ignored(self):
        plan={'provider_plan':{'source_hashes':{},'evidence':{'input':[{'origin':'process-environment','key':'XMODIFIERS','value':'@im=ibus'}]}}}
        with patch.dict(os.environ,{'XMODIFIERS':'@im=fcitx'}):
            with self.assertRaisesRegex(ValueError,'XMODIFIERS'):workflow.verify_provider_sources(plan)

    def test_new_package_startup_shadow_rolls_back_and_is_reapplied_on_resume(self):
        import hashlib
        from adws_install_package_owners import reviewed_package_owners
        system=self.root/'package-autostart';system.mkdir()
        with self.execution_fixture(fail_configuration=True) as (plan,state,packages,native):
            config=Path(plan['config_home'])
            plan['package_owner_plan']=reviewed_package_owners(
                {'manager':'pacman','features':[{'id':'input','provider':'fcitx5'}]},['fcitx5'],config,
                niri_path=plan['niri_config_path'],system_autostart_dir=system,
                audit_options={'autostart_dirs':[system,config/'autostart'],'enabled_units':[]})
            source=system/'org.fcitx.Fcitx5.desktop'
            source.write_text('[Desktop Entry]\nType=Application\nName=Fcitx 5\nExec=fcitx5 -d\n')
            identity={'package':'fcitx5','sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'verification':'fixture-package-db'}
            target=config/'autostart'/source.name
            with patch('adws_install_package_owners.package_file_identity',return_value=identity):
                with self.assertRaises(subprocess.CalledProcessError):workflow.execute(plan,self.root/'journal')
                self.assertFalse(target.exists())
                self.assertTrue(source.exists(),'package contents are retained after rollback')
                state['fail']=False
                self.assertEqual(workflow.execute(plan,self.root/'journal'),2)
            self.assertIn('Hidden=true',target.read_text())
            progress=json.loads((self.root/'journal/progress.json').read_text())
            self.assertEqual(progress['steps']['package-startup-ownership']['status'],'passed')
            self.assertIn(str(target),progress['deployment_receipt'])

    def test_legacy_pins_are_active_before_new_configuration_and_rollback_restores_source(self):
        from adws_install_legacy import plan as legacy_plan
        with self.execution_fixture(fail_configuration=True) as (plan,state,packages,native):
            config=Path(plan['config_home']);old=config/'mnws';old.mkdir()
            original='["firefox.desktop"]\n'
            (old/'taskbar-pins.json').write_text(original)
            (old/'taskbar-layout.json').write_text('{"options":{"start_launcher_mode":"custom","start_launcher_command":"fuzzel"}}\n')
            plan['legacy_plan']=legacy_plan(config,niri_path=plan['niri_config_path'],root=self.source)
            self.assertEqual(plan['legacy_plan']['conflicts'],[])
            self.assertEqual(plan['legacy_plan']['launcher_policy']['policy'],'preserve')
            target=config/'adws/taskbar-pins.json'
            native.side_effect=lambda:self.assertEqual(target.read_text(),original)
            with self.assertRaises(subprocess.CalledProcessError):workflow.execute(plan,self.root/'journal')
            self.assertEqual((old/'taskbar-pins.json').read_text(),original)
            self.assertFalse(target.exists())
            state['fail']=False
            self.assertEqual(workflow.execute(plan,self.root/'journal'),2)
            self.assertEqual(target.read_text(),original)
            self.assertFalse(old.exists())

    def source_move_fixture(self, plan):
        from adws_install_source_migration import plan as source_plan, STATE_RELATIVE
        from adws_desktop_groups_model import new_group
        old=self.root/'old installation'
        for root in (old,self.source):
            (root/'src/niri-desktop-layer').mkdir(parents=True,exist_ok=True)
            (root/'src/niri-desktop-layer/desktop-layer').write_text('# desktop fixture\n')
            (root/'adws').write_text('# launcher fixture\n')
        source=old/STATE_RELATIVE;source.mkdir()
        group=new_group(self.home/'Desktop',name='Migration proof')
        group.update(x=.25,y=.15,width=400,height=280,cells={'note.txt':[2,1]})
        (source/'desktop-groups.json').write_text(json.dumps({'version':1,'default_monitor':'primary','groups':[group]}))
        (source/'layout.json').write_text(json.dumps({'version':1,'positions':{'display:0':{'note.txt':[2,1]}},'preferences':{}}))
        inventory=self.home/'.local/state/adws/install-record.json'
        inventory.parent.mkdir(parents=True,exist_ok=True)
        inventory.write_text(json.dumps({'root':str(old)}))
        plan['source_migration']=source_plan(self.source,runtime=[])
        self.assertFalse(plan['source_migration']['conflicts'])
        plan['source_fingerprint']=workflow.fingerprint(self.source)
        return old,source,self.source/STATE_RELATIVE,inventory

    def test_source_move_copies_final_layout_before_registration_and_resume_keeps_user_moves(self):
        with self.execution_fixture(fail_configuration=True) as (plan,state,packages,native):
            old,source,target,inventory=self.source_move_fixture(plan)
            # A legitimate last move after preview must be copied at stop time.
            group=json.loads((source/'desktop-groups.json').read_text())
            group['groups'][0]['x']=.45
            (source/'desktop-groups.json').write_text(json.dumps(group))
            originals={p.name:p.read_bytes() for p in source.iterdir()}
            def configure():
                self.assertEqual(json.loads(inventory.read_text())['root'],str(old))
                self.assertEqual((target/'desktop-groups.json').read_bytes(),originals['desktop-groups.json'])
                inventory.write_text(json.dumps({'root':str(self.source)}))
            state['configuration_hook']=configure
            with patch.object(transaction,'integration_paths',return_value=[self.home/'.config/adws',inventory]):
                with self.assertRaises(subprocess.CalledProcessError):workflow.execute(plan,self.root/'journal')
                self.assertFalse(target.exists())
                self.assertEqual(json.loads(inventory.read_text())['root'],str(old))
                state['fail']=False
                self.assertEqual(workflow.execute(plan,self.root/'journal'),2)
                progress=json.loads((self.root/'journal/progress.json').read_text())
                self.assertEqual(progress['steps']['installation-source-migration']['status'],'passed')
                self.assertNotIn(str(target/'desktop-groups.json'),progress['deployment_receipt'])
                # Acceptance-only resume must not overwrite a new user move or
                # reject the inventory now correctly registered to the new root.
                group['groups'][0]['x']=.8
                (target/'desktop-groups.json').write_text(json.dumps(group))
                calls=native.call_count
                self.assertEqual(workflow.execute(plan,self.root/'journal'),2)
                self.assertEqual(native.call_count,calls)
                self.assertEqual(json.loads((target/'desktop-groups.json').read_text())['groups'][0]['x'],.8)
            self.assertEqual({p.name:p.read_bytes() for p in source.iterdir()},originals)

    def test_relocates_existing_startup_even_when_adding_startups_is_disabled(self):
        import adws_install_startup as startup
        audit=startup.audit
        def isolated_audit(config_home,niri_path=None,enabled_units=None,unit_dirs=None,autostart_dirs=None,**kwargs):
            return audit(config_home,niri_path,enabled_units=[],autostart_dirs=[],unit_dirs=[self.home/'empty-units'],**kwargs)
        with self.execution_fixture(fail_configuration=True) as (plan,state,packages,native):
            old,source,target,inventory=self.source_move_fixture(plan)
            included=self.home/'personal-config/session.kdl';included.parent.mkdir()
            command=['bash',str(old/'adws'),'desktop','-s']
            original=startup.BEGIN+'\nspawn-at-startup '+' '.join(json.dumps(v) for v in command)+'\n'+startup.END+'\n'
            included.write_text(original)
            main=Path(plan['niri_config_path']);main.write_text('include '+json.dumps(str(included))+'\n')
            commands={'desktop':['bash',str(self.source/'adws'),'desktop','-s'],
                      'taskbar':['bash',str(self.source/'adws'),'taskbar','-s']}
            with patch.object(startup,'audit',side_effect=isolated_audit):
                plan['startup_plan']=startup.plan(plan['config_home'],commands,niri_path=main,
                    source_migration=plan['source_migration'],add_missing=False)
                self.assertFalse(plan['startup_plan']['conflicts'])
                self.assertFalse(plan['autostart'])
                self.assertFalse(plan['startup_plan']['additions'])
                def configure():
                    self.assertIn(str(self.source/'adws'),included.read_text())
                    self.assertNotIn('taskbar',included.read_text())
                    self.assertEqual(json.loads(inventory.read_text())['root'],str(old))
                    inventory.write_text(json.dumps({'root':str(self.source)}))
                state['configuration_hook']=configure
                with patch('adws_install_niri.apply'), patch.object(transaction,'integration_paths',return_value=[self.home/'.config/adws',inventory]):
                    with self.assertRaises(subprocess.CalledProcessError):workflow.execute(plan,self.root/'journal')
                    self.assertEqual(included.read_text(),original,'external include must roll back')
                    self.assertEqual(json.loads(inventory.read_text())['root'],str(old))
                    state['fail']=False
                    self.assertEqual(workflow.execute(plan,self.root/'journal'),2)
                receipt=json.loads((self.root/'journal/progress.json').read_text())['deployment_receipt']
                self.assertIn(str(included),receipt)
                result=json.loads((self.root/'journal/result.json').read_text())
                self.assertIn('autostart',result['completed'])
                self.assertNotIn('autostart',result['skipped'])
                included.write_text(included.read_text()+'// changed after install\n')
                with self.assertRaisesRegex(ValueError,'安装后文件发生变化'):workflow.verify_receipt(receipt)

    def test_relocation_rebase_accepts_only_reviewed_session_fragment(self):
        from adws_install_niri import relocation_plan, DEFAULT_HEADER
        with self.execution_fixture() as (plan,state,packages,native):
            old,source,target,inventory=self.source_move_fixture(plan)
            env=self.home/'.config/adws/niri-session.kdl';env.parent.mkdir()
            env.write_text('environment { FIXTURE "before"; }\n')
            main=Path(plan['niri_config_path'])
            main.write_text(DEFAULT_HEADER+'\ninclude '+json.dumps(str(env))+'\nbinds {\n  Mod+Space { spawn "bash" '+json.dumps(str(old/'adws'))+' "menu"; }\n}\n')
            plan['niri_relocation']=relocation_plan(main,plan['source_migration'])
            self.assertFalse(plan['niri_relocation']['conflicts'])
            self.assertTrue(plan['niri_relocation']['replacements'])
            desired='environment { FIXTURE "approved"; }\n'
            plan['session_plan']={'env_file':str(env),'env_kdl':desired}
            env.write_text(desired)
            current=workflow.refreshed_niri_relocation(plan)
            self.assertEqual(current['files'],plan['niri_relocation']['files'])
            env.write_text('environment { FIXTURE "unapproved"; }\n')
            with self.assertRaisesRegex(ValueError,'配置来源发生变化'):workflow.refreshed_niri_relocation(plan)
            env.write_text(desired);main.write_text(main.read_text()+'// user changed another file\n')
            with self.assertRaisesRegex(ValueError,'配置来源发生变化'):workflow.refreshed_niri_relocation(plan)

    def test_generated_rules_outside_xdg_config_are_restored_and_receipted(self):
        with self.execution_fixture(fail_configuration=True) as (plan,state,packages,native):
            external=self.home/'custom-config';external.mkdir()
            main=external/'desktop.kdl';main.write_text('// personal external config\n')
            untouched=external/'unrelated.txt';untouched.write_text('personal contents')
            plan['niri_config_path']=str(main)
            rules=self.source/'config/adws-windows.kdl';rules.parent.mkdir()
            rules.write_text('// fixture generated rules\n')
            plan['source_fingerprint']=workflow.fingerprint(self.source)
            include=workflow.niri_rule_include(plan)
            def generate(proposal,backup):
                include.write_bytes(rules.read_bytes())
                main.write_text('include '+json.dumps(include.name)+'\n')
            with patch('adws_install_niri.apply',side_effect=generate):
                with self.assertRaises(subprocess.CalledProcessError):workflow.execute(plan,self.root/'journal')
                self.assertEqual(set(p.name for p in external.iterdir()),{'desktop.kdl','unrelated.txt'})
                self.assertEqual(main.read_text(),'// personal external config\n')
                state['fail']=False
                self.assertEqual(workflow.execute(plan,self.root/'journal'),2)
            receipt=json.loads((self.root/'journal/progress.json').read_text())['deployment_receipt']
            self.assertIn(str(include),receipt)
            include.write_text('// user changed rules\n')
            with self.assertRaisesRegex(ValueError,'安装后文件发生变化'):workflow.verify_receipt(receipt)
            self.assertEqual(untouched.read_text(),'personal contents')

    def test_relocation_rebase_rejects_retargeted_include_even_with_same_file_hashes(self):
        from adws_install_niri import relocation_plan, DEFAULT_HEADER
        with self.execution_fixture() as (plan,state,packages,native):
            old,source,target,inventory=self.source_move_fixture(plan)
            main=Path(plan['niri_config_path'])
            first=main.parent/'a.kdl';second=main.parent/'b.kdl';alias=main.parent/'alias.kdl'
            first.write_text('// first\n');second.write_text('// second\n');alias.symlink_to(first.name)
            main.write_text(DEFAULT_HEADER+'\ninclude "a.kdl"\ninclude "b.kdl"\ninclude "alias.kdl"\nbinds {\n  Mod+Space { spawn "bash" '+json.dumps(str(old/'adws'))+' "menu"; }\n}\n')
            plan['niri_relocation']=relocation_plan(main,plan['source_migration'])
            self.assertFalse(plan['niri_relocation']['conflicts'])
            alias.unlink();alias.symlink_to(second.name)
            changed=relocation_plan(main,plan['source_migration'])
            self.assertEqual(changed['source_hashes'],plan['niri_relocation']['source_hashes'])
            with self.assertRaisesRegex(ValueError,'包含关系发生变化'):
                workflow.refreshed_niri_relocation(plan)

    def test_topbar_restart_failure_restores_paths_inventory_and_previous_bar_before_retry(self):
        from adws_install_topbar_migration import plan as topbar_plan
        with self.execution_fixture() as (plan,state,packages,native):
            old,source,target,inventory=self.source_move_fixture(plan)
            live=self.home/'.config/waybar/config.jsonc';live.parent.mkdir()
            original=json.dumps({'custom/settings':{'on-click':'bash '+shlex.quote(str(old/'adws'))+' config'},'height':37})+'\n'
            live.write_text(original)
            style=live.parent/'style.css';style.write_text('* { font-family: "Personal"; }\n')
            plan['topbar_migration']=topbar_plan(plan['config_home'],plan['source_migration'])
            self.assertFalse(plan['topbar_migration']['conflicts'],plan['topbar_migration']['conflicts'])
            self.assertTrue(plan['topbar_migration']['restart_profiles'])
            events=[];fail=[True];case=self
            class Bars:
                def capture(self):events.append('capture')
                def stop(self):
                    case.assertEqual(live.read_text(),original);events.append('stop')
                def start_new(self):
                    case.assertIn(str(case.source/'adws'),live.read_text())
                    case.assertEqual(json.loads(inventory.read_text())['root'],str(case.source))
                    events.append('start-new')
                    if fail[0]:raise RuntimeError('topbar start failed')
                def stop_new(self):
                    case.assertIn(str(case.source/'adws'),live.read_text());events.append('stop-new')
                def restore_old(self):
                    case.assertEqual(live.read_text(),original)
                    case.assertEqual(json.loads(inventory.read_text())['root'],str(old))
                    events.append('restore-old')
                def close(self):events.append('close')
            def configure():inventory.write_text(json.dumps({'root':str(self.source)}))
            state['configuration_hook']=configure
            with patch('adws_install_bar_lifecycle.TopbarLifecycle',return_value=Bars()) as lifecycle, patch.object(transaction,'integration_paths',return_value=[self.home/'.config/adws',inventory]):
                with self.assertRaisesRegex(RuntimeError,'topbar start failed'):workflow.execute(plan,self.root/'journal')
                self.assertEqual(events,['capture','stop','start-new','stop-new','restore-old','close'])
                self.assertEqual(lifecycle.call_args.args[0],plan['topbar_migration']['restart_profiles'])
                self.assertEqual(style.read_text(),'* { font-family: "Personal"; }\n')
                self.assertFalse(target.exists())
                fail[0]=False;events.clear()
                self.assertEqual(workflow.execute(plan,self.root/'journal'),2)
                self.assertEqual(events,['capture','stop','start-new','close'])
            progress=json.loads((self.root/'journal/progress.json').read_text())
            self.assertEqual(progress['steps']['topbar-source-migration']['status'],'passed')
            self.assertIn(str(live),progress['deployment_receipt'])

    def test_source_build_library_is_migrated_after_native_install_and_rolls_back(self):
        from adws_layout import desktop_space_relocation_plan, default_layout, INTERNAL_SPACE_MODULE
        with self.execution_fixture(fail_configuration=True) as (plan,state,packages,native):
            old,source,target,inventory=self.source_move_fixture(plan)
            old_library=old/'src/niri-desktop-layer/integration/libwaybar-space.so'
            old_library.parent.mkdir();old_library.write_bytes(b'old inert artifact')
            installed=self.home/'.local/lib/waybar/libwaybar-space.so'
            live=self.home/'.config/waybar/config-bottom.jsonc';live.parent.mkdir()
            original=json.dumps({INTERNAL_SPACE_MODULE:{'module_path':str(old_library)},'height':47})+'\n'
            live.write_text(original)
            saved=self.home/'.config/adws/taskbar-layout.json';saved.parent.mkdir()
            saved.write_text(json.dumps(default_layout()))
            plan['bottom_library_migration']=desktop_space_relocation_plan(plan['config_home'],plan['source_migration'],home=self.home)
            self.assertFalse(plan['bottom_library_migration']['conflicts'])
            self.assertTrue(plan['bottom_library_migration']['files'])
            self.assertFalse(installed.exists())
            def prepare():
                self.assertEqual(live.read_text(),original)
                installed.parent.mkdir(parents=True,exist_ok=True);installed.write_bytes(b'new inert artifact')
            def configure():
                self.assertEqual(json.loads(live.read_text())[INTERNAL_SPACE_MODULE]['module_path'],str(installed))
                self.assertEqual(installed.read_bytes(),b'new inert artifact')
            native.side_effect=prepare;state['configuration_hook']=configure
            with patch.object(transaction,'integration_paths',return_value=[saved.parent,inventory,installed]):
                with self.assertRaises(subprocess.CalledProcessError):workflow.execute(plan,self.root/'journal')
                self.assertEqual(live.read_text(),original)
                self.assertFalse(installed.exists())
                state['fail']=False
                self.assertEqual(workflow.execute(plan,self.root/'journal'),2)
            progress=json.loads((self.root/'journal/progress.json').read_text())
            self.assertEqual(progress['steps']['bottom-library-migration']['status'],'passed')
            self.assertIn(str(live),progress['deployment_receipt'])
            self.assertEqual(old_library.read_bytes(),b'old inert artifact')

    def test_plan_does_not_write_configuration_progress_or_launch_apps(self):
        before = list(self.home.rglob('*'))
        with patch.object(workflow.subprocess,'run') as run, patch.object(workflow.subprocess,'Popen') as popen:
            result = self.selected()
        self.assertEqual(list(self.home.rglob('*')), before)
        self.assertEqual(result['blocking'], [])
        self.assertNotIn('approved',result)
        run.assert_not_called(); popen.assert_not_called()

    def test_uninstalled_explicit_default_fails_before_plan(self):
        with self.assertRaises(ValueError): self.selected({'terminal':'missing.desktop'})
        self.assertEqual(list(self.home.rglob('*')), [])

    def test_removed_selected_application_fails_before_default_writes(self):
        plan = self.selected()
        removed = dict(self.apps); removed['terminal'] = []
        with patch.object(workflow,'installed_apps',return_value=removed), patch.object(workflow.subprocess,'run') as run:
            with self.assertRaises(ValueError): workflow.configure_defaults(plan)
        run.assert_not_called()
        self.assertFalse((self.home/'.config').exists())

    def test_installed_apps_does_not_accept_missing_exec_or_shadowed_system_entry(self):
        data = self.home/'.local/share/applications'; data.mkdir(parents=True)
        system = self.root/'system-data/applications'; system.mkdir(parents=True)
        template = '[Desktop Entry]\nType=Application\nName=Fixture\nCategories=TerminalEmulator;\nExec={}\n'
        (data/'bad.desktop').write_text(template.format('adws-nonexistent-fixture'))
        (data/'good.desktop').write_text(template.format('true'))
        (system/'hidden.desktop').write_text(template.format('true'))
        (data/'hidden.desktop').write_text(template.format('true')+'Hidden=true\n')
        result = workflow.installed_apps()
        self.assertEqual([a['desktop_id'] for a in result['terminal']],['good.desktop'])

    def test_desktop_inventory_preserves_nondefault_associations_and_nested_ids(self):
        folder=self.home/'.local/share/applications/vendor';folder.mkdir(parents=True)
        (folder/'pdf.desktop').write_text('[Desktop Entry]\nType=Application\nName=PDF Reader\nExec=true %f\nCategories=Viewer;\n')
        self.assertEqual([a['desktop_id'] for a in workflow.desktop_inventory()],['vendor-pdf.desktop'])
        self.assertFalse(any(workflow.installed_apps().values()))

    def test_env_wrapper_requires_an_installed_target(self):
        folder=self.home/'.local/share/applications';folder.mkdir(parents=True)
        header='[Desktop Entry]\nType=Application\nName=Fixture\nCategories=TerminalEmulator;\nExec='
        (folder/'good.desktop').write_text(header+'env -u REMOVE COLOR=blue true %u\n')
        (folder/'bad.desktop').write_text(header+'env COLOR=blue adws-definitely-missing-test\n')
        (folder/'empty.desktop').write_text(header+'env COLOR=blue\n')
        (folder/'path.desktop').write_text(header+'env PATH=/adws-missing-bin true\n')
        self.assertEqual([a['desktop_id'] for a in workflow.installed_apps()['terminal']],['good.desktop'])

    def test_palette_registration_is_covered_by_outer_transaction_rollback(self):
        directory=self.root/'journal'
        kitty=self.home/'.config/kitty/kitty.conf';kitty.parent.mkdir(parents=True)
        kitty.write_text('font_size 14\n')
        with self.execution_fixture(fail_configuration=True) as (plan,state,packages,native):
            from adws_palette_sync import registration_plan
            plan['palette_plan']=registration_plan(['kitty'],config_home=plan['config_home'],data_home=plan['data_home'],home=plan['home'])
            with self.assertRaises(subprocess.CalledProcessError):workflow.execute(plan,directory)
            self.assertEqual(kitty.read_text(),'font_size 14\n')
            self.assertFalse((self.home/'.config/adws/palette-sync.json').exists())
            state['fail']=False
            self.assertEqual(workflow.execute(plan,directory),2)
            self.assertIn('include ',kitty.read_text())
            self.assertEqual(json.loads((directory/'palette-result.json').read_text())['status'],'registered')

    def test_resume_rechecks_completed_steps_and_reruns_drifted_files(self):
        plan = {'fixture':1}; directory = self.root/'journal'
        operation = Mock(); verified = Mock(side_effect=[True, True, False, True])
        journal = workflow.Journal(directory,plan)
        journal.step('files',operation,verified)
        resumed = workflow.Journal(directory,plan)
        resumed.step('files',operation,verified)
        self.assertEqual(operation.call_count,1)
        resumed.step('files',operation,verified)
        self.assertEqual(operation.call_count,2)
        self.assertEqual(verified.call_count,4)

    def test_resume_never_skips_step_without_verifier(self):
        journal=workflow.Journal(self.root/'journal',{'fixture':1})
        operation=Mock()
        journal.step('files',operation)
        journal.step('files',operation)
        self.assertEqual(operation.call_count,2)

    def test_failure_is_durable_and_changed_plan_cannot_resume(self):
        directory=self.root/'journal';journal=workflow.Journal(directory,{'fixture':1})
        with self.assertRaises(RuntimeError): journal.step('files',Mock(side_effect=RuntimeError('fixture failed')))
        self.assertEqual(json.loads((directory/'progress.json').read_text())['steps']['files']['status'],'failed')
        with self.assertRaises(ValueError): workflow.Journal(directory,{'fixture':2})

    def test_modified_source_rejected_before_packages(self):
        plan=self.selected();plan['approved']=True
        (self.source/'install.sh').write_text('# changed after confirmation\n')
        with patch('adws_setup.install_packages') as install:
            with self.assertRaises(ValueError): workflow.execute(plan,self.root/'journal')
        install.assert_not_called()
        self.assertFalse((self.root/'journal').exists())

    def test_native_source_is_part_of_resume_fingerprint(self):
        folder=self.source/'src/native';folder.mkdir(parents=True)
        path=folder/'main.rs';path.write_text('original')
        first=workflow.fingerprint(self.source)
        path.write_text('changed')
        self.assertNotEqual(first,workflow.fingerprint(self.source))

    def test_fingerprint_covers_sources_beneath_bootstrap_state_directory(self):
        source=self.root/'state/adws/bootstrap/bundle';(source/'tools').mkdir(parents=True)
        path=source/'tools/adws_setup.py';path.write_text('before')
        before=workflow.fingerprint(source);path.write_text('after')
        self.assertNotEqual(before,workflow.fingerprint(source))

    def test_fingerprint_binds_reviewed_prebuilt_artifacts_and_manifest(self):
        folder=self.source/'prebuilt';folder.mkdir()
        (folder/'manifest.json').write_text('{}')
        artifact=folder/'libniri_taskbar.so';artifact.write_bytes(b'before')
        before=workflow.fingerprint(self.source);artifact.write_bytes(b'after')
        self.assertNotEqual(before,workflow.fingerprint(self.source))

    def test_transaction_restores_operation_files_and_removes_new_files(self):
        config=self.home/'.config/fixture';config.mkdir(parents=True)
        original=config/'old';original.write_text('personal')
        def operation(backup):
            self.assertTrue(Path(backup).exists())
            original.write_text('changed')
            (config/'new').write_text('new file')
            raise RuntimeError('operation failed')
        with patch('adws_runtime.pids',return_value=[]), patch.object(transaction,'integration_paths',return_value=[]):
            with self.assertRaisesRegex(RuntimeError,'operation failed'):
                transaction.install(self.source,operation=operation,extra_paths=[config])
        self.assertEqual(original.read_text(),'personal')
        self.assertFalse((config/'new').exists())
        manifests=list((self.home/'.local/state/adws-install-backups').rglob('manifest.json'))
        self.assertEqual(len(manifests),1)

    @contextlib.contextmanager
    def execution_fixture(self, fail_configuration=False, report=None):
        """Real snapshots/config writes; fake only external package/UI effects."""
        config = self.home/'.config'
        config.mkdir(exist_ok=True)
        mime = config/'mimeapps.list'; mime.write_text('personal associations\n')
        niri = config/'niri/config.kdl'; niri.parent.mkdir(exist_ok=True)
        niri.write_text('// personal niri config\n')
        plan = self.selected(); plan['approved'] = True
        plan['package_candidates'] = ['fixture-package']
        database = set(); commands = []; associations = {}
        state = {'fail': fail_configuration, 'installed': database, 'commands': commands}
        real_run = subprocess.run
        def run(argv, **kwargs):
            commands.append(list(argv))
            if argv[0] == 'cp': return real_run(argv, **kwargs)
            if argv[:2] == ['xdg-mime','default']:
                associations[argv[3]] = argv[2]
                mime.write_text(json.dumps(associations))
                return subprocess.CompletedProcess(argv,0)
            if argv == ['bash',str(self.source/'scripts/adws-install.sh')]:
                (config/'adws').mkdir(exist_ok=True)
                (config/'adws/installed.json').write_text('{"installed":true}')
                if state.get('configuration_hook'):state['configuration_hook']()
                if state['fail']: raise subprocess.CalledProcessError(7,argv)
                return subprocess.CompletedProcess(argv,0)
            raise AssertionError('Unexpected external command: '+repr(argv))
        def install_packages(programs, *, system_upgrade=False): database.update(programs)
        def apply_niri(proposal, backup): niri.write_text('// validated generated config\n')
        report = report or {'complete':False,'failed':[],'pending':['preview'],'checks':[]}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(workflow,'install_log',side_effect=lambda _:contextlib.nullcontext()))
            stack.enter_context(patch('adws_runtime.pids',return_value=[]))
            stack.enter_context(patch.object(transaction,'integration_paths',return_value=[config/'adws']))
            package_call=stack.enter_context(patch('adws_setup.install_packages',side_effect=install_packages))
            native_call=stack.enter_context(patch('adws_setup.prepare',return_value=0))
            stack.enter_context(patch('adws_niri_install.installed_packages',side_effect=lambda manager,wanted:set(wanted)&database))
            stack.enter_context(patch('adws_niri_install.package_candidates',side_effect=lambda manager,wanted:dict.fromkeys(wanted,'1.0')))
            stack.enter_context(patch('adws_install_niri.plan',return_value={'conflicts':[]}))
            stack.enter_context(patch('adws_install_niri.apply',side_effect=apply_niri))
            stack.enter_context(patch('adws_niri_install.validate'))
            stack.enter_context(patch('adws_niri_compat.niri_binary',return_value='/bin/niri-fixture'))
            stack.enter_context(patch.object(workflow,'installed_apps',return_value=self.apps))
            stack.enter_context(patch.object(workflow.subprocess,'run',side_effect=run))
            stack.enter_context(patch.object(transaction,'run',side_effect=lambda argv,**kwargs:run(argv,**kwargs)))
            stack.enter_context(patch.object(workflow.subprocess,'check_output',side_effect=lambda argv,**kwargs:associations[argv[-1]]))
            stack.enter_context(patch('adws_install_acceptance.evaluate',return_value=report))
            yield plan, state, package_call, native_call

    def test_execute_failure_rolls_back_real_files_and_resume_keeps_packages(self):
        directory = self.root/'journal'
        original_env = dict(os.environ)
        with self.execution_fixture(fail_configuration=True) as (plan,state,packages,native):
            with self.assertRaises(subprocess.CalledProcessError): workflow.execute(plan,directory)
            self.assertEqual((self.home/'.config/mimeapps.list').read_text(),'personal associations\n')
            self.assertEqual((self.home/'.config/niri/config.kdl').read_text(),'// personal niri config\n')
            self.assertFalse((self.home/'.config/adws/default-terminal.json').exists())
            self.assertFalse((self.home/'.config/adws/installed.json').exists())
            journal=json.loads((directory/'progress.json').read_text())
            self.assertEqual(journal['steps']['packages']['status'],'passed')
            self.assertEqual(journal['steps']['native-components']['status'],'rolled-back')
            self.assertEqual(journal['steps']['default-applications']['status'],'rolled-back')
            self.assertEqual(journal['steps']['adws-configuration']['status'],'failed')
            self.assertTrue(journal['backups'])
            self.assertEqual(json.loads((directory/'failure.json').read_text())['status'],'failed')
            self.assertEqual(dict(os.environ),original_env)
            state['fail']=False
            self.assertEqual(workflow.execute(plan,directory),2)
            packages.assert_called_once()
            self.assertEqual(native.call_count,2,'rolled-back native step must rerun')
            journal=json.loads((directory/'progress.json').read_text())
            self.assertTrue(journal['steps']['packages']['revalidated'])
            self.assertEqual(journal['status'],'pending-acceptance')
            self.assertTrue((self.home/'.config/adws/installed.json').exists())
            self.assertEqual(json.loads((directory/'resolved-plan.json').read_text())['applications'],plan['applications'])
            self.assertTrue(all(cmd[0] in ('cp','xdg-mime','bash') for cmd in state['commands']))
            self.assertEqual(dict(os.environ),original_env)

    def test_execute_failed_acceptance_has_failure_status_and_exit_code(self):
        report={'complete':False,'failed':['taskbar'],'pending':[],'checks':[]}
        with self.execution_fixture(report=report) as (plan,state,packages,native):
            directory=self.root/'journal'
            self.assertEqual(workflow.execute(plan,directory),1)
            self.assertEqual(json.loads((directory/'progress.json').read_text())['status'],'acceptance-failed')
            self.assertEqual(json.loads((directory/'acceptance.json').read_text())['failed'],['taskbar'])

    def test_failed_snapshot_restore_is_not_reported_as_rolled_back_or_replayed(self):
        with self.execution_fixture(fail_configuration=True) as (plan,state,packages,native):
            directory=self.root/'journal'
            with patch.object(transaction.Snapshot,'restore',side_effect=RuntimeError('cannot restore fixture')):
                with self.assertRaisesRegex(RuntimeError,'配置快照未完整恢复'):
                    workflow.execute(plan,directory)
            self.assertTrue((self.home/'.config/adws/installed.json').is_file(),'configuration was not restored')
            progress=json.loads((directory/'progress.json').read_text())
            self.assertFalse(progress['configuration_restored'])
            self.assertEqual(progress['status'],'recovery-incomplete')
            self.assertEqual(progress['steps']['native-components']['status'],'passed')
            result=json.loads((directory/'result.json').read_text())
            self.assertEqual(result['rolled_back'],[])
            self.assertFalse(result['configuration_restored'])
            self.assertTrue(result['recovery_errors'])
            count=native.call_count
            with self.assertRaisesRegex(ValueError,'上次安装的自动恢复未完成'):
                workflow.execute(plan,directory)
            self.assertEqual(native.call_count,count)
            self.assertIn('旧计划不能自动重放',json.loads((directory/'failure.json').read_text())['resume'])

    def test_theme_failure_before_result_uses_recorded_backup_and_restores_user_config(self):
        with self.execution_fixture() as (plan,state,packages,native):
            plan['theme_plan']={'changes':[{'fixture':True}]}
            directory=self.root/'journal';backup=str(self.root/'system-theme-backup')
            with patch.object(workflow,'system_theme_action',side_effect=[RuntimeError('helper failed before result'),{'conflicts':[]}]) as action, patch('adws_install_boot_themes.operation_backup',return_value=backup):
                with self.assertRaisesRegex(RuntimeError,'helper failed before result'):
                    workflow.execute(plan,directory)
            self.assertEqual(action.call_count,2)
            self.assertEqual(action.call_args.kwargs,{'rollback':backup})
            self.assertEqual((self.home/'.config/mimeapps.list').read_text(),'personal associations\n')
            journal=json.loads((directory/'progress.json').read_text())
            self.assertEqual(journal['recovery_errors'],[])
            self.assertEqual(journal['steps']['packages']['status'],'passed')
            self.assertTrue((directory/'system-theme-rollback.json').is_file())

    def test_active_privileged_recovery_is_reported_without_starting_another_helper(self):
        with self.execution_fixture() as (plan,state,packages,native):
            plan['theme_plan']={'changes':[{'fixture':True}]}
            directory=self.root/'journal'
            with patch.object(workflow,'system_theme_action',side_effect=RuntimeError('helper still recovering')) as action, patch('adws_install_boot_themes.operation_backup',side_effect=RuntimeError('recovery still running')):
                with self.assertRaisesRegex(RuntimeError,'recovery still running'):
                    workflow.execute(plan,directory)
            action.assert_called_once_with(plan,directory)
            self.assertEqual((self.home/'.config/mimeapps.list').read_text(),'personal associations\n')
            journal=json.loads((directory/'progress.json').read_text())
            self.assertEqual(len(journal['recovery_errors']),1)

    def test_failure_before_theme_step_does_not_reuse_an_old_theme_operation(self):
        with self.execution_fixture(fail_configuration=True) as (plan,state,packages,native):
            plan['theme_plan']={'changes':[{'fixture':True}]}
            directory=self.root/'journal';directory.mkdir()
            (directory/'system-theme-operation.json').write_text('{"state":"applied","backup":"old-operation"}')
            with patch.object(workflow,'system_theme_action') as action, patch('adws_install_boot_themes.operation_backup',side_effect=AssertionError('unrelated old operation')) as lookup:
                with self.assertRaises(subprocess.CalledProcessError):workflow.execute(plan,directory)
            action.assert_not_called();lookup.assert_not_called()

    def test_execute_revalidates_package_database_on_resume(self):
        with self.execution_fixture() as (plan,state,packages,native):
            directory=self.root/'journal'
            self.assertEqual(workflow.execute(plan,directory),2)
            state['installed'].clear()
            self.assertEqual(workflow.execute(plan,directory),2)
            self.assertEqual(packages.call_count,2,'package removed since first execution must be restored')

    def test_arch_upgrade_checks_reviewed_sources_and_does_not_use_stale_repository_query(self):
        with self.execution_fixture() as (plan,state,packages,native):
            plan['system_upgrade']=True;plan['package_review']={'source_fingerprint':'fixture-review'}
            with patch('adws_install_arch_packages.verify_sources',return_value=True) as verify, patch('adws_niri_install.package_candidates',side_effect=AssertionError('must not resolve old sync DB')):
                self.assertEqual(workflow.execute(plan,self.root/'journal'),2)
            verify.assert_called_once_with(plan['package_review'])
            packages.assert_called_once_with(programs=['fixture-package'], system_upgrade=True)

    def test_changed_arch_sources_block_upgrade_before_any_package_or_config_write(self):
        with self.execution_fixture() as (plan,state,packages,native):
            plan['system_upgrade']=True;plan['package_review']={'source_fingerprint':'old-review'}
            with patch('adws_install_arch_packages.verify_sources',side_effect=ValueError('sources changed')):
                with self.assertRaisesRegex(ValueError,'sources changed'):workflow.execute(plan,self.root/'journal')
            packages.assert_not_called();native.assert_not_called()

    def test_resume_after_deployment_only_revalidates_not_rewrites(self):
        with self.execution_fixture() as (plan,state,packages,native):
            directory=self.root/'journal'
            self.assertEqual(workflow.execute(plan,directory),2)
            receipt=json.loads((directory/'progress.json').read_text())['deployment_receipt']
            self.assertIn(str(self.home/'.config/niri/config.kdl'),receipt)
            self.assertEqual(workflow.execute(plan,directory),2)
            native.assert_called_once()
            packages.assert_called_once()

    def test_interrupted_acceptance_keeps_commit_receipt_and_resumes_without_reapplying(self):
        import hashlib
        with self.execution_fixture() as (plan,state,packages,native):
            directory=self.root/'journal'
            niri=self.home/'.config/niri/config.kdl'
            plan['provider_plan']={'source_hashes':{str(niri):hashlib.sha256(niri.read_bytes()).hexdigest()},'evidence':{}}
            with patch('adws_install_acceptance.evaluate',side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):workflow.execute(plan,directory)
            progress=json.loads((directory/'progress.json').read_text())
            self.assertEqual(progress['status'],'pending-acceptance')
            self.assertTrue(progress['deployment_receipt'])
            self.assertIn('session-acceptance',json.loads((directory/'result.json').read_text())['pending'])
            self.assertEqual(workflow.execute(plan,directory),2)
            native.assert_called_once()
            packages.assert_called_once()

    def test_sigterm_during_configuration_rolls_back_and_records_failure(self):
        code='''
import json,os,signal,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from test_install_workflow import InstallWorkflowTests,workflow
case=InstallWorkflowTests();case.setUp()
try:
 with case.execution_fixture() as (plan,state,packages,native):
  path=case.home/'.config/niri/config.kdl';before=path.read_bytes()
  def terminate():
   path.write_text('// interrupted native installation\\n')
   os.kill(os.getpid(),signal.SIGTERM)
  native.side_effect=terminate
  try:workflow.execute(plan,case.root/'journal')
  except KeyboardInterrupt:pass
  else:raise AssertionError('termination was not propagated')
  assert path.read_bytes()==before
  progress=json.loads((case.root/'journal/progress.json').read_text())
  assert progress['status']=='failed'
  assert progress['steps']['native-components']['status']=='failed'
  assert (case.root/'journal/failure.json').is_file()
finally:case.doCleanups()
'''
        result=subprocess.run([sys.executable,'-c',code,str(Path(__file__).parent)],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_resume_does_not_overwrite_user_edit_after_deployment(self):
        with self.execution_fixture() as (plan,state,packages,native):
            directory=self.root/'journal'
            workflow.execute(plan,directory)
            path=self.home/'.config/niri/config.kdl';path.write_text('// later personal edits\n')
            with self.assertRaisesRegex(ValueError,'安装后文件发生变化'):workflow.execute(plan,directory)
            self.assertEqual(path.read_text(),'// later personal edits\n')
            native.assert_called_once()


class InstalledApplicationEntryTests(unittest.TestCase):
    """Choose visible window launchers, preserving hidden MIME migration data."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='adws-desktop-entry-test-')
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.apps = self.folder/'data/applications'; self.apps.mkdir(parents=True)
        self.bin = self.folder/'bin'; self.bin.mkdir()
        for name in ('foot', 'kitty', 'alacritty', 'viewer', 'emacs'):
            path=self.bin/name; path.write_text('#!/bin/sh\nexit 0\n'); path.chmod(0o755)
        env = patch.dict(os.environ, {'HOME':str(self.folder/'home'),
            'XDG_CONFIG_HOME':str(self.folder/'home/.config'),
            'XDG_DATA_HOME':str(self.folder/'data'), 'XDG_DATA_DIRS':str(self.folder/'system'),
            'PATH':str(self.bin)+os.pathsep+os.environ.get('PATH',''), 'NIRI_CONFIG':''})
        env.start(); self.addCleanup(env.stop)

    def entry(self, name, argv, *, categories='TerminalEmulator;', extra=''):
        path=self.apps/name
        path.write_text('[Desktop Entry]\nType=Application\nName='+name+'\nExec='+argv+'\nCategories='+categories+'\n'+extra)
        return path

    def test_visible_foot_server_and_hidden_kitty_helper_are_not_terminal_candidates(self):
        # These fields match the real package entries; Foot Server is visible.
        self.entry('foot-server.desktop','foot --server')
        self.entry('foot.desktop','foot')
        self.entry('kitty-open.desktop','kitty +open %U',extra='NoDisplay=true\n')
        self.entry('kitty.desktop','kitty')
        self.entry('Alacritty.desktop','alacritty',extra='TryExec=alacritty\n')
        selected=workflow.installed_apps()['terminal']
        self.assertEqual({a['desktop_id'] for a in selected}, {'foot.desktop','kitty.desktop','Alacritty.desktop'})
        self.assertEqual(selected[0]['desktop_id'], 'kitty.desktop')
        self.assertTrue(all(a['argv'] in (['foot'],['kitty'],['alacritty']) for a in selected))
        inventory={a['desktop_id']:a for a in workflow.desktop_inventory()}
        self.assertTrue(inventory['foot-server.desktop']['background_only'])
        self.assertTrue(inventory['kitty-open.desktop']['no_display'])

    def test_firefox_precedes_another_browser_in_the_app_menu(self):
        self.entry('a-browser.desktop', 'viewer', categories='WebBrowser;')
        self.entry('org.mozilla.firefox.desktop', 'viewer', categories='WebBrowser;')
        browsers = workflow.installed_apps()['browser']
        self.assertEqual([app['desktop_id'] for app in browsers], ['org.mozilla.firefox.desktop', 'a-browser.desktop'])

    def test_service_filter_uses_real_arguments_not_id_or_localized_name(self):
        self.entry('normal-looking.desktop', 'env -u REMOVE COLOR=blue foot --server=/tmp/test.sock')
        self.entry('short-option.desktop', 'env -- foot -s')
        self.entry('nested-env.desktop', 'env COLOR=blue env foot --server')
        self.entry('service-editor.desktop', 'emacs --daemon', categories='TextEditor;')
        self.entry('name-says-server.desktop','kitty --title --server')
        self.entry('inside-terminal.desktop','foot -e viewer --server')
        candidates=workflow.installed_apps()
        self.assertEqual({a['desktop_id'] for a in candidates['terminal']}, {'name-says-server.desktop','inside-terminal.desktop'})
        self.assertEqual(candidates['text_editor'],[])

    def test_nodisplay_entry_still_shadows_system_entry_and_preserves_mime_inventory(self):
        system=self.folder/'system/applications';system.mkdir(parents=True)
        original=self.entry('viewer.desktop','viewer %f',categories='Viewer;TextEditor;')
        (system/'viewer.desktop').write_text(original.read_text())
        original.write_text(original.read_text()+'NoDisplay=true\n')
        self.assertEqual(workflow.installed_apps()['text_editor'],[])
        self.assertEqual([a['desktop_id'] for a in workflow.desktop_inventory()],['viewer.desktop'])

    def test_explicit_background_terminal_choice_rejected_before_plan_and_normal_foot_selected(self):
        self.entry('foot-server.desktop','foot --server')
        self.entry('foot.desktop','foot')
        with patch('adws_install_features.feature_plan',return_value={'manager':'pacman','packages':[],'features':[]}), patch('adws_setup.cargo_source_configuration',return_value=None), patch.object(workflow,'fingerprint',return_value='fixture'), patch.object(workflow,'prebuilt_status',return_value={'status':'missing'}):
            with self.assertRaisesRegex(ValueError,'foot-server.desktop'):
                workflow.selected_plan('fresh',root=self.folder,choices={'terminal':'foot-server.desktop'})
            by_default = workflow.selected_plan('fresh',root=self.folder)
            self.assertEqual(by_default['applications']['terminal']['install_package'], 'kitty')
            proposal=workflow.selected_plan('fresh',root=self.folder,choices={'terminal':'foot.desktop'})
        self.assertEqual(proposal['applications']['terminal']['desktop_id'],'foot.desktop')
        self.assertEqual(proposal['applications']['terminal']['argv'],['foot'])


if __name__=='__main__':unittest.main()

from pathlib import Path
import sys
import tempfile
import hashlib
import json
import shlex
import shutil
import subprocess
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_install_startup as startup


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config=self.root/'config';self.config.mkdir()
        self.niri=self.config/'niri/config.kdl';self.niri.parent.mkdir();self.niri.write_text('// user config\n')
        self.options={'enabled_units':[],'unit_dirs':[self.config/'systemd/user'],'autostart_dirs':[self.config/'autostart']}
    def test_owner_signature_ignores_moved_lines_but_preserves_changed_or_duplicate_commands(self):
        first={'taskbar':[{'origin':'niri','id':'/config/niri.kdl:85','argv':['adws','taskbar','-s'],'components':['taskbar']}]}
        moved={'taskbar':[{**first['taskbar'][0],'id':'/config/niri.kdl:76'}]}
        self.assertEqual(startup.owner_signature(first),startup.owner_signature(moved))
        duplicate={'taskbar':moved['taskbar']*2}
        self.assertNotEqual(startup.owner_signature(first),startup.owner_signature(duplicate))
        changed={'taskbar':[{**moved['taskbar'][0],'argv':['/other/adws','taskbar','-s']}]}
        self.assertNotEqual(startup.owner_signature(first),startup.owner_signature(changed))
        other={'taskbar':[{**moved['taskbar'][0],'id':'/config/other.kdl:76'}]}
        self.assertNotEqual(startup.owner_signature(first),startup.owner_signature(other))

    def desktop(self,name,command,extra=''):
        path=self.config/'autostart'/name;path.parent.mkdir(exist_ok=True)
        path.write_text('[Desktop Entry]\nType=Application\nExec='+command+'\n'+extra)
    def plan(self,commands):return startup.plan(self.config,commands,**self.options)
    def test_existing_xdg_input_method_preserved(self):
        self.desktop('fcitx.desktop','fcitx5 -d')
        plan=self.plan({'input-method':['fcitx5','-d']})
        self.assertEqual(plan['preserved'],['input-method']);self.assertFalse(plan['additions'])
        self.assertEqual(startup.apply(plan,self.root/'backup',lambda _:None)['status'],'unchanged')
    def test_conflicting_routes_are_reported_and_never_disabled(self):
        self.desktop('fcitx.desktop','fcitx5 -d')
        self.niri.write_text('spawn-at-startup "ibus-daemon" "-d"\n')
        plan=self.plan({'input-method':['fcitx5','-d']})
        self.assertEqual(plan['conflicts'][0]['component'],'input-method')
        with self.assertRaises(ValueError):startup.apply(plan,self.root/'backup',lambda _:None)
        self.assertTrue((self.config/'autostart/fcitx.desktop').exists())
    def test_clipboard_text_and_image_are_independent_valid_owners(self):
        self.niri.write_text('spawn-at-startup "wl-paste" "-t" "text" "--watch" "cliphist" "store"\nspawn-at-startup "wl-paste" "-t" "image" "--watch" "cliphist" "store"\n')
        plan=self.plan({})
        self.assertFalse(plan['conflicts']);self.assertEqual(len(plan['owners']['clipboard-text']),1)
    def test_enabled_user_service_prevents_duplicate_niri_start(self):
        path=self.config/'systemd/user/mako.service';path.parent.mkdir(parents=True)
        path.write_text('[Service]\nExecStart=/usr/bin/mako\n')
        self.options['enabled_units']=['mako.service']
        plan=self.plan({'notifications':['mako']})
        self.assertFalse(plan['additions']);self.assertEqual(plan['owners']['notifications'][0]['origin'],'systemd')
    def test_adws_combined_start_covers_both_components(self):
        self.niri.write_text('spawn-at-startup "/custom/install/adws" "--start"\n')
        plan=self.plan({'desktop':['adws','desktop','-s'],'taskbar':['adws','taskbar','-s']})
        self.assertFalse(plan['additions']);self.assertCountEqual(plan['preserved'],['desktop','taskbar'])
    def test_apply_validates_and_is_idempotent_after_replan(self):
        plan=self.plan({'taskbar':['/custom/install/adws','taskbar','-s']});checks=[]
        startup.apply(plan,self.root/'backup',lambda p:checks.append(p.read_text()))
        self.assertEqual(len(checks),1);self.assertIn('"/custom/install/adws"',checks[0])
        self.assertFalse(self.plan({'taskbar':['adws','taskbar','-s']})['additions'])
        self.assertEqual((self.root/'backup/config.kdl').read_text(),'// user config\n')
    def test_validation_failure_preserves_original(self):
        plan=self.plan({'taskbar':['adws','taskbar','-s']})
        def reject(_):raise ValueError('fixture unsupported config')
        with self.assertRaises(ValueError):startup.apply(plan,self.root/'backup',reject)
        self.assertEqual(self.niri.read_text(),'// user config\n')
    def test_startup_changed_after_review_blocks_write(self):
        plan=self.plan({'input-method':['fcitx5','-d']})
        self.desktop('fcitx.desktop','fcitx5 -d')
        with self.assertRaises(ValueError):startup.apply(plan,self.root/'backup',lambda _:None)
        self.assertEqual(self.niri.read_text(),'// user config\n')
    def test_disabled_and_other_desktop_entries_ignored(self):
        self.desktop('fcitx.desktop','fcitx5 -d','Hidden=true\n')
        self.desktop('ibus.desktop','ibus-daemon -d','OnlyShowIn=GNOME;\n')
        self.assertEqual(len(self.plan({'input-method':['fcitx5','-d']})['additions']),1)
    def test_included_niri_file_is_audited(self):
        (self.niri.parent/'startup.kdl').write_text('spawn-at-startup "mako"\n')
        self.niri.write_text('include "startup.kdl"\n')
        self.assertFalse(self.plan({'notifications':['mako']})['additions'])

    def test_niri_startup_terminator_and_comment_do_not_change_executable(self):
        self.niri.write_text('spawn-at-startup "ibus-daemon"; // active provider\n')
        result=self.plan({'input-method':['ibus-daemon']})
        self.assertFalse(result['unknown']);self.assertFalse(result['additions'])
        self.assertEqual(result['owners']['input-method'][0]['argv'],['ibus-daemon'])

    def test_bash_script_and_env_wrappers_are_recognized_without_execution(self):
        command=['env','XMODIFIERS=@im=fcitx','bash','/custom path/adws','desktop','-s']
        self.assertEqual(startup.components(command),{'desktop'})
        proposal=self.plan({'desktop':command})
        startup.apply(proposal,self.root/'backup',lambda _:None)
        self.assertFalse(self.plan({'desktop':command})['additions'])

    def test_headless_filesystem_enablement_and_aliases_avoid_duplicate_owner(self):
        folder=self.config/'systemd/user';folder.mkdir(parents=True)
        service=folder/'mako.service';service.write_text('[Service]\nExecStart=/usr/bin/mako\n')
        alias=folder/'notifications.service';alias.symlink_to(service)
        wants=folder/'default.target.wants';wants.mkdir()
        (wants/'mako.service').symlink_to(service)
        (wants/'notifications.service').symlink_to(alias)
        self.options['enabled_units']=None
        with patch.object(startup.subprocess,'run',side_effect=AssertionError('must not contact user bus')):
            proposal=self.plan({'notifications':['mako']})
        self.assertFalse(proposal['unknown'])
        self.assertFalse(proposal['additions'])
        self.assertEqual(len(proposal['owners']['notifications']),1)

    def test_user_mask_shadows_globally_enabled_component(self):
        local=self.config/'systemd/user';local.mkdir(parents=True)
        system=self.root/'system-user';system.mkdir()
        service=system/'mako.service';service.write_text('[Service]\nExecStart=/usr/bin/mako\n')
        wants=system/'default.target.wants';wants.mkdir();(wants/'mako.service').symlink_to(service)
        (local/'mako.service').symlink_to('/dev/null')
        self.options.update(enabled_units=None,unit_dirs=[local,system])
        proposal=self.plan({'notifications':['mako']})
        self.assertTrue(any(row['reason']=='masked_component_requires_review' for row in proposal['unknown']))
        with self.assertRaises(ValueError):startup.apply(proposal,self.root/'backup',lambda _:None)
        self.assertTrue((local/'mako.service').is_symlink())




class StartupRelocationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.config=self.root/'config';self.niri=self.config/'niri/config.kdl';self.niri.parent.mkdir(parents=True)
        self.old=self.root/'旧目录 old';self.new=self.root/'新目录 new'
        for folder in (self.old,self.new):folder.mkdir();(folder/'adws').write_text('#!/bin/bash\n')
        self.inventory=self.root/'install-record.json';self.inventory.write_text(json.dumps({'root':str(self.old)}))
        self.migration={'previous_root':str(self.old),'root':str(self.new),'inventory_path':str(self.inventory),
            'source_hashes':{str(self.inventory):hashlib.sha256(self.inventory.read_bytes()).hexdigest()},'conflicts':[]}
        self.options={'enabled_units':[],'unit_dirs':[],'autostart_dirs':[]}
        self.commands={kind:['env','QT_IM_MODULE=fcitx','bash',str(self.new/'adws'),kind,'-s'] for kind in ('desktop','taskbar')}
        self.niri.write_text(self.block())
    def block(self, kind='desktop'):
        argv=[str(self.old/'adws') if arg==str(self.new/'adws') else arg for arg in self.commands[kind]]
        return startup.BEGIN+'\n  spawn-at-startup '+ ' '.join(json.dumps(arg,ensure_ascii=False) for arg in argv)+'; // user note\n'+startup.END+'\n'
    def plan(self,**kwargs):
        return startup.plan(self.config,self.commands,source_migration=self.migration,**self.options,**kwargs)
    def test_relocates_existing_only_without_enabling_missing_components(self):
        before=self.niri.read_text();proposal=self.plan(add_missing=False)
        self.assertFalse(proposal['conflicts']);self.assertFalse(proposal['additions'])
        self.assertEqual([row['component'] for row in proposal['replacements']],['desktop'])
        result=startup.apply(proposal,self.root/'backup',lambda _:None)
        self.assertEqual(self.niri.read_text(),before.replace(str(self.old/'adws'),str(self.new/'adws')))
        self.assertIn('// user note',self.niri.read_text());self.assertNotIn('"taskbar"',self.niri.read_text())
        self.assertEqual(len(result['replacements']),1)
        self.assertFalse(self.plan(add_missing=False)['replacements'])
    def test_owned_nested_includes_are_validated_without_touching_originals(self):
        included=self.niri.parent/'starts 单独.kdl';included.write_text(self.block())
        middle=self.niri.parent/'middle.kdl';middle.write_text('include '+json.dumps(str(included))+'\n')
        original='include optional=true "middle.kdl"\n// unrelated\n';self.niri.write_text(original)
        proposal=self.plan(add_missing=False);before=included.read_text();seen=[]
        def validate(path):
            self.assertEqual(self.niri.read_text(),original);self.assertEqual(included.read_text(),before)
            audit=startup.audit(self.config,niri_path=path,**self.options)
            seen.extend(audit['owners']['desktop'])
            self.assertEqual(audit['owners']['desktop'][0]['argv'],self.commands['desktop'])
            binary=shutil.which('niri')
            if binary:subprocess.run([binary,'validate','-c',str(path)],check=True,capture_output=True)
        startup.apply(proposal,self.root/'backup',validate)
        self.assertEqual(len(seen),1);self.assertEqual(self.niri.read_text(),original)
        self.assertEqual(middle.read_text(),'include '+json.dumps(str(included))+'\n')
        self.assertIn(str(self.new/'adws'),included.read_text())
        self.assertEqual(proposal['snapshot_targets'],[str(included)])
        self.assertFalse(list(self.niri.parent.glob('.adws-startup-*')))
    def test_modified_wrapper_or_unmanaged_owner_never_rewritten(self):
        examples=[self.block().replace(startup.BEGIN+'\n','').replace(startup.END+'\n',''),
                  self.block().replace('QT_IM_MODULE=fcitx','QT_IM_MODULE=custom'),
                  self.block().replace('"-s"','"-s" "--custom"'),
                  startup.BEGIN+'\nspawn-sh-at-startup '+json.dumps('bash '+shlex.quote(str(self.old/'adws'))+' desktop -s')+'\n'+startup.END+'\n']
        for text in examples:
            with self.subTest(text=text):
                self.niri.write_text(text);proposal=self.plan(add_missing=False)
                self.assertTrue(proposal['conflicts'])
                with self.assertRaises(ValueError):startup.apply(proposal,self.root/'backup',lambda _:None)
                self.assertEqual(self.niri.read_text(),text)
    def test_reviewed_inventory_and_include_edits_abort_before_write(self):
        for change in ('inventory','include'):
            with self.subTest(change=change):
                self.setUp()
                included=self.niri.parent/'starts.kdl';included.write_text(self.block());self.niri.write_text('include "starts.kdl"\n')
                proposal=self.plan(add_missing=False)
                target=self.inventory if change=='inventory' else included
                target.write_text(target.read_text()+'\n')
                before=included.read_text()
                with self.assertRaises(ValueError):startup.apply(proposal,self.root/'backup',lambda _:None)
                self.assertEqual(included.read_text(),before)
    def test_validation_failure_leaves_all_real_files_unchanged(self):
        original=self.niri.read_text();proposal=self.plan(add_missing=False)
        def reject(path):raise ValueError('fixture unsupported')
        with self.assertRaisesRegex(ValueError,'fixture unsupported'):startup.apply(proposal,self.root/'backup',reject)
        self.assertEqual(self.niri.read_text(),original)
        self.assertFalse(list(self.niri.parent.glob('.adws-startup-*')))
    def test_transaction_snapshot_restores_relocated_include(self):
        from adws_install_transaction import Snapshot
        included=self.niri.parent/'starts.kdl';included.write_text(self.block());self.niri.write_text('include "starts.kdl"\n')
        before=included.read_bytes();proposal=self.plan(add_missing=False)
        backup=self.root/'snapshot';backup.mkdir();snapshot=Snapshot(backup,[Path(p) for p in proposal['snapshot_targets']])
        startup.apply(proposal,self.root/'startup-backup',lambda _:None)
        self.assertNotEqual(included.read_bytes(),before)
        snapshot.restore();self.assertEqual(included.read_bytes(),before)
    def test_disabled_missing_starts_remain_absent(self):
        self.niri.write_text('// no starts\n');proposal=self.plan(add_missing=False)
        self.assertFalse(proposal['additions']);self.assertFalse(proposal['replacements'])
        self.assertEqual(startup.apply(proposal,self.root/'backup',lambda _:None)['status'],'unchanged')


class PackageOwnerTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.config=self.root/'config';self.config.mkdir()
        self.niri=self.config/'niri/config.kdl';self.niri.parent.mkdir();self.niri.write_text('input {}\n')
        self.system=self.root/'system-autostart';self.system.mkdir()
        self.user=self.config/'autostart'
        self.options={'enabled_units':[],'unit_dirs':[],'autostart_dirs':[self.system,self.user]}
        self.features={'manager':'pacman','features':[{'id':'input','provider':None}]}
        self.source=self.system/'org.fcitx.Fcitx5.desktop'
    def review(self):
        return startup.reviewed_package_owners(self.features,['fcitx5'],self.config,self.niri,
            audit_options=self.options,system_autostart_dir=self.system)
    def package_entry(self):
        self.source.write_text('[Desktop Entry]\nType=Application\nExec=/usr/bin/fcitx5\n')
    def verified(self,path,manager):
        return {'package':'fcitx5','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'verification':'fixture-package-database'}
    def test_new_verified_package_entry_is_masked_before_niri_startup(self):
        review=self.review();self.assertEqual(len(review['entries']),1)
        self.assertIn(str(self.user/self.source.name),review['snapshot_targets'])
        self.package_entry()
        proposal=startup.reconcile_package_owners(review,verify_package=self.verified)
        startup.apply_reviewed_package_owners(proposal,self.root/'backup')
        self.assertIn('Hidden=true',(self.user/self.source.name).read_text())
        plan=startup.plan(self.config,{'input-method':['fcitx5']},**self.options)
        self.assertEqual(len(plan['additions']),1)
        startup.apply(plan,self.root/'startup-backup',lambda _:None)
        self.assertEqual(len(startup.audit(self.config,**self.options)['owners']['input-method']),1)
    def test_autostart_disabled_does_not_create_a_niri_owner(self):
        review=self.review();self.package_entry()
        proposal=startup.reconcile_package_owners(review,verify_package=self.verified)
        startup.apply_reviewed_package_owners(proposal,self.root/'backup')
        self.assertFalse(startup.audit(self.config,**self.options)['owners']['input-method'])
        self.assertEqual(self.niri.read_text(),'input {}\n')
    def test_unknown_added_owner_is_rejected_without_shadow_writes(self):
        review=self.review();self.package_entry()
        (self.system/'unknown.desktop').write_text('[Desktop Entry]\nType=Application\nExec=ibus-daemon\n')
        with self.assertRaises(ValueError):startup.reconcile_package_owners(review,verify_package=self.verified)
        self.assertFalse(self.user.exists())
    def test_wrong_package_and_modified_file_are_rejected(self):
        review=self.review();self.package_entry()
        with self.assertRaises(ValueError):startup.reconcile_package_owners(review,verify_package=lambda p,m:{'package':'unrelated','sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
        def modified(p,m):raise ValueError('package content modified')
        with self.assertRaises(ValueError):startup.reconcile_package_owners(review,verify_package=modified)
    def test_existing_or_new_user_shadow_is_never_overwritten(self):
        self.user.mkdir();target=self.user/self.source.name;target.write_text('[Desktop Entry]\nHidden=true\n')
        self.assertFalse(self.review()['entries'])
        target.unlink();review=self.review();self.package_entry();target.write_text('[Desktop Entry]\nHidden=true\n')
        with self.assertRaises(ValueError):startup.reconcile_package_owners(review,verify_package=self.verified)
    def test_file_changed_between_package_review_and_apply_blocks_write(self):
        review=self.review();self.package_entry();proposal=startup.reconcile_package_owners(review,verify_package=self.verified)
        self.source.write_text(self.source.read_text()+'# custom\n')
        with self.assertRaises(ValueError):startup.apply_reviewed_package_owners(proposal,self.root/'backup')
        self.assertFalse(self.user.exists())

if __name__=='__main__':unittest.main()

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_install_personal as personal
import adws_install_migration as migration


class PersonalReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'old';self.target=self.root/'new'
        self.source.mkdir();self.target.mkdir()
    def put(self,root,path,data):
        p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p
    def review(self,categories=None,**kwargs):return personal.review(self.source,self.target,categories,**kwargs)
    def test_review_approve_or_keep_shell_file_without_execution(self):
        marker=self.root/'never';self.put(self.source,'.bashrc',f'touch {marker}\nalias ll="ls -l"\n'.encode())
        unresolved=self.review(['shell']);self.assertEqual(unresolved['status'],'needs_review')
        approved=self.review(['shell'],decisions={'.bashrc':'import'})
        self.assertEqual(approved['status'],'ready')
        self.assertIn('touch',personal.text_diff(approved,'.bashrc')['diff'])
        migration.apply_migration(approved,self.root/'backup')
        self.assertFalse(marker.exists())
        kept=self.review(['shell'],decisions={'.bashrc':'keep'})
        self.assertEqual(kept['status'],'ready');self.assertFalse(kept['entries'])
    def test_explicit_conflict_choices_replace_or_keep(self):
        self.put(self.source,'.face',b'new');self.put(self.target,'.face',b'old')
        self.assertEqual(self.review(['avatar'])['status'],'needs_review')
        self.assertEqual(self.review(['avatar'],decisions={'.face':'keep'})['status'],'ready')
        plan=self.review(['avatar'],decisions={'.face':'replace'})
        self.assertEqual(plan['preview']['files'][0]['action'],'replace')
        migration.apply_migration(plan,self.root/'backup')
        self.assertEqual((self.target/'.face').read_bytes(),b'new')
        migration.rollback(self.root/'backup');self.assertEqual((self.target/'.face').read_bytes(),b'old')
    def test_target_xdg_and_external_source_xdg_are_honored(self):
        oldconfig=self.root/'source-config';oldconfig.mkdir()
        olddata=self.root/'source-data';olddata.mkdir()
        self.put(oldconfig,'fish/config.fish',b'alias ll="ls -l"\n')
        self.put(olddata,'fonts/personal.ttf',b'font')
        targetconfig=self.root/'destination-config';targetdata=self.root/'destination-data'
        plan=self.review(['shell','fonts'],decisions={'.config/fish/config.fish':'import'},
                         source_xdg={'config':oldconfig,'data':olddata},target_xdg={'config':targetconfig,'data':targetdata})
        migration.apply_migration(plan,self.root/'backup')
        self.assertEqual((targetconfig/'fish/config.fish').read_bytes(),b'alias ll="ls -l"\n')
        self.assertEqual((targetdata/'fonts/personal.ttf').read_bytes(),b'font')
        self.assertFalse((self.target/'.config').exists());self.assertFalse((self.target/'.local').exists())
        migration.rollback(self.root/'backup')
        self.assertFalse(targetconfig.exists());self.assertFalse(targetdata.exists())
        self.assertEqual((olddata/'fonts/personal.ttf').read_bytes(),b'font')
    def test_default_associations_filter_uninstalled_programs(self):
        relative='.config/mimeapps.list'
        self.put(self.source,relative,b'[Default Applications]\ntext/plain=old.desktop;installed.desktop;\ntext/html=missing.desktop;\n')
        plan=self.review(['defaults'],decisions={relative:'import'},installed_desktop_ids=['installed.desktop'])
        self.assertEqual(plan['status'],'ready');self.assertEqual(len(plan['filtered_associations']),2)
        migration.apply_migration(plan,self.root/'backup')
        result=(self.target/relative).read_text()
        self.assertIn('installed.desktop',result);self.assertNotIn('old.desktop',result);self.assertNotIn('missing.desktop',result)
    def test_default_terminal_not_installed_remains_unresolved(self):
        relative='.config/adws/default-terminal.json'
        self.put(self.source,relative,b'{"desktop_id":"old.desktop"}')
        plan=self.review(['defaults'],decisions={relative:'import'},installed_desktop_ids=['new.desktop'])
        self.assertEqual(plan['status'],'needs_review');self.assertFalse(plan['entries'])
    def test_defaults_require_destination_application_validation(self):
        relative='.config/mimeapps.list';self.put(self.source,relative,b'[Default Applications]\ntext/plain=ok.desktop;')
        self.assertEqual(self.review(['defaults'],decisions={relative:'import'})['status'],'needs_review')
    def test_nickname_is_preserved_unless_explicitly_selected(self):
        current={'uid':os.getuid(),'name':'Current'}
        plan=self.review(['nickname'],current_identity=current)
        self.assertEqual(plan['account_action']['policy'],'preserve')
        changed=self.review(['nickname'],current_identity=current,nickname='Selected')
        self.assertEqual(changed['account_action']['policy'],'set')
        self.assertTrue(changed['account_action']['requires_authorization'])
        self.assertFalse(changed['entries'])
    def test_nickname_backend_preserves_other_user_and_detects_stale_review(self):
        class Fake:
            name='Current'
            writes=[]
            def read(self,uid):return self.name
            def write(self,uid,name):self.writes.append((uid,name));self.name=name
        backend=Fake()
        action=personal.nickname_action('Selected',{'uid':os.getuid(),'name':'Current'})
        self.assertEqual(personal.apply_nickname(action,backend)['status'],'changed')
        self.assertEqual(backend.writes,[(os.getuid(),'Selected')])
        self.assertEqual(personal.apply_nickname(action,backend)['status'],'unchanged')
        backend.name='User changed'
        with self.assertRaises(ValueError):personal.apply_nickname(action,backend)
        with self.assertRaises(ValueError):personal.nickname_action('Other',{'uid':os.getuid()+1,'name':'Current'})
    def test_optional_nickname_rollback_preserves_later_edits(self):
        class Fake:
            name=''
            def read(self,uid):return self.name
            def write(self,uid,name):self.name=name
        backend=Fake()
        action=personal.nickname_action('Selected',{'uid':os.getuid(),'name':''})
        changed=personal.apply_nickname(action,backend)
        self.assertEqual(personal.rollback_nickname(changed,backend)['status'],'restored')
        self.assertEqual(backend.name,'')
        personal.apply_nickname(action,backend);backend.name='Edited'
        self.assertEqual(personal.rollback_nickname(changed,backend)['status'],'conflict')
        self.assertEqual(backend.name,'Edited')

    def test_gpu_session_settings_cannot_be_imported_even_by_decision(self):
        self.put(self.source,'.bashrc',b'export GBM_BACKEND=nvidia-drm\nalias ll="ls -l"\n')
        plan=self.review(['shell']);self.assertFalse(plan['entries']);self.assertTrue(plan['excluded'])
        with self.assertRaises(ValueError):self.review(['shell'],decisions={'.bashrc':'import'})
    def test_schema_one_rollback_is_still_supported(self):
        self.put(self.source,'.face',b'new')
        plan=self.review(['avatar']);migration.apply_migration(plan,self.root/'backup')
        path=self.root/'backup/migration.json';record=json.loads(path.read_text());record['schema_version']=1
        record.pop('target_roots');record['created_directories']=[];path.write_text(json.dumps(record))
        self.assertEqual(migration.rollback(self.root/'backup')['status'],'rolled_back')
        self.assertFalse((self.target/'.face').exists())
    def test_mapping_to_source_files_is_rejected(self):
        self.put(self.source,'.local/share/fonts/personal.ttf',b'font')
        plan=self.review(['fonts'],target_xdg={'data':self.source/'.local/share'})
        self.assertEqual(plan['status'],'needs_review');self.assertFalse(plan['entries'])
    def test_unknown_decisions_and_binary_preview(self):
        self.put(self.source,'.face',b'\x00\xffpng')
        with self.assertRaises(ValueError):self.review(['avatar'],decisions={'../escape':'import'})
        plan=self.review(['avatar']);self.assertEqual(personal.text_diff(plan,'.face')['kind'],'metadata')

if __name__=='__main__':unittest.main()

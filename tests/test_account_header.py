import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_account_header as header
from PIL import Image
from gi.repository import Gtk,GLib


class AccountHeaderDataTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.root=Path(self.temporary.name)
        self.cache=patch.object(header,'cache_directory',return_value=self.root)
        self.cache.start()
        self.uid=os.getuid()
        self.fallback=dict(uid=self.uid,name='Login name',username='tester',role='standard',avatar=None,groups=[])

    def tearDown(self):
        self.cache.stop();self.temporary.cleanup()

    def test_session_identity_matches_rust_format_and_socket_generation(self):
        socket=self.root/'wayland-0';socket.write_bytes(b'fixture')
        env={'XDG_RUNTIME_DIR':str(self.root),'WAYLAND_DISPLAY':'wayland-0','XDG_SESSION_ID':'session'}
        info=socket.stat();seconds,nanos=divmod(info.st_ctime_ns,1_000_000_000)
        old=header.session_key(env)
        self.assertEqual(old,f'session:{socket}:{info.st_ino}:{seconds}:{nanos}')
        replacement=self.root/'replacement';replacement.write_bytes(b'new')
        os.replace(replacement,socket)
        self.assertNotEqual(header.session_key(env),old)
        self.assertIsNone(header.session_key({}))

    def test_role_uses_account_service_before_fallback_groups(self):
        self.assertEqual(header.account_role(0,0,[]),'root')
        self.assertEqual(header.account_role(1000,1,[]),'administrator')
        self.assertEqual(header.account_role(1000,0,['wheel']),'standard')
        self.assertEqual(header.account_role(1000,None,['sudo']),'administrator')
        self.assertEqual(header.account_role(1000,None,[]),'standard')
        self.assertEqual(header.account_role(1000),'unknown')

    def test_cache_rejects_other_uid_symlinks_and_wrong_session(self):
        data=dict(self.fallback,session='one')
        path=header.cache_path('one');path.write_text(json.dumps(data))
        self.assertEqual(header.read_cache('one',self.uid)['name'],'Login name')
        self.assertIsNone(header.read_cache('one',self.uid+1))
        self.assertIsNone(header.read_cache('two',self.uid))
        symlink=self.root/'linked.json';symlink.symlink_to(path)
        self.assertIsNone(header.read_json_owned(symlink,self.uid))

    def test_rust_cache_is_matched_by_session_and_read_count_is_bounded(self):
        (self.root/'account-legacy.json').write_text(json.dumps({'session':'current','name':'Existing nickname','avatar':None}))
        self.assertEqual(header.read_menu_cache('current',self.uid)['name'],'Existing nickname')
        self.assertIsNone(header.read_menu_cache('different',self.uid))
        for number in range(50):
            (self.root/f'account-{number:02}.json').write_text('{}')
        with patch.object(header,'read_json_owned',return_value=None) as read:
            header.read_menu_cache('unmatched',self.uid)
            self.assertLessEqual(read.call_count,32)

    def test_cached_login_does_not_repeat_account_service_lookup(self):
        key='login'
        header.cache_path(key).write_text(json.dumps(dict(self.fallback,session=key)))
        with patch.object(header,'session_key',return_value=key),patch.object(header,'query_properties') as query:
            value,_=header.load_account()
        self.assertEqual(value['name'],'Login name');query.assert_not_called()

    def test_forced_refresh_ignores_old_start_menu_nickname(self):
        key='login'
        (self.root/'account-old.json').write_text(json.dumps({'session':key,'name':'Old menu nickname','avatar':None}))
        with patch.object(header,'session_key',return_value=key),patch.object(header,'fallback_account',return_value=self.fallback.copy()),patch.object(header,'query_properties',return_value={'RealName':'New nickname','Uid':self.uid,'AccountType':1}):
            value,_=header.load_account(force=True)
        self.assertEqual(value['name'],'New nickname')
        self.assertEqual(header.read_cache(key,self.uid)['name'],'New nickname')
        self.assertEqual(json.loads((self.root/'account-old.json').read_text())['name'],'Old menu nickname')

    def test_per_user_avatar_falls_back_after_missing_service_icon(self):
        image=self.root/'.face';Image.new('RGB',(120,80),'green').save(image,format='PNG')
        from types import SimpleNamespace
        user=SimpleNamespace(pw_dir=str(self.root),pw_name='fixture')
        with patch.object(header.pwd,'getpwuid',return_value=user):
            data=header.avatar_for_user(self.uid,str(self.root/'missing-service-icon'))
        self.assertIsNotNone(data)
        with Image.open(io.BytesIO(data)) as result:
            self.assertEqual(result.size,(112,112))
            self.assertEqual(result.getpixel((0,0))[3],0)
        image.unlink()
        with patch.object(header.pwd,'getpwuid',return_value=user):
            self.assertIsNone(header.avatar_for_user(self.uid,None))

    def test_avatar_is_bounded_and_round_with_transparent_corners(self):
        image=self.root/'avatar.png';Image.new('RGB',(800,600),'green').save(image)
        data=header.avatar_png(image)
        with Image.open(io.BytesIO(data)) as result:
            self.assertEqual(result.size,(112,112))
            self.assertEqual(result.getpixel((0,0))[3],0)
            self.assertEqual(result.getpixel((56,56))[3],255)
        with patch.object(header,'MAX_AVATAR_BYTES',1):
            self.assertIsNone(header.avatar_png(image))
        with patch.object(header,'MAX_AVATAR_PIXELS',100):
            self.assertIsNone(header.avatar_png(image))

    def test_avatar_source_removal_does_not_break_session_cache(self):
        image=self.root/'face.png';Image.new('RGB',(32,32),'blue').save(image)
        fallback=dict(self.fallback,avatar=str(image))
        with patch.object(header,'session_key',return_value='login'),patch.object(header,'fallback_account',return_value=fallback),patch.object(header,'query_properties',return_value={}):
            first,data=header.load_account()
            image.unlink()
            second,cached=header.load_account()
        self.assertIsNotNone(cached)
        self.assertTrue(Path(second['avatar']).is_file())
        self.assertEqual(first['name'],second['name'])

    def test_lookup_rejects_other_account_properties(self):
        from unittest.mock import MagicMock
        bus=MagicMock()
        bus.call_sync.return_value=GLib.Variant('(a{sv})',({'Uid':GLib.Variant('t',self.uid+1),'RealName':GLib.Variant('s','Wrong user')},))
        with patch.object(header.Gio,'bus_get_sync',return_value=bus):
            self.assertEqual(header.query_properties(self.uid),{})
        self.assertEqual(bus.call_sync.call_args.args[-2],1000)

    def test_display_name_removes_linebreaks_and_controls(self):
        self.assertEqual(header.display_name('A\nB\x00\t'),'AB')
        self.assertEqual(len(header.display_name('x'*1000)),512)


@unittest.skipUnless(Gtk.init_check()[0],'GTK display required')
class AccountHeaderWidgetTests(unittest.TestCase):
    def setUp(self):
        self.data={'name':'Akizuki','username':'akizuki','role':'administrator'}
        self.mock=patch.object(header,'load_account',return_value=(self.data,None));self.mock.start()
        self.clicked=[]
        self.widget=header.AccountHeader(lambda:self.clicked.append(True))
        self.window=Gtk.Window();self.window.add(self.widget);self.window.show_all()
        self.wait_until(lambda:self.widget.nickname.get_text()=='Akizuki')

    def tearDown(self):
        self.window.destroy();self.widget.executor.shutdown(wait=True)
        while Gtk.events_pending():Gtk.main_iteration_do(False)
        self.mock.stop()

    def wait_until(self,condition):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            while Gtk.events_pending():Gtk.main_iteration_do(False)
            if condition():return
            time.sleep(.01)
        self.fail('Account header did not complete its worker')

    def test_identity_fields_and_navigation_are_separate(self):
        self.assertEqual(self.widget.username.get_text(),'@akizuki')
        self.assertEqual(self.widget.role.get_text(),header.tr('管理员'))
        self.widget.clicked();self.assertEqual(self.clicked,[True])

    def test_refresh_ignores_outdated_worker_result(self):
        old_generation=self.widget.generation
        with patch.object(header,'load_account',return_value=(dict(self.data,name='Updated'),None)):
            self.widget.refresh(force=True)
            self.widget.update_account(old_generation,dict(self.data,name='Stale'),None)
            self.wait_until(lambda:self.widget.nickname.get_text()=='Updated')
        self.assertEqual(self.widget.nickname.get_text(),'Updated')

    def test_destroyed_widget_ignores_result(self):
        self.window.destroy()
        self.assertFalse(self.widget.update_account(self.widget.generation,self.data,None))


if __name__=='__main__':unittest.main()

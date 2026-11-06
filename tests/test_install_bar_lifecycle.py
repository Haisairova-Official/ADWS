"""Use disposable Python processes, never the user's Waybar or display."""
from pathlib import Path
import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_install_bar_lifecycle as lifecycle
import adws_waybar


@unittest.skipUnless(hasattr(os,'pidfd_open') and hasattr(signal,'pidfd_send_signal'),'Linux process handles required')
class TopbarLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='adws-topbar-life-')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.script=self.root/'bar-fixture.py'
        self.script.write_text('''import ctypes,json,os,signal,time
from pathlib import Path
ctypes.CDLL(None).prctl(15,b"waybar",0,0,0)
if os.environ.get("IGNORE_TERM")=="yes":signal.signal(signal.SIGTERM,signal.SIG_IGN)
record=Path(os.environ["FIXTURE_RECORD"])
record.write_text(json.dumps({"pid":os.getpid(),"cwd":os.getcwd(),"display":os.environ.get("WAYLAND_DISPLAY"),"authority":[x for x in os.environ if x.startswith("ADWS_INSTALL_")],"mask":list(signal.pthread_sigmask(signal.SIG_BLOCK,[]))}))
if os.environ.get("EXIT_EARLY")=="yes":raise SystemExit(13)
while True:time.sleep(1)
''')
        self.config=self.root/'config.jsonc';self.config.write_text('{}\n')
        self.style=self.root/'style.css';self.style.write_text('* {}\n')
        self.children=[]
        self.addCleanup(self.cleanup_children)
        self.profile={'config':str(self.config),'style':str(self.style)}

    def cleanup_children(self):
        for child in self.children:
            if child.poll() is None:child.kill()
            child.wait(timeout=3)

    def spawn(self,config=None,style=None,extra=None):
        record=self.root/('process-'+str(len(self.children))+'.json')
        env={'PATH':os.environ.get('PATH','/usr/bin'),'HOME':str(self.root),'LANG':'C.UTF-8',
             'WAYLAND_DISPLAY':'wayland-fixture','XDG_RUNTIME_DIR':str(self.root/'runtime'),
             'ADWS_INSTALL_MANAGED':'1','ADWS_INSTALL_PLAN':'/fixture-plan',
             'ADWS_NIRI_METHOD':'source','ADWS_BUILD_MIRROR':'1','FIXTURE_RECORD':str(record),**(extra or {})}
        child=subprocess.Popen(['waybar',str(self.script),'--config',str(config or self.config),'--style',str(style or self.style)],
                               executable=sys.executable,cwd=self.root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.children.append(child)
        until=time.monotonic()+3
        while not record.exists():
            if child.poll() is not None or time.monotonic()>until:self.fail('Fixture did not start')
            time.sleep(.01)
        return child,record

    def factory(self,argv,**kwargs):
        child=subprocess.Popen(argv,executable=sys.executable,**kwargs)
        self.children.append(child)
        return child

    def manager(self,**kwargs):
        manager=lifecycle.TopbarLifecycle([self.profile],self.root/'logs',popen=self.factory,startup_grace=.25,**kwargs)
        self.addCleanup(manager.close)
        return manager

    def test_no_running_profile_does_not_start_or_create_logs(self):
        manager=self.manager()
        self.assertEqual(manager.capture(),[])
        manager.stop()
        self.assertEqual(manager.start_new(),[])
        self.assertEqual(manager.restore_old(),[])
        self.assertFalse((self.root/'logs').exists())

    def test_real_stop_restart_retains_session_and_unrelated_bar(self):
        original,record=self.spawn()
        other=self.root/'other.jsonc';other.write_text('{}')
        unrelated,_=self.spawn(config=other)
        manager=self.manager()
        result=manager.capture()
        self.assertEqual([row['pid'] for row in result],[original.pid])
        self.assertNotIn('wayland-fixture',json.dumps(result))
        manager.stop();original.wait(timeout=2)
        self.assertIsNone(unrelated.poll())
        with patch.dict(os.environ,{'HOME':str(self.root)},clear=True):new=manager.start_new()
        self.assertEqual(len(new),1)
        self.assertNotEqual(new[0]['pid'],original.pid)
        state=json.loads(record.read_text())
        self.assertEqual(state['display'],'wayland-fixture')
        self.assertEqual(state['cwd'],str(self.root))
        self.assertEqual(state['authority'],[])
        self.assertEqual(state['mask'],[],'Deferred cancellation must not block signals in children')
        manager.close()
        self.assertIsNone(self.children[-1].poll(),'close must not terminate a committed bar')
        self.assertIsNone(unrelated.poll())
        self.assertFalse(any('wayland-fixture' in p.read_text() for p in (self.root/'logs').glob('*')))

    def test_rollback_stops_new_then_restores_original_once(self):
        original,_=self.spawn()
        manager=self.manager();manager.capture();manager.stop();original.wait(timeout=2)
        newer=manager.start_new()[0]['pid']
        manager.stop_new()
        self.assertIsNotNone(next(child for child in self.children if child.pid==newer).poll())
        restored=manager.restore_old()
        self.assertEqual(len(restored),1)
        self.assertNotEqual(restored[0]['pid'],newer)
        self.assertEqual(manager.restore_old(),[])
        active=[row for row in adws_waybar.processes() if row['config']==self.config]
        self.assertEqual(len(active),1)

    def test_duplicate_or_changed_stylesheet_fails_before_any_stop(self):
        original,_=self.spawn();duplicate,_=self.spawn()
        manager=self.manager()
        with self.assertRaisesRegex(RuntimeError,'Multiple Waybar'):manager.capture()
        self.assertIsNone(original.poll());self.assertIsNone(duplicate.poll())
        self.assertEqual(manager.restore_old(),[])
        duplicate.terminate();duplicate.wait(timeout=2)
        other_style=self.root/'different.css';other_style.write_text('* {}')
        profile={'config':str(self.config),'style':str(other_style)}
        changed=lifecycle.TopbarLifecycle([profile],self.root/'logs')
        self.addCleanup(changed.close)
        with self.assertRaisesRegex(RuntimeError,'different stylesheet'):changed.capture()
        self.assertIsNone(original.poll())

    def test_bottom_bar_profile_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Bottom taskbar'):
            lifecycle.TopbarLifecycle([{'config':str(self.root/'config-bottom.jsonc'),'style':str(self.style)}],self.root/'logs')

    def test_identity_change_rejects_capture_and_closes_handles(self):
        original,_=self.spawn();manager=self.manager()
        real_identity=lifecycle._identity;calls=0
        def changed(pid):
            nonlocal calls
            calls+=1
            return real_identity(pid) if calls==1 else 'changed'
        before=len(list(Path('/proc/self/fd').iterdir()))
        with patch.object(lifecycle,'_identity',side_effect=changed):
            with self.assertRaisesRegex(RuntimeError,'changed while capturing'):manager.capture()
        self.assertEqual(len(list(Path('/proc/self/fd').iterdir())),before)
        self.assertIsNone(original.poll())

    def test_stop_timeout_never_escalates_or_duplicates_original(self):
        original,_=self.spawn(extra={'IGNORE_TERM':'yes'})
        manager=self.manager(stop_timeout=.03);manager.capture()
        with patch.object(lifecycle.signal,'pidfd_send_signal',wraps=signal.pidfd_send_signal) as send:
            with self.assertRaisesRegex(RuntimeError,'did not exit normally'):manager.stop()
            self.assertEqual([call.args[1] for call in send.call_args_list],[signal.SIGTERM])
        self.assertEqual(manager.restore_old(),[])
        self.assertIsNone(original.poll())
        self.assertEqual(len(self.children),1)

    def test_interrupted_stop_recovers_only_after_original_exits(self):
        original,_=self.spawn();manager=self.manager();manager.capture()
        exited=lifecycle._exited
        def interrupted(fd,timeout=0):
            if timeout:raise KeyboardInterrupt()
            return exited(fd,timeout)
        with patch.object(lifecycle,'_exited',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):manager.stop()
        original.wait(timeout=2)
        self.assertEqual(len(manager.restore_old()),1)

    def test_cancel_at_popen_boundary_retains_child_for_rollback(self):
        original,_=self.spawn();manager=self.manager();manager.capture();manager.stop();original.wait(timeout=2)
        factory=self.factory
        def interrupted_spawn(argv,**kwargs):
            child=factory(argv,**kwargs)
            os.kill(os.getpid(),signal.SIGINT)
            return child
        manager.popen=interrupted_spawn
        with self.assertRaises(KeyboardInterrupt):manager.start_new()
        newer=self.children[-1]
        manager.stop_new()
        self.assertIsNotNone(newer.poll())
        manager.popen=factory
        self.assertEqual(len(manager.restore_old()),1)

    def test_pidfd_allocation_failure_after_popen_keeps_cleanup_handle(self):
        original,_=self.spawn();manager=self.manager();manager.capture();manager.stop();original.wait(timeout=2)
        with patch.object(lifecycle.os,'pidfd_open',side_effect=OSError('fixture descriptor limit')):
            with self.assertRaisesRegex(OSError,'descriptor limit'):manager.start_new()
        newer=self.children[-1]
        manager.stop_new();self.assertIsNotNone(newer.poll())
        self.assertEqual(len(manager.restore_old()),1)

    def test_start_requires_completed_stop_and_handles_close_after_recovery(self):
        original,_=self.spawn();manager=self.manager()
        before=len(list(Path('/proc/self/fd').iterdir()))
        manager.capture()
        with self.assertRaisesRegex(RuntimeError,'stop has not completed'):manager.start_new()
        self.assertIsNone(original.poll())
        manager.stop();original.wait(timeout=2);manager.start_new();manager.stop_new();manager.restore_old()
        manager.close();manager.close()
        self.assertEqual(len(list(Path('/proc/self/fd').iterdir())),before)

    def test_immediate_launch_failure_does_not_restore_over_live_replacement(self):
        original,_=self.spawn();manager=self.manager();manager.capture();manager.stop();original.wait(timeout=2)
        manager.rows[0]['env']['EXIT_EARLY']='yes'
        with self.assertRaisesRegex(RuntimeError,'exited while restarting'):manager.start_new()
        manager.stop_new()
        manager.rows[0]['env'].pop('EXIT_EARLY')
        self.assertEqual(len(manager.restore_old()),1)

    def test_external_restart_is_not_killed_or_duplicated(self):
        original,_=self.spawn();manager=self.manager();manager.capture();manager.stop();original.wait(timeout=2)
        external,_=self.spawn()
        with self.assertRaisesRegex(RuntimeError,'refusing to start a duplicate'):manager.start_new()
        manager.stop_new()
        with self.assertRaisesRegex(RuntimeError,'refusing to start a duplicate'):manager.restore_old()
        self.assertIsNone(external.poll())

    def test_failed_restore_does_not_skip_other_profile(self):
        original,_=self.spawn()
        config=self.root/'second.jsonc';config.write_text('{}')
        other,_=self.spawn(config=config)
        manager=lifecycle.TopbarLifecycle([self.profile,{'config':str(config),'style':str(self.style)}],
            self.root/'logs',popen=self.factory,startup_grace=.25)
        self.addCleanup(manager.close)
        manager.capture();manager.stop();original.wait(timeout=2);other.wait(timeout=2)
        def fail_one(argv,**kwargs):
            if str(self.config) in argv:raise OSError('fixture first launcher unavailable')
            return self.factory(argv,**kwargs)
        manager.popen=fail_one
        with self.assertRaisesRegex(RuntimeError,'recovery incomplete.*first launcher unavailable'):manager.restore_old()
        active=[row for row in adws_waybar.processes() if row['config'] in (self.config,config)]
        self.assertEqual([row['config'] for row in active],[config])
        self.assertFalse(manager.rows[0]['restored'])
        self.assertTrue(manager.rows[1]['restored'])


if __name__=='__main__':unittest.main()

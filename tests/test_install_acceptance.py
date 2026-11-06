import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_install_acceptance as acceptance

LIVE = {'WAYLAND_DISPLAY':'wayland-test', 'XDG_RUNTIME_DIR':'/tmp/adws-test', 'NIRI_SOCKET':'/tmp/niri.sock'}

class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        probe=patch.object(acceptance,'probe_text_fonts',return_value={'status':'ready','missing':{'zh':'','ja':'','ko':''}})
        probe.start();self.addCleanup(probe.stop)

    def run_ok(self, argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, '[]', '')

    def test_headless_is_pending_even_with_confirmations(self):
        with patch.object(acceptance.time,'sleep') as sleep:
            report = acceptance.evaluate(environ={}, confirmations=['preview','clipboard','launch','screenshot'])
            sleep.assert_not_called()
        self.assertFalse(report['complete'])
        self.assertEqual(report['pending'], [key for key in acceptance.CHECKS if key!='text-fonts'])
        self.assertFalse(report['failed'])
        self.assertEqual(report['checks'][-1]['status'],'passed')

    def test_missing_text_fonts_fail_even_in_english_headless_session(self):
        with patch.object(acceptance,'probe_text_fonts',return_value={'status':'missing','missing':{'zh':'中','ja':'ひ','ko':'한'}}):
            report=acceptance.evaluate(environ={'LANG':'en_US.UTF-8'})
        self.assertEqual(report['failed'],['text-fonts']);self.assertFalse(report['complete'])
        self.assertEqual(report['checks'][-1]['kind'],'glyph-coverage')

    def test_font_acceptance_needs_no_session_or_user_attestation(self):
        run=unittest.mock.Mock(side_effect=AssertionError('Font-only check must not touch Niri'))
        report=acceptance.evaluate(['text-fonts'],run=run,environ=LIVE)
        self.assertTrue(report['complete']);run.assert_not_called()

    def test_runtime_taskbar_and_exercise_are_distinct_from_dependencies(self):
        with patch.object(acceptance,'_bottom_bar_states',return_value=[{'pid':123,'loaded':True}]):
            report = acceptance.evaluate(run=self.run_ok,environ=LIVE)
        self.assertEqual(report['checks'][0]['status'],'passed')
        self.assertEqual(report['pending'],['preview','screenshot','clipboard','launch'])
        self.assertFalse(report['complete'])

    def test_duplicate_or_missing_bar_fails(self):
        for pids in ([], [3,4]):
            with patch.object(acceptance,'_bottom_bar_states',return_value=[{'pid':p,'loaded':True} for p in pids]), patch.object(acceptance.time,'sleep') as sleep:
                report=acceptance.evaluate(['taskbar'],run=self.run_ok,environ=LIVE)
                sleep.assert_not_called()
            self.assertEqual(report['failed'],['taskbar'])

    def test_broken_ipc_cannot_pass_from_user_confirmation(self):
        run=lambda argv,**kwargs:subprocess.CompletedProcess(argv,1,'','unavailable')
        report=acceptance.evaluate(['preview'],confirmations=['preview'],run=run,environ=LIVE)
        self.assertEqual(report['failed'],['preview'])

    def test_actual_capture_is_decoded_and_deleted(self):
        from PIL import Image
        seen=[]
        def run(argv, **kwargs):
            if argv[0]=='grim':
                target=Path(argv[1]);seen.append(target)
                Image.new('RGB',(8,8),(22,42,62)).save(target)
                return subprocess.CompletedProcess(argv,0,'','')
            return self.run_ok(argv,**kwargs)
        report=acceptance.evaluate(['screenshot'],exercise=['screenshot'],run=run,environ=LIVE)
        self.assertTrue(report['complete'])
        self.assertEqual(report['checks'][0]['kind'],'exercise')
        self.assertFalse(seen[0].exists())

    def test_truncated_capture_is_failure_not_success(self):
        def run(argv, **kwargs):
            if argv[0]=='grim':
                Path(argv[1]).write_bytes(b'\x89PNG\r\n\x1a\n')
                return subprocess.CompletedProcess(argv,0,'','')
            return self.run_ok(argv,**kwargs)
        report=acceptance.evaluate(['screenshot'],exercise=['screenshot'],run=run,environ=LIVE)
        self.assertEqual(report['failed'],['screenshot'])

    def test_manual_attestation_identified_as_manual(self):
        report=acceptance.evaluate(['preview','clipboard','launch'],confirmations=['preview','clipboard','launch'],run=self.run_ok,environ=LIVE)
        self.assertTrue(report['complete'])
        self.assertTrue(all(row['kind']=='user-confirmed' for row in report['checks']))
        with self.assertRaises(ValueError):acceptance.evaluate(['made-up'])
        with self.assertRaises(ValueError):acceptance.evaluate(exercise=['clipboard'])

    def test_proc_check_ignores_unrelated_bar_and_missing_library(self):
        with tempfile.TemporaryDirectory() as folder:
            proc=Path(folder)
            for pid,config,maps in [('1','config-top.jsonc','libniri_taskbar.so'),('2','config-bottom.jsonc',''),('3','config-bottom.jsonc','/lib/libniri_taskbar.so')]:
                p=proc/pid;p.mkdir()
                (p/'cmdline').write_bytes(b'waybar\0-c\0'+config.encode()+b'\0')
                (p/'maps').write_text(maps)
            self.assertEqual(acceptance._bottom_taskbars(proc),[3])

    def taskbar_fixture(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        proc=Path(temp.name);self.create_bar(proc,123)
        return proc

    def create_bar(self,proc,pid,loaded=False):
        path=proc/str(pid);path.mkdir()
        (path/'cmdline').write_bytes(b'/usr/bin/waybar\0--config=config-bottom.jsonc\0')
        self.set_loaded(path,loaded)
        return path

    def set_loaded(self,path,loaded):
        (path/'maps').write_text('70000000-70001000 r-xp 00000000 08:01 123 /lib/'+
                                ('libniri_taskbar.so' if loaded else 'libgtk-3.so.0')+'\n')

    def readiness(self,proc,on_sleep=None):
        now=[0.0];waits=[]
        def sleep(seconds):
            self.assertGreater(seconds,0)
            self.assertLessEqual(seconds,.1)
            waits.append(seconds);now[0]+=seconds
            if on_sleep:on_sleep(len(waits))
        report=acceptance.evaluate(['taskbar'],run=self.run_ok,environ=LIVE,proc=proc,
                                   clock=lambda:now[0],sleep=sleep)
        return report['checks'][0],waits

    def test_started_bar_waits_for_real_module_mapping(self):
        proc=self.taskbar_fixture()
        def update(at):
            if at == 3:self.set_loaded(proc/'123',True)
        row,waits=self.readiness(proc,update)
        self.assertEqual(row['status'],'passed')
        self.assertEqual(row['runtime_state'],'ready')
        self.assertEqual(len(waits),3)
        self.assertEqual(row['waited_ms'],300)

    def test_started_bar_has_bounded_wait_not_existence_success(self):
        proc=self.taskbar_fixture()
        row,waits=self.readiness(proc)
        self.assertEqual(row['status'],'failed')
        self.assertEqual(row['runtime_state'],'loading-timeout')
        self.assertAlmostEqual(sum(waits),5.0)
        self.assertEqual(row['waited_ms'],5000)

    def test_exit_during_loading_fails_without_waiting_full_timeout(self):
        proc=self.taskbar_fixture()
        row,waits=self.readiness(proc,lambda _:shutil.rmtree(proc/'123'))
        self.assertEqual(row['runtime_state'],'exited')
        self.assertEqual(row['status'],'failed')
        self.assertEqual(len(waits),1)

    def test_duplicate_during_loading_fails_even_if_one_bar_loaded(self):
        proc=self.taskbar_fixture()
        row,waits=self.readiness(proc,lambda _:self.create_bar(proc,456,True))
        self.assertEqual(row['runtime_state'],'duplicate')
        self.assertEqual(row['status'],'failed')
        self.assertEqual(set(row['pids']),{123,456})
        self.assertEqual(len(waits),1)

    def test_process_replacement_is_reported_instead_of_hiding_restart(self):
        proc=self.taskbar_fixture()
        def replace(_):
            shutil.rmtree(proc/'123');self.create_bar(proc,456,True)
        row,waits=self.readiness(proc,replace)
        self.assertEqual(row['runtime_state'],'restarted')
        self.assertEqual(row['status'],'failed')
        self.assertEqual(len(waits),1)

    def test_unreadable_mapping_is_not_ready(self):
        proc=self.taskbar_fixture();(proc/'123/maps').unlink()
        row,waits=self.readiness(proc)
        self.assertEqual(row['runtime_state'],'unreadable')
        self.assertFalse(waits)

    def test_similarly_named_library_is_not_accepted(self):
        proc=self.taskbar_fixture()
        (proc/'123/maps').write_text('/lib/libniri_taskbar.so.backup\n')
        self.assertEqual(acceptance._bottom_taskbars(proc),[])

if __name__=='__main__':unittest.main()

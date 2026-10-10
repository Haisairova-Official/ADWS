import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_plugin_watchdog as watchdog


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{'XDG_RUNTIME_DIR':self.temp.name});self.env.start();self.addCleanup(self.env.stop)
        self.notifications=patch.object(watchdog,'notify');self.notice=self.notifications.start();self.addCleanup(self.notifications.stop)

    def run_worker(self,code,instance='one'):
        return watchdog.monitor([sys.executable,'-c',code],instance,'Test',grace=.15,limit=.2)

    def test_crash_is_instance_scoped_and_notification_is_debounced(self):
        self.assertEqual(self.run_worker('raise SystemExit(7)'),1)
        self.assertEqual(watchdog.health('one')['state'],'failed')
        self.assertIsNone(watchdog.health('other'))
        self.assertEqual(self.run_worker('raise SystemExit(7)'),1)
        self.notice.assert_called_once()
        self.assertEqual(self.run_worker('pass'),0)
        self.assertEqual(watchdog.health('one')['state'],'completed')

    def test_missing_interpreter_heartbeat_is_detected(self):
        self.assertEqual(self.run_worker('import time;time.sleep(30)'),1)
        self.assertEqual(watchdog.health('one')['state'],'failed')
        self.assertIn('respond',watchdog.health('one')['reason'].lower())
        self.notice.assert_called_once()
        self.assertEqual(list(watchdog.folder().glob('.*.beat')),[])

    def test_stopped_worker_is_detected_separately_from_plugin_output(self):
        tools=str(Path(__file__).resolve().parents[1]/'tools')
        code=f"import sys,os,signal,time\nsys.path.insert(0,{tools!r})\nfrom adws_plugin_watchdog import pulse\npulse(os.getpid())\nos.kill(os.getpid(),signal.SIGSTOP)\ntime.sleep(30)"
        self.assertEqual(self.run_worker(code),1)
        self.assertEqual(watchdog.health('one')['state'],'failed')
        self.notice.assert_called_once()

    def test_quiet_legacy_output_is_not_a_watchdog_failure(self):
        tools=str(Path(__file__).resolve().parents[1]/'tools')
        code=f"import sys,os,time\nsys.path.insert(0,{tools!r})\nfrom adws_plugin_watchdog import pulse\nfor _ in range(8):\n pulse(os.getpid())\n time.sleep(.08)"
        self.assertEqual(self.run_worker(code),0)
        self.assertEqual(watchdog.health('one')['state'],'completed')
        self.notice.assert_not_called()

    def test_normal_stop_does_not_warn(self):
        code='import os,signal,time\ntime.sleep(.05)\nos.kill(os.getppid(),signal.SIGTERM)\ntime.sleep(30)'
        self.assertEqual(self.run_worker(code),0)
        self.assertEqual(watchdog.health('one')['state'],'stopped')
        self.notice.assert_not_called()

    def test_missing_executable_is_reported(self):
        self.assertEqual(watchdog.monitor(['/nonexistent-adws-fixture'],'one','Test'),1)
        self.assertEqual(watchdog.health('one')['state'],'failed')

    def test_old_boot_and_invalid_status_are_ignored(self):
        record={'instance':'one','boot':'old-boot','state':'failed'}
        watchdog.store(record);self.assertIsNone(watchdog.health('one'))
        record.update(boot=watchdog.boot_id(),state='invalid');watchdog.store(record)
        self.assertIsNone(watchdog.health('one'))

if __name__=='__main__':unittest.main()

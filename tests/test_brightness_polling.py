"""No hardware access from idle indicators; active DDC work is shared/serialized."""
import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import adws_quick_backend as backend
import adws_quick_controls as controls

ITEM = dict(name='DP-1', description='Fixture', provider='ddc', value=55,
            temperature=6500, night=False, color_provider=None)


class BrightnessPolling(unittest.TestCase):
    def test_idle_status_never_probes_even_without_fresh_cache(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(backend, 'cache_root', return_value=Path(folder)), \
                patch.object(backend, '_read_brightness') as read, \
                patch.object(backend, 'command') as command:
            self.assertEqual(controls.status('brightness')['state'], 'unread')
            for age in (0, 601, 86401):
                backend.write_json(Path(folder)/'brightness-snapshot.json',
                                   {'time': time.time()-age, 'items': [ITEM]})
                for _ in range(4):
                    result = controls.status('brightness')
                self.assertEqual(result.get('state') == 'unread', age > 86400)
            read.assert_not_called()
            command.assert_not_called()

    def test_active_readers_across_processes_share_one_snapshot(self):
        context = multiprocessing.get_context('fork')
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(backend, 'cache_root', return_value=Path(folder)):
            calls = Path(folder)/'reads'
            def read(force=False):
                with calls.open('a') as stream: stream.write('read\n')
                time.sleep(.15)
                backend.write_json(Path(folder)/'brightness-snapshot.json',
                                   {'time': time.time(), 'items': [ITEM]})
                return [ITEM]
            with patch.object(backend, '_read_brightness', side_effect=read):
                processes = [context.Process(target=backend.brightness) for _ in range(4)]
                for process in processes: process.start()
                for process in processes:
                    process.join(5)
                    self.assertEqual(process.exitcode, 0)
            self.assertEqual(calls.read_text().splitlines(), ['read'])

    def test_ddc_reads_and_writes_never_overlap_across_processes(self):
        context = multiprocessing.get_context('fork')
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(backend, 'cache_root', return_value=Path(folder)):
            events = Path(folder)/'events'
            def command(args, timeout):
                with events.open('a') as stream: stream.write('start\n')
                time.sleep(.05)
                with events.open('a') as stream: stream.write('end\n')
                return ''
            with patch.object(backend, 'command', side_effect=command):
                processes = [context.Process(target=backend.ddc_command,
                                             args=([operation, '10'], 4))
                             for operation in ('getvcp', 'getvcp', 'setvcp', 'detect')]
                for process in processes: process.start()
                for process in processes:
                    process.join(5)
                    self.assertEqual(process.exitcode, 0)
            self.assertEqual(events.read_text().splitlines(), ['start', 'end']*4)

    def test_failed_discovery_backs_off(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(backend, 'cache_root', return_value=Path(folder)), \
                patch.object(backend.shutil, 'which', return_value='/usr/bin/ddcutil'), \
                patch.object(backend, 'ddc_command', side_effect=RuntimeError('timeout')) as read:
            for _ in range(3): self.assertEqual(backend.ddc_devices(), {})
            self.assertEqual(read.call_count, 1)

    def test_older_ddcutil_falls_back_without_optimization_flags(self):
        with patch.object(backend,'ddc_command',side_effect=[RuntimeError('Unknown option --skip-ddc-checks'),'ok']) as call:
            self.assertEqual(backend.ddc_brightness_command({'bus':4},'setvcp',70),'ok')
            self.assertEqual(call.call_args.args[0],['--bus','4','--noverify','setvcp','10','70'])
        with patch.object(backend,'ddc_command',side_effect=RuntimeError('Display disconnected')) as call:
            with self.assertRaisesRegex(RuntimeError,'disconnected'):
                backend.ddc_brightness_command({'bus':4},'setvcp',70)
            self.assertEqual(call.call_count,1)


if __name__ == '__main__': unittest.main()

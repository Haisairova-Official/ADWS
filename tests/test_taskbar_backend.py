"""Production host selection, config validation and per-session ownership."""
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import adws_native_taskbar
import adws_runtime
import adws_taskbar_backend as backend


class ProductionBackend(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        config_dir = self.root / 'config'
        self.waybar = config_dir / 'waybar'
        self.waybar.mkdir(parents=True)
        self.config = self.waybar / 'config-bottom.jsonc'
        self.style = self.waybar / 'style-bottom.css'
        self.config.write_text('{"modules-right":["clock"],"include":"modules.jsonc"}')
        (self.waybar / 'modules.jsonc').write_text('{"clock":{"format":"first"}}')
        self.style.write_text('window#waybar {color: white;}')
        env = patch.dict(os.environ, {'XDG_CONFIG_HOME': str(config_dir), 'XDG_RUNTIME_DIR': str(self.root/'runtime'),
                                      'WAYLAND_DISPLAY': 'wayland-test', 'ADWS_TASKBAR_PREVIEW': '0'})
        env.start()
        self.addCleanup(env.stop)
        self.executable = self.root/'adws-taskbar'
        self.executable.write_text('#!/usr/bin/env python3\nimport json,sys\n'
                                   'd=json.load(open(sys.argv[sys.argv.index("--config")+1]))\n'
                                   'sys.exit("bad module" if "bad" in d.get("modules-right",[]) else 0)\n')
        self.executable.chmod(0o700)
        choose = patch.object(adws_native_taskbar, 'choose_binary', return_value=self.executable)
        choose.start()
        self.addCleanup(choose.stop)

    def select(self, value):
        with patch.object(sys, 'argv', ['adws_taskbar_backend.py', value]):
            backend.main()

    def test_selection_and_failed_replacement(self):
        self.assertEqual(backend.selected_backend(), 'waybar')
        self.select('rust')
        self.assertEqual(backend.selected_backend(), 'rust')
        live = backend.live_config_file()
        self.assertEqual(json.loads(live.read_text())['clock']['format'], 'first')
        (self.waybar/'modules.jsonc').write_text('{"clock":{"format":"updated"}}')
        args = backend.native_command(self.config, self.style)
        self.assertEqual(args, [str(self.executable), '--config', str(live), '--style', str(self.style)])
        saved = live.read_bytes()
        self.assertEqual(json.loads(saved)['clock']['format'], 'updated')
        self.config.write_text('{"modules-right":["bad"]}')
        self.select('waybar')
        with self.assertRaisesRegex(ValueError, 'bad module'):
            self.select('rust')
        self.assertEqual(backend.selected_backend(), 'waybar')
        self.assertEqual(live.read_bytes(), saved)

    def test_process_identity_excludes_previews_checks_and_other_sessions(self):
        args = backend.native_command(self.config, self.style)
        self.assertTrue(adws_runtime.matches('taskbar', args))
        self.assertFalse(adws_runtime.matches('taskbar', args + ['--check']))
        preview = [args[0], '--config', str(self.root / 'adws-taskbar-preview-random/bar.json')]
        self.assertFalse(adws_runtime.matches('taskbar', preview))
        with patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-other'}):
            self.assertFalse(adws_runtime.matches('taskbar', args))

    def test_reload_reads_current_applied_file_and_addresses_exact_process(self):
        self.select('rust')
        handles = os.pipe()
        self.addCleanup(os.close, handles[1])
        (self.waybar/'modules.jsonc').write_text('{"clock":{"format":"reloaded"}}')
        old_handler = signal.signal(signal.SIGUSR2, lambda *_: None)
        self.addCleanup(signal.signal, signal.SIGUSR2, old_handler)
        with patch.object(backend, 'running_native_pids', return_value=[os.getpid()]), \
             patch.object(os, 'pidfd_open', return_value=handles[0]), \
             patch.object(backend, 'process_is_native', return_value=True), \
             patch.object(signal, 'pidfd_send_signal') as send:
            self.assertTrue(backend.reload_live(self.config, self.style)[0])
            send.assert_called_once_with(handles[0], signal.SIGUSR2)
        self.assertEqual(json.loads(backend.live_config_file().read_text())['clock']['format'], 'reloaded')

    def test_native_start_uses_current_config_and_real_user_paths(self):
        self.select('rust')
        with patch.object(adws_runtime, 'pids', return_value=[]), \
             patch.object(adws_runtime.subprocess, 'Popen') as spawn, \
             patch.object(adws_runtime.time, 'sleep'), \
             patch.object(adws_runtime, 'taskbar_environment', return_value=dict(os.environ)), \
             patch('adws_health.state_home', return_value=self.root/'state'), \
             patch.object(backend, 'native_command', return_value=['sleep','1']), \
             patch('adws_health.waybar_capability_errors', side_effect=AssertionError("Waybar executed")):
            spawn.return_value.poll.return_value = None
            self.assertTrue(adws_runtime.start_taskbar(self.config, self.style)[0])
            args, opts = spawn.call_args
            self.assertEqual(args[0], ['sleep','1'])
            self.assertEqual(opts['env']['ADWS_TASKBAR_MANAGED'], '1')
            self.assertEqual(opts['env']['XDG_CONFIG_HOME'], str(self.root/'config'))


if __name__ == '__main__':
    unittest.main()

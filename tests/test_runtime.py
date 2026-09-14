import sys
from pathlib import Path
import signal
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import mnws_runtime as runtime
from mnws_i18n import tr as _tr


class RuntimeTests(unittest.TestCase):
    def test_only_component_processes_match(self):
        self.assertTrue(runtime.matches('taskbar', ['waybar', '-c', '/a/config-bottom.jsonc']))
        self.assertTrue(runtime.matches('taskbar', ['/usr/bin/waybar', '--config=/a/config-bottom.jsonc']))
        self.assertFalse(runtime.matches('taskbar', ['waybar', '-c', '/a/config-top.jsonc']))
        self.assertFalse(runtime.matches('taskbar', ['sh', '-c', 'waybar -c config-bottom.jsonc']))
        self.assertTrue(runtime.matches('desktop', ['python3', '/a/desktop-layer']))
        self.assertFalse(runtime.matches('desktop', ['python3', '/a/desktop-layer', '--preview']))
        self.assertFalse(runtime.matches('desktop', ['python3', '/a/start-desktop-layer']))

    def test_stop_and_kill_aliases(self):
        for component in ('desktop', 'taskbar'):
            for flag, sig in (('--stop', signal.SIGTERM), ('-S', signal.SIGTERM),
                              ('--kill', signal.SIGKILL), ('-k', signal.SIGKILL)):
                with self.subTest(component=component, flag=flag), patch.object(runtime, 'pids', side_effect=[[123], []]), patch.object(runtime.os, 'kill') as kill:
                    self.assertEqual(runtime.main([component, flag]), 0)
                    kill.assert_called_once_with(123, sig)

    def test_running_start_does_not_duplicate(self):
        for component in ('desktop', 'taskbar'):
            for flag in ('--start', '-s'):
                with patch.object(runtime, 'pids', return_value=[123]), patch.object(runtime.subprocess, 'Popen') as spawn, patch.object(runtime.subprocess, 'call') as call:
                    self.assertEqual(runtime.main([component, flag]), 0)
                    spawn.assert_not_called()
                    call.assert_not_called()

    def test_debug_runs_in_foreground_with_logs(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            folder = home / '.config/waybar'
            folder.mkdir(parents=True)
            for name in ('config-bottom.jsonc', 'style-bottom.css'):
                (folder / name).touch()
            for component in ('desktop', 'taskbar'):
                for flag in ('--debug', '-d'):
                    with patch.object(runtime, 'pids', side_effect=[[123], [123], []]), patch.object(runtime.os, 'kill') as kill, patch.object(runtime.os, 'execvpe') as execute, patch.object(runtime.Path, 'home', return_value=home):
                        self.assertEqual(runtime.main([component, flag]), 0)
                        kill.assert_called_once_with(123, signal.SIGTERM)
                        program, command, env = execute.call_args.args
                        if component == 'desktop':
                            self.assertIn('--debug', command)
                            self.assertIn('--state', command)
                        else:
                            self.assertEqual(command[-2:], ['-l', 'info'])
                            self.assertEqual(env['RUST_LOG'], 'info')
                            self.assertNotIn('MNWS_PANEL_DEBUG', env)
                        self.assertNotIn('GDK_BACKEND', env)

    def test_status_and_restart(self):
        for targets, code in (([], 1), ([123], 0)):
            with patch.object(runtime, 'pids', return_value=targets):
                self.assertEqual(runtime.main(['desktop', '--status']), code)
        with patch.object(runtime, 'pids', side_effect=[[123], [123], [], []]), patch.object(runtime.os, 'kill') as kill, patch.object(runtime.subprocess, 'call', return_value=0) as start:
            self.assertEqual(runtime.main(['desktop', '-r']), 0)
            kill.assert_called_once_with(123, signal.SIGTERM)
            start.assert_called_once()

    def test_all_six_log_levels(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            folder = home / '.config/waybar'
            folder.mkdir(parents=True)
            for name in ('config-bottom.jsonc', 'style-bottom.css'):
                (folder / name).touch()
            for component in ('desktop', 'taskbar'):
                for level in range(1, 7):
                    with self.subTest(component=component, level=level), patch.object(runtime, 'pids', return_value=[]), patch.object(runtime.os, 'execvpe') as execute, patch.object(runtime.Path, 'home', return_value=home):
                        self.assertEqual(runtime.main([component, '-d', f'-{level}']), 0)
                        program, command, env = execute.call_args.args
                        self.assertEqual(env['MNWS_LOG_LEVEL'], str(level))
                        if component == 'desktop':
                            self.assertEqual(command[command.index('--log-level') + 1], str(level))
                        else:
                            self.assertEqual(command[-1], ('critical', 'error', 'warning', 'info', 'debug', 'trace')[level - 1])
                            self.assertEqual(env['RUST_LOG'], ('off', 'error', 'warn', 'info', 'debug', 'trace')[level - 1])
                            self.assertEqual('MNWS_PANEL_DEBUG' in env, level >= 5)

    def test_log_level_requires_debug_and_rejects_conflicts(self):
        for args in (['desktop', '-s', '-6'], ['taskbar', '-d', '-1', '-6']):
            with patch.object(runtime, 'pids') as find, self.assertRaises(SystemExit) as caught:
                runtime.main(args)
            self.assertEqual(caught.exception.code, 2)
            find.assert_not_called()

    def test_start_is_silent_and_errors_are_visible(self):
        import io
        from contextlib import redirect_stdout, redirect_stderr
        for targets in ([123], []):
            output = io.StringIO()
            with patch.object(runtime, 'pids', return_value=targets), patch.object(runtime.subprocess, 'call', return_value=0) as start, redirect_stdout(output):
                self.assertEqual(runtime.main(['desktop', '-s']), 0)
            self.assertEqual(output.getvalue(), '')
            if not targets:
                self.assertEqual(start.call_args.kwargs['stdout'], runtime.subprocess.DEVNULL)
                self.assertNotIn('stderr', start.call_args.kwargs)
        error = io.StringIO()
        with patch.object(runtime, 'pids', return_value=[]), patch.object(runtime.Path, 'is_file', return_value=False), redirect_stderr(error), self.assertRaises(SystemExit) as caught:
            runtime.main(['taskbar', '-s'])
        self.assertEqual(caught.exception.code, 1)
        self.assertIn(_tr('缺少任务栏配置，请先运行 mnws install。\n'), error.getvalue())

    def test_help_aliases_do_not_touch_processes(self):
        import io
        from contextlib import redirect_stdout
        for prefix in ([], ['desktop'], ['taskbar']):
            results = []
            for flag in ('-h', '--help', '-?'):
                output = io.StringIO()
                with patch.object(runtime, 'pids') as find, redirect_stdout(output), self.assertRaises(SystemExit) as caught:
                    runtime.main(prefix + [flag])
                self.assertEqual(caught.exception.code, 0)
                find.assert_not_called()
                results.append(output.getvalue())
            self.assertEqual(len(set(results)), 1)
            self.assertIn(_tr('示例：'), results[0])

    def test_global_status_reports_both_components(self):
        import io
        from contextlib import redirect_stdout
        for states, expected in (([[123], [456]], 0), ([[123], []], 1), ([[], []], 1)):
            output = io.StringIO()
            with patch.object(runtime, 'pids', side_effect=states) as find, redirect_stdout(output):
                self.assertEqual(runtime.main(['--status']), expected)
            self.assertEqual([c.args[0] for c in find.call_args_list], ['desktop', 'taskbar'])
            self.assertIn('desktop:', output.getvalue())
            self.assertIn('taskbar:', output.getvalue())

"""Real subprocess checks; build src/adws-runtime in release mode first."""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import adws_plugin as plugin

BINARY = ROOT / 'src/adws-runtime/target/release/adws-plugin-runner'


@unittest.skipUnless(BINARY.is_file(), 'Build the Rust supervisor before running native integration checks')
class NativeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='adws native runner ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'; self.source.mkdir()
        self.manifest = {'id': 'org.Example.Native', 'version': '1.0.0', 'name': 'Native test',
                         'entry': 'main.py', 'renderer': 'panel.text-v1'}

    def start(self, code, backend='rust', manifest=None, timeout=.2, cli=False):
        (self.source / 'plugin.json').write_text(json.dumps(manifest or self.manifest))
        (self.source / 'main.py').write_text(code)
        archive = plugin.build_package(self.source)
        command = ([sys.executable, str(ROOT / 'tools/adws_plugin.py'), 'run'] if cli else
                   [sys.executable, str(ROOT / 'tools/adws_plugin_runner.py')])
        command += [str(archive), '--timeout', str(timeout)]
        env = {**os.environ, 'ADWS_PLUGIN_RUNNER': backend, 'ADWS_CACHE_DIR': str(self.root / 'cache'),
               'LC_ALL': 'C.UTF-8', 'LANGUAGE': ''}
        if backend is None: env.pop('ADWS_PLUGIN_RUNNER', None)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        def cleanup():
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=3)
            process.stdout.close(); process.stderr.close()
        self.addCleanup(cleanup)
        return process

    def result(self, *args, **kwargs):
        process = self.start(*args, **kwargs)
        out, error = process.communicate(timeout=4)
        # Plugin tracebacks are useful diagnostics; the supervisor must not crash.
        self.assertFalse(any(line.startswith(b'Traceback') for line in error.splitlines()), error)
        self.assertNotIn(b'panicked', error)
        return process.returncode, [json.loads(line) for line in out.splitlines()]

    def ready(self, process):
        self.assertTrue(select.select([process.stdout], [], [], 3)[0], 'No initial output')
        return json.loads(process.stdout.readline())

    def tracked_code(self, tail):
        pid = self.root / 'plugin.pid'
        return ('import os,time\nfrom pathlib import Path\n'
                f'Path({str(pid)!r}).write_text(str(os.getpid()))\n'
                'print(\'{"text":"ready"}\',flush=True)\n' + tail), pid

    def assert_reaped(self, pid):
        with self.assertRaises(ProcessLookupError): os.kill(int(pid.read_text()), 0)

    def test_python_rust_output_contract(self):
        cases = [
            'print(\'{"text":"hello 世界","class":["a","b"],"percentage":50}\')',
            'import sys;sys.stderr.write("diagnostic\\n");sys.stdout.write(\'{"text":"no newline"}\')',
            'print("not JSON")', 'print("[]")', 'print(\'{"text":7}\')',
            'print(\'{"text":"x","percentage":true}\')',
            'print(\'{"text":"x","percentage":\'+"9"*1000+"}")',
            'print("x"*(1024*1024+1))', 'raise RuntimeError("failure")',
            'import time;time.sleep(2)', '',
        ]
        for code in cases:
            with self.subTest(code=code[:80]):
                self.assertEqual(self.result(code, 'rust'), self.result(code, 'python'))

    def test_rows_settings_and_literal_arguments(self):
        manifest = {**self.manifest, 'renderer': 'panel.rows-v1',
                    'settingsSchema': [{'key': 'text', 'type': 'string', 'default': '文字 $(literal)'}]}
        code = ('import json,sys\nvalues=json.loads(sys.argv[sys.argv.index("--settings-json")+1])\n'
                'print(json.dumps({"primary":values["text"],"secondary":"translation"}))')
        self.assertEqual(self.result(code, manifest=manifest),
                         (0, [{'primary': '文字 $(literal)', 'secondary': 'translation'}]))

    def test_legacy_pause_and_closed_stream_exit(self):
        manifest = {**self.manifest, 'api':'adws-plugin', 'apiVersion':1, 'kind':'panel',
                    'language':'python', 'interfaces':['panel.json-v1']}
        del manifest['renderer']
        code = ('import time,sys; assert "--output-json" in sys.argv; '
                'print(\'{"text":"paused"}\',flush=True);time.sleep(.3);print(\'{"text":"resumed"}\')')
        self.assertEqual(self.result(code, manifest=manifest, timeout=.1)[0], 0)
        code = 'import os,time;print(\'{"text":"done"}\',flush=True);os.close(1);os.close(2);time.sleep(10)'
        start = time.monotonic()
        result = self.result(code, manifest=manifest, timeout=.1)
        self.assertEqual(result[0], 1); self.assertEqual(result[1][-1]['class'], 'error')
        self.assertLess(time.monotonic() - start, 2)

    def test_exec_replaces_python_and_cli_uses_native(self):
        for cli in (False, True):
            with self.subTest(cli=cli):
                code, pid = self.tracked_code('time.sleep(10)')
                process = self.start(code, timeout=10, cli=cli)
                self.assertEqual(self.ready(process)['text'], 'ready')
                self.assertEqual(Path(f'/proc/{process.pid}/exe').resolve(), BINARY.resolve())
                process.terminate(); self.assertEqual(process.wait(timeout=2), 0)
                self.assert_reaped(pid)

    def test_default_backend_uses_rust(self):
        code, pid = self.tracked_code('time.sleep(10)')
        process = self.start(code, backend=None, timeout=10)
        self.ready(process)
        self.assertEqual(Path(f'/proc/{process.pid}/exe').resolve(), BINARY.resolve())
        process.terminate(); self.assertEqual(process.wait(timeout=2), 0)
        self.assert_reaped(pid)

    def test_python_fallback_sigterm_is_prompt_and_reaps(self):
        code, pid = self.tracked_code('time.sleep(10)')
        process = self.start(code, backend='python', timeout=10)
        self.ready(process)
        process.terminate(); self.assertEqual(process.wait(timeout=2), 0)
        self.assert_reaped(pid)
        self.assertEqual(process.stderr.read(), b'')

    def test_disconnected_quiet_consumer_reaps_plugin(self):
        code, pid = self.tracked_code('time.sleep(10)')
        process = self.start(code, timeout=10)
        self.ready(process); process.stdout.close()
        self.assertEqual(process.wait(timeout=2), 0)
        self.assert_reaped(pid)
        self.assertEqual(process.stderr.read(), b'')

    def test_slow_consumer_is_bounded(self):
        code, pid = self.tracked_code('while True: print(\'{"text":"\'+"x"*10000+\'"}\',flush=True)')
        process = self.start(code, timeout=10)
        # Deliberately leave the consumer pipe full; the supervisor must not hang.
        self.assertEqual(process.wait(timeout=3), 1)
        self.assert_reaped(pid)
        self.assertIn(b'consumer is too slow', process.stderr.read())

    def test_stop_while_consumer_is_full(self):
        code, pid = self.tracked_code('while True:\n print(\'{"text":"\'+"x"*10000+\'"}\',flush=True)\n time.sleep(.005)')
        process = self.start(code, timeout=10)
        self.ready(process); time.sleep(.1)
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=2), 0)
        self.assert_reaped(pid)


if __name__ == '__main__': unittest.main()

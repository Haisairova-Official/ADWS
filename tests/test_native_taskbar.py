"""Read-only launcher tests using an isolated HOME and a foreground test host."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import adws_native_taskbar as preview
import adws_plugin_preview as snapshots
import adws_plugin_watchdog as watchdog


class TaskbarPreview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '配置 测试'
        self.root.mkdir()
        self.config = self.root / 'bar.jsonc'
        self.style = self.root / 'style.css'
        self.style.write_text('@import "colors.css"; label {color: @fg;}')
        (self.root / 'colors.css').write_text('@define-color fg #abcdef;')
        self.config.write_text('{"modules-left":["clock"],"modules-right":[]}')
        self.env = {**os.environ, 'HOME': str(self.root), 'XDG_CONFIG_HOME': str(self.root / 'config'),
                    'XDG_DATA_HOME': str(self.root / 'data'), 'XDG_CACHE_HOME': str(self.root / 'cache'),
                    'XDG_STATE_HOME': str(self.root / 'state'), 'XDG_RUNTIME_DIR': str(self.root / 'runtime'),
                    'ADWS_CACHE_DIR': str(self.root / 'live-packages'), 'ADWS_PLUGIN_DIR': str(self.root / 'plugins')}
        self.env.pop('WAYLAND_DISPLAY', None)
        self.env.pop('DISPLAY', None)

    def test_jsonc_recursive_include_precedence_and_cycle(self):
        (self.root / 'inner.json').write_text('{"clock":{"format":"first","nested":{"b":2}}, "margin":4}')
        (self.root / 'more.json').write_text('{"include":"inner.json", "clock":{"format":"outer"}}')
        self.config.write_text('[{"include":["more.json", "inner.json"], // selected\n "clock":{"nested":{"a":1}},"margin":0,}]')
        self.assertEqual(preview.expanded_config(self.config), {'clock': {'format': 'outer', 'nested': {'a': 1, 'b': 2}}, 'margin': 0})
        (self.root / 'inner.json').write_text('{"include":"bar.jsonc"}')
        with self.assertRaisesRegex(ValueError, 'Recursive'):
            preview.expanded_config(self.config)

    def test_live_stylesheet_retains_all_resources_and_rules(self):
        src = "/* @import 'skip'; */ @import 'colors.css'; @import url(\"more.css\"); a{background:url('图片 green.svg');font-family:\"url(no)\";} b{background:url(resource:///ok)}"
        result = preview.relocate_css(src, self.style)
        self.assertIn("/* @import 'skip'; */", result)
        self.assertIn(f"@import '{self.root}/colors.css';", result)
        self.assertIn(f'url("{self.root}/more.css")', result)
        self.assertIn(f"url('{self.root}/图片 green.svg')", result)
        self.assertIn('font-family:"url(no)"', result)
        self.assertIn('url(resource:///ok)', result)

    def test_shared_mplg_discovery_and_private_unpacking(self):
        folder = Path(self.env['ADWS_PLUGIN_DIR']); folder.mkdir()
        package = next((ROOT / 'plugins').glob('*NCMLyricsBar_1.2.0.mplg'))
        shutil.copyfile(package, folder / package.name)
        layout = self.root / 'layout.json'
        layout.write_text(json.dumps({'apiVersion': 2, 'builtins': [], 'plugins': [{
            'package': 'org.AkiACG_Community.NCMLyricsBar', 'enabled': True,
            'instance': 'lyrics-2', 'width': 190, 'slot':'right', 'order':0}]}))
        sandbox = self.root / 'snapshot'; sandbox.mkdir()
        with patch.dict(os.environ, self.env):
            cfg, css = preview.generate(sandbox, self.config, self.style, layout)
        data = json.loads(cfg.read_text())
        module = data['modules-right'][0]
        self.assertIn('lyrics-2', module)
        self.assertIn('ADWS_PLUGIN_INSTANCE=lyrics-2', data[module]['exec'])
        self.assertIn('adws_plugin_runner.py', data[module]['exec'])
        self.assertIn(str(folder / package.name), data[module]['exec'])
        self.assertEqual(data[module]['width'], 190)
        self.assertTrue(any((sandbox / 'packages').rglob('.adws-stamp.json')))
        self.assertFalse(Path(self.env['ADWS_CACHE_DIR']).exists())
        self.assertTrue(css.is_file())
        self.assertNotIn('include', data)

    def test_preview_prefers_its_built_modules_and_preserves_custom_paths(self):
        folder = self.root / 'libexec/taskbar-preview'
        folder.mkdir(parents=True)
        name = 'libniri_taskbar.so'
        (folder / name).touch()
        stock = Path.home() / '.local/lib/waybar' / name
        custom = self.root / 'custom' / name
        bar = {'cffi/niri-taskbar': {'module_path': str(stock)},
               'cffi/system-tray': {'module_path': str(custom)}}
        with patch.object(preview, 'ROOT', self.root):
            preview.use_preview_modules(bar)
        self.assertEqual(bar['cffi/niri-taskbar']['module_path'], str(folder / name))
        self.assertEqual(bar['cffi/system-tray']['module_path'], str(custom))

    def test_foreground_signal_destroys_only_owned_host_and_workspace(self):
        ready = self.root / 'ready.json'
        binary = self.root / 'host'
        binary.write_text('''#!/usr/bin/env python3
import json, os, pathlib, signal, sys
config = pathlib.Path(sys.argv[2]); pins = pathlib.Path(os.environ['ADWS_TASKBAR_PINS_FILE'])
assert json.loads(config.read_text())['modules-left'] == ['clock']
assert pins.read_text() == 'original pins'
pins.write_text('changed private pins')
signal.signal(signal.SIGTERM, lambda *_: sys.exit(19))
pathlib.Path(os.environ['TEST_READY']).write_text(json.dumps({'pid':os.getpid(),'private':str(config.parent),'style':sys.argv[4],'runtime':os.environ['XDG_RUNTIME_DIR']}))
signal.pause()
'''); binary.chmod(0o755)
        pins = Path(self.env['XDG_CONFIG_HOME']) / 'adws/taskbar-pins.json'
        pins.parent.mkdir(parents=True); pins.write_text('original pins')
        unrelated = subprocess.Popen(['sleep', '60']); self.addCleanup(unrelated.wait); self.addCleanup(unrelated.terminate)
        child = subprocess.Popen([str(ROOT / 'adws'), 'taskbar-preview', '--current-session', '--config', str(self.config),
                                  '--binary', str(binary), '--style', str(self.style)], env={**self.env, 'TEST_READY':str(ready)})
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            info = json.loads(ready.read_text())
            self.assertIn(str(self.root / 'colors.css'), Path(info['style']).read_text())
            self.assertEqual(info['runtime'], self.env['XDG_RUNTIME_DIR'])
            child.send_signal(signal.SIGTERM)
            self.assertEqual(child.wait(timeout=4), 19)
            self.assertFalse(Path(info['private']).exists())
            self.assertFalse(Path(f"/proc/{info['pid']}").exists())
            self.assertIsNone(unrelated.poll())
            self.assertEqual(pins.read_text(), 'original pins')
        finally:
            if child.poll() is None:
                child.terminate(); child.wait(timeout=4)

    def test_settings_plugins_and_pin_menu_only_modify_the_private_copy(self):
        folder = Path(self.env['ADWS_PLUGIN_DIR'])
        folder.mkdir()
        pkg = next((ROOT / 'plugins').glob('*NCMLyricsBar_1.2.0.mplg'))
        shutil.copyfile(pkg, folder / pkg.name)
        current = Path(self.env['XDG_CONFIG_HOME'])
        original_pins = current / 'adws/taskbar-pins.json'
        original_pins.parent.mkdir(parents=True)
        original_pins.write_text('{"version":1,"apps":[]}')
        model = original_pins.with_name('taskbar-layout.json')
        # This test validates file paths and never loads a native module.
        library = self.root / 'fixture-taskbar.so'
        library.touch()
        model.write_text(json.dumps({'apiVersion': 2, 'builtins': [], 'plugins': [],
                                     'options': {'taskbar_library': str(library)}}))
        programs = Path(self.env['XDG_DATA_HOME']) / 'applications'
        programs.mkdir(parents=True)
        (programs / 'preview-test.desktop').write_text('[Desktop Entry]\nType=Application\nName=Preview Test\nExec=/bin/true\n')
        sandbox = self.root / 'preview'
        with patch.dict(os.environ, self.env):
            bar, style, env = preview.prepare_workspace(sandbox, self.config, self.style, model)
        private = Path(env['XDG_CONFIG_HOME'])
        before = {p:p.read_bytes() for p in (model, original_pins, self.style, folder / pkg.name,
                                               ROOT / 'config/waybar/style-bottom.css')}
        pins = Path(env['ADWS_TASKBAR_PINS_FILE'])
        self.assertEqual(pins, private / 'adws/taskbar-pins.json')
        self.assertEqual(style, private / 'waybar/style-bottom.css')
        tool = [sys.executable, str(ROOT / 'tools/adws_app_launch.py')]
        for action, expected_count in (('--pin', 1), ('--unpin', 0)):
            subprocess.run([*tool, action, '--', 'preview-test'], env=env, check=True, capture_output=True, timeout=5)
            self.assertEqual(len(json.loads(pins.read_text())['apps']), expected_count)
        code = """import importlib.util, sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import adws_layout as layout
import adws_plugin as mplg
import gi
gi.require_version('Gtk','3.0')
from adws_plugin_manager import packages
from adws_runtime import pids
spec = importlib.util.spec_from_file_location('adws_config',Path(sys.argv[1])/'adws-config.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
config.write_taskbar_overrides(False, '#123456', 17)
config.write_taskbar_font('Sans', 13)
model = layout.load_layout()
model['options']['thickness'] = 45
layout.save_layout(model)
ok,message = layout.apply_layout(model, restart=False)
assert ok, message
assert pids('taskbar') == [] and config.taskbar_pids() == []
ok,message = layout.restart_taskbar()
assert not ok and 'native-host.json' in message, message
installed = packages()
assert len(installed) == 1 and installed[0]['file'].parent == mplg.plugin_dir()
installed[0]['file'].unlink()
"""
        # No Waybar executable is available to settings. Native edits and plugin
        # operations still succeed, and a missing host fails without fallback.
        result = subprocess.run([sys.executable, '-c', code, str(ROOT/'tools')], timeout=8,
                                env={**env, 'PATH': str(self.root/'no-executables')}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('#123456', style.read_text())
        self.assertEqual(json.loads((private/'adws/taskbar-layout.json').read_text())['options']['thickness'], 45)
        self.assertFalse((Path(env['ADWS_PLUGIN_DIR'])/pkg.name).exists())
        for path, source in before.items():
            self.assertEqual(path.read_bytes(), source)

    def test_settings_window_observes_the_owned_pid_even_in_current_session(self):
        from gi.repository import GLib
        workspace = self.root / 'preview-window'
        workspace.mkdir()
        env = {'ADWS_TASKBAR_PREVIEW':'1','ADWS_PLUGIN_RUNTIME_DIR':str(workspace)}
        class Window:
            def __init__(self):
                self.closed = False
            def connect(self, event, callback):
                self.cleanup = callback
            def destroy(self):
                self.closed = True
                self.cleanup(self)
        window = Window()
        with subprocess.Popen(['sleep','20']) as owner, patch.dict(os.environ, env):
            try:
                preview.register_host(owner, env, nested=False)
                preview.follow_preview(window)
            finally:
                owner.terminate()
                owner.wait(timeout=3)
            deadline = time.monotonic() + 1
            while not window.closed and time.monotonic() < deadline:
                GLib.MainContext.default().iteration(False)
            self.assertTrue(window.closed)

    def test_health_and_snapshots_do_not_replace_the_live_instance(self):
        live = Path(self.env['XDG_RUNTIME_DIR']); live.mkdir()
        private = self.root / 'preview'
        for name in ('plugin-health', 'plugin-preview'):
            (private / 'adws' / name).mkdir(parents=True)
        with patch.dict(os.environ, self.env):
            snapshots.publish({'text': 'existing'}, 'example')
            watchdog.store({'instance': 'example', 'boot': watchdog.boot_id(), 'state': 'running'})
            with patch.dict(os.environ, {'ADWS_PLUGIN_RUNTIME_DIR': str(private)}):
                snapshots.publish({'text': 'preview'}, 'example')
                watchdog.store({'instance': 'example', 'boot': watchdog.boot_id(), 'state': 'failed'})
                self.assertEqual(snapshots.read()['example']['text'], 'preview')
                self.assertEqual(watchdog.health('example')['state'], 'failed')
                shutil.rmtree(private)
                watchdog.store({'instance':'example','state':'stopped'})
                snapshots.publish({'text':'late'}, 'example')
                self.assertFalse(private.exists())
            self.assertEqual(snapshots.read()['example']['text'], 'existing')
            self.assertEqual(watchdog.health('example')['state'], 'running')


if __name__ == '__main__':
    unittest.main()

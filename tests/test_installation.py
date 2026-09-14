"""Fresh-home installation and startup checks; never operate on the live desktop."""
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import mnws_health as health
from mnws_i18n import tr as _tr
import mnws_layout as layout
import mnws_runtime as runtime

ROOT = Path(__file__).resolve().parents[1]


class InstallationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='mnws-install-test-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.config = self.root / 'xdg-config'
        self.state = self.root / 'xdg-state'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.config),
                        XDG_STATE_HOME=str(self.state), XDG_DATA_HOME=str(self.root / 'data'),
                        XDG_CACHE_HOME=str(self.root / 'cache'), PATH=str(self.bin) + os.pathsep + str(self.home / '.local/bin') + os.pathsep + os.environ['PATH'])
        for program in ('niri', 'waybar', 'thunar', 'systemctl', 'rofi'):
            file = self.bin / program
            file.write_text('#!/bin/sh\nexit 0\n')
            file.chmod(0o755)
        self.libs = self.home / '.local/lib/waybar'
        self.libs.mkdir(parents=True)
        for name in ('libniri_taskbar.so', 'libwaybar-space.so', 'libmnws_panel.so'):
            (self.libs / name).touch()

    def install(self):
        return subprocess.run(['bash', str(ROOT / 'scripts/mnws-install.sh')],
                              env=self.env, input="n\n", capture_output=True, text=True)

    def config_files(self):
        folder = self.config / 'waybar'
        folder.mkdir(parents=True, exist_ok=True)
        config, style = folder / 'config-bottom.jsonc', folder / 'style-bottom.css'
        config.write_text('{"modules-left": []}')
        style.write_text('')
        return config, style

    def test_clean_install_xdg_idempotence_and_preservation(self):
        first = self.install()
        self.assertEqual(first.returncode, 0, first.stderr)
        folder = self.config / 'waybar'
        target = folder / 'config-bottom.jsonc'
        self.assertTrue(target.is_file())
        self.assertFalse(target.is_symlink())
        self.assertEqual(layout.parse_jsonc(target.read_text())['include'], str(folder / 'modules.jsonc'))
        self.assertFalse((self.home / '.config/waybar').exists())
        self.assertTrue((self.home / 'Desktop').is_dir())
        original = self.root / 'custom.jsonc'
        original.write_text('{"height":77}')
        target.unlink()
        target.symlink_to(original)
        (folder / 'style-bottom.css').write_text('/* personal style */')
        before = (ROOT / 'config/waybar/config-bottom.jsonc').read_bytes()
        again = self.install()
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(target.resolve(), original)
        self.assertEqual(original.read_text(), '{"height":77}')
        self.assertEqual((folder / 'style-bottom.css').read_text(), '/* personal style */')
        self.assertEqual((ROOT / 'config/waybar/config-bottom.jsonc').read_bytes(), before)

    def test_missing_library_aborts_before_installing(self):
        (self.libs / 'libniri_taskbar.so').unlink()
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('libniri_taskbar.so', result.stdout)
        self.assertFalse((self.config / 'waybar').exists())
        self.assertFalse((self.home / '.local/bin/mnws').exists())

    def test_broken_symlink_is_not_replaced(self):
        config, _ = self.config_files()
        config.unlink()
        config.symlink_to(self.root / 'missing')
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(config.is_symlink())
        self.assertEqual(config.readlink(), self.root / 'missing')

    def test_early_waybar_exit_reports_log(self):
        config, style = self.config_files()
        fake = self.bin / 'waybar'
        fake.write_text('#!/bin/sh\necho "bad config test" >&2\nexit 7\n')
        with patch.dict(os.environ, self.env), patch.object(layout, 'taskbar_pids', return_value=[]):
            ok, message = layout.restart_taskbar(config, style)
        self.assertFalse(ok)
        self.assertIn('7', message)
        self.assertIn('taskbar.log', message)
        self.assertIn('bad config test', (self.state / 'mnws/taskbar.log').read_text())

    def test_missing_module_blocks_write_and_restart(self):
        config, style = self.config_files()
        data = {'modules-left':['cffi/test'], 'cffi/test':{'module_path':str(self.root/'missing.so')}}
        with patch.object(layout, 'render_waybar_config', return_value=data), patch.object(layout, 'restart_taskbar') as restart:
            before = config.read_text()
            ok, message = layout.apply_layout({}, True, config_path=config, style_path=style)
            self.assertFalse(ok)
            self.assertIn('missing.so', message)
            self.assertEqual(config.read_text(), before)
            restart.assert_not_called()

    def test_check_reports_missing_files(self):
        with patch.dict(os.environ, self.env), patch.object(health, 'dependency_errors', return_value=[]), patch('sys.stderr', new_callable=io.StringIO) as errors:
            self.assertEqual(health.check(), 1)
        self.assertIn(_tr('无法读取任务栏配置'), errors.getvalue())

    def test_xdg_paths_match_all_tools(self):
        with patch.dict(os.environ, self.env):
            self.assertEqual(layout.live_config_path(), self.config / 'waybar/config-bottom.jsonc')
            self.assertEqual(health.config_home(), self.config)
            self.assertEqual(health.state_home(), self.state)

    def test_build_allows_network_and_installs_atomically(self):
        # Fake Cargo makes the compiler invocation observable without downloading crates.
        source = self.root / 'project'
        (source / 'src/niri-taskbar/target/release').mkdir(parents=True)
        shutil.copy2(ROOT / 'mnws', source / 'mnws')
        (source / 'scripts').mkdir()
        shutil.copy2(ROOT / 'scripts/mnws-i18n.sh', source / 'scripts/mnws-i18n.sh')
        artifact = source / 'src/niri-taskbar/target/release/libniri_taskbar.so'
        artifact.write_text('new library')
        old = self.libs / 'libniri_taskbar.so'
        old.write_text('old library')
        held = old.open()
        self.addCleanup(held.close)
        cargo = self.bin / 'cargo'
        cargo.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$HOME/cargo-args"\nexit 0\n')
        cargo.chmod(0o755)
        result = subprocess.run([str(source / 'mnws'), 'build-taskbar'], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        flags = (self.home / 'cargo-args').read_text()
        self.assertNotIn('--offline', flags)
        self.assertIn('--locked', flags)
        self.assertEqual(old.read_text(), 'new library')
        self.assertEqual(held.read(), 'old library')

    def test_custom_desktop_directory_initializes(self):
        folder = self.config / 'niri-desktop-layer'
        folder.mkdir(parents=True)
        desktop = self.root / 'custom-desktop'
        (folder / 'config.toml').write_text('directory = "' + str(desktop) + '"\n')
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(desktop.is_dir())
        self.assertFalse((self.home / 'Desktop').exists())

    def test_include_and_css_errors_are_reported(self):
        config, style = self.config_files()
        config.write_text('{"include": ["missing.jsonc"]}')
        style.write_text('@import "missing.css";')
        errors = health.validate_waybar(config, style)
        self.assertTrue(any('missing.jsonc' in text for text in errors))
        self.assertTrue(any('missing.css' in text for text in errors))
        config.write_text('{"modules-left": ["group/loop"], "group/loop": {"modules": ["group/loop"]}}')
        style.write_text('')
        self.assertEqual(health.validate_waybar(config, style), [])

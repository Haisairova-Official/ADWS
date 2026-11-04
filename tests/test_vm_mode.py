import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import adws_vm_mode as vm
import adws_vm_settings as settings


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "original"
        self.source.mkdir()
        self.main = self.source / "config.kdl"

    def tearDown(self):
        self.temp.cleanup()

    def test_recursive_includes_modifier_taps_and_mru_are_all_disabled(self):
        self.main.write_text('include "binds.kdl"\ninclude "adws.kdl"\n'
                             'recent-windows { binds { Mod+Tab { next-window; } } }\n'
                             'layout { gaps 9; }\n')
        (self.source / "binds.kdl").write_text('binds { Alt+Tab { spawn "test"; } }\ninclude "nested.kdl"\n')
        (self.source / "nested.kdl").write_text('binds { XF86AudioMute { spawn "mute"; } }\n')
        (self.source / "adws.kdl").write_text('binds { Mod { toggle-overview; } Ctrl { spawn; } }\n')
        output, originals = vm.snapshot_config(self.main, self.root / "vm", passthrough=True)
        generated = "\n".join(p.read_text() for p in output.parent.glob("*.kdl"))
        for key in ("Alt+Tab", "Mod+Tab", "XF86AudioMute", "toggle-overview", "Ctrl {"):
            self.assertNotIn(key, generated)
        self.assertEqual(generated.count(vm.KEY + " repeat=false"), 1)
        self.assertIn("recent-windows { off; binds {}; }", generated)
        self.assertIn("layout { gaps 9; }", generated)
        self.assertTrue(all(p.read_text() == old for p, old in originals.items()))

    def test_comments_and_raw_strings_are_not_structural(self):
        content = ('/* outer { /* nested } */ } */\n'
                   'window-rule { match title=r###"a { binds } // z"###; }\n'
                   'environment { TEST r#"}"#; }\n'
                   '// binds { this is a comment }\n'
                   'binds { Mod+T { spawn "echo \\\"{ binds }\\\""; } }\n')
        self.main.write_text(content)
        output, _ = vm.snapshot_config(self.main, self.root / "vm", passthrough=True)
        text = output.read_text()
        self.assertIn('title=r###"a { binds } // z"###', text)
        self.assertIn('TEST r#"}"#', text)
        self.assertNotIn("Mod+T", text)
        self.assertIn('// binds { this is a comment }', text)

    def test_disabled_nodes_and_absent_optional_include_cannot_introduce_keys(self):
        self.main.write_text('/-include "missing-disabled.kdl"\n'
                             'include optional=true "future.kdl"\n'
                             '/-binds { Mod+X { quit; } }\n')
        output, _ = vm.snapshot_config(self.main, self.root / "vm", passthrough=True)
        (self.source / "future.kdl").write_text('binds { Mod+X { quit; } }\n')
        active_nodes = [n for n in vm.parse_nodes(vm.tokens(output.read_text())) if not n.disabled]
        include = next(n for n in active_nodes if n.name == "include")
        target = Path(vm.decode_string(next(t for t in include.header if t.kind == "quoted")))
        self.assertFalse(target.exists())
        self.assertEqual(target.parent, output.parent)

    def test_fallback_is_a_complete_original_snapshot(self):
        self.main.write_text('include "binds.kdl"\n')
        original = 'binds { Mod { toggle-overview; } }\n'
        included = self.source / "binds.kdl"
        included.write_text(original)
        output, _ = vm.snapshot_config(self.main, self.root / "desktop", passthrough=False)
        included.write_text('binds { Mod { quit; } }\n')
        node = vm.parse_nodes(vm.tokens(output.read_text()))[0]
        target = Path(vm.decode_string(node.header[0]))
        self.assertEqual(target.read_text(), original)

    def test_fork_builtin_super_fallback_is_disabled_in_vm_mode(self):
        self.main.write_text('include "appearance.kdl"\n'
                             'binds { Super { toggle-overview; } }\n')
        (self.source / "appearance.kdl").write_text('grid-overview { gap 16; default-mod-action true; }\n')
        output, _ = vm.snapshot_config(self.main, self.root / "vm", passthrough=True)
        overrides = output.parent / "passthrough-overrides.kdl"
        self.assertIn("grid-overview { default-mod-action false; }", overrides.read_text())
        self.assertNotIn("Super {", output.read_text())
        self.assertTrue(output.read_text().rstrip().endswith(json.dumps(str(overrides))))
        fallback, _ = vm.snapshot_config(self.main, self.root / "desktop", passthrough=False)
        baseline = "\n".join(p.read_text() for p in fallback.parent.glob("*.kdl"))
        self.assertIn("Super { toggle-overview; }", baseline)
        self.assertNotIn("default-mod-action false", baseline)

    def test_cycle_is_rejected(self):
        self.main.write_text('include "config.kdl"\n')
        with self.assertRaisesRegex(ValueError, "循环"):
            vm.snapshot_config(self.main, self.root / "vm", passthrough=True)

    def test_symlink_include_paths_remain_relative_to_named_file(self):
        real = self.root / "elsewhere"
        real.mkdir()
        (real / "main.kdl").write_text('include "binds.kdl"\n')
        self.main.symlink_to(real / "main.kdl")
        (self.source / "binds.kdl").write_text('layout { gaps 19; }\n')
        output, _ = vm.snapshot_config(self.main, self.root / "vm", passthrough=True)
        text = "\n".join(p.read_text() for p in output.parent.glob("*.kdl"))
        self.assertIn("gaps 19", text)


class SupervisionTests(unittest.TestCase):
    @patch.object(vm, "run_niri")
    def test_disabling_automatic_switch_does_not_enter_on_focus(self, run):
        run.return_value = '[{"id": 26, "app_id": "Vmware", "is_focused": true}]'
        controller = self.focused_controller()
        controller.options['auto_switch'] = False
        controller.check()
        controller.enter.assert_not_called()

    @patch.object(vm, "vmware_processes", return_value={123})
    @patch.object(vm, "run_niri")
    def test_disabling_automatic_switch_keeps_manual_mode_until_recovery(self, run, processes):
        run.return_value = '[{"id": 26, "app_id": "Vmware"}, {"id": 13, "app_id": "chatgpt", "is_focused": true}]'
        controller = self.focused_controller()
        controller.options['auto_switch'] = False
        controller.active = True
        controller.check()
        controller.restore.assert_not_called()

    def test_closing_frontend_or_last_window_restores_even_with_background_vm(self):
        windows = [{"app_id": "Vmware", "id": 26}]
        self.assertFalse(vm.should_restore({123}, windows))
        self.assertTrue(vm.should_restore(set(), windows))
        self.assertTrue(vm.should_restore({123}, []))
        self.assertTrue(vm.should_restore({123}, [{"app_id": "kitty"}]))

    def test_process_monitor_ignores_vmware_vmx_and_tray(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            for pid, name in ((1, "vmware"), (2, "vmware-vmx"), (3, "vmware-tray"), (4, "vmplayer")):
                path = proc / str(pid)
                path.mkdir()
                (path / "comm").write_text(name + "\n")
            self.assertEqual(vm.vmware_processes(proc), {1, 4})

    @patch.object(vm, "notify")
    @patch.object(vm, "load")
    @patch.object(vm, "validate")
    def test_restore_reads_latest_normal_config(self, validate, load, notify):
        controller = vm.Controller(Path("/normal/config.kdl"))
        controller.active = True
        controller.publish = Mock()
        controller.restore()
        load.assert_called_once_with(controller.normal)
        self.assertFalse(controller.active)
        controller.publish.assert_called_once()

    @patch.object(vm, "notify")
    @patch.object(vm, "load")
    @patch.object(vm, "validate")
    def test_invalid_edited_normal_config_restores_original_snapshot(self, validate, load, notify):
        with tempfile.TemporaryDirectory() as directory:
            fallback = Path(directory) / "saved.kdl"
            fallback.write_text("binds {}\n")
            controller = vm.Controller(Path("/normal/config.kdl"))
            controller.fallback = fallback
            controller.active = True
            controller.publish = Mock()
            validate.side_effect = [RuntimeError("bad config"), None]
            controller.restore()
            load.assert_called_once_with(fallback)
            self.assertFalse(controller.active)
            self.assertIn("快照", controller.reason)

    def test_indicator_exit_restores_instead_of_leaving_invisible_mode(self):
        controller = vm.Controller(Path("/normal/config.kdl"))
        controller.active = True
        controller.indicator = Mock()
        controller.indicator.poll.return_value = 1
        controller.restore = Mock()
        controller.check()
        controller.restore.assert_called_once_with("模式提示退出，自动恢复", automatic=True)

    @patch.object(vm, "run_niri", return_value="[]")
    @patch.object(vm, "vmware_processes", return_value={123})
    def test_window_closure_uses_a_short_grace_period(self, processes, run):
        controller = vm.Controller(Path("/normal/config.kdl"))
        controller.active = True
        controller.indicator = Mock()
        controller.indicator.poll.return_value = None
        controller.restore = Mock()
        with patch.object(vm.time, "monotonic", side_effect=[10, 12]):
            controller.check()
            controller.restore.assert_not_called()
            controller.check()
        controller.restore.assert_called_once_with("VMware 窗口已关闭，自动恢复", automatic=True)

    def focused_controller(self):
        controller = vm.Controller(Path("/normal/config.kdl"), options={'auto_switch': True, 'shortcut': vm.KEY})
        controller.indicator = Mock()
        controller.indicator.poll.return_value = None
        controller.publish = Mock()
        controller.enter = Mock()
        controller.restore = Mock()
        return controller

    @patch.object(vm, "run_niri")
    def test_focusing_vmware_enters_automatically(self, run):
        windows = [{"id": 26, "app_id": "Vmware", "is_focused": True}]
        run.return_value = json.dumps(windows)
        controller = self.focused_controller()
        controller.check()
        controller.enter.assert_called_once_with(automatic=True, windows=windows)

    @patch.object(vm, "vmware_processes", return_value={123})
    @patch.object(vm, "run_niri")
    def test_focusing_another_window_restores_without_moving_focus(self, run, processes):
        run.return_value = json.dumps([{"id": 26, "app_id": "Vmware"},
                                     {"id": 13, "app_id": "chatgpt", "is_focused": True}])
        controller = self.focused_controller()
        controller.active = True
        controller.check()
        controller.restore.assert_called_once_with("切到其他窗口，自动恢复", automatic=True)
        controller.enter.assert_not_called()
        run.assert_called_once_with("msg", "-j", "windows", timeout=2)

    @patch.object(vm, "run_niri")
    def test_manual_recovery_is_held_until_focus_leaves_then_reentry_works(self, run):
        controller = self.focused_controller()
        controller.manual_focus_id = 26
        focused_vm = [{"id": 26, "app_id": "Vmware", "is_focused": True}]
        run.return_value = json.dumps(focused_vm)
        controller.check()
        controller.enter.assert_not_called()
        run.return_value = json.dumps([{"id": 13, "app_id": "chatgpt", "is_focused": True}])
        controller.check()
        self.assertIsNone(controller.manual_focus_id)
        run.return_value = json.dumps(focused_vm)
        controller.check()
        controller.enter.assert_called_once_with(automatic=True, windows=focused_vm)

    @patch.object(vm, "run_niri", return_value='[{"id": 26, "app_id": "Vmware", "is_focused": true}]')
    def test_manual_shortcut_records_current_window(self, run):
        controller = self.focused_controller()
        controller.active = True
        controller.manual()
        controller.restore.assert_called_once_with()
        self.assertEqual(controller.manual_focus_id, 26)

    @patch.object(vm, "run_niri", return_value='[{"id": 26, "app_id": "Vmware"}]')
    def test_transient_null_focus_does_not_cancel_manual_override(self, run):
        controller = self.focused_controller()
        controller.manual_focus_id = 26
        controller.check()
        self.assertEqual(controller.manual_focus_id, 26)
        controller.enter.assert_not_called()

    @patch.object(vm, "notify")
    @patch.object(vm, "load")
    @patch.object(vm, "validate")
    @patch.object(vm, "vmware_processes", return_value={123})
    @patch.object(vm, "run_niri", return_value='{"id": 13, "app_id": "chatgpt"}')
    def test_focus_change_during_preparation_never_steals_focus(self, run, processes, validate, load, notify):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normal = root / "config.kdl"
            normal.write_text("binds {}\n")
            (root / "indicator.ready").touch()
            controller = vm.Controller(normal)
            controller.indicator = Mock()
            controller.indicator.poll.return_value = None
            controller.publish = Mock()
            with patch.object(vm, "RUNTIME", root):
                entered = controller.enter(automatic=True, windows=[{"id": 26, "app_id": "Vmware", "is_focused": True}])
            self.assertFalse(entered)
            self.assertFalse(controller.active)
            run.assert_called_once_with("msg", "-j", "focused-window")
            load.assert_not_called()
            self.assertFalse(list(root.glob("configs-*")))


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'niri/config.kdl'
        self.config.parent.mkdir()
        self.config.write_text('input {\n keyboard { repeat-rate 30; }\n}\n')
        self.options = self.root / 'adws/vm-mode.json'
        self.unit = self.root / 'systemd/user/niri-vm-mode.service'
        self.wrapper = self.root / 'niri/scripts/niri-vm-mode.py'
        self.script = self.root / 'ADWS/tools/adws_vm_mode.py'
        self.service = patch.object(settings, 'service').start()
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {'XDG_STATE_HOME': str(self.root / 'state')}).start()

    def apply(self, key=vm.KEY, auto=True):
        return settings.apply_options({'auto_switch': auto, 'shortcut': key}, config=self.config,
                                      settings=self.options, script=self.script, unit=self.unit, wrapper=self.wrapper)

    def test_saved_options_and_key_are_validated_and_legacy_block_is_migrated(self):
        (self.config.parent / '.niri-vm-mode.kdl').write_text(vm.toggle_binding())
        original = self.config.read_text()
        self.config.write_text(original + vm.LEGACY_BEGIN + '\ninclude ".niri-vm-mode.kdl"\n' + vm.LEGACY_END + '\n')
        result = self.apply('Shift+Control+Alt+r', auto=False)
        self.assertEqual(vm.read_options(self.options), {'auto_switch': False, 'shortcut': 'Ctrl+Alt+Shift+R'})
        self.assertNotIn(vm.LEGACY_BEGIN, self.config.read_text())
        self.assertTrue(self.config.read_text().startswith(original))
        included = next(self.config.parent.glob('.adws-vm-mode-*.kdl'))
        self.assertIn('Ctrl+Alt+Shift+R repeat=false allow-inhibiting=false', included.read_text())
        self.assertTrue(Path(result['backup']).is_dir())
        self.assertIn(str(self.script), self.unit.read_text())
        vm.validate(self.config)

    def test_conflicting_shortcut_is_rejected_before_service_or_files_change(self):
        original = 'binds {\n Ctrl+Alt+Shift+Q { spawn "reserved"; }\n}\n'
        self.config.write_text(original)
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.config.read_text(), original)
        self.assertFalse(self.options.exists())
        self.assertFalse(list(self.config.parent.glob('.adws-vm-mode-*.kdl')))
        self.service.assert_not_called()

    def test_invalid_keys_cannot_write_configuration(self):
        for key in ('Q', 'Ctrl', 'Ctrl+Ctrl+Q', 'Ctrl+Q; quit', 'Ctrl+\"Q', 'Ctrl+NotARealKeysym'):
            with self.subTest(key=key), self.assertRaises((ValueError, RuntimeError)):
                self.apply(key)
        self.assertFalse(self.options.exists())
        self.service.assert_not_called()

    def test_service_failure_rolls_back_configuration_and_options(self):
        original = self.config.read_text()
        self.options.parent.mkdir()
        self.options.write_text('{"auto_switch": true, "shortcut": "Ctrl+Alt+Shift+Q"}\n')
        old_options = self.options.read_bytes()
        def fail(*args):
            if args == ('enable', '--now', 'niri-vm-mode.service'):
                raise RuntimeError('start failed')
        self.service.side_effect = fail
        with self.assertRaisesRegex(RuntimeError, 'start failed'):
            self.apply('Ctrl+Alt+Shift+R', auto=False)
        self.assertEqual(self.config.read_text(), original)
        self.assertEqual(self.options.read_bytes(), old_options)
        self.assertFalse(self.unit.exists())
        self.assertFalse(self.wrapper.exists())
        self.assertFalse(list(self.config.parent.glob('.adws-vm-mode-*.kdl')))

    def test_config_symlink_is_preserved(self):
        target = self.root / 'my-config.kdl'
        self.config.rename(target)
        self.config.symlink_to(target)
        self.apply()
        self.assertTrue(self.config.is_symlink())
        self.assertIn(vm.BEGIN, target.read_text())

    def test_rollback_restores_files_even_if_stopping_service_fails(self):
        original = self.config.read_text()
        def fail(*args):
            if args[0] in ('enable', 'stop'):
                raise RuntimeError('service unavailable')
        self.service.side_effect = fail
        with self.assertRaisesRegex(RuntimeError, 'service unavailable'):
            self.apply('Ctrl+Alt+Shift+R')
        self.assertEqual(self.config.read_text(), original)
        self.assertFalse(self.options.exists())
        self.assertFalse(self.unit.exists())

    def test_changed_include_is_preserved_and_apply_is_aborted(self):
        included = self.config.parent / 'bindings.kdl'
        included.write_text('binds {}\n')
        self.config.write_text('include "bindings.kdl"\n')
        self.unit.parent.mkdir(parents=True)
        self.unit.write_text('old service\n')
        def change(*args):
            if args == ('stop', 'niri-vm-mode.service'):
                included.write_text('binds {\n Ctrl+Alt+Shift+R { quit; }\n}\n')
        self.service.side_effect = change
        with self.assertRaises(ValueError):
            self.apply('Ctrl+Alt+Shift+R')
        self.assertEqual(self.config.read_text(), 'include "bindings.kdl"\n')
        self.assertIn('quit', included.read_text())
        self.assertEqual(self.unit.read_text(), 'old service\n')
        self.assertFalse(self.options.exists())

    def test_new_shortcut_is_the_only_key_in_passthrough_snapshot(self):
        self.apply('Ctrl+Alt+Shift+R')
        output, _ = vm.snapshot_config(self.config, self.root / 'snapshot', passthrough=True,
                                       shortcut='Ctrl+Alt+Shift+R')
        generated = '\n'.join(p.read_text() for p in output.parent.glob('*.kdl'))
        self.assertIn('Ctrl+Alt+Shift+R repeat=false', generated)
        self.assertNotIn('Ctrl+Alt+Shift+Q repeat=false', generated)


if __name__ == "__main__":
    unittest.main()

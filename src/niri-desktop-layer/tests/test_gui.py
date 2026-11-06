"""Opt-in tests with a real GTK preview and an isolated temporary desktop.

Run from the project directory, preferably with an isolated display and D-Bus:
    DESKTOP_LAYER_GUI_TEST=1 GDK_BACKEND=x11 dbus-run-session -- \
        xvfb-run -a -s '-screen 0 1280x1024x24 -extension GLX' \
        /usr/bin/python3 -m unittest discover -s tests -p test_gui.py -v

These tests never create a layer surface, launch a file/application, or read or
write the user's desktop/configuration. Pointer callbacks are exercised directly;
actual compositor pointer routing requires a separate live layer smoke test.
"""

from __future__ import annotations
from desktop_layer.i18n import tr as _tr, chinese

import itertools
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(os.environ.get("DESKTOP_LAYER_GUI_TEST") == "1",
                     "set DESKTOP_LAYER_GUI_TEST=1 for isolated GTK integration tests")
class DesktopGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi
        for name, version in (("Gtk", "3.0"), ("Gdk", "3.0"),
                              ("GtkLayerShell", "0.1"), ("PangoCairo", "1.0")):
            gi.require_version(name, version)
        from gi.repository import Gtk, Gdk, Gio, GLib
        import cairo
        from desktop_layer import app
        from desktop_layer.config import Config
        cls.Gtk, cls.Gdk, cls.Gio, cls.GLib = Gtk, Gdk, Gio, GLib
        cls.cairo, cls.module, cls.Config = cairo, app, Config
        ok, _ = Gtk.init_check(None)
        if not ok:
            raise RuntimeError("GUI tests requested, but GTK cannot open the test display")
        cls.serial = itertools.count()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="desktop-layer-gui-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.desktop = self.root / "Desktop"
        self.desktop.mkdir()
        self.state = self.root / "state" / "layout.json"
        for index in range(2):
            (self.desktop / f"item-{index:04d}.txt").write_text("GUI fixture\n")
        self.launch = Mock(return_value=True)
        self.open_uri = Mock(return_value=True)

    def run_preview(self, cfg, scenario):
        """Drive a scenario generator on GTK's loop, with a hard failure timeout.

        A yielded callable is a condition to await without blocking the loop.
        A completed scenario must close its window itself: the watchdog catches
        regressions where closing a preview leaves an invisible process alive.
        """
        Gtk, GLib = self.Gtk, self.GLib
        args = self.module.arguments(["--preview", "--directory", str(self.desktop),
                                      "--state", str(self.state)])
        original_run = Gtk.Application.run
        failures, captured = [], []
        completed = False

        def wrapped_run(application, argv):
            nonlocal completed
            captured.append(application)
            flow = scenario(application)
            waiting = None
            sources = []

            def advance():
                nonlocal waiting, completed
                try:
                    if waiting is not None and not waiting():
                        return True
                    waiting = next(flow)
                    return True
                except StopIteration:
                    completed = True
                    return False
                except BaseException:
                    failures.append(sys.exc_info())
                    application.quit()
                    return False

            def timeout():
                failures.append((AssertionError, AssertionError(
                    f"GTK scenario timed out at line {flow.gi_frame.f_lineno if flow.gi_frame else 'closed'}, or closing the preview did not stop the app"), None))
                application.quit()
                return False

            sources.append(GLib.timeout_add(25, advance))
            sources.append(GLib.timeout_add(8000, timeout))
            try:
                return original_run(application, argv)
            finally:
                for source_id in sources:
                    source = GLib.MainContext.default().find_source_by_id(source_id)
                    if source is not None:
                        source.destroy()
                flow.close()

        # A unique name also avoids talking to an unrelated manual preview.
        bus_id = f"{self.module.APP_ID}.GuiTest{os.getpid()}.Run{next(self.serial)}"
        with patch.dict(os.environ,{"XDG_CONFIG_HOME":str(self.root/"config")}), \
             patch.object(self.module, "APP_ID", bus_id), \
             patch.object(self.module, "launch_entry", self.launch), \
             patch.object(self.module, "open_in_thunar", self.open_uri), \
             patch.object(Gtk.Application, "run", new=wrapped_run):
            result = self.module.run_gui(args, cfg, self.desktop)
        if failures:
            _, error, traceback = failures[0]
            raise error.with_traceback(traceback)
        self.assertEqual(result, 0, "GTK callback failures must fail the integration test")
        self.assertEqual(len(captured), 1)
        self.assertTrue(completed, "application exited before completing the scenario")
        self.assertEqual(captured[0].get_windows(), [])

    def ready(self, application):
        return bool(application.views and application.views[0].get_mapped()
                    and application.views[0].area.get_allocated_width() > 240
                    and application.views[0].area.get_allocated_height() > 300
                    and application.views[0].rects)

    @staticmethod
    def center(rect):
        x, y, width, height = rect
        return x + width / 2, y + height / 2

    def event(self, position, button=1, kind=None, state=0):
        return SimpleNamespace(x=position[0], y=position[1], button=button,
                               type=kind or self.Gdk.EventType.BUTTON_PRESS,
                               state=self.Gdk.ModifierType(state),
                               time=self.Gdk.CURRENT_TIME)

    def render(self, view):
        surface = self.cairo.ImageSurface(self.cairo.FORMAT_ARGB32,
                                         view.area.get_allocated_width(),
                                         view.area.get_allocated_height())
        self.assertTrue(view.draw(view.area, self.cairo.Context(surface)))
        surface.flush()
        return bytes(surface.get_data())

    def menu_item(self, menu, *labels):
        """Find visible menu choices by their user-facing path."""
        for index, label in enumerate(labels):
            matches = [child for child in menu.get_children()
                       if isinstance(child, self.Gtk.MenuItem) and child.get_label() == label]
            self.assertEqual(len(matches), 1, f"menu must contain exactly one {label!r}")
            item = matches[0]
            if index < len(labels) - 1:
                menu = item.get_submenu()
                self.assertIsInstance(menu, self.Gtk.Menu)
        return item

    def activate_menu(self, view, *labels, key=None):
        menu = view.make_menu(key)
        self.assertIsInstance(menu, self.Gtk.Menu)
        try:
            item = self.menu_item(menu, *labels)
            self.assertTrue(item.get_sensitive())
            item.activate()
        finally:
            menu.destroy()

    def test_explorer_menus_sort_metadata_icon_sizes_properties_and_preferences(self):
        cfg = self.Config()
        folder = self.desktop / "z-folder"
        folder.mkdir()
        first, second = (self.desktop / f"item-{index:04d}.txt" for index in range(2))
        picture = self.desktop / "alpha.png"
        hidden = self.desktop / ".secret.txt"
        for path, size, modified in ((first, 60, 100), (second, 10, 300),
                                     (picture, 20, 200), (hidden, 5, 250)):
            path.write_bytes(b"x" * size)
            os.utime(path, (modified, modified))
        os.utime(folder, (150, 150))
        saved = {}

        def assert_order(view, paths):
            self.assertEqual([entry.path for entry in view.owner.entries], paths)
            # Assert actual visual cells, not only the model's ordering.
            for index, path in enumerate(paths):
                column, row = divmod(index, view.rows)
                self.assertEqual(view.rects[str(path)][:2],
                                 (cfg.margin + column * cfg.cell_width,
                                  cfg.margin + row * cfg.cell_height))

        def first_run(application):
            yield lambda: self.ready(application)
            view = application.views[0]
            self.assertGreaterEqual(view.rows, 4)
            self.assertGreaterEqual(view.columns, 2)
            assert_order(view, [folder, picture, first, second])
            view.selection = {str(first), str(second)}

            menu = view.make_menu(str(first))
            self.assertIsInstance(menu, self.Gtk.Menu)
            self.assertIsInstance(self.menu_item(menu, _tr('查看'), _tr('中等图标')), self.Gtk.RadioMenuItem)
            self.assertTrue(self.menu_item(menu, _tr('查看'), _tr('中等图标')).get_active())
            self.assertTrue(self.menu_item(menu, _tr('排序方式'), _tr('名称')).get_active())
            self.assertTrue(self.menu_item(menu, _tr('排序方式'), _tr('文件夹优先')).get_active())
            self.menu_item(menu, (_tr('打开选中的 ') + '2' + _tr(' 项')))
            self.menu_item(menu, _tr('属性'))
            menu.destroy()
            # Merely opening a context menu must not change layout or preferences.
            self.assertFalse(self.state.exists())

            # Create a real dragged position, then sort through the context menu.
            origin = self.center(view.rects[str(first)])
            destination = (origin[0] + cfg.cell_width, origin[1])
            view.selection = {str(first)}
            view.button_press(view.area, self.event(origin))
            view.motion(view.area, self.event(destination))
            view.button_release(view.area, self.event(destination, kind=self.Gdk.EventType.BUTTON_RELEASE))
            self.assertTrue(application.positions)
            view.selection.add(str(second))
            self.activate_menu(view, _tr('排序方式'), _tr('大小'))
            self.assertEqual(cfg.sort_by, "size")
            self.assertEqual(application.positions, {}, "sorting must discard manual cell overrides")
            self.assertEqual(view.selection, {str(first), str(second)})
            assert_order(view, [folder, second, picture, first])

            self.activate_menu(view, _tr('排序方式'), _tr('项目类型'))
            self.assertEqual(cfg.sort_by, "type")
            self.assertEqual(application.entries[0].path, folder)
            typed_paths = [entry.path for entry in application.entries]
            self.assertEqual(abs(typed_paths.index(first) - typed_paths.index(second)), 1,
                             "files of the same type must be adjacent")
            self.activate_menu(view, _tr('排序方式'), _tr('名称'))
            self.assertEqual(cfg.sort_by, "name")
            assert_order(view, [folder, picture, first, second])
            self.activate_menu(view, _tr('排序方式'), _tr('修改日期'))
            self.assertEqual(cfg.sort_by, "modified")
            assert_order(view, [folder, first, picture, second])
            self.activate_menu(view, _tr('排序方式'), _tr('递减'))
            self.assertTrue(cfg.sort_descending)
            assert_order(view, [folder, second, picture, first])
            self.activate_menu(view, _tr('排序方式'), _tr('文件夹优先'))
            self.assertFalse(cfg.folders_first)
            assert_order(view, [second, picture, folder, first])

            self.activate_menu(view, _tr('查看'), _tr('小图标'))
            self.assertEqual((cfg.icon_size, cfg.cell_width, cfg.cell_height), (32, 96, 92))
            self.assertTrue(all(rect[2:] == (96, 92) for rect in view.rects.values()))
            self.activate_menu(view, _tr('查看'), _tr('大图标'))
            self.assertEqual((cfg.icon_size, cfg.cell_width, cfg.cell_height), (64, 132, 124))
            self.assertTrue(all(rect[2:] == (132, 124) for rect in view.rects.values()))
            self.assertTrue(any(self.render(view)), "resized icons must still render")
            self.activate_menu(view, _tr('查看'), _tr('显示隐藏文件'))
            self.assertTrue(cfg.show_hidden)
            assert_order(view, [second, hidden, picture, folder, first])
            self.assertEqual(view.selection, {str(first), str(second)})

            # The menu opens a usable modal properties dialog for the selected group.
            self.activate_menu(view, _tr('属性'), key=str(first))
            dialogs = [window for window in self.Gtk.Window.list_toplevels()
                       if isinstance(window, self.Gtk.Dialog) and window.get_transient_for() is view]
            self.assertEqual(len(dialogs), 1)
            dialog = dialogs[0]
            self.assertEqual(dialog.get_title(), _tr('属性'))
            self.assertTrue(dialog.get_visible())
            destroyed = []
            dialog.connect("destroy", lambda *_: destroyed.append(True))
            dialog.response(self.Gtk.ResponseType.CLOSE)
            self.assertEqual(destroyed, [True])
            self.assertNotIn(dialog, self.Gtk.Window.list_toplevels())

            saved.update(json.loads(self.state.read_text()))
            self.assertEqual(saved["positions"], {})
            self.assertEqual(saved["preferences"], {
                "sort_by": "modified", "sort_descending": True, "folders_first": False,
                "icon_size": 64, "cell_width": 132, "cell_height": 124, "show_hidden": True,
                "font_family": cfg.font_family, "font_size": cfg.font_size,
            })
            self.launch.assert_not_called()
            self.open_uri.assert_not_called()
            view.close()

        self.run_preview(cfg, first_run)
        cfg = self.Config()

        def second_run(application):
            yield lambda: self.ready(application)
            view = application.views[0]
            for key, value in saved["preferences"].items():
                self.assertEqual(getattr(cfg, key), value, f"{key} must restore in a new process")
            assert_order(view, [second, hidden, picture, folder, first])
            self.assertTrue(all(rect[2:] == (132, 124) for rect in view.rects.values()))
            menu = view.make_menu(None)
            for labels in ((_tr('排序方式'), _tr('修改日期')), (_tr('排序方式'), _tr('递减')),
                           (_tr('查看'), _tr('大图标')), (_tr('查看'), _tr('显示隐藏文件'))):
                self.assertTrue(self.menu_item(menu, *labels).get_active())
            self.assertFalse(self.menu_item(menu, _tr('排序方式'), _tr('文件夹优先')).get_active())
            menu.destroy()
            self.launch.assert_not_called()
            view.close()

        self.run_preview(cfg, second_run)

    def test_batch_untrusted_launch_prompts_are_serialized_and_cancellable(self):
        cfg = self.Config()
        launchers = []
        for index in range(3):
            path = self.desktop / f"launcher-{index}.desktop"
            path.write_text("[Desktop Entry]\nType=Application\n"
                            f"Name=Launcher {index}\nExec=true\n")
            path.chmod(0o600)
            launchers.append(path)
        attempted, allowed = [], []

        def mocked_launch(entry, _context, allow_untrusted=False):
            attempted.append((entry.path, allow_untrusted))
            if entry.kind == "application" and not allow_untrusted:
                raise self.module.UntrustedLauncher(str(entry.path))
            allowed.append(entry.path)
            return True

        self.launch.side_effect = mocked_launch

        def scenario(application):
            yield lambda: self.ready(application)
            view = application.views[0]
            keys = [str(path) for path in launchers]
            view.selection = set(reversed(keys))
            self.activate_menu(view, (_tr('打开选中的 ') + '3' + _tr(' 项')), key=keys[0])
            first_dialog = view.launch_dialog
            self.assertIsInstance(first_dialog, self.Gtk.MessageDialog)
            self.assertIn(keys[0], first_dialog.get_property("secondary-text"))
            self.assertEqual(view.pending_opens, keys[1:])
            self.assertEqual(attempted, [(launchers[0], False)])
            # Repeated open requests must preserve the existing prompt and queue.
            view.open_selected()
            view.open_entry(keys[2])
            self.assertIs(view.launch_dialog, first_dialog)
            self.assertEqual(view.pending_opens, keys[1:])
            self.assertEqual(len(attempted), 1)

            first_dialog.response(self.Gtk.ResponseType.ACCEPT)
            second_dialog = view.launch_dialog
            self.assertIsNot(second_dialog, first_dialog)
            self.assertNotIn(first_dialog, self.Gtk.Window.list_toplevels())
            self.assertIn(keys[1], second_dialog.get_property("secondary-text"))
            self.assertEqual(allowed, launchers[:1])
            self.assertEqual(attempted, [(launchers[0], False), (launchers[0], True),
                                         (launchers[1], False)])
            self.assertEqual(view.pending_opens, keys[2:])

            second_dialog.response(self.Gtk.ResponseType.REJECT)
            third_dialog = view.launch_dialog
            self.assertIsNot(third_dialog, second_dialog)
            self.assertNotIn(second_dialog, self.Gtk.Window.list_toplevels())
            self.assertIn(keys[2], third_dialog.get_property("secondary-text"))
            self.assertEqual(view.pending_opens, [])
            self.assertEqual(allowed, launchers[:1], "skip must not authorize a launch")
            self.assertEqual(attempted[-1], (launchers[2], False))
            third_dialog.response(self.Gtk.ResponseType.CANCEL)
            self.assertIsNone(view.launch_dialog)
            self.assertEqual(view.pending_opens, [])
            self.assertNotIn(third_dialog, self.Gtk.Window.list_toplevels())

            # Consent is per attempt; cancel-all must drop the remaining queue.
            view.open_selected()
            self.assertIn(keys[0], view.launch_dialog.get_property("secondary-text"))
            self.assertEqual(view.pending_opens, keys[1:])
            calls_before_cancel = len(attempted)
            view.launch_dialog.response(self.Gtk.ResponseType.CANCEL)
            self.assertIsNone(view.launch_dialog)
            self.assertEqual(view.pending_opens, [])
            view.process_open_queue()
            self.assertEqual(len(attempted), calls_before_cancel)
            self.assertEqual(allowed, launchers[:1])
            self.assertTrue(all(path.stat().st_mode & 0o111 == 0 for path in launchers),
                            "allow-once must not change launcher permissions")
            self.open_uri.assert_not_called()
            view.close()

        self.run_preview(cfg, scenario)

    def test_render_click_drag_persistence_watcher_and_preview_close(self):
        cfg = self.Config()
        saved = {}

        def first_run(application):
            yield lambda: self.ready(application)
            view = application.views[0]
            capacity = view.columns * view.rows
            self.assertGreaterEqual(capacity, 2)
            # Make exactly two pages regardless of the test monitor dimensions.
            for index in range(2, capacity + 3):
                (self.desktop / f"item-{index:04d}.txt").write_text("GUI fixture\n")
            application.refresh()
            self.assertEqual(len(view.rects), capacity)
            self.assertEqual(view.pages(), 2)
            first_page = set(view.rects)
            view.change_page(1)
            self.assertEqual(len(view.rects), 3)
            self.assertTrue(first_page.isdisjoint(view.rects))
            view.change_page(-1)
            self.assertEqual(set(view.rects), first_page)
            for x, y, width, height in view.rects.values():
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + width, view.area.get_allocated_width())
                self.assertLessEqual(y + height, view.toolbar[1])

            # Render through the actual icon/theme/Pango code, keeping margins transparent.
            surface = self.cairo.ImageSurface(self.cairo.FORMAT_ARGB32,
                                             view.area.get_allocated_width(),
                                             view.area.get_allocated_height())
            self.assertTrue(view.draw(view.area, self.cairo.Context(surface)))
            surface.flush()
            pixels = bytes(surface.get_data())
            self.assertEqual(pixels[:4], b"\0\0\0\0")
            self.assertTrue(any(pixels), "the preview must paint actual icon/label pixels")

            key, other = list(view.rects)[:2]
            source, target = view.rects[key], view.rects[other]
            press = self.event(self.center(source))
            release = self.event(self.center(source), kind=self.Gdk.EventType.BUTTON_RELEASE)
            view.button_press(view.area, press)
            view.button_release(view.area, release)
            self.launch.assert_not_called()
            view.button_press(view.area, self.event(self.center(source), kind=self.Gdk.EventType._2BUTTON_PRESS))
            view.button_release(view.area, release)
            self.launch.assert_called_once()
            self.assertEqual(self.launch.call_args.args[0].path, Path(key))

            self.launch.reset_mock()
            cfg.single_click = True
            view.button_press(view.area, press)
            view.button_release(view.area, release)
            self.launch.assert_called_once()
            self.launch.reset_mock()
            view.button_press(view.area, press)
            view.button_release(view.area, self.event((0, 0), kind=self.Gdk.EventType.BUTTON_RELEASE))
            self.launch.assert_not_called()

            # A real callback sequence swaps an occupied cell without opening either file.
            view.button_press(view.area, press)
            view.motion(view.area, self.event(self.center(target)))
            self.assertTrue(view.dragging)
            view.button_release(view.area, self.event(self.center(target), kind=self.Gdk.EventType.BUTTON_RELEASE))
            self.assertEqual(view.rects[key], target)
            self.assertEqual(view.rects[other], source)
            self.assertFalse(view.dragging)
            self.assertIsNone(view.press)
            self.launch.assert_not_called()
            data = json.loads(self.state.read_text())
            saved.update(data)
            layout_key = f"{view.monitor_key}:0"
            saved_cell = data["positions"][layout_key][key]
            self.assertEqual(saved_cell, [int((target[0] - cfg.margin) // cfg.cell_width),
                                          int((target[1] - cfg.margin) // cfg.cell_height)])

            with patch.object(view, "popup") as popup:
                right = self.event(self.center(view.rects[key]), button=3)
                view.button_press(view.area, right)
                popup.assert_called_once_with(right, key)
                popup.reset_mock()
                toolbar_click = self.event(self.center(view.toolbar))
                view.button_press(view.area, toolbar_click)
                popup.assert_called_once_with(toolbar_click, None)

            smooth = SimpleNamespace(direction=self.Gdk.ScrollDirection.SMOOTH,
                                     get_scroll_deltas=lambda: (True, 0.0, 0.6))
            view.scroll(view.area, smooth)
            self.assertEqual(view.page, 0)
            view.scroll(view.area, smooth)
            self.assertEqual(view.page, 1)
            view.change_page(-1)
            application.activate_action("toggle", None)
            yield lambda: not view.fade.pending
            self.assertTrue(view.get_visible())
            self.assertEqual(view.area.get_opacity(), 0.0)
            application.activate_action("toggle", None)
            yield lambda: not view.fade.pending
            self.assertTrue(view.get_visible())
            application.open_directory()
            self.open_uri.assert_called_once()
            self.assertEqual(self.open_uri.call_args.args[0], self.desktop.as_uri())

            scans = application.scan_count
            watched = self.desktop / "zz-watched.txt"
            watched.write_text("created while the GTK loop is running\n")
            yield lambda: str(watched) in application.by_path and application.scan_count > scans
            self.assertEqual(len(application.entries), capacity + 4)
            self.assertEqual(view.rects[key], target, "directory refresh must preserve dragged positions")
            self.launch.assert_not_called()
            view.close()

        self.run_preview(cfg, first_run)

        def second_run(application):
            yield lambda: self.ready(application)
            view = application.views[0]
            self.assertEqual(application.positions, saved["positions"])
            layout = saved["positions"][f"{view.monitor_key}:0"]
            for key, cell in layout.items():
                if key in view.rects and cell[0] < view.columns and cell[1] < view.rows:
                    x, y, _, _ = view.rects[key]
                    self.assertEqual((x, y), (cfg.margin + cell[0] * cfg.cell_width,
                                              cfg.margin + cell[1] * cfg.cell_height))
            self.launch.assert_not_called()
            view.close()

        self.run_preview(cfg, second_run)

    def test_multi_selection_marquee_group_drag_and_overview_blur(self):
        cfg = self.Config()
        for index in range(2, 4):
            (self.desktop / f"item-{index:04d}.txt").write_text("selection fixture\n")
        control = self.Gdk.ModifierType.CONTROL_MASK
        shift = self.Gdk.ModifierType.SHIFT_MASK

        def scenario(application):
            yield lambda: self.ready(application)
            view = application.views[0]
            self.assertGreaterEqual(view.rows, 4, "test display must fit four rows")
            self.assertGreaterEqual(view.columns, 2)
            keys = list(view.rects)
            self.assertEqual(len(keys), 4)
            first, second, third, fourth = keys

            def click(key, state=0):
                point = self.center(view.rects[key])
                view.button_press(view.area, self.event(point, state=state))
                view.button_release(view.area, self.event(point, state=state,
                                                         kind=self.Gdk.EventType.BUTTON_RELEASE))

            click(first)
            self.assertEqual(view.selection, {first})
            click(third, control)
            self.assertEqual(view.selection, {first, third})
            click(first, control)
            self.assertEqual(view.selection, {third})
            click(first)
            click(third, shift)
            self.assertEqual(view.selection, {first, second, third})

            # Start on empty space right of column one, then drag up and left.
            # The box intersects precisely the first two rows of that column.
            x, y, width, height = view.rects[first]
            box_start = (x + width + 1, y + 2 * height - 1)
            box_end = (x - 1, y - 1)
            self.assertIsNone(view.hit(*box_start))

            def marquee(state=0):
                view.button_press(view.area, self.event(box_start, state=state))
                view.motion(view.area, self.event(box_end, state=state))
                self.assertIsNotNone(view.marquee)
                self.assertLess(view.marquee[2], 0)
                self.assertLess(view.marquee[3], 0)
                view.button_release(view.area, self.event(box_end, state=state,
                                                         kind=self.Gdk.EventType.BUTTON_RELEASE))
                self.assertIsNone(view.marquee)

            click(fourth)
            marquee(control)
            self.assertEqual(view.selection, {first, second, fourth})
            marquee()
            self.assertEqual(view.selection, {first, second})

            before = dict(view.rects)
            origin = self.center(before[first])
            destination = (origin[0] + cfg.cell_width, origin[1] + cfg.cell_height)
            view.button_press(view.area, self.event(origin))
            self.assertEqual(view.selection, {first, second}, "press preserves a selected group")
            view.motion(view.area, self.event(destination))
            self.assertTrue(view.dragging)
            view.button_release(view.area, self.event(destination, kind=self.Gdk.EventType.BUTTON_RELEASE))
            self.assertEqual(view.selection, {first, second})
            for key in (first, second):
                bx, by, bw, bh = before[key]
                self.assertEqual(view.rects[key], (bx + cfg.cell_width, by + cfg.cell_height, bw, bh))
            self.assertEqual(view.rects[third], before[third])
            self.assertEqual(view.rects[fourth], before[fourth])
            original_delta = (before[second][0] - before[first][0], before[second][1] - before[first][1])
            self.assertEqual((view.rects[second][0] - view.rects[first][0],
                              view.rects[second][1] - view.rects[first][1]), original_delta)
            stored = json.loads(self.state.read_text())["positions"][f"{view.monitor_key}:0"]
            self.assertEqual(stored[first], [1, 1])
            self.assertEqual(stored[second], [1, 2])
            self.launch.assert_not_called()

            # A click without motion collapses a group only on release.
            origin = self.center(view.rects[first])
            view.button_press(view.area, self.event(origin))
            self.assertEqual(view.selection, {first, second})
            view.button_release(view.area, self.event(origin, kind=self.Gdk.EventType.BUTTON_RELEASE))
            self.assertEqual(view.selection, {first})
            self.assertTrue(view.key_press(view, SimpleNamespace(state=control, keyval=self.Gdk.KEY_a)))
            self.assertEqual(view.selection, set(view.rects))
            self.assertTrue(view.key_press(view, SimpleNamespace(state=0, keyval=self.Gdk.KEY_Escape)))
            self.assertEqual(view.selection, set())

            application.overview_changed(False)
            sharp = self.render(view)
            # Opening overview cancels a gesture without changing the underlying selection.
            view.button_press(view.area, self.event((1, 1)))
            view.motion(view.area, self.event((12, 12)))
            self.assertIsNotNone(view.marquee)
            application.overview_changed(True)
            self.assertTrue(application.overview_active)
            self.assertIsNone(view.press)
            self.assertIsNone(view.marquee)
            self.assertFalse(view.dragging)
            cached = view.blurred_surface()
            self.assertIs(view.blurred_surface(), cached, "overview redraws reuse the blur")
            blurred = self.render(view)
            self.assertNotEqual(blurred, sharp, "overview must visibly blur pixels")
            self.assertIs(view.blurred_surface(), cached)
            self.assertFalse(view.button_press(view.area, self.event(self.center(view.rects[first]))))
            self.assertFalse(view.key_press(view, SimpleNamespace(state=control, keyval=self.Gdk.KEY_a)))
            self.assertEqual(view.selection, set())
            application.overview_changed(False)
            self.assertIsNone(view.blur_cache)
            self.assertEqual(self.render(view), sharp, "leaving overview restores the original sharp pixels")
            application.overview_changed(True)
            self.assertIsNot(view.blurred_surface(), cached, "a new overview rebuilds the cache")
            application.overview_changed(False)
            self.launch.assert_not_called()
            view.close()

        self.run_preview(cfg, scenario)



    def test_inline_rename_keeps_position_and_never_overwrites(self):
        cfg = self.Config()
        launcher = self.desktop / 'fixture.desktop'
        launcher.write_text('[Desktop Entry]\nType=Application\nName=Original\nName[zh_CN]=原名\nExec=/usr/bin/true\n')
        launcher.chmod(0o755)
        def scenario(application):
            yield lambda: self.ready(application)
            view = application.views[0]
            original = self.desktop / 'item-0000.txt'
            key = str(original)
            view.selection = {key}
            menu = view.make_menu(key)
            self.menu_item(menu, _tr('重命名…')).activate()
            menu.destroy()
            yield lambda: view.rename_input is not None and view.rename_input.get_mapped() and view.rename_editor.get_allocated_width() > 10
            self.assertEqual(len(application.get_windows()), 1)
            self.assertEqual(view.rename_input.get_selection_bounds(), (0, len(original.stem)))
            rect = view.rects[key]
            box = view.rename_editor.get_allocation()
            self.assertEqual(view.rename_editor.translate_coordinates(view.area, 0, 0), (rect[0]+5, rect[1]+cfg.icon_size+14))
            self.assertLessEqual(box.width, cfg.cell_width)
            if destination := os.environ.get('ADWS_TEST_RENAME_SCREENSHOT'):
                surface = self.cairo.ImageSurface(self.cairo.FORMAT_ARGB32, view.get_allocated_width(), view.get_allocated_height())
                self.Gtk.Widget.draw(view, self.cairo.Context(surface))
                surface.write_to_png(destination)
            slot = f'{view.monitor_key}:{view.page}'
            position = [(rect[0]-cfg.margin)//cfg.cell_width, (rect[1]-cfg.margin)//cfg.cell_height]
            application.positions[slot] = {key: position}
            view.rename_input.set_text('重命名 文档.txt')
            view.rename_input.emit('activate')
            target = self.desktop / '重命名 文档.txt'
            self.assertIsNone(view.rename_input)
            self.assertFalse(original.exists())
            self.assertEqual(target.read_text(), 'GUI fixture\n')
            self.assertEqual(application.positions[slot][str(target)], position)
            self.assertEqual(view.rects[str(target)], rect)
            self.assertIn(str(target), view.selection)
            view.rename_entry(str(target))
            view.rename_input.set_text('item-0001.txt')
            self.assertFalse(view.commit_rename())
            self.assertTrue(view.rename_error_label.get_visible())
            self.assertTrue(target.exists())
            dangling = self.desktop / 'dangling'
            dangling.symlink_to(self.desktop / 'missing')
            view.rename_input.set_text('dangling')
            self.assertFalse(view.commit_rename())
            self.assertTrue(dangling.is_symlink())
            view.rename_input.set_text('../outside')
            self.assertFalse(view.commit_rename())
            view.cancel_rename()
            view.rename_entry(str(launcher))
            view.rename_input.set_text('新启动器')
            self.assertTrue(view.commit_rename())
            self.assertEqual(application.by_path[str(launcher)].name, '新启动器')
            self.assertIn('Exec=/usr/bin/true', launcher.read_text())
            self.assertEqual(launcher.stat().st_mode & 0o777, 0o755)
            view.close()
        self.run_preview(cfg, scenario)

    def test_inline_rename_keyboard_focus_and_cancellation(self):
        def scenario(application):
            yield lambda: self.ready(application)
            view = application.views[0]
            original = self.desktop / 'item-0000.txt'
            key = str(original)
            view.selection = {key}
            self.assertTrue(view.key_press(view, SimpleNamespace(keyval=self.Gdk.KEY_F2, state=0)))
            yield lambda: view.rename_input is not None and view.rename_input.get_mapped() and view.rename_editor.get_allocated_width() > 10
            field = view.rename_input
            field.set_text('cancelled.txt')
            # Desktop Ctrl+A / Delete must not select or delete desktop files while editing.
            self.assertFalse(view.key_press(view, SimpleNamespace(keyval=self.Gdk.KEY_Delete,state=0)))
            self.assertFalse(view.key_press(view, SimpleNamespace(keyval=self.Gdk.KEY_a,state=self.Gdk.ModifierType.CONTROL_MASK)))
            escape = self.Gdk.Event.new(self.Gdk.EventType.KEY_PRESS)
            escape.keyval = self.Gdk.KEY_Escape
            field.emit('key-press-event', escape)
            self.assertIsNone(view.rename_input)
            self.assertTrue(original.exists())
            self.assertFalse((self.desktop/'cancelled.txt').exists())
            view.rename_entry(key)
            yield lambda: view.rename_input is not None and view.rename_input.get_mapped() and view.rename_editor.get_allocated_width() > 10
            view.rename_input.set_text('outside-click.txt')
            view.button_press(view.area, self.event((900,500)))
            self.assertIsNone(view.rename_input)
            target = self.desktop/'outside-click.txt'
            self.assertTrue(target.exists())
            view.rename_entry(str(target))
            yield lambda: view.rename_input is not None and view.rename_input.get_mapped() and view.rename_editor.get_allocated_width() > 10
            view.rename_input.set_text('lost-focus.txt')
            view.rename_input.emit('activate')
            yield lambda: view.rename_input is None
            self.assertTrue((self.desktop/'lost-focus.txt').exists())
            view.rename_entry(str(self.desktop/'lost-focus.txt'))
            view.rename_input.set_text('not-saved-on-hide.txt')
            application.set_hidden(True)
            self.assertIsNone(view.rename_input)
            self.assertFalse((self.desktop/'not-saved-on-hide.txt').exists())
            view.close()
        self.run_preview(self.Config(), scenario)

    def test_inline_rename_ime_focus_and_layout_settle(self):
        def scenario(application):
            yield lambda: self.ready(application)
            view = application.views[0]
            original = self.desktop / 'item-0000.txt'
            view.rename_entry(str(original))
            yield lambda: view.rename_input is not None and view.rename_input.get_allocated_width() > 10
            field = view.rename_input
            # Repeated composition and candidate focus events must neither rename
            # files nor destroy/recreate the input context.
            for _ in range(20):
                field.emit('preedit-changed', 'zhongwen')
                field.emit('focus-out-event', self.Gdk.Event.new(self.Gdk.EventType.FOCUS_CHANGE))
                self.assertFalse(view.commit_rename())
                self.assertIs(view.rename_input, field)
                self.assertTrue(original.exists())
                field.emit('preedit-changed', '')
            with patch.object(view, 'relayout', wraps=view.relayout) as layout:
                deadline = self.GLib.get_monotonic_time() + 250000
                yield lambda: self.GLib.get_monotonic_time() >= deadline
                self.assertLessEqual(layout.call_count, 2, 'editor allocation must settle instead of continuously resizing')
            self.assertIs(view.rename_input, field)
            field.set_text('中文文档.txt')
            field.emit('activate')
            self.assertTrue((self.desktop/'中文文档.txt').exists())
            self.assertIsNone(view.rename_input)
            view.close()
        self.run_preview(self.Config(), scenario)

    def test_inline_create_defaults_cancel_validation_and_collision(self):
        def scenario(application):
            yield lambda: self.ready(application)
            view = application.views[0]
            for kind, name, caption in [('text','text.txt','文本文档'), ('markdown','markdown.md','Markdown 文档'), ('folder','folder','文件夹')]:
                menu = view.make_menu(None)
                self.menu_item(menu, _tr('新建'), _tr(caption)).activate()
                menu.destroy()
                yield lambda: view.rename_input is not None and view.rename_input.get_allocated_width() > 10
                self.assertEqual(view.rename_input.get_text(), name)
                self.assertEqual(len(application.get_windows()), 1)
                self.assertFalse((self.desktop/name).exists())
                self.assertIn(view.rename_key, view.rects)
                self.assertEqual(view.rename_input.get_selection_bounds(), (0,len(Path(name).stem if kind != 'folder' else name)))
                for bad in ['', '.', '..', '../outside', 'a/b']:
                    view.rename_input.set_text(bad)
                    self.assertFalse(view.commit_rename())
                    self.assertTrue(view.rename_error_label.get_visible())
                view.rename_input.set_text(name)
                self.assertTrue(view.commit_rename())
                self.assertIsNone(view.new_item)
                if kind == 'folder':
                    self.assertTrue((self.desktop/name).is_dir())
                elif kind == 'text':
                    self.assertEqual((self.desktop/name).read_text(), '')
                else:
                    self.assertEqual((self.desktop/name).read_text(), _tr('# 新文档\n'))
            view.create_item('text','text.txt')
            self.assertEqual(view.rename_input.get_text(),'text (2).txt')
            view.rename_input.set_text('text.txt')
            self.assertFalse(view.commit_rename())
            view.rename_input.set_text('appeared.txt')
            (self.desktop/'appeared.txt').write_text('another process')
            self.assertFalse(view.commit_rename())
            self.assertEqual((self.desktop/'appeared.txt').read_text(),'another process')
            (self.desktop/'dangling').symlink_to(self.desktop/'missing')
            view.rename_input.set_text('dangling')
            self.assertFalse(view.commit_rename())
            self.assertFalse((self.desktop/'missing').exists())
            view.cancel_rename()
            self.assertFalse((self.desktop/'text (2).txt').exists())
            self.assertFalse(list(self.desktop.glob('.adws-draft-*')))
            view.close()
        self.run_preview(self.Config(), scenario)

    def test_inline_create_full_page_refresh_and_escape(self):
        cfg = self.Config()
        def scenario(application):
            yield lambda: self.ready(application)
            view = application.views[0]
            capacity = view.columns * view.rows
            for index in range(capacity - len(application.entries)):
                (self.desktop/f'filler-{index:03d}.txt').touch()
            application.refresh()
            self.assertEqual(view.pages(),1)
            view.create_item('folder','folder')
            self.assertEqual(view.page,1)
            yield lambda: view.rename_input is not None and view.rename_input.get_allocated_width() > 10
            editor = view.rename_input
            application.refresh()
            self.assertIs(view.rename_input, editor)
            escape = self.Gdk.Event.new(self.Gdk.EventType.KEY_PRESS)
            escape.keyval = self.Gdk.KEY_Escape
            editor.emit('key-press-event',escape)
            self.assertIsNone(view.new_item)
            self.assertEqual(view.page,0)
            self.assertFalse((self.desktop/'folder').exists())
            view.create_item('folder','folder')
            view.rename_input.set_text('中文文件夹')
            self.assertTrue(view.commit_rename())
            self.assertTrue((self.desktop/'中文文件夹').is_dir())
            self.assertIn(str(self.desktop/'中文文件夹'),view.selection)
            self.assertIn(str(self.desktop/'中文文件夹'),view.rects)
            view.close()
        self.run_preview(cfg, scenario)

    def test_startup_initializes_missing_desktop(self):
        import shutil
        shutil.rmtree(self.desktop)
        def scenario(application):
            yield lambda: bool(application.views and application.views[0].get_mapped())
            self.assertTrue(self.desktop.is_dir())
            self.assertEqual(application.entries, [])
            application.views[0].close()
        self.run_preview(self.Config(), scenario)

    def test_terminal_and_confirmed_exit_menu(self):
        def scenario(application):
            yield lambda: self.ready(application)
            view = application.views[0]
            menu = view.make_menu(None)
            items = {item.get_label(): item for item in menu.get_children()
                     if not isinstance(item, self.Gtk.SeparatorMenuItem)}
            with patch.object(application, "open_terminal") as terminal:
                # Rebuild so the callback binds to the test double.
                menu.destroy()
                menu = view.make_menu(None)
                items = {item.get_label(): item for item in menu.get_children()
                         if not isinstance(item, self.Gtk.SeparatorMenuItem)}
                with self.assertLogs("desktop-layer", level="INFO") as logs:
                    items[_tr('打开终端')].activate()
                self.assertTrue(any((_tr('菜单操作：%s') % _tr('打开终端')) in line for line in logs.output))
                terminal.assert_called_once()
            exit_item = items[_tr('退出桌面环境')]
            self.module.apply_menu_palette(menu, self.Config())
            self.assertTrue(exit_item.get_style_context().has_class("desktop-exit"))
            with patch.object(application, "quit") as quit_app:
                exit_item.activate()
                quit_app.assert_not_called()
                dialog = view.exit_dialog
                self.assertIsNotNone(dialog)
                self.assertIn(('不会退出 Niri' if chinese() else 'does not log out of Niri'), dialog.get_property("secondary-text"))
                entries = [w for w in dialog.get_content_area().get_children() if isinstance(w, self.Gtk.Entry)]
                import shlex
                command = shlex.split(entries[0].get_text())
                self.assertEqual(command[1:], ["desktop", "--start"])
                import shutil
                self.assertTrue(shutil.which(command[0]))
                dialog.response(self.Gtk.ResponseType.CANCEL)
                quit_app.assert_not_called()
                self.assertIsNone(view.exit_dialog)
                exit_item.activate()
                view.exit_dialog.response(self.Gtk.ResponseType.DELETE_EVENT)
                quit_app.assert_not_called()
                exit_item.activate()
                view.exit_dialog.response(self.Gtk.ResponseType.ACCEPT)
                quit_app.assert_called_once()
            menu.destroy()
            view.close()
        self.run_preview(self.Config(), scenario)

    def test_hidden_icons_keep_desktop_menu_available(self):
        from desktop_layer.visibility import MarkerVisibility
        marker = self.root / "taskbar-hidden"
        def scenario(application):
            yield lambda: self.ready(application)
            view = application.views[0]
            application.taskbar_watcher = MarkerVisibility(marker, application.set_hidden).start()
            self.assertFalse(application.hidden)
            marker.touch()
            yield lambda: application.hidden and not view.fade.pending
            application.taskbar_watcher.sync()
            self.assertTrue(application.hidden)
            marker.unlink()
            yield lambda: not application.hidden and view.get_mapped() and not view.fade.pending
            self.assertTrue(view.rects)
            application.set_hidden(True)
            self.assertTrue(view.get_mapped(), "fade-out must keep drawing until finished")
            self.assertTrue(view.area.get_sensitive())
            yield lambda: 0.1 < view.area.get_opacity() < 0.9
            opacity = view.area.get_opacity()
            application.set_hidden(False)
            self.assertAlmostEqual(view.area.get_opacity(), opacity, places=2)
            yield lambda: not view.fade.pending
            self.assertTrue(view.get_mapped())
            self.assertEqual(view.area.get_opacity(), 1.0)
            application.set_hidden(True)
            yield lambda: not view.fade.pending
            self.assertTrue(view.get_mapped())
            self.assertEqual(view.area.get_opacity(), 0.0)
            menu = view.make_menu(next(iter(view.rects)))
            labels = [child.get_label() for child in menu.get_children() if not isinstance(child, self.Gtk.SeparatorMenuItem)]
            for label in ('显示桌面图标','显示桌面小组件','打开终端','打开桌面文件夹','退出桌面环境'):
                self.assertIn(_tr(label), labels)
            checks={child.get_label():child for child in menu.get_children() if isinstance(child,self.Gtk.CheckMenuItem)}
            self.assertFalse(checks[_tr('显示桌面图标')].get_active())
            checks[_tr('显示桌面小组件')].set_active(False)
            self.assertTrue(application.hidden and application.widgets_hidden)
            application.activate_action('toggle-widgets',None)
            self.assertTrue(application.hidden)
            self.assertFalse(application.widgets_hidden)
            self.assertTrue(any(isinstance(child.get_child(),self.Gtk.Box) and any(isinstance(w,self.Gtk.Label) and w.get_text()==_tr('桌面小组件…') for w in child.get_child().get_children()) for child in menu.get_children() if isinstance(child,self.Gtk.MenuItem)))
            menu.destroy()
            with patch.object(view, "popup") as popup:
                event = SimpleNamespace(button=3, x=20, y=20)
                self.assertTrue(view.button_press(view.area, event))
                popup.assert_called_once_with(event, None)
                event.button = 1
                self.assertFalse(view.button_press(view.area, event))
            with patch("subprocess.Popen") as launch_terminal:
                application.open_terminal()
                self.assertEqual(launch_terminal.call_args.kwargs["cwd"], self.desktop)
            self.assertEqual(view.fade.pending, 0)
            application.set_hidden(False)
            yield lambda: 0.1 < view.area.get_opacity() < 0.9
            application.set_hidden(True)
            yield lambda: not view.fade.pending
            application.set_hidden(False)
            yield lambda: not view.fade.pending
            view.close()
        self.run_preview(self.Config(), scenario)


    def test_desktop_widgets_move_lock_resize_note_and_visibility(self):
        tools=Path(__file__).resolve().parents[3]/'tools'
        if str(tools) not in sys.path:sys.path.insert(0,str(tools))
        import adws_desktop_widgets_model as widgets
        data=widgets.add({}, {'key':'builtin:clock'})
        data=widgets.add(data, {'key':'builtin:note'})
        data['instances'][0].pop('x_percent');data['instances'][0].pop('y_percent')
        data['instances'][0].update(x=400,y=20)
        data['instances'][1].pop('x_percent');data['instances'][1].pop('y_percent')
        data['instances'][1].update(x=400,y=290)
        self.state.parent.mkdir(parents=True,exist_ok=True)
        path=self.state.with_name('desktop-widgets.json');widgets.save(data,path)
        def scenario(application):
            yield lambda: bool(application.views and hasattr(application.views[0],'desktop_widgets'))
            view=application.views[0];layer=view.desktop_widgets
            yield lambda: len(layer.cards)==2 and layer.fixed.get_mapped()
            clock=layer.cards[data['instances'][0]['instance']]
            note=layer.cards[data['instances'][1]['instance']]
            self.assertTrue(clock.primary.get_text())
            event=SimpleNamespace(button=1,x_root=100.,y_root=100.)
            self.assertTrue(clock.press(None,event,False))
            clock.motion(None,SimpleNamespace(x_root=150.,y_root=130.));clock.release(None,event)
            self.assertEqual(widgets.geometry(widgets.load(path)['instances'][0],view.area.get_allocated_width(),view.area.get_allocated_height())[0],450)
            clock.press(None,event,True)
            clock.motion(None,SimpleNamespace(x_root=160.,y_root=150.));clock.release(None,event)
            self.assertEqual(widgets.load(path)['instances'][0]['width'],460)
            application.widget_manager.edit(clock.row['instance'],locked=True)
            self.assertFalse(clock.press(None,event,False))
            note.note.grab_focus()
            self.assertFalse(view.key_press(view,SimpleNamespace(keyval=self.Gdk.KEY_a,state=self.Gdk.ModifierType.CONTROL_MASK)))
            self.assertFalse(view.selection,'note shortcut must not select desktop files')
            note.note.get_buffer().set_text('saved desktop note 你好')
            note.save_note()
            self.assertEqual(widgets.load(path)['instances'][1]['settings']['text'],'saved desktop note 你好')
            application.set_hidden(True)
            self.assertFalse(layer.fixed.get_visible());self.assertEqual(clock.source,0)
            application.set_hidden(False)
            yield lambda: layer.fixed.get_mapped() and clock.source!=0
            application.overview_changed(True);self.assertFalse(layer.fixed.get_visible())
            application.overview_changed(False)
            yield lambda: layer.fixed.get_mapped()
            application.widget_manager.remove(note.row['instance'])
            self.assertEqual(len(layer.cards),1)
            view.close()
        self.run_preview(self.Config(),scenario)

    def test_widget_css_is_scoped_and_survives_duplication(self):
        tools=Path(__file__).resolve().parents[3]/'tools'
        if str(tools) not in sys.path:sys.path.insert(0,str(tools))
        import adws_desktop_widgets_model as widgets
        data=widgets.add({}, {'key':'builtin:clock'})
        data=widgets.add(data, {'key':'builtin:clock'})
        data['instances'][0]['css']='.desktop-clock { color: rgb(255, 0, 0); }'
        self.state.parent.mkdir(parents=True,exist_ok=True)
        path=self.state.with_name('desktop-widgets.json');widgets.save(data,path)
        def scenario(application):
            yield lambda: bool(application.views and hasattr(application.views[0],'desktop_widgets'))
            layer=application.views[0].desktop_widgets
            yield lambda:len(layer.cards)==2 and layer.fixed.get_mapped()
            first=layer.cards[data['instances'][0]['instance']];second=layer.cards[data['instances'][1]['instance']]
            color=first.primary.get_style_context().get_color(self.Gtk.StateFlags.NORMAL)
            self.assertAlmostEqual(color.red,1);self.assertAlmostEqual(color.green,0)
            other=second.primary.get_style_context().get_color(self.Gtk.StateFlags.NORMAL)
            self.assertGreater(other.green,.1)
            first.duplicate()
            yield lambda:len(layer.cards)==3
            self.assertEqual(widgets.load(path)['instances'][-1]['css'],first.row['css'])
            application.widget_manager.edit(second.row['instance'],css='invalid css {{{')
            yield lambda:len(layer.cards)==3
            self.assertFalse(application.widget_manager.closed)
            application.views[0].close()
        self.run_preview(self.Config(),scenario)

    def test_repeated_desktop_widgets_release_cards_and_timers(self):
        tools=Path(__file__).resolve().parents[3]/'tools'
        if str(tools) not in sys.path:sys.path.insert(0,str(tools))
        import gc
        import weakref
        import adws_desktop_widgets_model as widgets
        def scenario(application):
            yield lambda: bool(application.views and hasattr(application.views[0],'desktop_widgets'))
            view=application.views[0];layer=view.desktop_widgets;manager=application.widget_manager
            refs=[]
            for _ in range(30):
                manager.data=widgets.add(manager.data,{'key':'builtin:clock'})
                manager.persist();layer.render()
                yield lambda: bool(layer.cards)
                card=next(iter(layer.cards.values()));refs.append(weakref.ref(card))
                manager.remove(card.row['instance']);self.assertEqual(card.source,0)
                del card
            gc.collect()
            self.assertTrue(all(ref() is None for ref in refs),'removed desktop cards survived GC')
            view.close()
        self.run_preview(self.Config(),scenario)

    def test_desktop_plugin_uses_watchdog_and_stops_when_removed(self):
        tools=Path(__file__).resolve().parents[3]/'tools'
        if str(tools) not in sys.path:sys.path.insert(0,str(tools))
        import adws_desktop_widgets_model as widgets
        import adws_plugin as mplg
        from adws_components import components
        import zipfile
        manifest={'id':'org.adws.desktopfixture','name':'Fixture','version':'1.0.0',
                  'components':[{'id':'lyrics','target':'desktop','name':'Desktop lyrics','entry':'main.py','renderer':'panel.rows-v1'}]}
        package=self.root/'fixture.mplg'
        failing=self.root/'fail';failing.write_text('fail once')
        with zipfile.ZipFile(package,'w') as z:
            z.writestr('plugin.json',json.dumps(manifest))
            z.writestr('main.py',f"import json,time\nfrom pathlib import Path\nif Path({str(failing)!r}).exists():raise SystemExit(7)\nprint(json.dumps({{'primary':'fixture lyric','secondary':'translation'}}),flush=True)\ntime.sleep(60)\n")
        definition={'key':'org.adws.desktopfixture.lyrics','name':'Desktop lyrics','kind':'plugin','file':package,'repeatable':True,'manifest':components(manifest,'desktop')[0]}
        data=widgets.add({},definition)
        self.state.parent.mkdir(parents=True,exist_ok=True);path=self.state.with_name('desktop-widgets.json');widgets.save(data,path)
        runtime=self.root/'runtime';runtime.mkdir(mode=0o700)
        def scenario(application):
            yield lambda: bool(application.views and hasattr(application.views[0],'desktop_widgets'))
            view=application.views[0];layer=view.desktop_widgets
            yield lambda: len(layer.cards)==1
            card=next(iter(layer.cards.values()))
            yield lambda: card.box.get_style_context().has_class('desktop-error')
            from adws_plugin_watchdog import health
            yield lambda: (health(card.row['instance']) or {}).get('state')=='failed'
            failing.unlink();card.restart()
            yield lambda: card.primary.get_text()=='fixture lyric'
            self.assertFalse(card.box.get_style_context().has_class('desktop-error'))
            stream=card.stream
            self.assertEqual(card.secondary.get_text(),'translation')
            application.widget_manager.remove(card.row['instance'])
            yield lambda: not stream.thread.is_alive()
            self.assertIsNotNone(stream.process.poll())
            self.assertEqual(card.source,0)
            view.close()
        with patch.object(widgets,'catalog',return_value=[definition]),patch.dict(os.environ,{'XDG_RUNTIME_DIR':str(runtime),'XDG_CACHE_HOME':str(self.root/'cache')}):
            self.run_preview(self.Config(),scenario)


    def test_real_netease_desktop_lyrics_with_isolated_mpris(self):
        import importlib.util
        import time
        tools=Path(__file__).resolve().parents[3]/'tools'
        if str(tools) not in sys.path:sys.path.insert(0,str(tools))
        import adws_plugin as mplg
        import adws_plugin_api as api
        import adws_desktop_widgets_model as widgets
        from adws_components import components
        root=tools.parent
        package=mplg.build_package(root/'plugins/netease-lyrics',self.root/'lyrics.mplg')
        manifest=components(mplg.load_manifest(package),'desktop')[0]
        definition={'key':manifest['id'],'name':manifest['name'],'kind':'plugin','file':package,'manifest':manifest,'repeatable':True}
        runtime=self.root/'runtime';runtime.mkdir(mode=0o700)
        cache=self.root/'cache';cache_folder=cache/'adws/netease-lyrics-v2';cache_folder.mkdir(parents=True)
        spec=importlib.util.spec_from_file_location('desktop_test_lyrics',root/'plugins/netease-lyrics/main.py')
        lyrics=importlib.util.module_from_spec(spec);spec.loader.exec_module(lyrics)
        lyrics.SETTINGS=api.settings(manifest,{})
        track={'title':'ADWS desktop fixture','artists':['ADWS'],'album':'Tests','duration':180}
        (cache_folder/(lyrics.track_key(track)+'.json')).write_text(json.dumps({'state':'ready','expires':time.time()+3600,'lines':[[0,'Previous fixture'],[3,'君の夢'],[8,'Next fixture']],'translation':[[3,'桌面双语歌词验证']],'romanization':[[3,'kimi no yume']]}))
        data=widgets.add({},definition);data=widgets.add(data,definition);self.state.parent.mkdir(parents=True,exist_ok=True)
        data['instances'][0].pop('x_percent');data['instances'][0].pop('y_percent')
        data['instances'][0].update(x=400,y=20,height=216,settings={'show_romanization':True,'show_furigana':True})
        data['instances'][1].pop('x_percent');data['instances'][1].pop('y_percent')
        data['instances'][1].update(x=400,y=400,height=330)
        widgets.save(data,self.state.with_name('desktop-widgets.json'))
        state={'status':'Playing'};actions=[]
        bus=self.Gio.bus_get_sync(self.Gio.BusType.SESSION,None)
        xml='<node><interface name="org.mpris.MediaPlayer2.Player"><method name="Pause"/><method name="Play"/><method name="Previous"/><method name="Next"/><method name="SetPosition"><arg type="o" direction="in"/><arg type="x" direction="in"/></method><property name="CanSeek" type="b" access="read"/><property name="Metadata" type="a{sv}" access="read"/><property name="Position" type="x" access="read"/><property name="PlaybackStatus" type="s" access="read"/></interface></node>'
        iface=self.Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0]
        meta={'xesam:title':self.GLib.Variant('s',track['title']),'xesam:artist':self.GLib.Variant('as',track['artists']),'xesam:album':self.GLib.Variant('s',track['album']),'xesam:url':self.GLib.Variant('s','https://music.163.com/song?id=1'),'mpris:trackid':self.GLib.Variant('o','/track/fixture'),'mpris:length':self.GLib.Variant('x',180000000)}
        def method(connection,sender,path,interface,name,args,invocation):
            actions.append(name)
            if name=='Pause':state['status']='Paused'
            if name=='SetPosition':state['seek']=args.unpack();state['position']=state['seek'][1]
            invocation.return_value(self.GLib.Variant('()',()))
        def property_value(connection,sender,path,interface,name):
            if name=='CanSeek':return self.GLib.Variant('b',True)
            return self.GLib.Variant('a{sv}',meta) if name=='Metadata' else self.GLib.Variant('x',state.get('position',3000000)) if name=='Position' else self.GLib.Variant('s',state['status'])
        registration=bus.register_object('/org/mpris/MediaPlayer2',iface,method,property_value,None)
        owner=self.Gio.bus_own_name_on_connection(bus,'org.mpris.MediaPlayer2.firefox.adws_desktop_test',self.Gio.BusNameOwnerFlags.NONE,None,None)
        def scenario(application):
            yield lambda: bool(application.views and hasattr(application.views[0],'desktop_widgets'))
            view=application.views[0];layer=view.desktop_widgets
            yield lambda: bool(layer.cards)
            card=next(iter(layer.cards.values()))
            yield lambda: card.primary.get_text()=='君の夢'
            self.assertEqual(card.secondary.get_text(),'桌面双语歌词验证')
            sibling=list(layer.cards.values())[1]
            yield lambda:sibling.primary.get_text()=='君の夢'
            self.assertNotEqual(card.stream.process.pid,sibling.stream.process.pid)
            self.assertEqual(card.previous.get_text(),'Previous fixture')
            self.assertEqual(card.following.get_text(),'Next fixture')
            self.assertEqual(card.romanization.get_text(),'kimi no yume')
            self.assertFalse(sibling.romanization.get_visible())
            self.assertAlmostEqual(card.media.progress.get_value(),3/180)
            self.assertTrue(card.media.row.get_visible());self.assertTrue(card.media.progress.get_mapped())
            self.assertTrue(card.media.elapsed.get_mapped())
            self.assertEqual(card.media.elapsed.get_text(),'0:03')
            self.assertTrue(card.ruby.get_visible());self.assertFalse(card.primary.get_visible())
            self.assertTrue(sibling.primary.get_visible());self.assertFalse(sibling.ruby.get_visible())
            self.assertEqual(card.ruby_value,(('君','きみ'),('の',''),('夢','ゆめ')))
            first=card.ruby_tokens[0].get_children()
            self.assertEqual(first[0].get_text(),'きみ');self.assertEqual(first[1].get_text(),'君')
            self.assertLess(first[0].translate_coordinates(view,0,0)[1],first[1].translate_coordinates(view,0,0)[1])
            self.assertLessEqual(card.ruby.get_allocated_width(),card.box.get_allocated_width())
            # An indivisible reading wider than the available space falls back to plain text.
            card.reflow_ruby(8)
            self.assertTrue(card.primary.get_visible());self.assertFalse(card.ruby.get_visible())
            card.reflow_ruby(452)
            self.assertTrue(card.ruby.get_visible());self.assertFalse(card.primary.get_visible())
            self.assertEqual(card.content.get_children()[3],card.secondary)
            self.assertGreater(card.following.get_margin_top(),card.content.get_spacing())
            original_text=card.primary.get_text();original_runs=card.ruby_value
            card.primary.set_text('あ'*20);card.update_ruby([]);card.reflow_ruby(500)
            self.assertLess(card.fit_font_size,28);self.assertGreaterEqual(card.fit_font_size,card.fit_minimum)
            self.assertEqual(card.fit_rows,1)
            card.reflow_ruby(300)
            self.assertEqual(card.fit_font_size,card.fit_minimum);self.assertEqual(card.fit_rows,2)
            self.assertEqual(card.primary.get_justify(),self.Gtk.Justification.CENTER)
            repeated=(('君','きみ'),('の',''),('夢','ゆめ'),('を',''),('信','しん'),('じ',''),('て',''))*4
            card.primary.set_text(''.join(b for b,r in repeated))
            card.update_ruby([{'base':b,'reading':r} for b,r in repeated]);card.reflow_ruby(452)
            self.assertEqual(card.fit_rows,2);self.assertTrue(card.ruby.get_visible())
            for line in card.ruby.get_children():
                self.assertEqual(line.get_halign(),self.Gtk.Align.CENTER)
                self.assertLessEqual(line.get_preferred_width()[1],452)
            first_row=card.ruby.get_children()[0];card.reflow_ruby(452)
            self.assertIs(card.ruby.get_children()[0],first_row,'unchanged frames must reuse label widgets')
            card.primary.set_text(original_text)
            card.update_ruby([{'base':b,'reading':r} for b,r in original_runs])
            self.assertEqual(card.fit_font_size,28)

            def click(action):
                import subprocess
                button=card.control_buttons[action]
                x,y=button.translate_coordinates(view,button.get_allocated_width()//2,button.get_allocated_height()//2)
                origin=view.get_window().get_origin();x+=origin[-2];y+=origin[-1]
                subprocess.run(['xdotool','mousemove','--sync',str(x),str(y),'click','1'],check=True,timeout=3)
            # Real pointer drag sends exactly one SetPosition to the bound track.
            import subprocess
            scale=card.media.progress
            yield lambda:scale.get_sensitive() and card.following.get_allocated_height()>1
            footer_y=card.media.translate_coordinates(card.box,0,0)[1]
            following_y=card.following.translate_coordinates(card.box,0,0)[1]
            self.assertGreaterEqual(footer_y,following_y+card.following.get_allocated_height())
            sx,sy=scale.translate_coordinates(view,8,scale.get_allocated_height()//2)
            origin=view.get_window().get_origin();sx+=origin[-2];sy+=origin[-1]
            subprocess.run(['xdotool','mousemove','--sync',str(sx),str(sy),'mousedown','1',
                'mousemove','--sync',str(sx+scale.get_allocated_width()//2),str(sy),'mouseup','1'],check=True,timeout=3)
            yield lambda:'SetPosition' in actions and not card.control_busy
            self.assertEqual(actions.count('SetPosition'),1)
            self.assertEqual(state['seek'][0],'/track/fixture')
            self.assertGreater(state['seek'][1],30000000)
            self.assertLess(state['seek'][1],150000000)
            state['position']=3000000
            click('play-pause')
            yield lambda: 'Pause' in actions and not card.control_busy
            yield lambda: card.primary.get_text().startswith('Ⅱ ')
            self.assertEqual(card.media.timer,0)
            click('next')
            yield lambda: 'Next' in actions and not card.control_busy
            click('previous')
            yield lambda: 'Previous' in actions and not card.control_busy
            stream=card.stream
            application.widget_manager.remove(card.row['instance'])
            yield lambda: not stream.thread.is_alive()
            self.assertEqual(len(layer.cards),1)
            self.assertIsNone(sibling.stream.process.poll())
            sibling_stream=sibling.stream
            application.widget_manager.remove(sibling.row['instance'])
            yield lambda:not sibling_stream.thread.is_alive()
            view.close()
        try:
            with patch.object(widgets,'catalog',return_value=[definition]),patch.dict(os.environ,{'XDG_RUNTIME_DIR':str(runtime),'XDG_CACHE_HOME':str(cache)}):
                self.run_preview(self.Config(),scenario)
        finally:
            self.Gio.bus_unown_name(owner);bus.unregister_object(registration)

    def test_desktop_basic_pack_interaction_and_isolated_state(self):
        import time
        tools=Path(__file__).resolve().parents[3]/'tools'
        if str(tools) not in sys.path:sys.path.insert(0,str(tools))
        import adws_plugin as mplg
        import adws_desktop_widgets_model as widgets
        from adws_components import components
        root=tools.parent;package=mplg.build_package(root/'plugins/desktop-basic-pack',self.root/'basic.mplg')
        definitions=[{'key':m['id'],'name':m['name'],'kind':'plugin','file':package,'manifest':m,'repeatable':True} for m in components(mplg.load_manifest(package),'desktop')]
        data={};positions={'clock':(10,10),'timer':(420,10),'note':(840,10),'game2048':(10,350),'puzzle':(420,350),'photo':(870,350)}
        for definition in definitions:
            data=widgets.add(data,definition);row=data['instances'][-1];row.pop('x_percent');row.pop('y_percent');kind=definition['manifest']['componentId'];row['x'],row['y']=positions[kind]
        self.state.parent.mkdir(parents=True,exist_ok=True);widgets.save(data,self.state.with_name('desktop-widgets.json'))
        data['instances'][0]['settings']={'display':'analog','face':'minimal'}
        widgets.save(data,self.state.with_name('desktop-widgets.json'))
        cache=self.root/'cache';state=self.root/'plugin-state';runtime=self.root/'runtime';runtime.mkdir(mode=0o700)
        def scenario(application):
            yield lambda:bool(application.views and hasattr(application.views[0],'desktop_widgets'))
            view=application.views[0];layer=view.desktop_widgets
            yield lambda:len(layer.cards)==6 and all(card.interactive and card.interactive.shape for card in layer.cards.values())
            cards={c.definition['manifest']['componentId']:c for c in layer.cards.values()}
            yield lambda:'dial' in cards['clock'].interactive.widgets and cards['clock'].interactive.widgets['dial'].cached is not None
            timer=cards['timer'];ui=timer.interactive
            ui.widgets['toggle'].clicked()
            yield lambda:ui.widgets['status'].get_text() in ('正在计时','Running')
            ui.widgets['toggle'].clicked()
            yield lambda:ui.widgets['status'].get_text() in ('已暂停','Paused')
            board=cards['game2048'];board.box.grab_focus()
            import subprocess
            subprocess.run(['xdotool','key','Left','Up'],check=True,timeout=3)
            yield lambda:board.interactive.widgets['undo'].get_sensitive()
            # A real pointer click slides a neighboring image into the empty cell.
            puzzle=cards['puzzle']
            yield lambda:puzzle.interactive.widgets['image0'].pixbuf is not None
            def click(button):
                x,y=button.translate_coordinates(view,button.get_allocated_width()//2,button.get_allocated_height()//2)
                origin=view.get_window().get_origin();x+=origin[-2];y+=origin[-1]
                subprocess.run(['xdotool','mousemove','--sync',str(x),str(y),'click','1'],check=True,timeout=3)
            target=next(w for key,w in puzzle.interactive.widgets.items() if key.startswith('tile') and w.get_sensitive())
            click(target)
            yield lambda:puzzle.interactive.widgets['moves'].get_text().endswith('1')
            note=cards['note'];buffer=note.interactive.widgets['note'].get_buffer();buffer.set_text('独立便签 · 中文输入与保存')
            path=state/'adws/desktop-plugins/org.AkiACG-Community.desktopBasicPack'/(note.row['instance']+'.json')
            yield lambda:path.exists() and json.loads(path.read_text()).get('text')=='独立便签 · 中文输入与保存'
            photo=cards['photo']
            yield lambda:photo.interactive.widgets['photo'].pixbuf is not None
            self.assertEqual(len(puzzle.interactive.widgets['board'].get_children()),16)
            # Flush an edit immediately before unmapping/stopping the runner.
            buffer.set_text('关闭前最后一笔')
            stream=note.stream;note.stop()
            yield lambda:not stream.thread.is_alive()
            self.assertEqual(json.loads(path.read_text())['text'],'关闭前最后一笔')
            self.assertFalse(Path(stream.event_dir).exists())
            note.start()
            yield lambda:note.interactive.nodes['note']['value']=='关闭前最后一笔'
            streams=[c.stream for c in layer.cards.values()]
            for c in list(layer.cards.values()):application.widget_manager.remove(c.row['instance'])
            yield lambda:all(not stream.thread.is_alive() for stream in streams)
            self.assertTrue(all(not Path(stream.event_dir).exists() for stream in streams))
            view.close()
        with patch.object(widgets,'catalog',return_value=definitions),patch.dict(os.environ,{'XDG_STATE_HOME':str(state),'XDG_CACHE_HOME':str(cache),'XDG_RUNTIME_DIR':str(runtime)}):
            self.run_preview(self.Config(),scenario)


if __name__ == "__main__":
    unittest.main()

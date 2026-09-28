"""GTK3 / wlr-layer-shell desktop, with input restricted to visible icons."""
from __future__ import annotations
from .i18n import tr as _tr, prepare_gtk_language

import argparse
from dataclasses import replace
from datetime import datetime
import json
import logging
import math
import os
from pathlib import Path
import signal
import shutil
import sys
import time
import uuid
from urllib.parse import urlsplit

from .config import load_config, state_path, validate_config
from .selection import move_group, rectangle_hits
from .overview import OverviewWatcher
from .visibility import MarkerVisibility, WindowFade
from .model import (Entry, scan_desktop, desktop_directory, launch_entry, UntrustedLauncher,
                    atomic_save_json, arrange_grid, sort_entries, open_in_thunar,
                    file_manager_location)

TRACE = 5
logging.addLevelName(TRACE, "TRACE")
LOG = logging.getLogger("desktop-layer")


def logged_action(label):
    """Record requests and handler completion; external app success is not implied."""
    from functools import wraps
    def decorate(callback):
        @wraps(callback)
        def run(*args, **kwargs):
            LOG.info(_tr('操作请求：%s'), label)
            try:
                result = callback(*args, **kwargs)
            except Exception:
                LOG.exception(_tr('操作异常：%s'), label)
                raise
            LOG.debug(_tr('操作处理返回：%s'), label)
            return result
        return run
    return decorate

APP_ID = "io.github.akizuki.NiriDesktopLayer"


@logged_action(_tr('打开统一设置'))
def open_adws_config(tab: str) -> bool:
    """Try to open the unified ADWS-Config app; return False when unavailable."""
    import subprocess

    candidates = []
    root = Path(__file__).resolve().parents[3]
    if (root / "tools/adws-config.py").exists():
        candidates.append(str(root / "tools/adws-config.py"))
    candidates.append(str(Path.home() / ".local/bin/adws-config"))
    script = next((candidate for candidate in candidates if Path(candidate).exists()), None)
    if script is None:
        return False
    env = {key: value for key, value in os.environ.items() if key != "GDK_BACKEND"}
    try:
        subprocess.Popen([sys.executable, script, "--tab", tab], env=env, start_new_session=True)
        return True
    except OSError:
        return False


def palette_file_candidates() -> list[Path]:
    """配色来源：优先读当前 Waybar 使用的 matugen colors.css。"""
    return [
        Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "waybar/colors.css",
        Path(__file__).resolve().parents[2] / "config/waybar/colors.css",
    ]


def read_palette_colors() -> dict[str, str]:
    import re

    for candidate in palette_file_candidates():
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        colors = {
            name.strip(): value.strip()
            for name, value in re.findall(
                r"@define-color\s+([\w-]+)\s+([^;]+);", text
            )
        }
        if colors:
            return colors
    return {}


def apply_menu_palette(menu, cfg) -> None:
    """让桌面图标层的 GTK 右键菜单跟随 matugen 调色板（每次弹出重读）。"""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
    except (ImportError, ValueError):
        return
    colors = read_palette_colors()

    def pick(name: str, fallback: str) -> str:
        return colors.get(name, fallback)

    background = pick("surface_container_high", "#282934")
    foreground = pick("on_surface", "#e2e1ef")
    hover = pick("surface_container", "#1e1f29")
    outline = pick("outline_variant", "#454651")
    font = (getattr(cfg, "font_family", "") or "Noto Sans CJK SC").replace('"', "")
    css = (
        'menu {\n'
        '    background-color: %s;\n'
        '    color: %s;\n'
        '    font-family: "%s";\n'
        '    padding: 4px;\n'
        '}\n'
        'menu menuitem {\n'
        '    color: %s;\n'
        '    padding: 5px 12px;\n'
        '}\n'
        'menu menuitem:hover,\n'
        'menu menuitem:selected {\n'
        '    background-color: %s;\n'
        '    color: %s;\n'
        '}\n'
        'menu separator {\n'
        '    background-color: %s;\n'
        '}\n'
    ) % (background, foreground, font, foreground, hover, foreground, outline)

    css += ("menu menuitem.desktop-exit:hover, menu menuitem.desktop-exit:selected {"
            "background-image: none; background-color: #b3261e; color: #ffffff; }"
            "menu menuitem.desktop-exit:hover label, menu menuitem.desktop-exit:selected label {"
            "color: #ffffff; }")
    try:
        candidate = Gtk.CssProvider()
        candidate.load_from_data(css.encode("utf-8"))
        provider = getattr(menu, "_adws_palette_provider", None)
        if provider is None:
            provider = candidate
        else:
            provider.load_from_data(css.encode("utf-8"))
        menu._adws_palette_provider = provider
    except Exception as exc:  # noqa: BLE001 - 样式失败不应影响菜单本身
        LOG.warning(_tr('菜单调色板样式加载失败: %s'), exc)
        return False

    def attach(widget):
        widget.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        for child in widget.get_children() if isinstance(widget, Gtk.Container) else []:
            attach(child)
            if isinstance(child, Gtk.MenuItem):
                submenu = child.get_submenu()
                if submenu is not None:
                    attach(submenu)

    attach(menu)
    if not hasattr(menu, "_adws_palette_watch"):
        from adws_theme import Watch
        menu._adws_palette_watch = Watch(palette_file_candidates(),
                                         lambda: apply_menu_palette(menu, cfg), menu)


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=_tr('轻量 Wayland 桌面图标层'))
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--stop", action="store_true", help=_tr('退出运行中的图标层'))
    actions.add_argument("--toggle", action="store_true", help=_tr('隐藏 / 显示图标层'))
    actions.add_argument("--refresh", action="store_true", help=_tr('刷新桌面文件'))
    actions.add_argument("--check", action="store_true", help=_tr('检查依赖与桌面目录，不创建窗口'))
    parser.add_argument("--config", type=Path, help=_tr('配置文件'))
    parser.add_argument("--state", type=Path, help=_tr('布局状态文件'))
    parser.add_argument("--directory", type=Path, help=_tr('覆盖桌面目录，用于预览或测试'))
    parser.add_argument("--monitor", help="primary / all / DP-1 / 0")
    parser.add_argument("--preview", action="store_true", help=_tr('以普通窗口预览，不创建 layer'))
    parser.add_argument("--smoke-test", type=float, metavar="SECONDS", help=_tr('运行指定秒数后自动退出'))
    parser.add_argument("--diagnostics", type=Path, help=_tr('退出前写入运行诊断 JSON'))
    parser.add_argument("--snapshot", type=Path, help=_tr('保存图标画布 PNG（仅图标，不截取桌面）'))
    parser.add_argument("--debug", action="store_true", help=_tr('输出详细调试日志'))
    parser.add_argument("--log-level", type=int, choices=range(1, 7), default=4)
    args = parser.parse_args(argv)
    for key in ("config", "state", "directory", "diagnostics", "snapshot"):
        value = getattr(args, key)
        if value is not None:
            setattr(args, key, value.expanduser().absolute())
    if args.smoke_test is not None and (not math.isfinite(args.smoke_test) or args.smoke_test <= 0):
        parser.error(_tr('--smoke-test 必须是大于零的有限数值'))
    return args


def main(argv=None):
    args = arguments(argv)
    logging.basicConfig(level=(logging.CRITICAL, logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG, TRACE)[args.log_level - 1],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("GtkLayerShell", "0.1")
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Gio, GLib
        # Controls never create a window, and are usable even from a non-GUI terminal.
        action = "quit" if args.stop else "toggle" if args.toggle else "refresh" if args.refresh else None
        if action:
            bus_id = APP_ID + (".Preview" if args.preview else "")
            bus_path = "/" + bus_id.replace(".", "/")
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            owner = connection.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                         "org.freedesktop.DBus", "NameHasOwner", GLib.Variant("(s)", (bus_id,)),
                                         GLib.VariantType.new("(b)"), Gio.DBusCallFlags.NONE, 2000, None)
            if not owner.unpack()[0]:
                print(_tr('桌面图标层未运行。'))
                return 0
            connection.call_sync(bus_id, bus_path, "org.gtk.Actions", "Activate",
                                 GLib.Variant("(sava{sv})", (action, [], {})), None,
                                 Gio.DBusCallFlags.NONE, 2000, None)
            return 0
        cfg = load_config(args.config)
        if args.monitor:
            cfg.monitor = args.monitor
        directory = args.directory
        if directory is None:
            directory = Path(cfg.directory).expanduser() if cfg.directory else desktop_directory()
        directory = directory.absolute()
        if args.check:
            import cairo
            from PIL import ImageFilter
            from gi.repository import Gtk, GtkLayerShell, PangoCairo
            entries = scan_desktop(directory, cfg.show_hidden)
            print(json.dumps({"python": sys.version.split()[0], "desktop": str(directory),
                              "directory_exists": directory.is_dir(), "entries": len(entries),
                              "monitor": cfg.monitor, "dependencies": "GTK3 + GtkLayerShell + PyGObject OK",
                              "invalid_entries": [{"name": e.name, "error": e.error} for e in entries if e.error]},
                             ensure_ascii=False, indent=2))
            return 0 if directory.is_dir() else 1
        if not args.preview:
            os.environ["GDK_BACKEND"] = "wayland"
        from gi.repository import Gtk, Gdk, GtkLayerShell
        ok, _ = Gtk.init_check(None)
        if not ok:
            raise RuntimeError(_tr('无法连接图形会话，请从当前 Niri 会话的终端运行。'))
        if not args.preview and not GtkLayerShell.is_supported():
            raise RuntimeError(_tr('当前显示服务不支持 wlr-layer-shell，已退出。'))
        # Define GTK classes only after backend selection; --check needs no display.
        return run_gui(args, cfg, directory)
    except (ImportError, ValueError, OSError, RuntimeError) as exc:
        LOG.critical("%s", exc)
        return 1
    except Exception as exc:
        LOG.critical("%s: %s", type(exc).__name__, exc)
        return 1


def run_gui(args, cfg, directory):
    prepare_gtk_language()
    # GUI startup initializes the selected directory; --check stays read-only.
    directory.mkdir(parents=True, exist_ok=True)
    import cairo
    from gi.repository import Gtk, Gdk, Gio, GLib, Pango, PangoCairo, GtkLayerShell
    from PIL import Image, ImageFilter
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
    from adws_theme import start as start_theme_watch
    start_theme_watch()

    class DesktopWindow(Gtk.ApplicationWindow):
        def __init__(self, application, monitor, key):
            super().__init__(application=application)
            self.owner = application
            self.monitor_key = key
            self.monitor = monitor
            self.monitor_handler = None
            self.page = 0
            self.selection = set()
            self.selection_anchor = None
            self.hover = None
            self.press = None
            self.dragging = False
            self.drag_point = None
            self.press_key = None
            self.collapse_on_release = False
            self.press_modified = False
            self.marquee = None
            self.marquee_base = set()
            self.blur_cache = None
            self.rects = {}
            self.toolbar = (0, 0, 0, 0)
            self.icons = {}
            self.menu = None
            self.launch_dialog = None
            self.exit_dialog = None
            self.pending_opens = []
            self.rename_editor = self.rename_input = self.rename_key = None
            self.new_item = None
            self.new_item_kind = None
            self.rename_preedit = False
            self.last_area_size = None
            self.columns = self.rows = 1
            self.layout_pending = 0
            self.scroll_accumulator = 0.0
            self.set_title(_tr('桌面图标预览') if args.preview else _tr('桌面图标'))
            self.set_decorated(args.preview)
            self.set_app_paintable(True)
            self.set_accept_focus(True)
            visual = self.get_screen().get_rgba_visual()
            if visual:
                self.set_visual(visual)
            if args.preview:
                self.set_default_size(1024, 720)
            else:
                GtkLayerShell.init_for_window(self)
                GtkLayerShell.set_namespace(self, "niri-desktop-layer")
                GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BOTTOM)
                GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
                # Zero avoids panel exclusive zones but reserves no tiling area itself.
                GtkLayerShell.set_exclusive_zone(self, 0)
                GtkLayerShell.set_monitor(self, monitor)
                if cfg.columns:
                    width = min(monitor.get_geometry().width, cfg.columns * cfg.cell_width + 2 * cfg.margin)
                    self.set_default_size(width, 0)
                    self.set_size_request(width, -1)
                    self.monitor_handler = monitor.connect("notify::geometry", self.monitor_resized)
                else:
                    GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
                for edge in (GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM):
                    GtkLayerShell.set_anchor(self, edge, True)
            self.area = Gtk.DrawingArea()
            self.area.set_can_focus(True)
            self.area.set_hexpand(True)
            self.area.set_vexpand(True)
            self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                                 Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK |
                                 Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
            self.area.set_has_tooltip(True)
            self.overlay = Gtk.Overlay()
            self.overlay.add(self.area)
            self.overlay.connect('get-child-position', self.position_rename_editor)
            self.add(self.overlay)
            for event, callback in [("draw", self.draw), ("size-allocate", self.resized),
                                    ("button-press-event", self.button_press),
                                    ("button-release-event", self.button_release),
                                    ("motion-notify-event", self.motion),
                                    ("leave-notify-event", self.leave),
                                    ("query-tooltip", self.tooltip), ("scroll-event", self.scroll)]:
                self.area.connect(event, callback)
            self.connect("key-press-event", self.key_press)
            self.connect("map-event", self.mapped)
            self.connect("notify::scale-factor", lambda *_: self.invalidate_icons())
            self.connect("destroy", self.destroyed)
            self.fade = WindowFade(self, self.area, application.hidden)
            self.show_all()

        def monitor_resized(self, *_):
            width = min(self.monitor.get_geometry().width, cfg.columns * cfg.cell_width + 2 * cfg.margin)
            self.set_size_request(max(1, width), -1)
            self.resize(max(1, width), 1)

        def destroyed(self, *_):
            self.cancel_rename()
            self.fade.close()
            if self.monitor_handler is not None:
                self.monitor.disconnect(self.monitor_handler)
                self.monitor_handler = None
            if self.layout_pending:
                GLib.source_remove(self.layout_pending)
                self.layout_pending = 0
            if self.menu:
                self.menu.destroy()
                self.menu = None

        def invalidate_icons(self):
            self.blur_cache = None
            self.icons.clear()
            self.area.queue_draw()

        def mapped(self, *_):
            self.relayout()
            return False

        def resized(self, _widget, allocation):
            size = (allocation.width, allocation.height)
            if size == self.last_area_size:
                return
            self.last_area_size = size
            if not self.layout_pending:
                self.layout_pending = GLib.idle_add(self.delayed_layout)

        def delayed_layout(self):
            self.layout_pending = 0
            self.relayout()
            return False

        def pages(self):
            return max(1, math.ceil((len(self.owner.entries) + (self.new_item is not None)) / (self.columns * self.rows)))

        def relayout(self):
            previous_rename_rect = self.rects.get(self.rename_key)
            width, height = self.area.get_allocated_width(), self.area.get_allocated_height()
            self.columns = max(1, (width - 2 * cfg.margin) // cfg.cell_width)
            self.rows = max(1, (height - 2 * cfg.margin - 38) // cfg.cell_height)
            self.page = min(self.page, self.pages() - 1)
            capacity = self.columns * self.rows
            # Stable names determine pagination. Saved positions are per output and page.
            entries = self.owner.entries + ([self.new_item] if self.new_item is not None else [])
            visible = entries[self.page * capacity:(self.page + 1) * capacity]
            saved = self.owner.positions.get(f"{self.monitor_key}:{self.page}", {})
            layout = arrange_grid([str(e.path) for e in visible], saved, self.columns, self.rows)
            self.rects = {key: (cfg.margin + cell[0] * cfg.cell_width,
                                cfg.margin + cell[1] * cfg.cell_height,
                                cfg.cell_width, cfg.cell_height) for key, cell in layout.items()}
            self.toolbar = (cfg.margin, max(0, height - cfg.margin - 30), min(242, max(0, width - 2 * cfg.margin)), 30)
            self.selection.intersection_update([str(entry.path) for entry in entries])
            if self.rename_key is not None:
                if self.rename_key not in self.rects:
                    self.cancel_rename()
                elif previous_rename_rect != self.rects[self.rename_key]:
                    self.overlay.queue_resize()
            self.blur_cache = None
            self.apply_input_region()
            self.area.queue_draw()

        def apply_input_region(self):
            if args.preview or not self.get_window():
                return
            # The desktop accepts empty-space drags for marquee selection. During
            # overview it yields all pointer input back to the compositor.
            region = cairo.Region()
            if not self.owner.overview_active:
                region.union(cairo.RectangleInt(0, 0, self.area.get_allocated_width(),
                                                self.area.get_allocated_height()))
            self.get_window().input_shape_combine_region(region, 0, 0)

        def hit(self, x, y):
            for key, (rx, ry, width, height) in self.rects.items():
                if rx <= x < rx + width and ry <= y < ry + height:
                    return key
            return None

        def in_toolbar(self, x, y):
            rx, ry, width, height = self.toolbar
            return rx <= x < rx + width and ry <= y < ry + height

        def entry(self, key):
            if self.new_item is not None and key == str(self.new_item.path):
                return self.new_item
            return self.owner.by_path.get(key)

        def pixbuf(self, entry):
            scale = self.get_scale_factor()
            key = (entry.icon.to_string(), scale)
            if key not in self.icons:
                theme = Gtk.IconTheme.get_default()
                try:
                    info = theme.lookup_by_gicon_for_scale(entry.icon, cfg.icon_size, scale,
                                                         Gtk.IconLookupFlags.FORCE_SIZE)
                    self.icons[key] = info.load_icon() if info else None
                except GLib.Error:
                    self.icons[key] = None
                if self.icons[key] is None:
                    try:
                        self.icons[key] = theme.load_icon_for_scale("text-x-generic", cfg.icon_size, scale,
                                                                   Gtk.IconLookupFlags.FORCE_SIZE)
                    except GLib.Error:
                        pass
            return self.icons[key]

        @staticmethod
        def rounded(cr, x, y, w, h, radius=8):
            radius = min(radius, w / 2, h / 2)
            cr.new_sub_path()
            for cx, cy, start in [(x+w-radius, y+radius, -math.pi/2),
                                  (x+w-radius, y+h-radius, 0),
                                  (x+radius, y+h-radius, math.pi/2),
                                  (x+radius, y+radius, math.pi)]:
                cr.arc(cx, cy, radius, start, start + math.pi / 2)
            cr.close_path()

        def text(self, cr, text, x, y, width, size=None, lines=2):
            layout = PangoCairo.create_layout(cr)
            options = cairo.FontOptions()
            options.set_antialias(cairo.ANTIALIAS_GRAY)
            PangoCairo.context_set_font_options(layout.get_context(), options)
            layout.set_font_description(Pango.FontDescription(f"{cfg.font_family} {size or cfg.font_size}"))
            layout.set_text(text, -1)
            layout.set_width(max(1, int(width)) * Pango.SCALE)
            layout.set_height(-lines)
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
            layout.set_ellipsize(Pango.EllipsizeMode.END)
            layout.set_alignment(Pango.Alignment.CENTER)
            cr.set_source_rgba(0, 0, 0, .85)
            for dx, dy in [(0, 1), (1, 1), (-1, 1)]:
                cr.move_to(x + dx, y + dy)
                PangoCairo.show_layout(cr, layout)
            cr.set_source_rgba(1, 1, 1, 1)
            cr.move_to(x, y)
            PangoCairo.show_layout(cr, layout)

        def draw_icon(self, cr, key, rect, ghost=False):
            entry = self.entry(key)
            if not entry:
                return
            x, y, width, height = rect
            if key in self.selection or key == self.hover or ghost:
                self.rounded(cr, x + 3, y + 2, width - 6, height - 4)
                cr.set_source_rgba(.25, .48, .72, .45 if key in self.selection else .22)
                cr.fill_preserve()
                cr.set_source_rgba(.75, .87, 1, .42)
                cr.set_line_width(1)
                cr.stroke()
            icon = self.pixbuf(entry)
            if icon:
                scale = self.get_scale_factor()
                cr.save()
                cr.translate(x + (width - icon.get_width() / scale) / 2, y + 8)
                cr.scale(1 / scale, 1 / scale)
                Gdk.cairo_set_source_pixbuf(cr, icon, 0, 0)
                cr.paint_with_alpha(.72 if ghost else 1)
                cr.restore()
            else:
                self.text(cr, "◇", x, y + 8, width, 30, 1)
            if key != self.rename_key:
                self.text(cr, entry.name, x + 5, y + cfg.icon_size + 14, width - 10)

        def draw_contents(self, cr):
            for key, rect in self.rects.items():
                self.draw_icon(cr, key, rect)
            x, y, width, height = self.toolbar
            self.rounded(cr, x, y, width, height, 9)
            cr.set_source_rgba(.08, .10, .14, .65)
            cr.fill()
            label = ''.join([_tr('已选 '), f'{len(self.selection)}', ' / ', f'{len(self.owner.entries)}', _tr(' 项')]) if self.selection else ''.join([_tr('桌面 · '), f'{len(self.owner.entries)}', _tr(' 项')])
            if self.pages() > 1:
                label += f"    ‹  {self.page+1}/{self.pages()}  ›"
            label += "    ⋮"
            self.text(cr, label, x + 5, y + 6, width - 10, 9, 1)

        def blurred_surface(self):
            if self.blur_cache is None:
                # Only cache the content bounding box, not the full 4K canvas.
                rects = [*self.rects.values(), self.toolbar]
                width = min(self.area.get_allocated_width(), max(int(x+w) for x,y,w,h in rects) + 16)
                height = min(self.area.get_allocated_height(), max(int(y+h) for x,y,w,h in rects) + 16)
                surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, width), max(1, height))
                self.draw_contents(cairo.Context(surface))
                surface.flush()
                source = Image.frombuffer("RGBA", (width, height), bytes(surface.get_data()), "raw", "BGRA", surface.get_stride(), 1)
                blurred = source.filter(ImageFilter.GaussianBlur(cfg.overview_blur))
                data = bytearray(blurred.tobytes("raw", "BGRA"))
                result = cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32, width, height)
                # Retain backing bytes for the cairo surface lifetime.
                self.blur_cache = (result, data)
            return self.blur_cache[0]

        def draw(self, _widget, cr):
            LOG.log(TRACE, _tr('绘制桌面：output=%s'), self.monitor_key)
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            if self.owner.overview_active and cfg.overview_blur:
                cr.set_source_surface(self.blurred_surface(), 0, 0)
                cr.paint()
                return True
            self.draw_contents(cr)
            if self.marquee:
                x, y, w, h = self.marquee
                if w < 0:
                    x, w = x+w, -w
                if h < 0:
                    y, h = y+h, -h
                cr.rectangle(x+.5, y+.5, w, h)
                cr.set_source_rgba(.28, .57, .92, .20)
                cr.fill_preserve()
                cr.set_source_rgba(.53, .76, 1, .85)
                cr.set_line_width(1)
                cr.stroke()
            if self.dragging and self.press_key and self.drag_point:
                dx, dy = self.drag_point[0]-self.press[0], self.drag_point[1]-self.press[1]
                for key in self.selection:
                    if key in self.rects:
                        x,y,w,h = self.rects[key]
                        self.draw_icon(cr, key, (x+dx,y+dy,w,h), ghost=True)
            return True

        def selection_changed(self):
            self.blur_cache = None
            self.area.queue_draw()

        def key_press(self, _widget, event):
            LOG.debug(_tr('桌面按键：keyval=%s'), event.keyval)
            if self.rename_input is not None:
                # Editing shortcuts belong to the entry, never the desktop selection.
                return False
            if self.owner.overview_active or self.owner.hidden:
                return False
            control = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
            if event.keyval == Gdk.KEY_F2 and len(self.selection) == 1:
                self.rename_entry(next(iter(self.selection)))
                return True
            if control and event.keyval in (Gdk.KEY_a, Gdk.KEY_A):
                self.selection = set(self.rects)
                self.selection_changed()
                return True
            if event.keyval == Gdk.KEY_Escape:
                self.selection.clear()
                self.press = self.marquee = self.drag_point = None
                self.dragging = False
                self.selection_changed()
                return True
            if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                self.open_selected()
                return True
            if event.keyval == Gdk.KEY_Delete and self.selection:
                if event.state & Gdk.ModifierType.SHIFT_MASK:
                    self.confirm_permanent_delete()
                else:
                    self.trash_selected()
                return True
            return False

        def button_press(self, _widget, event):
            LOG.debug(_tr('鼠标按下：button=%s x=%.1f y=%.1f'), event.button, event.x, event.y)
            if self.rename_input is not None and not self.commit_rename():
                return True
            if self.owner.overview_active:
                return False
            if self.owner.hidden:
                if event.button == 3:
                    self.popup(event, None)
                    return True
                return False
            key = self.hit(event.x, event.y)
            if event.button == 3:
                if key and key not in self.selection:
                    self.selection = {key}
                    self.selection_anchor = key
                self.popup(event, key)
                self.selection_changed()
                return True
            if event.button != 1:
                return False
            self.area.grab_focus()
            if self.in_toolbar(event.x, event.y):
                self.press = None
                self.popup(event, None)
                return True
            state = getattr(event, "state", 0)
            control = bool(state & Gdk.ModifierType.CONTROL_MASK)
            shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
            if event.type == Gdk.EventType._2BUTTON_PRESS and key and not cfg.single_click and not (control or shift):
                self.press = None
                self.open_entry(key, event)
                return True
            self.press = (event.x, event.y)
            self.press_key = key
            self.press_modified = control or shift
            self.dragging = False
            self.collapse_on_release = False
            self.marquee = None
            if key:
                if shift and self.selection_anchor in self.rects:
                    keys = sorted(self.rects, key=lambda k: (self.rects[k][0], self.rects[k][1]))
                    a, b = sorted((keys.index(self.selection_anchor), keys.index(key)))
                    chosen = set(keys[a:b+1])
                    self.selection = self.selection | chosen if control else chosen
                elif control:
                    self.selection.symmetric_difference_update({key})
                    self.selection_anchor = key
                elif key not in self.selection:
                    self.selection = {key}
                    self.selection_anchor = key
                else:
                    # Preserve an existing group until we know this is a click.
                    self.collapse_on_release = True
            else:
                self.marquee_base = set(self.selection) if control or shift else set()
                self.selection = set(self.marquee_base)
                self.selection_anchor = None
            self.selection_changed()
            return True

        def button_release(self, _widget, event):
            if event.button != 1:
                return False
            had_press = self.press is not None
            if self.dragging and self.press_key and self.press:
                target_key = self.hit(event.x, event.y)
                target_entry = self.entry(target_key) if target_key is not None else None
                if (target_key is not None and target_key not in self.selection
                        and target_entry is not None and self.owner.drop_target(target_entry)):
                    self.drop_selection(target_entry)
                    self.press = None
                    self.press_key = None
                    self.dragging = False
                    self.drag_point = None
                    self.marquee = None
                    self.selection_changed()
                    return True
                dx = round((event.x - self.press[0]) / cfg.cell_width)
                dy = round((event.y - self.press[1]) / cfg.cell_height)
                self.move_selection(dx, dy)
            elif had_press and self.marquee is None and self.press_key:
                if self.collapse_on_release:
                    self.selection = {self.press_key}
                    self.selection_anchor = self.press_key
                if cfg.single_click and not self.press_modified and self.press_key == self.hit(event.x, event.y):
                    self.open_entry(self.press_key, event)
            self.press = None
            self.press_key = None
            self.dragging = False
            self.drag_point = None
            self.marquee = None
            self.selection_changed()
            return True

        @logged_action(_tr('移动选中图标'))
        def move_selection(self, dx, dy):
            layout = {k: (int((r[0]-cfg.margin)//cfg.cell_width), int((r[1]-cfg.margin)//cfg.cell_height))
                      for k,r in self.rects.items()}
            moved = move_group(layout, self.selection, dx, dy, self.columns, self.rows)
            if moved != layout:
                self.owner.positions[f"{self.monitor_key}:{self.page}"] = {k:list(v) for k,v in moved.items()}
                self.owner.save_state()
                self.relayout()

        @logged_action(_tr('移动图标'))
        def move_icon(self, key, x, y):
            if key not in self.rects:
                return
            self.selection = {key}
            old = self.rects[key]
            target_col = int((x-cfg.margin)//cfg.cell_width)
            target_row = int((y-cfg.margin)//cfg.cell_height)
            self.move_selection(target_col-int((old[0]-cfg.margin)//cfg.cell_width),
                                target_row-int((old[1]-cfg.margin)//cfg.cell_height))

        def motion(self, _widget, event):
            LOG.log(TRACE, _tr('鼠标移动：x=%.1f y=%.1f'), event.x, event.y)
            if self.owner.overview_active or self.owner.hidden:
                return False
            self.hover = self.hit(event.x, event.y)
            if self.press:
                dx, dy = event.x-self.press[0], event.y-self.press[1]
                if dx*dx + dy*dy > 64:
                    if self.press_key and self.press_key in self.selection:
                        self.dragging = True
                        self.drag_point = (event.x, event.y)
                    elif not self.press_key:
                        self.marquee = (self.press[0], self.press[1], dx, dy)
                        self.selection = self.marquee_base | rectangle_hits(self.rects, self.marquee)
            self.selection_changed()
            return True

        def leave(self, *_):
            self.hover = None
            self.area.queue_draw()
            return False

        def tooltip(self, _widget, x, y, keyboard, tooltip):
            if self.owner.hidden or self.owner.overview_active or self.new_item is not None:
                return False
            if keyboard or self.dragging or self.marquee:
                return False
            entry = self.entry(self.hit(x, y))
            if entry:
                tooltip.set_text(entry.name + "\n" + str(entry.path) + ("\n" + entry.error if entry.error else ""))
                return True
            if self.in_toolbar(x, y):
                tooltip.set_text(_tr('点击打开桌面菜单；滚轮翻页'))
                return True
            return False

        @logged_action(_tr('翻页'))
        def change_page(self, step):
            self.cancel_rename()
            self.page = (self.page + step) % self.pages()
            self.selection.clear()
            self.selection_anchor = None
            self.relayout()

        def scroll(self, _widget, event):
            if self.pages() <= 1:
                return False
            if event.direction in (Gdk.ScrollDirection.DOWN, Gdk.ScrollDirection.RIGHT):
                self.change_page(1)
            elif event.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.LEFT):
                self.change_page(-1)
            elif event.direction == Gdk.ScrollDirection.SMOOTH:
                valid, dx, dy = event.get_scroll_deltas()
                if valid:
                    self.scroll_accumulator += dy if abs(dy) >= abs(dx) else dx
                    if abs(self.scroll_accumulator) >= 1.0:
                        self.change_page(1 if self.scroll_accumulator > 0 else -1)
                        self.scroll_accumulator = 0.0
            return True

        @logged_action(_tr('打开桌面项目'))
        def open_entry(self, key, event=None, allow=False):
            if self.launch_dialog:
                self.launch_dialog.present()
                return
            self.pending_opens = [key]
            self.launch_time = event.time if event is not None else Gtk.get_current_event_time()
            self.process_open_queue(allow_first=allow)

        @logged_action(_tr('处理打开队列'))
        def process_open_queue(self, allow_first=False):
            while self.pending_opens:
                key = self.pending_opens.pop(0)
                entry = self.entry(key)
                if entry is None:
                    continue
                try:
                    context = self.get_display().get_app_launch_context()
                    context.set_timestamp(getattr(self, "launch_time", Gtk.get_current_event_time()))
                    LOG.info(_tr('项目打开请求：%s'), entry.path)
                    launch_entry(entry, context, allow_untrusted=allow_first)
                    LOG.info(_tr('项目打开请求已提交：%s'), entry.path)
                    allow_first = False
                except UntrustedLauncher:
                    self.confirm_launch(entry)
                    return
                except Exception as exc:
                    LOG.warning(_tr('打开失败 %s: %s'), entry.path, exc)
                    self.confirm_launch(entry, error=str(exc))
                    return

        @logged_action(_tr('打开快捷方式确认框'))
        def confirm_launch(self, entry, error=None):
            title = _tr('无法打开项目') if error else _tr('运行此快捷方式？')
            dialog = Gtk.MessageDialog(transient_for=self, modal=True, destroy_with_parent=True,
                                       message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.QUESTION,
                                       buttons=Gtk.ButtonsType.NONE, text=title)
            details = entry.name + "\n" + str(entry.path)
            if error:
                details += "\n\n" + error
            else:
                try:
                    keyfile = GLib.KeyFile.new()
                    keyfile.load_from_file(str(entry.path), GLib.KeyFileFlags.NONE)
                    details += _tr('\n\n命令：') + keyfile.get_string("Desktop Entry", "Exec")[:300]
                except GLib.Error:
                    pass
                details += _tr('\n\n此文件尚未标记为可执行。允许本次运行不会修改文件权限。')
            dialog.format_secondary_text(details)
            dialog.add_button(_tr('取消全部') if self.pending_opens else _tr('取消'), Gtk.ResponseType.CANCEL)
            if self.pending_opens:
                dialog.add_button(_tr('跳过此项'), Gtk.ResponseType.REJECT)
            if not error:
                dialog.add_button(_tr('本次运行'), Gtk.ResponseType.ACCEPT)
            self.launch_dialog = dialog
            def response(widget, result):
                widget.destroy()
                self.launch_dialog = None
                if result == Gtk.ResponseType.ACCEPT:
                    self.pending_opens.insert(0, str(entry.path))
                    self.process_open_queue(allow_first=True)
                elif result == Gtk.ResponseType.REJECT:
                    self.process_open_queue()
                else:
                    self.pending_opens.clear()
            dialog.connect("response", response)
            dialog.connect("response", lambda w, result: LOG.info(_tr('弹窗响应：%s，结果=%s'), w.get_title(), result))
            dialog.show_all()

        def make_menu(self, key):
            menu = Gtk.Menu()
            def item(parent, label, callback=None):
                widget = Gtk.MenuItem(label=label)
                widget.set_sensitive(callback is not None)
                if callback:
                    widget.connect("activate", lambda *_: (LOG.info(_tr('菜单操作：%s'), label), callback()))
                parent.append(widget)
                return widget
            def separator(parent):
                parent.append(Gtk.SeparatorMenuItem())
            def submenu(label):
                parent = Gtk.MenuItem(label=label)
                child = Gtk.Menu()
                parent.set_submenu(child)
                menu.append(parent)
                return child
            def radio(parent, labels, selected, callback):
                group = None
                for value, label in labels:
                    widget = Gtk.RadioMenuItem.new_with_label_from_widget(group, label)
                    group = widget
                    widget.set_active(value == selected)
                    widget.connect("activate", lambda w, value=value, label=label: (LOG.info(_tr('菜单选择：%s'), label), callback(value)) if w.get_active() else None)
                    parent.append(widget)
            def check(parent, label, active, callback):
                widget = Gtk.CheckMenuItem(label=label)
                widget.set_active(active)
                widget.connect("toggled", lambda w: (LOG.info(_tr('菜单开关：%s=%s'), label, w.get_active()), callback(w.get_active())))
                parent.append(widget)
            if self.owner.hidden:
                item(menu, _tr('显示桌面图标'), self.owner.toggle)
                separator(menu)
                item(menu, _tr('打开终端'), self.owner.open_terminal)
                item(menu, _tr('打开桌面文件夹'), self.owner.open_directory)
                return menu
            if not key:
                new_menu = submenu(_tr('新建'))
                item(new_menu, _tr('文件夹'), lambda: self.create_item("folder", "folder"))
                item(new_menu, _tr('文本文档'), lambda: self.create_item("text", "text.txt"))
                item(new_menu, _tr('Markdown 文档'), lambda: self.create_item("markdown", "markdown.md"))
                separator(menu)
            if key:
                item(menu, ''.join([_tr('打开选中的 '), f'{len(self.selection)}', _tr(' 项')]) if len(self.selection) > 1 else _tr('打开'),
                     self.open_selected if len(self.selection) > 1 else lambda: self.open_entry(key))
                item(menu, _tr('在 Thunar 中显示'), self.reveal_selected)
                item(menu, _tr('复制文件路径'), self.copy_paths)
                item(menu, _tr('重命名…'), (lambda: self.rename_entry(key)) if len(self.selection) <= 1 else None)
                separator(menu)
                item(menu, _tr('删除（移到回收站）'), self.trash_selected)
                separator(menu)
            elif self.selection:
                separator(menu)
                item(menu, ''.join([_tr('删除选中的 '), f'{len(self.selection)}', _tr(' 项（移到回收站）')]), self.trash_selected)
                separator(menu)
            view = submenu(_tr('查看'))
            radio(view, [(64, _tr('大图标')), (48, _tr('中等图标')), (32, _tr('小图标'))], cfg.icon_size, self.owner.change_icon_size)
            separator(view)
            check(view, _tr('显示隐藏文件'), cfg.show_hidden, self.owner.change_hidden_files)
            sorting = submenu(_tr('排序方式'))
            radio(sorting, [("name", _tr('名称')), ("type", _tr('项目类型')), ("size", _tr('大小')), ("modified", _tr('修改日期'))],
                  cfg.sort_by, lambda value: self.owner.set_sort(sort_by=value))
            separator(sorting)
            radio(sorting, [(False, _tr('递增')), (True, _tr('递减'))], cfg.sort_descending,
                  lambda value: self.owner.set_sort(sort_descending=value))
            separator(sorting)
            check(sorting, _tr('文件夹优先'), cfg.folders_first, lambda value: self.owner.set_sort(folders_first=value))
            item(menu, _tr('刷新'), self.owner.refresh)
            item(menu, _tr('按当前排序重新排列'), self.owner.rearrange)
            separator(menu)
            item(menu, _tr('全选'), self.select_all)
            item(menu, _tr('取消选择'), self.clear_selection if self.selection else None)
            item(menu, _tr('打开终端'), self.owner.open_terminal)
            item(menu, _tr('打开桌面文件夹'), self.owner.open_directory)
            if key:
                separator(menu)
                item(menu, _tr('属性'), self.show_properties)
            if self.pages() > 1:
                separator(menu)
                item(menu, _tr('上一页'), lambda: self.change_page(-1))
                item(menu, _tr('下一页'), lambda: self.change_page(1))
            separator(menu)
            item(menu, _tr('桌面设置…'), self.show_desktop_settings)
            item(menu, _tr('隐藏桌面图标'), self.owner.toggle)
            exit_item = item(menu, _tr('退出桌面图标'), self.confirm_exit)
            exit_item.get_style_context().add_class("desktop-exit")
            return menu

        @logged_action(_tr('打开退出确认框'))
        def confirm_exit(self):
            import shlex
            if self.exit_dialog is not None:
                self.exit_dialog.present()
                return
            launcher = Path(__file__).resolve().parents[3] / "adws"
            restart_command = "adws desktop --start" if shutil.which("adws") else shlex.quote(str(launcher)) + " desktop --start"
            dialog = Gtk.MessageDialog(transient_for=self, modal=True, destroy_with_parent=True,
                                       message_type=Gtk.MessageType.WARNING,
                                       buttons=Gtk.ButtonsType.NONE, text=_tr('您真的要退出吗？'))
            dialog.format_secondary_text(_tr('退出后桌面图标和桌面右键功能将失效。\n您可以输入以下命令重启：'))
            command = Gtk.Entry()
            command.set_text(restart_command)
            command.set_editable(False)
            command.set_tooltip_text(_tr('可选中并复制此命令，在终端中运行'))
            dialog.get_content_area().pack_start(command, False, False, 8)
            dialog.add_button(_tr('取消'), Gtk.ResponseType.CANCEL)
            confirm = dialog.add_button(_tr('退出桌面'), Gtk.ResponseType.ACCEPT)
            confirm.get_style_context().add_class("destructive-action")
            dialog.set_default_response(Gtk.ResponseType.CANCEL)
            self.exit_dialog = dialog
            def response(widget, result):
                widget.destroy()
                if result == Gtk.ResponseType.ACCEPT:
                    self.owner.quit()
            def destroyed(*_):
                self.exit_dialog = None
            dialog.connect("destroy", destroyed)
            dialog.connect("response", response)
            dialog.connect("response", lambda w, result: LOG.info(_tr('弹窗响应：%s，结果=%s'), w.get_title(), result))
            dialog.show_all()

        @logged_action(_tr('打开桌面右键菜单'))
        def popup(self, event, key):
            if self.menu:
                self.menu.destroy()
            self.menu = self.make_menu(key)
            apply_menu_palette(self.menu, cfg)
            self.menu.show_all()
            if event is not None:
                self.menu.popup_at_pointer(event)
            else:
                self.menu.popup_at_widget(self.area, Gdk.Gravity.CENTER, Gdk.Gravity.CENTER, None)

        def chosen_entries(self):
            return [entry for entry in self.owner.entries if str(entry.path) in self.selection]

        @logged_action(_tr('复制文件路径'))
        def copy_paths(self):
            paths = "\n".join(str(entry.path) for entry in self.chosen_entries())
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(paths, -1)

        @logged_action(_tr('在文件管理器中显示选中项目'))
        def reveal_selected(self):
            self.owner.reveal_files(self.chosen_entries())

        def unique_target(self, name):
            """返回桌面目录中不存在的文件名，重复时自动追加 (2)、(3)…"""
            name = Path(name).name
            target = directory / name
            if not os.path.lexists(target):
                return target
            stem, suffix = os.path.splitext(name)
            index = 2
            while True:
                target = directory / f"{stem} ({index}){suffix}"
                if not os.path.lexists(target):
                    return target
                index += 1

        def position_rename_editor(self, _overlay, child, allocation):
            if child is not self.rename_editor or self.rename_key not in self.rects:
                return False
            x, y, width, _ = self.rects[self.rename_key]
            allocation.width = max(1, int(width - 10))
            allocation.height = child.get_preferred_height_for_width(allocation.width)[1]
            allocation.x = max(0, int(x + 5))
            allocation.y = max(0, min(int(y + cfg.icon_size + 14),
                                      self.area.get_allocated_height() - allocation.height))
            return True

        def cancel_rename(self, keep_draft=False):
            editor = self.rename_editor
            self.rename_editor = self.rename_input = self.rename_key = None
            self.rename_preedit = False
            if editor is not None:
                editor.destroy()
                self.selection_changed()
            if self.new_item is not None and not keep_draft:
                if self.selection_anchor == str(self.new_item.path):
                    self.selection_anchor = None
                self.selection.discard(str(self.new_item.path))
                self.new_item = self.new_item_kind = None
                self.relayout()

        def rename_error(self, message):
            LOG.warning('%s: %s', _tr('创建失败') if self.new_item is not None else _tr('重命名失败'), message)
            self.rename_input.get_style_context().add_class('error')
            self.rename_error_label.set_text(message)
            self.rename_error_label.show()
            self.overlay.queue_resize()
            return False

        @logged_action(_tr('重命名'))
        def rename_entry(self, key):
            entry = self.entry(key)
            if entry is None or key not in self.rects or self.owner.hidden or self.owner.overview_active:
                return
            self.cancel_rename(keep_draft=entry is self.new_item)
            self.selection = {key}
            self.selection_anchor = key
            self.rename_key = key
            launcher = entry.kind in ('application', 'link') and not entry.error
            name = entry.name if launcher or entry is self.new_item else entry.path.name
            editor = self.rename_editor = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            field = self.rename_input = Gtk.Entry()
            if not args.preview:
                # Layer-shell runs on Wayland. Let the compositor/IME own the
                # candidate surface: fcitx's GTK client-side themed popup can
                # block this desktop's main loop in synchronous image decoding.
                # This per-entry override does not alter the user's IM settings.
                field.set_property('im-module', 'wayland')
            field.set_width_chars(1)
            field.set_alignment(.5)
            field.set_text(name)
            field.get_accessible().set_name(_tr('新建项目') if entry is self.new_item else _tr('重命名'))
            editor.pack_start(field, False, False, 0)
            error = self.rename_error_label = Gtk.Label()
            error.set_line_wrap(True)
            error.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            error.set_max_width_chars(1)
            error.get_style_context().add_class('error')
            editor.pack_start(error, False, False, 0)
            error.set_no_show_all(True)
            field.connect('activate', lambda *_: self.commit_rename())
            field.connect('preedit-changed', self.rename_preedit_changed)
            def key_press(_field, event):
                if event.keyval == Gdk.KEY_Escape:
                    # Let the IME dismiss its candidate/preedit first. Do not destroy
                    # an input context while it is handling composition.
                    if _field.im_context_filter_keypress(event):
                        return True
                    if self.rename_preedit:
                        _field.reset_im_context()
                        self.rename_preedit = False
                        return True
                    self.cancel_rename()
                    self.area.grab_focus()
                    return True
                return False
            field.connect('key-press-event', key_press)
            # Candidate windows and input-method switching may temporarily take
            # focus. Losing focus is not a file operation and must not grab it back.
            self.overlay.add_overlay(editor)
            self.overlay.set_overlay_pass_through(editor, False)
            editor.show_all()
            self.selection_changed()
            def focus():
                if self.rename_input is field:
                    field.grab_focus()
                    # Like Explorer: retain the extension; directories and launchers select all.
                    suffix = Path(name).suffix if entry.kind == 'file' and not launcher else ''
                    field.select_region(0, len(name) - len(suffix) if suffix else -1)
                return False
            GLib.idle_add(focus)

        def rename_preedit_changed(self, field, text):
            if self.rename_input is field:
                self.rename_preedit = bool(text)

        def commit_rename(self):
            if self.rename_input is None:
                return True
            if self.rename_preedit:
                return False
            key = self.rename_key
            entry = self.entry(key)
            if entry is None:
                self.cancel_rename()
                return True
            launcher = entry.kind in ('application', 'link') and not entry.error
            name = self.rename_input.get_text()
            old_name = entry.name if launcher else entry.path.name
            if name == old_name and entry is not self.new_item:
                self.cancel_rename()
                return True
            if not name.strip() or '/' in name or '\x00' in name or name in ('.', '..'):
                return self.rename_error(_tr('名称不能为空，不能包含 /，也不能是 . 或 ..'))
            if entry is self.new_item:
                target = directory / name
                try:
                    if self.new_item_kind == 'folder':
                        target.mkdir()
                    else:
                        # Exclusive creation protects files and dangling symlinks,
                        # including a file created after the editor was opened.
                        with target.open('x', encoding='utf-8') as stream:
                            if self.new_item_kind == 'markdown':
                                stream.write(_tr('# 新文档\n'))
                except OSError as exc:
                    return self.rename_error(str(exc))
                self.cancel_rename()
                self.finish_file_change(target)
                LOG.info('%s: %s', _tr('新建项目'), target)
                return True
            target = entry.path if launcher else entry.path.with_name(name)
            try:
                source = Gio.File.new_for_path(key)
                if launcher:
                    # Desktop launchers display Name, not their file basename.
                    _, content, etag = source.load_contents(None)
                    data = GLib.KeyFile()
                    data.load_from_data(content.decode('utf-8'), len(content),
                                        GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
                    for field in data.get_keys('Desktop Entry')[0]:
                        if field == 'Name' or field.startswith('Name['):
                            data.set_string('Desktop Entry', field, name)
                    payload, _ = data.to_data()
                    source.replace_contents(payload.encode('utf-8'), etag, False,
                                            Gio.FileCreateFlags.NONE, None)
                else:
                    # NONE must never overwrite a file, directory or dangling link.
                    source.move(Gio.File.new_for_path(str(target)), Gio.FileCopyFlags.NONE, None, None)
            except (GLib.Error, OSError, ValueError) as exc:
                return self.rename_error(str(exc))
            for positions in self.owner.positions.values():
                if key in positions:
                    positions[str(target)] = positions.pop(key)
            self.owner.save_state()
            self.cancel_rename()
            self.finish_file_change(target)
            LOG.info('%s: %s → %s', _tr('重命名'), old_name, name)
            return True

        @logged_action(_tr('新建项目'))
        def create_item(self, kind, default):
            if self.owner.hidden or self.owner.overview_active:
                return
            self.cancel_rename()
            self.new_item_kind = kind
            self.new_item = Entry(directory / ('.adws-draft-' + uuid.uuid4().hex),
                                  self.unique_target(default).name,
                                  Gio.ThemedIcon.new('folder' if kind == 'folder' else 'text-x-generic'),
                                  'directory' if kind == 'folder' else 'file')
            self.page = self.pages() - 1
            self.relayout()
            self.rename_entry(str(self.new_item.path))

        def finish_file_change(self, target):
            self.owner.refresh()
            key = str(target)
            if key in self.owner.by_path and key not in self.rects:
                index = next(i for i, entry in enumerate(self.owner.entries) if str(entry.path) == key)
                self.page = index // (self.columns * self.rows)
                self.relayout()
            if key in self.owner.by_path and key in self.rects:
                self.selection = {key}
                self.selection_anchor = key
            self.selection_changed()

        @logged_action(_tr('移到回收站'))
        def trash_selected(self):
            entries = self.chosen_entries()
            if not entries:
                return
            failures = []
            for entry in entries:
                try:
                    file = Gio.File.new_for_path(str(entry.path))
                    file.trash(None)
                except (GLib.Error, OSError) as exc:
                    message = exc.message if isinstance(exc, GLib.Error) else str(exc)
                    failures.append(f"{entry.name}：{message}")
            self.after_delete()
            if failures:
                self.show_error(_tr('部分项目未能删除'), "\n".join(failures))

        @logged_action(_tr('打开永久删除确认框'))
        def confirm_permanent_delete(self):
            entries = self.chosen_entries()
            if not entries:
                return
            names = "\n".join(e.name for e in entries[:8]) + ("\n…" if len(entries) > 8 else "")
            dialog = Gtk.MessageDialog(transient_for=self, modal=True, destroy_with_parent=True,
                                       message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
                                       text=''.join([_tr('永久删除 '), f'{len(entries)}', _tr(' 项？')]))
            dialog.format_secondary_text(_tr('项目不会进入回收站，删除后无法恢复：\n') + names)
            dialog.add_button(_tr('取消'), Gtk.ResponseType.CANCEL)
            dialog.add_button(_tr('永久删除'), Gtk.ResponseType.ACCEPT)
            result = dialog.run()
            dialog.destroy()
            if result != Gtk.ResponseType.ACCEPT:
                return
            self.delete_permanently(entries)

        @logged_action(_tr('永久删除'))
        def delete_permanently(self, entries):
            failures = []
            for entry in entries:
                path = entry.path
                try:
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                except OSError as exc:
                    failures.append(f"{entry.name}：{exc}")
            self.after_delete()
            if failures:
                self.show_error(_tr('部分项目未能删除'), "\n".join(failures))

        def after_delete(self):
            self.owner.refresh()
            self.selection.clear()
            self.selection_anchor = None
            self.selection_changed()

        @logged_action(_tr('拖放项目'))
        def drop_selection(self, target_entry):
            target = self.owner.drop_target(target_entry)
            if not target:
                return
            kind, folder = target
            entries = [e for e in self.chosen_entries() if str(e.path) != str(target_entry.path)]
            if not entries:
                return
            if kind == "trash":
                self.trash_selected()
                return
            failures = []
            for entry in entries:
                source = entry.path
                try:
                    if source == folder:
                        continue
                    if source.is_dir() and folder.is_relative_to(source):
                        raise OSError(_tr('不能把文件夹移动到它自己内部'))
                    destination = folder / source.name
                    if destination.exists():
                        failures.append(''.join([f'{entry.name}', _tr('：目标已存在同名项目')]))
                        continue
                    source.rename(destination)
                except OSError as exc:
                    failures.append(f"{entry.name}：{exc}")
            self.after_delete()
            if failures:
                self.show_error(_tr('未能全部移动'), "\n".join(failures))

        @logged_action(_tr('显示错误弹窗'))
        def show_error(self, title, message):
            LOG.error("%s：%s", title, message)
            dialog = Gtk.MessageDialog(transient_for=self, modal=True, destroy_with_parent=True,
                                       message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE,
                                       text=title)
            dialog.format_secondary_text(message)
            dialog.run()
            dialog.destroy()

        @logged_action(_tr('打开桌面设置'))
        def show_desktop_settings(self):
            if open_adws_config("desktop"):
                return
            dialog = Gtk.Dialog(title=_tr('桌面设置'), transient_for=self, modal=True, destroy_with_parent=True)
            dialog.add_button(_tr('取消'), Gtk.ResponseType.CANCEL)
            dialog.add_button(_tr('应用'), Gtk.ResponseType.ACCEPT)
            dialog.set_default_size(400, -1)
            grid = Gtk.Grid(column_spacing=14, row_spacing=12, margin=20)

            family_label = Gtk.Label(label=_tr('字体：'), xalign=0)
            fonts = ["Noto Sans CJK SC", "LXGW WenKai Screen", "Noto Sans", "Sans"]
            if cfg.font_family not in fonts:
                fonts.insert(0, cfg.font_family)
            family = Gtk.ComboBoxText.new_with_entry()
            for font in fonts:
                family.append_text(font)
            family.set_active(fonts.index(cfg.font_family)) if cfg.font_family in fonts else family.set_entry_text(cfg.font_family)

            size_label = Gtk.Label(label=_tr('字号：'), xalign=0)
            size = Gtk.SpinButton.new_with_range(8, 20, 1)
            size.set_value(cfg.font_size)

            icon_label = Gtk.Label(label=_tr('图标大小：'), xalign=0)
            icons = Gtk.ComboBoxText()
            icons.append_text(_tr('小（32）'))
            icons.append_text(_tr('中（48）'))
            icons.append_text(_tr('大（64）'))
            icons.set_active({32: 0, 48: 1, 64: 2}.get(cfg.icon_size, 1))

            grid.attach(family_label, 0, 0, 1, 1)
            grid.attach(family, 1, 0, 1, 1)
            grid.attach(size_label, 0, 1, 1, 1)
            grid.attach(size, 1, 1, 1, 1)
            grid.attach(icon_label, 0, 2, 1, 1)
            grid.attach(icons, 1, 2, 1, 1)
            dialog.get_content_area().add(grid)
            dialog.connect("response", lambda w, result: LOG.info(_tr('弹窗响应：%s，结果=%s'), w.get_title(), result))
            dialog.show_all()

            if dialog.run() == Gtk.ResponseType.ACCEPT:
                chosen = family.get_active_text().strip()
                chosen_size = int(size.get_value())
                chosen_icon = {0: 32, 1: 48, 2: 64}.get(icons.get_active(), cfg.icon_size)
                self.owner.apply_desktop_settings(
                    family=chosen or cfg.font_family,
                    font_size=chosen_size,
                    icon_size=chosen_icon,
                )
            dialog.destroy()

        @staticmethod
        def format_size(size):
            value = float(size)
            for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
                if value < 1024 or unit == "TiB":
                    return f"{value:,.0f} {unit}" if unit == "B" else f"{value:,.1f} {unit}"
                value /= 1024

        @logged_action(_tr('打开属性'))
        def show_properties(self):
            entries = self.chosen_entries()
            if not entries:
                return None
            dialog = Gtk.Dialog(title=_tr('属性'), transient_for=self, modal=True, destroy_with_parent=True)
            dialog.add_button(_tr('关闭'), Gtk.ResponseType.CLOSE)
            dialog.set_default_size(460, -1)
            grid = Gtk.Grid(column_spacing=18, row_spacing=12, margin=20)
            if len(entries) == 1:
                entry = entries[0]
                modified = datetime.fromtimestamp(entry.modified).strftime("%Y-%m-%d %H:%M:%S") if entry.modified else _tr('未知')
                rows = [(_tr('名称'), entry.name), (_tr('类型'), entry.type_name), (_tr('位置'), str(entry.path)),
                        (_tr('大小'), _tr('文件夹（未递归统计）') if entry.kind == "directory" else self.format_size(entry.size)),
                        (_tr('修改日期'), modified)]
                if entry.error:
                    rows.append((_tr('状态'), entry.error))
            else:
                rows = [(_tr('项目'), ''.join([f'{len(entries)}', _tr(' 项（'), f"{sum((e.kind == 'directory' for e in entries))}", _tr(' 个文件夹）')])),
                        (_tr('位置'), str(directory)), (_tr('文件总大小'), self.format_size(sum(e.size for e in entries))),
                        (_tr('说明'), _tr('文件夹内容未递归统计')),
                        (_tr('名称'), "\n".join(e.name for e in entries[:8]) + ("\n…" if len(entries)>8 else ""))]
            for index, (name, value) in enumerate(rows):
                key_label = Gtk.Label(label=name, xalign=0, yalign=0)
                value_label = Gtk.Label(label=value, xalign=0, yalign=0, selectable=True)
                value_label.set_line_wrap(True)
                value_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                value_label.set_max_width_chars(52)
                grid.attach(key_label, 0, index, 1, 1)
                grid.attach(value_label, 1, index, 1, 1)
            dialog.get_content_area().add(grid)
            dialog.connect("response", lambda widget, _response: widget.destroy())
            dialog.connect("response", lambda w, result: LOG.info(_tr('弹窗响应：%s，结果=%s'), w.get_title(), result))
            dialog.show_all()
            return dialog

        @logged_action(_tr('全选'))
        def select_all(self):
            self.selection = set(self.rects)
            self.selection_changed()

        @logged_action(_tr('取消选择'))
        def clear_selection(self):
            self.selection.clear()
            self.selection_changed()

        @logged_action(_tr('打开选中项目'))
        def open_selected(self):
            if self.launch_dialog:
                self.launch_dialog.present()
                return
            self.pending_opens = [str(e.path) for e in self.chosen_entries()]
            self.launch_time = Gtk.get_current_event_time()
            self.process_open_queue()

        @logged_action(_tr('重置布局'))
        def reset_layout(self):
            self.owner.rearrange()

    class DesktopApplication(Gtk.Application):
        def __init__(self):
            super().__init__(application_id=APP_ID + (".Preview" if args.preview else ""),
                             flags=Gio.ApplicationFlags.FLAGS_NONE)
            self.entries = []
            self.by_path = {}
            self.positions = {}
            self.views = []
            self.hidden = False
            self.overview_active = False
            self.overview_events = []
            self.overview_watcher = None
            self.taskbar_watcher = None
            self.started = False
            self.refresh_pending = 0
            self.monitors_pending = 0
            self.watchers = []
            self.state_file = args.state or state_path()
            self.preference_keys = ("sort_by", "sort_descending", "folders_first", "icon_size",
                                    "cell_width", "cell_height", "show_hidden", "font_family", "font_size")
            self.started_at = time.monotonic()
            self.scan_count = 0
            self.status = None
            self.connect("startup", self.startup)
            self.connect("activate", self.activate)
            self.connect("shutdown", self.shutdown)

        def startup(self, *_):
            for name, callback in [("quit", self.quit), ("toggle", self.toggle), ("refresh", self.refresh)]:
                action = Gio.SimpleAction.new(name, None)
                action.connect("activate", lambda _a, _p, callback=callback: callback())
                self.add_action(action)
            if not args.preview:
                self.hold()
            for sig in (signal.SIGTERM, signal.SIGINT):
                GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self.on_signal)
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, self.on_toggle_signal)

        @logged_action(_tr('接收停止信号'))
        def on_signal(self):
            self.quit()
            return False

        def on_toggle_signal(self):
            self.toggle()
            return True

        def activate(self, *_):
            if self.started:
                return
            self.started = True
            css = ('* { font-family: "%s"; }' % cfg.font_family.replace('"', "")).encode("utf-8")
            self.font_provider = Gtk.CssProvider()
            self.font_provider.load_from_data(css)
            screen = Gdk.Screen.get_default()
            if screen is not None:
                Gtk.StyleContext.add_provider_for_screen(screen, self.font_provider,
                                                         Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            try:
                data = json.loads(self.state_file.read_text())
                if data.get("version") == 1 and isinstance(data.get("positions"), dict):
                    self.positions = {k: v for k, v in data["positions"].items() if isinstance(v, dict)}
                preferences = data.get("preferences", {})
                if isinstance(preferences, dict):
                    try:
                        updates = {k:v for k,v in preferences.items() if k in self.preference_keys and type(v) is type(getattr(cfg, k))}
                        restored = validate_config(replace(cfg, **updates))
                        for k in updates:
                            setattr(cfg, k, getattr(restored, k))
                    except ValueError as exc:
                        LOG.warning(_tr('忽略无法读取的视图偏好: %s'), exc)
            except (OSError, ValueError, AttributeError) as exc:
                if self.state_file.exists():
                    LOG.warning(_tr('忽略无法读取的布局状态: %s'), exc)
            if not args.preview and cfg.visibility_marker:
                self.taskbar_watcher = MarkerVisibility(cfg.visibility_marker, self.set_hidden).start()
            self.refresh()
            self.rebuild_monitors()
            display = Gdk.Display.get_default()
            display.connect("monitor-added", self.monitor_changed)
            display.connect("monitor-removed", self.monitor_changed)
            Gtk.IconTheme.get_default().connect("changed", self.theme_changed)
            self.watch_directory()
            if not args.preview:
                self.overview_watcher = OverviewWatcher(self.overview_changed).start()
            if args.smoke_test:
                GLib.timeout_add(int(args.smoke_test * 1000), self.finish_test)
            LOG.info(_tr('桌面图标层运行中：%s，%d 项，%d 个显示器'), directory, len(self.entries), len(self.views))

        def overview_changed(self, is_open):
            self.overview_events = (self.overview_events + [bool(is_open)])[-16:]
            self.overview_active = bool(is_open)
            for view in self.views:
                view.blur_cache = None
                view.cancel_rename()
                view.hover = None
                view.press = view.press_key = view.marquee = view.drag_point = None
                view.dragging = False
                if view.menu:
                    view.menu.popdown()
                view.apply_input_region()
                view.area.queue_draw()

        def finish_test(self):
            self.quit()
            return False

        def theme_changed(self, *_):
            for view in self.views:
                view.invalidate_icons()

        def refresh(self):
            LOG.debug(_tr('刷新桌面文件列表'))
            if self.refresh_pending:
                GLib.source_remove(self.refresh_pending)
                self.refresh_pending = 0
            try:
                self.entries = sort_entries(scan_desktop(directory, cfg.show_hidden), cfg.sort_by, cfg.sort_descending, cfg.folders_first)
                self.status = None
                self.scan_count += 1
            except OSError as exc:
                self.status = str(exc)
                LOG.warning(_tr('无法读取桌面: %s'), exc)
                self.entries = []
            self.by_path = {str(e.path): e for e in self.entries}
            for view in self.views:
                view.icons.clear()
                view.relayout()
            return False

        def changed(self, _monitor, file, other_file, event):
            # Parent watch catches a desktop directory created, removed or replaced later.
            if not self.refresh_pending:
                self.refresh_pending = GLib.timeout_add(180, self.refresh_and_watch)

        def refresh_and_watch(self):
            self.refresh_pending = 0
            self.refresh()
            self.watch_directory()
            return False

        def watch_directory(self):
            for watcher in self.watchers:
                watcher.cancel()
            self.watchers.clear()
            for path in (directory, directory.parent):
                if not path.is_dir():
                    continue
                try:
                    watcher = Gio.File.new_for_path(str(path)).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
                    if path == directory.parent:
                        watcher.connect("changed", self.parent_changed)
                    else:
                        watcher.connect("changed", self.changed)
                    self.watchers.append(watcher)
                except GLib.Error as exc:
                    LOG.warning(_tr('目录监视不可用 %s: %s'), path, exc)

        def parent_changed(self, watcher, file, other_file, event):
            if any(f is not None and f.get_path() == str(directory) for f in (file, other_file)):
                self.changed(watcher, file, other_file, event)

        def monitor_changed(self, *_):
            if not self.monitors_pending:
                self.monitors_pending = GLib.timeout_add(250, self.rebuild_monitors)

        def rebuild_monitors(self):
            self.monitors_pending = 0
            display = Gdk.Display.get_default()
            monitors = [display.get_monitor(i) for i in range(display.get_n_monitors())]
            named = [(monitor, connector_name(monitor, i)) for i, monitor in enumerate(monitors)]
            primary = display.get_primary_monitor()
            if cfg.monitor == "all":
                targets = named
            elif cfg.monitor == "primary":
                targets = [next(((m, k) for m, k in named if m == primary),
                                min(named, key=lambda pair: (pair[0].get_geometry().x,
                                                             pair[0].get_geometry().y), default=None))]
                targets = [pair for pair in targets if pair is not None]
            else:
                targets = [(m, k) for i, (m, k) in enumerate(named) if cfg.monitor in (k, str(i))]
                if not targets:
                    LOG.warning(_tr('显示器 %s 未连接，等待热插拔。可用：%s'), cfg.monitor, ", ".join(k for _, k in named))
            for view in self.views:
                view.destroy()
            if args.preview:
                targets = targets[:1]
            self.views = [DesktopWindow(self, m, k) for m, k in targets]
            if self.overview_active:
                self.overview_changed(True)
            return False

        def save_state(self):
            try:
                atomic_save_json(self.state_file, {"version": 1, "positions": self.positions,
                                                   "preferences": {k:getattr(cfg, k) for k in self.preference_keys}})
            except OSError as exc:
                LOG.warning(_tr('布局保存失败: %s'), exc)

        @logged_action(_tr('修改排序'))
        def set_sort(self, **changes):
            for key, value in changes.items():
                if key in ("sort_by", "sort_descending", "folders_first"):
                    setattr(cfg, key, value)
            self.rearrange()

        @logged_action(_tr('重新排列'))
        def rearrange(self):
            self.positions.clear()
            self.refresh()
            self.save_state()

        @logged_action(_tr('修改图标大小'))
        def change_icon_size(self, size):
            sizes = {32: (96, 92), 48: (112, 104), 64: (132, 124)}
            width, height = sizes[size]
            cfg.icon_size = size
            cfg.cell_width = width
            cfg.cell_height = max(height, size + cfg.font_size * 3 + 14)
            for view in self.views:
                if cfg.columns and not args.preview:
                    view.monitor_resized()
            self.refresh()
            self.save_state()

        @logged_action(_tr('修改隐藏文件显示'))
        def change_hidden_files(self, show):
            cfg.show_hidden = show
            self.refresh()
            self.save_state()

        def drop_target(self, entry):
            """Return (\"folder\", Path) or (\"trash\", None) when an entry accepts drops."""
            if entry is None or entry.error:
                return None
            if entry.kind == "directory":
                return ("folder", entry.path)
            if entry.kind == "application":
                try:
                    location = file_manager_location(entry.path)
                except (OSError, ValueError):
                    return None
                if not location:
                    return None
                parts = urlsplit(location)
                if parts.scheme == "trash":
                    return ("trash", None)
                if parts.scheme == "file" and parts.path:
                    candidate = Path(parts.path)
                    if candidate.is_dir():
                        return ("folder", candidate)
            return None

        @logged_action(_tr('应用桌面设置'))
        def apply_desktop_settings(self, family=None, font_size=None, icon_size=None):
            if family:
                cfg.font_family = family
            if font_size is not None:
                cfg.font_size = int(font_size)
            if icon_size is not None:
                sizes = {32: (96, 92), 48: (112, 104), 64: (132, 124)}
                width, height = sizes.get(int(icon_size), (cfg.cell_width, cfg.cell_height))
                cfg.icon_size = int(icon_size)
                cfg.cell_width = width
                cfg.cell_height = max(height, cfg.icon_size + cfg.font_size * 3 + 14)
            cfg.cell_height = max(cfg.cell_height, cfg.icon_size + cfg.font_size * 3 + 14)
            self.refresh()
            self.save_state()

        @logged_action(_tr('打开文件管理器定位文件'))
        def reveal_files(self, entries):
            uris = [entry.path.as_uri() for entry in entries]
            if not uris:
                return
            def completed(connection, result):
                try:
                    connection.call_finish(result)
                except GLib.Error:
                    self.open_directory()
            try:
                connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                connection.call("org.xfce.Thunar", "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1",
                                "ShowItems", GLib.Variant("(ass)", (uris, "")), None, Gio.DBusCallFlags.NONE, 1500, None, completed)
            except GLib.Error:
                self.open_directory()

        def toggle(self):
            self.set_hidden(not self.hidden)

        @logged_action(_tr('修改桌面图标显隐'))
        def set_hidden(self, hidden):
            hidden = bool(hidden)
            if self.hidden == hidden:
                return
            self.hidden = hidden
            LOG.info(_tr('桌面图标隐藏状态：%s'), hidden)
            for view in self.views:
                if view.menu:
                    view.menu.popdown()
                view.press = view.press_key = view.marquee = None
                view.dragging = False
                view.drag_point = None
                view.selection.clear()
                view.cancel_rename()
                view.fade.set_hidden(self.hidden)
                view.apply_input_region()

        @logged_action(_tr('打开终端'))
        def open_terminal(self):
            import subprocess
            executable = next((path for name in ("xdg-terminal-exec", "kitty", "foot", "alacritty", "konsole", "gnome-terminal", "xterm")
                               if (path := shutil.which(name))), None)
            if executable is None:
                LOG.warning(_tr('未找到可用的终端程序'))
                return
            try:
                process = subprocess.Popen([executable], cwd=directory, start_new_session=True)
                LOG.info(_tr('终端启动请求已提交：%s，PID=%s'), executable, process.pid)
            except OSError as exc:
                LOG.warning(_tr('打开终端失败: %s'), exc)

        @logged_action(_tr('打开桌面文件夹'))
        def open_directory(self):
            try:
                open_in_thunar(directory.as_uri(), Gdk.Display.get_default().get_app_launch_context())
                LOG.info(_tr('桌面文件夹打开请求已提交：%s'), directory)
            except Exception as exc:
                LOG.warning(_tr('打开桌面文件夹失败: %s'), exc)

        def diagnostics(self):
            return {"namespace": "niri-desktop-layer", "desktop": str(directory),
                    "entries": len(self.entries), "directory_scans": self.scan_count,
                    "elapsed_seconds": round(time.monotonic() - self.started_at, 2),
                    "sort": {"by": cfg.sort_by, "descending": cfg.sort_descending, "folders_first": cfg.folders_first},
                    "hidden": self.hidden, "overview": self.overview_active, "overview_events": self.overview_events, "error": self.status,
                    "windows": [{"output": v.monitor_key, "size": [v.area.get_allocated_width(), v.area.get_allocated_height()],
                                 "is_layer": GtkLayerShell.is_layer_window(v),
                                 "layer": "bottom" if not args.preview and GtkLayerShell.get_layer(v) == GtkLayerShell.Layer.BOTTOM else "preview",
                                 "exclusive_zone": GtkLayerShell.get_exclusive_zone(v) if not args.preview else None,
                                 "keyboard": ("none" if GtkLayerShell.get_keyboard_mode(v) == GtkLayerShell.KeyboardMode.NONE else "on-demand") if not args.preview else None,
                                 "visible_icons": len(v.rects), "pages": v.pages(),
                                 "selected": len(v.selection),
                                 "input_rectangles": [] if self.overview_active else [[0, 0, v.area.get_allocated_width(), v.area.get_allocated_height()]]}
                                for v in self.views]}

        @logged_action(_tr('退出桌面'))
        def shutdown(self, *_):
            if self.taskbar_watcher:
                self.taskbar_watcher.close()
            if self.overview_watcher:
                self.overview_watcher.close()
            if args.diagnostics:
                atomic_save_json(args.diagnostics, self.diagnostics())
            if args.snapshot and self.views:
                view = self.views[0]
                surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, view.area.get_allocated_width(), view.area.get_allocated_height())
                view.draw(view.area, cairo.Context(surface))
                args.snapshot.parent.mkdir(parents=True, exist_ok=True)
                surface.write_to_png(str(args.snapshot))
            for watcher in self.watchers:
                watcher.cancel()
            for source in (self.refresh_pending, self.monitors_pending):
                if source:
                    GLib.source_remove(source)
            for view in self.views:
                view.destroy()
            self.views.clear()

    application = DesktopApplication()
    failures = []
    previous_hook = sys.excepthook
    def fail_closed(kind, value, traceback):
        failures.append(value)
        previous_hook(kind, value, traceback)
        application.quit()
    sys.excepthook = fail_closed
    try:
        result = application.run(["desktop-layer"])
        return 1 if failures else result
    finally:
        sys.excepthook = previous_hook


def connector_name(monitor, index):
    """GTK3 exposes connector names via its legacy screen API."""
    try:
        from gi.repository import Gdk
        screen = Gdk.Screen.get_default()
        name = screen.get_monitor_plug_name(index)
        if name:
            return name
    except (AttributeError, OSError):
        pass
    return f"{monitor.get_manufacturer() or 'monitor'}-{monitor.get_model() or index}-{index}"


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""MNWS-Config — My Niri Workspace Solution 统一设置
"""
from __future__ import annotations
from mnws_i18n import tr as _tr

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from mnws_i18n import prepare_gtk_language
prepare_gtk_language()
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gdk, Gtk

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MARKER = "/* ==== MNWS 任务栏样式（自动生成）==== */"

DESKTOP_MARKER = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "desktop-hidden"
TASKBAR_MARKER = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "taskbar-hidden"

AUTOSTART_BEGIN = "// ==== MNWS 桌面图标层自启（自动生成）===="
AUTOSTART_END = "// ==== MNWS 桌面图标层自启 END ===="

FONT_PRESETS = [
    "JetBrainsMono Nerd Font Propo",
    "Noto Sans CJK SC",
    "Noto Serif CJK SC",
    "LXGW WenKai Screen",
    "LXGW WenKai GB Screen",
    "WenQuanYi Micro Hei",
    "Noto Sans Mono CJK SC",
]

DEFAULT_DESKTOP_PREFS = {
    "sort_by": "name",
    "sort_descending": False,
    "folders_first": True,
    "icon_size": 48,
    "cell_width": 112,
    "cell_height": 104,
    "show_hidden": False,
    "font_family": "Noto Sans CJK SC",
    "font_size": 10,
}
PREF_KEYS = tuple(DEFAULT_DESKTOP_PREFS)


def home() -> Path:
    return Path.home()


def live_style_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or home() / ".config") / "waybar/style-bottom.css"


def live_config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or home() / ".config") / "waybar/config-bottom.jsonc"


def project_state_path() -> Path:
    return PROJECT_ROOT / "src/niri-desktop-layer/state/layout.json"


def running_pids(pattern: str) -> list[int]:
    pids = []
    try:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                raw = (entry / "cmdline").read_bytes().split(b"\0")
            except (OSError, PermissionError):
                continue
            cmd = b" ".join(raw).decode(errors="replace")
            if not cmd:
                continue
            if int(entry.name) == os.getpid():
                continue
            if re.search(pattern, cmd):
                pids.append(int(entry.name))
    except OSError:
        pass
    return sorted(pids)


def desktop_pids() -> list[int]:
    return running_pids(r"[d]esktop-layer")


def taskbar_pids() -> list[int]:
    return running_pids(r"[c]onfig-bottom[.]jsonc")


def desktop_state_path() -> Path:
    for pid in desktop_pids():
        try:
            raw = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
            args = [part.decode(errors="replace") for part in raw if part]
            if "--state" in args:
                index = args.index("--state")
                if index + 1 < len(args):
                    return Path(args[index + 1])
        except OSError:
            continue
    xdg = Path(os.environ.get("XDG_STATE_HOME") or home() / ".local/state") / "niri-desktop-layer/layout.json"
    if xdg.exists():
        return xdg
    return project_state_path()


def desktop_service_script() -> Path:
    for pid in desktop_pids():
        try:
            raw = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
            args = [part.decode(errors="replace") for part in raw if part]
            for arg in args:
                candidate = Path(arg)
                if candidate.name == "desktop-layer" and candidate.is_file():
                    script = candidate.resolve().parent / "start-desktop-layer"
                    if script.exists():
                        return script
        except OSError:
            continue
    project_script = PROJECT_ROOT / "src/niri-desktop-layer/start-desktop-layer"
    if project_script.exists():
        return project_script
    return project_script


def desktop_daemon_script() -> Path:
    """返回桌面图标层实际可执行入口（desktop-layer），避免经过 systemd 封装。"""
    for pid in desktop_pids():
        try:
            raw = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
            args = [part.decode(errors="replace") for part in raw if part]
            for arg in args:
                candidate = Path(arg)
                if candidate.name == "desktop-layer" and candidate.is_file():
                    return candidate
        except OSError:
            continue
    project_script = PROJECT_ROOT / "src/niri-desktop-layer/desktop-layer"
    if project_script.exists():
        return project_script
    return project_script


def load_json(path: Path, fallback=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {} if fallback is None else fallback


def save_json_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def load_desktop_prefs() -> dict:
    prefs = dict(DEFAULT_DESKTOP_PREFS)
    data = load_json(desktop_state_path())
    stored = data.get("preferences")
    if isinstance(stored, dict):
        for key in PREF_KEYS:
            if key in stored and type(stored[key]) is type(prefs[key]):
                prefs[key] = stored[key]
    return prefs


def save_desktop_prefs(prefs: dict) -> Path:
    path = desktop_state_path()
    data = load_json(path)
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("positions"), dict):
        data["positions"] = {}
    data["version"] = 1
    data["preferences"] = {key: prefs[key] for key in PREF_KEYS}
    save_json_atomic(path, data)
    project = project_state_path()
    if path.resolve() != project.resolve():
        save_json_atomic(project, data)
    return path


def stop_processes(pids: list[int], timeout: float) -> bool:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and pids:
        if not any((Path("/proc") / str(pid)).exists() for pid in pids):
            break
        time.sleep(0.08)
    return not any((Path("/proc") / str(pid)).exists() for pid in pids)


def stop_desktop() -> bool:
    return stop_processes(desktop_pids(), 3.0)


def start_desktop() -> tuple[bool, str]:
    daemon = desktop_daemon_script()
    state = desktop_state_path()
    if not daemon.exists():
        return False, _tr('找不到桌面图标层入口：%s') % daemon
    env = {key: value for key, value in os.environ.items() if key != "GDK_BACKEND"}
    try:
        subprocess.Popen(
            [sys.executable, str(daemon), "--state", str(state)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True, _tr('已提交桌面图标层启动')
    except OSError as exc:
        return False, _tr('启动失败：%s') % exc


def restart_desktop() -> tuple[bool, str]:
    stop_desktop()
    time.sleep(0.3)
    return start_desktop()


def stop_taskbar() -> bool:
    return stop_processes(taskbar_pids(), 2.0)


def start_taskbar() -> tuple[bool, str]:
    from mnws_runtime import start_taskbar as start
    return start(live_config_path(), live_style_path())


def restart_taskbar() -> tuple[bool, str]:
    from mnws_layout import restart_taskbar as restart
    return restart(live_config_path(), live_style_path())


def set_marker(marker: Path, hidden: bool) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    if hidden:
        marker.touch(exist_ok=True)
    else:
        try:
            marker.unlink()
        except FileNotFoundError:
            pass


def toggle_taskbar_script() -> Path | None:
    candidates = [
        PROJECT_ROOT / "scripts/taskbar-toggle.sh",
        home() / ".local/bin/taskbar-toggle.sh",
    ]
    return next((path for path in candidates if path.exists()), None)


def run_taskbar_toggle() -> tuple[bool, str]:
    script = toggle_taskbar_script()
    if script is None:
        return False, _tr('找不到 taskbar-toggle.sh')
    env = {key: value for key, value in os.environ.items() if key != "GDK_BACKEND"}
    try:
        subprocess.Popen([str(script)], env=env, start_new_session=True)
        return True, _tr('已发送任务栏切换信号')
    except OSError as exc:
        return False, _tr('运行失败：%s') % exc


def niri_config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or home() / ".config") / "niri/config.kdl"


def autostart_script() -> Path:
    return desktop_service_script()


def autostart_line() -> str:
    return 'spawn-at-startup "%s"' % autostart_script()


def desktop_autostart_enabled() -> bool:
    path = niri_config_path()
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    from mnws_autostart import desktop_enabled
    return desktop_enabled(text)


def set_desktop_autostart(enabled: bool) -> tuple[bool, str]:
    """在 niri config.kdl 中加入/移除桌面图标层的 spawn-at-startup。"""
    path = niri_config_path()
    if not path.is_file():
        return False, _tr('找不到 niri 配置：%s') % path
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, _tr('读取失败：%s') % exc
    from mnws_autostart import set_desktop
    line = autostart_line()
    try:
        set_desktop(path, enabled)
    except (OSError, ValueError) as exc:
        return False, _tr('写入失败：%s') % exc
    if enabled:
        return True, _tr('已写入 niri 自启：%s\n（下次登录生效；可立即运行 mnws restart desktop 启动）') % line
    return True, _tr('已从 niri 配置移除桌面图标层自启行。')


def read_colors(path: Path) -> dict[str, str]:
    result = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return result
    for name, value in re.findall(r"@define-color\s+([\w-]+)\s+([^;]+);", text):
        result[name.strip()] = value.strip()
    return result


def resolve_color(value: str, colors: dict[str, str]) -> str:
    seen = set()
    current = value.strip()
    while current.startswith("@"):
        key = current[1:]
        if key not in colors or current in seen:
            break
        seen.add(current)
        current = colors[key].strip()
    return current


def parse_css_color(raw: str):
    raw = raw.strip().lower()
    match = re.fullmatch(
        r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)", raw
    )
    if match:
        r, g, b = (float(match.group(i)) / 255.0 for i in (1, 2, 3))
        a = float(match.group(4)) if match.group(4) is not None else 1.0
        return (r, g, b, a)
    match = re.fullmatch(r"#([0-9a-f]{3,8})", raw)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits) + "ff"
        elif len(digits) == 4:
            digits = "".join(ch * 2 for ch in digits)
        elif len(digits) == 6:
            digits += "ff"
        if len(digits) == 8:
            values = [int(digits[i:i + 2], 16) for i in (0, 2, 4, 6)]
            return tuple(values[i] / 255.0 for i in range(4))
    return None


def css_rgba(rgba) -> str:
    r = round(rgba.red * 255)
    g = round(rgba.green * 255)
    b = round(rgba.blue * 255)
    a = rgba.alpha
    if a >= 1.0:
        return "#%02x%02x%02x" % (r, g, b)
    return "rgba(%d, %d, %d, %.3f)" % (r, g, b, a)


def parse_css_length(value: str) -> float:
    match = re.fullmatch(r"([\d.]+)\s*(px|em)?", value.strip())
    if not match:
        return 12.0
    number = float(match.group(1))
    if match.group(2) == "em":
        return round(number * 16.6)
    return round(number)


def parse_css_font_size(value: str) -> float:
    match = re.fullmatch(r"([\d.]+)\s*(px|em)?", value.strip())
    if not match:
        return 16.6
    number = float(match.group(1))
    if match.group(2) == "em":
        number *= 16.6
    return number


def split_font_list(value: str) -> list[str]:
    names = []
    for part in re.split(r"\s*,\s*", value.strip() or ""):
        part = part.strip()
        if not part:
            continue
        if len(part) >= 2 and part.startswith('"') and part.endswith('"'):
            names.append(part[1:-1])
        else:
            names.append(part)
    return names


def join_font_list(names: list[str]) -> str:
    return ", ".join('"%s"' % name for name in names if name.strip())


def css_base_fonts(text: str):
    """从样式文件的全局 `*` 块读取字体列表和字号（未加任务栏覆盖时生效的默认值）。"""
    star = re.search(r"(?ms)^\s*\*\s*\{([^}]*)\}", text)
    if not star:
        return [], None
    body = star.group(1)
    family: list[str] = []
    size = None
    match = re.search(r"font-family\s*:\s*([^;}]+);", body)
    if match:
        family = split_font_list(match.group(1))
    match = re.search(r"font-size\s*:\s*([^;}]+);", body)
    if match:
        size = parse_css_font_size(match.group(1))
    return family, size


def read_taskbar_overrides():
    style = live_style_path()
    colors = read_colors(style.parent / "colors.css")
    text = style.read_text(encoding="utf-8") if style.exists() else ""
    base_family, base_size = css_base_fonts(text)
    font_family = (base_family or ["Noto Sans CJK SC"])[0]
    font_size = base_size if base_size is not None else 16.6
    if MARKER in text:
        base_text = text[: text.index(MARKER)]
        override = text[text.index(MARKER):]
    else:
        base_text = text
        override = ""
    use_theme = False
    color = None
    radius = 12.0
    found_bg = False
    found_radius = False
    for scope in (override, base_text):
        if not scope:
            continue
        box_block = re.search(r"window#waybar\s*>\s*box\s*\{([^}]*)\}", scope, re.S)
        if box_block:
            body = box_block.group(1)
            bg = re.search(r"background\s*:\s*([^;}]+);", body)
            if bg and not found_bg:
                value = bg.group(1).strip()
                use_theme = value.startswith("@")
                color = parse_css_color(resolve_color(value, colors))
                found_bg = True
            box_radius = re.search(r"border-radius\s*:\s*([^;}]+);", body)
            if box_radius and not found_radius:
                radius = parse_css_length(box_radius.group(1))
                found_radius = True
    font_block = re.search(r"window#waybar\s*\*\s*\{([^}]*)\}", override, re.S)
    if font_block:
        body = font_block.group(1)
        match = re.search(r"font-family\s*:\s*([^;}]+);", body)
        if match:
            names = split_font_list(match.group(1))
            if names:
                font_family = names[0]
        match = re.search(r"font-size\s*:\s*([^;}]+);", body)
        if match:
            font_size = parse_css_font_size(match.group(1))
    if color is None:
        theme = resolve_color("@surface_container_high", colors) if "@surface_container_high" in colors else "#000000"
        color = parse_css_color(theme) or (0.16, 0.14, 0.10, 0.92)
    return use_theme, color, radius, font_family, font_size


def write_taskbar_overrides(use_theme: bool, color_text: str, radius: int, restore: bool = False) -> Path:
    style = live_style_path()
    text = style.read_text(encoding="utf-8") if style.exists() else ""
    if MARKER in text:
        text = text[: text.index(MARKER)]
    if not restore:
        background = "@surface_container_high" if use_theme else color_text
        text += ("\n%s\nwindow#waybar > box {\n"
                 "    background: %s;\n"
                 "    border-radius: %dpx;\n"
                 "}\n\n.niri-taskbar button {\n"
                 "    border-radius: %dpx;\n"
                 "}\n") % (MARKER, background, radius, radius)
    style.write_text(text, encoding="utf-8")
    project_copy = PROJECT_ROOT / "config/waybar/style-bottom.css"
    if style.resolve() != project_copy.resolve():
        project_copy.write_text(text, encoding="utf-8")
    return style


def write_taskbar_font(font_family: str, font_size: float) -> Path:
    """只更新底部任务栏文字的字体与字号，不影响背景/圆角等其他样式。"""
    style = live_style_path()
    text = style.read_text(encoding="utf-8") if style.exists() else ""
    if MARKER in text:
        base, override = text.split(MARKER, 1)
    else:
        base, override = text, ""
    base_family, _ = css_base_fonts(base)
    primary = font_family.strip().strip('"')
    if not primary:
        primary = (base_family or ["Noto Sans CJK SC"])[0]
    names = [primary]
    for name in base_family:
        if name.lower() != primary.lower():
            names.append(name)
    override = re.sub(r"window#waybar\s*\*\s*\{[^}]*\}", "", override, flags=re.S)
    body = override.strip()
    font_block = (
        "window#waybar * {\n"
        "    font-family: %s;\n"
        "    font-size: %spx;\n"
        "}\n" % (join_font_list(names), ("%g" % font_size))
    )
    text = "%s\n\n%s\n" % (base.strip(), MARKER)
    if body:
        text += body + "\n\n"
    text += font_block
    style.write_text(text, encoding="utf-8")
    project_copy = PROJECT_ROOT / "config/waybar/style-bottom.css"
    if style.resolve() != project_copy.resolve():
        project_copy.write_text(text, encoding="utf-8")
    return style


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=_tr('MNWS 统一设置'))
    parser.add_argument("--tab", choices=("desktop", "taskbar", "components", "about"), default=None)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--restart-desktop", action="store_true", help=_tr('重启桌面图标层（不打开界面）'))
    parser.add_argument("--autostart", choices=("status", "on", "off"), default=None,
                        help=_tr('管理桌面图标层的 Niri 登录自启'))
    return parser.parse_args(argv)


def row_widget(label_text: str, widget) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    label = Gtk.Label(label=label_text, xalign=0, width_chars=10)
    box.pack_start(label, False, False, 0)
    if isinstance(widget, Gtk.Switch):
        widget.set_hexpand(False)
        widget.set_halign(Gtk.Align.START)
        widget.set_valign(Gtk.Align.CENTER)
        box.pack_start(widget, False, False, 0)
    else:
        box.pack_start(widget, True, True, 0)
    return box


def make_font_controls(family: str, size: float):
    """创建带预设的字体下拉框与字号调节控件。"""
    combo = Gtk.ComboBoxText.new_with_entry()
    for font in FONT_PRESETS:
        combo.append_text(font)
    if family in FONT_PRESETS:
        combo.set_active(FONT_PRESETS.index(family))
    else:
        combo.set_entry_text(family)
    spin = Gtk.SpinButton.new_with_range(8.0, 24.0, 0.5)
    spin.set_digits(1)
    spin.set_value(max(8.0, min(24.0, size)))
    return combo, spin


def cell_size_for_icon(size: int) -> tuple[int, int]:
    """根据图标尺寸推算桌面网格单元尺寸（与桌面层旧档位平滑衔接）。"""
    size = max(24, min(96, int(size)))
    if size <= 48:
        width = 96 + (size - 32) * 1.0
        height = 92 + (size - 32) * 0.75
    else:
        width = 112 + (size - 48) * 1.25
        height = 104 + (size - 48) * 1.25
    return round(width), round(height)


def dialog_box() -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
    box.set_margin_top(18)
    box.set_margin_bottom(18)
    box.set_margin_start(18)
    box.set_margin_end(18)
    return box


class AnimatedPages(Gtk.Box):
    """Notebook-compatible page API with a real GTK crossfade between pages."""
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        from mnws_layout import load_layout
        from mnws_panel_options import validate
        options = validate(load_layout().get('options', {}))
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE if options['tab_animations'] else Gtk.StackTransitionType.NONE)
        self.stack.set_transition_duration(options['animation_duration'])
        self.stack.set_homogeneous(True)
        switcher = Gtk.StackSwitcher(stack=self.stack)
        switcher.set_halign(Gtk.Align.CENTER)
        self.pack_start(switcher, False, False, 0)
        self.pack_start(self.stack, True, True, 0)
        self.count = 0

    def append_page(self, page, label):
        page.show()
        self.stack.add_titled(page, str(self.count), label.get_text())
        self.count += 1

    def get_current_page(self):
        return int(self.stack.get_visible_child_name() or 0)

    def set_current_page(self, index):
        self.stack.set_visible_child_name(str(index))


def on_settings_window_destroy(*_):
    def quit_when_closed():
        if Gtk.main_level() and not any(window.get_visible() and window.get_window_type() == Gtk.WindowType.TOPLEVEL
                                        for window in Gtk.Window.list_toplevels()):
            Gtk.main_quit()
        return False
    GLib.idle_add(quit_when_closed)


class ConfigWindow(Gtk.Window):
    def __init__(self, tab=None):
        super().__init__(title=_tr('桌面设置 — MNWS'))
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_default_size(600, 440)
        self.set_border_width(12)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(outer)
        self.notebook = AnimatedPages()
        outer.pack_start(self.notebook, True, True, 0)
        self.appearance_page = self.build_appearance_page()
        self.components_page = self.build_components_page()
        self.about_page = self.build_about_page()
        self.notebook.append_page(self.appearance_page, Gtk.Label(label=_tr('外观')))
        self.notebook.append_page(self.components_page, Gtk.Label(label=_tr('组件')))
        self.notebook.append_page(self.about_page, Gtk.Label(label=_tr('关于')))
        order = {"desktop": 0, "appearance": 0, "components": 1, "about": 2}
        if tab in order:
            self.notebook.set_current_page(order[tab])
        footer = Gtk.ButtonBox(orientation=Gtk.Orientation.HORIZONTAL)
        footer.set_halign(Gtk.Align.END)
        apply = Gtk.Button(label=_tr('应用'))
        apply.connect("clicked", self.apply_current)
        ok = Gtk.Button(label=_tr('确定'))
        ok.connect("clicked", self.apply_current_close)
        close = Gtk.Button(label=_tr('关闭'))
        close.connect("clicked", lambda _b: self.destroy())
        footer.pack_end(close, False, False, 0)
        footer.pack_end(ok, False, False, 0)
        footer.pack_end(apply, False, False, 0)
        outer.pack_end(footer, False, False, 0)
        self.connect("destroy", on_settings_window_destroy)
        self.show_all()

    def build_appearance_page(self):
        prefs = load_desktop_prefs()
        box = dialog_box()
        title = Gtk.Label(label=_tr('桌面图标文字'), xalign=0)
        title.get_style_context().add_class("title")
        box.pack_start(title, False, False, 0)
        self.family = Gtk.ComboBoxText.new_with_entry()
        fonts = ["Noto Sans CJK SC", "LXGW WenKai Screen", "Noto Sans", "Sans"]
        for font in fonts:
            self.family.append_text(font)
        if prefs["font_family"] in fonts:
            self.family.set_active(fonts.index(prefs["font_family"]))
        else:
            self.family.set_entry_text(prefs["font_family"])
        box.pack_start(row_widget(_tr('字体：'), self.family), False, False, 0)
        self.font_size = Gtk.SpinButton.new_with_range(8, 20, 1)
        self.font_size.set_value(prefs["font_size"])
        box.pack_start(row_widget(_tr('字号：'), self.font_size), False, False, 0)
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        box.pack_start(separator, False, False, 6)
        self.icon_size = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 24, 96, 2)
        self.icon_size.set_size_request(220, -1)
        self.icon_size.set_digits(0)
        self.icon_size.set_value(float(prefs["icon_size"]))
        self.icon_size.set_draw_value(True)
        self.icon_size.set_value_pos(Gtk.PositionType.RIGHT)
        box.pack_start(row_widget(_tr('图标大小：'), self.icon_size), False, False, 0)
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        box.pack_start(separator, False, False, 6)
        taskbar_title = Gtk.Label(label=_tr('底部任务栏文字'), xalign=0)
        taskbar_title.get_style_context().add_class("title")
        box.pack_start(taskbar_title, False, False, 0)
        _, _, _, taskbar_family, taskbar_size = read_taskbar_overrides()
        self.taskbar_family, self.taskbar_font_size = make_font_controls(taskbar_family, taskbar_size)
        box.pack_start(row_widget(_tr('字体：'), self.taskbar_family), False, False, 0)
        box.pack_start(row_widget(_tr('字号：'), self.taskbar_font_size), False, False, 0)
        hint = Gtk.Label(
            label=_tr('底部任务栏使用独立的字体/字号，顶部 waybar 与桌面图标文字不受影响。'), xalign=0
        )
        hint.get_style_context().add_class("dim-label")
        hint.set_line_wrap(True)
        box.pack_start(hint, False, False, 0)
        self.restart_desktop_check = Gtk.CheckButton(label=_tr('应用后立即重启桌面图标层'))
        self.restart_desktop_check.set_active(True)
        box.pack_start(self.restart_desktop_check, False, False, 0)
        return box

    def apply_current(self, _button=None, close_after: bool = False):
        errors = []
        if self.notebook.get_current_page() == 0:
            try:
                prefs = load_desktop_prefs()
                family = self.family.get_active_text() or prefs["font_family"]
                prefs["font_family"] = family.strip() or prefs["font_family"]
                prefs["font_size"] = int(self.font_size.get_value())
                prefs["icon_size"] = int(self.icon_size.get_value())
                cell_width, cell_height = cell_size_for_icon(prefs["icon_size"])
                prefs.update(cell_width=cell_width, cell_height=cell_height)
                prefs["cell_height"] = max(
                    prefs["cell_height"], prefs["icon_size"] + prefs["font_size"] * 3 + 14
                )
                save_desktop_prefs(prefs)
                _, _, _, current_family, current_size = read_taskbar_overrides()
                new_family = (self.taskbar_family.get_active_text() or current_family).strip()
                new_size = float(self.taskbar_font_size.get_value())
                if new_family != current_family or abs(new_size - current_size) > 0.05:
                    write_taskbar_font(new_family, new_size)
                if self.restart_desktop_check.get_active():
                    ok, text = restart_desktop()
                    if not ok:
                        errors.append(text)
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
        if errors:
            self.show_message(_tr('保存失败'), "\n".join(errors))
            return False
        if close_after:
            self.destroy()
        return True

    def apply_current_close(self, _button=None):
        self.apply_current(close_after=True)

    def build_components_page(self):
        box = dialog_box()
        section = Gtk.Label(label=_tr('桌面图标层'), xalign=0)
        section.get_style_context().add_class("title")
        box.pack_start(section, False, False, 0)
        self.desktop_switch = Gtk.Switch()
        self.desktop_switch.set_active(not DESKTOP_MARKER.exists())
        self.desktop_switch.connect("state-set", self.on_desktop_switch)
        box.pack_start(row_widget(_tr('显示桌面图标'), self.desktop_switch), False, False, 0)
        self.desktop_autostart = Gtk.CheckButton(
            label=_tr('随 Niri 登录自启（写入 niri config.kdl）'))
        self.desktop_autostart.set_active(desktop_autostart_enabled())
        self.desktop_autostart.connect("toggled", self.on_desktop_autostart)
        box.pack_start(self.desktop_autostart, False, False, 0)
        self.desktop_status = Gtk.Label(label=_tr('状态：检测中…'), xalign=0)
        box.pack_start(self.desktop_status, False, False, 0)
        desktop_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        restart = Gtk.Button(label=_tr('启动 / 重启'))
        restart.connect("clicked", self.action_restart_desktop)
        stop = Gtk.Button(label=_tr('停止'))
        stop.connect("clicked", self.action_stop_desktop)
        desktop_buttons.pack_start(restart, False, False, 0)
        desktop_buttons.pack_start(stop, False, False, 0)
        box.pack_start(desktop_buttons, False, False, 0)
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        box.pack_start(separator, False, False, 6)
        section = Gtk.Label(label=_tr('底部任务栏'), xalign=0)
        section.get_style_context().add_class("title")
        box.pack_start(section, False, False, 0)
        self.taskbar_switch = Gtk.Switch()
        self.taskbar_switch.set_active(not TASKBAR_MARKER.exists())
        self.taskbar_switch.connect("state-set", self.on_taskbar_switch)
        box.pack_start(row_widget(_tr('显示任务栏'), self.taskbar_switch), False, False, 0)
        self.taskbar_status = Gtk.Label(label=_tr('状态：检测中…'), xalign=0)
        box.pack_start(self.taskbar_status, False, False, 0)
        taskbar_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        restart_task = Gtk.Button(label=_tr('重启'))
        restart_task.connect("clicked", self.action_restart_taskbar)
        style_task = Gtk.Button(label=_tr('任务栏设置…'))
        style_task.connect("clicked", self.action_open_taskbar_style)
        taskbar_buttons.pack_start(restart_task, False, False, 0)
        taskbar_buttons.pack_start(style_task, False, False, 0)
        box.pack_start(taskbar_buttons, False, False, 0)
        hint = Gtk.Label(
            label=_tr('两个开关互相独立：桌面图标层使用 desktop-hidden 标记，任务栏使用 taskbar-hidden。'),
            xalign=0,
        )
        hint.get_style_context().add_class("dim-label")
        hint.set_line_wrap(True)
        box.pack_start(hint, False, False, 0)
        self.refresh_statuses()
        refresh = Gtk.Button(label=_tr('刷新状态'))
        refresh.connect("clicked", lambda _b: self.refresh_statuses())
        box.pack_end(refresh, False, False, 0)
        return box

    def on_desktop_switch(self, _switch, active: bool):
        set_marker(DESKTOP_MARKER, hidden=not active)
        if active and not desktop_pids():
            ok, text = start_desktop()
            if not ok:
                self.show_message(_tr('组件'), text)
        GLib.timeout_add(300, self.refresh_statuses)
        return False

    def on_desktop_autostart(self, button):
        if getattr(self, "_autostart_syncing", False):
            return
        ok, text = set_desktop_autostart(button.get_active())
        if not ok:
            self._autostart_syncing = True
            button.set_active(not button.get_active())
            self._autostart_syncing = False
            self.show_message(_tr('自启设置失败'), text)

    def on_taskbar_switch(self, _switch, active: bool):
        if active == (not TASKBAR_MARKER.exists()):
            return False
        ok, text = run_taskbar_toggle()
        if not ok:
            self.show_message(_tr('组件'), text)
        GLib.timeout_add(400, self.refresh_statuses)
        return False

    def refresh_statuses(self):
        desktop = desktop_pids()
        if desktop:
            self.desktop_status.set_text(_tr('状态：运行中（PID %s）') % ", ".join(map(str, desktop)))
        else:
            self.desktop_status.set_text(_tr('状态：未运行（开关仍会保留显示状态）'))
        taskbar = taskbar_pids()
        if taskbar:
            self.taskbar_status.set_text(_tr('状态：运行中（PID %s）') % ", ".join(map(str, taskbar)))
        else:
            self.taskbar_status.set_text(_tr('状态：未运行'))
        self.desktop_switch.set_active(not DESKTOP_MARKER.exists())
        self.taskbar_switch.set_active(not TASKBAR_MARKER.exists())
        self._autostart_syncing = True
        self.desktop_autostart.set_active(desktop_autostart_enabled())
        self._autostart_syncing = False
        return False

    def action_restart_desktop(self, _button=None):
        ok, text = restart_desktop()
        self.show_message(_tr('组件'), text if ok else _tr('操作失败：%s') % text)
        GLib.timeout_add(400, self.refresh_statuses)

    def action_stop_desktop(self, _button=None):
        ok = stop_desktop()
        self.show_message(_tr('组件'), _tr('桌面图标层已停止。') if ok else _tr('停止超时，仍有进程在运行。'))
        GLib.timeout_add(300, self.refresh_statuses)

    def action_restart_taskbar(self, _button=None):
        ok, text = restart_taskbar()
        self.show_message(_tr('组件'), text if ok else _tr('操作失败：%s') % text)
        GLib.timeout_add(400, self.refresh_statuses)

    def action_open_taskbar_style(self, _button=None):
        TaskbarStyleWindow()

    def action_open_layout(self, _button=None):
        script = PROJECT_ROOT / "tools/mnws_layout.py"
        if not script.exists():
            self.show_message(_tr('布局设置'), _tr('找不到 %s') % script)
            return
        env = {key: value for key, value in os.environ.items() if key != "GDK_BACKEND"}
        try:
            subprocess.Popen([sys.executable, str(script), "gui"], env=env,
                             start_new_session=True)
        except OSError as exc:
            self.show_message(_tr('布局设置'), _tr('启动失败：%s') % exc)

    def build_about_page(self):
        box = dialog_box()
        title = Gtk.Label(label="My Niri Workspace Solution (MNWS)", xalign=0)
        title.get_style_context().add_class("title")
        box.pack_start(title, False, False, 0)
        self.update_preview = Gtk.CheckButton(label=_tr('Beta 渠道（包含预发布版本）'))
        box.pack_start(self.update_preview, False, False, 0)
        self.update_button = Gtk.Button(label=_tr('检查更新'))
        self.update_button.set_halign(Gtk.Align.START)
        self.update_button.connect('clicked', self.check_updates)
        box.pack_start(self.update_button, False, False, 0)
        self.update_result = Gtk.Label(xalign=0, selectable=True)
        self.update_result.set_line_wrap(True)
        box.pack_start(self.update_result, False, False, 0)
        self.update_link = Gtk.LinkButton.new_with_label('https://github.com/Haisairova-Official/MNWS/releases', _tr('打开发布页面'))
        self.update_link.set_no_show_all(True)
        self.update_link.set_halign(Gtk.Align.START)
        box.pack_start(self.update_link, False, False, 0)
        prefs = load_desktop_prefs()
        info = [
            (_tr('项目目录'), str(PROJECT_ROOT)),
            (_tr('底部任务栏配置'), str(live_config_path())),
            (_tr('底部任务栏样式'), str(live_style_path())),
            (_tr('桌面布局状态'), str(desktop_state_path())),
            (_tr('桌面服务'), str(desktop_service_script())),
            (_tr('字体'), "%s / %dpx" % (prefs["font_family"], prefs["font_size"])),
            (_tr('桌面标记'), str(DESKTOP_MARKER)),
            (_tr('任务栏标记'), str(TASKBAR_MARKER)),
        ]
        text = "\n".join("%s：%s" % (name, value) for name, value in info)
        label = Gtk.Label(label=text, xalign=0, yalign=0, selectable=True)
        label.set_line_wrap(True)
        box.pack_start(label, False, False, 0)
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        box.pack_start(separator, False, False, 6)
        help_text = (
            _tr('常用命令：\n  mnws config           打开本设置\n  mnws check            查看组件状态\n  mnws restart taskbar  重启底部任务栏\n  mnws restart desktop  重启桌面图标层\n  mnws build-taskbar    重新编译任务栏模块')
        )
        help_label = Gtk.Label(label=help_text, xalign=0, yalign=0, selectable=True)
        help_label.set_line_wrap(True)
        box.pack_start(help_label, False, False, 0)
        return box

    def check_updates(self, _button=None):
        import threading
        from mnws_update import check_update
        preview = self.update_preview.get_active()
        self.update_preview.set_sensitive(False)
        self.update_button.set_sensitive(False)
        self.update_result.set_text(_tr('正在检查更新…'))
        self.update_link.hide()
        def finish(result, error):
            if not self.get_realized():
                return False
            self.update_button.set_sensitive(True)
            self.update_preview.set_sensitive(True)
            self.update_result.set_text(error or result['text'])
            if result and result['url']:
                self.update_link.set_uri(result['url'])
                self.update_link.show()
            return False
        def worker():
            try:
                result = check_update(preview=preview)
                GLib.idle_add(finish, result, None)
            except (OSError, ValueError, RuntimeError) as error:
                GLib.idle_add(finish, None, str(error))
        threading.Thread(target=worker, daemon=True).start()

    def show_message(self, title, message):
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, destroy_with_parent=True,
            message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()


def keep_scroll_for_page(container, scroll):
    """Wheel/touchpad input scrolls settings instead of silently editing values."""
    def forward(_control, event):
        scroll.emit("scroll-event", event.copy())
        return True  # Stop the control's default value-changing handler.

    def attach(widget):
        if isinstance(widget, (Gtk.ComboBox, Gtk.SpinButton, Gtk.Scale)):
            if getattr(widget, "_mnws_scroll_guard", False):
                return
            widget._mnws_scroll_guard = True
            widget.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
            widget.connect("scroll-event", forward)
        elif isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                attach(child)
    attach(container)


class TaskbarSettingsWindow(Gtk.Window):
    def __init__(self, tab=None, layout_file=None, open_plugin=None):
        super().__init__(title=_tr('任务栏设置 — MNWS'))
        self.layout_file = layout_file
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_default_size(820, 760)
        self.set_border_width(12)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(outer)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.notebook = AnimatedPages()
        outer.pack_start(self.notebook, True, True, 0)
        self.notebook.append_page(scroll, Gtk.Label(label=_tr('外观')))
        box = dialog_box()
        scroll.add(box)
        from mnws_layout import load_layout
        from mnws_panel_options import validate
        self.panel_layout = load_layout(self.layout_file)
        options = validate(self.panel_layout.get('options', {}))
        self.position = Gtk.ComboBoxText()
        for key, caption in [('bottom', _tr('底部')), ('top', _tr('顶部')), ('left', _tr('左侧')), ('right', _tr('右侧'))]:
            self.position.append(key, caption)
        self.position.set_active_id(options['position'])
        box.pack_start(row_widget(_tr('任务栏位置：'), self.position), False, False, 0)
        self.thickness = Gtk.SpinButton.new_with_range(24, 160, 1)
        self.thickness.set_value(options['thickness'])
        box.pack_start(row_widget(_tr('高度 / 竖栏宽度：'), self.thickness), False, False, 0)
        self.window_rows = Gtk.ComboBoxText()
        self.window_rows.append('1', _tr('单排（竖栏单列）'))
        self.window_rows.append('2', _tr('双排（竖栏双列）'))
        self.window_rows.set_active_id(str(options['window_rows']))
        def rows_changed(*_):
            minimum = 48 if self.window_rows.get_active_id() == '2' else 24
            self.thickness.set_range(minimum, 160)
        self.window_rows.connect('changed', rows_changed)
        rows_changed()
        box.pack_start(row_widget(_tr('应用窗口排列：'), self.window_rows), False, False, 0)
        self.panel_toggles = {}
        for key, caption in [('group_windows', _tr('堆叠同一应用的窗口')), ('window_peek', _tr('悬停显示窗口画面预览')),  ('window_animations', _tr('窗口悬停与聚焦颜色渐变')), ('tab_animations', _tr('设置选项卡淡入淡出'))]:
            control = Gtk.CheckButton(label=caption)
            control.set_active(options[key])
            self.panel_toggles[key] = control
            box.pack_start(control, False, False, 0)
        self.animation_duration = Gtk.SpinButton.new_with_range(80, 1000, 10)
        self.animation_duration.set_value(options['animation_duration'])
        box.pack_start(row_widget(_tr('动效时长（毫秒）：'), self.animation_duration), False, False, 0)
        self.panel_colors = {}
        for key, caption in [('hover_color', _tr('窗口悬停颜色：')), ('focus_color', _tr('聚焦窗口颜色：')), ('focus_text_color', _tr('聚焦窗口文字：')), ('urgent_color', _tr('需要关注的窗口：'))]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            control = Gtk.ColorButton(use_alpha=True)
            color_value = Gdk.RGBA()
            color_value.parse(options[key] or '#808080')
            control.set_rgba(color_value)
            follow = Gtk.CheckButton(label=_tr('跟随主题'))
            follow.set_active(not options[key])
            control.set_sensitive(bool(options[key]))
            follow.connect('toggled', lambda toggle, target=control: target.set_sensitive(not toggle.get_active()))
            row.pack_start(control, True, True, 0)
            row.pack_start(follow, False, False, 0)
            self.panel_colors[key] = (control, follow)
            box.pack_start(row_widget(caption, row), False, False, 0)
        use_theme, color, radius, font_family, font_size = read_taskbar_overrides()
        style_title = Gtk.Label(label=_tr('任务栏背景'), xalign=0)
        style_title.get_style_context().add_class("title")
        box.pack_start(style_title, False, False, 0)
        self.theme_background = Gtk.CheckButton(label=_tr('使用主题背景（跟随配色）'))
        self.theme_background.set_active(use_theme)
        self.theme_background.connect("toggled", self.on_theme_toggled)
        box.pack_start(self.theme_background, False, False, 0)
        self.color_button = Gtk.ColorButton()
        self.color_button.set_use_alpha(True)
        if color is not None:
            rgba = Gdk.RGBA()
            rgba.red, rgba.green, rgba.blue, rgba.alpha = color
            self.color_button.set_rgba(rgba)
        box.pack_start(row_widget(_tr('背景颜色：'), self.color_button), False, False, 0)
        self.radius = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 24, 1)
        self.radius.set_value(radius)
        self.radius.set_hexpand(True)
        self.radius.set_draw_value(True)
        self.radius.set_value_pos(Gtk.PositionType.RIGHT)
        box.pack_start(row_widget(_tr('圆角半径：'), self.radius), False, False, 0)
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        box.pack_start(separator, False, False, 6)
        font_title = Gtk.Label(label=_tr('任务栏文字'), xalign=0)
        font_title.get_style_context().add_class("title")
        box.pack_start(font_title, False, False, 0)
        self.family, self.font_size = make_font_controls(font_family, font_size)
        box.pack_start(row_widget(_tr('字体：'), self.family), False, False, 0)
        box.pack_start(row_widget(_tr('字号：'), self.font_size), False, False, 0)
        hint = Gtk.Label(label=_tr('仅作用于 MNWS 任务栏；竖栏以宽度作为厚度。其他组件始终保持单排。'), xalign=0)
        hint.get_style_context().add_class("dim-label")
        hint.set_line_wrap(True)
        box.pack_start(hint, False, False, 0)
        from mnws_layout_gui import LayoutWindow
        self.layout_editor = LayoutWindow(layout_file, open_plugin, parent=self, on_apply=self.apply_style)
        layout_page = self.layout_editor.content
        layout_page.set_border_width(18)
        self.notebook.append_page(layout_page, Gtk.Label(label=_tr('组件与插件')))
        # Protect both existing and subsequently added layout rows from wheel edits.
        def protect_layout(widget):
            scroller = self.layout_editor.list_box.get_parent()
            while scroller is not None and not isinstance(scroller, Gtk.ScrolledWindow):
                scroller = scroller.get_parent()
            if scroller is not None:
                keep_scroll_for_page(widget, scroller)
        self.layout_editor.protect_scroll = protect_layout
        protect_layout(layout_page)
        if tab == "layout" or open_plugin:
            self.notebook.set_current_page(1)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_hexpand(True)
        restore = Gtk.Button(label=_tr('恢复默认外观'))
        restore.connect("clicked", self.apply_restore)
        restore.set_no_show_all(True)
        def show_appearance_restore(*_):
            restore.set_visible(self.notebook.get_current_page() == 0)
        self.notebook.stack.connect("notify::visible-child", show_appearance_restore)
        show_appearance_restore()
        buttons.pack_start(restore, False, False, 0)
        apply = Gtk.Button(label=_tr('应用'))
        apply.connect("clicked", lambda _b: self.apply_style(close_after=False))
        ok = Gtk.Button(label=_tr('确定'))
        ok.connect("clicked", lambda _b: self.apply_style(close_after=True))
        close = Gtk.Button(label=_tr('关闭'))
        close.connect("clicked", lambda _b: self.destroy())
        buttons.pack_end(apply, False, False, 0)
        buttons.pack_end(ok, False, False, 0)
        buttons.pack_end(close, False, False, 0)
        outer.pack_end(buttons, False, False, 0)
        keep_scroll_for_page(box, scroll)
        self.on_theme_toggled()
        self.connect("destroy", on_settings_window_destroy)
        self.show_all()

    def on_theme_toggled(self, *_):
        self.color_button.set_sensitive(not self.theme_background.get_active())

    def apply_style(self, _button=None, close_after: bool = False) -> bool:
        try:
            from mnws_layout import load_layout, save_layout, apply_layout
            from mnws_panel_options import validate
            layout = self.layout_editor.collect_layout()
            options = dict(layout.get('options', {}))
            options.update(position=self.position.get_active_id(), thickness=self.thickness.get_value_as_int(),
                           window_rows=int(self.window_rows.get_active_id()), animation_duration=self.animation_duration.get_value_as_int())
            options.update({key: control.get_active() for key, control in self.panel_toggles.items()})
            options.update({key: '' if follow.get_active() else css_rgba(control.get_rgba()) for key, (control, follow) in self.panel_colors.items()})
            validate(options)
            layout['options'] = options
            color_text = css_rgba(self.color_button.get_rgba())
            family = (self.family.get_active_text() or "").strip()
            size = float(self.font_size.get_value())
            write_taskbar_overrides(
                self.theme_background.get_active(), color_text, int(self.radius.get_value())
            )
            if family:
                write_taskbar_font(family, size)
            ok, message = apply_layout(layout, restart=True)
            if not ok:
                raise ValueError(message)
            save_layout(layout, self.layout_file)
            self.layout_editor.status.set_text(_tr('设置已应用。'))
        except (OSError, ValueError) as exc:
            self.show_error(str(exc))
            return False
        if close_after:
            self.destroy()
        return True

    def apply_restore(self, _button=None):
        try:
            from mnws_panel_options import DEFAULTS
            self.position.set_active_id(DEFAULTS['position'])
            self.window_rows.set_active_id('1')
            self.thickness.set_value(DEFAULTS['thickness'])
            self.animation_duration.set_value(DEFAULTS['animation_duration'])
            for key, control in self.panel_toggles.items(): control.set_active(DEFAULTS[key])
            for _, follow in self.panel_colors.values(): follow.set_active(True)
            self.theme_background.set_active(True)
            self.radius.set_value(12)
            self.layout_editor.status.set_text(_tr('外观已恢复默认，点击应用后生效。'))
        except OSError as exc:
            self.show_error(str(exc))

    def show_error(self, text):
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, destroy_with_parent=True,
            message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
            text=_tr('保存失败'),
        )
        dialog.format_secondary_text(text)
        dialog.run()
        dialog.destroy()


# Compatibility entry point for existing launchers.
TaskbarStyleWindow = TaskbarSettingsWindow


def main(argv=None):
    args = arguments(argv)
    if args.check:
        from mnws_health import check
        return check()
    if args.restart_desktop:
        ok, text = restart_desktop()
        print(text)
        return 0 if ok else 1
    if args.autostart:
        if args.autostart == "status":
            print(_tr('桌面图标层自启：%s') % (_tr('已开启') if desktop_autostart_enabled() else _tr('未开启')))
            return 0
        ok, text = set_desktop_autostart(args.autostart == "on")
        print(text)
        return 0 if ok else 1
    GLib.set_prgname("mnws-config")
    Gdk.set_program_class("mnws-config")
    Gtk.init([])
    from mnws_theme import start as start_theme_watch
    start_theme_watch()
    if args.tab == "taskbar":
        TaskbarStyleWindow()
    else:
        ConfigWindow(tab=args.tab)
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

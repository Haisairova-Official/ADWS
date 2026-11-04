#!/usr/bin/python3
"""Reversible niri keyboard passthrough, supervised independently of VMware."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from adws_i18n import tr as _tr

KEY = "Ctrl+Alt+Shift+Q"
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
CONFIG = Path(os.environ.get("NIRI_CONFIG") or CONFIG_HOME / "niri/config.kdl").expanduser()
OPTIONS = CONFIG_HOME / "adws/vm-mode.json"
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "niri-vm-mode"
SCRIPT = Path(__file__).resolve()
BEGIN = '// ==== ADWS virtual machine mode BEGIN ===='
END = '// ==== ADWS virtual machine mode END ===='
LEGACY_BEGIN = '// ==== niri virtual machine mode BEGIN ===='
LEGACY_END = '// ==== niri virtual machine mode END ===='


def validated_options(options):
    if not isinstance(options, dict) or type(options.get('auto_switch')) is not bool:
        raise ValueError(_tr('自动切换必须为开启或关闭。'))
    key = options.get('shortcut')
    if not isinstance(key, str) or len(key) > 96:
        raise ValueError(_tr('请输入有效的切换快捷键。'))
    parts = key.strip().split('+')
    aliases = {'ctrl': 'Ctrl', 'control': 'Ctrl', 'alt': 'Alt', 'shift': 'Shift',
               'super': 'Super', 'win': 'Super', 'mod': 'Super'}
    modifiers = [aliases.get(part.strip().casefold()) for part in parts[:-1]]
    trigger = parts[-1].strip()
    if (not modifiers or None in modifiers or len(set(modifiers)) != len(modifiers)
            or not re.fullmatch(r'[A-Za-z0-9_]+', trigger) or trigger.casefold() in aliases):
        raise ValueError(_tr('快捷键至少包含一个修饰键和一个普通按键，例如 Ctrl+Alt+Shift+Q。'))
    modifiers = [name for name in ('Ctrl', 'Alt', 'Shift', 'Super') if name in modifiers]
    if len(trigger) == 1:
        trigger = trigger.upper()
    return {'auto_switch': options['auto_switch'], 'shortcut': '+'.join([*modifiers, trigger])}


def read_options(path=None):
    path = Path(path) if path is not None else OPTIONS
    if not path.exists():
        return {'auto_switch': True, 'shortcut': KEY}
    return validated_options(json.loads(path.read_text()))


def clean_integration(text):
    for begin, end in ((BEGIN, END), (LEGACY_BEGIN, LEGACY_END)):
        pattern = re.compile(r'(?m)^' + re.escape(begin) + r'\ninclude "([^"\n]+)"\n' + re.escape(end) + r'\n?')
        found = list(pattern.finditer(text))
        if text.count(begin) != len(found) or text.count(end) != len(found) or len(found) > 1:
            raise ValueError(_tr('虚拟机模式配置标记不完整，请检查 Niri 配置。'))
        text = pattern.sub('', text)
    return text


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".vm-mode-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@dataclass
class Token:
    value: str
    start: int
    end: int
    kind: str = "word"


def tokens(text: str) -> list[Token]:
    """Locate KDL nodes without treating braces in comments/strings as structure.

    This is a source-preserving scanner, not a replacement for niri's validator.
    """
    result = []
    i = 0
    while i < len(text):
        start = i
        if text[i] in " \t\r":
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        elif text.startswith("/*", i):
            i += 2
            depth = 1
            while depth and i < len(text):
                if text.startswith("/*", i):
                    depth += 1
                    i += 2
                elif text.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if depth:
                raise ValueError("KDL 注释没有结束")
        elif text[i] == "\\":
            # KDL line continuation, including optional whitespace/comment.
            end = text.find("\n", i)
            if end < 0:
                raise ValueError("KDL 续行没有结束")
            i = end + 1
        elif text.startswith("/-", i):
            i += 2
            result.append(Token("/-", start, i))
        elif match := re.match(r'r(#+)?"|#+"', text[i:]):
            opener = match[0]
            hashes = opener.count("#")
            body = i + len(opener)
            end = text.find('"' + "#" * hashes, body)
            if end < 0:
                raise ValueError("KDL 原始字符串没有结束")
            i = end + 1 + hashes
            result.append(Token(text[body:end], start, i, "string"))
        elif text[i] == '"':
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            else:
                raise ValueError("KDL 字符串没有结束")
            # Decode only includes later; other strings may contain KDL escapes
            # that are not JSON escapes.
            result.append(Token(text[start:i], start, i, "quoted"))
        elif text[i] in "{};\n=":
            i += 1
            result.append(Token(text[start:i], start, i, "symbol"))
        else:
            while i < len(text) and text[i] not in ' \t\r\n{};="\\' and not text.startswith(("//", "/*", "/-"), i):
                i += 1
            if i == start:
                raise ValueError(f"不能识别的 KDL 内容：{text[i:i + 20]}")
            result.append(Token(text[start:i], start, i))
    return result


def decode_string(token: Token) -> str:
    return json.loads(token.value) if token.kind == "quoted" else token.value


@dataclass
class Node:
    name: str
    start: int
    end: int
    header: list[Token]
    children: list[Node]
    disabled: bool


def parse_nodes(items: list[Token]) -> list[Node]:
    def delimiter(item, values):
        return item.kind == "symbol" and item.value in values

    def group(index):
        nodes = []
        while index < len(items):
            if delimiter(items[index], (";", "\n")):
                index += 1
                continue
            if delimiter(items[index], ("}",)):
                return nodes, index
            start = items[index].start
            disabled = items[index].value == "/-"
            if disabled:
                index += 1
            if index >= len(items):
                raise ValueError("KDL 节点没有名称")
            name = decode_string(items[index])
            index += 1
            header = []
            children = []
            while index < len(items) and not delimiter(items[index], ("{", "}", ";", "\n")):
                header.append(items[index])
                index += 1
            if index < len(items) and delimiter(items[index], ("{",)):
                children, index = group(index + 1)
                if index >= len(items) or not delimiter(items[index], ("}",)):
                    raise ValueError("KDL 花括号没有结束")
                end = items[index].end
                index += 1
            else:
                end = items[index - 1].end
            nodes.append(Node(name, start, end, header, children, disabled))
        return nodes, index

    result, index = group(0)
    if index != len(items):
        raise ValueError("KDL 存在多余的花括号")
    return result


def toggle_binding(script: Path = SCRIPT, shortcut: str = KEY) -> str:
    return ("binds {\n"
            f"    {shortcut} repeat=false allow-inhibiting=false hotkey-overlay-title=\"切换虚拟机 / 桌面模式\" "
            f"{{ spawn \"/usr/bin/python3\" {json.dumps(str(script), ensure_ascii=False)} \"toggle\"; }}\n"
            "}\n")


def snapshot_config(source: Path, directory: Path, *, passthrough: bool, shortcut: str = KEY) -> tuple[Path, dict[Path, str]]:
    """Mirror the complete include tree; never edit original binding files."""
    directory.mkdir(parents=True, exist_ok=True)
    originals = {}
    outputs = {}
    visiting = set()

    def copy(path):
        # Do not resolve symlinks: include paths are relative to the named file.
        path = Path(os.path.abspath(path.expanduser()))
        if path in visiting:
            raise ValueError(f"循环引用配置：{path}")
        if path in outputs:
            return outputs[path]
        visiting.add(path)
        text = path.read_text()
        originals[path] = text
        output = directory / (hashlib.sha256(str(path).encode()).hexdigest()[:20] + ".kdl")
        edits = []

        def inspect(nodes, disabled=False):
            for node in nodes:
                inactive = disabled or node.disabled
                if passthrough and node.name == "binds" and not inactive:
                    edits.append((node.start, node.end, "binds {}"))
                    continue
                if node.name == "include" and not inactive:
                    paths = [item for item in node.header if item.kind in ("quoted", "string")]
                    if len(paths) != 1:
                        raise ValueError(f"无法识别 include 路径：{path}")
                    item = paths[0]
                    included = Path(decode_string(item)).expanduser()
                    if not included.is_absolute():
                        included = path.parent / included
                    included = Path(os.path.abspath(included))
                    optional = any(
                        [x.value for x in node.header[i:i + 3]] == ["optional", "=", "true"]
                        for i in range(len(node.header) - 2)
                    )
                    if included.exists():
                        target = copy(included)
                    elif optional:
                        # Keep absent optional includes absent in the snapshot.
                        # Referencing the live path would allow new binds to leak.
                        target = directory / (hashlib.sha256(str(included).encode()).hexdigest()[:20] + ".absent.kdl")
                    else:
                        raise ValueError(f"找不到引用的配置：{included}")
                    edits.append((item.start, item.end, json.dumps(str(target), ensure_ascii=False)))
                inspect(node.children, inactive)

        inspect(parse_nodes(tokens(text)))
        for start, end, replacement in sorted(edits, reverse=True):
            text = text[:start] + replacement + text[end:]
        if path == Path(os.path.abspath(source.expanduser())) and passthrough:
            # Empty MRU binds suppress defaults, even when the original config
            # has no recent-windows section at all.
            overrides = directory / "passthrough-overrides.kdl"
            # SHORiN's fork falls back to a built-in standalone Mod tap when
            # there is no configured modifier binding. Removing binds alone
            # therefore enables its grid-overview fallback. Disable that too.
            grid = any(node.name == "grid-overview" and not node.disabled
                       for original in originals.values()
                       for node in parse_nodes(tokens(original)))
            defaults = "grid-overview { default-mod-action false; }\n" if grid else ""
            atomic_write(overrides, "recent-windows { off; binds {}; }\n" + defaults + toggle_binding(shortcut=shortcut))
            text += "\ninclude " + json.dumps(str(overrides), ensure_ascii=False) + "\n"
        atomic_write(output, text)
        outputs[path] = output
        visiting.remove(path)
        return output

    return copy(source), originals


def run_niri(*args, timeout=6):
    result = subprocess.run(["niri", *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or "niri 操作失败")
    return result.stdout


def validate(path):
    run_niri("validate", "-c", str(path))


def load(path):
    run_niri("msg", "action", "load-config-file", "--path", str(path))


def vmware_windows(windows):
    return [w for w in windows if str(w.get("app_id", "")).lower() in ("vmware", "vmware-player")]


def vmware_processes(proc: Path = Path("/proc")) -> set[int]:
    result = set()
    for path in proc.iterdir():
        if not path.name.isdigit():
            continue
        try:
            if path.stat().st_uid == os.getuid() and (path / "comm").read_text().strip() in ("vmware", "vmplayer"):
                result.add(int(path.name))
        except (OSError, ProcessLookupError):
            pass
    return result


def should_restore(processes, windows) -> bool:
    # Background VMs and vmware-tray do not count as an open Workstation UI.
    return not processes or not vmware_windows(windows)


def read_state():
    try:
        return json.loads((RUNTIME / "state.json").read_text())
    except (OSError, ValueError):
        return {}


def notify(title, message):
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "ADWS 虚拟机模式", "-t", "3000",
                          "-h", "string:x-canonical-private-synchronous:adws-vm-mode", _tr(title), _tr(message)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Controller:
    def __init__(self, normal: Path, options=None):
        self.normal = normal
        self.options = validated_options(options) if options is not None else read_options()
        self.active = False
        self.vm_config = None
        self.fallback = None
        self.generation = None
        self.reason = "就绪"
        self.missing_since = None
        self.ipc_failures = 0
        self.indicator = None
        self.manual_focus_id = None
        self.retry_after = 0
        self.auto_error = None

    def state(self):
        return {"mode": "vm" if self.active else "desktop", "shortcut": self.options['shortcut'],
                "reason": self.reason, "normal_config": str(self.normal),
                "fallback_config": str(self.fallback) if self.fallback else None,
                "vm_config": str(self.vm_config) if self.vm_config else None,
                "follow_focus": self.options['auto_switch'], "manual_focus_id": self.manual_focus_id,
                "session_socket": os.environ.get("NIRI_SOCKET"),
                "daemon_pid": os.getpid(), "indicator_pid": self.indicator.pid if self.indicator else None}

    def publish(self):
        atomic_write(RUNTIME / "state.json", json.dumps(self.state(), ensure_ascii=False) + "\n")

    def enter(self, *, automatic=False, windows=None):
        if self.indicator is None or self.indicator.poll() is not None or not (RUNTIME / "indicator.ready").exists():
            raise RuntimeError("模式提示尚未准备好，请稍后重试")
        if windows is None:
            windows = json.loads(run_niri("msg", "-j", "windows"))
        candidates = vmware_windows(windows)
        if should_restore(vmware_processes(), windows):
            raise RuntimeError("请先打开 VMware Workstation 窗口，再进入虚拟机模式")
        if automatic and not any(w.get("is_focused") for w in candidates):
            return False
        validate(self.normal)
        directory = Path(tempfile.mkdtemp(prefix="configs-", dir=RUNTIME))
        try:
            fallback, normal_sources = snapshot_config(self.normal, directory / "desktop", passthrough=False)
            preview, vm_sources = snapshot_config(self.normal, directory / "vm", passthrough=True,
                                                  shortcut=self.options['shortcut'])
            validate(fallback)
            validate(preview)
            if normal_sources != vm_sources or any(p.read_text() != content for p, content in normal_sources.items()):
                raise RuntimeError("配置正在被其他程序修改，请重试")
            selected = next((w for w in candidates if w.get("is_focused")), candidates[0])
            if automatic:
                # Validation and snapshotting take time. Never steal focus if
                # the user has already switched away while preparing the mode.
                focused = json.loads(run_niri("msg", "-j", "focused-window"))
                if not focused or not vmware_windows([focused]):
                    shutil.rmtree(directory, ignore_errors=True)
                    return False
            elif not selected.get("is_focused"):
                run_niri("msg", "action", "focus-window", "--id", str(selected["id"]))
            self.generation, self.fallback, self.vm_config = directory, fallback, preview
            # Save recovery information before switching, so a crash at any
            # subsequent point can be recovered by the restarted supervisor.
            self.active = True
            self.reason = "聚焦 VMware，自动进入" if automatic else "快捷键已交给虚拟机"
            self.publish()
            load(preview)
        except BaseException:
            if self.active:
                self.restore("切换失败，已恢复")
            else:
                shutil.rmtree(directory, ignore_errors=True)
            raise
        self.missing_since = None
        notify("虚拟机模式", _tr("按 %s 恢复桌面快捷键。") % self.options['shortcut'])
        return True

    def restore(self, reason="手动恢复", *, automatic=False):
        used_fallback = False
        try:
            validate(self.normal)
            load(self.normal)
        except Exception:
            if self.fallback is None or not self.fallback.exists():
                raise
            validate(self.fallback)
            load(self.fallback)
            used_fallback = True
        self.active = False
        self.reason = reason if not used_fallback else "原配置无效，已用进入前的快照恢复"
        self.publish()
        if self.generation and not used_fallback:
            shutil.rmtree(self.generation, ignore_errors=True)
            self.generation = self.vm_config = self.fallback = None
            self.publish()
        self.missing_since = None
        notify("桌面模式", _tr(self.reason) + _tr("，宿主快捷键已恢复。"))

    def manual(self, *, restore_only=False):
        if self.active or restore_only:
            self.restore()
        else:
            self.enter()
        windows = json.loads(run_niri("msg", "-j", "windows"))
        focused = next((w for w in windows if w.get("is_focused")), None)
        # A manual recovery stays in effect for this focus visit. Otherwise the
        # focus watcher would immediately undo the recovery shortcut.
        self.manual_focus_id = focused["id"] if focused else None
        self.publish()

    def check(self):
        if self.indicator is None or self.indicator.poll() is not None:
            if self.active:
                self.restore("模式提示退出，自动恢复", automatic=True)
            return
        try:
            windows = json.loads(run_niri("msg", "-j", "windows", timeout=2))
            self.ipc_failures = 0
        except Exception:
            self.ipc_failures += 1
            if self.ipc_failures >= 3 and self.active:
                self.restore("窗口监测中断，自动恢复", automatic=True)
            return
        focused = next((w for w in windows if w.get("is_focused")), None)
        if focused and self.manual_focus_id is not None and focused["id"] != self.manual_focus_id:
            self.manual_focus_id = None
            self.publish()
        if self.active and should_restore(vmware_processes(), windows):
            if self.missing_since is None:
                self.missing_since = time.monotonic()
            elif time.monotonic() - self.missing_since >= 1:
                self.restore("VMware 窗口已关闭，自动恢复", automatic=True)
            return
        self.missing_since = None
        if not self.options['auto_switch']:
            return
        # A brief null focus occurs while menus/layers grab keyboard focus.
        # Only actual focused application windows end a manual focus visit.
        if not focused:
            return
        is_vm = bool(vmware_windows([focused]))
        if self.active and not is_vm:
            self.restore("切到其他窗口，自动恢复", automatic=True)
        elif not self.active and is_vm and self.manual_focus_id != focused["id"]:
            if time.monotonic() < self.retry_after:
                return
            try:
                self.enter(automatic=True, windows=windows)
                self.auto_error = None
            except Exception as exc:
                self.retry_after = time.monotonic() + 5
                message = str(exc)
                if message != self.auto_error:
                    print(f"自动切换失败：{message}", file=sys.stderr, flush=True)
                    notify("自动进入虚拟机模式未完成", message)
                self.auto_error = message


def indicator():
    import cairo
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell

    if not GtkLayerShell.is_supported():
        raise RuntimeError("当前会话不支持模式提示")
    display = Gdk.Display.get_default()
    windows = []
    provider = Gtk.CssProvider()
    provider.load_from_data(b"""
        window { background-color: transparent; }
        label { border-radius: 9px; padding: 7px 13px; font-size: 12px;
                background: rgba(32, 36, 43, 0.87); color: #d4dbe7;
                border: 1px solid rgba(150, 162, 184, 0.4); }
        label.vm { background: rgba(24, 67, 47, 0.96); color: #d5ffe5;
                   border: 1px solid #54ba82; font-weight: bold; }
    """)

    def rebuild(*_args):
        for window, _label in windows:
            window.destroy()
        windows.clear()
        for index in range(display.get_n_monitors()):
            window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
            window.set_title("niri 模式提示")
            window.set_decorated(False)
            window.set_accept_focus(False)
            window.set_app_paintable(True)
            visual = window.get_screen().get_rgba_visual()
            if visual:
                window.set_visual(visual)
            GtkLayerShell.init_for_window(window)
            GtkLayerShell.set_namespace(window, "niri-vm-mode")
            GtkLayerShell.set_layer(window, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.NONE)
            GtkLayerShell.set_exclusive_zone(window, 0)
            GtkLayerShell.set_monitor(window, display.get_monitor(index))
            GtkLayerShell.set_anchor(window, GtkLayerShell.Edge.BOTTOM, True)
            GtkLayerShell.set_anchor(window, GtkLayerShell.Edge.RIGHT, True)
            GtkLayerShell.set_margin(window, GtkLayerShell.Edge.BOTTOM, 64)
            GtkLayerShell.set_margin(window, GtkLayerShell.Edge.RIGHT, 12)
            label = Gtk.Label()
            label.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            window.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            window.add(label)
            # A truly empty input region: the badge cannot steal clicks or keys.
            window.connect("realize", lambda w: w.get_window().input_shape_combine_region(cairo.Region(), 0, 0))
            windows.append((window, label))
            # Desktop mode has no surface; only active VM mode shows the badge.
        refresh()

    def refresh():
        state = read_state()
        active = state.get("mode") == "vm"
        for _window, label in windows:
            label.set_text(_tr("虚拟机模式  ·  %s 恢复") % state.get('shortcut', KEY))
            context = label.get_style_context()
            (context.add_class if active else context.remove_class)("vm")
            if active and not _window.get_visible():
                _window.show_all()
            elif not active and _window.get_visible():
                _window.hide()
        return True

    rebuild()
    display.connect("monitor-added", rebuild)
    display.connect("monitor-removed", rebuild)
    GLib.timeout_add(250, refresh)
    atomic_write(RUNTIME / "indicator.ready", str(os.getpid()))
    Gtk.main()


def daemon(normal: Path):
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = (RUNTIME / "daemon.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    if not os.environ.get("NIRI_SOCKET"):
        raise RuntimeError("未找到当前 niri 会话")
    controller = Controller(normal)
    old = read_state()
    if old.get("mode") == "vm" and old.get("session_socket") == os.environ.get("NIRI_SOCKET"):
        if old.get("fallback_config"):
            controller.fallback = Path(old["fallback_config"])
        controller.restore("模式守护进程重启，自动恢复")
    controller.publish()
    path = RUNTIME / "control.sock"
    path.unlink(missing_ok=True)
    stopped = False

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(path))
    os.chmod(path, 0o600)
    server.listen(4)
    server.settimeout(0.1)
    next_check = 0
    next_indicator = 0
    try:
        while not stopped:
            now = time.monotonic()
            if now >= next_check:
                controller.check()
                next_check = now + 0.2
            if (controller.indicator is None or controller.indicator.poll() is not None) and now >= next_indicator:
                (RUNTIME / "indicator.ready").unlink(missing_ok=True)
                controller.indicator = subprocess.Popen(["/usr/bin/python3", str(SCRIPT), "indicator"])
                controller.publish()
                next_indicator = now + 5
            try:
                connection, _ = server.accept()
            except socket.timeout:
                continue
            with connection:
                connection.settimeout(1)
                try:
                    command = connection.recv(64).decode().strip()
                    if command == "toggle":
                        controller.manual()
                    elif command == "restore":
                        controller.manual(restore_only=True)
                    elif command != "status":
                        raise ValueError("未知操作")
                    result = {"ok": True, **controller.state()}
                except Exception as exc:
                    print(f"模式操作失败：{exc}", file=sys.stderr, flush=True)
                    notify("模式切换未完成", str(exc))
                    result = {"ok": False, "error": str(exc), **controller.state()}
                try:
                    connection.sendall(json.dumps(result, ensure_ascii=False).encode())
                except OSError:
                    pass
    finally:
        if controller.active:
            controller.restore("模式守护进程停止，自动恢复")
        server.close()
        path.unlink(missing_ok=True)
        (RUNTIME / "indicator.ready").unlink(missing_ok=True)
        if controller.indicator and controller.indicator.poll() is None:
            controller.indicator.terminate()
            controller.indicator.wait(timeout=3)


def request(command):
    def connect():
        client = socket.socket(socket.AF_UNIX)
        client.settimeout(20)
        try:
            client.connect(str(RUNTIME / "control.sock"))
            client.sendall(command.encode())
            data = b""
            while chunk := client.recv(4096):
                data += chunk
            return json.loads(data)
        finally:
            client.close()

    try:
        return connect()
    except (FileNotFoundError, ConnectionRefusedError):
        if command == "restore":
            # Recovery also works when the supervisor is unavailable.
            controller = Controller(CONFIG)
            old = read_state()
            if old.get("fallback_config"):
                controller.fallback = Path(old["fallback_config"])
            controller.restore()
            return {"ok": True, **controller.state()}
        subprocess.run(["systemctl", "--user", "start", "niri-vm-mode.service"], check=True, timeout=5)
        for _ in range(20):
            try:
                return connect()
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.1)
        raise RuntimeError("无法连接模式守护进程")


def main():
    parser = argparse.ArgumentParser(description=f"niri 虚拟机模式，切换键 {KEY}")
    parser.add_argument("command", choices=("toggle", "restore", "status", "daemon", "indicator", "preview", "configure"))
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--auto-switch", choices=('on', 'off'))
    parser.add_argument("--shortcut")
    args = parser.parse_args()
    if args.command == "configure":
        from adws_vm_settings import apply_options
        options = read_options()
        if args.auto_switch is not None:
            options['auto_switch'] = args.auto_switch == 'on'
        if args.shortcut is not None:
            options['shortcut'] = args.shortcut
        print(json.dumps(apply_options(options, config=args.config), ensure_ascii=False))
    elif args.command == "daemon":
        daemon(args.config)
    elif args.command == "indicator":
        indicator()
    elif args.command == "preview":
        RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix="preview-", dir=RUNTIME))
        path, _ = snapshot_config(args.config, directory, passthrough=True, shortcut=read_options()['shortcut'])
        validate(path)
        print(path)
    else:
        result = request(args.command)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        notify("虚拟机模式", str(exc))
        sys.exit(1)

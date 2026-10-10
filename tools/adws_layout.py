#!/usr/bin/env python3
"""adws-layout — 底部任务栏组件布局：内置组件 + .mplg 插件 → Waybar 配置

布局状态与 .mplg 插件分离：
- taskbar-layout.json 只描述“组件列表、位置、顺序、宽度”；
- .mplg 直接丢进插件目录即可被发现；
- 宿主（当前为 Waybar 适配层）按布局渲染实际配置。
"""
from __future__ import annotations
from adws_i18n import tr as _tr

import argparse
import copy
import uuid
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parent

import adws_plugin as mplg  # noqa: E402  (同目录，供 CLI 复用扫描/解包)

USER_CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "adws"
USER_LAYOUT_PATH = USER_CONFIG_DIR / "taskbar-layout.json"
PROJECT_LAYOUT_PATH = PROJECT_ROOT / "config/taskbar-layout.json"
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")

TASKBAR_MARKER = "/* ==== ADWS 任务栏样式（自动生成）==== */"
CSS_START = "/* ==== ADWS 插件布局（自动生成）==== */"
CSS_END = "/* ==== ADWS 插件布局 END ==== */"

SLOT_NAMES = {"left": _tr('前部'), "center": _tr('中间'), "right": _tr('后部')}

BUILTIN_INFO = {
    "start": {"name": _tr('开始按钮'), "module": "custom/applauncher", "slot": "left"},
    "workspaces": {"name": _tr('工作区'), "module": "niri/workspaces", "slot": "left"},
    "windows": {"name": _tr('窗口图标（任务栏）'), "module": "cffi/niri-taskbar", "slot": "left"},
    "tray": {"name": _tr("系统托盘"), "module":"cffi/system-tray", "slot":"right"},
    "brightness": {"name": _tr("亮度"), "module":"cffi/system-brightness", "slot":"right"},
    "sound": {"name": _tr("声音"), "module":"cffi/system-sound", "slot":"right"},
    "sidebar": {"name": _tr("侧边栏"), "module": "cffi/system-sidebar", "slot": "right"},
    "clock": {"name": _tr('时钟'), "module": "clock", "slot": "right"},
}

INTERNAL_SPACE_MODULE = "cffi/desktop-space"
CUSTOM_PREFIX = "custom/adws-"
PLUGIN_PREFIXES = (CUSTOM_PREFIX, "cffi/adws-")


def home() -> Path:
    return Path.home()


def live_config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or home() / ".config") / "waybar/config-bottom.jsonc"


def live_style_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or home() / ".config") / "waybar/style-bottom.css"


def plugin_dir() -> Path:
    return mplg.plugin_dir()


def layout_path() -> Path:
    if USER_LAYOUT_PATH.is_file():
        return USER_LAYOUT_PATH
    return PROJECT_LAYOUT_PATH


def default_layout() -> dict:
    """Clean first-install/reset layout; existing v2 layouts remain authoritative."""
    return {"apiVersion": 2, "builtins": [
        {"id": key, "instance": key, "enabled": True, "slot": slot, "order": order}
        for slot, keys in (("left", ("start", "windows")),
                           ("right", ("sound", "brightness", "tray", "clock")))
        for order, key in enumerate(keys)
    ], "plugins": [], "options": {}}


def move_component(rows, identity, slot, anchor=None, after=False):
    """Reorder a single stable instance, including moves between regions."""
    if slot not in SLOT_NAMES:
        return False
    item = next((r for r in rows if r.get('instance', r.get('key')) == identity), None)
    if item is None or anchor == identity:
        return False
    target = next((r for r in rows if r.get('instance', r.get('key')) == anchor and r['slot'] == slot), None)
    rows.remove(item)
    item['slot'] = slot
    if target is not None:
        index = rows.index(target) + bool(after)
    else:
        rank = list(SLOT_NAMES).index(slot)
        index = next((i for i,r in enumerate(rows) if list(SLOT_NAMES).index(r['slot']) > rank), len(rows))
    rows.insert(index, item)
    return True


def load_layout(path: Path | None = None) -> dict:
    target = path or layout_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = default_layout()
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("builtins"), list):
        data["builtins"] = []
    if not isinstance(data.get("plugins"), list):
        data["plugins"] = []
    for item in data["plugins"]:
        if isinstance(item, dict) and isinstance(item.get("package"), str):
            item["package"] = mplg.api1.canonical_id(item["package"])
    data.setdefault("apiVersion", 1)
    data.setdefault("options", {})
    return normalize_layout(data)


def save_layout(data: dict, path: Path | None = None) -> Path:
    data = normalize_layout(data)
    target = path or USER_LAYOUT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, target)
    # User saves must not rewrite shipped defaults (or leak personal plugin
    # settings into the next source/release package).
    return target


def scan_available_plugins() -> list[dict]:
    """扫描插件目录中的 .mplg，返回带 manifest 的条目。"""
    results = []
    for path in mplg.scan_packages(plugin_dir()):
        ok, errors, manifest = mplg.validate_package(path)
        if not ok:
            results.append({"file": path, "ok": False, "errors": errors})
            continue
        manifest["id"] = mplg.api1.canonical_id(manifest["id"])
        results.append({"file": path, "ok": True, "manifest": manifest})
    chosen = {}
    for item in results:
        if item.get("ok"):
            key = item["manifest"]["id"]
            if key not in chosen or mplg.api1.package_version(item["manifest"]["version"]) > mplg.api1.package_version(chosen[key]["manifest"]["version"]):
                chosen[key] = item
    return [item for item in results if not item.get("ok")] + list(chosen.values())


def plugin_by_id(package_id: str) -> dict | None:
    for item in scan_available_plugins():
        if item.get("ok") and item["manifest"]["id"] == package_id:
            return item
    return None


def _strip_jsonc(text: str) -> str:
    out = []
    i = 0
    in_str = False
    esc = False
    while i < len(text):
        ch = text[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < len(text) and text[i + 1] == "/":
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and i + 1 < len(text) and text[i + 1] == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i = min(i + 2, len(text))
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _drop_trailing_commas(text: str) -> str:
    out = []
    i = 0
    in_str = False
    esc = False
    while i < len(text):
        ch = text[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < len(text) and text[j] in " \t\r\n":
                j += 1
            if j < len(text) and text[j] in "}]":
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def parse_jsonc(text: str) -> dict:
    clean = _drop_trailing_commas(_strip_jsonc(text))
    data = json.loads(clean)
    if not isinstance(data, dict):
        raise ValueError(_tr('配置文件根必须是对象'))
    return data


def read_live_config() -> dict | None:
    path = live_config_path()
    if not path.is_file():
        return None
    try:
        return parse_jsonc(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def default_base_config() -> dict:
    return {
        "include": ["modules.jsonc"],
        "layer": "bottom",
        "reload_style_on_change": True,
        "modes": {"invisible": {"visible": True, "passthrough": True, "exclusive": True}},
        "position": "bottom",
        "height": 36,
        "margin-bottom": 8,
        "margin-left": 8,
        "margin-right": 8,
        "spacing": 4,
        "fixed-center": True,
    }


def taskbar_library_path(layout: dict) -> Path:
    value = layout.get("options", {}).get("taskbar_library")
    if value:
        return Path(value).expanduser()
    return Path.home() / ".local/lib/waybar/libniri_taskbar.so"


def desktop_space_library_path(layout: dict, base: dict | None) -> Path:
    value = layout.get("options", {}).get("desktop_space_library")
    if value:
        return Path(value).expanduser()
    if base and isinstance(base.get(INTERNAL_SPACE_MODULE), dict):
        current = base[INTERNAL_SPACE_MODULE].get("module_path")
        if current:
            return Path(current).expanduser()
    candidate = PROJECT_ROOT / "src/niri-desktop-layer/integration/libwaybar-space.so"
    return candidate if candidate.is_file() else Path.home() / ".local/lib/waybar/libwaybar-space.so"


def _module_key(module: str) -> str:
    return module.split("/", 1)[-1]


def _plugin_module_id(package_id: str) -> str:
    return CUSTOM_PREFIX + package_id.replace(".", "-")


def module_css_id(module: str) -> str:
    name = module.split("/", 1)[-1]
    return "custom-" + name.replace(".", "-").replace("#", "-")


def normalize_plugin_defaults(manifest: dict) -> dict:
    defaults = manifest.get("defaults") or {}
    return {
        "slot": defaults.get("slot", "right"),
        "width": int(defaults.get("width", 0) or 0),
        "interval": defaults.get("interval", 5.0),
    }


def normalize_layout(data: dict) -> dict:
    """Migrate legacy singleton layouts to stable, independently configured instances.

    Version 2 lists are authoritative: a missing optional component stays absent.
    Window icons are the sole mandatory component, even in imported/edited JSON.
    """
    data = copy.deepcopy(data)
    legacy = data.get("apiVersion", 1) == 1
    raw = data.get("builtins", [])
    raw = raw if isinstance(raw, list) else []
    if legacy:
        known = {item.get("id") for item in raw if isinstance(item, dict)}
        raw = raw + [{"id": key, "enabled": key in ("start", "windows", "clock"),
                      "slot": info["slot"], "order": 0}
                     for key, info in BUILTIN_INFO.items() if key not in known]
    rows, used, singletons = [], set(), set()
    for value in raw:
        if not isinstance(value, dict) or value.get("id") not in BUILTIN_INFO:
            continue
        item = copy.deepcopy(value)
        key = item["id"]
        if key in ("windows", "workspaces", "tray", "brightness", "sound", "sidebar"):
            if key in singletons:
                continue
            singletons.add(key)
        instance = item.get("instance", key)
        if not isinstance(instance, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", instance):
            raise ValueError(_tr('组件实例标识无效。'))
        if instance in BUILTIN_INFO and instance != key:
            raise ValueError(_tr("组件实例标识无效。"))
        if key in ("windows", "workspaces", "tray", "brightness", "sound", "sidebar"):
            instance = key
        if instance in used:
            # Deterministic migration of hand-edited legacy duplicate records.
            index = 2
            while f"{key}-{index}" in used:
                index += 1
            instance = f"{key}-{index}"
        used.add(instance)
        item["instance"] = instance
        item["enabled"] = True if key == "windows" else item.get("enabled", True) is True
        item["slot"] = item.get("slot") if item.get("slot") in SLOT_NAMES else BUILTIN_INFO[key]["slot"]
        item["order"] = int(item.get("order", 0) or 0)
        if not isinstance(item.get("options", {}), dict):
            raise ValueError(_tr('组件设置格式无效。'))
        rows.append(item)
    if "windows" not in singletons:
        rows.append({"id": "windows", "instance": "windows", "enabled": True,
                     "slot": "left", "order": 1})
    data["builtins"] = rows
    plugins, used_plugins = [], set()
    for value in data.get("plugins", []):
        if not isinstance(value, dict) or not isinstance(value.get("package"), str):
            continue
        package = mplg.api1.canonical_id(value["package"])
        instance = value.get("instance", package)
        if not isinstance(instance,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,256}',instance):
            raise ValueError(_tr('组件实例标识无效。'))
        if instance in used_plugins:
            # Preserve formerly hand-edited duplicates as separate instances.
            index=2
            while f"plugin-{index}-{package}" in used_plugins:index+=1
            instance=f"plugin-{index}-{package}"
        used_plugins.add(instance)
        plugins.append({**copy.deepcopy(value), "package":package, "instance":instance})
    data["plugins"] = plugins
    data["apiVersion"] = 2
    if not isinstance(data.get("options"), dict):
        data["options"] = {}
    return data


def component_catalog(available: list[dict]) -> list[dict]:
    """Capabilities belong to the component type, never to editable instances."""
    catalog = [{"kind": "builtin", "key": key, **info,
                "repeatable": key in ("start", "clock"), "required": key == "windows",
                "icon": {"start": "view-app-grid-symbolic", "windows": "view-grid-symbolic",
                         "clock": "preferences-system-time-symbolic", "workspaces": "view-dual-symbolic", "tray":"view-more-symbolic", "brightness":"display-brightness-symbolic", "sound":"audio-volume-high-symbolic", "sidebar":"view-grid-symbolic"}[key]}
               for key, info in BUILTIN_INFO.items()]
    catalog.extend({"kind": "plugin", "key": entry["manifest"]["id"],
                    "name": _tr(entry["manifest"].get("name", entry["manifest"]["id"])),
                    "repeatable": entry["manifest"].get("isSingleOnly") is not True, "required": False, "icon": "application-x-addon-symbolic",
                    "file": entry["file"], "manifest": entry["manifest"]}
                   for entry in available if entry.get("ok"))
    return catalog


def new_builtin(key: str, rows: list[dict], options: dict) -> dict:
    if key not in BUILTIN_INFO:
        raise ValueError(_tr('未知组件。'))
    existing = [row for row in rows if row.get("id") == key]
    if existing and key in ("windows", "workspaces", "tray", "brightness", "sound", "sidebar"):
        raise ValueError(_tr('此组件只能添加一个。'))
    used = {row.get("instance", row.get("id")) for row in rows}
    instance = key if key not in used else f"{key}-{uuid.uuid4().hex[:12]}"
    overrides = {k: copy.deepcopy(v) for k,v in options.items()
                 if (key == "start" and k.startswith("start_")) or (key == "clock" and k == "clock")}
    return {"id": key, "instance": instance, "enabled": True,
            "slot": BUILTIN_INFO[key]["slot"], "order": len(rows), "options": overrides}


def new_plugin(manifest: dict, rows: list[dict]) -> dict:
    package=mplg.api1.canonical_id(manifest['id'])
    same=[row for row in rows if row.get('package')==package]
    if manifest.get('isSingleOnly') is True and any(row.get('enabled',False) for row in same):
        raise ValueError(_tr('此组件只能添加一个。'))
    inactive=next((row for row in same if not row.get('enabled',False)),None)
    if inactive is not None:
        inactive['enabled']=True
        return inactive
    defaults=normalize_plugin_defaults(manifest)
    used={row.get('instance',row['package']) for row in rows}
    instance=package if package not in used else 'plugin-'+uuid.uuid4().hex
    value={'package':package,'instance':instance,'enabled':True,'slot':defaults['slot'],
           'order':len(rows),'width':defaults['width'],'settings':{},'animations':False}
    rows.append(value)
    return value


def instance_options(layout: dict, item: dict) -> dict:
    return {**layout.get("options", {}), **item.get("options", {})}


def enabled_builtins(layout: dict) -> list[dict]:
    result = []
    for item in normalize_layout(layout)["builtins"]:
        key = item["id"]
        info = BUILTIN_INFO[key]
        suffix = "" if item["instance"] == key else "#" + item["instance"]
        result.append({**item, "name": info["name"], "module": info["module"] + suffix,
                       "width": 0, "kind": "builtin"})
    return result


def enabled_plugins(layout: dict, available: list[dict]) -> list[dict]:
    rows = []
    singles=set()
    for item in normalize_layout(layout).get("plugins", []):
        if not isinstance(item, dict) or not item.get("package"):
            continue
        package_id = item["package"]
        found = next((entry for entry in available
                      if entry.get("ok") and entry["manifest"]["id"] == package_id), None)
        if found is None:
            continue
        manifest = found["manifest"]
        if manifest.get('isSingleOnly') is True and item.get('enabled',False):
            if package_id in singles: raise ValueError(_tr('此组件只能添加一个。'))
            singles.add(package_id)
        suffix='' if item['instance']==package_id else '#'+item['instance']
        defaults = normalize_plugin_defaults(manifest)
        width = item.get("width", defaults["width"])
        if width is None:
            width = defaults["width"]
        rows.append({
            "package": package_id,
            "instance":item["instance"],
            "name": manifest.get("name", package_id),
            "kind": "plugin",
            "module": (_plugin_module_id(package_id).replace("custom/", "cffi/", 1)
                       if "panel.rows-v1" in manifest.get("interfaces", [])
                       else _plugin_module_id(package_id))+suffix,
            "entry": manifest["entry"],
            "language": manifest["language"],
            "enabled": bool(item.get("enabled", False)),
            "slot": item.get("slot", defaults["slot"]) or defaults["slot"],
            "order": int(item.get("order", 0) or 0),
            "width": max(0, int(width or 0)),
            "animations": item.get("animations") is True,
            "interval": float(item.get("settings", {}).get("interval", defaults["interval"]) or 0),
            "file": found["file"],
            "manifest": manifest,
            "settings": dict(item.get("settings") or {}),
        })
    return rows


def distro_logo():
    """Return the OS name and a Nerd Fonts / Font Logos glyph."""
    import platform
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        release = {}
    logos = {"arch": "\uf303", "debian": "\uf306", "ubuntu": "\uf31b",
             "fedora": "\uf30a", "linuxmint": "\uf30e", "manjaro": "\uf312",
             "nixos": "\uf313", "gentoo": "\uf30d", "opensuse": "\uf314"}
    candidates = [release.get("ID", ""), *release.get("ID_LIKE", "").split()]
    glyph = next((logos[key] for key in candidates if key in logos), "\uf17c")
    return release.get("PRETTY_NAME", "Linux"), glyph


def validate_start_images(options):
    if options.get("start_icon_mode") != "image":
        return
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib
    sizes = []
    for key in ("start_image", "start_hover_image"):
        path = str(options.get(key) or "")
        if not path and key == "start_hover_image":
            continue
        if not path:
            raise ValueError(_tr('请选择开始按钮的默认图片。'))
        try:
            image = GdkPixbuf.Pixbuf.new_from_file(str(Path(path).expanduser()))
        except GLib.Error as exc:
            raise ValueError(_tr('无法读取开始按钮图片：%s') % path) from exc
        sizes.append((image.get_width(), image.get_height()))
    if len(sizes) == 2 and sizes[0] != sizes[1]:
        raise ValueError(_tr('默认图片与悬停图片的尺寸必须完全一致。'))


def module_definition(module, base=None, config_path=None):
    definition, visited = {}, set()
    def read(obj, parent):
        includes = obj.get("include", [])
        if isinstance(includes, str):
            includes = [includes]
        for name in includes:
            path = Path(os.path.expandvars(name)).expanduser()
            path = (path if path.is_absolute() else parent / path).resolve()
            if path in visited:
                continue
            visited.add(path)
            read(parse_jsonc(path.read_text()), path.parent)
        value = obj.get(module)
        if isinstance(value, dict):
            definition.update(value)
    read(base if base is not None else (read_live_config() or default_base_config()), (config_path or live_config_path()).parent)
    return definition


def launcher_definition(base=None, config_path=None):
    definition = module_definition('custom/applauncher', base, config_path)
    if definition.get('format') in ('Apps', 'Start', '开始'):
        definition['format'] = _tr('开始')
    return definition


def start_right_command(options, instance, launcher):
    mode = options.get('start_right_mode', 'settings')
    if mode == 'settings':
        return shlex.join([sys.executable, str(PROJECT_ROOT/'tools/adws-config.py'),
                           '--tab', 'start', '--start-instance', instance])
    if mode == 'menu':
        return launcher
    if mode == 'terminal':
        return shlex.join([sys.executable, str(PROJECT_ROOT/'tools/adws_launcher.py'), '--terminal'])
    if mode == 'none':
        return ''
    if mode == 'custom':
        command = options.get('start_right_custom', '')
        if isinstance(command, str) and command.strip() and '\x00' not in command:
            return command.strip()
        raise ValueError(_tr('请输入右键自定义命令。'))
    raise ValueError(_tr('无效的开始按钮右键操作。'))


def render_waybar_config(layout: dict, available: list[dict] | None = None,
                         base: dict | None = None,
                         base_from_live: bool = True,
                         config_path: Path | None = None) -> dict:
    """按布局渲染底部任务栏 waybar 配置对象。"""
    layout = normalize_layout(layout)
    available = available if available is not None else scan_available_plugins()
    if base is None and base_from_live:
        base = read_live_config()
    if not isinstance(base, dict):
        base = default_base_config()
    cfg = json.loads(json.dumps(base))  # 深拷贝
    from adws_include import normalize_default_include
    normalize_default_include(cfg, config_path or live_config_path())
    # "中间" means the bar's geometric centre, independent of side widths.
    cfg["fixed-center"] = True
    # Popups inherit their layer-shell parent. Bottom puts descriptions behind tiles.
    if cfg.get("layer", "bottom") in ("bottom", "background"):
        cfg["layer"] = "top"

    options = layout.get("options", {}) if isinstance(layout.get("options"), dict) else {}

    from adws_panel_options import geometry
    panel, vertical = geometry(cfg, options)

    if ("start_label" in options or options.get("start_icon_mode") == "distro"
            or "start_launcher_command" in options or options.get("start_launcher_mode") == "adws"):
        import html
        definition = launcher_definition(cfg, config_path)
        if "start_label" in options or options.get("start_icon_mode") == "distro":
            text = distro_logo()[1] if options.get("start_icon_mode") == "distro" else str(options.get("start_label") or _tr('开始'))
            definition["format"] = html.escape(text).replace("{", "{{").replace("}", "}}")
        if "start_launcher_command" in options or options.get("start_launcher_mode") == "adws":
            from adws_launcher import native_menu_command
            command = native_menu_command() if options.get("start_launcher_mode") == "adws" else options["start_launcher_command"]
            if not isinstance(command, str) or not command.strip() or "\x00" in command:
                raise ValueError(_tr('请输入启动器命令。'))
            definition["on-click"] = command.strip()
        cfg["custom/applauncher"] = definition

    for key in list(cfg):
        if ('#' in key and key.split('#', 1)[0] in ('custom/applauncher', 'cffi/start-button', 'clock')) or key.startswith(PLUGIN_PREFIXES):
            cfg.pop(key)
    cfg.pop('cffi/start-button', None)
    items = enabled_builtins(layout) + enabled_plugins(layout, available)
    cfg.pop('custom/sidebar', None)  # Migrate the former unanchored launcher.
    from adws_launcher import native_menu_command
    for item in items:
        if item.get("id") != "start" or not item.get("enabled"):
            continue
        own = instance_options(layout, item)
        import html
        definition = launcher_definition(cfg, config_path)
        if "start_label" in own or own.get("start_icon_mode") == "distro":
            label = distro_logo()[1] if own.get("start_icon_mode") == "distro" else str(own.get("start_label") or _tr('开始'))
            definition["format"] = html.escape(label).replace("{", "{{").replace("}", "}}")
        if "start_launcher_command" in own or own.get("start_launcher_mode") == "adws":
            command = native_menu_command() if own.get("start_launcher_mode") == "adws" else own["start_launcher_command"]
            if not isinstance(command, str) or not command.strip() or "\x00" in command:
                raise ValueError(_tr('请输入启动器命令。'))
            definition["on-click"] = command.strip()
        definition['on-click-right'] = start_right_command(own, item['instance'], definition.get('on-click', 'fuzzel'))
        definition['tooltip'] = True
        definition['tooltip-format'] = _tr('开始')
        image_start = own.get("start_icon_mode") == "image"
        if image_start or definition.get("on-click") == native_menu_command():
            if image_start:
                validate_start_images(own)
            suffix = "" if item["instance"] == "start" else "#" + item["instance"]
            item["module"] = "cffi/start-button" + suffix
            cfg[item["module"]] = {
                "module_path": str(Path.home() / ".local/lib/waybar/libadws_panel.so"),
                "start_image": str(Path(own["start_image"]).expanduser().resolve()) if image_start else "",
                "start_hover_image": str(Path(own["start_hover_image"]).expanduser().resolve()) if image_start and own.get("start_hover_image") else "",
                "exec": definition.get("on-click", "fuzzel"),
                "start_animations": panel["window_animations"],
                "start_position": panel["position"], "animation_duration": panel["animation_duration"],
                "start_right_command": definition.get("on-click-right", ""),
                "start_middle_command": definition.get("on-click-middle", ""),
                "start_tooltip": _tr('开始'),
                "start_label": definition.get("format", _tr('开始')).replace("{{", "{").replace("}}", "}"),
                "vertical": vertical, "thickness": panel["thickness"],
            }
        else:
            definition['rotate'] = 90 if vertical else 0
            cfg[item["module"]] = definition
    slots = {"left": [], "center": [], "right": []}
    generated_modules: list[tuple[str, int]] = []

    for item in sorted(items, key=lambda entry: (entry.get("slot", "left"), entry.get("order", 0))):
        if not item.get("enabled"):
            continue
        slot = item.get("slot", "left")
        if slot not in slots:
            slot = "left"
        slots[slot].append(item)

    def defs_for(module: str) -> dict | None:
        if module in ("cffi/system-tray", "cffi/system-brightness", "cffi/system-sound", "cffi/system-sidebar"):
            return {"module_path":str(taskbar_library_path(layout)),"component":module.removeprefix("cffi/system-"),
                    "control_helper":str(PROJECT_ROOT / ("tools/adws_sidebar.py" if module == "cffi/system-sidebar" else "tools/adws_quick_controls.py")),
                    "control_output":cfg.get("output", "") if isinstance(cfg.get("output", ""),str) else "",
                    "vertical":vertical,"position":panel['position'],"thickness":panel['thickness']}
        if module == "cffi/niri-taskbar":
            base_def = cfg.get(module)
            if not isinstance(base_def, dict):
                base_def = {}
            result = {
                "module_path": str(taskbar_library_path(layout)),
                "show_all_outputs": base_def.get("show_all_outputs", False),
                "current_workspace_only": base_def.get("current_workspace_only", True),
                "vertical": vertical,
                "rows": panel['window_rows'],
                "group_windows": panel['group_windows'],
                "termination_mode": panel["termination_mode"],
                "position": panel['position'], "window_peek": panel['window_peek'],
                "window_animations": panel['window_animations'],
                "animation_duration": panel['animation_duration'],
                "preview_helper": str(PROJECT_ROOT / "tools/adws_window_preview.py"),
                "clock_control_helper": str(PROJECT_ROOT / "tools/adws_control_center.py"),
                "thickness": panel['thickness'],
            }
            if isinstance(base_def.get("apps"), dict):
                result["apps"] = base_def["apps"]
            for key in ("max_width", "icon_zone_fraction"):
                if key in base_def:
                    result[key] = base_def[key]
            configured_max = options.get("windows_max_width")
            if configured_max:
                result["max_width"] = int(configured_max)
            return result
        if module == INTERNAL_SPACE_MODULE:
            base_def = cfg.get(module)
            current = base_def.get("module_path") if isinstance(base_def, dict) else None
            return {
                "panel_mode": panel["panel_mode"], "split_panel": panel["split_panel"], "position": panel["position"],
                "split_center_corners": panel["split_center_corners"], "thickness": panel["thickness"],
                "window_animations": panel["window_animations"], "animation_duration": panel["animation_duration"],
                "module_path": str(desktop_space_library_path(layout, cfg)
                                   if not current else Path(current).expanduser()),
            }
        if module.startswith(PLUGIN_PREFIXES):
            item = next((entry for entry in items
                         if entry.get("module") == module), None)
            if item is None:
                return None
            defaults = normalize_plugin_defaults(item["manifest"])
            entry_path = None
            try:
                entry_root = mplg.materialize(item["file"])
                entry_path = entry_root / item["entry"]
            except ValueError:
                return None
            if not entry_path.is_file():
                return None
            try:
                settings = mplg.api1.settings(item['manifest'], item.get('settings', {}))
            except ValueError:
                # Let the isolated runner report invalid saved settings, not abort the whole layout.
                settings = item.get('settings', {})
            command = shlex.join(['env', 'ADWS_PLUGIN_INSTANCE='+item['instance'], sys.executable, str(mplg.project_root() / 'tools/adws_plugin_runner.py'), str(item['file']), '--settings-json', json.dumps(settings, ensure_ascii=False)])
            settings_command = shlex.join([
                sys.executable, str(PROJECT_ROOT / "tools/adws_layout.py"),
                "gui", "--plugin", item["package"]+"#"+item["instance"],
            ])
            controls = set(item["manifest"].get("controls", []))
            def control_command(action):
                if action not in controls:
                    return ""
                return shlex.join([
                    'env', 'ADWS_PLUGIN_INSTANCE='+item['instance'], sys.executable, str(entry_path), "--control", action,
                    "--settings-json", json.dumps(settings, ensure_ascii=False),
                ])
            if "panel.rows-v1" in item["manifest"].get("interfaces", []):
                return {
                    "module_path": str(Path.home() / ".local/lib/waybar/libadws_panel.so"),
                    "exec": command,
                    "right_command": settings_command,
                    "left_command": control_command("play-pause"),
                    "previous_command": control_command("previous"),
                    "next_command": control_command("next"),
                    **{key: str(settings.get(key, "")) for key in ("font_family", "primary_color", "secondary_color", "separator_color")},
                    "width": int(item.get("width", 420)),
                    "animations": item.get("animations") is True,
                    "vertical": vertical,
                    "thickness": panel['thickness'],
                    "widget_name": module_css_id(module),
                }
            module_cfg = {"return-type": "json", "exec": command, "tooltip": False,
                          "on-click-right": settings_command}
            alignment = item["manifest"].get("defaults", {}).get("align")
            if isinstance(alignment, (int, float)) and 0 <= alignment <= 1:
                module_cfg["align"] = alignment
            interval = item.get("interval")
            if interval:
                module_cfg["interval"] = max(0.5, float(interval))
            else:
                interval = defaults.get("interval")
                if interval:
                    module_cfg["interval"] = max(0.5, float(interval))
            return module_cfg
        return None  # 其余内置模块定义由 modules.jsonc 提供

    # 清掉上次由 ADWS 生成的插件模块定义
    for key in [key for key in cfg if key.startswith(PLUGIN_PREFIXES)]:
        cfg.pop(key, None)

    left_names = []
    for item in slots["left"]:
        module = item["module"]
        if module.startswith(PLUGIN_PREFIXES):
            module_cfg = defs_for(module)
            if module_cfg is None:
                continue
            cfg[module] = module_cfg
        elif module in ("cffi/niri-taskbar", "cffi/system-tray", "cffi/system-brightness", "cffi/system-sound", "cffi/system-sidebar"):
            cfg[module] = defs_for(module)
        left_names.append(module)

    center_names = [INTERNAL_SPACE_MODULE]
    if not isinstance(cfg.get("modes"), dict):
        cfg["modes"] = {"invisible": {"visible": True, "passthrough": True, "exclusive": True}}
    for item in slots["center"]:
        module = item["module"]
        if module.startswith(PLUGIN_PREFIXES):
            module_cfg = defs_for(module)
            if module_cfg is None:
                continue
            cfg[module] = module_cfg
        elif module in ("cffi/niri-taskbar", "cffi/system-tray", "cffi/system-brightness", "cffi/system-sound", "cffi/system-sidebar"):
            cfg[module] = defs_for(module)
        center_names.append(module)

    right_names = []
    for item in slots["right"]:
        module = item["module"]
        if module.startswith(PLUGIN_PREFIXES):
            module_cfg = defs_for(module)
            if module_cfg is None:
                continue
            cfg[module] = module_cfg
        elif module in ("cffi/niri-taskbar", "cffi/system-tray", "cffi/system-brightness", "cffi/system-sound", "cffi/system-sidebar"):
            cfg[module] = defs_for(module)
        right_names.append(module)

    if INTERNAL_SPACE_MODULE not in center_names:
        center_names.insert(0, INTERNAL_SPACE_MODULE)
    cfg[INTERNAL_SPACE_MODULE] = defs_for(INTERNAL_SPACE_MODULE)

    # 收集插件宽度用于 CSS（min-width 才能真正控制像素宽）
    css_rules = []
    for item in items:
        if item.get("enabled") and item.get("module", "").startswith(PLUGIN_PREFIXES):
            width = int(item.get("width", 0) or 0)
            if width > 0:
                css_rules.append((item["module"], width))

    # Waybar labels support rotation; retain included formats/click actions.
    for module in [name for name in left_names+center_names+right_names
                   if name.split('#',1)[0] == 'clock' or name.startswith('custom/')]:
        definition = module_definition(module, cfg, config_path)
        if module.split('#',1)[0] == 'clock':
            from adws_clock import definition as clock_definition
            item = next(entry for entry in items if entry.get('module') == module)
            definition = clock_definition(instance_options(layout, item), definition, PROJECT_ROOT, item.get('instance'))
        if module == 'custom/applauncher' and not definition:
            definition = launcher_definition(cfg, config_path)
        if vertical or 'position' in options:
            definition['rotate'] = 90 if vertical and module.split('#',1)[0] != 'clock' else 0
        cfg[module] = definition
    cfg["modules-left"] = left_names or []
    cfg["modules-center"] = center_names
    cfg["modules-right"] = right_names or []
    cfg["_adws_css_rules"] = css_rules
    cfg["_adws_options"] = {**options, **panel, "_occupied_slots": [slot for slot,names in (("left",left_names),("center",center_names),("right",right_names)) if any(n != INTERNAL_SPACE_MODULE for n in names)]}
    return cfg


def render_css_block(rules: list[tuple[str, int]], options=None) -> str:
    if not rules and options is None:
        return ""
    lines = [CSS_START]
    vertical = options is not None and options.get('position') in ('left', 'right')
    for module, width in rules:
        lines.append("#%s {\n    min-%s: %dpx;\n}" % (module_css_id(module), 'height' if vertical else 'width', width))
    if options is not None:
        from adws_panel_options import styles
        lines.append(styles(options))
    lines.append(CSS_END)
    return "\n".join(lines)


def patch_style(text: str, css_block: str) -> str:
    if css_block:
        if CSS_START in text and CSS_END in text:
            text = re.sub(re.escape(CSS_START) + r".*?" + re.escape(CSS_END),
                          css_block, text, flags=re.S)
        elif TASKBAR_MARKER in text:
            index = text.index(TASKBAR_MARKER)
            text = text[:index] + css_block + "\n\n" + text[index:]
        else:
            text = text.rstrip() + "\n\n" + css_block + "\n"
    else:
        if CSS_START in text and CSS_END in text:
            text = re.sub(re.escape(CSS_START) + r".*?" + re.escape(CSS_END),
                          "", text, flags=re.S).rstrip() + "\n"
    from adws_fonts import with_symbol_fallbacks
    return with_symbol_fallbacks(text)


def config_to_jsonc(cfg: dict) -> str:
    body = {key: value for key, value in cfg.items()
            if not key.startswith("_adws_")}
    return json.dumps(body, ensure_ascii=False, indent=2) + "\n"


def backup_file(path: Path) -> Path:
    backup = path.with_name(path.name + ".adws-bak")
    if path.is_file():
        shutil.copy2(path, backup)
    return backup


def apply_layout(layout: dict | None = None, restart: bool = False,
                 available: list[dict] | None = None,
                 config_path: Path | None = None,
                 style_path: Path | None = None) -> tuple[bool, str]:
    """写入 live waybar 配置与插件宽度 CSS，可选重启任务栏。"""
    config_path = config_path or live_config_path()
    style_path = style_path or live_style_path()
    layout = layout if layout is not None else load_layout()
    try:
        cfg = render_waybar_config(layout, available=available, config_path=config_path)
        config_text = config_to_jsonc(cfg)
        from adws_panel_options import surface_from_css
        old_style = style_path.read_text(encoding="utf-8") if style_path.exists() else ""
        css_options={**cfg.get("_adws_options", {}), **surface_from_css(old_style)}
        css_block = render_css_block(cfg.get("_adws_css_rules", []), css_options)
    except (OSError, ValueError) as exc:
        return False, _tr('渲染失败：%s') % exc

    from adws_health import validate_waybar
    errors = validate_waybar(config_path, style_path, cfg)
    if errors:
        return False, _tr('应用前检查失败：\n') + "\n".join(errors)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    style_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from adws_atomic import replace_files
        old_style = style_path.read_text(encoding="utf-8") if style_path.exists() else ""
        backup_file(config_path)
        backup_file(style_path)
        replace_files({config_path: config_text.encode('utf-8'),
                       style_path: patch_style(old_style, css_block).encode('utf-8')})
    except OSError as exc:
        return False, _tr('写入失败：%s') % exc

    message = _tr('已写入 %s（备份：%s.adws-bak）') % (config_path, config_path)
    if restart:
        ok, text = restart_taskbar(config_path, style_path)
        if not ok:
            return False, message + _tr('\n重启失败：') + text
        message += "\n" + text
    return True, message


def taskbar_pids() -> list[int]:
    from adws_runtime import pids
    return pids('taskbar')


def restart_taskbar(config_path: Path | None = None, style_path: Path | None = None) -> tuple[bool, str]:
    from adws_health import validate_waybar
    from adws_runtime import start_taskbar
    config_path = config_path or live_config_path()
    style_path = style_path or live_style_path()
    errors = validate_waybar(config_path, style_path)
    if errors:
        return False, "\n".join(errors)
    targets = taskbar_pids()
    for pid in targets:
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 2.0
    while set(targets) & set(taskbar_pids()):
        if time.monotonic() >= deadline:
            return False, _tr('旧任务栏尚未退出；未启动第二个实例。')
        time.sleep(0.08)
    ok, message = start_taskbar(config_path, style_path)
    return ok, message if not ok else _tr('底部任务栏已重启')


def cli_render(args) -> int:
    layout = load_layout(Path(args.layout) if args.layout else None)
    cfg = render_waybar_config(layout, base_from_live=not args.no_live)
    text = config_to_jsonc(cfg)
    if args.output:
        Path(args.output).expanduser().write_text(text, encoding="utf-8")
        print(_tr('已写入：%s') % args.output)
    else:
        sys.stdout.write(text)
    if args.style_out:
        block = render_css_block(cfg.get("_adws_css_rules", []), cfg.get("_adws_options", {}))
        Path(args.style_out).expanduser().write_text(block, encoding="utf-8")
        print(_tr('CSS 已写入：%s') % args.style_out)
    return 0


def cli_apply(args) -> int:
    layout = load_layout(Path(args.layout) if args.layout else None)
    ok, text = apply_layout(layout, restart=args.restart)
    print(text)
    return 0 if ok else 1


def cli_show(_args) -> int:
    data = load_layout()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def arguments(argv=None):
    parser = argparse.ArgumentParser(
        prog="adws-layout", description=_tr('任务栏组件布局：渲染 / 应用'),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("show", help=_tr('显示当前布局状态'))
    p.set_defaults(func=cli_show)

    p = sub.add_parser("render", help=_tr('渲染 Waybar 配置（不写入 live 配置）'))
    p.add_argument("--layout", help=_tr('布局文件'))
    p.add_argument("-o", "--output", help=_tr('输出 jsonc 路径'))
    p.add_argument("--style-out", help=_tr('把插件宽度 CSS 写到该文件'))
    p.add_argument("--no-live", action="store_true", help=_tr('不用 live 配置做底，使用内置模板'))
    p.set_defaults(func=cli_render)

    p = sub.add_parser("apply", help=_tr('写入 live 配置并可选重启任务栏'))
    p.add_argument("--layout", help=_tr('布局文件'))
    p.add_argument("--restart", action="store_true", help=_tr('写入后重启底部任务栏'))
    p.set_defaults(func=cli_apply)

    p = sub.add_parser("gui", help=_tr('打开任务栏组件与插件管理窗口'))
    p.add_argument("--layout", help=_tr('布局文件'))
    p.add_argument("--plugin", help=_tr('直接打开指定插件的设置'))
    p.add_argument("--start-instance", help=_tr("开始按钮实例"))
    p.set_defaults(func=cli_gui)

    return parser.parse_args(argv)


def cli_gui(args) -> int:
    import adws_layout_gui
    return adws_layout_gui.run(args.layout, args.plugin, args.start_instance)


def main(argv=None) -> int:
    args = arguments(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

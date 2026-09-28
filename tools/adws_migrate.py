#!/usr/bin/env python3
"""One-way migration of an existing MNWS installation to ADWS.

The command intentionally creates no MNWS compatibility links.  User data is
moved to the ADWS XDG locations and every edited configuration file receives a
recoverable ``.adws-migration.bak`` copy first.
"""
from __future__ import annotations

from adws_i18n import tr as _tr

import os
import json
from pathlib import Path
import shutil
import sys
import time
import re


ROOT = Path(__file__).resolve().parent.parent


def exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def backup_name(path: Path) -> Path:
    candidate = path.with_name(path.name + ".adws-migration.bak")
    if not exists(candidate):
        return candidate
    stamp = int(time.time())
    candidate = path.with_name(path.name + f".adws-migration-{stamp}.bak")
    count = 0
    while exists(candidate):
        count += 1
        candidate = path.with_name(path.name + f".adws-migration-{stamp}-{count}.bak")
    return candidate


def read_record(path):
    if not exists(path): return {}
    try:
        data = json.loads(path.read_text())
        if (not isinstance(data, dict) or not isinstance(data.get('root', ''), str)
                or not isinstance(data.get('migration_roots', []), list)
                or not all(isinstance(value, str) for value in data.get('migration_roots', []))):
            raise ValueError('Invalid installation record fields')
        return data
    except (OSError, ValueError) as error:
        raise ValueError(_tr('安装记录无效，未开始迁移：%s') % path) from error


def move_tree(old: Path, new: Path, messages: list[str]) -> bool:
    if not exists(old):
        return False
    new.parent.mkdir(parents=True, exist_ok=True)
    if not exists(new):
        os.replace(old, new)
        messages.append(_tr("已迁移：%s → %s") % (old, new))
        return True
    preserved = backup_name(old)
    os.replace(old, preserved)
    messages.append(_tr("ADWS 目录已存在，旧 MNWS 数据已保留在：%s") % preserved)
    return True


COMMAND_KEYS = {'exec', 'exec-if', 'command', 'launcher_command', 'start_launcher_command',
                'start_right_command', 'start_middle_command', 'previous_command', 'next_command',
                'on-click', 'on-click-right', 'on-click-middle', 'on-scroll-up', 'on-scroll-down'}


def translate_path(value, roots):
    # Match actual path boundaries, never arbitrary occurrences in names/URLs.
    mapped = False
    for old, new in sorted(roots, key=lambda pair: len(str(pair[0])), reverse=True):
        old = str(old)
        if value == old or value.startswith(old + '/'):
            value = str(new) + value[len(old):]
            mapped = True
            break
    if not mapped: return value
    for old, new in (('/tools/mnws_', '/tools/adws_'), ('/tools/mnws-config.py', '/tools/adws-config.py'),
                     ('/libmnws_panel.so', '/libadws_panel.so')):
        if old in value: value = value.replace(old, new)
    if value.endswith('/mnws'): value = value[:-4] + 'adws'
    return value


def module_name(value):
    for prefix in ('custom/mnws-', 'cffi/mnws-'):
        if value.startswith(prefix): return value.replace('/mnws-', '/adws-', 1)
    return value


def command_text(value, roots):
    # Quoted/unquoted shell words are rewritten in place; shell syntax is never executed.
    tokens = re.compile(r'"[^"\n]*"|\x27[^\x27\n]*\x27|[^\s;|&<>]+')
    def word(match):
        raw = match[0]
        quote = raw[0] if raw[0] in ('"', "'") else ''
        body = raw[1:-1] if quote else raw
        prefix = value[:match.start()].strip()
        executable = prefix in ('', 'spawn-at-startup', 'exec', 'sudo', 'env') or prefix.endswith((';', '|', '&'))
        if executable and body in ('mnws', 'mnws-config'):
            body = body.replace('mnws', 'adws', 1)
        else:
            body = translate_path(body, roots)
        return quote + body + quote
    return tokens.sub(word, value)


def translate_json(value, roots, key=''):
    if key == 'migration_roots': return value
    if isinstance(value, dict):
        return {module_name(k): translate_json(v, roots, k) for k, v in value.items()}
    if isinstance(value, list): return [translate_json(v, roots, key) for v in value]
    if not isinstance(value, str): return value
    if key in COMMAND_KEYS or key.startswith('on-click'):
        return command_text(value, roots)
    return module_name(translate_path(value, roots))


def rewrite(path: Path, messages: list[str], roots=()) -> bool:
    if not path.is_file():
        return False
    suffix = path.suffix
    path = path.resolve(strict=True)
    text = path.read_text(encoding="utf-8")
    if suffix in ('.json', '.jsonc'):
        from adws_layout import parse_jsonc
        original = parse_jsonc(text)
        translated = translate_json(original, roots)
        if translated == original: return False
        updated = json.dumps(translated, ensure_ascii=False, indent=2) + '\n'
    elif suffix == '.kdl':
        rows = []
        for row in text.splitlines(keepends=True):
            if row.lstrip().startswith('spawn-at-startup '):
                row = command_text(row, roots)
            for name in ('mnws-config', 'mnws-layout'):
                row = row.replace('app-id="^'+name+'$"', 'app-id="^'+name.replace('mnws','adws')+'$"')
            if row.lstrip().startswith('// ==== MNWS '): row = row.replace('MNWS', 'ADWS')
            rows.append(row)
        updated = ''.join(rows)
    elif suffix == '.css':
        updated = re.sub(r'([.#])mnws-', r'\1adws-', text)
        updated = updated.replace('#custom-mnws-', '#custom-adws-').replace('#cffi-mnws-', '#cffi-adws-')
        updated = updated.replace('/* ==== MNWS ', '/* ==== ADWS ')
    else:
        return False
    if updated == text:
        return False
    copy = backup_name(path)
    shutil.copy2(path, copy)
    temporary = path.with_name(path.name + ".adws-migration.tmp")
    temporary.write_text(updated, encoding="utf-8")
    temporary.chmod(path.stat().st_mode & 0o777)
    os.replace(temporary, path)
    messages.append(_tr("已更新配置：%s（备份：%s）") % (path, copy))
    return True


def retire_link(path: Path, messages: list[str]) -> None:
    if not path.is_symlink():
        return
    try:
        target = path.resolve(strict=False)
    except OSError:
        return
    raw = str(target).lower()
    if target.name in {"mnws", "mnws-config.py"} or "/mnws/" in raw:
        path.unlink()
        messages.append(_tr("已移除旧命令入口：%s") % path)


def migrate(
    config_home: Path,
    state_home: Path,
    data_home: Path,
    cache_home: Path,
    user_bin: Path,
    library_dir: Path,
    root: Path = ROOT,
) -> list[str]:
    """Migrate known ADWS-owned data without touching unrelated desktop data."""
    messages: list[str] = []
    # Validate both records before moving any tree or replacing a package.
    old_record = read_record(state_home/'mnws/install-record.json')
    read_record(state_home/'adws/install-record.json')
    roots = []
    # XDG paths change independently of the installation source directory.
    for directory in (config_home, state_home, data_home, cache_home):
        roots.append((directory/'mnws', directory/'adws'))
    roots.append((library_dir/'libmnws_panel.so', library_dir/'libadws_panel.so'))
    source_roots = []
    old_root = old_record.get('root')
    if isinstance(old_root, str) and Path(old_root).is_absolute() and len(Path(old_root).parts) > 2:
        roots.append((old_root, root))
        source_roots.append(old_root)
    for entry in (user_bin / "mnws", user_bin / "mnws-config"):
        if entry.is_symlink():
            target = entry.resolve(strict=False)
            if target.name == "mnws":
                roots.append((target.parent, root))
                source_roots.append(str(target.parent))
            elif target.name == "mnws-config.py":
                roots.append((target.parent.parent, root))
                source_roots.append(str(target.parent.parent))
    move_tree(config_home / "mnws", config_home / "adws", messages)
    move_tree(state_home / "mnws", state_home / "adws", messages)
    move_tree(cache_home / "mnws", cache_home / "adws", messages)
    importing_plugins = exists(data_home / "mnws") and not exists(data_home / "adws")
    move_tree(data_home / "mnws", data_home / "adws", messages)

    # Old plugins cannot be loaded by the new API.  Retain their packages for
    # manual porting while keeping the active ADWS scanner clean.
    plugin_dir = data_home / "adws/plugins"
    if importing_plugins and exists(plugin_dir):
        retired = data_home / "adws/legacy-mnws-plugins"
        if not exists(retired):
            os.replace(plugin_dir, retired)
            messages.append(_tr("旧插件已保留在：%s") % retired)
    official = root / "plugins/org.AkiACG_Community.NCMLyricsBar_1.1.0.mplg"
    if official.is_file():
        plugin_dir.mkdir(parents=True, exist_ok=True)
        target = plugin_dir / official.name
        content = official.read_bytes()
        if not exists(target) or target.read_bytes() != content:
            if exists(target):
                backup = backup_name(target)
                shutil.copy2(target, backup)
                messages.append(_tr('原插件包已备份：%s') % backup)
            from adws_atomic import replace_files
            replace_files({target: content})

    for name in ('taskbar-layout.json', 'taskbar-pins.json', 'setup.json', 'wallpaper.json'):
        rewrite(config_home/'adws'/name, messages, roots)
    rewrite(state_home/'adws/install-record.json', messages, roots)

    for name in ("config-bottom.jsonc", "style-bottom.css", "modules.jsonc", "colors.css"):
        rewrite(config_home / "waybar" / name, messages, roots)
    from adws_windows import config_path
    # Respect an explicitly selected Niri configuration as the floating rules do.
    niri = config_path() if os.environ.get('NIRI_CONFIG') else config_home/'niri/config.kdl'
    rewrite(niri, messages, roots)
    record = state_home/'adws/install-record.json'
    if record.is_file() and source_roots:
        data = json.loads(record.read_text())
        data['migration_roots'] = list(dict.fromkeys(data.get('migration_roots', []) + source_roots))
        from adws_atomic import replace_files
        replace_files({record: (json.dumps(data, ensure_ascii=False, indent=2)+'\n').encode()})

    retire_link(user_bin / "mnws", messages)
    retire_link(user_bin / "mnws-config", messages)
    old_library = library_dir / "libmnws_panel.so"
    if old_library.is_file():
        retired = backup_name(old_library)
        os.replace(old_library, retired)
        messages.append(_tr("旧动态库已保留在：%s") % retired)
    return messages


def main() -> int:
    home = Path.home()
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    state = Path(os.environ.get("XDG_STATE_HOME") or home / ".local/state")
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share")
    cache = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    try:
        messages = migrate(config, state, data, cache, home / ".local/bin", home / ".local/lib/waybar")
    except (OSError, ValueError) as error:
        print(_tr('迁移未完成：%s') % error, file=sys.stderr)
        return 1
    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

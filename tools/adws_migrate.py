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
import time


ROOT = Path(__file__).resolve().parent.parent


def exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def backup_name(path: Path) -> Path:
    candidate = path.with_name(path.name + ".adws-migration.bak")
    if not exists(candidate):
        return candidate
    return path.with_name(path.name + f".adws-migration-{int(time.time())}.bak")


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


def rewrite(path: Path, messages: list[str], roots=()) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    text = path.read_text(encoding="utf-8")
    updated = text
    for index, (old, _) in enumerate(roots):
        updated = updated.replace(str(old), f"__ADWS_SOURCE_ROOT_{index}__")
    updated = updated.replace("MNWS", "ADWS").replace("Mnws", "Adws").replace("mnws", "adws")
    for index, (_, new) in enumerate(roots):
        updated = updated.replace(f"__ADWS_SOURCE_ROOT_{index}__", str(new))
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
    roots = []
    try:
        old_root = json.loads((state_home / "mnws/install-record.json").read_text()).get("root")
        if isinstance(old_root, str) and Path(old_root).is_absolute() and len(Path(old_root).parts) > 2:
            roots.append((old_root, root))
    except (OSError, ValueError):
        pass
    for entry in (user_bin / "mnws", user_bin / "mnws-config"):
        if entry.is_symlink():
            target = entry.resolve(strict=False)
            if target.name == "mnws":
                roots.append((target.parent, root))
            elif target.name == "mnws-config.py":
                roots.append((target.parent.parent, root))
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
        shutil.copy2(official, plugin_dir / official.name)

    for directory in (config_home / "adws", state_home / "adws"):
        if directory.is_dir() and not directory.is_symlink():
            for file in directory.rglob("*.json"):
                rewrite(file, messages, roots)

    for name in ("config-bottom.jsonc", "style-bottom.css", "modules.jsonc", "colors.css"):
        rewrite(config_home / "waybar" / name, messages, roots)
    rewrite(config_home / "niri/config.kdl", messages, roots)

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
    messages = migrate(config, state, data, cache, home / ".local/bin", home / ".local/lib/waybar")
    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

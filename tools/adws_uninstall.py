"""Interactive removal of ADWS-owned integration files, never desktop contents."""
from adws_i18n import tr as _tr
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import subprocess

from adws_health import config_home, state_home

ROOT = Path(__file__).resolve().parent.parent


def inventory_path():
    return state_home() / 'adws/install-record.json'


def read_inventory():
    try:
        data = json.loads(inventory_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_inventory(data):
    path = inventory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    os.replace(temporary, path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def library_sources():
    names = ('libniri_taskbar.so', 'libwaybar-space.so', 'libadws_panel.so')
    if (ROOT / 'prebuilt/manifest.json').is_file():
        return {name: ROOT / 'prebuilt' / name for name in names}
    return {
        'libniri_taskbar.so': ROOT / 'src/niri-taskbar/target/release/libniri_taskbar.so',
        'libwaybar-space.so': ROOT / 'src/niri-desktop-layer/integration/libwaybar-space.so',
        'libadws_panel.so': ROOT / 'src/panel-rows/libadws_panel.so',
    }


def record(config=None):
    data = read_inventory()
    configs = set(data.get('configs', []))
    if config:
        configs.add(str(Path(config).absolute()))
    data['configs'] = sorted(configs)
    libraries = data.setdefault('libraries', {})
    for name, source in library_sources().items():
        installed = Path.home() / '.local/lib/waybar' / name
        if source.is_file() and installed.is_file() and digest(source) == digest(installed):
            libraries[name] = digest(installed)
    data['root'] = str(ROOT)
    save_inventory(data)


def ask(prompt, default):
    while True:
        answer = input(prompt).strip().lower()
        if not answer:
            return default
        if answer in ('y', 'yes'):
            return True
        if answer in ('n', 'no'):
            return False
        print(_tr('请输入 y 或 n。'))


def remove_autostart():
    path = config_home() / 'niri/config.kdl'
    if not path.is_file():
        return
    text = path.read_text()
    pattern = re.compile(r'(?ms)^[ \t]*// ==== ADWS 桌面图标层自启（自动生成）====[^\n]*\n.*?^[ \t]*// ==== ADWS 桌面图标层自启 END ====[^\n]*\n?')
    from adws_autostart import PATTERN
    cleaned = PATTERN.sub('', pattern.sub('', text))
    from adws_windows import PATTERN as WINDOW_RULES
    cleaned = WINDOW_RULES.sub('', cleaned)
    launchers = {str(ROOT / 'src/niri-desktop-layer/start-desktop-layer')}
    previous_root = read_inventory().get('root')
    if isinstance(previous_root, str):
        launchers.add(str(Path(previous_root) / 'src/niri-desktop-layer/start-desktop-layer'))
    lines = {f'spawn-at-startup "{launcher}"' for launcher in launchers}
    cleaned = ''.join(line for line in cleaned.splitlines(keepends=True) if line.strip() not in lines)
    if cleaned != text:
        # Edit only the ADWS block; keep all other compositor configuration.
        path.write_text(cleaned)


def remove_owned_files(keep_config):
    data = read_inventory()
    roots = {ROOT}
    previous_root = data.get('root')
    if isinstance(previous_root, str):
        roots.add(Path(previous_root))
    entries = {'adws':'adws', 'adws-config':'tools/adws-config.py',
               'taskbar-toggle.sh':'scripts/taskbar-toggle.sh', 'taskbar-state.sh':'scripts/taskbar-state.sh'}
    directories = {Path.home() / '.local/bin'}
    if '/usr/local/bin' in data.get('command_dirs', []):
        directories.add(Path('/usr/local/bin'))
    for directory in directories:
        for name, relative in entries.items():
            path = directory / name
            if path.is_symlink() and any(path.resolve() == (root / relative).resolve() for root in roots):
                if os.access(directory, os.W_OK):
                    path.unlink()
                else:
                    print(''.join([_tr('移除系统命令链接需要管理员权限：'), f'{path}']))
                    subprocess.run(['sudo', 'unlink', str(path)], check=True)
    for name, source in library_sources().items():
        path = Path.home() / '.local/lib/waybar' / name
        recorded = data.get('libraries', {}).get(name)
        # Older installations can be identified by matching their build artifacts.
        expected = recorded or (digest(source) if source.is_file() else None)
        if path.is_file() and expected and digest(path) == expected:
            path.unlink()
    if not keep_config:
        recorded_configs = set(data.get('configs', []))
        for name in ('config-bottom.jsonc', 'style-bottom.css'):
            path = config_home() / 'waybar' / name
            legacy_link = path.is_symlink() and any(path.resolve() == (root / 'config/waybar' / name).resolve() for root in roots)
            if (str(path) in recorded_configs or legacy_link) and (path.exists() or path.is_symlink()):
                path.unlink()
        # Shared Waybar modules/colors and the Niri configuration are never deleted.
        for path in (config_home() / 'adws', config_home() / 'niri-desktop-layer',
                     state_home() / 'niri-desktop-layer', ROOT / 'src/niri-desktop-layer/state'):
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        for name in ('desktop-hidden', 'taskbar-hidden'):
            (state_home() / name).unlink(missing_ok=True)
        inventory_path().unlink(missing_ok=True)
    else:
        # Preserve ownership of retained config for a future reinstall/uninstall.
        data['libraries'] = {}
        data['uninstalled'] = True
        save_inventory(data)


def uninstall():
    try:
        if not ask(_tr('您真的要卸载adws吗？（y/N）'), False):
            print(_tr('已取消。'))
            return 0
        keep_config = ask(_tr('您需要保留配置文件便于以后使用吗？（Y/n）'), True)
    except (EOFError, KeyboardInterrupt):
        print(_tr('\n已取消。'))
        return 0
    print(_tr('卸载中，感谢您的使用。'), flush=True)
    try:
        from adws_runtime import main as control
        for component in ('desktop', 'taskbar'):
            if control([component, '--stop'], quiet=True) != 0:
                return 1
        remove_autostart()
        remove_owned_files(keep_config)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(''.join([_tr('卸载未完成：'), f'{error}']), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--record', action='store_true')
    parser.add_argument('--record-config')
    args = parser.parse_args()
    if args.record or args.record_config:
        record(args.record_config)
    else:
        raise SystemExit(uninstall())

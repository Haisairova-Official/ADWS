"""Interactive removal of ADWS-owned integration files, never desktop contents."""
from adws_i18n import tr as _tr
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
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
    from adws_atomic import replace_files
    replace_files({inventory_path(): (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode()})


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
    data['root'] = str(ROOT.resolve())
    data['installation_role'] = 'development' if (ROOT / '.adws-development').exists() else 'installed'
    data['build_method'] = 'prebuilt' if (ROOT / 'prebuilt/manifest.json').is_file() else 'source'
    from adws_templates import hashes
    data.setdefault('template_hashes', hashes(ROOT))
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
    from adws_windows import config_path
    path = config_path()
    if not path.is_file():
        return
    text = path.read_text()
    pattern = re.compile(r'(?ms)^[ \t]*// ==== ADWS 桌面图标层自启（自动生成）====[^\n]*\n.*?^[ \t]*// ==== ADWS 桌面图标层自启 END ====[^\n]*\n?')
    from adws_autostart import PATTERN
    cleaned = PATTERN.sub('', pattern.sub('', text))
    from adws_topbar import BEGIN as TOP_BEGIN, END as TOP_END
    top_pattern = re.compile(r'(?ms)^' + re.escape(TOP_BEGIN) + r'[^\n]*\n.*?^' + re.escape(TOP_END) + r'[^\n]*\n?')
    cleaned = top_pattern.sub('', cleaned)
    from adws_windows import PATTERN as WINDOW_RULES
    cleaned = WINDOW_RULES.sub('', cleaned)
    from adws_keyboard import clean_block
    cleaned = clean_block(cleaned)
    launchers = {str(ROOT / 'src/niri-desktop-layer/start-desktop-layer')}
    previous_root = read_inventory().get('root')
    if isinstance(previous_root, str):
        launchers.add(str(Path(previous_root) / 'src/niri-desktop-layer/start-desktop-layer'))
    lines = {f'spawn-at-startup "{launcher}"' for launcher in launchers}
    cleaned = ''.join(line for line in cleaned.splitlines(keepends=True) if line.strip() not in lines)
    cleaned = remove_managed_install_entries(cleaned, path)
    if cleaned != text:
        # Edit only the ADWS block; keep all other compositor configuration.
        from adws_atomic import replace_files
        replace_files({path: cleaned.encode()})


def remove_managed_install_entries(text, config):
    """Remove only verified ADWS starts/rules from the new installer blocks.

    Clipboard, notifications, input-method starts and all user-edited commands
    remain in place. Included files are retained: another user include may use
    them, and removing the owned reference is enough to disable ADWS rules.
    """
    from adws_install_startup import BEGIN as START, END as STOP
    from adws_install_niri import BLOCK
    roots = {ROOT.resolve()}
    previous = read_inventory().get('root')
    if isinstance(previous, str): roots.add(Path(previous).resolve())

    def own_command(argv):
        if not argv: return False
        if Path(argv[0]).name == 'env':
            args = list(argv[1:])
            if any(arg.startswith('PATH=') for arg in args): return False
            while args and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*=.*', args[0]): args.pop(0)
            if args[:1] == ['--']: args.pop(0)
            return own_command(args)
        if Path(argv[0]).name in ('sh', 'bash', 'zsh'):
            if len(argv) == 3 and argv[1] in ('-c', '-lc'):
                try: return own_command(shlex.split(argv[2]))
                except ValueError: return False
            return own_command(argv[1:]) if len(argv)>1 and not argv[1].startswith('-') else False
        executable = Path(argv[0])
        if argv[0] != 'adws' and executable not in {root/'adws' for root in roots}: return False
        # Do not swallow user-added shell operators, wrappers or extra actions.
        args=argv[1:]
        return (args in (['-s'], ['--start']) or
                len(args)==2 and set(args) in ({'desktop','-s'},{'desktop','--start'},
                                             {'taskbar','-s'},{'taskbar','--start'}))

    pattern=re.compile(r'(?ms)^'+re.escape(START)+r'\n.*?^'+re.escape(STOP)+r'\n?')
    def clean_starts(match):
        retained=[]
        for line in match.group().splitlines(keepends=True)[1:-1]:
            try:
                argv=shlex.split(line.strip(),comments=False)
                command=(argv[1:] if argv[:1]==['spawn-at-startup'] else
                         shlex.split(argv[1]) if len(argv)==2 and argv[0]=='spawn-sh-at-startup' else [])
            except ValueError: command=[]
            if not own_command(command): retained.append(line)
        return START+'\n'+''.join(retained)+STOP+'\n' if retained else ''
    text=pattern.sub(clean_starts,text)

    def clean_rules(match):
        lines=match.group().splitlines()[1:-1]
        if len(lines)==1:
            included=re.fullmatch(r'include "(\.adws-install-([0-9a-f]{20})\.kdl)"',lines[0])
            if included:
                path=Path(config).parent/included[1]
                try:
                    if hashlib.sha256(path.read_bytes()).hexdigest()[:20]==included[2]: return ''
                except OSError: pass
        elif lines and lines[0].startswith('// content-sha256: '):
            payload='\n'.join(lines[1:])+'\n'
            if hashlib.sha256(payload.encode()).hexdigest()==lines[0].removeprefix('// content-sha256: '):return ''
        return match.group()
    return BLOCK.sub(clean_rules,text)


def remove_owned_files(keep_config):
    from adws_vm_settings import uninstall as remove_vm_mode
    remove_vm_mode()
    from adws_location_registration import remove_location_registration
    remove_location_registration()
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
            if path == config_home()/'adws':
                # These files configure the continuing Niri session and default
                # terminal, not an ADWS widget. Niri still includes the session
                # file after uninstall, so deleting it prevents the next login.
                shared=shared_system_config_names(path)
                if shared is None:continue
                if any((path/name).exists() or (path/name).is_symlink() for name in shared):
                    if not path.is_symlink():
                        for child in path.iterdir():
                            if child.name in shared:continue
                            if child.is_symlink() or child.is_file():child.unlink()
                            elif child.is_dir():shutil.rmtree(child)
                    continue
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


def shared_system_config_names(adws_config):
    """Preserve external configuration dependencies even during widget purge.

    Unknown/unreadable includes return None: retaining preferences is preferable
    to making the user's next compositor login fail. Only read literal KDL
    include paths; never evaluate shell/environment expressions from config.
    """
    shared={'niri-session.kdl','default-terminal.json','palette','palette-sync.json'}
    from adws_windows import config_path
    root=Path(os.path.abspath(adws_config));pending=[config_path()];visited=set()
    while pending:
        path=Path(os.path.abspath(Path(pending.pop()).expanduser()))
        if path in visited:continue
        if len(visited)>=64:return None
        visited.add(path)
        try:text=path.read_text()
        except FileNotFoundError:
            if len(visited)==1:continue
            return None
        except (OSError,UnicodeError):return None
        for line in text.splitlines():
            line=line.strip()
            if not line.startswith('include '):continue
            try:args=shlex.split(line,comments=False)
            except ValueError:return None
            if len(args)<2:return None
            included=Path(args[1]).expanduser()
            if not included.is_absolute():included=path.parent/included
            included=Path(os.path.abspath(included))
            if root in included.parents:shared.add(included.relative_to(root).parts[0])
            pending.append(included)
    return shared


def uninstall():
    try:
        if not ask(_tr('您真的要卸载adws吗？（y/N）'), False):
            print(_tr('已取消。'))
            return 0
        keep_config = ask(_tr('您需要保留配置文件便于以后使用吗？（Y/n）'), True)
    except (EOFError, KeyboardInterrupt):
        print(_tr('\n已取消。'))
        return 0
    try:
        from adws_runtime import main as control
        from adws_upgrade import update_lock
        with update_lock():
            print(_tr('卸载中，感谢您的使用。'), flush=True)
            for component in ('desktop', 'taskbar'):
                if control([component, '--stop'], quiet=True) != 0:
                    return 1
            from adws_power_policy import stop_all
            stop_all()
            # Uninstall only ADWS-owned components and app configuration.
            # System settings chosen by the user remain effective.
            remove_autostart()
            remove_owned_files(keep_config)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
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

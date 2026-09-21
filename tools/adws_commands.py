"""Install command symlinks into an existing PATH directory."""
from adws_i18n import tr as _tr
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pwd
from adws_launcher import ask
from adws_uninstall import read_inventory, save_inventory

ROOT = Path(__file__).resolve().parent.parent
SYSTEM_BIN = Path('/usr/local/bin')
ENTRIES = {'adws': 'adws', 'adws-config': 'tools/adws-config.py',
           'taskbar-toggle.sh': 'scripts/taskbar-toggle.sh',
           'taskbar-state.sh': 'scripts/taskbar-state.sh'}

PATH_BLOCK = '''# >>> ADWS user command PATH >>>
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) export PATH="$HOME/.local/bin:$PATH" ;;
esac
# <<< ADWS user command PATH <<<
'''


def persist_user_path():
    """Do not rely on PATH inherited from the installer or an interactive shell."""
    shell = Path(os.environ.get('SHELL') or pwd.getpwuid(os.getuid()).pw_shell).name
    profiles = [Path.home() / '.profile']
    if shell == 'zsh':
        profiles.append(Path(os.environ.get('ZDOTDIR') or Path.home()) / '.zprofile')
    elif shell == 'bash':
        profiles.extend(p for p in [Path.home() / '.bash_profile', Path.home() / '.bash_login'] if p.exists())
    for path in profiles:
        text = path.read_text() if path.exists() else ''
        if '# >>> ADWS user command PATH >>>' in text:
            continue
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + '.adws-path.bak'))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as stream:
            stream.write('\n' + PATH_BLOCK)


def owned(path, relative, roots):
    return path.is_symlink() and any(path.resolve() == (root / relative).resolve() for root in roots)


def run(command, directory):
    if not os.access(directory, os.W_OK):
        if not shutil.which('sudo'):
            raise RuntimeError(_tr('需要 sudo 才能修改 /usr/local/bin，请安装 sudo 或将 ~/.local/bin 加入 PATH 后重试。'))
        command = ['sudo', *command]
    subprocess.run(command, check=True)


def install():
    paths = {Path(p).absolute() for p in os.environ.get('PATH', '').split(os.pathsep) if p}
    local = Path.home() / '.local/bin'
    if local in paths:
        directory = local
    else:
        if SYSTEM_BIN not in paths or not SYSTEM_BIN.is_dir():
            raise RuntimeError(_tr('/usr/local/bin 不在 PATH 中或不存在。请先将 ~/.local/bin 加入 PATH 后重新安装。'))
        while True:
            answer = ask(_tr('~/.local/bin 不在 PATH 中。是否将命令链接安装到 /usr/local/bin（可能需要 sudo）？（Y/n/Ctrl+C）')).lower()
            if answer in ('', 'y'):
                break
            if answer == 'n':
                raise RuntimeError(_tr('已取消命令安装。请将 ~/.local/bin 加入 PATH 后重试。'))
        directory = SYSTEM_BIN
    data = read_inventory()
    roots = {ROOT, Path(data.get('root') or ROOT)}
    # Check every name before modifying anything; never overwrite another program.
    for name, relative in ENTRIES.items():
        path = directory / name
        if (path.exists() or path.is_symlink()) and not owned(path, relative, roots):
            raise RuntimeError(''.join([_tr('已有非 ADWS 命令，未覆盖：'), f'{path}']))
    directory.mkdir(parents=True, exist_ok=True)
    if directory == local:
        persist_user_path()
    for name, relative in ENTRIES.items():
        source, path = ROOT / relative, directory / name
        source.chmod(source.stat().st_mode | 0o111)
        if path.is_symlink() and path.resolve() == source.resolve():
            continue
        if path.is_symlink():
            run(['unlink', str(path)], directory)
        run(['ln', '-s', str(source), str(path)], directory)
        # Record partial progress as well, so a failed install remains removable.
        data.setdefault('command_dirs', [])
        if str(directory) not in data['command_dirs']:
            data['command_dirs'].append(str(directory))
        save_inventory(data)
    data.setdefault('command_dirs', [])
    if str(directory) not in data['command_dirs']:
        data['command_dirs'].append(str(directory))
    save_inventory(data)
    print(''.join([_tr('命令入口已安装到 '), f'{directory}', '。']))
    resolved = shutil.which('adws')
    if resolved and Path(resolved).resolve() != (ROOT / 'adws').resolve():
        print(''.join([_tr('提示：PATH 中更靠前的命令遮挡了 ADWS：'), f'{resolved}', _tr('；请使用 '), f'{directory}', '/adws。']))


if __name__ == '__main__':
    try:
        install()
    except (KeyboardInterrupt, EOFError):
        print(_tr('\n已取消。'), file=sys.stderr)
        raise SystemExit(130)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(''.join([_tr('命令安装未完成：'), f'{error}']), file=sys.stderr)
        raise SystemExit(1)

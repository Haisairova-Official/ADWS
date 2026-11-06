"""Install command symlinks into an existing PATH directory."""
from adws_i18n import tr as _tr
import os
import hashlib
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


def path_profiles():
    shell=Path(os.environ.get('SHELL') or pwd.getpwuid(os.getuid()).pw_shell).name
    profiles=[Path.home()/'.profile']
    if shell=='zsh':profiles.append(Path(os.environ.get('ZDOTDIR') or Path.home())/'.zprofile')
    elif shell=='bash':profiles.extend(p for p in (Path.home()/'.bash_profile',Path.home()/'.bash_login') if p.exists())
    return profiles


def path_state(path):
    path=Path(path)
    return {'resolved':str(path.resolve()),'symlink':os.readlink(path) if path.is_symlink() else None,
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,'exists':path.exists() or path.is_symlink()}


def plan(root=ROOT):
    root=Path(root);local=Path.home()/'.local/bin';data=read_inventory()
    roots={root,Path(data.get('root') or root)}
    roots.update(Path(p) for p in data.get('migration_roots',[]) if isinstance(p,str))
    conflicts=[]
    for name,relative in ENTRIES.items():
        path=local/name
        if (path.exists() or path.is_symlink()) and not owned(path,relative,roots):conflicts.append(str(path))
    return {'schema_version':1,'root':str(root),'directory':str(local),'policy':'user-local',
            'entries':{name:str(root/relative) for name,relative in ENTRIES.items()},
            'profiles':{str(p):path_state(p) for p in path_profiles()},'conflicts':conflicts,
            'activation':'Commands use ~/.local/bin; login profiles add PATH for next login; generated Niri commands use absolute paths.'}


def persist_user_path(proposal=None):
    """Persist only reviewed profile edits in managed installs; never source them."""
    profiles=path_profiles()
    if proposal:
        if set(map(str,profiles))!=set(proposal['profiles']):raise RuntimeError('Login profiles changed after review')
        for path in profiles:
            if path_state(path)!=proposal['profiles'][str(path)]:raise RuntimeError('Login profile changed after review: '+str(path))
    for path in profiles:
        text=path.read_text() if path.exists() else ''
        if '# >>> ADWS user command PATH >>>' in text:continue
        if path.exists():shutil.copy2(path,path.with_name(path.name+'.adws-path.bak'))
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a') as stream:stream.write('\n'+PATH_BLOCK)


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
    proposal=None
    if os.environ.get('ADWS_INSTALL_MANAGED')=='1':
        from adws_install_workflow import approved_plan
        proposal=approved_plan().get('command_plan')
        if not proposal or proposal.get('policy')!='user-local' or proposal.get('root')!=str(ROOT) or proposal.get('directory')!=str(local):
            raise RuntimeError('NEW_PLAN_REQUIRED: command installation was not reviewed')
        if proposal.get('conflicts'):raise RuntimeError('Command conflicts require review')
        directory=local
    elif local in paths:
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
    roots.update(Path(value) for value in data.get('migration_roots', []) if isinstance(value, str))
    # Check every name before modifying anything; never overwrite another program.
    for name, relative in ENTRIES.items():
        path = directory / name
        if (path.exists() or path.is_symlink()) and not owned(path, relative, roots):
            raise RuntimeError(''.join([_tr('已有非 ADWS 命令，未覆盖：'), f'{path}']))
    directory.mkdir(parents=True, exist_ok=True)
    if directory == local:
        persist_user_path(proposal)
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

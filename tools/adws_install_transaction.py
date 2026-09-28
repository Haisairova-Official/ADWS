"""Snapshot owned integration paths and restore them when installation fails."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

from adws_i18n import tr as _tr

ROOT = Path(__file__).resolve().parents[1]


def exists(path):
    return path.exists() or path.is_symlink()


class Snapshot:
    def __init__(self, directory, paths, follow_links=None):
        self.directory = directory
        self.entries = []
        candidates = set()
        for path in paths:
            path = Path(path)
            # Preserve leaf links as links; snapshot their targets independently.
            candidates.add(path.parent.resolve()/path.name)
            if path.is_symlink() and (follow_links is None or path in follow_links): candidates.add(path.resolve())
        chosen = []
        for path in sorted(candidates, key=lambda p: (len(p.parts), str(p))):
            if any(parent in path.parents and not parent.is_symlink() for parent in chosen): continue
            chosen.append(path)
            saved = directory/str(len(self.entries))
            present = exists(path)
            if present:
                subprocess.run(['cp', '-a', '--reflink=auto', '--', str(path), str(saved)], check=True)
            self.entries.append((path, saved, present))
        (directory/'manifest.json').write_text(json.dumps([
            {'path': str(p), 'backup': str(s), 'existed': e} for p, s, e in self.entries], indent=2)+'\n')

    def restore(self):
        errors = []
        for path, saved, present in self.entries:
            try:
                if not os.access(path.parent, os.W_OK) and path.parent.exists():
                    # The installer only changes symlinks in /usr/local/bin.
                    if not present and not exists(path): continue
                    if present and saved.is_symlink() and path.is_symlink() and os.readlink(saved) == os.readlink(path): continue
                    if present and saved.is_file() and not saved.is_symlink() and path.is_file() and saved.read_bytes() == path.read_bytes(): continue
                    if not path.is_symlink() and exists(path): raise OSError('Refusing to replace an unowned system file: '+str(path))
                    if path.is_symlink(): subprocess.run(['sudo', 'unlink', str(path)], check=True)
                    if present:
                        if not saved.is_symlink(): raise OSError('Cannot restore system file: '+str(path))
                        subprocess.run(['sudo', 'ln', '-s', os.readlink(saved), str(path)], check=True)
                    continue
                if path.is_symlink() or path.is_file(): path.unlink()
                elif path.is_dir(): shutil.rmtree(path)
                if present:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    subprocess.run(['cp', '-a', '--reflink=auto', '--', str(saved), str(path)], check=True)
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append(str(exc))
        if errors: raise RuntimeError('\n'.join(errors))


def integration_paths(root):
    home = Path.home()
    config = Path(os.environ.get('XDG_CONFIG_HOME') or home/'.config')
    state = Path(os.environ.get('XDG_STATE_HOME') or home/'.local/state')
    data = Path(os.environ.get('XDG_DATA_HOME') or home/'.local/share')
    cache = Path(os.environ.get('XDG_CACHE_HOME') or home/'.cache')
    paths = [folder/name for folder in (config, state, data, cache) for name in ('adws', 'mnws')]
    paths += [config/'niri-desktop-layer', state/'niri-desktop-layer', root/'src/niri-desktop-layer/state']
    paths += [config/'waybar'/name for name in ('config-bottom.jsonc', 'style-bottom.css', 'modules.jsonc', 'colors.css')]
    from adws_windows import config_path
    paths += [config_path(), config/'niri/config.kdl']
    paths += [home/name for name in ('.profile', '.bash_profile', '.bash_login')]
    paths += [Path(os.environ.get('ZDOTDIR') or home)/'.zprofile']
    paths += [state/name for name in ('desktop-hidden', 'taskbar-hidden')]
    paths += [directory/name for directory in (home/'.local/bin', Path('/usr/local/bin'))
              for name in ('adws', 'adws-config', 'mnws', 'mnws-config', 'taskbar-toggle.sh', 'taskbar-state.sh')]
    paths += [home/'.local/lib/waybar'/name for name in ('libniri_taskbar.so', 'libwaybar-space.so', 'libadws_panel.so', 'libmnws_panel.so')]
    paths += [root/'libexec/adws-plugin-runner', root/'libexec/adws-start-menu', root/'config/taskbar-layout.json']
    return paths


def foreground(terminal, group):
    # The installer temporarily becomes a background process while its child
    # owns the terminal. Ignore SIGTTOU only while handing the terminal back.
    previous = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
    try:
        os.tcsetpgrp(terminal, group)
    finally:
        signal.signal(signal.SIGTTOU, previous)


def run(command, env=None):
    terminal = None
    child = None
    try:
        terminal = os.open('/dev/tty', os.O_RDWR | os.O_NOCTTY)
        if os.tcgetpgrp(terminal) != os.getpgrp():
            os.close(terminal)
            terminal = None
    except OSError:
        if terminal is not None: os.close(terminal)
        terminal = None
    try:
        # Keep the controlling terminal for sudo/password prompts, but use a
        # separate process group so cancellation can also stop build helpers.
        child = subprocess.Popen(command, env=env, process_group=0)
        if terminal is not None:
            foreground(terminal, child.pid)
            # A fast child may have tried to read before the handoff (SIGTTIN).
            try: os.killpg(child.pid, signal.SIGCONT)
            except ProcessLookupError: pass
        code = child.wait()
        if code: raise subprocess.CalledProcessError(code, command)
    except BaseException:
        if child is not None:
            # Even if the shell exits first, its remaining children must stop
            # before rollback. Waiting only for the leader misses those jobs.
            try: os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            try: child.wait(timeout=3)
            except subprocess.TimeoutExpired: pass
            try: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            child.wait()
        raise
    finally:
        if terminal is not None:
            try: foreground(terminal, os.getpgrp())
            finally: os.close(terminal)


def install(root=ROOT):
    if sys.version_info < (3, 11):
        raise RuntimeError(_tr('需要 Python 3.11 或更新版本，请先通过系统的软件管理器升级 Python。'))
    from adws_runtime import pids, main as control
    state = Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')
    backups = state/'adws-install-backups'
    backups.mkdir(parents=True, exist_ok=True)
    with (backups/'install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        directory = Path(tempfile.mkdtemp(prefix='install-', dir=backups))
        snapshot = None
        stopped = []
        running = {}
        try:
            # Capture old launch commands without persisting session credentials.
            for component in ('desktop', 'taskbar'):
                ids = pids(component)
                if ids:
                    proc = Path('/proc')/str(ids[0])
                    argv = [os.fsdecode(x) for x in (proc/'cmdline').read_bytes().split(b'\0') if x]
                    env = dict(os.fsdecode(x).split('=', 1) for x in (proc/'environ').read_bytes().split(b'\0') if b'=' in x)
                    running[component] = (argv, env)
            # Stop first so the desktop's final state write enters the snapshot.
            for component in running:
                try:
                    code = control([component, '--stop'], quiet=True)
                finally:
                    if not pids(component): stopped.append(component)
                if code or component not in stopped: raise RuntimeError('Could not stop '+component)
            paths = integration_paths(root)
            entry_dirs = {Path('/usr/local/bin'), Path.home()/'.local/bin', Path.home()/'.local/lib/waybar'}
            snapshot = Snapshot(directory, paths, {p for p in paths if p.parent not in entry_dirs})
            print(_tr('安装前备份：%s') % directory, flush=True)
            env = dict(os.environ, ADWS_INSTALL_TRANSACTION=str(root))
            run(['bash', str(root/'scripts/adws-install.sh')], env)
            for component in running:
                run([str(root/'adws'), component, '--start'])
                if not pids(component): raise RuntimeError('Could not start '+component)
            (directory/'complete').touch()
        except BaseException as original:
            # Newly started components must stop before restoring their files.
            if snapshot is not None:
                try:
                    for component in stopped:
                        if pids(component): control([component, '--stop'], quiet=True)
                        if pids(component): raise RuntimeError('Could not stop '+component+' before restoring files')
                    snapshot.restore()
                except Exception as exc:
                    raise RuntimeError(_tr('自动恢复未完成，备份保留在：%s') % directory + '\n' + str(exc)) from original
                print(_tr('安装未完成，已恢复原配置和组件文件。'), file=sys.stderr)
            for component in stopped:
                argv, env = running[component]
                with (directory/('restore-'+component+'.log')).open('ab') as log:
                    subprocess.Popen(argv, env=env, stdout=log, stderr=log, start_new_session=True)
            raise
    return 0


if __name__ == '__main__':
    def terminated(_signum, _frame): raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, terminated)
    try: raise SystemExit(install())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(_tr('安装未完成：%s') % exc, file=sys.stderr); raise SystemExit(1)
    except KeyboardInterrupt:
        print(_tr('已取消。'), file=sys.stderr); raise SystemExit(130)

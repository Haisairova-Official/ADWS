"""Select the installed bottom-bar host and publish its per-session configuration."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import sys

from adws_atomic import stage
from adws_i18n import chinese


def choice_file():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'adws/taskbar-backend'


def selected_backend():
    try:
        value = choice_file().read_text(encoding='utf-8').strip()
    except FileNotFoundError:
        return 'waybar'
    if value not in ('waybar', 'rust'):
        raise ValueError(f'Invalid ADWS taskbar backend in {choice_file()}: {value!r}')
    return value


def live_config_file():
    base = Path(os.environ.get('XDG_RUNTIME_DIR') or os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state')
    # Distinct compositors can coexist under the same UID and runtime directory.
    display = os.environ.get('WAYLAND_DISPLAY') or os.environ.get('NIRI_SOCKET') or 'default'
    session = hashlib.sha256(os.fsencode(display)).hexdigest()[:20]
    return base.absolute() / 'adws/taskbar' / session / 'bar.json'


@contextmanager
def session_lock():
    directory = live_config_file().parent
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (directory / 'host.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def is_native_argv(argv):
    if not argv or Path(argv[0]).name != 'adws-taskbar' or '--check' in argv:
        return False
    try:
        return argv[argv.index('--config') + 1] == str(live_config_file())
    except (ValueError, IndexError):
        return False


def native_command(config, style):
    """Validate a staged snapshot before replacing the file used for live reload."""
    from adws_native_taskbar import choose_binary, expanded_config, use_preview_modules
    from adws_health import validate_waybar
    binary = choose_binary(None)
    bar = expanded_config(config)
    use_preview_modules(bar)
    errors = validate_waybar(config, style, bar)
    if errors:
        raise ValueError('\n'.join(errors))
    path = live_config_file()
    temp = stage(path, json.dumps(bar, ensure_ascii=False).encode('utf-8'), mode=0o600)
    try:
        checked = subprocess.run([str(binary), '--check', '--config', str(temp), '--style', str(style)],
                                 capture_output=True, text=True, timeout=8)
        if checked.returncode:
            raise ValueError(checked.stderr.strip() or 'Invalid native taskbar configuration')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return [str(binary), '--config', str(path), '--style', str(style)]


def running_native_pids():
    from adws_runtime import pids
    return [pid for pid in pids('taskbar') if process_is_native(pid)]


def process_is_native(pid):
    try:
        argv = (Path('/proc') / str(pid) / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
        return is_native_argv([os.fsdecode(arg) for arg in argv])
    except (FileNotFoundError, ProcessLookupError):
        return False


def reload_live(config_path, style_path):
    try:
        with session_lock():
            pids = running_native_pids()
            if len(pids) != 1:
                raise ValueError('Expected one running native ADWS taskbar')
            pid = pids[0]
            fd = os.pidfd_open(pid)
            try:
                if not process_is_native(pid):
                    raise ValueError('The native taskbar exited')
                # SIGUSR2 terminates a process before its GLib reload handler is
                # installed. A GUI apply may race an externally launched host.
                status = (Path('/proc') / str(pid) / 'status').read_text()
                caught = re.search(r'^SigCgt:\s*([0-9a-fA-F]+)$', status, re.M)
                if not caught or not int(caught[1], 16) & (1 << (signal.SIGUSR2 - 1)):
                    raise ValueError('The native taskbar is not ready to reload')
                native_command(config_path, style_path)
                signal.pidfd_send_signal(fd, signal.SIGUSR2)
            finally:
                os.close(fd)
        return True, ('已请求原生底栏重新加载配置。' if chinese() else 'Requested a native taskbar reload.')
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def main():
    parser = argparse.ArgumentParser(prog='adws taskbar-backend')
    parser.add_argument('backend', nargs='?', choices=('rust', 'waybar'))
    args = parser.parse_args()
    if args.backend is None:
        print(selected_backend())
        return 0
    if os.environ.get('ADWS_TASKBAR_PREVIEW') == '1':
        raise ValueError('Select the live taskbar backend outside the preview.')
    if args.backend == 'rust':
        from adws_layout import live_config_path, live_style_path
        with session_lock():
            native_command(live_config_path(), live_style_path())
    path = choice_file()
    tmp = stage(path, (args.backend + '\n').encode(), mode=0o600)
    try:
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    print(f'{args.backend} — ' + ('运行 adws taskbar --restart 应用。' if chinese()
                                 else 'Run adws taskbar --restart to apply.'))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        sys.exit(f'adws taskbar-backend: {error}')

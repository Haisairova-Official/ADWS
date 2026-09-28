"""Optional wallpaper setup. Only explicit selections change the wallpaper."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from adws_i18n import tr as _tr

ENGINES = ('awww', 'swww', 'swaybg')
PROCESSES = {'awww-daemon': 'awww', 'swww-daemon': 'swww', 'swaybg': 'swaybg',
             'hyprpaper': 'hyprpaper', 'mpvpaper': 'mpvpaper'}


def config_path():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'adws/wallpaper.json'


def installed():
    return [name for name in (*ENGINES, 'hyprpaper', 'mpvpaper') if shutil.which(name)]


def running():
    result = {}
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit(): continue
        try:
            if proc.stat().st_uid != os.getuid(): continue
            argv = (proc/'cmdline').read_bytes().split(b'\0')
            name = Path(os.fsdecode(argv[0])).name
            if name in PROCESSES:
                env = (proc/'environ').read_bytes().split(b'\0')
                display = os.environ.get('WAYLAND_DISPLAY', '')
                if display and ('WAYLAND_DISPLAY='+display).encode() in env:
                    result[int(proc.name)] = name
        except (OSError, ValueError): pass
    return result


def validate(engine, image):
    if engine not in ENGINES or not shutil.which(engine):
        raise ValueError(_tr('所选壁纸工具不可用，请刷新后重试。'))
    path = Path(image).expanduser().resolve(strict=True)
    from PIL import Image
    with Image.open(path) as source: source.verify()
    return str(path)


def install_command():
    # Use the system's configured repositories, never a downloaded shell script.
    if shutil.which('pacman'): args = ['pacman', '-S', '--needed', '--noconfirm', 'awww']
    elif shutil.which('apt-get'): args = ['apt-get', 'install', '-y', 'awww']
    elif shutil.which('dnf'): args = ['dnf', 'install', '-y', 'awww']
    else: raise ValueError(_tr('此系统不支持自动安装，请通过软件管理器安装 awww 后刷新。'))
    if os.geteuid() != 0:
        if not shutil.which('pkexec'): raise ValueError(_tr('缺少图形授权组件，请通过软件管理器安装 awww 后刷新。'))
        args.insert(0, 'pkexec')
    return args


def install_awww():
    result = subprocess.run(install_command(), capture_output=True, text=True, timeout=600)
    if result.returncode or not shutil.which('awww'):
        raise RuntimeError(_tr('awww 安装未完成。可以稍后重试，或通过软件管理器安装后刷新。')+'\n'+(result.stderr or result.stdout)[-1500:])


def apply(engine, image, approved=None):
    image = validate(engine, image)
    approved = approved or {}
    state = config_path().parent
    state.mkdir(parents=True, exist_ok=True)
    with (state/'wallpaper.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = running()
        conflicts = {pid: name for pid, name in current.items() if PROCESSES[name] != engine or engine == 'swaybg'}
        if any(approved.get(pid) != name for pid, name in conflicts.items()):
            raise ValueError(_tr('壁纸服务已变化，请重新确认后再应用。'))
        spawned = None
        try:
            if engine in ('awww', 'swww'):
                ready = subprocess.run([engine, 'query'], capture_output=True, timeout=3).returncode == 0
                if not ready:
                    daemon = shutil.which(engine+'-daemon')
                    if not daemon: raise ValueError(_tr('缺少壁纸后台服务，请重新安装所选工具。'))
                    spawned = subprocess.Popen([daemon], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    until = time.monotonic()+4
                    while time.monotonic() < until:
                        if subprocess.run([engine, 'query'], capture_output=True, timeout=1).returncode == 0: break
                        if spawned.poll() is not None: raise RuntimeError(_tr('壁纸后台服务启动失败。'))
                        time.sleep(.1)
                    else: raise RuntimeError(_tr('等待壁纸后台服务超时。'))
                result = subprocess.run([engine, 'img', image], capture_output=True, text=True, timeout=15)
                if result.returncode: raise RuntimeError(result.stderr[-1500:] or _tr('壁纸应用失败。'))
            else:
                spawned = subprocess.Popen(['swaybg', '-i', image, '-m', 'fill'], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(.25)
                if spawned.poll() is not None: raise RuntimeError(_tr('壁纸后台服务启动失败。'))
            # Stop only the exact services the user confirmed, still in this session.
            now = running()
            for pid, name in conflicts.items():
                if now.get(pid) == name:
                    try: os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError: pass
        except Exception:
            if spawned and spawned.poll() is None: spawned.terminate()
            raise


def restore():
    if not config_path().is_file() or running(): return
    data = json.loads(config_path().read_text())
    apply(data['engine'], data['image'])


def launch_restore():
    if config_path().is_file() and os.environ.get('WAYLAND_DISPLAY'):
        subprocess.Popen([sys.executable, str(Path(__file__).resolve())], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    try: restore()
    except Exception as exc: print(str(exc), file=sys.stderr)

"""Scoped taskbar visibility, monitor presets and confirmed session actions."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
from adws_i18n import tr

def marker():return Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/'taskbar-hidden'
def state():
    hidden=marker().exists()
    return {'text':'\uf108' if hidden else '\uf109','class':'disabled' if hidden else 'enabled','tooltip':tr('底部任务栏：已隐藏' if hidden else '底部任务栏：显示中')}
def identity(pid):
    path=Path('/proc')/str(pid)
    try:
        from adws_runtime import matches
        argv=path.joinpath('cmdline').read_bytes().decode().rstrip('\0').split('\0')
        if path.stat().st_uid!=os.getuid() or not matches('taskbar',argv):return None
        return path.joinpath('stat').read_text().rsplit(')',1)[1].split()[19]
    except (OSError,UnicodeError,IndexError):return None

def toggle():
    from adws_runtime import pids
    path=marker();path.parent.mkdir(parents=True,exist_ok=True)
    lock_path=path.parent/'adws/taskbar-toggle.lock';lock_path.parent.mkdir(parents=True,exist_ok=True)
    with lock_path.open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        targets=[(pid,identity(pid)) for pid in pids('taskbar')]
        if path.exists():path.unlink()
        else:path.touch()
        for pid,start in targets:
            if start is not None and identity(pid)==start:
                try:os.kill(pid,signal.SIGUSR1)
                except ProcessLookupError:pass
    return state()

def brightness(value=None,night=False):
    import adws_quick_backend as backend
    entries=[item for item in backend.brightness() if item.get('provider') or (night and item.get('color_provider'))]
    if not entries:raise RuntimeError(tr('无可用配置'))
    for item in entries:
        if night and item.get('color_provider'):backend.brightness_write(item,'night',not item['night'])
        elif value is not None and item.get('provider'):backend.brightness_write(item,'brightness',value)

def session_command(action):
    if action in ('poweroff','reboot','suspend'):return ['systemctl',action]
    if action=='logout':
        if os.environ.get('NIRI_SOCKET'):return ['niri','msg','action','quit','--skip-confirmation']
        if os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):return ['hyprctl','dispatch','exit']
        raise RuntimeError(tr('无法识别当前桌面会话'))
    if action=='lock':
        for name in ('hyprlock','gtklock','swaylock','waylock'):
            if binary:=shutil.which(name):
                config=Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'niri/hyprlock.conf'
                return [binary,*(['-c',str(config)] if name=='hyprlock' and os.environ.get('NIRI_SOCKET') and config.is_file() else [])]
        raise RuntimeError(tr('未找到可用的锁屏程序'))
    raise ValueError('Invalid session action')

def session(action):
    import gi
    gi.require_version('Gtk','3.0')
    from gi.repository import Gtk
    from adws_launch_dialogs import CompactDialog
    titles={'poweroff':'关机','reboot':'重启','logout':'注销','lock':'锁屏','suspend':'挂起'}
    argv=session_command(action)
    if action in ('poweroff','reboot','logout'):
        title=tr(titles[action]);dialog=CompactDialog(None,title,title,tr('确定要执行此操作吗？请先保存工作。'),icon='system-shutdown-symbolic',accept='确定')
        try:
            gi.require_version('GtkLayerShell','0.1')
            from gi.repository import GtkLayerShell as layer
            if layer.is_supported():
                layer.init_for_window(dialog);layer.set_namespace(dialog,'waybar');layer.set_layer(dialog,layer.Layer.OVERLAY);layer.set_keyboard_mode(dialog,layer.KeyboardMode.EXCLUSIVE);layer.set_exclusive_zone(dialog,0)
        except (ValueError,ImportError):pass
        dialog.show_all();accepted=dialog.run()==Gtk.ResponseType.OK;dialog.destroy()
        if not accepted:return
    subprocess.run(argv,check=True,timeout=15)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('state','toggle','brightness','night','poweroff','reboot','logout','lock','suspend'))
    parser.add_argument('--value',type=int,choices=range(5,101));args=parser.parse_args()
    try:
        if args.action=='state':print(json.dumps(state(),ensure_ascii=False))
        elif args.action=='toggle':toggle()
        elif args.action in ('brightness','night'):brightness(args.value,args.action=='night')
        else:session(args.action)
        return 0
    except Exception as error:
        print(str(error),file=sys.stderr)
        if shutil.which('notify-send'):subprocess.run(['notify-send','ADWS',str(error)],timeout=5,check=False)
        return 1
if __name__=='__main__':raise SystemExit(main())

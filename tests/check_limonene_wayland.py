#!/usr/bin/env python3
"""Isolated Niri: real folder-group drags and fresh start-menu output selection."""
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]

def main():
    processes=[];connection=None;niri=None
    with tempfile.TemporaryDirectory(prefix='adws-limonene-wayland-') as folder:
        root=Path(folder);runtime=root/'runtime';runtime.mkdir(mode=0o700)
        desktop=root/'Desktop';desktop.mkdir()
        for name in ['alpha.txt','beta.txt','gamma.txt']:(desktop/name).write_text(name)
        config=root/'config';config.mkdir()
        coordinates=root/'coordinates.json';wrapper=root/'client.py'
        wrapper.write_text('''import sys,json
from pathlib import Path
sys.path.insert(0,ROOT+'/src/niri-desktop-layer')
from desktop_layer.app import main
import gi;gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
opened=False
def inspect():
 global opened
 result={}
 for window in Gtk.Window.list_toplevels():
  layer=getattr(window,'desktop_groups',None)
  if layer and layer.cards:
   card=layer.cards[0]
   result['header']=card.translate_coordinates(window,60,20)
   result['geometry']=[card.get_allocated_width(),card.get_allocated_height()]
   result['icons']=[button.translate_coordinates(window,35,35) for button in card.grid.get_children() if isinstance(button,Gtk.Button)]
 dialogs=[w for w in Gtk.Window.list_toplevels() if isinstance(w,Gtk.Dialog) and w.get_visible()]
 if dialogs:
  def walk(widget):
   yield widget
   if isinstance(widget,Gtk.Container):
    for child in widget.get_children():yield from walk(child)
  entry=next((w for w in walk(dialogs[0]) if isinstance(w,Gtk.Entry)),None)
  if entry:result['entry']=entry.get_text()
  result['editor_parent']=dialogs[0].get_transient_for() is not None
 Path(COORDINATES).write_text(json.dumps(result))
 if Path(COORDINATES+'.edit').exists() and not opened:
  opened=True
  window=next(w for w in Gtk.Window.list_toplevels() if getattr(w,'desktop_groups',None))
  GLib.idle_add(lambda:window.desktop_groups.manager.edit(window,window.desktop_groups.cards[0].row))
 return True
GLib.timeout_add(100,inspect)
raise SystemExit(main())
'''.replace('ROOT',repr(str(ROOT))).replace('COORDINATES',repr(str(coordinates))))
        niri_config=root/'niri.kdl';niri_config.write_text('hotkey-overlay { skip-at-startup; }\nanimations { off; }\n')
        logs=[]
        def start(cmd,env,name):
            log=root/(name+'.log');logs.append(log)
            with log.open('w') as stream:p=subprocess.Popen(cmd,env=env,stdout=stream,stderr=stream,start_new_session=True)
            processes.append(p);return p
        def wait(predicate,timeout=12):
            until=time.monotonic()+timeout
            while not predicate():
                if time.monotonic()>until:raise RuntimeError('Timeout')
                time.sleep(.05)
        try:
            xvfb=subprocess.Popen(['Xvfb','-displayfd','1','-screen','0','1280x800x24'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            processes.append(xvfb);display=':'+xvfb.stdout.readline().decode().strip()
            env={**os.environ,'DISPLAY':display,'XDG_RUNTIME_DIR':str(runtime),'XDG_CONFIG_HOME':str(config),
                 'XDG_CACHE_HOME':str(root/'cache'),'XDG_STATE_HOME':str(root/'state'),'XDG_DATA_HOME':str(root/'data'),
                 'ADWS_PLUGIN_DIR':str(root/'plugins'),'LIBGL_ALWAYS_SOFTWARE':'1','WINIT_UNIX_BACKEND':'x11',
                 'RUST_LOG':'niri=info','LC_ALL':'C.UTF-8','GIO_USE_VFS':'local','NO_AT_BRIDGE':'1','PYTHONWARNINGS':'ignore'}
            for key in ('WAYLAND_DISPLAY','NIRI_SOCKET','GDK_BACKEND','HYPRLAND_INSTANCE_SIGNATURE'):env.pop(key,None)
            niri=start(['niri','--config',str(niri_config)],env,'niri')
            wait(lambda:any(p.is_socket() and not p.name.endswith('-agent') for p in runtime.glob('wayland-*')))
            sock=next(p for p in runtime.glob('wayland-*') if p.is_socket() and not p.name.endswith('-agent'))
            wait(lambda:bool(list(runtime.glob('niri.*.sock'))))
            ipc=next(runtime.glob('niri.*.sock'));time.sleep(.5)
            client_env={**env,'GTK_IM_MODULE':'fcitx','QT_QPA_PLATFORM':'wayland','WAYLAND_DISPLAY':sock.name,'GDK_BACKEND':'wayland','NIRI_SOCKET':str(ipc),'XDG_CURRENT_DESKTOP':'niri'}
            fcitx_dir=config/'fcitx5';fcitx_dir.mkdir()
            (fcitx_dir/'profile').write_text('[Groups/0]\nName=Default\nDefault Layout=us\nDefaultIM=pinyin\n[Groups/0/Items/0]\nName=keyboard-us\n[Groups/0/Items/1]\nName=pinyin\n[GroupOrder]\n0=Default\n')
            ime=start(['fcitx5','-D','--disable=cloudpinyin,notifications'],client_env,'fcitx')
            time.sleep(1)
            client=start([sys.executable,str(wrapper),'--directory',str(desktop),'--state',str(root/'layout.json')],client_env,'desktop')
            def positions():
                try:return json.loads(coordinates.read_text())
                except (OSError,ValueError):return {}
            wait(lambda:len(positions().get('icons',[]))==3)
            def xdo(*args):return subprocess.check_output(['xdotool',*map(str,args)],env=env,timeout=5).decode().strip()
            host=xdo('search','--name','^niri$').splitlines()[0];xdo('windowfocus',host)
            xlib=ctypes.CDLL('libX11.so.6');xtst=ctypes.CDLL('libXtst.so.6')
            xlib.XOpenDisplay.argtypes=[ctypes.c_char_p];xlib.XOpenDisplay.restype=ctypes.c_void_p
            xlib.XFlush.argtypes=[ctypes.c_void_p];xlib.XCloseDisplay.argtypes=[ctypes.c_void_p]
            xtst.XTestFakeMotionEvent.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ulong]
            connection=xlib.XOpenDisplay(display.encode())
            def move(x,y):xtst.XTestFakeMotionEvent(connection,-1,int(x),int(y),0);xlib.XFlush(connection);time.sleep(.15)
            path=root/'desktop-groups.json'
            def row():return json.loads(path.read_text())['groups'][0]
            before=row();x,y=positions()['header'];move(x,y);xdo('mousedown',1);move(x+25,y+15);move(x+140,y+100);xdo('mouseup',1)
            wait(lambda:row()['x']!=before['x'])
            assert row()['cells']==before['cells'],'Moving group changed internal grid'
            wait(lambda:positions()['header'][0]>x+60)
            old=row()['cells'];icons=positions()['icons'];ax,ay=icons[0];bx,by=icons[1]
            move(ax,ay);xdo('mousedown',1);move(ax+20,ay+10);move(bx,by);xdo('mouseup',1)
            wait(lambda:row()['cells']!=old)
            # Modifier-held drags also use the same reliable pointer-grab path.
            before=row();x,y=positions()['header'];move(x,y);xdo('keydown','Shift_L');xdo('mousedown',1);move(x+30,y+15);move(750,430);xdo('mouseup',1);xdo('keyup','Shift_L')
            wait(lambda:row()['x']!=before['x'])
            saved=row();time.sleep(.4)
            assert row()==saved,'Idle writes changed layout'
            subprocess.run(['import','-display',display,'-window','root','/tmp/adws-limonene-groups.png'],check=True,timeout=5)
            # A real Fcitx instance on the isolated bus exercises candidate popups.
            Path(str(coordinates)+'.edit').touch()
            wait(lambda:'entry' in positions())
            assert not positions()['editor_parent'],'Editor is parented to desktop layer'
            subprocess.run(['fcitx5-remote','-s','pinyin'],env=client_env,check=True,timeout=3)
            subprocess.run(['fcitx5-remote','-o'],env=client_env,check=True,timeout=3)
            xdo('key','ctrl+a');xdo('type','--delay',120,'nihao');time.sleep(.4);xdo('key','space')
            wait(lambda:any('\u4e00'<=c<='\u9fff' for c in positions().get('entry','')))
            print('PASS: real Fcitx candidate selection commits Chinese in group name')
            # Exit while the editor is open: nested dialog loops must not hang.
            # Snapshot restart preserves the group and cell geometry.
            client.terminate();client.wait(timeout=5)
            assert row()==saved
            assert 'Could not find position of child window' not in (root/'desktop.log').read_text()
            move(600,400)
            menu=start([str(ROOT/'src/adws-start-menu/target/release/adws-start-menu'),'--root',str(ROOT),'--check-wayland','--smoke-test',str(root/'menu.png')],client_env,'menu')
            menu.wait(timeout=30)
            assert menu.returncode==0,'Start menu smoke test failed'
            layers=json.loads(subprocess.check_output(['niri','msg','--json','layers'],env=client_env))
            assert 'adws-pointer-locator' not in json.dumps(layers),'Pointer probe leaked'
            print('PASS: real Wayland group movement, grid reorder, persistence, menu open and probe cleanup')
        except Exception:
            subprocess.run(['import','-display',display,'-window','root','/tmp/adws-limonene-failure.png'],timeout=5)
            print('coordinates:',positions() if coordinates.exists() else None,file=sys.stderr)
            for log in logs:print(log.name+':\n'+log.read_text()[-3500:],file=sys.stderr)
            raise
        finally:
            if connection:xlib.XCloseDisplay(connection)
            for process in reversed(processes):
                if process.poll() is None:
                    if process is niri:os.killpg(process.pid,signal.SIGTERM)
                    else:process.terminate()
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:process.kill();process.wait()

if __name__=='__main__':main()

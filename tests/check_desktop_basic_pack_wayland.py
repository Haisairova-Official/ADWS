#!/usr/bin/env python3
"""Exercise the actual package in an isolated Wayland compositor, including input."""
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
sys.path.insert(0,str(ROOT/'tools'))
import adws_plugin as plugin
from adws_components import components
import adws_desktop_widgets_model as model

def main():
    processes=[];niri=None;connection=None;client=None
    with tempfile.TemporaryDirectory(prefix='adws-basic-wayland-') as folder:
        root=Path(folder);runtime=root/'runtime';runtime.mkdir(mode=0o700)
        desktop=root/'Desktop';desktop.mkdir();config=root/'config';config.mkdir();packages=root/'plugins';packages.mkdir()
        package=plugin.build_package(ROOT/'plugins/desktop-basic-pack',packages/'basic.mplg')
        data={};positions={'clock':(25,20),'timer':(445,20),'note':(900,20),'game2048':(25,360),'puzzle':(445,360),'photo':(925,370)}
        for manifest in components(plugin.load_manifest(package),'desktop'):
            definition={'key':manifest['id'],'manifest':manifest,'repeatable':True};data=model.add(data,definition)
            row=data['instances'][-1];row.pop('x_percent');row.pop('y_percent');row['x'],row['y']=positions[manifest['componentId']]
        data['instances'][0]['settings']={'display':'analog','face_image':str(ROOT/'plugins/desktop-basic-pack/assets/default.svg'),'dial_markers':False}
        widget_path=config/'adws/desktop-widgets.json';model.save(data,widget_path)
        coordinates=root/'coordinates.json'
        wrapper=root/'client.py'
        wrapper.write_text('''import sys,json
from pathlib import Path
sys.path.insert(0,ROOT+'/src/niri-desktop-layer')
import gi;gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
from desktop_layer.app import main
settings_dialog=None
def inspect():
 global settings_dialog
 result={}
 for window in Gtk.Window.list_toplevels():
  layer=getattr(window,'desktop_widgets',None)
  if not layer:continue
  for card in layer.cards.values():
   if not card.interactive or not card.interactive.shape:continue
   kind=card.definition['manifest']['componentId'];ui=card.interactive
   if kind=='clock' and Path(COORDINATES+'.settings').exists() and settings_dialog is None:
    from adws_plugin_settings import SettingsDialog
    settings_dialog=SettingsDialog(window,'Clock test',card.definition['manifest']['settingsSchema'],{})
    settings_dialog.dialog.show_all();settings_dialog.update_visibility()
    assert not settings_dialog.field_widgets['face'][0].get_visible()
    settings_dialog.controls['display'][1].set_active_id('analog')
    assert settings_dialog.field_widgets['face'][0].get_visible()
    assert not settings_dialog.field_widgets['seconds'][0].get_visible()
    assert settings_dialog.collect()['display']=='analog'
   if settings_dialog and Path(COORDINATES+'.popup').exists():
    button=settings_dialog.controls['face'][1]._adws_choice_button
    if not button.get_active():button.set_active(True)
    popup=button.popover
    origin=button.translate_coordinates(settings_dialog.dialog,0,0)
    point=popup.translate_coordinates(settings_dialog.dialog,0,0)
    result['_popup']={'visible':popup.get_mapped(),'anchor':origin,'rect':point,'size':[popup.get_allocated_width(),popup.get_allocated_height()],'button_size':[button.get_allocated_width(),button.get_allocated_height()]}
    assert popup.get_relative_to() is button
   result[kind]={}
   for key in ('toggle','note','left','right','up','down','dial',*[f'tile{i}' for i in range(16)]):
    if key in ui.widgets:
     w=ui.widgets[key];result[kind][key]=w.translate_coordinates(window,w.get_allocated_width()//2,w.get_allocated_height()//2)
   if kind=='puzzle':result[kind]['ready']=ui.widgets['image0'].pixbuf is not None
   if kind=='clock':
    control=card.clock_settings_button
    result[kind]['settings']=control.translate_coordinates(window,control.get_allocated_width()//2,control.get_allocated_height()//2)
    assert control.get_mapped()
    current=control
    while current is not None and current is not card.box:
     assert current.get_style_context().get_property('opacity',Gtk.StateFlags.NORMAL)>0
     current=current.get_parent()
    result[kind]['ready']=ui.widgets['dial'].picture.pixbuf is not None
    assert card.box.get_style_context().has_class('desktop-analog-clock')
    assert card.box.get_style_context().get_background_color(Gtk.StateFlags.NORMAL).alpha==0
 Path(COORDINATES).write_text(json.dumps(result))
 return True
GLib.timeout_add(200,inspect)
raise SystemExit(main())
'''.replace('ROOT',repr(str(ROOT))).replace('COORDINATES',repr(str(coordinates))))
        niri_config=root/'niri.kdl';niri_config.write_text('hotkey-overlay { skip-at-startup; }\nanimations { off; }\n')
        def wait(predicate,timeout=10):
            end=time.monotonic()+timeout
            while not predicate():
                if time.monotonic()>end:raise RuntimeError('Desktop basic pack interaction timed out')
                if any(p.poll() is not None for p in processes):raise RuntimeError('Nested process exited')
                time.sleep(.04)
        try:
            x=subprocess.Popen(['Xvfb','-displayfd','1','-screen','0','1500x1100x24'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL);processes.append(x)
            display=':'+x.stdout.readline().decode().strip()
            env={**os.environ,'DISPLAY':display,'XDG_RUNTIME_DIR':str(runtime),'XDG_CONFIG_HOME':str(config),'XDG_CACHE_HOME':str(root/'cache'),'XDG_STATE_HOME':str(root/'state'),'XDG_DATA_HOME':str(root/'data'),'ADWS_PLUGIN_DIR':str(packages),'LIBGL_ALWAYS_SOFTWARE':'1','WINIT_UNIX_BACKEND':'x11','LC_ALL':'zh_CN.UTF-8','NO_AT_BRIDGE':'1'}
            for key in ('WAYLAND_DISPLAY','NIRI_SOCKET','GDK_BACKEND','HYPRLAND_INSTANCE_SIGNATURE'):env.pop(key,None)
            with (root/'niri.log').open('w') as out:niri=subprocess.Popen(['niri','--config',str(niri_config)],env=env,stdout=out,stderr=out,start_new_session=True)
            processes.append(niri)
            wait(lambda:any(p.is_socket() and not p.name.endswith('-agent') for p in runtime.glob('wayland-*')))
            wayland=next(p.name for p in runtime.glob('wayland-*') if p.is_socket() and not p.name.endswith('-agent'));time.sleep(.5)
            with (root/'desktop.log').open('w') as out:client=subprocess.Popen([sys.executable,str(wrapper),'--directory',str(desktop),'--state',str(root/'layout.json')],env={**env,'WAYLAND_DISPLAY':wayland,'GDK_BACKEND':'wayland'},stdout=out,stderr=out)
            processes.append(client)
            def coords():
                try:return json.loads(coordinates.read_text())
                except (OSError,ValueError):return {}
            wait(lambda:len(coords())==6 and coords()['puzzle'].get('ready') and coords()['clock'].get('ready'))
            def xdo(*args):return subprocess.check_output(['xdotool',*args],env=env,timeout=4).decode().strip()
            host=xdo('search','--name','^niri$').splitlines()[0];xdo('windowmove',host,'0','0');xdo('windowsize',host,'1500','1100');xdo('windowfocus',host);time.sleep(.8)
            xlib=ctypes.CDLL('libX11.so.6');xtst=ctypes.CDLL('libXtst.so.6')
            xlib.XOpenDisplay.argtypes=[ctypes.c_char_p];xlib.XOpenDisplay.restype=ctypes.c_void_p;xlib.XFlush.argtypes=[ctypes.c_void_p];xlib.XCloseDisplay.argtypes=[ctypes.c_void_p]
            xtst.XTestFakeMotionEvent.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ulong];connection=xlib.XOpenDisplay(display.encode())
            def click(kind,control):
                px,py=coords()[kind][control];xtst.XTestFakeMotionEvent(connection,-1,px,py,0);xlib.XFlush(connection);time.sleep(.15);xdo('click','1')
            def state(kind):
                row=next(r for r in data['instances'] if r['component'].endswith('.'+kind))
                return json.loads((root/'state/adws/desktop-plugins/org.AkiACG-Community.desktopBasicPack'/(row['instance']+'.json')).read_text())
            click('timer','toggle');wait(lambda:state('timer').get('running'))
            blank=state('puzzle')['board'].index(15)
            target=blank-4 if blank>=4 else blank+4
            click('puzzle','tile'+str(target));wait(lambda:state('puzzle')['moves']==1)
            click('note','note');xdo('type','--clearmodifiers','--delay','20','ADWS persistent note');wait(lambda:state('note')['text']=='ADWS persistent note')
            sys.path.insert(0,str(ROOT/'plugins/desktop-basic-pack'))
            from engine import move_board
            board=state('game2048')['board'];direction=next(d for d in ('left','up','right','down') if move_board(board,d)[0]!=board)
            click('game2048',direction);wait(lambda:'undo' in state('game2048'))
            subprocess.run(['import','-display',display,'-window','root','/tmp/adws-desktop-basic-pack.png'],check=True,timeout=5)
            assert model.load(widget_path)==model.normalize(data)
            niri_env={**env,'NIRI_SOCKET':str(next(runtime.glob('niri*.sock')))}
            def clock_dialog_open():
                windows=json.loads(subprocess.check_output(['niri','msg','-j','windows'],env=niri_env,timeout=3))
                return any(w.get('is_floating') and w.get('title')=='时钟设置' for w in windows)
            click('clock','settings');wait(clock_dialog_open)
            xdo('key','Escape');wait(lambda:not clock_dialog_open())
            px,py=coords()['clock']['dial'];xtst.XTestFakeMotionEvent(connection,-1,px,py,0);xlib.XFlush(connection);time.sleep(.15)
            xdo('click','--repeat','2','--delay','100','1');wait(clock_dialog_open)
            xdo('key','Escape');wait(lambda:not clock_dialog_open())
            Path(str(coordinates)+'.settings').touch()
            def floating_dialog():
                windows=json.loads(subprocess.check_output(['niri','msg','-j','windows'],env=niri_env,timeout=3))
                matching=[w for w in windows if w.get('title','').startswith('Clock test')]
                return matching and matching[0].get('is_floating')
            wait(floating_dialog)
            Path(str(coordinates)+'.popup').touch()
            wait(lambda:coords().get('_popup',{}).get('visible'))
            time.sleep(.4)
            pop=coords()['_popup'];ax,ay=pop['anchor'];px,py=pop['rect'];pw,ph=pop['size'];bw,bh=pop['button_size']
            assert px<ax+bw and px+pw>ax, pop
            assert abs(py-(ay+bh))<40 or abs(py+ph-ay)<40, pop
            subprocess.run(['import','-display',display,'-window','root','/tmp/adws-widget-settings-floating.png'],check=True,timeout=5)
            windows=json.loads(subprocess.check_output(['niri','msg','-j','windows'],env=niri_env,timeout=3))
            identity=next(w['id'] for w in windows if w.get('title','').startswith('Clock test'))
            subprocess.run(['niri','msg','action','move-floating-window','--id',str(identity),'--x','100','--y','100'],env=niri_env,check=True,stdout=subprocess.DEVNULL)
            outputs=json.loads(subprocess.check_output(['niri','msg','-j','outputs'],env=niri_env,timeout=3))
            subprocess.run(['niri','msg','output',next(iter(outputs)),'scale','1.25'],env=niri_env,check=True,stdout=subprocess.DEVNULL)
            time.sleep(.7)
            pop=coords()['_popup'];ax,ay=pop['anchor'];px,py=pop['rect'];pw,ph=pop['size'];bw,bh=pop['button_size']
            assert pop['visible'] and px<ax+bw and px+pw>ax, pop
            assert abs(py-(ay+bh))<40 or abs(py+ph-ay)<40, pop
            subprocess.run(['import','-display',display,'-window','root','/tmp/adws-widget-dropdown-scaled.png'],check=True,timeout=5)
            client.terminate();client.wait(timeout=5);processes.remove(client)
            print('PASS: six actual Wayland widgets, countdown, 15-tile sliding puzzle, keyboard note entry/autosave, 2048 move, visible clock settings button and real double-click, floating settings with conditional clock controls; isolated configuration preserved.')
        except Exception:
            subprocess.run(['import','-display',display,'-window','root','/tmp/adws-desktop-basic-pack-failure.png'],timeout=5)
            for name in ('niri.log','desktop.log'):
                path=root/name
                if path.exists():print(name+':\n'+path.read_text()[-6000:],file=sys.stderr)
            raise
        finally:
            if connection:xlib.XCloseDisplay(connection)
            for process in reversed(processes):
                if process.poll() is None:
                    if process is niri:os.killpg(process.pid,signal.SIGTERM)
                    else:process.terminate()
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
            # The watchdog flushes its final health records after the desktop exits.
            # Wait for only this test's plugin workers before deleting their runtime.
            if client is not None:
                marker=('ADWS_PLUGIN_HOST_PID='+str(client.pid)).encode()
                def workers_alive():
                    for entry in Path('/proc').glob('[0-9]*/environ'):
                        try:
                            if marker in entry.read_bytes().split(b'\0'):return True
                        except (OSError,PermissionError):pass
                    return False
                deadline=time.monotonic()+5
                while workers_alive() and time.monotonic()<deadline:time.sleep(.05)
                assert not workers_alive(), 'Isolated plugin workers did not stop'

if __name__=='__main__':main()

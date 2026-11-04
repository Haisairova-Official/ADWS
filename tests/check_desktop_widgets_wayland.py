#!/usr/bin/env python3
"""Real desktop-card input in an isolated Niri; never sends input to the user's session."""
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
import adws_desktop_widgets_model as model


def main():
    processes=[];niri=None;logs=[];connection=None
    with tempfile.TemporaryDirectory(prefix='adws-desktop-widgets-wayland-') as folder:
        root=Path(folder);runtime=root/'runtime';runtime.mkdir(mode=0o700)
        desktop=root/'Desktop';desktop.mkdir();(desktop/'fixture.txt').write_text('fixture')
        (root/'desktop-groups.json').write_text(json.dumps({'version':1,'groups':[],'default_monitor':'primary'}))
        config=root/'config';config.mkdir()
        widget_path=config/'adws/desktop-widgets.json'
        data=model.add({}, {'key':'builtin:clock'});data['instances'][0].pop('x_percent');data['instances'][0].pop('y_percent');data['instances'][0].update(x=400,y=40,width=360,height=220);model.save(data,widget_path)
        import adws_plugin as mplg
        fixture=root/'fixture';fixture.mkdir();controls_log=root/'controls.log'
        manifest={'id':'org.adws.lyric_input','name':'Lyrics input fixture','version':'1.0.0','defaults':{'align':0.5},
            'components':[{'id':'desktop','target':'desktop','name':'Lyrics','entry':'main.py','renderer':'panel.rows-v1','desktopStyle':'lyrics','settingsSchema':[{'key':'show_furigana','type':'boolean','default':True,'label':'Furigana'}],'controls':['previous','play-pause','next']}]}
        (fixture/'plugin.json').write_text(json.dumps(manifest))
        (fixture/'main.py').write_text("import json,sys,time,pathlib\nif '--control' in sys.argv:\n pathlib.Path("+repr(str(controls_log))+").open('a').write(sys.argv[sys.argv.index('--control')+1]+'\\n');sys.exit(0)\nwhile True:\n print(json.dumps({'primary':'君の夢を信じて'*4,'secondary':'相信你的梦想','romanization':'kimi no yume wo shinjite','ruby':[{'base':'君','reading':'きみ'},{'base':'の','reading':''},{'base':'夢','reading':'ゆめ'},{'base':'を','reading':''},{'base':'信','reading':'しん'},{'base':'じ','reading':''},{'base':'て','reading':''}]*4,'previous':'空を見上げて','next':'明日へ歩こう','playing':True,'position':65,'duration':240}),flush=True);time.sleep(.3)\n")
        (root/'plugins').mkdir();mplg.build_package(fixture,root/'plugins/fixture.mplg')
        data=model.add(data,{'key':'org.adws.lyric_input.desktop'});data['instances'][-1].pop('x_percent');data['instances'][-1].pop('y_percent');data['instances'][-1].update(x=400,y=360,width=500,height=320,settings={"show_furigana":True});model.save(data,widget_path)
        coordinates=root/'controls.json';wrapper=root/'client.py'
        wrapper.write_text("import sys,json\nfrom pathlib import Path\nsys.path.insert(0,"+repr(str(ROOT/'src/niri-desktop-layer'))+")\nfrom desktop_layer.app import main\nimport gi;gi.require_version('Gtk','3.0')\nfrom gi.repository import Gtk,GLib\ndef inspect():\n result={}\n for window in Gtk.Window.list_toplevels():\n  layer=getattr(window,'desktop_widgets',None)\n  if layer:\n   for card in layer.cards.values():\n    for action,button in card.control_buttons.items():\n     result[action]=button.translate_coordinates(window,button.get_allocated_width()//2,button.get_allocated_height()//2)\n Path("+repr(str(coordinates))+").write_text(json.dumps(result))\n return True\nGLib.timeout_add(200,inspect)\nraise SystemExit(main())\n")
        niri_config=root/'niri.kdl';niri_config.write_text('hotkey-overlay { skip-at-startup; }\nanimations { off; }\n')
        def wait_for(predicate,timeout=10):
            deadline=time.monotonic()+timeout
            while not predicate():
                if time.monotonic()>deadline:raise RuntimeError('Timed out waiting for desktop widget input')
                if any(p.poll() is not None for p in processes):raise RuntimeError('Nested test process exited early')
                time.sleep(.03)
        try:
            xvfb=subprocess.Popen(['Xvfb','-displayfd','1','-screen','0','1280x800x24'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            processes.append(xvfb);display=':'+xvfb.stdout.readline().decode().strip()
            env={**os.environ,'DISPLAY':display,'XDG_RUNTIME_DIR':str(runtime),'XDG_CONFIG_HOME':str(config),
                 'XDG_CACHE_HOME':str(root/'cache'),'XDG_STATE_HOME':str(root/'state'),'XDG_DATA_HOME':str(root/'data'),
                 'ADWS_PLUGIN_DIR':str(root/'plugins'),'LIBGL_ALWAYS_SOFTWARE':'1','WINIT_UNIX_BACKEND':'x11',
                 'RUST_LOG':'niri=info','LC_ALL':'C.UTF-8','GIO_USE_VFS':'local','NO_AT_BRIDGE':'1'}
            for key in ('WAYLAND_DISPLAY','NIRI_SOCKET','GDK_BACKEND','HYPRLAND_INSTANCE_SIGNATURE'):env.pop(key,None)
            log=root/'niri.log';logs.append(log)
            with log.open('w') as stream:niri=subprocess.Popen(['niri','--config',str(niri_config)],env=env,stdout=stream,stderr=stream,start_new_session=True)
            processes.append(niri);wait_for(lambda:any(p.is_socket() and not p.name.endswith('-agent') for p in runtime.glob('wayland-*')))
            socket=next(p for p in runtime.glob('wayland-*') if p.is_socket() and not p.name.endswith('-agent'))
            time.sleep(0.6)
            client_env={**env,'WAYLAND_DISPLAY':socket.name,'GDK_BACKEND':'wayland'}
            diagnostics=root/'diagnostics.json';log=root/'desktop.log';logs.append(log)
            with log.open('w') as stream:client=subprocess.Popen([sys.executable,str(wrapper),'--directory',str(desktop),'--state',str(root/'layout.json'),'--diagnostics',str(diagnostics)],env=client_env,stdout=stream,stderr=stream)
            processes.append(client)
            wait_for(lambda:'running' in log.read_text().lower())
            def xdo(*args):return subprocess.check_output(['xdotool',*args],env=env,timeout=5).decode().strip()
            host=xdo('search','--name','^niri$').splitlines()[0];xdo('windowfocus',host)
            xlib=ctypes.CDLL('libX11.so.6');xtst=ctypes.CDLL('libXtst.so.6')
            xlib.XOpenDisplay.argtypes=[ctypes.c_char_p];xlib.XOpenDisplay.restype=ctypes.c_void_p
            xlib.XFlush.argtypes=[ctypes.c_void_p];xlib.XCloseDisplay.argtypes=[ctypes.c_void_p]
            xtst.XTestFakeMotionEvent.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ulong]
            connection=xlib.XOpenDisplay(display.encode())
            def move(x,y):
                xtst.XTestFakeMotionEvent(connection,-1,x,y,0);xlib.XFlush(connection);time.sleep(.2)
            wait_for(lambda:'x_percent' in model.load(widget_path)['instances'][0])
            assert model.geometry(model.load(widget_path)['instances'][0],1280,800)[:2]==(400,40),model.load(widget_path)
            move(440,65);xdo('mousedown','1');move(560,135);xdo('mouseup','1')
            wait_for(lambda:model.geometry(model.load(widget_path)['instances'][0],1280,800)[0]>400)
            row=model.load(widget_path)['instances'][0]
            assert model.geometry(row,1280,800)[:2]==(520,110),row
            assert 'x_percent' in row and 'x' not in row,row
            wait_for(lambda:coordinates.exists() and len(json.loads(coordinates.read_text()))==3)
            for action in ('previous','play-pause','next'):
                x,y=json.loads(coordinates.read_text())[action];move(x,y);xdo('click','1')
                wait_for(lambda:controls_log.exists() and action in controls_log.read_text().splitlines())
            subprocess.run(['import','-display',env['DISPLAY'],'-window','root','/tmp/adws-lyrics-media-hover.png'],timeout=5)
            move(70,70);xdo('click','1');time.sleep(.2)
            subprocess.run(['import','-display',env['DISPLAY'],'-window','root','/tmp/adws-lyrics-media-idle.png'],timeout=5)
            client.terminate();client.wait(timeout=5);processes.remove(client)
            state=json.loads(diagnostics.read_text());assert state['windows'],state
            # Folder-group icon routing has its own real Wayland regression.
            assert not (config/'adws/taskbar-layout.json').exists()
            print('PASS: real Wayland card drag persisted; taskbar layout untouched; real mouse clicks dispatched all three media actions.')
        except Exception:
            subprocess.run(['import','-display',env['DISPLAY'],'-window','root','/tmp/adws-desktop-widgets-wayland.png'],timeout=5)
            for log in logs:print(log.name+':\n'+log.read_text()[-4000:],file=sys.stderr)
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

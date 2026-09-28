"""Run under Xvfb/private DBus with ADWS_TEST_NIRI; never touch the live session."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import stat
import time

binary = Path(os.environ['ADWS_TEST_NIRI']).resolve()
with tempfile.TemporaryDirectory(prefix='adws-niri-input-test-') as folder:
    root = Path(folder); runtime = root/'run'; runtime.mkdir(mode=0o700)
    taps = root/'taps'; events = root/'events'; config = root/'config.kdl'
    config.write_text('hotkey-overlay { skip-at-startup; }\nbinds {\n'
                      'Super repeat=false { spawn "sh" "-c" '+json.dumps('echo super >> '+str(taps))+'; }\n'
                      'Ctrl repeat=false { spawn "sh" "-c" '+json.dumps('echo ctrl >> '+str(taps))+'; }\n}\n')
    client_code = '''import gi,sys
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,Gdk
w=Gtk.Window(title='ADWS keyboard client');w.set_default_size(400,250)
def key(w,e):
 with open(sys.argv[1],'a') as f:f.write(f'{e.type.value_nick} {Gdk.keyval_name(e.keyval)} {int(e.state)}\\n')
 return False
w.connect('key-press-event',key);w.connect('key-release-event',key);w.show_all();Gtk.main()
'''
    env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), LIBGL_ALWAYS_SOFTWARE='1', WINIT_UNIX_BACKEND='x11', GTK_USE_PORTAL='0', GIO_USE_VFS='local', NO_AT_BRIDGE='1')
    for name in ('WAYLAND_DISPLAY','NIRI_SOCKET','ADWS_NIRI_BINARY'): env.pop(name,None)
    def wait(predicate, message):
        for _ in range(160):
            result = predicate()
            if result: return result
            if compositor.poll() is not None: raise AssertionError((root/'niri.log').read_text())
            time.sleep(.05)
        raise AssertionError(message+'\n'+(root/'niri.log').read_text()[-2500:])
    with (root/'niri.log').open('w') as output:
        compositor = subprocess.Popen([str(binary), '-c', str(config)], env=env, stdout=output, stderr=output)
        client = None
        try:
            socket = wait(lambda: next((p for p in runtime.glob('wayland-*') if stat.S_ISSOCK(p.stat().st_mode)),None), 'No nested Wayland socket')
            env['WAYLAND_DISPLAY']=socket.name;env['GDK_BACKEND']='wayland'
            client=subprocess.Popen(['python3','-c',client_code,str(events)], env=env,stdout=output,stderr=output)
            time.sleep(1)
            assert client.poll() is None, (root/'niri.log').read_text()
            win = subprocess.check_output(['xdotool','search','--onlyvisible','--class','niri']).decode().splitlines()[-1]
            subprocess.run(['xdotool','windowfocus','--sync',win],check=True)
            def keys(*args):
                subprocess.run(['xdotool',*args],check=True);time.sleep(.15)
            def lines(): return taps.read_text().splitlines() if taps.exists() else []
            keys('keydown','Control_L');assert lines()==[], 'Action on press'
            keys('keyup','Control_L');wait(lambda: lines()==['ctrl'],'Ctrl tap missing')
            keys('keydown','Super_L');assert lines()==['ctrl']
            keys('keyup','Super_L');wait(lambda: lines()==['ctrl','super'],'Super tap missing')
            expected=lines()
            keys('keydown','Control_L','key','c','keyup','Control_L')
            keys('keydown','Super_L','key','t','keyup','Super_L')
            keys('keydown','c','keydown','Control_L','keyup','c','keyup','Control_L')
            keys('keydown','Control_L','click','1','keyup','Control_L')
            keys('keydown','Super_L','click','4','keyup','Super_L')
            assert lines()==expected, 'Combination, click or scroll triggered a tap'
            received=events.read_text()
            assert 'key-press c ' in received and 'key-release c ' in received, received
            assert 'key-press Control_L ' in received and 'key-release Control_L ' in received, received
            print('Nested upstream Niri: taps trigger on release; combinations/click/scroll cancel; key pairs reach the client.')
        finally:
            if client:
                client.terminate();client.wait(timeout=5)
            compositor.terminate();compositor.wait(timeout=10)

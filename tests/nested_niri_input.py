"""A nested Niri seat for real Wayland input without addressing the user's seat."""
from contextlib import ExitStack, contextmanager
import ctypes
from io import BytesIO
import json
import os
from pathlib import Path
import signal
import subprocess
from types import SimpleNamespace
import time

from PIL import Image
from check_rust_taskbar_wayland import child_environment, wait_for


@contextmanager
def nested_input(root):
    env = child_environment(root)
    with ExitStack() as stack:
        def run(*args, **kwargs):
            return subprocess.check_output(args, env=env, timeout=10, **kwargs)

        def spawn(name, args, pipe=False):
            log = stack.enter_context((root / (name + '.log')).open('wb'))
            child = subprocess.Popen(args, env=env, stdout=subprocess.PIPE if pipe else log,
                                     stderr=log, start_new_session=True)
            def finish():
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
                if child.stdout:
                    child.stdout.close()
            stack.callback(finish)
            return child

        def screen():
            frame = run('grim', '-t', 'png', '-')
            return Image.open(BytesIO(frame)).convert('RGB')

        bus = spawn('bus', ['dbus-daemon', '--session', '--nofork', '--print-address=1'], True)
        env['DBUS_SESSION_BUS_ADDRESS'] = bus.stdout.readline().decode().strip()
        xserver = spawn('xvfb', ['Xvfb', '-displayfd', '1', '-screen', '0', '1600x900x24', '-nolisten', 'tcp'], True)
        env['DISPLAY'] = ':' + xserver.stdout.readline().decode().strip()
        config = root / 'test.kdl'
        config.write_text('animations { off; }\nhotkey-overlay { skip-at-startup; }\n'
                          'window-rule { match title="ADWS"; open-floating true; }\n')
        spawn('niri', ['niri', '--config', str(config)])
        runtime = Path(env['XDG_RUNTIME_DIR'])
        ipc = wait_for('private Niri', lambda: next(runtime.glob('niri.*.sock'), None))
        env.update(NIRI_SOCKET=str(ipc), GDK_BACKEND='wayland', XDG_CURRENT_DESKTOP='niri',
                   WAYLAND_DISPLAY=ipc.name.split('.')[1])
        host = run('xdotool', 'search', '--name', '^niri$', text=True).splitlines()[0]
        run('xdotool', 'windowfocus', host)
        xlib = ctypes.CDLL('libX11.so.6')
        xtst = ctypes.CDLL('libXtst.so.6')
        xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        xlib.XOpenDisplay.restype = ctypes.c_void_p
        xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        xlib.XFlush.argtypes = [ctypes.c_void_p]
        xtst.XTestFakeRelativeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        connection = xlib.XOpenDisplay(env['DISPLAY'].encode())
        assert connection
        stack.callback(xlib.XCloseDisplay, connection)
        def move(x, y):
            run('xdotool', 'mousemove', '--window', host, str(x), str(y))
            time.sleep(.08)
            # XWarpPointer alone may not produce a device event after a
            # Wayland grab. Feed winit one small real motion via XTEST.
            xtst.XTestFakeRelativeMotionEvent(connection, 1, 0, 0)
            xlib.XFlush(connection)
            time.sleep(.08)

        def layers():
            return {layer['namespace'] for layer in json.loads(run('niri', 'msg', '-j', 'layers'))}

        yield SimpleNamespace(env=env, run=run, spawn=spawn, screen=screen, move=move, layers=layers)

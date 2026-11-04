"""Integration test: isolated transient units only; never restarts the desktop."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/niri-desktop-layer'))
from desktop_layer.service import start_service
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
def call(path, interface, method, args):
    return bus.call_sync('org.freedesktop.systemd1', path, interface, method,
                         args, None, Gio.DBusCallFlags.NONE, 5000, None).unpack()
def ctl(*args):
    return subprocess.run(['systemctl', '--user', *args], capture_output=True, text=True, check=True)
def alive(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().split(')')[1].split()[0] != 'Z'
    except FileNotFoundError:
        return False
for mode in ('control-group', 'process'):
    unit = f'adws-debug-children-{os.getpid()}-{mode}.service'
    child = None
    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / 'child'
        program = "import subprocess,time,pathlib; p=subprocess.Popen(['/usr/bin/sleep','60']); pathlib.Path(%r).write_text(str(p.pid)); time.sleep(60)" % str(marker)
        properties = [('Type', GLib.Variant('s', 'exec')), ('KillMode', GLib.Variant('s', mode)),
                      ('CollectMode', GLib.Variant('s', 'inactive-or-failed')),
                      ('ExecStart', GLib.Variant('a(sasb)', [(sys.executable, [sys.executable, '-c', program], False)]))]
        try:
            start_service(call, properties, unit)
            deadline=time.monotonic()+5
            while not marker.exists() and time.monotonic()<deadline: time.sleep(.02)
            child=int(marker.read_text())
            ctl('stop', unit)
            assert alive(child) == (mode == 'process'), (mode, child)
            print(mode, 'child survives:', alive(child))
        finally:
            subprocess.run(['systemctl','--user','stop',unit],capture_output=True)
            if child and alive(child): os.kill(child, signal.SIGTERM)
# Retain an inactive main process's unit to reproduce UnitExists deterministically.
unit=f'adws-debug-reuse-{os.getpid()}.service'
properties=[('Type',GLib.Variant('s','oneshot')),('RemainAfterExit',GLib.Variant('b',True)),
            ('ExecStart',GLib.Variant('a(sasb)',[('/usr/bin/true',['/usr/bin/true'],False)]))]
try:
    start_service(call,properties,unit)
    time.sleep(.1)
    start_service(call,properties,unit)
    print('Loaded unit reused successfully')
    changed=[(k, GLib.Variant('a(sasb)',[('/usr/bin/false',['/usr/bin/false'],False)]) if k=='ExecStart' else v) for k,v in properties]
    try: start_service(call,changed,unit)
    except RuntimeError: print('Different installation command rejected')
    else: raise AssertionError('Mismatched command accepted')
finally:
    subprocess.run(['systemctl','--user','stop',unit],capture_output=True)

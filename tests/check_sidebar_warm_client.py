"""Run with dbus-run-session: real warm launcher, no desktop/window required."""
import json
import os
from pathlib import Path
import sys
import time
from gi.repository import Gio, GLib

root = Path(__file__).resolve().parents[1]
app = Gio.Application(application_id='org.adws.Sidebar')
action = Gio.SimpleAction.new('open', GLib.VariantType.new('s'))
received = []
action.connect('activate', lambda _, payload: received.append(json.loads(payload.get_string())))
app.add_action(action)
assert app.register(None) and not app.get_is_remote()
loop = GLib.MainLoop()
results = []
errors = []

def launch():
    start = time.perf_counter()
    process = Gio.Subprocess.new([sys.executable, str(root/'tools/adws_sidebar.py'), '--side', 'left', '--anchor', '{"inset":46}'],
                                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
    def finished(proc, result):
        try:
            ok, out, err = proc.communicate_utf8_finish(result)
            assert ok and proc.get_successful(), err
            assert received[-1] == {'anchor': {'inset':46}, 'side':'left', 'locale':{key:os.environ[key] for key in ('LANG','LANGUAGE','LC_ALL','LC_MESSAGES') if os.environ.get(key)}}
            results.append(round((time.perf_counter()-start)*1000, 1))
            assert len(received) == len(results), 'duplicate activation'
            if len(results) == 10: loop.quit()
            else: GLib.idle_add(launch)
        except Exception as error:
            errors.append(error); loop.quit()
    process.communicate_utf8_async(None, None, finished)
    return False
GLib.idle_add(launch)
GLib.timeout_add_seconds(20, lambda: (errors.append(TimeoutError('launcher hung')),loop.quit(),False)[-1])
loop.run()
if errors: raise errors[0]
print('Warm toggle roundtrip milliseconds:', results)

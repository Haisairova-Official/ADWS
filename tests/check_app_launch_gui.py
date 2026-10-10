"""Isolated launch/auth GUI fixtures. No actual privileged command is run."""
import os
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Polkit', '1.0')
from gi.repository import Gtk, Gdk, GLib, Polkit
import adws_app_launch as launch
import adws_native_auth as auth

Gtk.init([])
main_thread = threading.get_ident()

for code in (0, 126, 127, 1):
    agent = Mock()
    dispatched = []
    GLib.idle_add(lambda: (dispatched.append(True), False)[1])
    def run(argv, cwd=None, stderr=None):
        assert threading.get_ident() != main_thread
        assert argv == ['fixture-command'] and cwd is None
        stderr.write(b'x' * 10000)
        return subprocess.CompletedProcess(argv, code)
    with patch.object(auth, 'start', return_value=agent) as start, patch.object(launch.subprocess, 'run', side_effect=run):
        result = launch.run_administrator(['fixture-command'])
    assert result.returncode == code and result.stderr == 'x' * 4096
    assert dispatched, 'authorization UI must retain its main-loop dispatch'
    assert start.call_args.kwargs == {'process_only': True}
    agent.close.assert_called_once()

# A missing native library can still use an installed session agent; execution
# errors propagate and the temporary host is released on every path.
agent = Mock()
with patch.object(auth, 'start', return_value=agent), patch.object(launch.subprocess, 'run', side_effect=OSError('fixture failure')):
    try:
        launch.run_administrator(['fixture-command'])
        raise AssertionError('missing executable must be reported')
    except OSError as error:
        assert str(error) == 'fixture failure'
agent.close.assert_called_once()
with patch.object(auth, 'start', side_effect=ImportError('fixture absent')), patch.object(launch.subprocess, 'run', return_value=subprocess.CompletedProcess([], 126)):
    assert launch.run_administrator(['fixture-command']).returncode == 126

# Verify the process-scoped subject independently of the real system bus.
agent = auth.AuthenticationAgent(Gtk.Window())
subject = Mock()
bus=Mock(); authority=Mock()
with patch.object(auth.Polkit.UnixProcess, 'new_for_owner', return_value=subject) as process, patch.object(auth.Polkit.UnixSession, 'new_for_process_sync', side_effect=AssertionError('must not claim the session')), patch.object(auth.Gio, 'bus_get_sync', return_value=bus), patch.object(auth.Polkit.Authority, 'get_sync', return_value=authority):
    agent.start(process_only=True)
    process.assert_called_once_with(os.getpid(), 0, os.getuid())
    assert authority.register_authentication_agent_sync.call_args.args[0] is subject
    agent.close()
    bus.unregister_object.assert_called_once()
agent.host.destroy()

checked = []
def inspect_error():
    from adws_launch_dialogs import CompactDialog
    dialogs = [w for w in Gtk.Window.list_toplevels() if isinstance(w, CompactDialog) and w.get_visible()]
    assert len(dialogs) == 1
    dialog = dialogs[0]
    assert dialog.get_type_hint() == Gdk.WindowTypeHint.DIALOG
    assert 'fixture refusal' in dialog.description.get_text()
    assert dialog.get_allocated_height() < 420
    assert GLib.get_prgname() == 'adws-config'
    checked.append(True)
    dialog.response(Gtk.ResponseType.CLOSE)
    return False
GLib.idle_add(inspect_error)
with patch.object(sys, 'argv', ['adws_app_launch.py', '--administrator', 'Fixture']), patch.object(launch, 'launch', side_effect=RuntimeError('fixture refusal')):
    assert launch.main() == 1
assert checked
print('Administrator launch GUI fixtures passed: dispatch, cleanup, scoped auth and visible error dialog.')

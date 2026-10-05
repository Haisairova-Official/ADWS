"""Real isolated D-Bus conversations, mocked PAM; never requests privileges.

Run: GDK_BACKEND=x11 dbus-run-session -- xvfb-run -a python3 tests/check_auth_bus_gui.py
"""
import os
from pathlib import Path
import sys
import time
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Polkit', '1.0')
from gi.repository import Gdk, Gio, GLib, GObject, Gtk
import adws_native_auth as auth

Gtk.init([])
address = os.environ['DBUS_SESSION_BUS_ADDRESS']
flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
connect = lambda: Gio.DBusConnection.new_for_address_sync(address, flags, None, None)
server, client, intruder = connect(), connect(), connect()
host = Gtk.Window()
host.authorization_app_name = 'Mozilla Firefox'
agent = auth.AuthenticationAgent(host)
authority = Mock()
authority.get_owner.return_value = client.get_unique_name()
with patch.object(auth.Gio, 'bus_get_sync', return_value=server), patch.object(auth.Polkit.Authority, 'get_sync', return_value=authority):
    agent.start(process_only=True)


def pump_until(check, timeout=3):
    end = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < end, 'conversation timed out'
        while GLib.MainContext.default().pending(): GLib.MainContext.default().iteration(False)
        time.sleep(.003)


def children(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children(): yield from children(child)


class Session(GObject.GObject):
    __gsignals__ = {'request': (GObject.SignalFlags.RUN_LAST, None, (str, bool)),
                   'completed': (GObject.SignalFlags.RUN_LAST, None, (bool,)),
                   'show-error': (GObject.SignalFlags.RUN_LAST, None, (str,)),
                   'show-info': (GObject.SignalFlags.RUN_LAST, None, (str,))}
    def __init__(self):
        super().__init__(); self.cancelled = 0; self.answers = []; self.success = True
    def initiate(self): self.emit('request', 'Password:', False)
    def response(self, text):
        self.answers.append(text)
        # Entry must already be cleared before handing a response to PAM.
        assert not next(w for w in children(agent.pending[0][0]) if isinstance(w, Gtk.Entry)).get_text()
        self.emit('completed', self.success)
    def cancel(self):
        self.cancelled += 1
        # Synchronous cancellation signals must not cause a second reply.
        self.emit('completed', False)


sessions = []
def new_session(identity, cookie):
    session = Session(); sessions.append(session); return session


def call(method, parameters, caller=client):
    outcome = []
    def ready(connection, result, unused):
        try: outcome.append(connection.call_finish(result))
        except GLib.Error as error: outcome.append(error)
    caller.call(server.get_unique_name(), auth.PATH, auth.INTERFACE, method,
                parameters, GLib.VariantType.new('()'), Gio.DBusCallFlags.NONE, 3000, None, ready, None)
    return outcome


def begin(cookie, caller=client):
    return call('BeginAuthentication', GLib.Variant('(sssa{ss}sa(sa{sv}))', (
        'org.freedesktop.policykit.exec', 'Run /usr/bin/env WAYLAND_DISPLAY=/run/user/1000/wayland-1 /usr/lib/firefox/firefox as superuser',
        '', {}, cookie, [('unix-user', {'uid': GLib.Variant('u', os.getuid())})])), caller)


try:
    with patch.object(auth.PolkitAgent.Session, 'new', side_effect=new_session):
        # Actual message dispatch and reply; not a direct virtual-method call.
        outcome = begin('success')
        pump_until(lambda: bool(agent.pending))
        dialog = agent.pending[0][0]
        pump_until(lambda: dialog.get_allocated_height() > 1)
        assert dialog.get_type_hint() == Gdk.WindowTypeHint.DIALOG
        assert dialog.get_allocated_width() < 650 and dialog.get_allocated_height() < 440
        assert dialog.get_widget_for_response(Gtk.ResponseType.OK).get_label() not in ('应用更改', 'Apply changes')
        entry = next(w for w in children(dialog) if isinstance(w, Gtk.Entry))
        assert not entry.get_visibility()
        # A collapsed expander contains the complete operation for inspection.
        expander = next(w for w in children(dialog) if isinstance(w, Gtk.Expander))
        assert not expander.get_expanded()
        assert any('WAYLAND_DISPLAY' in w.get_text() for w in children(expander) if isinstance(w, Gtk.Label))
        screenshot = os.environ.get('ADWS_AUTH_SCREENSHOT')
        if screenshot:
            for _ in range(8):
                while Gtk.events_pending(): Gtk.main_iteration()
                time.sleep(.025)
            window = dialog.get_window()
            pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, window.get_width(), window.get_height())
            pixbuf.savev(screenshot, 'png', [], [])
        entry.set_text('fixture response')
        dialog.response(Gtk.ResponseType.OK)
        pump_until(lambda: bool(outcome))
        assert not isinstance(outcome[0], GLib.Error) and outcome[0].unpack() == ()
        assert sessions[-1].answers == ['fixture response'] and not agent.pending
        # Retry keeps one dialog/conversation and sends only one final reply.
        outcome = begin('retry')
        pump_until(lambda: bool(agent.pending))
        dialog = agent.pending[0][0]
        entry = next(w for w in children(dialog) if isinstance(w, Gtk.Entry))
        sessions[-1].success = False
        entry.set_text('wrong fixture')
        dialog.response(Gtk.ResponseType.OK)
        assert agent.pending and not outcome and not entry.get_text()
        assert any(w.get_visible() and w.get_style_context().has_class('dialog-status') for w in children(dialog))
        dialog.response(Gtk.ResponseType.OK)  # start a fresh conversation
        entry.set_text('retry fixture')
        dialog.response(Gtk.ResponseType.OK)
        pump_until(lambda: bool(outcome))
        assert not agent.pending and len(outcome) == 1
        # CancelAuthentication comes through the bus too; late PAM signals are harmless.
        outcome = begin('cancel')
        pump_until(lambda: bool(agent.pending))
        session = sessions[-1]
        cancelled = call('CancelAuthentication', GLib.Variant('(s)', ('cancel',)))
        pump_until(lambda: bool(outcome) and bool(cancelled))
        assert session.cancelled == 1 and not agent.pending
        session.emit('completed', True)
        assert len(outcome) == len(cancelled) == 1
        missing = call('CancelAuthentication', GLib.Variant('(s)', ('missing',)))
        pump_until(lambda: bool(missing))
        assert isinstance(missing[0], GLib.Error)
        # Unauthorized local peers cannot display prompts or feed a cookie.
        denied = begin('intruder', intruder)
        pump_until(lambda: bool(denied))
        assert isinstance(denied[0], GLib.Error) and 'AccessDenied' in str(denied[0]) and not agent.pending
        # Native conversation startup failures return one error and clear UI.
        with patch.object(auth.PolkitAgent.Session, 'new', side_effect=RuntimeError('fixture startup failure')):
            failed = begin('failure')
            pump_until(lambda: bool(failed))
            assert isinstance(failed[0], GLib.Error) and not agent.pending
        # Also exercise signals on the real native Session type, without PAM
        # initiation or privileges. Only its operation is simulated here.
        from gi.repository import Polkit
        real_session = auth.PolkitAgent.Session.new(Polkit.UnixUser.new(os.getuid()), 'native-fixture')
        with patch.object(auth.PolkitAgent.Session, 'new', return_value=real_session), patch.object(auth.PolkitAgent.Session, 'initiate'):
            native_reply = begin('native-session')
            pump_until(lambda: bool(agent.pending))
            real_session.emit('request', 'Password:', False)
            real_session.emit('completed', True)
            pump_until(lambda: bool(native_reply))
            assert not isinstance(native_reply[0], GLib.Error) and not agent.pending
        outcome = begin('close')
        pump_until(lambda: bool(agent.pending))
        session = sessions[-1]
        agent.close()
        pump_until(lambda: bool(outcome))
        assert session.cancelled == 1 and agent.registration is None
        authority.unregister_authentication_agent_sync.assert_called_once()
finally:
    agent.close(); host.destroy()
    for connection in (intruder, client, server): connection.close_sync(None)
print('PASS real D-Bus auth success, retry, cancellation, late signals, sender checks and compact GUI.')

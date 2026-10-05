"""ADWS Polkit D-Bus agent; PAM stays in the system authentication library.

Export the documented agent protocol directly: forwarding a C async closure
through PyGObject Listener/GTask loses its opaque context on some versions.
No authentication policy, credentials or privilege checks are implemented here.
"""
import logging
import os
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Polkit', '1.0')
gi.require_version('PolkitAgent', '1.0')
from gi.repository import Gio, GLib, Polkit, PolkitAgent, Gtk
from adws_i18n import tr

PATH = '/org/ADWS/AuthenticationAgent'
INTERFACE = 'org.freedesktop.PolicyKit1.AuthenticationAgent'
XML = '''<node><interface name="org.freedesktop.PolicyKit1.AuthenticationAgent">
<method name="BeginAuthentication"><arg type="s" direction="in"/>
<arg type="s" direction="in"/><arg type="s" direction="in"/>
<arg type="a{ss}" direction="in"/><arg type="s" direction="in"/>
<arg type="a(sa{sv})" direction="in"/></method>
<method name="CancelAuthentication"><arg type="s" direction="in"/></method>
</interface></node>'''
LOG = logging.getLogger(__name__)


class AuthenticationAgent:
    def __init__(self, host):
        self.host = host
        self.registration = None
        self.bus = self.authority = self.subject = None
        self.pending = []

    def start(self, process_only=False):
        self.subject = (Polkit.UnixProcess.new_for_owner(os.getpid(), 0, os.getuid()) if process_only
                        else Polkit.UnixSession.new_for_process_sync(os.getpid(), None))
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.authority = Polkit.Authority.get_sync(None)
        self.node = Gio.DBusNodeInfo.new_for_xml(XML)
        self.registration = self.bus.register_object(PATH, self.node.interfaces[0], self.method_call, None, None)
        try:
            self.authority.register_authentication_agent_sync(self.subject, os.environ.get('LANG') or 'C.UTF-8', PATH, None)
        except GLib.Error:
            self.bus.unregister_object(self.registration)
            self.registration = None
            raise

    def method_call(self, connection, sender, path, interface, method, parameters, invocation):
        # Also reject other processes of this user. System D-Bus policy already
        # restricts calls to the authority; unique owner checking is additional.
        if sender != self.authority.get_owner():
            invocation.return_dbus_error('org.freedesktop.DBus.Error.AccessDenied', 'Only the Polkit authority may authenticate.')
            return
        if method == 'CancelAuthentication':
            cookie, = parameters.unpack()
            item = next((state for _, state in self.pending if state['cookie'] == cookie), None)
            if item:
                item['finish'](False)
                invocation.return_value(None)
            else:
                invocation.return_dbus_error('org.freedesktop.PolicyKit1.Error.Failed', 'No pending authentication request.')
            return
        if method != 'BeginAuthentication':
            invocation.return_dbus_error('org.freedesktop.DBus.Error.UnknownMethod', 'Unknown authentication method.')
            return
        cookie = None
        try:
            action, message, icon, details, cookie, values = parameters.unpack()
            allowed = []
            for kind, attributes in values:
                if kind == 'unix-user' and isinstance(attributes.get('uid'), int):
                    allowed.append(Polkit.UnixUser.new(attributes['uid']))
            self.begin(message, cookie, allowed, invocation)
        except Exception:
            LOG.exception('Cannot open authorization dialog')
            pending = next((state for _, state in self.pending if state['cookie'] == cookie), None)
            if pending:
                pending['finish'](False, 'Cannot open authorization dialog.')
            else:
                invocation.return_dbus_error('org.freedesktop.PolicyKit1.Error.Failed', 'Cannot open authorization dialog.')

    def begin(self, message, cookie, allowed, invocation):
        from adws_launch_dialogs import CompactDialog, label
        if not allowed or any(state['cookie'] == cookie for _, state in self.pending):
            invocation.return_dbus_error('org.freedesktop.PolicyKit1.Error.Failed', 'Invalid authentication request.')
            return
        app_name = getattr(self.host, 'authorization_app_name', None)
        dialog = CompactDialog(self.host, '需要管理员授权', app_name or tr('确认此操作'),
                               tr('输入密码以管理员权限运行。') if app_name else message)
        if app_name: dialog.details(message)
        account = Gtk.Box(spacing=12)
        account.get_style_context().add_class('dialog-account')
        account.pack_start(Gtk.Image.new_from_icon_name('avatar-default-symbolic', Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
        selector = Gtk.ComboBoxText()
        for identity in allowed:
            selector.append(str(identity.get_uid()), identity.get_name() or str(identity.get_uid()))
        selector.set_active_id(str(os.getuid()))
        if selector.get_active() < 0: selector.set_active(0)
        if len(allowed) == 1:
            account.pack_start(label(selector.get_active_text()), True, True, 0)
        else:
            account.pack_start(label(tr('认证账户')), True, True, 0)
            account.pack_end(selector, False, False, 0)
        dialog.body.pack_start(account, False, False, 0)
        password = Gtk.Entry(visibility=False, placeholder_text=tr('密码'), activates_default=True)
        password.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        password.set_max_length(1024)
        dialog.body.pack_start(password, False, False, 0)
        status = label('', 'dialog-status')
        status.set_no_show_all(True)
        dialog.body.pack_start(status, False, False, 0)
        state = {'session': None, 'finished': False, 'signals': [], 'cookie': cookie}
        self.pending.append((dialog, state))

        def disconnect_session():
            session = state['session']
            if session:
                for handler in state['signals']: session.disconnect(handler)
            state['signals'] = []
            state['session'] = None
            return session

        def finish(success, error=None):
            if state['finished']: return
            state['finished'] = True
            session = disconnect_session()
            if session and not success: session.cancel()
            password.set_text('')
            dialog.destroy()
            self.pending.remove((dialog, state))
            # Polkit checks PAM independently. This reply only ends the
            # conversation; it never grants authorization by itself.
            if error:
                invocation.return_dbus_error('org.freedesktop.PolicyKit1.Error.Failed', error)
            else:
                invocation.return_value(None)

        state['finish'] = finish

        def request(session, text, echo):
            if state['finished']: return
            password.set_visibility(echo)
            password.set_placeholder_text(text.strip().rstrip(':') if echo else tr('密码'))
            password.set_text('')
            password.grab_focus()
            dialog.get_widget_for_response(Gtk.ResponseType.OK).set_sensitive(True)

        def completed(session, gained):
            if state['finished']: return
            disconnect_session()
            if gained: finish(True)
            else:
                status.set_text(tr('认证未通过，请重试或取消。'))
                status.show()
                password.set_text('')
                selector.set_sensitive(True)
                dialog.get_widget_for_response(Gtk.ResponseType.OK).set_sensitive(True)

        def show_status(session, text):
            if not state['finished']:
                status.set_text(text)
                status.show()

        def perform_response(response):
            if state['finished']: return
            if response != Gtk.ResponseType.OK:
                finish(False)
                return
            if state['session']:
                answer = password.get_text()
                password.set_text('')
                dialog.get_widget_for_response(Gtk.ResponseType.OK).set_sensitive(False)
                state['session'].response(answer)
                return
            identity = next(item for item in allowed if str(item.get_uid()) == selector.get_active_id())
            session = PolkitAgent.Session.new(identity, cookie)
            state['session'] = session
            state['signals'] = [session.connect(name, fn) for name, fn in
                                [('request', request), ('completed', completed), ('show-error', show_status), ('show-info', show_status)]]
            selector.set_sensitive(False)
            password.set_text('')
            session.initiate()

        def responded(_, response):
            try:
                perform_response(response)
            except Exception:
                LOG.exception('Authorization conversation failed')
                finish(False, 'Authorization conversation failed.')

        dialog.connect('response', responded)
        dialog.connect('destroy', lambda *_: finish(False) if not state['finished'] else None)
        dialog.show_all()
        dialog.present()
        password.grab_focus()
        responded(dialog, Gtk.ResponseType.OK)

    def close(self):
        for dialog, state in list(self.pending): state['finish'](False)
        if self.registration is not None:
            try:
                self.authority.unregister_authentication_agent_sync(self.subject, PATH, None)
            except GLib.Error:
                LOG.warning('Polkit agent could not unregister', exc_info=True)
            self.bus.unregister_object(self.registration)
            self.registration = None


def start(host, process_only=False):
    agent = AuthenticationAgent(host)
    try: agent.start(process_only=process_only)
    except GLib.Error:
        # Preserve any already registered session agent and all system policy.
        return None
    return agent

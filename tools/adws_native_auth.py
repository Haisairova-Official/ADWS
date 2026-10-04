"""A temporary ADWS Polkit agent, using the system's authentication library."""
import os
import gi
gi.require_version('Gtk','3.0')
gi.require_version('Polkit','1.0')
gi.require_version('PolkitAgent','1.0')
from gi.repository import Gio,GLib,Polkit,PolkitAgent,Gtk
from adws_i18n import tr


class AuthenticationAgent(PolkitAgent.Listener):
    def __init__(self,host):
        super().__init__()
        self.host=host;self.registration=None;self.pending=[]

    def start(self):
        subject=Polkit.UnixSession.new_for_process_sync(os.getpid(),None)
        self.registration=self.register(PolkitAgent.RegisterFlags.NONE,subject,'/org/ADWS/AuthenticationAgent',None)

    def do_initiate_authentication(self,action_id,message,icon_name,details,cookie,identities,cancellable,callback,user_data):
        task=Gio.Task.new(self,cancellable,callback,user_data)
        from adws_native_settings_gui import Form,caption,choice,entry
        dialog=Form(self.host,'需要管理员授权')
        dialog.body.pack_start(caption(message),False,False,0)
        allowed=[identity for identity in identities if isinstance(identity,Polkit.UnixUser)]
        if not allowed:task.return_boolean(False);dialog.destroy();return
        selector=choice([(str(identity.get_uid()),identity.get_name() or str(identity.get_uid())) for identity in allowed],os.getuid())
        if selector.get_active()<0:selector.set_active(0)
        dialog.field('identity','认证账户',selector)
        prompt=caption('请输入此账户的密码。');dialog.body.pack_start(prompt,False,False,0)
        password=entry(secret=True);dialog.field('password','密码',password)
        status=caption('','dim-label');dialog.body.pack_start(status,False,False,0)
        state={'session':None,'finished':False,'cancel':None}
        self.pending.append((dialog,state))
        def finish(success):
            if state['finished']:return
            state['finished']=True
            if state['cancel'] and cancellable:cancellable.disconnect(state['cancel'])
            password.set_text('');dialog.destroy()
            if (dialog,state) in self.pending:self.pending.remove((dialog,state))
            task.return_boolean(success)
        def request(session,text,echo):
            prompt.set_text(text);password.set_visibility(echo);password.set_text('');password.grab_focus()
            dialog.get_widget_for_response(Gtk.ResponseType.OK).set_sensitive(True)
        def completed(session,gained):
            state['session']=None
            if gained:finish(True)
            else:
                status.set_text(tr('认证未通过，请重试或取消。'))
                password.set_text('');selector.set_sensitive(True)
                dialog.get_widget_for_response(Gtk.ResponseType.OK).set_sensitive(True)
        def responded(_,response):
            if state['finished']:return
            if response!=Gtk.ResponseType.OK:
                if state['session']:state['session'].cancel()
                finish(False);return
            if state['session']:
                answer=password.get_text();password.set_text('')
                dialog.get_widget_for_response(Gtk.ResponseType.OK).set_sensitive(False)
                state['session'].response(answer)
                return
            identity=next(item for item in allowed if str(item.get_uid())==selector.get_active_id())
            session=PolkitAgent.Session.new(identity,cookie);state['session']=session
            session.connect('request',request);session.connect('completed',completed)
            session.connect('show-error',lambda _,text:status.set_text(text))
            session.connect('show-info',lambda _,text:status.set_text(text))
            selector.set_sensitive(False);password.set_text('');session.initiate()
        dialog.connect('response',responded)
        password.connect('activate',lambda *_:dialog.response(Gtk.ResponseType.OK))
        if cancellable:state['cancel']=cancellable.connect(lambda *_:GLib.idle_add(lambda:(responded(dialog,Gtk.ResponseType.CANCEL),False)[1]))
        dialog.show_all();password.grab_focus()
        # Start the PAM conversation without retaining an initial password.
        responded(dialog,Gtk.ResponseType.OK)

    def do_initiate_authentication_finish(self,result):return result.propagate_boolean()

    def close(self):
        for dialog,state in list(self.pending):
            dialog.response(Gtk.ResponseType.CANCEL)
        if self.registration is not None:
            PolkitAgent.Listener.unregister(self.registration)
            self.registration=None


def start(host):
    agent=AuthenticationAgent(host)
    try:agent.start()
    except GLib.Error:
        # An already registered session agent remains in charge. We do not
        # replace it, change policies or grant any permissions ourselves.
        return None
    return agent

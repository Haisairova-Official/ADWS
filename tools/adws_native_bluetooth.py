"""BlueZ discovery and a temporary ADWS pairing agent; never auto-accept PINs."""
import re
import secrets
from gi.repository import Gio, GLib, Gtk
from adws_native_services import bus_call
from adws_i18n import tr

DEST='org.bluez'
PATH='/org/bluez/adws_agent'
XML='''<node><interface name="org.bluez.Agent1">
<method name="Release"/><method name="Cancel"/>
<method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
<method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
<method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
<method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
<method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
<method name="RequestAuthorization"><arg type="o" direction="in"/></method>
<method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
</interface></node>'''


def snapshot(adapter=None):
    objects=bus_call(DEST,'/','org.freedesktop.DBus.ObjectManager','GetManagedObjects').unpack()[0]
    adapters=[{'path':path,**interfaces[DEST+'.Adapter1']} for path,interfaces in objects.items() if DEST+'.Adapter1' in interfaces]
    if not adapters:return {'adapters':[],'devices':[],'adapter':None}
    selected=next((item for item in adapters if item['path']==adapter),adapters[0])
    devices=[{'path':path,**interfaces[DEST+'.Device1']} for path,interfaces in objects.items()
             if DEST+'.Device1' in interfaces and interfaces[DEST+'.Device1'].get('Adapter')==selected['path']]
    owner=bus_call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetNameOwner','(s)',(DEST,)).unpack()[0]
    return {'adapters':adapters,'devices':sorted(devices,key=lambda d:(not d.get('Connected',False),not d.get('Paired',False),d.get('Alias','').casefold())),
            'adapter':selected,'owner':owner}


def action(adapter,device,method,value=None):
    if not re.fullmatch(r'/org/bluez/hci\d+',adapter):raise ValueError('Invalid Bluetooth adapter')
    if device and not re.fullmatch(re.escape(adapter)+r'/dev_[A-Fa-f0-9_]{17}',device):raise ValueError('Invalid Bluetooth device')
    if method=='Powered' and device is None and type(value) is bool:
        return bus_call(DEST,adapter,'org.freedesktop.DBus.Properties','Set','(ssv)',(DEST+'.Adapter1',method,GLib.Variant('b',value)))
    if method in ('StartDiscovery','StopDiscovery') and not device:
        return bus_call(DEST,adapter,DEST+'.Adapter1',method)
    if method=='RemoveDevice' and device:
        return bus_call(DEST,adapter,DEST+'.Adapter1',method,'(o)',(device,))
    if method in ('Connect','Disconnect') and device:
        return bus_call(DEST,device,DEST+'.Device1',method,timeout=15000)
    if device and method in ('Trusted','Blocked') and type(value) is bool:
        return bus_call(DEST,device,'org.freedesktop.DBus.Properties','Set','(ssv)',(DEST+'.Device1',method,GLib.Variant('b',value)))
    raise ValueError('Invalid Bluetooth action')


class PairingAgent:
    def __init__(self,host,device,owner,done):
        self.host,self.device,self.owner,self.done=host,device,owner,done
        self.closed,self.registered=False,False
        self.prompt=None
        self.path=PATH+'_'+secrets.token_hex(8)
        self.bus=Gio.bus_get_sync(Gio.BusType.SYSTEM,None)
        info=Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]
        self.export=self.bus.register_object(self.path,info,self.method,None,None)
        self.cancel=Gio.Cancellable()
        self.call('/org/bluez','org.bluez.AgentManager1','RegisterAgent','(os)',(self.path,'KeyboardDisplay'),self.ready)

    def call(self,path,interface,method,signature,values,callback,timeout=120000):
        args=GLib.Variant(signature,values) if signature else None
        self.bus.call(DEST,path,interface,method,args,None,Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION,timeout,self.cancel,callback,None)

    def ready(self,bus,result,_):
        try:
            bus.call_finish(result);self.registered=True
            if self.closed:
                self.unregister();return
            self.call(self.device,'org.bluez.Device1','Pair',None,(),self.paired)
        except Exception as error:self.finish(str(error))

    def paired(self,bus,result,_):
        try:bus.call_finish(result);error=None
        except Exception as exc:error=str(exc)
        self.finish(error)

    def finish(self,error=None):
        if self.closed:return
        self.close()
        if not self.host.closed:self.done(error)

    def close(self):
        if self.closed:return
        self.closed=True;self.cancel.cancel()
        if self.prompt:self.prompt.response(Gtk.ResponseType.CANCEL)
        # Cleanup calls get an independent cancellable so cancelling Pair does
        # not also cancel UnregisterAgent/CancelPairing.
        if self.registered:
            self.bus.call(DEST,self.device,'org.bluez.Device1','CancelPairing',None,None,Gio.DBusCallFlags.NONE,3000,None,None,None)
        self.unregister()
        self.bus.unregister_object(self.export)

    def unregister(self):
        self.bus.call(DEST,'/org/bluez','org.bluez.AgentManager1','UnregisterAgent',GLib.Variant('(o)',(self.path,)),None,Gio.DBusCallFlags.NONE,3000,None,None,None)
        self.registered=False

    def method(self,bus,sender,path,interface,method,parameters,invocation):
        if self.closed or sender!=self.owner:
            invocation.return_dbus_error('org.bluez.Error.Rejected','Unknown pairing requester');return
        values=parameters.unpack()
        if method in ('Cancel','Release'):
            if self.prompt:self.prompt.response(Gtk.ResponseType.CANCEL)
            invocation.return_value(None);return
        if not values or values[0]!=self.device:
            invocation.return_dbus_error('org.bluez.Error.Rejected','Unexpected device');return
        from adws_native_settings_gui import Form,caption,entry
        dialog=Form(self.host,'蓝牙配对确认');self.prompt=dialog
        dialog.body.pack_start(caption(self.device.rsplit('/',1)[-1].removeprefix('dev_').replace('_',':')),False,False,0)
        if method in ('DisplayPasskey','DisplayPinCode','RequestConfirmation'):
            code=f'{values[1]:06d}' if method!='DisplayPinCode' else str(values[1])
            dialog.body.pack_start(caption(tr('请核对设备上的配对码：')+' '+code,'settings-hero-title'),False,False,0)
        elif method in ('RequestPinCode','RequestPasskey'):
            dialog.field('code','设备 PIN / 配对码',entry())
        else:dialog.body.pack_start(caption('是否允许此设备配对或使用蓝牙服务？'),False,False,0)
        # Display notifications must acknowledge immediately; leave a visible
        # code until the user dismisses it or BlueZ ends pairing.
        if method in ('DisplayPasskey','DisplayPinCode'):
            invocation.return_value(None);dialog.show_all()
            def dismissed(*_):
                if self.prompt is dialog:self.prompt=None
                dialog.destroy()
            dialog.connect('response',dismissed)
            return
        answer=dialog.read();self.prompt=None
        if answer is None or self.closed:
            invocation.return_dbus_error('org.bluez.Error.Rejected','User cancelled');return
        if method=='RequestPasskey':
            code=answer['code']
            if not re.fullmatch(r'\d{1,6}',code):invocation.return_dbus_error('org.bluez.Error.Rejected','Invalid passkey');return
            invocation.return_value(GLib.Variant('(u)',(int(code),)))
        elif method=='RequestPinCode':
            code=answer['code']
            if not code or len(code.encode())>16:invocation.return_dbus_error('org.bluez.Error.Rejected','Invalid PIN');return
            invocation.return_value(GLib.Variant('(s)',(code,)))
        else:invocation.return_value(None)

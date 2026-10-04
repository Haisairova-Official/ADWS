"""Fixture-only GUI regression: no live D-Bus writes or account/device changes."""
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import gi
gi.require_version('Gtk','3.0')
gi.require_version('Polkit','1.0')
from gi.repository import Gtk,GLib,Gdk,Polkit,Gio
from adws_native_settings_gui import network_sections,sound_sections,bluetooth_sections,account_sections,power_sections,Form
import adws_native_settings_gui as gui
import adws_native_services as native
import adws_native_input as inputs
import adws_native_accounts as accounts
import adws_native_bluetooth as bluetooth
import adws_native_auth as auth
import adws_power_policy as power
Gtk.init([])
main=threading.get_ident()

def pump(seconds=.15):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        while Gtk.events_pending():Gtk.main_iteration()
        time.sleep(.003)

def descendants(widget):
    yield widget
    if isinstance(widget,Gtk.Container):
        for child in widget.get_children():yield from descendants(child)

class Host(Gtk.Window):
    def __init__(self):
        super().__init__();self.closed=False;self.busy=False;self.errors=[];self.account_header=Mock()
        self.set_default_size(1000,780);self.scroll=Gtk.ScrolledWindow();self.scroll.set_overlay_scrolling(False)
        self.body=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=18);self.body.set_border_width(24)
        self.scroll.add(self.body);self.add(self.scroll)
        # Style API is installed by the full settings host; fixtures remain
        # usable without theme files and never apply system changes.
    def error(self,message):self.errors.append(message)
    def confirm(self,*args):return False
    def run_worker(self,job,success,on_failure=None):
        assert threading.get_ident()==main;self.busy=True
        def work():
            try:job();error=None
            except Exception as exc:error=exc
            def done():
                assert threading.get_ident()==main;self.busy=False
                if error:
                    self.errors.append(str(error))
                    if on_failure:on_failure()
                else:success()
                return False
            GLib.idle_add(done)
        threading.Thread(target=work,daemon=True).start()
    def reset(self):
        for child in self.body.get_children():child.destroy()
        pump()

profile={'path':native.NM_SETTINGS+'/1','name':'Fixture Wi-Fi','type':'802-11-wireless','active':None,'settings':{'connection':{'id':GLib.Variant('s','Fixture Wi-Fi')},'ipv4':{'method':GLib.Variant('s','auto')},'ipv6':{'method':GLib.Variant('s','auto')}}}
ap={'ssid':b'Fixture Wi-Fi','name':'Fixture Wi-Fi','device':native.NM_ROOT+'/Devices/1','path':native.NM_ROOT+'/AccessPoint/1','signal':90,'security':'wpa-psk','active':False}
blue={'adapter':{'path':'/org/bluez/hci0'},'adapters':[{'path':'/org/bluez/hci0'},{'path':'/org/bluez/hci1'}],'owner':':1.5','devices':[{'path':'/org/bluez/hci0/dev_AB_CD_EF_01_02_03','Alias':'Fixture keyboard','Address':'AB:CD:EF:01:02:03','Paired':True,'Connected':True,'Trusted':False}]}
user={'path':accounts.ROOT+'/User1000','Uid':1000,'UserName':'fixture','RealName':'Fixture User','AccountType':0,'Locked':False}
fcitx={'group':'Default','layout':'us','enabled':[('keyboard-us',''),('pinyin','')],'available':[('keyboard-us','English','','','','',False),('pinyin','Pinyin','','','','',True)],'addons':[('classicui','Classic UI','Candidate panel',0,True,False),('dbus','D-Bus','Communication',0,False,True)]}
volume={'front-left':{'value':32768},'front-right':{'value':32768}}
audio={'sink-inputs':[{'index':7,'sink':1,'properties':{'application.name':'Fixture Player'},'volume':volume,'mute':False}],'source-outputs':[],'cards':[{'index':0,'name':'Card','profiles':{'stereo':{'description':'Stereo','available':'yes'}},'active_profile':'stereo'}],'sinks':[{'index':1,'name':'speaker','description':'Fixture Speaker','volume':volume,'ports':[{'name':'analog-output','description':'Analog output'}],'active_port':'analog-output'}],'sources':[]}
patches=[patch.object(native,'bus_call',side_effect=AssertionError('Live bus operation forbidden')),patch.object(native,'command',side_effect=AssertionError('Live command forbidden')),patch.object(accounts,'bus_call',side_effect=AssertionError('Live account operation forbidden')),patch.object(native,'nm_wifi',return_value=[ap]),patch.object(native,'nm_profiles',return_value=[profile]),patch('adws_sound_settings.snapshot',return_value={**audio,'default_sink':'speaker','default_source':''}),patch.object(native,'fcitx_snapshot',return_value=fcitx),patch.object(bluetooth,'snapshot',return_value=blue),patch.object(bluetooth,'action',side_effect=AssertionError('Live Bluetooth operation forbidden')),patch.object(accounts,'users',return_value=[user]),patch.object(accounts,'locale_snapshot',return_value={'values':{'LANG':'C.UTF-8'},'locales':['C','C.UTF-8']}),patch.object(accounts,'timezone_snapshot',return_value={'zones':['UTC','Asia/Shanghai'],'timezone':'UTC','ntp':True,'can_ntp':True}),patch.object(power,'load',return_value=power.defaults()),patch.object(power,'logind_snapshot',return_value={key:'ignore' for key in ('HandlePowerKey','HandleLidSwitch','HandleLidSwitchExternalPower','HandleLidSwitchDocked')})]
for item in patches:item.start()
try:
    host=Host();host.show_all()
    for name,render in [('network',network_sections),('bluetooth',bluetooth_sections),('sound',sound_sections),('region',account_sections),('power',power_sections),('input',inputs.fcitx_sections)]:
        host.reset();render(host,host.body);host.show_all();pump(.5)
        labels=[w.get_text() for w in descendants(host.body) if isinstance(w,Gtk.Label)]
        assert not any('forbidden' in text for text in labels),(name,labels)
        assert not host.errors,(name,host.errors)
        if name=='input':
            switches=[w for w in descendants(host.body) if isinstance(w,Gtk.Switch)]
            assert sorted(w.get_active() for w in switches)==[False,True], 'Fcitx configurable/enabled fields reversed'
        picture=Gdk.pixbuf_get_from_window(host.get_window(),0,0,host.get_allocated_width(),host.get_allocated_height())
        picture.savev('/tmp/adws-native-'+name+'.png','png',[],[])
        print('PASS',name,'native controls',flush=True)
    host.reset()
    with patch.object(native,'bus_call',return_value=GLib.Variant('(b)',(False,))),patch.object(native,'fcitx_snapshot') as activate,patch.object(Gio.SettingsSchemaSource,'get_default',return_value=None):
        inputs.input_sections(host,host.body);pump(.3);activate.assert_not_called()
    print('PASS opening input settings does not activate a daemon',flush=True)
    # Cancel the profile form: no network update, including hidden credentials.
    with patch.object(native,'nm_update') as update:
        GLib.idle_add(lambda:(next(w for w in Gtk.Window.list_toplevels() if isinstance(w,Form)).response(Gtk.ResponseType.CANCEL),False)[1])
        gui.edit_profile(Mock(host=host),profile);update.assert_not_called()
    # A failed immediate action must refresh to the real service state.
    host.reset();renders=[]
    section=gui.NativeSection(host,host.body,'Fixture',lambda:False,lambda s,data:renders.append(data));pump(.2)
    def fail():raise RuntimeError('Fixture operation rejected')
    section.change(fail);pump(.3);assert renders==[False,False],renders
    assert host.errors.pop()=='Fixture operation rejected'
    # Close while discovery runs: stale data must not recreate destroyed rows.
    gate=threading.Event();called=[]
    section=gui.NativeSection(host,host.body,'Fixture',lambda:(gate.wait(2),True)[1],lambda *_:called.append(True))
    section.box.destroy();gate.set();pump(.2);assert not called
    # Native Polkit dialog uses no real authority, helper, or password changes.
    session=Mock();signals={}
    session.connect.side_effect=lambda name,callback:signals.__setitem__(name,callback)
    agent=auth.AuthenticationAgent(host)
    with patch.object(auth.PolkitAgent.Session,'new',return_value=session):
        agent.do_initiate_authentication('fixture.action','Fixture authorization','',None,'fixture-cookie',[Polkit.UnixUser.new(os.getuid())],None,None,None)
        assert len(agent.pending)==1
        signals['request'](session,'Password:',False)
        agent.close();pump();assert not agent.pending;session.cancel.assert_called_once()
    host.closed=True;host.destroy();pump()
    print('PASS cancel, errors, discovery cleanup and native authentication',flush=True)
finally:
    for item in reversed(patches):item.stop()

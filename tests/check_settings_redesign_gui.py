"""Fixture-only integration/visual checks for Input, Sound, Bluetooth and Accounts."""
import importlib.util
import os
from pathlib import Path
import sys
import time
from contextlib import ExitStack
from unittest.mock import patch
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk, Gdk, GLib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('adws_config',ROOT/'tools/adws-config.py')
config=importlib.util.module_from_spec(spec);sys.modules[spec.name]=config;spec.loader.exec_module(config)
from adws_system_settings import SystemSettingsWindow
import adws_native_services as native
import adws_native_accounts as accounts
import adws_system_pages as services
import adws_input_settings as keyboard


def pump(seconds=.35):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        while Gtk.events_pending():Gtk.main_iteration_do(False)
        time.sleep(.003)


def descendants(widget):
    yield widget
    if isinstance(widget,Gtk.Container):
        for child in widget.get_children():yield from descendants(child)


def shot(window,name):
    pump(.15)
    locale='zh' if os.environ.get('LANGUAGE','').startswith('zh') else 'en'
    image=Gdk.pixbuf_get_from_window(window.get_window(),0,0,window.get_allocated_width(),window.get_allocated_height())
    image.savev('/tmp/adws-settings-new-'+name+'-'+locale+'.png','png',[],[])


volume={'front-left':{'value':36044},'front-right':{'value':36044}}
audio={'default_sink':'speakers','default_source':'microphone',
    'sinks':[{'index':1,'name':'speakers','description':'Built-in Speakers','volume':volume,'mute':False,
              'ports':[{'name':'analog-output','description':'Analog output'}],'active_port':'analog-output'}],
    'sources':[{'index':2,'name':'microphone','description':'USB Microphone','volume':volume,'mute':False}],
    'sink-inputs':[{'index':3,'sink':1,'properties':{'application.name':'Firefox'},'volume':volume,'mute':False}],
    'source-outputs':[],'cards':[]}
user={'path':accounts.ROOT+'/User1000','Uid':1000,'UserName':'akizuki','RealName':'Akizuki','AccountType':1,'Locked':False}
blue={'adapter':{'path':'/org/bluez/hci0'},'adapters':[{'path':'/org/bluez/hci0'}],'owner':':1.5',
      'devices':[{'path':'/org/bluez/hci0/dev_AB_CD_EF_01_02_03','Alias':'Wireless Headphones',
                  'Address':'AB:CD:EF:01:02:03','Paired':True,'Connected':True,'Trusted':True}]}
fcitx={'group':'Default','layout':'us','enabled':[('keyboard-us',''),('pinyin','')],
       'available':[('keyboard-us','English','','','','',False),('pinyin','Pinyin','','','','',True)],
       'addons':[('classicui','Classic UI','Candidate panel',0,True,True),('dbus','D-Bus','Communication',0,False,True)]}
from PIL import Image
import io
_fixture_avatar=io.BytesIO();Image.new('RGBA',(48,48),(188,140,255,255)).save(_fixture_avatar,format='PNG')
user['avatar_png']=_fixture_avatar.getvalue()
region={'avatar_png':_fixture_avatar.getvalue(),'username':'akizuki','name':'Akizuki','language':'zh_CN.UTF-8','time':'zh_CN.UTF-8','numeric':'zh_CN.UTF-8',
        'desktop':'niri','account':None,'locales':['C','en_US.utf8','zh_CN.utf8']}
patches=[patch('adws_display.detect_session',return_value='niri'),patch('adws_display.outputs',return_value=[]),
    patch.dict(services.READERS,{'bluetooth':lambda:{'adapter':'Built-in Bluetooth','powered':True,'devices':[]},'region':lambda:region}),
    patch('adws_sound_settings.snapshot',return_value=audio),patch.object(accounts,'users',return_value=[user,{**user,'Uid':1001,'UserName':'guest','RealName':'Guest','AccountType':0}]),
    patch.object(accounts,'locale_snapshot',return_value={'values':{'LANG':'zh_CN.UTF-8'},'locales':['C','en_US.utf8','zh_CN.utf8']}),
    patch.object(accounts,'timezone_snapshot',return_value={'zones':['UTC','Asia/Shanghai'],'timezone':'Asia/Shanghai','ntp':True,'can_ntp':True}),
    patch('adws_native_bluetooth.snapshot',return_value=blue),patch('adws_native_bluetooth.action',side_effect=AssertionError('Live Bluetooth write forbidden')),
    patch.object(native,'fcitx_snapshot',return_value=fcitx),
    patch.object(native,'bus_call',side_effect=lambda *args,**kwargs:GLib.Variant('(b)',(True,)) if len(args)>3 and args[3]=='NameHasOwner' else (_ for _ in ()).throw(AssertionError('Live bus operation forbidden'))),
    patch.object(native,'command',side_effect=AssertionError('Live service command forbidden')),
    patch.object(accounts,'bus_call',side_effect=AssertionError('Live account operation forbidden')),
    patch.object(keyboard,'read_niri_repeat',return_value={'rate':25,'delay':500}),
    patch.object(keyboard,'niri_layouts',return_value={'names':['English (US)','Chinese'],'current_idx':0}),
    patch('adws_keyboard.modifier_taps_supported',return_value=True),patch('adws_keyboard.current_profile',return_value='traditional')]
with ExitStack() as stack:
    for item in patches:stack.enter_context(item)
    window=SystemSettingsWindow(config)
    errors=[];window.error=lambda error:errors.append(error)
    for key in ('input','sound','bluetooth','region','start'):
        window.show_page(key);pump(.6)
        assert not errors,(key,errors)
        assert not window.dirty,(key,window.dirty)
        for widget in descendants(window.pages[key]):
            if isinstance(widget,Gtk.Switch) and widget.get_mapped():
                assert widget.get_allocated_height()<=widget.get_preferred_height()[1]+2,(key,widget.get_allocated_height())
                assert widget.get_allocated_width()<=widget.get_preferred_width()[1]+2,(key,widget.get_allocated_width())
        shot(window,key)
        if key=='input':
            page=window.input_page
            page.tabs.stack.set_visible_child_name('shortcuts');pump();shot(window,'shortcuts')
            page.tabs.stack.set_visible_child_name('methods');pump();shot(window,'input-methods')
            page.tabs.stack.set_visible_child_name('keyboard')
            page.rate.set_value(32);assert 'input' in window.dirty
            page.tabs.stack.set_visible_child_name('methods');page.tabs.stack.set_visible_child_name('keyboard')
            assert page.rate.get_value_as_int()==32
            window.dirty.clear();window.update_footer()
        if key=='sound':
            controller=window.service_pages[key]
            tabs=next(w for w in descendants(controller.box) if hasattr(w,'stack'))
            tabs.stack.set_visible_child_name('apps');pump();shot(window,'sound-apps')
        if key=='region':
            current=[w for w in descendants(window.pages[key]) if isinstance(w,Gtk.Image) and w.get_style_context().has_class('settings-current-avatar')]
            assert len(current)==1 and current[0].get_storage_type()==Gtk.ImageType.PIXBUF
            assert current[0].get_parent().get_children()[0] is current[0]
            images=[w for w in descendants(window.pages[key]) if isinstance(w,Gtk.Image) and w.get_style_context().has_class('settings-user-avatar')]
            assert len(images)==2
            for avatar in images:assert avatar.get_parent().get_children()[0] is avatar
            scroll=window.pages[key].get_vadjustment();scroll.set_value(scroll.get_upper()-scroll.get_page_size())
            pump();shot(window,'accounts')
        if key=='start':
            editor=window.owners['taskbar'].layout_editor
            assert 'akiacg' in [item[1] for item in editor.menu_theme.get_model()]
            editor.menu_theme.set_active_id('akiacg')
            assert editor.menu_theme.get_active_id()=='akiacg'
            assert editor.collect_layout()['options']['start_menu_theme']=='akiacg'
            window.dirty.clear();window.update_footer()
    window.resize(880,680);window.show_page('sound');pump();shot(window,'compact')
    assert window.get_allocated_width()<=890,window.get_allocated_width()
    window.destroy();pump()
    assert not errors,errors
print('PASS redesigned settings, compact toggles, avatars, tab state and AkiACG selection')

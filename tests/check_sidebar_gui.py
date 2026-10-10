"""Run under an isolated Xvfb/private D-Bus; never alter real hardware."""
import os
import sys
import tempfile
import time
import threading
import subprocess
from pathlib import Path
from unittest.mock import patch
root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root/'tools'), str(root/'src/niri-desktop-layer')]
base = Path(tempfile.mkdtemp(prefix='adws-sidebar-gui-'))
for env, name in [('HOME','home'),('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_CACHE_HOME','cache'),('XDG_STATE_HOME','state')]:
    path = base/name; path.mkdir(); os.environ[env] = str(path)
os.environ.pop('WAYLAND_DISPLAY', None)
os.environ.update(XDG_SESSION_TYPE='x11', GDK_BACKEND='x11', GTK_USE_PORTAL='0', GIO_USE_VFS='local')
from adws_sidebar import Dashboard
from gi.repository import Gtk, GLib, Gdk
Gtk.init([])
app = Gtk.Application(application_id='org.adws.SidebarGuiTest'); app.register(None)
def pump(seconds=.4):
    until = time.monotonic()+seconds
    while time.monotonic() < until:
        while Gtk.events_pending(): Gtk.main_iteration()
        time.sleep(.005)

sink = {'index':1,'volume':40,'mute':False,'description':'Test audio','default':True}
items = [{'name':'DP-1','description':'Test display','value':60,'provider':'ddc'}]
writes = []
with patch('adws_account_header.query_properties', return_value={}), \
     patch('adws_quick_backend.audio', return_value={'sinks':[sink]}), \
     patch('adws_quick_backend.cached_brightness', return_value=None), \
     patch('adws_quick_backend.brightness', return_value=items), \
     patch('adws_quick_backend.audio_write', side_effect=lambda *args: writes.append(args)), \
     patch('adws_quick_backend.brightness_all', side_effect=lambda *args: writes.append(args)), \
     patch('adws_sidebar_widgets.media_snapshot', return_value=None), \
     patch('adws_sidebar_notifications.snapshot',return_value={'provider':'mako','items':[],'dnd':None}), \
     patch('adws_sidebar_widgets.QuickActions.snapshot',return_value={'wifi':{'wifi':True,'devices':[['wlan0','wifi','connected','Test']]},'bluetooth':{'adapter':'Test','powered':False}}):
    w = Dashboard(app); w.motion_settings = (True, 240)
    w.reveal(); pump(.08)
    assert 0 < w.motion_opacity < 1, w.motion_opacity
    pump(); assert w.motion_opacity == 1
    assert w.quick.poll_source and all(item.poll_source for item in w.controls)
    sound, brightness, media = w.controls
    assert sound.scale.get_value() == 40
    # A click during a slow status poll must be queued, never discarded.
    waiting=threading.Event();started=threading.Event()
    state={'wifi':{'wifi':True,'devices':[['wlan0','wifi','connected','Test']]},'bluetooth':{'adapter':'Test','powered':False}}
    def slow_snapshot():started.set();waiting.wait(2);return state
    with patch.object(w.quick,'snapshot',side_effect=slow_snapshot),patch('adws_system_pages.wifi_enabled') as wifi:
        w.quick.refresh();assert started.wait(1)
        w.quick.buttons['wifi'].clicked();waiting.set();pump(.2)
        wifi.assert_called_once_with(False)
    assert brightness.scale.get_value() == 60
    assert not media.buttons['Next'].get_sensitive()
    for value in (41,52,63,75): sound.scale.set_value(value)
    pump(); assert writes == [('sink',1,'volume',75.0)], writes
    pix = Gdk.pixbuf_get_from_window(w.get_window(),0,0,w.get_allocated_width(),w.get_allocated_height())
    pix.savev('/tmp/adws-sidebar-center.png','png',[],[])
    print('SIZE',w.get_size(),w.get_allocated_width(),w.get_preferred_width(),w.get_child().get_allocation().width, 'dock',w.quick_dock.get_preferred_width(), 'stack',w.stack.get_preferred_width())
    notices=[{'id':i,'app':'Chat','title':f'Notice {i}','body':'body','historical':False} for i in range(30)]
    history=[{'id':50+i,'app':'Mail','title':f'History {i}','body':'body','historical':True} for i in range(4)]
    data={'provider':'mako','items':notices+history,'dnd':None}
    with patch('adws_sidebar_notifications.snapshot',return_value=data):
        w.notifications.loaded(data);pump(.05)
        group=w.notifications.groups[('active','chat')]
        assert len(group.get_child().get_children())==6
        for _ in range(3):group.get_child().get_children()[-1].clicked()
        assert len(group.get_child().get_children())==30
        group.set_expanded(False)
        w.notifications.history_expander.set_expanded(True)
        w.notifications.groups[('history','mail')].set_expanded(True)
        newer=dict(data,items=[*notices,dict(notices[0],id=90),*history])
        w.notifications.loaded(newer);pump(.05)
        assert not w.notifications.groups[('active','chat')].get_expanded()
        assert w.notifications.history_expander.get_expanded()
        assert w.notifications.groups[('history','mail')].get_expanded()
    w.stack.set_visible_child_name('widgets'); pump()
    assert not w.quick.poll_source and not w.notifications.poll_source
    assert all(not item.poll_source for item in w.controls)
    assert w.board.columns==2
    original=list(w.board.model['order'])
    w.board.step('brightness',-1); assert w.board.model['order'][0]=='brightness'
    w.board.resize_card('sound',2); assert w.board.model['sizes']['sound']==2
    w.board.remove_card('notes'); assert 'notes' not in w.board.model['order']
    w.board.add_card('notes'); assert 'notes' in w.board.model['order']
    w.board.resize_card('sound',1); w.board.step('sound',-1)
    w.todo.entry.set_text('Test persisted task'); w.todo.add()
    from adws_sidebar import load_config
    assert load_config()['tasks'][0]['text']=='Test persisted task'
    w.todo.edit(0,True); assert load_config()['tasks'][0]['done']
    w.countdown.minutes.set_value(1); w.countdown.reset(); w.countdown.toggle_timer()
    assert load_config()['timer']['deadline']>time.time()
    w.countdown.toggle_timer(); assert 0<load_config()['timer']['remaining']<=60
    pump()
    pix = Gdk.pixbuf_get_from_window(w.get_window(),0,0,w.get_allocated_width(),w.get_allocated_height())
    pix.savev('/tmp/adws-sidebar-readable.png','png',[],[])
    # Real GTK drag, not just a model reorder call.
    source=w.board.cards['brightness'].get_children()[0].get_children()[0]
    target=w.board.cards['sound'].get_children()[0].get_children()[0]
    origin=w.get_window().get_origin(); ox,oy=origin[-2:]
    sx,sy=source.translate_coordinates(w,12,12); tx,ty=target.translate_coordinates(w,12,12)
    subprocess.run(['xdotool','mousemove',str(ox+sx),str(oy+sy),'mousedown','1'],check=True);pump(.15)
    for step in range(1,9):
        subprocess.run(['xdotool','mousemove',str(round(ox+sx+(tx-sx)*step/8)),str(round(oy+sy+(ty-sy)*step/8))],check=True);pump(.05)
    subprocess.run(['xdotool','mouseup','1'],check=True);pump()
    assert w.board.model['order'][:2]==['brightness','sound']
    assert w.interaction_depth==0
    w.is_active = lambda: False
    w.had_focus = True; w.focus_out(); pump(.22)
    assert w.closing
    pump(); assert w.closed
print('SIDEBAR TRANSLUCENT THEME / FADE / FOCUS LOSS / COALESCED CONTROLS PASSED')

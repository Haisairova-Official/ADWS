"""Repeated sidebar lifecycle regression with isolated user data and mocked services."""
import os,sys,tempfile,time,threading
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sys.path[:0]=[str(root/'tools'),str(root/'tests')]
base=Path(tempfile.mkdtemp(prefix='adws-calendar-weather-'))
for env,name in [('HOME','home'),('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_CACHE_HOME','cache'),('XDG_STATE_HOME','state')]:
    path=base/name;path.mkdir();os.environ[env]=str(path)
os.environ.pop('WAYLAND_DISPLAY',None)
os.environ.update(XDG_SESSION_TYPE='x11',GDK_BACKEND='x11',GTK_USE_PORTAL='0',GIO_USE_VFS='local')
from adws_sidebar import Dashboard,load_config
from adws_control_center import ControlCenter
from adws_agenda import save_event
from adws_weather import parse_weather
from test_calendar_weather import fixture
from gi.repository import Gtk,Gdk
Gtk.init([]);app=Gtk.Application(application_id='org.adws.CalendarWeatherTest');app.register(None)
def pump(seconds=.3):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        while Gtk.events_pending():Gtk.main_iteration()
        time.sleep(.005)
def screenshot(window,name):
    pix=Gdk.pixbuf_get_from_window(window.get_window(),0,0,window.get_allocated_width(),window.get_allocated_height())
    pix.savev('/tmp/'+name+'.png','png',[],[])
with patch('adws_tides.city_location',side_effect=ValueError('no fixture city')),patch('adws_account_header.query_properties',return_value={}),patch('adws_quick_backend.audio',return_value={'sinks':[]}),patch('adws_quick_backend.brightness',return_value=[]),patch('adws_quick_backend.cached_brightness',return_value=None),patch('adws_sidebar_widgets.media_snapshot',return_value=None),patch('adws_sidebar_notifications.snapshot',return_value={'provider':None,'items':[],'dnd':None}),patch('adws_sidebar_widgets.QuickActions.snapshot',return_value={}):
    import gc,weakref,json
    from adws_tides import parse_marine
    from test_environment_cards import marine_fixture
    windows=[];surfaces=[];samples=[]
    for cycle in range(40):
        w=Dashboard(app);windows.append(weakref.ref(w));w.reveal();pump(.06)
        w.stack.set_visible_child_name('widgets');pump(.04)
        for key in list(w.board.model['order']):w.board.remove_card(key)
        w.stack.set_visible_child_name('weather');pump(.04)
        now=time.time();data=parse_marine(marine_fixture(now=int(now)-1800),{'latitude':36.06,'longitude':120.4,'name':'Fixture'},now=now)
        w.motion_settings=(True,280)
        for _ in range(4):
            w.tides.render(data);surfaces.append(weakref.ref(w.tides.ocean));pump(.02)
        w.pages['weather'].get_parent().get_parent().get_vadjustment().set_value(10000);pump(.05)
        w.destroy();del w;data=None;pump(.03);gc.collect()
        assert not any(ref() is not None for ref in windows),'Destroyed windows retained'
        assert not any(ref() is not None for ref in surfaces),'Destroyed ocean widgets retained'
        rss=int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')//1024
        samples.append({'cycle':cycle,'rss_kib':rss,'windows':sum(ref() is not None for ref in windows),'surfaces':sum(ref() is not None for ref in surfaces)})
    print(json.dumps(samples),flush=True)

assert samples[-1]['rss_kib']-samples[8]['rss_kib']<8192,'Resident memory keeps growing after warmup'

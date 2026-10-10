"""Visual and interaction regression using fixture weather and isolated user data."""
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
    w=Dashboard(app);w.reveal();w.stack.set_visible_child_name('weather');pump()
    w.city.set_text('Hangzhou');weather_fixture=fixture()
    for day in weather_fixture['weather']:
        for i,hour in enumerate(day['hourly']):hour.update(tempC=str([16,15,18,22,24,23,21,19][i]),chanceofrain=str([5,10,20,30,40,65,80,50][i]))
    data=parse_weather(weather_fixture,'Hangzhou')
    with patch('adws_sidebar.weather',return_value=data) as fetch:
        w.fetch_weather();pump();assert fetch.call_count==1
    assert load_config()['weather_snapshot']['city']=='Hangzhou'
    assert w.weather_view.hour_columns==6,w.weather_view.get_allocation().width
    assert data['astronomy']['sunrise']=='06:00' and data['astronomy']['sunset']=='17:30'
    assert any(isinstance(child,__import__('adws_weather').ForecastChart) for child in w.weather_view.get_children())
    import cairo
    surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,64,64);cr=cairo.Context(surface)
    Gtk.render_background(w.get_style_context(),cr,0,0,64,64)
    surface.flush();alpha=surface.get_data()[32*surface.get_stride()+32*4+3]
    assert 150<=alpha<=190,('Panel alpha',alpha)
    Gtk.render_background(w.pages['weather'].get_children()[0].get_style_context(),cr,0,0,64,64)
    surface.flush();alpha=surface.get_data()[32*surface.get_stride()+32*4+3]
    assert alpha<215,('Stacked card alpha',alpha)
    screenshot(w,'adws-weather-redesign')
    with patch('adws_sidebar.weather',side_effect=TimeoutError('fixture timeout')):
        w.fetch_weather();pump()
    assert load_config()['weather_snapshot']==data and w.weather_button.get_sensitive()
    assert not w.weather_spinner.get_visible()
    assert w.weather_view.get_children()[0].get_visible(),'Keep last valid conditions after failure'
    from adws_tides import parse_marine
    from test_environment_cards import marine_fixture
    coast={'latitude':36.06,'longitude':120.4,'name':'Qingdao test coast','source':'ip'}
    tide_data=parse_marine(marine_fixture(now=int(time.time())-1800),coast);tide_data["nearby"]=True
    with patch('adws_location.system_location',side_effect=RuntimeError('no location service')),patch('adws_location.ip_location',return_value=coast) as ip,patch('adws_tides.marine',return_value=tide_data),patch('adws_sidebar.weather',return_value=dict(data)):
        chooser=w.location_chooser
        chooser.start();pump();assert chooser.prompt.get_visible();ip.assert_not_called()
        chooser.clear();assert not chooser.prompt.get_visible();assert not w.tides.refresh.get_sensitive();ip.assert_not_called()
        chooser.start();pump();chooser.start(use_ip=True);pump()
        ip.assert_called_once_with(consent=True);assert w.tides.content.get_sensitive()
        assert w.tides.data['peaks'] and w.tides.location==coast
        assert __import__('adws_i18n').tr('附近网格模型估算') in w.tides.status.get_text()
        # Geo-weather is ephemeral; the manual city and saved weather are untouched.
        assert load_config()['city']=='Hangzhou' and load_config()['weather_snapshot']==data
        w.pages['weather'].get_parent().get_parent().get_vadjustment().set_value(10000);pump()
        w.motion_settings=(True,280);w.tides.ocean.sync_motion();pump()
        assert w.tides.ocean.source
        old_phase=w.tides.ocean.phase;pump(.15);assert w.tides.ocean.phase!=old_phase
        adjustment=w.pages['weather'].get_parent().get_parent().get_vadjustment()
        adjustment.set_value(0);pump();assert not w.tides.ocean.source and not w.tides.ocean.marker_source
        adjustment.set_value(10000);pump();assert w.tides.ocean.source
        for _ in range(4):
            old=w.tides.ocean;w.tides.render(tide_data);pump(.05)
            assert old.closed and not old.source and not old.marker_source and len(w.weather_surfaces)==1
        screenshot(w,'adws-tides-redesign')
        w.motion_settings=(False,280);w.tides.ocean.sync_motion();assert not w.tides.ocean.source
        w.motion_settings=(True,280);w.tides.ocean.sync_motion()
        w.stack.set_visible_child_name('widgets');pump();assert not w.tides.ocean.source and not w.tides.ocean.marker_source
        w.stack.set_visible_child_name('weather');pump()
        chooser.clear();assert w.tides.data is None and not w.tides.content.get_sensitive()
        assert not list(w.weather_surfaces)
    started=threading.Event();release=threading.Event()
    def delayed_location(*_,**kwargs):started.set();release.wait(2);return coast
    with patch('adws_location.system_location',side_effect=delayed_location),patch('adws_location.ip_location') as ip,patch('adws_tides.marine') as marine:
        w.location_chooser.start();assert started.wait(1);w.location_chooser.clear();release.set();pump()
        assert w.tides.location is None;ip.assert_not_called();marine.assert_not_called()
    # A selected city bypasses location services and supersedes pending geolocation.
    started.clear();release.clear()
    with patch('adws_location.system_location',side_effect=delayed_location),patch('adws_location.ip_location') as ip,patch('adws_tides.city_location',return_value=coast) as resolve,patch('adws_tides.marine',return_value=tide_data) as marine,patch('adws_sidebar.weather',return_value=dict(data)):
        w.location_chooser.start();assert started.wait(1)
        w.city.set_text('Qingdao');w.fetch_weather();pump()
        resolve.assert_called_once_with('Qingdao');marine.assert_called_once_with(coast);ip.assert_not_called()
        assert w.tides.data==tide_data
        release.set();pump();assert marine.call_count==1
        assert len([child for child in w.tides.content.get_children() if isinstance(child,Gtk.DrawingArea)])==1
        w.pages['weather'].get_parent().get_parent().get_vadjustment().set_value(10000);pump(.5)
        screenshot(w,'adws-tides-merged')
    # Old city lookups cannot replace the new one or start their marine request.
    started.clear();release.clear()
    def delayed_city(city):
        if city=='Old city':started.set();release.wait(2)
        return dict(coast,name=city)
    with patch('adws_tides.city_location',side_effect=delayed_city),patch('adws_tides.marine',return_value=tide_data) as marine:
        w.tides.set_city('Old city');assert started.wait(1)
        w.tides.set_city('New city');pump();release.set();pump()
        assert marine.call_count==1 and marine.call_args.args[0]['name']=='New city'
    w.stack.set_visible_child_name('widgets');w.board.add_card('calendar');pump()
    assert w.get_size().width<=560,'Compact calendar must not force the sidebar wider'
    w.destroy();pump()
    with patch('adws_tides.city_location',return_value=coast) as resolve,patch('adws_tides.marine',return_value=tide_data),patch('adws_location.system_location') as system,patch('adws_location.ip_location') as ip:
        saved=Dashboard(app);saved.reveal();pump();resolve.assert_not_called()
        saved.stack.set_visible_child_name('weather');pump()
        resolve.assert_called_once_with('Qingdao');system.assert_not_called();ip.assert_not_called()
        saved.destroy();pump()
    center=ControlCenter(app);center.reveal();pump()
    center.calendar.choose(__import__('datetime').date(2024,2,29));pump()
    assert center.selected.isoformat()=='2024-02-29'
    save_event({'title':'Design review','date':'2024-02-29','time':'14:00','end':'15:00'})
    center.reload_agenda();assert 29 in center.calendar.marks
    center.calendar.navigate(1);assert not center.calendar.marks
    center.calendar.navigate(-1);assert 29 in center.calendar.marks
    pump();screenshot(center,'adws-calendar-redesign')
    center.destroy();pump()
print('CALENDAR / WEATHER: date navigation, event dots, bounded layout, cache and network failure passed')

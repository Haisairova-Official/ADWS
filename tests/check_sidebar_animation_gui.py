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
    import json,statistics
    class Measured(Dashboard):
        def draw_surface(self,widget,cr):
            if getattr(self,'phase',None) and (self.motion_source or getattr(self,'_reveal_pending',False) or self.stack.get_transition_running()):self.paint_times[self.phase].append(time.perf_counter())
            return super().draw_surface(widget,cr)
    report=[]
    for cycle in range(3):
        start=time.perf_counter();w=Measured(app);construction=(time.perf_counter()-start)*1000
        w.motion_settings=(True,280);w.stack.set_transition_duration(280);w.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        w.paint_times={name:[] for name in ('open','widgets','info','close')}
        w.phase='open';w.reveal();pump(.5)
        w.phase='widgets';w.stack.set_visible_child_name('widgets');pump(.5)
        menu=w.board.add_button.get_popup();cards=list(w.board.grid.get_children());w.board.render()
        assert w.board.add_button.get_popup()==menu and list(w.board.grid.get_children())==cards
        w.phase='info';w.stack.set_visible_child_name('info');pump(.5)
        w.phase='close';w.dismiss();pump(.5)
        assert w.closed and not w.motion_source and w._motion_snapshot is None
        result={'construction_ms':round(construction,1)}
        for phase,stamps in w.paint_times.items():
            gaps=[(b-a)*1000 for a,b in zip(stamps,stamps[1:]) if b-a<.15]
            result[phase]={'frames':len(stamps),'max_gap_ms':round(max(gaps,default=0),1),'gaps_over_25ms':sum(g>25 for g in gaps)}
        report.append(result)
    print(json.dumps(report),flush=True)

    w=Measured(app);w.motion_settings=(True,280);w.reveal();pump(.08)
    w.dismiss();pump(.05);w.closing=False;w.animate(True);pump(.4)
    assert not w.closed and w.motion_opacity==1
    w.dismiss();pump(.4);assert w.closed and not w.motion_source and w._motion_snapshot is None
    w=Measured(app);w.motion_settings=(False,280);w.reveal();pump(.05)
    w.dismiss();assert w.closed and not w.motion_source

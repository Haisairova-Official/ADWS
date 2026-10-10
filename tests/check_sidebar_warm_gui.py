"""Bounded hidden-window reuse, deferred updates and transition-cache regression."""
import gc
import os
from pathlib import Path
import sys
import tempfile
import time
import weakref
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'tools'),str(root/'tests')]
base=Path(tempfile.mkdtemp(prefix='adws-warm-test-'))
for variable, folder in [('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_CACHE_HOME','cache'),('XDG_STATE_HOME','state')]:
    path=base/folder;path.mkdir();os.environ[variable]=str(path)
if '--wayland' not in sys.argv:
    os.environ.pop('WAYLAND_DISPLAY',None);os.environ.update(XDG_SESSION_TYPE='x11',GDK_BACKEND='x11')
os.environ.update(GTK_USE_PORTAL='0',GIO_USE_VFS='local')
from adws_sidebar import Dashboard
from adws_popup import cache_stack_transitions
from adws_weather import parse_weather
from test_calendar_weather import fixture
from gi.repository import Gtk,GLib
Gtk.init([])
app=Gtk.Application(application_id='org.adws.SidebarWarmTest');app.register(None)
def pump(seconds):
    loop=GLib.MainLoop();GLib.timeout_add(max(1,int(seconds*1000)),lambda:(loop.quit(),False)[1]);loop.run()
class Measured(Dashboard):
    def focus_out(self,*_):return False
    def draw_surface(self,widget,cr):
        start=time.perf_counter()
        active=self.motion_active()
        result=super().draw_surface(widget,cr)
        if active:self.draws.append((time.perf_counter()-start)*1000)
        self.frames+=1
        return result
with patch('adws_account_header.query_properties',return_value={}),patch('adws_quick_backend.audio',return_value={'sinks':[]}),patch('adws_quick_backend.brightness',return_value=[]),patch('adws_quick_backend.cached_brightness',return_value=None),patch('adws_sidebar_widgets.media_snapshot',return_value=None),patch('adws_sidebar_notifications.snapshot',return_value={'provider':None,'items':[],'dnd':None}),patch('adws_sidebar_widgets.QuickActions.snapshot',return_value={}):
    w=Measured(app);w.retain_on_close=True;w.draws=[];w.frames=0
    w.motion_settings=(True,180);w.stack.set_transition_duration(180);w.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    w.weather_view.display(parse_weather(fixture(),'Fixture'))
    builds=[];rss=[]
    for cycle in range(12):
        w.reveal();delivered=[];w.after_motion(lambda:delivered.append(w.motion_active()))
        pump(.65);assert delivered==[False]
        w.stack.set_visible_child_name('weather' if cycle%2 else 'widgets');pump(.3)
        w.dismiss();pump(.3)
        assert not w.get_visible() and not w.closed and not w.motion_source
        assert w._motion_snapshot is None and not w.deferred_sources
        count=w.frames;pump(.08);assert count==w.frames,'hidden panel keeps painting'
        rss.append(int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')//1024)
    print('Warm 12-cycle RSS KiB:',rss,'max draw ms:',round(max(w.draws),2))
    assert rss[-1]-rss[3]<8192
    w.reveal();pump(.35)
    # Simulate an occluded compositor withholding all further frame callbacks.
    real_add=w.add_tick_callback
    w.add_tick_callback=lambda callback:real_add(lambda *_:True)
    w.dismiss()
    pump(.4)
    assert not w.get_visible() and not w.motion_source and not w.motion_deadline
    del real_add
    del w.add_tick_callback
    # Deferred UI mutations must not all land on the same completion frame.
    times=[]
    for _ in range(5): w.after_motion(lambda:times.append(time.monotonic()))
    pump(.25)
    assert len(times)==5 and all(b-a>.020 for a,b in zip(times,times[1:])),times
    ref=weakref.ref(w);w.destroy();del w;pump(.2);gc.collect();assert ref() is None

    # Incoming page draws once during crossfade, then resumes live updates.
    window=Gtk.Window();stack=Gtk.Stack();stack.set_transition_duration(220);stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    first=Gtk.DrawingArea();second=Gtk.DrawingArea();second.set_size_request(200,200)
    stack.add_named(first,'first');stack.add_named(second,'second');window.add(stack)
    cache_stack_transitions(stack)
    paints=[]
    second.connect('draw',lambda *_:paints.append(stack.get_transition_running()) or False)
    window.show_all();pump(.1);stack.set_visible_child_name('second');pump(.4)
    assert sum(paints)<=2,paints
    second.queue_draw();pump(.08);assert paints[-1] is False
    window.destroy()
print('PASS: bounded reuse, deferred delivery, hidden rendering stopped, cache and disposal')

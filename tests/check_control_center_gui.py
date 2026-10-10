"""Isolated popup interaction test; hardware backends are stubbed."""
import os, sys, tempfile, time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
base=Path(tempfile.mkdtemp(prefix='adws-center-gui-'))
for env,name in [('HOME','home'),('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_CACHE_HOME','cache'),('XDG_STATE_HOME','state')]:
    p=base/name;p.mkdir();os.environ[env]=str(p)
os.environ.pop('WAYLAND_DISPLAY',None)
os.environ.update(XDG_SESSION_TYPE='x11',GDK_BACKEND='x11',GTK_USE_PORTAL='0',GIO_USE_VFS='local')
from adws_control_center import ControlCenter, popup_geometry
from adws_agenda import load_events
from gi.repository import Gtk, Gdk
Gtk.init([])
app=Gtk.Application(application_id='org.adws.CenterTest');app.register(None)
def pump(seconds=.35):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        while Gtk.events_pending():Gtk.main_iteration()
        time.sleep(.005)
sink={'index':1,'volume':40,'mute':False,'description':'Test audio','default':True}
items=[{'name':'DP-1','description':'Test display','value':60,'provider':'ddc'}]
writes=[]
with patch('adws_quick_backend.audio',return_value={'sinks':[sink]}) as audio,patch('adws_quick_backend.brightness',return_value=items) as brightness,patch('adws_quick_backend.cached_brightness',return_value=None),patch('adws_quick_backend.audio_write',side_effect=lambda *a:writes.append(a)),patch('adws_sidebar_widgets.QuickActions.snapshot',return_value={'wifi':{'wifi':True,'devices':[]},'bluetooth':{'adapter':'Test','powered':False}}):
    w=ControlCenter(app,{'edge':'bottom','x':1150,'inset':48});w.motion_settings=(True,240);w.reveal();pump(.06)
    assert 0<w.motion_opacity<1
    pump();assert w.motion_opacity==1
    assert not w.editor.get_visible()
    assert not audio.called and not brightness.called,'Hidden quick controls should not start hardware reads'
    # Inspect actual RGBA rendering: rounded corners stay clear, backdrop stays translucent.
    import cairo
    surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,w.get_allocated_width(),w.get_allocated_height())
    cr=cairo.Context(surface);w.draw(cr);surface.flush();data=surface.get_data()
    def alpha(x,y):return data[y*surface.get_stride()+4*x+3]
    assert alpha(0,0)==0,alpha(0,0)
    assert 0<alpha(15,w.get_allocated_height()-20)<255
    assert w.get_opacity()==1, 'Native surface opacity must remain stable'
    w.edit_event();pump();assert w.fields['title'].get_mapped()
    w.fields['title'].set_text('');w.save_form();assert w.form_error.get_text()
    w.fields['title'].set_text('测试：设计评审');w.save_form();pump()
    assert len(load_events())==1 and not w.editor.get_visible()
    event=load_events()[0];w.edit_event(event);w.fields['title'].set_text('修改后的日程');w.save_form();pump()
    assert len(load_events())==1 and load_events()[0]['title']=='修改后的日程'
    rect=w.get_display().get_monitor(0).get_geometry()
    for edge in ('top','bottom','left','right'):
        w.position({'edge':edge,'x':1150,'y':650,'inset':48});pump()
        x,y=w.base_position;width,height=w.get_size()
        assert rect.x<=x and x+width<=rect.x+rect.width,(edge,x,width)
        assert rect.y<=y and y+height<=rect.y+rect.height,(edge,y,height)
    w.stack.set_visible_child_name('controls');pump();w.controls[0].scale.set_value(55);pump()
    assert writes==[('sink',1,'volume',55.0)],writes
    sink['volume']=68;sink['mute']=True;pump(4)
    assert w.controls[0].scale.get_value()==68 and w.controls[0].mute.get_active()
    w.stack.set_visible_child_name('calendar');pump()
    assert not w.quick.poll_source and all(not item.poll_source for item in w.controls)
    pix=Gdk.pixbuf_get_from_window(w.get_window(),0,0,w.get_allocated_width(),w.get_allocated_height());pix.savev('/tmp/adws-control-center.png','png',[],[])
    row=w.agenda_list.get_children()[0];button=row.get_children()[-1];w.confirm_delete(button,load_events()[0]);pump()
    # Storage deletion is tested independently; destroy any grab before focus loss.
    grab=Gtk.grab_get_current()
    if grab:grab.hide()
    w.had_focus=True;w.is_active=lambda:False;w.focus_out();pump(.65)
    assert w.closed
print('CONTROL CENTER: agenda validation/edit persistence, four edges, quick controls, animation/focus passed')

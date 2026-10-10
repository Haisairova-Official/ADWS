"""Low-frequency decorative sea motion; never changes forecast measurements."""
import math
import time
import weakref
import cairo
import gi
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk,GLib,Pango,PangoCairo
from datetime import datetime,timezone
from adws_i18n import tr


def sample_runs(samples):
    runs=[];run=[]
    for stamp,height in samples:
        if height is None or (run and stamp-run[-1][0]>3600):
            if run:runs.append(run);run=[]
        if height is not None:run.append((stamp,height))
    if run:runs.append(run)
    return runs


def monotone_segments(points):
    """C1 cubic curves through samples, with control heights inside each interval."""
    if len(points)<2:return []
    slopes=[(b[1]-a[1])/(b[0]-a[0]) for a,b in zip(points,points[1:])]
    tangents=[slopes[0]]
    for left,right in zip(slopes,slopes[1:]):
        tangents.append(2*left*right/(left+right) if left*right>0 else 0)
    tangents.append(slopes[-1]);result=[]
    for i,(a,b) in enumerate(zip(points,points[1:])):
        third=(b[0]-a[0])/3
        result.append((a,(a[0]+third,a[1]+third*tangents[i]),(b[0]-third,b[1]-third*tangents[i+1]),b))
    return result


def tide_at(samples,stamp):
    """Evaluate the same cubic used by the chart; never extrapolate across gaps."""
    for run in sample_runs(samples):
        for start,c1,c2,end in monotone_segments(run):
            if start[0]<=stamp<=end[0]:
                t=(stamp-start[0])/(end[0]-start[0]);u=1-t
                return u*u*u*start[1]+3*u*u*t*c1[1]+3*u*t*t*c2[1]+t*t*t*end[1]
    return None


class OceanSurface(Gtk.DrawingArea):
    def __init__(self,host,data):
        super().__init__();self.host=host;self.source=0;self.closed=False;self.phase=0;self.adjustment=None;self.adjustment_handler=0
        self.marker_source=0;self.geometry_key=None;self.geometry=[]
        self.caption_layout=None;self.caption_text=None;self.caption_width=None;self.marker_stamp=None;self.marker_level=None
        self.data=data;self.progress=1;self.started=time.monotonic();self.duration=.3
        self.set_size_request(-1,180);self.get_style_context().add_class('weather-condition')
        self.set_tooltip_text(tr('当前潮位按预报曲线插值，非实时测量；时间使用查询地点时区。'))
        if not hasattr(host,'weather_surfaces'):host.weather_surfaces=weakref.WeakSet()
        host.weather_surfaces.add(self)
        self.connect('draw',self.draw_sea);self.connect('map',self.mapped)
        self.connect('unmap',self.unmapped);self.connect('destroy',self.dispose)

    def mapped(self,*_):
        self.progress=0 if self.enabled() else 1;self.started=time.monotonic()
        self.duration=max(.2,min(.65,getattr(self.host,'motion_settings',(False,300))[1]/1000))
        scroll=self.get_ancestor(Gtk.ScrolledWindow)
        if scroll:
            self.adjustment=scroll.get_vadjustment()
            self.adjustment_handler=self.adjustment.connect('value-changed',lambda *_:self.sync_motion())
        self.sync_motion()

    def unmapped(self,*_):
        self.stop();self.stop_marker()
        if self.adjustment is not None and self.adjustment_handler:self.adjustment.disconnect(self.adjustment_handler)
        self.adjustment=None;self.adjustment_handler=0

    def in_viewport(self):
        scroll=self.get_ancestor(Gtk.ScrolledWindow)
        if scroll:
            position=self.translate_coordinates(scroll,0,0)
            if position is not None:
                return position[1]<scroll.get_allocated_height() and position[1]+self.get_allocated_height()>0
        return True

    def enabled(self):return bool(getattr(self.host,'motion_settings',(False,0))[0])

    def sync_motion(self):
        if self.closed:return
        visible=self.get_mapped() and self.in_viewport()
        if visible:
            if not self.marker_source:self.marker_source=GLib.timeout_add_seconds(30,self.tick_marker)
        else:self.stop_marker()
        if visible and self.enabled():
            if not self.source:self.source=GLib.timeout_add(50,self.tick)
        else:
            self.stop()
            if not self.enabled():self.progress=1
        self.queue_draw()

    def tick_marker(self):
        if self.closed or self.host.closed or not self.get_mapped() or not self.in_viewport():self.marker_source=0;return False
        self.queue_draw();return True

    def stop_marker(self):
        if self.marker_source:GLib.source_remove(self.marker_source);self.marker_source=0

    def tick(self):
        if self.closed or self.host.closed or not self.get_mapped() or not self.enabled() or not self.in_viewport():self.source=0;return False
        self.progress=1-(1-min(1,(time.monotonic()-self.started)/self.duration))**3
        self.phase=(time.monotonic()%12)/12*math.tau;self.queue_draw();return True

    def stop(self,*_):
        if self.source:GLib.source_remove(self.source);self.source=0

    def dispose(self,*_):
        self.closed=True;self.unmapped();self.host.weather_surfaces.discard(self)
        self.caption_layout=None;self.geometry=[]

    def draw_sea(self,_,cr):
        width,height=self.get_allocated_width(),self.get_allocated_height()
        samples=self.data['samples'];valid=[level for _,level in samples if level is not None]
        if not valid:return False
        color=self.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        low,high=min(valid),max(valid);span=max(.3,high-low)
        first,last=samples[0][0],samples[-1][0]
        cr.save();cr.rectangle(0,0,width,height);cr.clip()
        sky=cairo.LinearGradient(0,0,0,height)
        sky.add_color_stop_rgba(0,color.red,color.green,color.blue,.02)
        sky.add_color_stop_rgba(1,color.red,color.green,color.blue,.10)
        cr.set_source(sky);cr.paint()
        fading=self.progress<1
        if fading:cr.push_group()
        if self.geometry_key!=(width,height):
            self.geometry_key=(width,height);self.geometry=[]
            for run in sample_runs(samples):
                points=[(4+(width-8)*(stamp-first)/max(1,last-first),38+(height-78)*(high-level)/span) for stamp,level in run]
                if len(points)>=2:self.geometry.append((points,monotone_segments(points)))
        for points,curves in self.geometry:
            def path():
                cr.move_to(*points[0])
                for _,c1,c2,end in curves:cr.curve_to(*c1,*c2,*end)
            cr.new_path();path();cr.line_to(points[-1][0],height);cr.line_to(points[0][0],height);cr.close_path()
            cr.save();cr.clip()
            water=cairo.LinearGradient(0,30,0,height)
            water.add_color_stop_rgba(0,color.red,color.green,color.blue,.24)
            water.add_color_stop_rgba(1,color.red,color.green,color.blue,.08)
            cr.set_source(water);cr.paint()
            # Ripples are clipped inside the data-defined water surface. They never move its boundary.
            for layer,alpha in ((0,.09),(1,.12),(2,.16)):
                cr.move_to(0,height)
                for x in range(0,width+5,4):
                    y=height*(.67+layer*.10)+math.sin(x/max(1,width)*math.tau*1.5+self.phase*(1 if layer%2 else -1)+layer)*4
                    cr.line_to(x,y)
                cr.line_to(width,height);cr.close_path();cr.set_source_rgba(color.red,color.green,color.blue,alpha);cr.fill()
            cr.restore();cr.new_path();path();cr.set_line_width(2)
            cr.set_source_rgba(color.red,color.green,color.blue,.9);cr.stroke()
        stamp=time.time()
        if self.marker_stamp is None or abs(stamp-self.marker_stamp)>=30:
            self.marker_stamp=stamp;self.marker_level=tide_at(samples,stamp)
        now=self.marker_stamp;level=self.marker_level
        if level is not None:
            x=4+(width-8)*(now-first)/max(1,last-first);y=38+(height-78)*(high-level)/span
            cr.set_source_rgba(color.red,color.green,color.blue,.4);cr.set_line_width(1);cr.set_dash([3,4])
            cr.move_to(x,30);cr.line_to(x,height-4);cr.stroke();cr.set_dash([])
            cr.set_source_rgba(color.red,color.green,color.blue,.20);cr.arc(x,y,9,0,math.tau);cr.fill()
            cr.set_source_rgba(color.red,color.green,color.blue,1);cr.arc(x,y,4,0,math.tau);cr.fill()
            clock=datetime.fromtimestamp(now+self.data.get('offset',0),timezone.utc).strftime('%H:%M')
            caption=tr('当前预报 · %s · %s 米')%(clock,f'{level:.2f}')
        else:caption=tr('当前时刻暂无有效潮位')
        if self.caption_layout is None:
            self.caption_layout=self.create_pango_layout('');self.caption_layout.set_ellipsize(Pango.EllipsizeMode.END)
        layout=self.caption_layout
        if self.caption_text!=caption:layout.set_text(caption,-1);self.caption_text=caption
        if self.caption_width!=width:layout.set_width(max(1,width-16)*Pango.SCALE);self.caption_width=width
        cr.set_source_rgba(color.red,color.green,color.blue,1);cr.move_to(8,5);PangoCairo.show_layout(cr,layout)
        if fading:cr.pop_group_to_source();cr.paint_with_alpha(self.progress)
        cr.restore();return False

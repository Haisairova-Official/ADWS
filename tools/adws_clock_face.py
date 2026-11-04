"""Cached Cairo clock faces; hand animation follows the monitor's GTK frame clock."""
import math
import time
import weakref
import cairo
from gi.repository import Gtk, GLib, Gdk

FACES=('retro','minimal','railway','orbit')

def hand_positions(epoch,offset=0,face='minimal',seconds=True):
    local=epoch+offset;whole=math.floor(local);phase=local-whole
    second=local%60
    if face=='retro':
        # A short mechanical step with a small spring-back, then a quiet hand.
        t=min(1.,phase/.18);c=1.35
        step=1+(c+1)*(t-1)**3+c*(t-1)**2
        second=(whole-1+step)%60
    elif face=='railway':second=whole%60
    minute=(local/60)%60 if seconds else (whole//60)%60
    return ((local/3600)%12/12,minute/60,second/60)

class ClockFace(Gtk.DrawingArea):
    def __init__(self):
        super().__init__();self.node={};self.tick_id=0;self.timer_id=0;self.paused=False
        self.cached=None;self.cache_key=None;self.last_hands=None
        from adws_desktop_interactive import Picture
        ref=weakref.ref(self)
        def changed():
            owner=ref()
            if owner:owner.image_changed()
        self.picture=Picture(on_change=changed)
        self.connect('destroy',lambda *_:self.picture.destroy())
        self.set_hexpand(True);self.set_vexpand(True)
        self.connect('draw',self.draw);self.connect('map',self.start)
        self.connect('unmap',self.stop);self.connect('destroy',self.stop)
        self.connect('style-updated',self.style_changed)
    def do_get_preferred_width(self):return (100,180)
    def do_get_preferred_height(self):return (100,164)
    def image_changed(self):
        self.cache_key=None
        self.set_tooltip_text(self.picture.get_tooltip_text())
        self.queue_draw()
    def style_changed(self,*_):self.cache_key=None;self.queue_draw()
    def update(self,node):
        changed=self.node!=node;old_seconds=self.node.get('seconds',True);self.node=dict(node)
        self.paused=False
        path=node.get('path','')
        if path:self.picture.update(dict(path=path))
        else:
            self.set_tooltip_text(None)
            if self.picture.path_key is not None:
                self.picture.path_key=None;self.picture.pixbuf=None;self.cache_key=None
        if old_seconds!=node.get('seconds',True):self.stop()
        self.start()
        if changed:self.queue_draw()
    def stop(self,*_):
        if self.tick_id:self.remove_tick_callback(self.tick_id);self.tick_id=0
        if self.timer_id:GLib.source_remove(self.timer_id);self.timer_id=0
    def suspend(self):self.paused=True;self.stop()
    def start(self,*_):
        if self.paused or not self.get_mapped() or self.tick_id or self.timer_id:return
        if self.node.get('seconds',True):self.tick_id=self.add_tick_callback(self.frame)
        else:self.timer_id=GLib.timeout_add_seconds(1,self.minute)
        self.last_hands=None;self.queue_draw()
    def frame(self,widget,clock):
        # Queue only changed hands; ticking faces remain idle between steps.
        now=time.time();face=self.node.get('face','retro')
        stamp=math.floor(now) if face=='railway' or (face=='retro' and now%1>=.18) else now
        if stamp!=self.last_hands:self.last_hands=stamp;self.queue_draw()
        return True
    def minute(self):
        stamp=int(time.time()+self.node.get('utc_offset',0))//60
        if stamp!=self.last_hands:self.last_hands=stamp;self.queue_draw()
        return True
    def colors(self):
        context=self.get_style_context();fg=context.get_color(Gtk.StateFlags.NORMAL)
        face=self.node.get('face','retro')
        palettes={
            'retro':((.94,.88,.74),(.22,.16,.11),(.61,.31,.17)),
            'minimal':((.14,.15,.19),(fg.red,fg.green,fg.blue),(.72,.73,.98)),
            'railway':((.94,.95,.93),(.12,.15,.18),(.83,.23,.26)),
            'orbit':((.09,.11,.17),(fg.red,fg.green,fg.blue),(.65,.73,.96))}
        values=list(palettes[face])
        for i,name in enumerate(('clock_face','clock_ink','clock_accent')):
            found,color=context.lookup_color(name)
            if found:values[i]=(color.red,color.green,color.blue)
        return values
    @staticmethod
    def line(cr,turn,start,end,width,color):
        angle=turn*math.tau-math.pi/2;dx,dy=math.cos(angle),math.sin(angle)
        cr.set_source_rgb(*color);cr.set_line_width(width);cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.move_to(dx*start,dy*start);cr.line_to(dx*end,dy*end);cr.stroke()
    def dial(self,cr,size,colors):
        face=self.node.get('face','retro');bg,ink,accent=colors
        cr.translate(size/2,size/2);cr.scale(size/2-3,size/2-3)
        if self.picture.pixbuf is not None and self.node.get('path'):
            image=self.picture.pixbuf;w,h=image.get_width(),image.get_height();factor=2/min(w,h)
            cr.save();cr.arc(0,0,1,0,math.tau);cr.clip()
            cr.translate(-w*factor/2,-h*factor/2);cr.scale(factor,factor)
            Gdk.cairo_set_source_pixbuf(cr,image,0,0);cr.paint();cr.restore()
        else:
            cr.set_source_rgb(*bg);cr.arc(0,0,1,0,math.tau);cr.fill()
        if not self.node.get('markers',True):return
        cr.set_source_rgba(*accent,.75 if face=='retro' else .25);cr.set_line_width(.035 if face=='retro' else .012);cr.arc(0,0,.97,0,math.tau);cr.stroke()
        if face=='retro':
            cr.set_source_rgba(*accent,.45);cr.set_line_width(.008);cr.arc(0,0,.91,0,math.tau);cr.stroke()
        for i in range(60):
            major=i%5==0
            if face=='minimal' and not major:continue
            if face=='orbit' and not major:continue
            self.line(cr,i/60,.81 if major else .86,.89,.028 if major and face!='retro' else .009,ink)
        if face in ('retro','railway','orbit'):
            roman=['XII','I','II','III','IV','V','VI','VII','VIII','IX','X','XI']
            cr.select_font_face('serif' if face=='retro' else 'sans-serif',cairo.FONT_SLANT_NORMAL,cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(.18 if face=='retro' else .16)
            for i in range(12):
                if face!='retro' and i%3:continue
                text=roman[i] if face=='retro' else str(i or 12)
                angle=i*math.tau/12-math.pi/2;radius=.69
                xb,yb,tw,th,_,_=cr.text_extents(text)
                cr.set_source_rgb(*ink);cr.move_to(math.cos(angle)*radius-tw/2-xb,math.sin(angle)*radius-th/2-yb);cr.show_text(text)
        if face=='orbit':
            for radius,alpha in ((.57,.12),(.48,.09)):
                cr.set_source_rgba(*accent,alpha);cr.set_line_width(.01);cr.arc(0,0,radius,0,math.tau);cr.stroke()
    def draw(self,widget,cr):
        width,height=self.get_allocated_width(),self.get_allocated_height();size=max(1,min(width,height))
        scale=self.get_scale_factor();colors=self.colors();key=(size,scale,self.node.get('face'),tuple(colors),self.node.get('markers',True),self.picture.path_key,id(self.picture.pixbuf))
        if key!=self.cache_key:
            self.cached=cairo.ImageSurface(cairo.FORMAT_ARGB32,size*scale,size*scale);self.cached.set_device_scale(scale,scale)
            self.dial(cairo.Context(self.cached),size,colors);self.cache_key=key
        cr.set_source_surface(self.cached,(width-size)/2,(height-size)/2);cr.paint()
        cr.translate(width/2,height/2);cr.scale(max(1,size/2-3),max(1,size/2-3))
        face=self.node.get('face','retro');bg,ink,accent=colors;seconds=self.node.get('seconds',True)
        hour,minute,second=hand_positions(time.time(),self.node.get('utc_offset',0),face,seconds)
        self.line(cr,hour,-.09,.45,.055 if face=='retro' else .065,ink)
        self.line(cr,minute,-.1,.68,.032 if face=='retro' else .042,ink)
        if seconds:
            self.line(cr,second,-.18,.78,.014,accent)
            if face=='railway':
                a=second*math.tau-math.pi/2;cr.arc(math.cos(a)*.68,math.sin(a)*.68,.055,0,math.tau);cr.fill()
            elif face=='orbit' and self.node.get('markers',True):
                cr.set_source_rgba(*accent,.65);cr.set_line_width(.018);cr.arc(0,0,.94,-math.pi/2,second*math.tau-math.pi/2);cr.stroke()
        cr.set_source_rgb(*(accent if seconds else ink));cr.arc(0,0,.045,0,math.tau);cr.fill()
        return False

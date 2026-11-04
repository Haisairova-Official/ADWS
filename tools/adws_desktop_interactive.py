"""Bounded declarative desktop UI. Packages send data and receive named events."""
import concurrent.futures
from collections import OrderedDict
import json
from pathlib import Path
import re
import threading
import weakref
from gi.repository import Gtk,Gdk,GdkPixbuf,GLib,Gio
from adws_i18n import tr

KINDS={'column','row','grid','label','button','text','file','image','progress','clockface'}
IDENT=re.compile(r'[A-Za-z0-9_-]{1,64}')

def validate_view(value):
    seen=set();count=0
    def visit(node,depth):
        nonlocal count
        count+=1
        if depth>8 or count>160 or not isinstance(node,dict):raise ValueError('Widget tree is too large')
        identity=node.get('id');kind=node.get('type')
        if not isinstance(identity,str) or not IDENT.fullmatch(identity) or identity in seen or kind not in KINDS:raise ValueError('Invalid widget node')
        seen.add(identity)
        for field in ('text','path','placeholder','confirm'):
            if field in node and (not isinstance(node[field],str) or len(node[field])>4096):raise ValueError('Invalid widget text')
        if kind=='text' and (not isinstance(node.get('value',''),str) or len(node.get('value',''))>20000):raise ValueError('Note is too long')
        if kind in ('button','file','text') and (not isinstance(node.get('action'),str) or not IDENT.fullmatch(node['action'])):raise ValueError('Invalid widget action')
        classes=node.get('classes',[])
        if not isinstance(classes,list) or len(classes)>12 or any(not isinstance(c,str) or not IDENT.fullmatch(c) for c in classes):raise ValueError('Invalid widget style')
        if 'enabled' in node and type(node['enabled']) is not bool:raise ValueError('Invalid enabled state')
        if kind=='grid' and (type(node.get('columns'))!=int or not 1<=node['columns']<=8):raise ValueError('Invalid grid columns')
        if kind=='clockface':
            from adws_clock_face import FACES
            if type(node.get('markers',True)) is not bool:raise ValueError('Invalid clock markers')
            if node.get('face') not in FACES or type(node.get('seconds')) is not bool or type(node.get('utc_offset')) is not int or not -86400<=node['utc_offset']<=86400:raise ValueError('Invalid clock face')
        if kind=='image':
            if type(node.get('size',240))!=int or not 24<=node.get('size',240)<=640:raise ValueError('Invalid image size')
            crop=node.get('crop')
            if crop is not None and (not isinstance(crop,list) or len(crop)!=4 or any(type(v)!=int for v in crop) or not 1<=crop[2]<=8 or not 1<=crop[3]<=8 or not 0<=crop[0]<crop[2] or not 0<=crop[1]<crop[3]):raise ValueError('Invalid image crop')
        if kind=='progress' and (type(node.get('value')) not in (float,int) or not 0<=node['value']<=1):raise ValueError('Invalid progress')
        children=node.get('children',[])
        if not isinstance(children,list) or len(children)>64 or (children and kind not in ('row','column','grid','button')) or (kind=='button' and len(children)>1):raise ValueError('Invalid widget children')
        return (identity,kind,node.get('columns'),tuple(visit(c,depth+1) for c in children))
    return visit(value,0)

# At most two decoding workers; at most eight pending/shared pictures. Decoding
# never runs in the GTK main loop, and image completions retain only weak widgets.
_IMAGES=OrderedDict();_PENDING={};_LOCK=threading.Lock()
_POOL=concurrent.futures.ThreadPoolExecutor(max_workers=2,thread_name_prefix='widget-image')

def image_key(path):
    p=Path(path).expanduser();info=p.stat()
    if not p.is_file() or info.st_size>32*1024*1024:raise ValueError('Image must be a file smaller than 32 MiB')
    return (str(p),info.st_mtime_ns,info.st_size)

def load_image(key):
    image=GdkPixbuf.Pixbuf.new_from_file_at_scale(key[0],1024,1024,True)
    return image.apply_embedded_orientation()

class Picture(Gtk.DrawingArea):
    def __init__(self,on_change=None):
        super().__init__();self.pixbuf=None;self.path_key=None;self.node={};self.alive=True;self.on_change=on_change
        self.connect('draw',self.draw);self.connect('destroy',lambda *_:setattr(self,'alive',False))
    def invalidate(self):
        self.queue_draw()
        if self.on_change:self.on_change()
    def do_get_request_mode(self):return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH
    def do_get_preferred_width(self):return (32,self.node.get('size',240))
    def do_get_preferred_height(self):return (32,self.node.get('size',240))
    def do_get_preferred_height_for_width(self,width):return (32,max(32,min(width,640 if self.node.get('crop') else self.node.get('size',240))))
    def update(self,node):
        old=self.node;self.node=node
        if old.get('size')!=node.get('size'):self.queue_resize()
        if old.get('crop')!=node.get('crop') or old.get('fit')!=node.get('fit'):self.invalidate()
        try:key=image_key(node.get('path',''))
        except (OSError,ValueError):
            self.path_key=None;self.pixbuf=None;self.set_tooltip_text(tr('图片不可用，请重新选择。'));self.invalidate();return
        if key==self.path_key:return
        self.path_key=key;self.pixbuf=None;self.set_tooltip_text(None);self.invalidate();ref=weakref.ref(self)
        def done(future):
            try:pixbuf=future.result();error=None
            except Exception:pixbuf=None;error=tr('无法读取图片，请选择其他图片。')
            def apply():
                widget=ref()
                if widget and widget.alive and widget.path_key==key:
                    widget.pixbuf=pixbuf;widget.set_tooltip_text(error);widget.invalidate()
                return False
            GLib.idle_add(apply)
        with _LOCK:
            cached=_IMAGES.get(key)
            if cached is not None:
                _IMAGES.move_to_end(key);self.pixbuf=cached;self.invalidate();return
            future=_PENDING.get(key)
            if future is None:
                if len(_PENDING)>=8:self.path_key=None;return
                future=_POOL.submit(load_image,key);_PENDING[key]=future
        def cache(f):
            with _LOCK:
                _PENDING.pop(key,None)
                try:_IMAGES[key]=f.result()
                except Exception:return
                while len(_IMAGES)>8:_IMAGES.popitem(last=False)
        # Register outside the lock: completed futures invoke callbacks inline.
        future.add_done_callback(cache);future.add_done_callback(done)
    def draw(self,widget,cr):
        w,h=self.get_allocated_width(),self.get_allocated_height();cr.rectangle(0,0,w,h);cr.clip()
        if self.pixbuf is None:
            color=self.get_style_context().get_color(Gtk.StateFlags.NORMAL);cr.set_source_rgba(color.red,color.green,color.blue,.12);cr.paint();return False
        p=self.pixbuf;sw,sh=p.get_width(),p.get_height();x=y=0;crop=self.node.get('crop')
        if crop:
            side=min(sw,sh);x=(sw-side)/2+crop[0]*side/crop[2];y=(sh-side)/2+crop[1]*side/crop[3];sw=side/crop[2];sh=side/crop[3]
        factor=(max if self.node.get('fit')=='cover' else min)(w/sw,h/sh)
        cr.translate((w-sw*factor)/2,(h-sh*factor)/2);cr.scale(factor,factor)
        Gdk.cairo_set_source_pixbuf(cr,p,-x,-y);cr.paint();return False

class Interactive:
    def __init__(self,card,parent):
        self.card=card;self.parent=parent;self.nodes={};self.widgets={};self.shape=None;self.keys={};self.sources={};self.dirty=set();self.syncing=False;self.closed=False;self.alert=None
        self.error=Gtk.Label(wrap=True);self.error.set_no_show_all(True);parent.pack_start(self.error,False,False,0)
        self.root=Gtk.Box(orientation=Gtk.Orientation.VERTICAL);parent.pack_start(self.root,True,True,0)
        card.box.connect('key-press-event',self.key)
    def send(self,action,value=None):
        if self.closed:return False
        okay=bool(self.card.stream and self.card.stream.event(action,value))
        self.error.set_text('' if okay else tr('组件暂时未响应，请重试。'));self.error.set_visible(not okay)
        return okay
    def key(self,widget,event):
        if not self.card.box.has_focus():return False
        action=self.keys.get(Gdk.keyval_name(event.keyval))
        if action:return self.send(action)
        return False
    def activate(self,identity):
        n=self.nodes[identity]
        if n.get('confirm'):
            dialog=Gtk.MessageDialog(transient_for=self.card.layer.window,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.OK_CANCEL,text=n['confirm'])
            answer=dialog.run();dialog.destroy()
            if answer!=Gtk.ResponseType.OK:return
        if n['type']=='file':
            dialog=Gtk.FileChooserDialog(title=tr('选择图片'),transient_for=self.card.layer.window,action=Gtk.FileChooserAction.OPEN)
            dialog.add_buttons(tr('取消'),Gtk.ResponseType.CANCEL,tr('打开'),Gtk.ResponseType.OK)
            filt=Gtk.FileFilter();filt.set_name(tr('图片'));filt.add_pixbuf_formats();dialog.add_filter(filt)
            result=dialog.run();path=dialog.get_filename();dialog.destroy()
            if result==Gtk.ResponseType.OK and path:self.send(n['action'],path)
        else:self.send(n['action'])
    def changed(self,buffer,identity):
        if self.syncing:return
        if buffer.get_char_count()>20000:
            buffer.delete(buffer.get_iter_at_offset(20000),buffer.get_end_iter())
        self.dirty.add(identity)
        if identity in self.sources:GLib.source_remove(self.sources.pop(identity))
        self.sources[identity]=GLib.timeout_add(400,self.flush,identity)
    def flush(self,identity):
        source=self.sources.pop(identity,None)
        if source:GLib.source_remove(source)
        if identity in self.dirty and identity in self.widgets:
            buffer=self.widgets[identity].get_buffer();value=buffer.get_text(*buffer.get_bounds(),True)
            if self.send(self.nodes[identity]['action'],value):self.dirty.discard(identity)
        return False
    def build(self,node):
        k=node['type'];identity=node['id']
        if k in ('row','column'):w=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if k=='row' else Gtk.Orientation.VERTICAL,spacing=6)
        elif k=='grid':w=Gtk.Grid(column_homogeneous=True,row_homogeneous=True,column_spacing=4,row_spacing=4)
        elif k=='label':w=Gtk.Label(wrap=True);w.set_max_width_chars(34);w.set_justify(Gtk.Justification.CENTER)
        elif k in ('button','file'):
            w=Gtk.Button();w.connect('clicked',lambda *_:self.activate(identity))
        elif k=='text':
            w=Gtk.TextView();w.set_wrap_mode(Gtk.WrapMode.WORD_CHAR);w.set_size_request(-1,90)
            w.get_buffer().connect('changed',self.changed,identity);w.connect('focus-out-event',lambda *_:(self.flush(identity),False)[1])
        elif k=='clockface':
            from adws_clock_face import ClockFace
            w=ClockFace()
        elif k=='image':w=Picture()
        else:w=Gtk.ProgressBar()
        self.widgets[identity]=w
        w.get_style_context().add_class('basic-'+k)
        w.get_style_context().add_provider(self.card.layer.provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+10)
        if self.card.custom_provider:w.get_style_context().add_provider(self.card.custom_provider,Gtk.STYLE_PROVIDER_PRIORITY_USER+10)
        for i,child in enumerate(node.get('children',[])):
            c=self.build(child)
            if k=='grid':w.attach(c,i%node['columns'],i//node['columns'],1,1)
            elif k=='button':w.add(c)
            else:w.pack_start(c,k=='row' or child['type']=='clockface',True,0)
        return w
    def update(self,payload):
        if self.closed:return
        try:
            view=payload.get('view');shape=validate_view(view)
            keys=payload.get('key_actions',{})
            if not isinstance(keys,dict) or len(keys)>16 or any(not isinstance(k,str) or not isinstance(v,str) or not IDENT.fullmatch(v) for k,v in keys.items()):raise ValueError('Invalid keyboard actions')
        except (ValueError,TypeError):
            self.error.set_text(tr('组件界面数据无效，请检查插件。'));self.error.show();return
        self.keys=keys
        if not self.dirty:self.error.hide()
        if shape!=self.shape:
            for identity in list(self.dirty):self.flush(identity)
            for child in self.root.get_children():child.destroy()
            self.widgets={};self.nodes={};self.shape=shape
            self.root.pack_start(self.build(view),True,True,0);self.root.show_all()
        self.syncing=True
        def apply(n):
            identity=n['id'];w=self.widgets[identity];previous=self.nodes.get(identity,{})
            context=w.get_style_context()
            for cls in set(previous.get('classes',[]))-set(n.get('classes',[])):context.remove_class(cls)
            for cls in set(n.get('classes',[]))-set(previous.get('classes',[])):context.add_class(cls)
            self.nodes[identity]=n;k=n['type']
            if k=='label' and w.get_text()!=n.get('text',''):w.set_text(n.get('text',''))
            elif k in ('button','file'):
                if not n.get('children') and w.get_label()!=n.get('text',''):w.set_label(n.get('text',''))
                w.set_sensitive(n.get('enabled',True))
            elif k=='text' and identity not in self.dirty and not w.has_focus():
                buffer=w.get_buffer();value=n.get('value','')
                if buffer.get_text(*buffer.get_bounds(),True)!=value:buffer.set_text(value)
                w.set_tooltip_text(n.get('placeholder'))
            elif k=='progress':w.set_fraction(n['value'])
            elif k in ('image','clockface'):w.update(n)
            for child in n.get('children',[]):apply(child)
        try:apply(view)
        finally:self.syncing=False
        alert=payload.get('alert')
        if isinstance(alert,dict) and isinstance(alert.get('id'),str) and isinstance(alert.get('text'),str) and self.alert!=alert['id']:
            self.alert=alert['id'];notification=Gio.Notification.new(alert['text'][:256]);notification.set_body(self.card.title.get_text())
            app=self.card.layer.window.get_application()
            if app:app.send_notification('widget-'+self.card.row['instance'],notification)
            self.send('alert_seen',alert['id'])
    def stop(self):
        for widget in self.widgets.values():
            if hasattr(widget,'suspend'):widget.suspend()
        for identity in list(self.dirty):self.flush(identity)
        for source in self.sources.values():GLib.source_remove(source)
        self.sources.clear()
    def close(self):
        self.stop();self.closed=True

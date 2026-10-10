#!/usr/bin/env python3
"""Small layer-shell audio/brightness controls; all service work stays off GTK."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sys
import threading
from adws_i18n import tr, prepare_gtk_language
import adws_quick_backend as backend



def error_message(kind, error):
    """Explain known failures without claiming an unverified root cause."""
    raw=str(error).strip()
    text=raw.lower()
    if kind=='sound':
        if 'too many' in text or 'connection limit' in text:
            message='声音服务连接数已满，无法读取或调节音量。请关闭占用声音连接的应用后重试；ADWS 会自动检测恢复。'
        elif 'connection terminated' in text or 'connection reset' in text or 'broken pipe' in text:
            message='声音服务断开连接，暂时无法读取音量或调节声音。服务可能正在重启，或连接数已满；可尝试关闭 Waydroid 等使用声音的应用后重试。ADWS 会自动检测恢复。'
        elif 'connection refused' in text or 'connection failure' in text:
            message='无法连接声音服务，暂时无法读取或调节音量。请检查 PipeWire/PulseAudio 是否运行；ADWS 会自动重试。'
        elif 'timeout' in text or 'timed out' in text:
            message='声音状态读取超时，请稍后重试；ADWS 会继续检测声音服务。'
        else:message='声音操作失败，请检查声音服务后重试。'
    elif 'timeout' in text or 'timed out' in text:
        message='亮度设备响应超时，请检查显示器连接和 DDC/CI 设置后重试。'
    elif isinstance(error,PermissionError) or 'permission denied' in text:
        message='没有权限调节亮度，请检查背光设备或 DDC/CI 的访问权限。'
    else:message='亮度操作失败，请检查显示器连接及亮度控制支持后重试。'
    return tr(message)+(('\n'+tr('技术详情：%s')%raw) if raw else '')


def status(kind, output=None):
    if kind=='sound':
        data=backend.audio(); item=next((d for d in data['sinks'] if d.get('default')),None)
        level=round(item['volume']) if item else None
        icon='audio-volume-muted-symbolic' if not item or item.get('mute') else 'audio-volume-high-symbolic' if level>65 else 'audio-volume-medium-symbolic' if level>30 else 'audio-volume-low-symbolic'
    else:
        items=backend.brightness_targets(backend.brightness(),output)
        level=round(sum(item['value'] for item in items)/len(items)) if items else None
        icon='display-brightness-symbolic'
    result={'icon':icon,'text':f'{level}%' if level is not None else '—','available':level is not None}
    if level is None:result['error']=tr('未找到可用的默认声音输出，请连接或选择声音输出设备。' if kind=='sound' else '未找到可调节亮度的显示器；请检查背光、DDC/CI 或软件亮度服务。')
    if kind=='sound' and level is None:
        result['state']='no-device';result['icon']='audio-volume-muted-symbolic'
    return result


def run(kind, detailed, anchor=None, output=None):
    output = output or None
    import gi
    gi.require_version('Gtk','3.0')
    gi.require_version('Gdk','3.0')
    from gi.repository import Gdk, Gio, GLib, Gtk
    from adws_settings_widgets import compact_switch
    from adws_settings_style import PanelStyle
    prepare_gtk_language()
    # Single-instance, scoped to each control; wheel requests don't create windows.
    app=Gtk.Application(application_id='org.adws.Quick.'+kind,flags=Gio.ApplicationFlags.FLAGS_NONE)
    app.register(None)
    payload=json.dumps({'detailed':detailed,'anchor':anchor or {}})
    if app.get_is_remote():
        app.activate_action('open',GLib.Variant('s',payload)); return 0

    class Panel(Gtk.ApplicationWindow):
        def __init__(self):
            super().__init__(application=app)
            self.closed=False; self.pending={}; self.busy=False; self.timer=0; self.generation=0; self.edit_serial=0; self.read_future=None; self.poll_timer=0; self.updating=False; self.audio_refs=[]; self.identity=None
            self.pool=ThreadPoolExecutor(max_workers=1)
            self.read_pool=ThreadPoolExecutor(max_workers=1)
            self.set_title(tr('音量合成器' if kind=='sound' else '亮度与夜间模式'))
            self.set_decorated(False); self.set_resizable(False); self.set_skip_taskbar_hint(True)
            self.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
            self.get_style_context().add_class('adws-system-settings')
            self.get_style_context().add_class('adws-quick-panel')
            self.body=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=14,margin=18)
            self.add(self.body)
            self.set_default_size(350,-1)
            self.connect('key-press-event',lambda _,e:self.close() or True if e.keyval==Gdk.KEY_Escape else False)
            self.had_focus=False
            self.connect('focus-in-event',lambda *_:setattr(self,'had_focus',True) or False)
            self.connect('focus-out-event',lambda *_:(self.close() if self.had_focus else None) or False)
            self.connect('destroy',self.shutdown)
            if kind=='sound':self.poll_timer=GLib.timeout_add_seconds(3,self.poll_audio)
            import importlib.util
            spec=importlib.util.spec_from_file_location('adws_quick_config',os.path.join(os.path.dirname(__file__),'adws-config.py'))
            self.config=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.config;spec.loader.exec_module(self.config)
            self.style=PanelStyle(self)
            self.layer=None
            if isinstance(Gdk.Display.get_default(),Gdk.Display) and 'Wayland' in type(Gdk.Display.get_default()).__name__:
                gi.require_version('GtkLayerShell','0.1')
                from gi.repository import GtkLayerShell as layer
                if not layer.is_supported(): raise RuntimeError('Layer-shell is required for taskbar popups')
                self.layer=layer; layer.init_for_window(self);layer.set_layer(self,layer.Layer.OVERLAY)
                layer.set_namespace(self,'waybar')  # inherit compositor material/blur rules
                layer.set_keyboard_mode(self,layer.KeyboardMode.ON_DEMAND)
                layer.auto_exclusive_zone_enable(self);layer.set_exclusive_zone(self,0)

        def shutdown(self,*_):
            self.closed=True;self.generation+=1
            if self.timer:GLib.source_remove(self.timer);self.timer=0
            if self.poll_timer:GLib.source_remove(self.poll_timer);self.poll_timer=0
            # Preserve the final slider edit if the user dismisses immediately.
            remaining=list(self.pending.values());self.pending.clear()
            if remaining:self.pool.submit(lambda:[fn() for fn in remaining])
            self.pool.shutdown(wait=False,cancel_futures=False)
            self.read_pool.shutdown(wait=False,cancel_futures=True);self.style.close()

        def position(self,where):
            display=self.get_display();monitor=None
            for i in range(display.get_n_monitors()):
                candidate=display.get_monitor(i)
                if i==where.get('monitor') or candidate.get_model()==where.get('monitor'):monitor=candidate;break
            if monitor is None:
                pointer=display.get_default_seat().get_pointer(); _,px,py=pointer.get_position()
                monitor=display.get_monitor_at_point(px,py)
            rect=monitor.get_geometry();edge=where.get('edge','bottom')
            x=max(0,min(rect.width-350,int(where.get('x',rect.width//2))-175))
            if self.layer:
                l=self.layer;l.set_monitor(self,monitor)
                for e in (l.Edge.TOP,l.Edge.BOTTOM,l.Edge.LEFT,l.Edge.RIGHT):l.set_anchor(self,e,False)
                if edge in ('top','bottom'):
                    e=l.Edge.TOP if edge=='top' else l.Edge.BOTTOM
                    l.set_anchor(self,e,True);l.set_margin(self,e,max(0,int(where.get('inset',48))))
                    l.set_anchor(self,l.Edge.LEFT,True);l.set_margin(self,l.Edge.LEFT,x)
                else:
                    e=l.Edge.LEFT if edge=='left' else l.Edge.RIGHT
                    l.set_anchor(self,e,True);l.set_margin(self,e,max(0,int(where.get('inset',48))))
                    l.set_anchor(self,l.Edge.TOP,True);l.set_margin(self,l.Edge.TOP,max(0,min(rect.height-400,int(where.get('y',rect.height//2))-180)))
            else:self.move(rect.x+x,rect.y+max(0,rect.height-450) if edge=='bottom' else rect.y+48)

        def open(self,options):
            self.detailed=options.get('detailed',False);self.generation+=1
            self.position(options.get('anchor',{}));self.load()
            self.show_all();self.present()

        def worker(self,function,done,read=False):
            future=(self.read_pool if read else self.pool).submit(function)
            def complete(f):
                try:value=f.result();error=None
                except Exception as e:value=None;error=error_message(kind,e)
                if not self.closed:GLib.idle_add(done,value,error)
            future.add_done_callback(complete)
            return future

        def load(self,*_):
            self.generation+=1
            generation=self.generation
            edit_serial=self.edit_serial
            for child in self.body.get_children():child.destroy()
            cached=backend.cached_brightness() if kind=='brightness' else None
            if cached:self.brightness(cached)
            else:self.body.pack_start(Gtk.Label(label=tr('正在读取系统状态…'),xalign=0),False,False,0)
            self.body.show_all()
            def complete(data,error):
                if self.closed or generation!=self.generation:return False
                if cached:
                    # Never replace a slider while dragging or overwrite an edit
                    # queued after the hardware refresh began.
                    def grabbed(widget):
                        return (isinstance(widget,Gtk.Scale) and widget.has_grab()) or (isinstance(widget,Gtk.Container) and any(grabbed(c) for c in widget.get_children()))
                    if self.edit_serial!=edit_serial or self.pending or self.busy or grabbed(self.body):return False
                    if error:self.error.set_text(error);return False
                for child in self.body.get_children():child.destroy()
                if error:self.body.pack_start(Gtk.Label(label=error,wrap=True),False,False,0)
                elif kind=='sound':self.sound(data)
                else:self.brightness(data)
                self.body.show_all();return False
            if self.read_future:self.read_future.cancel()
            self.read_future=self.worker(lambda: backend.audio(self.detailed) if kind=='sound' else backend.brightness(force=bool(_)),complete,read=True)

        def queue(self,key,function):
            if self.closed or self.updating:return
            self.edit_serial+=1
            self.pending[key]=function
            if not self.timer:self.timer=GLib.timeout_add(120,self.flush)

        def flush(self):
            self.timer=0
            if self.closed or not self.pending:return False
            if self.busy:self.timer=GLib.timeout_add(120,self.flush);return False
            self.busy=True;values=list(self.pending.values());self.pending.clear()
            def done(_,error):
                self.busy=False
                if self.closed:return False
                if error:self.error.set_text(error)
                if self.pending and not self.timer:self.timer=GLib.timeout_add(120,self.flush)
                return False
            self.worker(lambda:[fn() for fn in values],done);return False

        def header(self,title):
            line=Gtk.Box(spacing=12);label=Gtk.Label(label=tr(title),xalign=0)
            label.get_style_context().add_class('settings-section-title');line.pack_start(label,True,True,0)
            refresh=Gtk.Button.new_from_icon_name('view-refresh-symbolic',Gtk.IconSize.BUTTON)
            refresh.set_tooltip_text(tr('刷新状态'));refresh.connect('clicked',self.load);line.pack_end(refresh,False,False,0)
            close=Gtk.Button.new_from_icon_name('window-close-symbolic',Gtk.IconSize.BUTTON)
            close.set_tooltip_text(tr('关闭'));close.connect('clicked',lambda *_:self.close());line.pack_end(close,False,False,0)
            self.body.pack_start(line,False,False,0)
            self.error=Gtk.Label(label='',xalign=0,wrap=True);self.error.get_style_context().add_class('error')
            self.body.pack_end(self.error,False,False,0)

        def scale(self,parent,title,value,callback,vertical=False,low=0,high=100):
            label=Gtk.Label(label=title,xalign=0,wrap=True,max_width_chars=18 if vertical else 42);parent.pack_start(label,False,False,0)
            control=Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,low,high,1 if high==100 else 100)
            control.set_digits(0);control.set_value(value);control.set_hexpand(not vertical)
            if vertical:control.set_inverted(True);control.set_size_request(60,150);control.set_value_pos(Gtk.PositionType.BOTTOM)
            control.connect('notify::sensitive',lambda c,_:label.set_sensitive(c.get_sensitive()))
            control.connect('value-changed',lambda c:callback(c.get_value()))
            parent.pack_start(control,False,False,0);return control

        def sound(self,data):
            self.audio_refs=[];self.identity=self.audio_identity(data)
            self.header('音量合成器' if self.detailed else '音量')
            devices=data.get('sinks',[]);default=next((d for d in devices if d.get('default')),None)
            if not default:self.body.pack_start(Gtk.Label(label=tr('无可用配置')),False,False,0);return
            if len(devices)>1:
                from adws_sound_settings import device_choice
                selected=device_choice([{'name':str(d['index']),'description':d['description']} for d in devices],str(default['index']))
                def select(control):
                    item=next((d for d in devices if str(d['index'])==control.get_active_id()),None)
                    if item:
                        def change():
                            backend.audio_write('sink',item['index'],'default',item['name'])
                            if not self.closed:GLib.idle_add(self.load)
                        self.queue(('default',0),change)
                selected.connect('changed',select);self.body.pack_start(selected,False,False,0)
            if not self.detailed:
                self.audio_column(self.body,default,'sink',False);return
            scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.NEVER)
            scroll.set_min_content_width(350);scroll.set_max_content_width(650);scroll.set_propagate_natural_width(True)
            line=Gtk.Box(spacing=18);scroll.add(line);self.body.pack_start(scroll,False,False,0)
            for item in [default,*data.get('apps',[])]:
                column=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=9);column.set_size_request(112,-1)
                line.pack_start(column,False,False,0);self.audio_column(column,item,'sink' if item is default else 'sink-input',True)
            if not data.get('apps'):self.body.pack_start(Gtk.Label(label=tr('当前没有正在播放或录音的应用。'),wrap=True),False,False,0)

        def audio_column(self,parent,item,device_kind,vertical):
            props=item.get('properties',{});title=item.get('description') or props.get('application.name') or props.get('media.name') or str(item['index'])
            index=item['index']
            scale=self.scale(parent,title,min(100,item['volume']),lambda v:self.queue((device_kind,index,'volume'),lambda:backend.audio_write(device_kind,index,'volume',v)),vertical)
            line=Gtk.Box(spacing=8);line.pack_start(Gtk.Label(label=tr('静音')),True,True,0)
            mute=compact_switch(Gtk.Switch(active=item.get('mute',False)));line.pack_end(mute,False,False,0)
            mute.connect('notify::active',lambda c,_:self.queue((device_kind,index,'mute'),lambda v=c.get_active():backend.audio_write(device_kind,index,'mute',v)))
            parent.pack_start(line,False,False,0)
            self.audio_refs.append((device_kind,index,scale,mute))

        def audio_identity(self,data):
            return (tuple((d['index'],d.get('default',False)) for d in data.get('sinks',[])),tuple(d['index'] for d in data.get('apps',[])))

        def poll_audio(self):
            if self.closed:return False
            if self.busy or self.pending or (self.read_future and not self.read_future.done()):return True
            generation=self.generation
            def done(data,error):
                if self.closed or generation!=self.generation:return False
                if error:return False  # Keep last valid controls on a transient service outage.
                if self.identity!=self.audio_identity(data):
                    for child in self.body.get_children():child.destroy()
                    self.sound(data);self.body.show_all();return False
                self.updating=True
                try:
                    lookup={('sink',d['index']):d for d in data.get('sinks',[])}
                    lookup.update({('sink-input',d['index']):d for d in data.get('apps',[])})
                    for device_kind,index,scale,mute in self.audio_refs:
                        item=lookup.get((device_kind,index))
                        if item and not scale.has_grab():
                            scale.set_value(min(100,item['volume']));mute.set_active(item.get('mute',False))
                finally:self.updating=False
                return False
            self.read_future=self.worker(lambda:backend.audio(self.detailed),done,read=True)
            return True

        def brightness(self,items):
            self.header('亮度与夜间模式' if self.detailed else '亮度')
            if not items:self.body.pack_start(Gtk.Label(label=tr('无可用配置')),False,False,0);return
            if not self.detailed:
                targets=backend.brightness_targets(items,output)
                level=sum(item['value'] for item in targets)/len(targets) if targets else 100
                slider=self.scale(self.body,tr('所有可调显示器') if not output else output,level,
                                  lambda v:self.queue(('all','brightness'),lambda:backend.brightness_all(targets,v)),low=5)
                slider.set_sensitive(bool(targets))
                if not targets:self.body.pack_start(Gtk.Label(label=tr('无可用配置'),xalign=0),False,False,0)
                return
            scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC);scroll.set_max_content_height(600);scroll.set_propagate_natural_height(True)
            content=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=18);scroll.add(content);self.body.pack_start(scroll,True,True,0)
            for index,item in enumerate(items):
                if index:
                    divider=Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
                    content.pack_start(divider,False,False,0)
                panel=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8);content.pack_start(panel,False,False,0)
                name=item['name'];title=item['description']+' · '+name
                slider=self.scale(panel,title,item.get('value') or 100,lambda v,i=item:self.queue((i['name'],'brightness'),lambda:backend.brightness_write(i,'brightness',v)),low=5)
                slider.set_sensitive(bool(item.get('provider')))
                if not item.get('provider'):
                    unavailable=Gtk.Label(label=tr('无可用配置'),xalign=0);unavailable.set_sensitive(False)
                    panel.pack_start(unavailable,False,False,0)
                if not self.detailed:continue
                temp=self.scale(panel,tr('色温')+' (K)',item['temperature'],lambda v,i=item:self.queue((i['name'],'temperature'),lambda:backend.brightness_write(i,'temperature',v)),low=1000,high=10000)
                temp.set_sensitive(bool(item.get('color_provider')))
                row=Gtk.Box(spacing=12)
                night_label=Gtk.Label(label=tr('夜间模式'),xalign=0);night_label.set_sensitive(bool(item.get('color_provider')))
                row.pack_start(night_label,True,True,0)
                night=compact_switch(Gtk.Switch(active=item['night']));night.set_sensitive(bool(item.get('color_provider')))
                night.connect('notify::active',lambda c,_,i=item:self.queue((i['name'],'temperature'),lambda v=c.get_active():backend.brightness_write(i,'night',v)))
                row.pack_end(night,False,False,0);panel.pack_start(row,False,False,0)
                if not item.get('color_provider'):
                    unavailable=Gtk.Label(label=tr('需要 wl-gammarelay-rs 或 wlsunset 才能调节色温。'),xalign=0,wrap=True);unavailable.set_sensitive(False)
                    panel.pack_start(unavailable,False,False,0)

    panel=Panel()
    action=Gio.SimpleAction.new('open',GLib.VariantType.new('s'))
    action.connect('activate',lambda _,p:panel.open(json.loads(p.get_string())))
    app.add_action(action);app.connect('activate',lambda *_:panel.open(json.loads(payload)))
    return app.run([sys.argv[0]])


def main():
    parser=argparse.ArgumentParser();parser.add_argument('kind',choices=('sound','brightness'))
    parser.add_argument('--status',action='store_true');parser.add_argument('--panel',action='store_true');parser.add_argument('--step',type=float)
    parser.add_argument('--output');parser.add_argument('--anchor')
    parser.add_argument('--brightness-worker-fd',type=int,help=argparse.SUPPRESS)
    args=parser.parse_args()
    try:
        if args.brightness_worker_fd is not None:
            if args.kind!='brightness':raise ValueError('Invalid brightness worker')
            backend.brightness_step_worker(args.brightness_worker_fd);return 0
        if args.status:print(json.dumps(status(args.kind,args.output)));return 0
        if args.step is not None:backend.step(args.kind,args.step,args.output);return 0
        return run(args.kind,args.panel,json.loads(args.anchor) if args.anchor else None,args.output)
    except Exception as error:
        if args.status:print(json.dumps({'icon':'audio-volume-high-symbolic' if args.kind=='sound' else 'display-brightness-symbolic',
                                        'text':'—','available':False,'error':error_message(args.kind,error)}))
        else:print(str(error),file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())

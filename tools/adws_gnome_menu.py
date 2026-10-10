"""ADWS calendar and combined quick-settings popup for its GNOME-style preset."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess,sys
from adws_i18n import tr,prepare_gtk_language
import adws_quick_backend as backend
import adws_system_pages as services

ROOT=Path(__file__).resolve().parents[1]


def popup(kind='system',preview=False):
    import gi
    gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0')
    from gi.repository import Gtk,Gdk,Gio,GLib
    prepare_gtk_language()
    app=Gtk.Application(application_id='org.akiacg.ADWS.Gnome.'+kind,flags=Gio.ApplicationFlags.FLAGS_NONE)
    def activate(app):
        if app.get_windows():app.get_windows()[0].destroy();return
        window=Gtk.ApplicationWindow(application=app);window.set_decorated(False);window.set_resizable(False);window.set_title(tr('日历' if kind=='calendar' else '快捷设置'));window.get_style_context().add_class('adws-gnome-menu')
        css=Gtk.CssProvider();css.load_from_data(b'''
.adws-gnome-menu { background: #303030; color: #f6f5f4; border-radius: 24px; border: 1px solid #454545; font-family: Cantarell, "Noto Sans CJK SC", sans-serif; font-size: 14px; }
.adws-gnome-menu button { background: #454545; color: #f6f5f4; border: none; border-radius: 24px; padding: 10px 14px; box-shadow: none; }
.adws-gnome-menu button:hover { background: #555555; }
.adws-gnome-menu button:checked { background: #3584e4; color: white; }
.adws-gnome-menu button:disabled { opacity: .45; }
.adws-gnome-menu scale trough { min-height: 5px; background: #555555; border-radius: 8px; }
.adws-gnome-menu scale highlight { background: #f6f5f4; border-radius: 8px; }
.adws-gnome-menu scale slider { background: #f6f5f4; min-width: 14px; min-height: 14px; border-radius: 50%; }
.adws-gnome-menu calendar { color: #f6f5f4; }
.adws-gnome-menu calendar:selected { background: #3584e4; color: white; }
''');Gtk.StyleContext.add_provider_for_screen(window.get_screen(),css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+20)
        try:
            gi.require_version('GtkLayerShell','0.1');from gi.repository import GtkLayerShell as layer
            if layer.is_supported():
                layer.init_for_window(window);layer.set_namespace(window,'waybar');layer.set_layer(window,layer.Layer.OVERLAY);layer.set_keyboard_mode(window,layer.KeyboardMode.ON_DEMAND);layer.set_exclusive_zone(window,-1)
                display=window.get_display();_,x,y=display.get_default_seat().get_pointer().get_position();monitor=display.get_monitor_at_point(x,y);layer.set_monitor(window,monitor)
                layer.set_anchor(window,layer.Edge.TOP,True)
                inset=32
                if preview:inset+=48+max(0,monitor.get_workarea().y-monitor.get_geometry().y)
                layer.set_margin(window,layer.Edge.TOP,inset+8)
                if kind=='system':layer.set_anchor(window,layer.Edge.RIGHT,True);layer.set_margin(window,layer.Edge.RIGHT,12)
        except (ImportError,ValueError):pass
        body=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=16,margin=20);window.add(body);window.set_default_size(380,-1)
        reads=ThreadPoolExecutor(max_workers=2);writes=ThreadPoolExecutor(max_workers=1)
        state={'focused':False,'closed':False,'busy':False,'pending':{},'timer':0}
        def work(fn,done):
            def ready(f):
                def deliver():
                    if state['closed']:return False
                    try:done(f.result())
                    except Exception as error:status.set_text(str(error))
                    return False
                GLib.idle_add(deliver)
            reads.submit(fn).add_done_callback(ready)
        def flush():
            if state['closed']:return False
            if state['busy'] or not state['pending']:return True
            jobs=list(state['pending'].values());state['pending'].clear();state['busy']=True
            def send():
                errors=[]
                for job in jobs:
                    try:job()
                    except Exception as error:errors.append(str(error))
                return errors
            def ready(f):
                errors=f.result()
                def deliver():
                    state['busy']=False
                    if not state['closed'] and errors:status.set_text('\n'.join(errors))
                    return False
                GLib.idle_add(deliver)
            writes.submit(send).add_done_callback(ready);return True
        def queue(key,fn):state['pending'][key]=fn
        def launch(name,*args):
            subprocess.Popen([sys.executable,str(ROOT/'tools'/name),*args],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True);window.destroy()
        def settings(tab=None):launch('adws-config.py',*(['--tab',tab] if tab else []))
        status=Gtk.Label(xalign=0,wrap=True);status.set_max_width_chars(40)
        if kind=='calendar':
            import datetime
            body.pack_start(Gtk.Label(label=datetime.datetime.now().strftime('%A, %B %d'),xalign=0),False,False,0)
            body.pack_start(Gtk.Calendar(),False,False,0)
            button=Gtk.Button(label=tr('日期与时间设置'));button.connect('clicked',lambda *_:settings('region'));body.pack_start(button,False,False,0)
        else:
            header=Gtk.Box(spacing=8);battery=Gtk.Label(label='',xalign=0);header.pack_start(battery,True,True,0)
            def icon_button(icon,tip,fn):
                button=Gtk.Button.new_from_icon_name(icon,Gtk.IconSize.BUTTON);button.set_tooltip_text(tr(tip));button.connect('clicked',lambda *_:fn());header.pack_start(button,False,False,0)
            icon_button('preferences-system-symbolic','设置',settings)
            icon_button('system-lock-screen-symbolic','锁屏',lambda:launch('adws_topbar_controls.py','lock'))
            icon_button('system-shutdown-symbolic','电源与会话',lambda:settings('power'))
            body.pack_start(header,False,False,0)
            def slider(icon,title):
                line=Gtk.Box(spacing=12);line.pack_start(Gtk.Image.new_from_icon_name(icon,Gtk.IconSize.BUTTON),False,False,0)
                scale=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,100,1);scale.set_draw_value(False);scale.set_sensitive(False);scale.set_tooltip_text(tr(title));line.pack_start(scale,True,True,0);body.pack_start(line,False,False,0);return scale
            volume=slider('audio-volume-high-symbolic','音量');brightness=slider('display-brightness-symbolic','亮度')
            grid=Gtk.Grid(column_spacing=10,row_spacing=10,column_homogeneous=True);body.pack_start(grid,False,False,0)
            wifi=Gtk.ToggleButton(label='Wi-Fi');bluetooth=Gtk.ToggleButton(label=tr('蓝牙'));night=Gtk.ToggleButton(label=tr('夜间模式'));power=Gtk.Button(label=tr('电源模式'))
            for n,button in enumerate((wifi,bluetooth,night,power)):
                button.set_sensitive(button is power);grid.attach(button,n%2,n//2,1,1)
            power.connect('clicked',lambda *_:settings('power'))
            def audio(data):
                item=next((d for d in data.get('sinks',[]) if d.get('default')),None)
                if not item:return
                volume.set_value(min(100,item['volume']));volume.set_sensitive(True)
                volume.connect('value-changed',lambda w:queue('volume',lambda value=w.get_value():backend.audio_write('sink',item['index'],'volume',value)))
            def screens(items):
                item=next((i for i in items if i.get('provider')),None)
                if item:
                    brightness.set_range(5,100);brightness.set_value(item.get('value') or 100);brightness.set_sensitive(True)
                    brightness.connect('value-changed',lambda w:queue('brightness',lambda value=w.get_value():backend.brightness_write(item,'brightness',value)))
                adjustable=[i for i in items if i.get('color_provider')]
                if adjustable:
                    night.set_active(any(i.get('night') for i in adjustable));night.set_sensitive(True)
                    night.connect('toggled',lambda w:queue('night',lambda value=w.get_active():[backend.brightness_write(i,'night',value) for i in adjustable]))
            def network(data):
                if 'wifi' not in data:return
                wifi.set_active(data['wifi']);wifi.set_sensitive(True);wifi.connect('toggled',lambda w:queue('wifi',lambda value=w.get_active():services.wifi_enabled(value)))
            def bt(data):
                if not data.get('adapter'):return
                bluetooth.set_active(data['powered']);bluetooth.set_sensitive(True);bluetooth.connect('toggled',lambda w:queue('bluetooth',lambda value=w.get_active():services.bluetooth_power(value)))
            work(backend.audio,audio);work(backend.brightness,screens);work(services.network_snapshot,network);work(services.bluetooth_snapshot,bt)
            work(services.batteries,lambda items:battery.set_text(' · '.join(str(i.get('capacity',''))+'%' for i in items)))
            footer=Gtk.Box(spacing=8)
            for title,action in [('挂起','suspend'),('注销','logout'),('重启','reboot'),('关机','poweroff')]:
                button=Gtk.Button(label=tr(title));button.connect('clicked',lambda _,action=action:launch('adws_topbar_controls.py',action));footer.pack_start(button,True,True,0)
            body.pack_start(footer,False,False,0)
        body.pack_start(status,False,False,0)
        state['timer']=GLib.timeout_add(120,flush)
        def close(*_):
            state['closed']=True;GLib.source_remove(state['timer'])
            for job in state['pending'].values():writes.submit(job)
            reads.shutdown(wait=False,cancel_futures=True);writes.shutdown(wait=False,cancel_futures=False)
            Gtk.StyleContext.remove_provider_for_screen(window.get_screen(),css)
        window.connect('destroy',close)
        window.connect('focus-in-event',lambda *_:(state.update(focused=True) or False))
        # Layer-shell can send a transient focus-out while mapping the popup.
        def focus_out(*_):
            def dismiss():
                if not state['closed'] and state['focused'] and not window.is_active():window.destroy()
                return False
            GLib.timeout_add(180,dismiss);return False
        window.connect('focus-out-event',focus_out)
        window.connect('key-press-event',lambda _,e:(window.destroy() or True) if e.keyval==Gdk.KEY_Escape else False)
        window.show_all();window.present()
    app.connect('activate',activate);return app.run([])

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('kind',choices=('calendar','system'),nargs='?',default='system');parser.add_argument('--preview',action='store_true');args=parser.parse_args()
    raise SystemExit(popup(args.kind,args.preview))

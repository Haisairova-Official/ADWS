#!/usr/bin/env python3
"""Draw all four clock faces and exercise animation resource lifetime."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import gi
gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0')
from gi.repository import Gtk,Gdk,GLib
from adws_clock_face import ClockFace,FACES

window=Gtk.Window(title='ADWS clock faces');window.set_default_size(1000,280)
row=Gtk.Box(spacing=16);row.set_border_width(16);window.add(row)
provider=Gtk.CssProvider();provider.load_from_data(b'window {background:#252630;color:#eceaf5;} label {color:#eceaf5;}')
Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
clocks=[]
for face,title in zip(FACES,('复古 · 机械跳秒','简洁 · 平滑扫秒','车站 · 节拍秒针','星环 · 平滑扫秒')):
    box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8);row.pack_start(box,True,True,0)
    clock=ClockFace();clock.update(dict(face=face,seconds=True,utc_offset=28800));box.pack_start(clock,True,True,0)
    box.pack_start(Gtk.Label(label=title),False,False,0);clocks.append(clock)
window.show_all()
failures=[]
def check():
    try:
        assert all(w.tick_id for w in clocks)
        for w in clocks:
            assert w.cached is not None
            w.update(dict(w.node,seconds=False));assert not w.tick_id and w.timer_id
        # Custom images preserve transparent pixels; the generated dial backing
        # is entirely absent when using a transparent PNG with markings disabled.
        import cairo
        with tempfile.NamedTemporaryFile(suffix='.png',delete=False) as f:custom=Path(f.name)
        image=cairo.ImageSurface(cairo.FORMAT_ARGB32,64,64);cr=cairo.Context(image)
        cr.set_source_rgba(.8,.2,.5,1);cr.rectangle(22,22,20,20);cr.fill();image.write_to_png(str(custom))
        import json
        from adws_plugin_settings import SettingsDialog
        schema=json.loads((Path(__file__).resolve().parents[1]/'plugins/desktop-basic-pack/plugin.json').read_text())['components'][0]['settingsSchema']
        settings=SettingsDialog(window,'Clock',schema,{'display':'analog','face_image':str(custom)})
        settings.dialog.show_all();settings.update_visibility()
        adapter=settings.controls['face'][1]._adws_choice_button
        assert adapter.get_visible() and not settings.controls['face'][1].get_visible()
        assert settings.collect()['face_image']==str(custom)
        settings.controls['face_image'][1].set_text('/missing/clock-image.png')
        try:settings.collect()
        except ValueError:pass
        else:raise AssertionError('Missing image accepted')
        settings.dialog.destroy()
        clock=clocks[0];clock.update(dict(clock.node,path=str(custom),markers=False))
        deadline=__import__('time').monotonic()+3
        while clock.picture.pixbuf is None and __import__('time').monotonic()<deadline:
            while Gtk.events_pending():Gtk.main_iteration()
            __import__('time').sleep(.01)
        assert clock.picture.pixbuf is not None
        target=cairo.ImageSurface(cairo.FORMAT_ARGB32,160,160);clock.dial(cairo.Context(target),160,clock.colors());target.flush()
        assert bytes(target.get_data())[20*target.get_stride()+80*4+3]==0
        assert bytes(target.get_data())[80*target.get_stride()+80*4+3]>0
        clock.update(dict(clock.node,path='',markers=True));assert clock.picture.pixbuf is None
        custom.unlink()
        window.hide();assert all(not w.tick_id and not w.timer_id for w in clocks)
        window.show_all()
        for w in clocks:
            assert w.timer_id
            w.update(dict(w.node,seconds=True));assert w.tick_id and not w.timer_id
            w.suspend();assert not w.tick_id and not w.timer_id
            w.update(w.node);assert w.tick_id
    except Exception as exc:failures.append(exc)
    GLib.timeout_add(150,finish);return False
def finish():
    try:
        surface=window.get_window();pixbuf=Gdk.pixbuf_get_from_window(surface,0,0,*window.get_size())
        pixbuf.savev('/tmp/adws-clock-faces.png','png',[],[])
        window.destroy();assert all(not w.tick_id and not w.timer_id for w in clocks)
    except Exception as exc:failures.append(exc)
    Gtk.main_quit();return False
GLib.timeout_add(350,check);Gtk.main()
if failures:raise failures[0]
print('PASS: four clock faces drawn; seconds toggle, unmap, suspend, resume and destroy release callbacks.')

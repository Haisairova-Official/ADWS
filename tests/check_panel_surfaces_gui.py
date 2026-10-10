"""Isolated GTK rendering of materials, split geometry and saved radius."""
from pathlib import Path
import sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk
import cairo
from adws_panel_options import styles
root=Path(__file__).resolve().parents[1]
Gtk.init([])
for material in ('solid','mica','acrylic','candy'):
    window=Gtk.Window();window.set_name('waybar');window.set_default_size(720,64)
    context=window.get_style_context();context.add_class('adws-panel');context.add_class('adws-split')
    box=Gtk.Box(spacing=0);window.add(box)
    left=Gtk.Box(spacing=8);left.get_style_context().add_class('modules-left')
    left.add(Gtk.Label(label=' Start    App 1    App 2 '));box.pack_start(left,False,False,0)
    center=Gtk.Box();center.get_style_context().add_class('modules-center');box.set_center_widget(center)
    right=Gtk.Box();right.get_style_context().add_class('modules-right');right.add(Gtk.Label(label=' 12:30 '));box.pack_end(right,False,False,0)
    css=Gtk.CssProvider()
    css.load_from_data(('@define-color surface_container_high #303849; @define-color primary #6dc5e6; @define-color on_surface #e9eaff; window#waybar {background:transparent;} label {color:@on_surface;padding:10px;} '+styles({'split_panel':True,'panel_material':material,'_occupied_slots':['left','right'],'_surface_radius':'19px'})).encode())
    Gtk.StyleContext.add_provider_for_screen(window.get_screen(),css,800)
    window.show_all()
    for _ in range(40):
        while Gtk.events_pending():Gtk.main_iteration()
        time.sleep(.005)
    assert center.get_allocated_width()<=1
    assert left.get_allocated_width()+right.get_allocated_width()<window.get_allocated_width()
    assert box.get_style_context().get_background_color(Gtk.StateFlags.NORMAL).alpha == 0
    surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,window.get_allocated_width(),window.get_allocated_height())
    window.draw(cairo.Context(surface));surface.write_to_png('/tmp/adws-b-material-'+material+'.png')
    window.destroy();Gtk.StyleContext.remove_provider_for_screen(window.get_screen(),css)
print('Four materials rendered; empty center remains transparent; segments request content width.')

for edge in ('top', 'bottom', 'left', 'right'):
    for corners in ('same', 'pointed'):
        window=Gtk.Window(); window.set_name('waybar')
        window.get_style_context().add_class('adws-panel')
        window.get_style_context().add_class('adws-split')
        outer=Gtk.Box(); window.add(outer)
        center=Gtk.Box(); center.get_style_context().add_class('modules-center')
        center.add(Gtk.Label(label='Lyrics'))
        outer.pack_start(center,False,False,0)
        css=Gtk.CssProvider()
        css.load_from_data(('@define-color surface_container_high #303849; @define-color primary #6dc5e6; @define-color on_surface #e9eaff; '+styles({'split_panel':True,'position':edge,'split_center_corners':corners,'_occupied_slots':['center']})).encode())
        Gtk.StyleContext.add_provider_for_screen(window.get_screen(),css,800)
        window.show_all()
        while Gtk.events_pending(): Gtk.main_iteration()
        padding=center.get_style_context().get_padding(Gtk.StateFlags.NORMAL)
        inset=23 if corners=='pointed' else 5
        assert (padding.top,padding.right,padding.bottom,padding.left)==((inset,0,inset,0) if edge in ('left','right') else (0,inset,0,inset))
        window.destroy();Gtk.StyleContext.remove_provider_for_screen(window.get_screen(),css)
print('Center 5px axial padding and both corner variants parsed on all four edges.')

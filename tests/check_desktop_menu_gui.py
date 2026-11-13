"""Real GTK popup transparency and destructive-action transition, isolated config."""
import os
import sys
import tempfile
import time
from pathlib import Path
import cairo
import gi
gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0')
from gi.repository import Gtk,Gdk
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'src/niri-desktop-layer')]
from desktop_layer.app import apply_menu_palette, menu_item_with_icon
from desktop_layer.config import Config

def settle(seconds=.05):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        while Gtk.events_pending():Gtk.main_iteration()
        time.sleep(.002)

def pixel(widget,x,y):
    surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,120,80)
    Gtk.render_background(widget.get_style_context(),cairo.Context(surface),0,0,120,80)
    surface.flush()
    return tuple(surface.get_data()[y*surface.get_stride()+x*4:y*surface.get_stride()+x*4+4])

with tempfile.TemporaryDirectory() as folder:
    os.environ['XDG_CONFIG_HOME']=folder
    config=Path(folder)/'adws';config.mkdir()
    (config/'taskbar-layout.json').write_text('{"options":{"window_animations":true,"animation_duration":400}}')
    base=Gtk.CssProvider();base.load_from_data(b'* {border-radius:0;} window {background:#282934;}')
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),base,Gtk.STYLE_PROVIDER_PRIORITY_USER+1)
    Gtk.Settings.get_default().set_property('gtk-enable-animations',True)
    window=Gtk.Window();window.show_all()
    menu=Gtk.Menu();normal=menu_item_with_icon('Open','document-open-symbolic');danger=Gtk.MenuItem(label='Exit desktop environment')
    danger.get_style_context().add_class('desktop-exit');menu.append(normal);menu.append(danger)
    apply_menu_palette(menu,Config());menu.show_all()
    rect=Gdk.Rectangle();rect.x=20;rect.y=20;rect.width=1;rect.height=1
    menu.popup_at_rect(window.get_window(),rect,Gdk.Gravity.SOUTH_WEST,Gdk.Gravity.NORTH_WEST,None)
    settle()
    top=menu.get_toplevel()
    assert menu.get_style_context().has_class('adws-context-menu')
    assert top.get_style_context().has_class('adws-context-popup')
    assert danger.get_style_context().has_class('adws-destructive')
    image,label=normal.get_child().get_children()
    assert image.get_icon_name()==('document-open-symbolic',Gtk.IconSize.MENU)
    assert normal.get_child().get_spacing()==8 and label.get_text()=='Open'
    assert top.get_visual().get_depth()==32
    assert top.get_style_context().get_property('background-color',Gtk.StateFlags.NORMAL).alpha==0
    assert pixel(menu,0,0)[3]==0 and pixel(menu,60,40)[3]>240
    menu.select_item(normal);settle(.45)
    start=pixel(danger,60,40)
    menu.select_item(danger);settle(.10);middle=pixel(danger,60,40)
    settle(.45);end=pixel(danger,60,40)
    assert start[3]==0,(start,middle,end)
    assert 0<middle[3]<end[3],(start,middle,end)
    assert end==(40,40,198,255),end
    # Palette reloading retains corner transparency and does not accumulate hooks.
    apply_menu_palette(menu,Config());assert pixel(menu,0,0)[3]==0
    menu.popdown();menu.destroy();window.destroy()
print('PASS: transparent popup shell, rounded menu, red hover transition and theme reload')

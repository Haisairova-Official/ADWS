"""GNOME preset popups with fake services; no system changes are performed."""
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
import adws_gnome_menu as menu
import cairo
for kind in ('system','calendar'):
 seen=[]
 def check():
  app=Gtk.Application.get_default()
  if not app or not app.get_windows():
   print('waiting for popup',app,flush=True);return True
  w=app.get_windows()[0];widgets=[]
  def walk(widget):
   widgets.append(widget)
   if isinstance(widget,Gtk.Container):
    for child in widget.get_children():walk(child)
  walk(w)
  if kind=='system':
   scales=[v for v in widgets if isinstance(v,Gtk.Scale)]
   assert len(scales)==2
   if not all(v.get_sensitive() for v in scales):
    print('waiting for services',[v.get_sensitive() for v in scales],[v.get_text() for v in widgets if isinstance(v,Gtk.Label)],flush=True);return True
   assert len([v for v in widgets if isinstance(v,Gtk.ToggleButton)])==3
  else:assert any(isinstance(v,Gtk.Calendar) for v in widgets)
  surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,w.get_allocated_width(),w.get_allocated_height());w.draw(cairo.Context(surface));surface.write_to_png('/tmp/adws-gnome-'+kind+'.png')
  seen.append(True);w.destroy();return False
 with patch.object(menu.backend,'audio',return_value={'sinks':[{'default':True,'volume':50,'index':1}]}),patch.object(menu.backend,'brightness',return_value=[{'name':'screen','value':70,'provider':'ddc','color_provider':True,'night':False}]),patch.object(menu.services,'network_snapshot',return_value={'wifi':True}),patch.object(menu.services,'bluetooth_snapshot',return_value={'adapter':'Bluetooth','powered':False}),patch.object(menu.services,'batteries',return_value=[{'capacity':80}]),patch.object(menu.backend,'audio_write') as audio_write,patch.object(menu.backend,'brightness_write') as brightness_write:
  GLib.timeout_add(600,check);GLib.timeout_add_seconds(6,lambda:Gtk.Application.get_default().quit() or False)
  assert menu.popup(kind)==0;assert seen
  audio_write.assert_not_called();brightness_write.assert_not_called()
 print('PASS '+kind+' popup renders without device mutations.')

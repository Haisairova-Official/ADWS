"""Actual mouse drag regression on an isolated X11 display; no configuration writes."""
import os,sys,tempfile,json,subprocess,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import gi
gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0')
from gi.repository import Gtk,Gdk,GLib
import adws_layout as layout
import adws_layout_gui as gui
errors=[]
with tempfile.TemporaryDirectory() as temp,patch.object(gui,'scan_available_plugins',return_value=[]):
 path=Path(temp)/'layout.json';path.write_text(json.dumps(layout.default_layout()))
 host=Gtk.Window();host.set_default_size(1100,720);app=gui.LayoutWindow(str(path),parent=host);host.add(app.content)
 from adws_settings_style import SettingsStyle
 import importlib.util
 spec=importlib.util.spec_from_file_location('adws_test_config',ROOT/'tools/adws-config.py');host.config=importlib.util.module_from_spec(spec);spec.loader.exec_module(host.config)
 style=SettingsStyle(host);host.show_all()
 steps=[('start','center',None),('start','right','sound'),('sound','center','preview')]
 current=[0]
 def verify_move():
  try:
   row=next(r for r in app.rows if r['instance']==steps[current[0]][0])
   expected=steps[current[0]][1]
   assert row['slot']==expected,(row['slot'],expected)
   current[0]+=1
   if current[0]<len(steps):GLib.timeout_add(400,drag)
   else:
    import cairo
    image=cairo.ImageSurface(cairo.FORMAT_ARGB32,host.get_allocated_width(),host.get_allocated_height());host.draw(cairo.Context(image));image.write_to_png('/tmp/adws-layout-horizontal.png')
    host.destroy();style.close();Gtk.main_quit()
  except Exception as e:errors.append(e);host.destroy();Gtk.main_quit()
  return False
 def drag():
  identity,slot,anchor=steps[current[0]]
  if anchor=='preview':
   source=app.preview
   rect,_=next(hit for hit in source.hits if hit[1]==identity)
   rx,ry,rw,rh=rect
   start=source.translate_coordinates(host,int(rx+rw/2),int(ry+rh/2))
   end=source.translate_coordinates(host,source.get_allocated_width()//2,int(ry+rh/2))
  else:
   source=next(r['box'] for r in app.rows if r['instance']==identity)
   start=source.translate_coordinates(host,source.get_allocated_width()//2,source.get_allocated_height()//2)
   dest=next((r['box'] for r in app.rows if r['instance']==anchor),app.sections[slot])
   end=dest.translate_coordinates(host,10,max(10,dest.get_allocated_height()//2))
  _,ox,oy=host.get_window().get_origin()
  # Run outside the main thread so GTK receives the real DND events.
  subprocess.Popen(['xdotool','mousemove',str(ox+start[0]),str(oy+start[1]),'mousedown','1','sleep','.15','mousemove',str(ox+start[0]+24),str(oy+start[1]),'sleep','.2','mousemove',str(ox+end[0]),str(oy+end[1]),'sleep','.5','mouseup','1'])
  GLib.timeout_add(1400,verify_move);return False
 GLib.timeout_add(800,drag)
 GLib.timeout_add_seconds(12,lambda:errors.append('timeout') or Gtk.main_quit() or False)
 Gtk.main();assert not errors,errors
print('PASS real mouse DND between regions, card order and live preview')

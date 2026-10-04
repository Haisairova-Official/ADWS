"""Run under Xvfb with isolated XDG config/state. No live mutations."""
import sys, importlib.util, time, os, threading
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'tools'))
spec=importlib.util.spec_from_file_location('adws_config',root/'tools/adws-config.py');config=importlib.util.module_from_spec(spec);sys.modules[spec.name]=config;spec.loader.exec_module(config)
from gi.repository import Gtk,GLib,Gdk
from adws_system_settings import SystemSettingsWindow
Gtk.init([])
monitors=[dict(name='DP-1',description='Wide display',modes=['3440x1440@144.000','2560x1080@60.000'],mode='3440x1440@144.000',scale=1.25,x=0,y=0,transform=0),dict(name='HDMI-A-1',description='Second display',modes=['1920x1080@60.000','1920x1080@120.000'],mode='1920x1080@60.000',scale=1,x=2752,y=0,transform=0)]
def pump(seconds=.5):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  while Gtk.events_pending():Gtk.main_iteration()
  time.sleep(.005)
def shot(window,name):
 pump(.3)
 pixbuf=Gdk.pixbuf_get_from_window(window.get_window(),0,0,window.get_allocated_width(),window.get_allocated_height());pixbuf.savev('/tmp/adws-redesign-'+name+'.png','png',[],[])
with patch('adws_display.outputs',return_value=monitors), patch('adws_display.detect_session',return_value='niri'):
 w=SystemSettingsWindow(config)
 pump();shot(w,'home')
 w.account_header.clicked();pump();assert w.current=='region'
 for page in w.page_definitions:
  print('PAGE',page.key,flush=True)
  w.show_page(page.key);pump(.8)
  assert w.stack.get_visible_child_name()==page.key
  if page.key in ('taskbar','displays','sound','components','input','wallpaper','region','network','apps'):shot(w,page.key)
  if page.key=='apps':
   chooser=w.app_choices['x-scheme-handler/https']
   identities=[app.get_id() or app.get_commandline() for app in chooser.apps.values()]
   assert len(identities)==len(set(identities)),identities
   selector=chooser._adws_choice_button
   selector.set_active(True);pump();shot(w,'app-choices');selector.set_active(False)
  if page.key=='displays':
   adjustment=w.pages[page.key].get_vadjustment()
   adjustment.set_value(adjustment.get_upper()-adjustment.get_page_size());pump()
   shot(w,'display-controls')
   adjustment.set_value(0)
 w.search.set_text('lyrics');w.filter_navigation();assert w.rows['layout'].get_child_visible()
 w.search.set_text('zzzz-no-results');w.filter_navigation();assert w.empty_search.get_visible()
 w.search.set_text('');w.filter_navigation()
 print('DIRTY',w.dirty,flush=True)
 assert not w.dirty,w.dirty
 owner=w.owners['taskbar'];owner.thickness.set_value(owner.thickness.get_value()+1);assert 'taskbar' in w.dirty
 w.show_page('taskbar');pump()
 owner.position._adws_choice_button.set_active(True);pump();shot(w,'choices');owner.position._adws_choice_button.set_active(False)
 with patch.object(owner,'apply_style',return_value=True) as save:
  w.apply_changes();save.assert_called_once();assert not w.dirty
 w.show_page('displays');pump();w.display_page.select_monitor('HDMI-A-1');w.display_page.scale.set_value(125)
 assert 'displays' in w.dirty
 w.show_page('home');pump();w.show_page('displays');pump();assert w.display_page.current()['scale']==1.25
 w.display_page.discard_changes();assert not w.dirty
 # Image validation and wallpaper-service inspection must not block GTK.
 main_thread = threading.get_ident()
 def validate_wallpaper(engine, path):
  assert threading.get_ident() != main_thread
  return '/fixture/validated.png'
 def wait_idle():
  deadline = time.monotonic()+5
  while w.busy and time.monotonic()<deadline:pump(.05)
  assert not w.busy
 with patch.object(w.wallpaper_file,'get_filename',return_value='/fixture/image.png'), patch.object(w.wallpaper_engine,'get_active_id',return_value='awww'), patch('adws_wallpaper.validate',side_effect=validate_wallpaper), patch('adws_wallpaper.running',return_value={}), patch('adws_wallpaper.apply') as apply, patch.object(config,'save_json_atomic') as save:
  w.mark_dirty('wallpaper');w.apply_changes();wait_idle()
  apply.assert_called_once_with('awww','/fixture/validated.png',{})
  save.assert_called_once();assert not w.dirty
 with patch.object(w.wallpaper_file,'get_filename',return_value='/fixture/image.png'), patch.object(w.wallpaper_engine,'get_active_id',return_value='awww'), patch('adws_wallpaper.validate',side_effect=validate_wallpaper), patch('adws_wallpaper.running',return_value={123:'swaybg'}), patch('adws_wallpaper.apply') as apply, patch.object(w,'confirm',return_value=False):
  w.mark_dirty('wallpaper');w.apply_changes();wait_idle()
  apply.assert_not_called();assert 'wallpaper' in w.dirty
  w.dirty.discard('wallpaper')
 region = w.service_pages['region']
 if region.account and 'name' in region.account_inputs:
  original = region.account['name']
  region.account_inputs['name'].set_text(original+' QA')
  assert 'region' in w.dirty
  with patch('adws_system_pages.apply_account') as save, patch.object(region,'refresh'), patch.object(w.account_header,'refresh') as header:
   w.apply_changes();wait_idle()
   save.assert_called_once();header.assert_called_once_with(force=True)
   assert 'region' not in w.dirty
  region.account['name']=original;region.account_inputs['name'].set_text(original)
 w.show_page('home');w.resize(880,620);pump();shot(w,'compact')
 assert w.get_allocated_width() <= 890, w.get_allocated_width()
 w.destroy();pump()
 print('PASS all pages, state retention, custom choices and cleanup',flush=True)

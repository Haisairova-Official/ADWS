"""Isolated GTK update progress, background execution and automatic install fixture."""
import importlib.util,sys,time,threading,os,shutil
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'tools'))
spec=importlib.util.spec_from_file_location('adws_config',root/'tools/adws-config.py');config=importlib.util.module_from_spec(spec);sys.modules[spec.name]=config;spec.loader.exec_module(config)
from gi.repository import Gtk
from adws_system_settings import SystemSettingsWindow
Gtk.init([])
result={'available':True,'text':'new fixture','url':'https://github.com/fixture','release':{'tag_name':'v1.35-L-pre-release'}}
config_dir=Path(os.environ['XDG_CONFIG_HOME'])/'waybar'
config_dir.mkdir(parents=True,exist_ok=True)
for name in ('config-bottom.jsonc','style-bottom.css','modules.jsonc','colors.css'):
 shutil.copy2(root/'config/waybar'/name,config_dir/name)
main=threading.get_ident();entered=threading.Event();finish=threading.Event()
def install(result,phase,transfer):
 assert threading.get_ident()!=main
 transfer(50,100);entered.set();assert finish.wait(5)
 phase('Installing fixture');return 'Installed fixture'
def pump_until(condition):
 end=time.monotonic()+6
 while time.monotonic()<end:
  while Gtk.events_pending():Gtk.main_iteration()
  if condition():return
  time.sleep(.01)
 raise AssertionError('GUI did not finish')
w=SystemSettingsWindow(config,tab='about');owner=w.owners['desktop']
try:
 with patch('adws_update.check_update',return_value=result),patch('adws_update.install_update',side_effect=install) as updater,patch.object(owner,'confirm_update',return_value=True):
  owner.check_updates();pump_until(lambda:entered.is_set() and owner.update_progress.get_fraction()==.5)
  assert owner.update_progress.get_visible();assert not owner.update_link.get_visible()
  w.show_page('taskbar');assert w.current=='taskbar'
  finish.set();pump_until(lambda:owner.update_result.get_text()=='Installed fixture')
  assert owner.update_progress.get_fraction()==1
  assert owner.update_button.get_sensitive();assert updater.call_count==1
  assert owner.update_pulse_source==0
 print('Background download progress and automatic install GUI checks passed.')
finally:
 finish.set();w.dirty.clear();w.request_close()

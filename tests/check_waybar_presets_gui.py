"""Isolated GTK regression for staging, applying and manually backing up presets."""
import os,sys,tempfile,time,importlib.util,shutil,json
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'tools'))
import gi
gi.require_version('Gtk','3.0');from gi.repository import Gtk
import adws_waybar as backend
with tempfile.TemporaryDirectory(prefix='adws-preset-ui-') as name:
 os.environ.update(XDG_CONFIG_HOME=name+'/config',XDG_STATE_HOME=name+'/state',XDG_CACHE_HOME=name+'/cache')
 folder=Path(name)/'config/waybar';folder.mkdir(parents=True)
 for filename in ('colors.css','style-top.css','arrow-left-symbolic.svg','arrow-right-symbolic.svg'):shutil.copy2(root/'config/waybar'/filename,folder/filename)
 config=folder/'config.jsonc';config.write_text('{"name":"fixture","modules-left":["clock"],"modules-right":["tray"]}')
 style=folder/'style.css';shutil.copy2(folder/'style-top.css',style)
 spec=importlib.util.spec_from_file_location('adws_config',root/'tools/adws-config.py');module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
 from adws_system_settings import SystemSettingsWindow
 def pump():
  while Gtk.events_pending():Gtk.main_iteration()
  time.sleep(.01)
 def ready(predicate):
  until=time.monotonic()+8
  while not predicate():assert time.monotonic()<until; pump()
 with patch.object(backend,'processes',return_value=[]),patch.object(backend,'reload',return_value=0),patch.object(backend,'autostart_status',return_value={'available':True,'enabled':False}):
  window=SystemSettingsWindow(module,tab='waybar');ready(lambda:window.waybar_page.original is not None and not window.busy)
  page=window.waybar_page;original=config.read_text();original_style=style.read_text()
  for preset in ('standard','simple','status','gnome'):
   page.preset.set_active_id(preset);page.modified.clear();page.load_preset()
   assert config.read_text()==original and style.read_text()==original_style
   assert backend.decode(page.content())['adws-preset']==preset
   with patch('adws_topbar.preview') as preview:
    page.preview_preset();ready(lambda:not window.busy);preview.assert_called_once_with(preset=preset)
   assert page.preset_style and 'waybar' in window.dirty
  page.apply();ready(lambda:not window.busy)
  assert backend.decode(config.read_text())['adws-preset']=='gnome'
  assert 'border-radius: 0' in style.read_text();assert not window.dirty
  page.load();ready(lambda:not window.busy);assert page.preset.get_active_id()=='gnome'
  with patch.object(backend,'restart',return_value={'pid':99,'log':'fixture'}) as restart:
   page.restart();ready(lambda:not window.busy);restart.assert_called_once_with(config,style)
  before=list((Path(name)/'state/adws/waybar-backups').glob('*/manifest.json'))
  page.backup_current();ready(lambda:not window.busy)
  after=list((Path(name)/'state/adws/waybar-backups').glob('*/manifest.json'));assert len(after)==len(before)+1
  assert len(json.loads(after[0].read_text())['files'])==3
  page.font_follow.set_active(False);page.font_button.set_font_name('Noto Sans CJK SC 12');page.changed('font')
  page.apply();ready(lambda:not window.busy)
  fonts=backend.load_style(config)['font_settings'];assert fonts['family']=='Noto Sans CJK SC' and fonts['size']==12 and not fonts['follow']
  provider=Gtk.CssProvider();provider.load_from_data(style.read_bytes())
  page.font_follow.set_active(True);page.apply();ready(lambda:not window.busy)
  assert backend.load_style(config)['font_settings']['follow']
  page.preset.set_active_id('standard');page.load_preset();page.widgets['height'].set_value(60);page.apply();ready(lambda:not window.busy)
  assert 'min-width: 30.0px' in style.read_text()
  provider.load_from_data(style.read_bytes())
  with patch.object(backend,'set_autostart') as startup:
   page.autostart.set_active(True);page.apply();ready(lambda:not window.busy);startup.assert_called_once_with(config,style,True)
  imported=Path(name)/'import.jsonc';imported.write_text('// imported\n{"height":38,"modules-left":["clock"]}')
  before=config.read_text();before_style=style.read_text()
  page.stage_import(imported,style);ready(lambda:not window.busy)
  assert config.read_text()==before and style.read_text()==before_style
  assert page.widgets['height'].get_value_as_int()==38 and 'waybar' in window.dirty
  page.apply();ready(lambda:not window.busy)
  assert backend.decode(config.read_text())['height']==38 and '// imported' in config.read_text()
  assert 'border-radius' in style.read_text() and len(backend.bundle_records(config,style))>2
  window.destroy();pump()
 print('PASS four presets stage without writes, Apply backs up and installs, manual backup includes colors.')

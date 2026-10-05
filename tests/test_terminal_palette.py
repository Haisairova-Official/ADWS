import json,os,sys,tempfile,tomllib,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_terminal_presets as terminal
import adws_wallpaper_colors as colors
from desktop_layer import terminal as default

class PresetTests(unittest.TestCase):
 def test_preset_preserves_symlinks_and_backup(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'XDG_CONFIG_HOME':tmp+'/config','XDG_STATE_HOME':tmp+'/state'}),patch.object(terminal,'font_available',return_value=True):
   folder=Path(tmp)/'config/kitty';folder.mkdir(parents=True);real=Path(tmp)/'old.conf';real.write_text('old config\n');(folder/'kitty.conf').symlink_to(real)
   result=terminal.deploy('kitty')
   self.assertTrue((folder/'kitty.conf').is_symlink());self.assertIn('background_opacity 0.8',real.read_text())
   self.assertEqual((Path(result['backup'])/'kitty.conf').read_text(),'old config\n')
   self.assertTrue((folder/'themes/matugen.conf').is_file())
 def test_alacritty_equivalent_and_missing_font_fallback(self):
  with patch.object(terminal,'font_available',return_value=True):data,_=terminal.prepare('alacritty')
  config=tomllib.loads(data['alacritty.toml'])
  self.assertEqual(config['font']['size'],13.5);self.assertEqual(config['window']['opacity'],.8);self.assertEqual(config['window']['padding'],{'x':5,'y':5})
  self.assertEqual(config['colors']['primary']['background'],'#1e100c')
  with patch.object(terminal,'font_available',return_value=False):data,fallback=terminal.prepare('alacritty')
  self.assertTrue(fallback);self.assertEqual(tomllib.loads(data['alacritty.toml'])['font']['normal']['family'],'monospace')
 def test_partial_deploy_rolls_back(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'XDG_CONFIG_HOME':tmp+'/config','XDG_STATE_HOME':tmp+'/state'}),patch.object(terminal,'font_available',return_value=True):
   p=Path(tmp)/'config/kitty/kitty.conf';p.parent.mkdir(parents=True);p.write_text('original')
   write=terminal.write;count=[0]
   def failing(path,content):
    count[0]+=1
    if count[0]==2:raise OSError('fixture')
    return write(path,content)
   with patch.object(terminal,'write',side_effect=failing),self.assertRaises(OSError):terminal.deploy('kitty')
   self.assertEqual(p.read_text(),'original')
 def test_package_removal_is_narrow_and_unmanaged_is_rejected(self):
  data={'manager':'pacman','package':'matugen','installed':True}
  with patch.object(colors.os,'geteuid',return_value=0):self.assertEqual(colors.package_command(True,data),['pacman','-R','--noconfirm','matugen'])
  data['package']=None
  with self.assertRaises(ValueError):colors.package_command(True,data)
 def test_invalid_extraction_preserves_colors(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'XDG_CONFIG_HOME':tmp}),patch.object(colors.shutil,'which',return_value='/usr/bin/matugen'):
   image=Path(tmp)/'image.png';image.write_bytes(b'fixture');target=Path(tmp)/'waybar/colors.css';target.parent.mkdir();target.write_text('old palette')
   with patch.object(colors.subprocess,'run',side_effect=[Mock(stdout='--prefer'),Mock(returncode=0,stdout=json.dumps({'colors':{'primary':'#ffffff'}}))]),self.assertRaises(ValueError):colors.extract(image)
   self.assertEqual(target.read_text(),'old palette')
 def test_default_terminal_persists_and_rejects_unavailable_choice(self):
  info=Mock();info.get_id.return_value='kitty.desktop'
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'XDG_CONFIG_HOME':tmp}),patch.object(default,'choices',return_value=[info]),patch.object(default.Gio.AppInfo,'get_all',return_value=[]):
   default.set_default('kitty.desktop')
   self.assertEqual(default.current(),'kitty.desktop')
   with self.assertRaises(ValueError):default.set_default('missing.desktop')
   self.assertEqual(default.current(),'kitty.desktop')
 def test_default_terminal_can_return_to_system_default(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'XDG_CONFIG_HOME':tmp}):
   default.path().parent.mkdir();default.path().write_text(json.dumps({'desktop_id':'kitty.desktop'}))
   default.set_default(None);self.assertIsNone(default.current())
   default.set_default(None)
 def test_default_terminal_exec_is_literal(self):
  info=Mock();info.get_boolean.return_value=False;info.get_string.return_value='/usr/bin/kitty --title "hello world" %U'
  with patch.object(default,'current',return_value='kitty.desktop'),patch.object(default.Gio.DesktopAppInfo,'new',return_value=info),patch.object(default.shutil,'which',side_effect=lambda name:name):
   self.assertEqual(default.configured_argv(),['/usr/bin/kitty','--title','hello world'])

if __name__=='__main__':unittest.main()

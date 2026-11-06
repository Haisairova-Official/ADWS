import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_wallpaper_colors as colors
import adws_palette_sync as sync

class WallpaperChainTests(unittest.TestCase):
 def test_success_updates_adws_palette_then_only_registered_targets(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'XDG_CONFIG_HOME':tmp+'/config','XDG_STATE_HOME':tmp+'/state'}):
   image=Path(tmp)/'wallpaper.png';image.write_bytes(b'fixture')
   run=Mock(side_effect=[Mock(stdout='--source-color-index'),Mock(returncode=0,stdout=json.dumps({'colors':sync.DEFAULT_PALETTE}))])
   with patch.object(colors.shutil,'which',return_value='/fixture/matugen'),patch.object(colors.subprocess,'run',run),patch.object(sync,'synchronize',return_value={'status':'complete','targets':{}}) as apply:
    result=colors.extract(image)
   self.assertEqual(result,sync.DEFAULT_PALETTE);apply.assert_called_once_with(result)
   self.assertIn('@define-color primary',(Path(tmp)/'config/waybar/colors.css').read_text())
   command=run.call_args.args[0];self.assertIn('--dry-run',command);self.assertIn('--config',command)
 def test_failed_registered_refresh_is_reported_after_palette_write(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'XDG_CONFIG_HOME':tmp+'/config','XDG_STATE_HOME':tmp+'/state'}):
   image=Path(tmp)/'wallpaper.png';image.write_bytes(b'fixture')
   with patch.object(colors.shutil,'which',return_value='/fixture/matugen'),patch.object(colors.subprocess,'run',side_effect=[Mock(stdout=''),Mock(returncode=0,stdout=json.dumps({'colors':sync.DEFAULT_PALETTE}))]),patch.object(sync,'synchronize',return_value={'status':'partial','targets':{'mako':{'status':'failed'}}}):
    with self.assertRaisesRegex(RuntimeError,'mako'):colors.extract(image)
   self.assertTrue((Path(tmp)/'config/waybar/colors.css').exists())

if __name__=='__main__':unittest.main()

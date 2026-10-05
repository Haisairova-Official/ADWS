import io,os,sys,tempfile,subprocess,zipfile
from pathlib import Path
from unittest.mock import patch,Mock
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_fonts as fonts

class FontTests(unittest.TestCase):
 def test_existing_font_skips_everything(self):
  confirm,packages=Mock(),Mock()
  with patch.object(fonts,'available',return_value=True),patch.object(fonts,'install') as install:
   self.assertTrue(fonts.ensure_fonts(confirm,packages));install.assert_not_called()
  confirm.assert_not_called();packages.assert_not_called()
 def test_decline_never_downloads(self):
  with patch.object(fonts,'available',return_value=False),patch.object(fonts,'install') as install:
   self.assertFalse(fonts.ensure_fonts(lambda _:False,Mock(),lambda _:None));install.assert_not_called()
 def test_optional_failure_allows_adws_install(self):
  with patch.object(fonts,'available',return_value=False),patch.object(fonts,'install',side_effect=RuntimeError('network')):
   self.assertFalse(fonts.ensure_fonts(lambda _:True,Mock(),lambda _:None))
 def test_detect_font_family_without_accepting_plain_font(self):
  with patch.object(fonts.shutil,'which',return_value='/bin/tool'),patch.object(fonts.subprocess,'run',return_value=Mock(returncode=0,stdout='JetBrains Mono\n')):
   self.assertFalse(fonts.available())
  with patch.object(fonts.shutil,'which',return_value='/bin/tool'),patch.object(fonts.subprocess,'run',return_value=Mock(returncode=0,stdout='Symbols Nerd Font Mono\n')):
   self.assertTrue(fonts.available())
 def test_wrong_hash_is_rejected(self):
  with tempfile.TemporaryDirectory() as name,patch('adws_update.github_urls',return_value=['https://example.invalid/font.zip']),patch('adws_update.mainland_china',return_value=False),patch.object(fonts.urllib.request,'urlopen',return_value=io.BytesIO(b'wrong')):
   path=Path(name)/'font.zip'
   with self.assertRaises(RuntimeError):fonts.download(path)
   self.assertFalse(path.exists())
 def test_cache_failure_restores_old_fonts_and_paths_are_not_extracted(self):
  with tempfile.TemporaryDirectory() as name,patch.dict(os.environ,{'XDG_DATA_HOME':name}):
   destination=Path(name)/'fonts/ADWS-NerdSymbols';destination.mkdir(parents=True);(destination/'old').write_text('keep')
   def fake_download(target):
    with zipfile.ZipFile(target,'w') as package:
     for filename in fonts.FONTS:package.writestr(filename,b'\x00\x01\x00\x00font')
     package.writestr('../../unexpected','bad');package.writestr('LICENSE.txt','license')
   with patch.object(fonts,'download',side_effect=fake_download),patch.object(fonts.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['fc-cache'])):
    with self.assertRaises(subprocess.CalledProcessError):fonts.install()
   self.assertEqual((destination/'old').read_text(),'keep');self.assertFalse((Path(name)/'unexpected').exists())
 def test_missing_font_does_not_replace_previous(self):
  with tempfile.TemporaryDirectory() as name,patch.dict(os.environ,{'XDG_DATA_HOME':name}):
   destination=Path(name)/'fonts/ADWS-NerdSymbols';destination.mkdir(parents=True);(destination/'old').write_text('keep')
   def fake_download(target):
    with zipfile.ZipFile(target,'w') as package:package.writestr('other.ttf',b'bad')
   with patch.object(fonts,'download',side_effect=fake_download):
    with self.assertRaises(ValueError):fonts.install()
   self.assertEqual((destination/'old').read_text(),'keep')
if __name__=='__main__':unittest.main()

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

class TextFontTests(unittest.TestCase):
 def charset(self,text):return ' '.join(format(ord(char),'x') for char in dict.fromkeys(text))
 def runner(self,output):return Mock(return_value=subprocess.CompletedProcess(['fc-list'],0,output,''))
 def test_symbol_and_latin_fonts_do_not_satisfy_text_coverage(self):
  run=self.runner('20-7e a0-ff e000-f8ff\n')
  report=fonts.probe_text_fonts(run=run,environ={'LANG':'en_US.UTF-8'})
  self.assertEqual(report['status'],'missing');self.assertIn('中',report['missing']['zh'])
  self.assertIn('ひ',report['missing']['ja'])
  self.assertIn('한',report['missing']['ko']);self.assertEqual(run.call_args.args[0][0],'fc-list')
 def test_multiple_font_charsets_can_together_supply_the_scripts(self):
  output='\n'.join(self.charset(sample) for sample in fonts.TEXT_SAMPLES.values())
  report=fonts.probe_text_fonts(run=self.runner(output),environ={'LANG':'C'})
  self.assertEqual(report['status'],'ready');self.assertFalse(any(report['missing'].values()))
 def test_a_single_missing_glyph_is_reported(self):
  chars=''.join(fonts.TEXT_SAMPLES.values()).replace('한','')
  report=fonts.probe_text_fonts(run=self.runner(self.charset(chars)))
  self.assertEqual(report['status'],'missing');self.assertEqual(report['missing']['ko'],'한')
  self.assertFalse(report['missing']['zh']);self.assertFalse(report['missing']['ja'])
 def test_fontconfig_failure_cannot_pass(self):
  cases=[self.runner('not-a-charset'),self.runner('110000'),self.runner('ffff-20'),
         Mock(side_effect=FileNotFoundError('fc-list')),Mock(side_effect=subprocess.TimeoutExpired('fc-list',15)),
         Mock(return_value=subprocess.CompletedProcess(['fc-list'],1,'20-10ffff','error'))]
  for run in cases:
   with self.subTest(run=run):
    report=fonts.probe_text_fonts(run=run);self.assertEqual(report['status'],'unavailable')
    with self.assertRaisesRegex(RuntimeError,'文字字体覆盖验证失败'):fonts.require_text_fonts(probe=lambda:report)
 def test_legacy_repair_installs_only_when_missing_then_rechecks(self):
  missing={'status':'missing','missing':{'zh':'中','ja':'日','ko':'한'}}
  ready={'status':'ready','missing':{'zh':'','ja':'','ko':''}}
  install=Mock();probe=Mock(side_effect=[missing,ready])
  self.assertEqual(fonts.ensure_text_fonts(install,'pacman',probe=probe),ready)
  install.assert_called_once_with(['fontconfig','noto-fonts-cjk']);self.assertEqual(probe.call_count,2)
  install.reset_mock();fonts.ensure_text_fonts(install,'pacman',probe=lambda:ready);install.assert_not_called()
  with self.assertRaisesRegex(RuntimeError,'文字字体覆盖验证失败'):
   fonts.ensure_text_fonts(Mock(),'pacman',probe=lambda:missing)
 def test_managed_prepare_rejects_missing_coverage_without_unreviewed_repair(self):
  import adws_setup as setup
  missing={'status':'missing','missing':{'zh':'中','ja':'ひ','ko':'한'}}
  with patch('adws_niri_install.ensure_niri'),patch.object(setup,'dependency_errors',return_value=[]),\
       patch.object(setup,'approved_plan',return_value={'features':{'manager':'pacman'}}),\
       patch.object(fonts,'probe_text_fonts',return_value=missing),patch.object(setup,'install_packages') as install,\
       patch.object(fonts,'ensure_fonts') as symbols,patch('builtins.print'):
   with self.assertRaisesRegex(RuntimeError,'文字字体覆盖验证失败'):setup.prepare()
  install.assert_not_called();symbols.assert_not_called()
if __name__=='__main__':unittest.main()

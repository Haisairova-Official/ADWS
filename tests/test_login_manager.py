import sys,tempfile,subprocess
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_login_manager as login

class LoginTests(unittest.TestCase):
    def setup_root(self,folder,target):
        root=Path(folder);alias=root/'etc/systemd/system/display-manager.service';alias.parent.mkdir(parents=True);alias.symlink_to('/usr/lib/systemd/system/'+target+'.service');return root
    def write(self,root,path,text):
        p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    def test_sddm_custom_directory_priority_and_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self.setup_root(folder,'sddm')
            self.write(root,'usr/lib/sddm/sddm.conf.d/10.conf','[Wayland]\nSessionDir=/vendor/sessions\n')
            self.write(root,'etc/sddm.conf','[Wayland]\nSessionDir=/custom/wayland-sessions,/usr/share/wayland-sessions\n')
            self.write(root,'custom/wayland-sessions/niri.desktop','[Desktop Entry]\nExec=/usr/bin/niri-session\n')
            result=login.detect(root)
            self.assertEqual(result['id'],'sddm');self.assertEqual(result['session_dirs'][0],Path('/custom/wayland-sessions'))
            self.assertEqual(len(login.session_entries(result,root)),1)
    def test_plasma_does_not_read_sddm_setting(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self.setup_root(folder,'plasmalogin')
            self.write(root,'etc/sddm.conf','[Wayland]\nSessionDir=/wrong\n')
            result=login.detect(root)
            self.assertEqual(result['name'],'Plasma Login Manager');self.assertIn(Path('/usr/share/wayland-sessions'),result['session_dirs'])
    def test_gdm_disabled_is_reported_not_modified(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self.setup_root(folder,'gdm')
            self.write(root,'etc/gdm/custom.conf','[daemon]\nWaylandEnable=false\n')
            self.assertEqual(login.detect(root)['warning'],'wayland-disabled')
            self.assertIn('false',(root/'etc/gdm/custom.conf').read_text())
    def test_lightdm_honors_disabled_wayland_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self.setup_root(folder,'lightdm')
            self.write(root,'etc/lightdm/lightdm.conf','[LightDM]\nsessions-directory=/usr/share/xsessions\n')
            self.assertEqual(login.detect(root)['session_dirs'],[])
    def test_unknown_is_not_inferred_from_installed_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.write(root,'usr/bin/sddm','installed')
            self.assertIsNone(login.detect(root)['id'])
    def test_active_manager_takes_precedence(self):
        result=subprocess.CompletedProcess([],0,'ActiveState=active\nId=plasmalogin.service\n','')
        with patch.object(Path,'is_symlink',return_value=True),patch.object(Path,'readlink',return_value=Path('/usr/lib/systemd/system/sddm.service')):
            found=login.detect(runner=lambda *a,**k:result)
        self.assertEqual(found['id'],'plasmalogin');self.assertEqual(found['configured'],'sddm')
    def test_relative_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self.setup_root(folder,'sddm');self.write(root,'etc/sddm.conf','[Wayland]\nSessionDir=../sessions\n')
            with self.assertRaises(ValueError):login.detect(root)
if __name__=='__main__':unittest.main()

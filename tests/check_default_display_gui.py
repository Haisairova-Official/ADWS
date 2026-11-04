"""Default display selector persists immediately without changing compositor modes."""
import os,sys,tempfile
from pathlib import Path
from unittest.mock import patch
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from adws_display_gui import DisplaySettingsPage
import adws_desktop_preferences as prefs
class Host(Gtk.Window):
    closed=False;busy=False;display_session='niri'
    def __init__(self):super().__init__();self.dirty=set()
    def mark_dirty(self,key):self.dirty.add(key)
    def update_footer(self):pass
    def confirm(self,*_):return True
    def run_worker(self,job,success):job();success()
with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'XDG_CONFIG_HOME':folder}):
    outputs=[dict(name='DP-'+str(i),monitor_id='id-'+str(i),description='Display '+str(i),mode='1920x1080@60',modes=['1920x1080@60'],scale=1.,transform=0,x=(i-1)*1920,y=0) for i in (1,2)]
    with patch('adws_display.outputs',return_value=outputs):
        host=Host();page=DisplaySettingsPage(host);host.add(page);host.show_all()
        while Gtk.events_pending():Gtk.main_iteration()
        page.default_monitor.set_active_id('id-2')
        assert prefs.load()['default_monitor']=='id-2'
        assert not page.has_pending() and not host.dirty
        page.set_outputs(outputs[:1])
        assert page.default_monitor.get_active_id()=='id-2'
        assert prefs.load()['default_monitor']=='id-2'
        page.set_outputs(outputs)
        assert page.default_monitor.get_active_id()=='id-2'
        host.destroy()
    print('PASS: explicit default-display setting, immediate persistence and disconnected selection retention')

"""Native blur-region lifecycle regression; run on Wayland with --library PATH.

All user data is isolated. Hardware reads are stubbed. This verifies protocol
lifetime/regions, not compositor screenshots or subjective smoothness.
"""
import argparse
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
parser=argparse.ArgumentParser();parser.add_argument('--library',type=Path,required=True);args=parser.parse_args()
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'tools'))
base=Path(tempfile.mkdtemp(prefix='adws-blur-test-'))
for key in ('XDG_CONFIG_HOME','XDG_CACHE_HOME','XDG_DATA_HOME','XDG_STATE_HOME'):
    path=base/key;path.mkdir();os.environ[key]=str(path)
os.environ['GDK_BACKEND']='wayland';os.environ['GTK_USE_PORTAL']='0'
from adws_sidebar import Dashboard
from gi.repository import Gtk
app=Gtk.Application(application_id='org.adws.BlurLifecycleTest');app.register(None)
def pump(seconds):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        while Gtk.events_pending():Gtk.main_iteration()
        time.sleep(.003)
with patch('adws_popup_effect.library_paths',return_value=[args.library]),patch('adws_account_header.query_properties',return_value={}),patch('adws_quick_backend.audio',return_value={'sinks':[]}),patch('adws_quick_backend.brightness',return_value=[]),patch('adws_quick_backend.cached_brightness',return_value=None),patch('adws_sidebar_widgets.QuickActions.snapshot',return_value={}),patch('adws_sidebar_widgets.media_snapshot',return_value=None),patch('adws_sidebar_notifications.snapshot',return_value={'provider':None,'items':[],'dnd':None}):
    window=Dashboard(app);window.motion_settings=(True,180);window.retain_on_close=True;window.interaction_depth=1
    for edge in ('right','left','bottom','top')*2:
        window.slide_edge=edge
        window.reveal();pump(.35)
        assert window.popup_effect.handle and window.motion_shift==0
        assert window.popup_effect.region[:2]==(0,0)
        window.dismiss();pump(.085)
        region=window.popup_effect.region;assert region is not None
        axis=0 if edge in ('left','right') else 1
        assert region[axis]<0 if edge in ('left','top') else region[axis]>0
        pump(.25)
        assert not window.get_mapped() and not window.popup_effect.handle
    window.reveal();pump(.08);window.dismiss();pump(.03)
    window.closing=False;window.animate(True);pump(.3)
    assert window.motion_shift==0 and window.motion_opacity==1 and window.popup_effect.handle
    window.motion_settings=(False,180);window.dismiss()
    assert not window.get_mapped() and not window.popup_effect.handle
    window.destroy();pump(.1)
print('PASS: all edges, repeated surface recreation, interrupted closing, disabled animation, cleanup')

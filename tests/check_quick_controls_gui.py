"""Isolated native popup regression; fixture devices, no hardware changes."""
import os
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import gi
gi.require_version('Gtk','3.0')
gi.require_version('Gdk','3.0')
from gi.repository import Gtk,GLib
import adws_quick_backend as backend
import adws_quick_controls as controls

kind=sys.argv[1];detailed='--panel' in sys.argv
sinks=[{'name':'speakers','index':1,'description':'Speakers','volume':56,'mute':False,'default':True}]
apps=[{'index':8,'volume':34,'mute':False,'properties':{'application.name':'Music'}}]
displays=[{'name':'DP-1','description':'Monitor','value':55,'provider':'ddc','device':1,'maximum':100,'temperature':4500,'night':True,'color_provider':'gamma'},
          {'name':'HDMI-A-1','description':'Unsupported monitor','value':None,'provider':None,'temperature':6500,'night':False,'color_provider':None}]
writes=[]

def widgets(parent):
    yield parent
    if isinstance(parent,Gtk.Container):
        for child in parent.get_children():yield from widgets(child)

errors=[]

def verify():
    try:
        panel=next(w for w in Gtk.Window.list_toplevels() if w.get_visible() and isinstance(w,Gtk.ApplicationWindow))
        children=list(widgets(panel));scales=[w for w in children if isinstance(w,Gtk.Scale)]
        expected=2 if detailed and kind=='sound' else 4 if detailed else 1
        assert len(scales)==expected,(len(scales),expected)
        assert not writes,'Opening controls changed hardware'
        scales[0].set_value(61)
        for switch in (w for w in children if isinstance(w,Gtk.Switch)):
            assert switch.get_allocated_width()<100,'Switch stretched'
        if kind=='brightness' and detailed:
            assert not scales[2].get_sensitive() and not scales[3].get_sensitive()
        # Dismissing before the coalescing timer expires must retain the edit.
        panel.close()
    except Exception as error:
        errors.append(error)
        for window in Gtk.Window.list_toplevels():window.destroy()
    return False

with patch.object(backend,'audio',return_value={'sinks':sinks,'apps':apps if detailed else []}),patch.object(backend,'brightness',return_value=displays),patch.object(backend,'audio_write',side_effect=lambda *args:writes.append(args)),patch.object(backend,'brightness_write',side_effect=lambda *args:writes.append(args)):
    GLib.timeout_add(800,verify)
    controls.run(kind,detailed,{'edge':'bottom','x':500,'monitor':0})
    import time
    deadline=time.monotonic()+1
    while not writes and time.monotonic()<deadline:time.sleep(.01)
    assert not errors,errors
    assert len(writes)==1,writes
print('PASS',kind,'panel' if detailed else 'quick')

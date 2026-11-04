"""Actual X11 pointer drag: no hardware commits before release, final edit retained."""
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk
from adws_brightness_slider import HardwareSlider

assert os.environ.get('ADWS_ISOLATED_X11')=='1', 'Run only inside an isolated Xvfb display'
def pump(seconds):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        while Gtk.events_pending():Gtk.main_iteration()
        time.sleep(.005)
def mouse(*args):subprocess.run(['xdotool',*map(str,args)],check=True)

window=Gtk.Window();window.set_default_size(440,100)
scale=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,5,100,1)
scale.set_value(50);window.add(scale)
writes=[];control=HardwareSlider(scale,writes.append)
window.show_all();pump(.2)
_,ox,oy=window.get_window().get_origin()
x,y=scale.translate_coordinates(window,0,0);y+=scale.get_allocated_height()//2
try:
    mouse('mousemove',ox+x+220,oy+y,'mousedown',1);pump(.1)
    for offset in (250,290,330,370):
        mouse('mousemove',ox+x+offset,oy+y);pump(.12)
    pump(.35)
    assert not writes, ('DDC write while pointer held',writes)
    final=scale.get_value()
    mouse('mouseup',1);pump(.1)
    assert writes==[final],writes
    control.set_value(40);pump(.3)
    assert writes==[final], 'Status refresh committed a hardware write'
    for value in (41,42,43,44):scale.set_value(value);pump(.05)
    pump(.3)
    assert writes==[final,44],writes
    scale.set_value(60);window.hide();pump(.1)
    assert writes==[final,44,60],writes
    print('PASS: real drag writes only on release; wheel/key edits coalesce; hide retains final value')
finally:
    mouse('mouseup',1)
    window.destroy()

"""Cached controls remain usable while hardware reads are deliberately blocked."""
import os,sys,tempfile,threading,time,shutil
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
workspace=tempfile.TemporaryDirectory(prefix='adws-brightness-ui-')
for key,sub in [('HOME','home'),('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('XDG_STATE_HOME','state'),('XDG_DATA_HOME','data')]:
    path=Path(workspace.name)/sub;path.mkdir();os.environ[key]=str(path)
os.environ['GDK_BACKEND']='x11'
folder=Path(os.environ['XDG_CONFIG_HOME'])/'waybar';folder.mkdir()
for name in ('config-bottom.jsonc','style-bottom.css','modules.jsonc','colors.css'):
    shutil.copy2(root/'config/waybar'/name,folder/name)
sys.path.insert(0,str(root/'tools'))
import adws_quick_controls as controls
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
release=threading.Event();reading=threading.Event();written=threading.Event();errors=[];phase=[0];start=time.monotonic();scale=[None]
detailed='--detailed' in sys.argv
items=[{'name':'DP-1','description':'Fixture','provider':'ddc','value':40,'temperature':6500,'night':False,'color_provider':None}]
if detailed:items.append(dict(items[0],name='DP-2',description='Unavailable fixture',provider=None,value=None))
def read(**kwargs):
    reading.set();assert release.wait(8);return [dict(items[0],value=40)]
def write(item,action,value):
    assert value==70;assert not release.is_set();written.set()
def widgets(widget):
    yield widget
    if isinstance(widget,Gtk.Container):
        for child in widget.get_children():yield from widgets(child)
def inspect():
    try:
        if time.monotonic()-start>6:raise AssertionError('UI fixture timed out')
        windows=[w for w in Gtk.Window.list_toplevels() if hasattr(w,'body')]
        if not windows:return True
        window=windows[0]
        if phase[0]==0:
            candidates=[w for w in widgets(window.body) if isinstance(w,Gtk.Scale)]
            if not candidates:return True
            assert reading.is_set()
            if detailed:
                all_widgets=list(widgets(window.body))
                assert len([w for w in all_widgets if isinstance(w,Gtk.Separator)])==1
                assert len(candidates)==4
                assert candidates[0].get_sensitive()
                assert all(not w.get_sensitive() for w in candidates[1:])
                labels=[w for w in all_widgets if isinstance(w,Gtk.Label)]
                assert any('Unavailable fixture' in w.get_text() and not w.get_sensitive() for w in labels)
                release.set();phase[0]=3;window.close();return False
            assert len(candidates)==1
            scale[0]=candidates[0];assert scale[0].get_sensitive();assert scale[0].get_value()==40
            scale[0].set_value(70);phase[0]=1
        elif phase[0]==1 and written.is_set():
            release.set();phase[0]=2
        elif phase[0]==2 and window.read_future.done():
            assert scale[0].get_value()==70
            window.close();return False
        return True
    except Exception as error:
        errors.append(error);release.set()
        for w in Gtk.Window.list_toplevels():w.close()
        return False
GLib.timeout_add(30,inspect)
try:
    with patch.object(controls.backend,'cached_brightness',return_value=items),patch.object(controls.backend,'brightness',side_effect=read),patch.object(controls.backend,'brightness_write',side_effect=write):
        controls.run('brightness',detailed,output='')
    if errors:raise errors[0]
    assert phase[0]==3 if detailed else written.is_set()
    print('Per-display separator and insensitive labels/controls verified.' if detailed else 'Cached slider appears before hardware completion; edits apply immediately and survive refresh.')
finally:
    release.set();workspace.cleanup()

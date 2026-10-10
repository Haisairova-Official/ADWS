"""Use dbus-run-session + xvfb-run: real service cache expiry and invalidation."""
import gc,json,os,sys,tempfile,weakref
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'tools'))
base=Path(tempfile.mkdtemp(prefix='adws-service-test-'))
for key in ('XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME','XDG_STATE_HOME'):
    path=base/key;path.mkdir();os.environ[key]=str(path)
os.environ.pop('WAYLAND_DISPLAY',None);os.environ.update(GDK_BACKEND='x11',XDG_SESSION_TYPE='x11')
os.environ.update(GTK_USE_PORTAL='0',GIO_USE_VFS='local')
import adws_sidebar as sidebar
from gi.repository import Gio,GLib
windows=[];errors=[]
class Measured(sidebar.Dashboard):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.motion_settings=(True,100);windows.append(weakref.ref(self))
    def focus_out(self,*_):return False
real_timeout=GLib.timeout_add_seconds
def bounded_timeout(seconds,callback,*args):return real_timeout(1 if seconds==60 else seconds,callback,*args)
def request(locale=None):
    payload={'anchor':{},'side':None}
    if locale is not None:payload['locale']=locale
    Gio.Application.get_default().activate_action('open',GLib.Variant('s',json.dumps(payload)))
def stage(at,fn):
    def checked():
        try:fn()
        except Exception as error:errors.append(error);Gio.Application.get_default().quit()
        return False
    GLib.timeout_add(at,checked)
def first_close():
    assert len(windows)==1 and windows[-1]().get_visible();request()
def reopen():
    assert not windows[-1]().get_visible();request();assert len(windows)==1

def invalidation():
    assert not windows[-1]().get_visible()
    sidebar.save_config({'side':'left'})
    request();assert len(windows)==2
def language_change():
    request({'LANG':'zh_CN.UTF-8'})
    assert len(windows)==3 and windows[-1]().get_title()=='ADWS 侧边栏'
def prepared():
    assert len(windows)==1 and not windows[-1]().get_visible()
    request()
stage(100,prepared)
stage(300,first_close);stage(600,reopen);stage(900,request);stage(1200,invalidation);stage(1550,request);stage(1850,language_change);stage(2200,request)
with patch.object(sidebar,'Dashboard',Measured),patch.object(GLib,'timeout_add_seconds',bounded_timeout),patch('adws_account_header.query_properties',return_value={}),patch('adws_quick_backend.audio',return_value={'sinks':[]}),patch('adws_quick_backend.brightness',return_value=[]),patch('adws_quick_backend.cached_brightness',return_value=None),patch('adws_sidebar_widgets.media_snapshot',return_value=None),patch('adws_sidebar_notifications.snapshot',return_value={'provider':None,'items':[],'dnd':None}),patch('adws_sidebar_widgets.QuickActions.snapshot',return_value={}):
    sidebar.run(prepare=True)
if errors:raise errors[0]
gc.collect()
assert len(windows)==3 and all(ref() is None for ref in windows)
print('PASS: warm reuse, external configuration invalidation, expiry destroys all windows and exits')

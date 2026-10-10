"""Opt-in real Niri pointer test; all clipboard data is synthetic."""
import os,sys,time,socket,struct,tempfile,json,subprocess
from pathlib import Path
from unittest.mock import patch
if '--allow-pointer-test' not in sys.argv or not os.environ.get('NIRI_SOCKET'):
 raise SystemExit('Run in Niri with --allow-pointer-test: moves the pointer over a temporary test window.')
sys.path.insert(0,str(Path(os.environ.get('ADWS_TEST_ROOT',Path(__file__).resolve().parents[1]))/'tools'))
base=Path(tempfile.mkdtemp(prefix='adws-pin-wayland-'))
for env in ('HOME','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME','XDG_STATE_HOME'):
 p=base/env;p.mkdir();os.environ[env]=str(p)
from adws_clipboard_gui import Clipboard
from gi.repository import Gtk

def pump(seconds):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  while Gtk.events_pending():Gtk.main_iteration()
  time.sleep(.003)
class Pointer:
 def __init__(self,rect):
  path=os.environ['WAYLAND_DISPLAY'];path=path if path.startswith('/') else os.path.join(os.environ['XDG_RUNTIME_DIR'],path)
  self.s=socket.socket(socket.AF_UNIX);self.s.settimeout(2);self.s.connect(path);self.buf=b'';self.globals=[];self.outputs={};self.nextid=4
  self.send(1,1,struct.pack('I',2));self.sync(3)
  manager=next(n for n,i,v in self.globals if i=='zwlr_virtual_pointer_manager_v1')
  manager_id=self.alloc();self.bind(manager,'zwlr_virtual_pointer_manager_v1',2,manager_id)
  for i,(n,iface,v) in enumerate(self.globals):
   if iface=='wl_output':self.bind(n,iface,min(v,4),self.alloc())
  self.sync(self.alloc())
  descriptions=json.loads(subprocess.check_output(['niri','msg','-j','outputs']))
  name=next(k for k,v in descriptions.items() if v.get('logical') and v['logical']['x']==rect.x and v['logical']['y']==rect.y)
  output=next(i for i,n in self.outputs.items() if n==name)
  self.pointer_id=self.alloc();self.send(manager_id,2,struct.pack('III',0,output,self.pointer_id));self.sync(self.alloc())
 def alloc(self):
  value=self.nextid;self.nextid+=1;return value
 def send(self,obj,op,data=b''):self.s.sendall(struct.pack('II',obj,((8+len(data))<<16)|op)+data)
 def bind(self,name,iface,version,identity):
  b=iface.encode()+b'\0';self.send(2,0,struct.pack('II',name,len(b))+b+b'\0'*((-len(b))%4)+struct.pack('II',version,identity))
 def sync(self,identity):
  self.send(1,0,struct.pack('I',identity))
  while True:
   while len(self.buf)<8:self.buf+=self.s.recv(65536)
   obj,sizeop=struct.unpack('II',self.buf[:8]);size=sizeop>>16;op=sizeop&65535
   while len(self.buf)<size:self.buf+=self.s.recv(65536)
   b=self.buf[8:size];self.buf=self.buf[size:]
   if obj==identity:return
   if obj==1 and op==0:raise RuntimeError(b)
   if obj==2 and op==0:
    name,length=struct.unpack('II',b[:8]);iface=b[8:8+length-1].decode();version=struct.unpack('I',b[8+(length+3)//4*4:][:4])[0];self.globals.append((name,iface,version))
   elif obj>=5 and op==4:
    length=struct.unpack('I',b[:4])[0];self.outputs[obj]=b[4:4+length-1].decode()
 def move(self,x,y,w,h):
  self.send(self.pointer_id,1,struct.pack('IIIII',int(time.monotonic()*1000)&0xffffffff,int(x),int(y),w,h));self.send(self.pointer_id,4)
 def button(self,down):self.send(self.pointer_id,2,struct.pack('III',int(time.monotonic()*1000)&0xffffffff,272,int(down)));self.send(self.pointer_id,4)
 def close(self):self.button(False);self.send(self.pointer_id,8);self.s.close()
previous=json.loads(subprocess.check_output(['niri','msg','-j','focused-window']))
Gtk.init([]);app=Gtk.Application(application_id='org.adws.PinWaylandTest');app.register(None)
with patch('adws_clipboard.ensure_watcher'),patch('adws_clipboard.entries',return_value=['1\tWindow pin drag test']),patch('adws_clipboard.copy_entry'):
 w=Clipboard(app);pointer=None;receiver=None
 try:
  w.motion_settings=(False,0);w.reveal();pump(.4);assert w.layer
  w.window_pin_button.set_active(True);pump(.2)
  rect=w.popup_monitor.get_geometry();pointer=Pointer(rect)
  ox,oy=w.manual_position;hx,hy=w.drag_handle.translate_coordinates(w,35,18)
  x=ox-rect.x+hx;y=oy-rect.y+hy
  pointer.move(x,y,rect.width,rect.height);pump(.2);pointer.button(True);pump(.08)
  assert w.drag_origin is not None,'Header press did not start drag'
  for step in range(1,13):
   pointer.move(x-15*step,y+5*step,rect.width,rect.height);pump(.035)
  pointer.button(False);pump(.2)
  print(json.dumps({'start':[ox,oy],'end':w.manual_position,'expected':[ox-180,oy+60],'size':list(w.get_size())}),flush=True)
  assert abs(w.manual_position[0]-(ox-180))<10 and abs(w.manual_position[1]-(oy+60))<10
  assert w.drag_origin is None and w.interaction_depth==0
  ox,oy=w.manual_position;hx,hy=w.drag_handle.translate_coordinates(w,35,18)
  x=ox-rect.x+hx;y=oy-rect.y+hy
  pointer.move(x,y,rect.width,rect.height);pump(.08);pointer.button(True);pump(.04)
  for step in range(1,13):
   pointer.move(x-10*step,y+3*step,rect.width,rect.height);pump(.005)
  pointer.button(False);pump(.15)
  assert abs(w.manual_position[0]-(ox-120))<10 and abs(w.manual_position[1]-(oy+36))<10, w.manual_position
  receiver=Gtk.Window();receiver.set_decorated(False);receiver.set_size_request(60,60)
  layer=w.layer;layer.init_for_window(receiver);layer.set_monitor(receiver,w.popup_monitor)
  layer.set_layer(receiver,layer.Layer.OVERLAY);layer.set_keyboard_mode(receiver,layer.KeyboardMode.ON_DEMAND)
  layer.set_exclusive_zone(receiver,-1)
  for edge in (layer.Edge.LEFT,layer.Edge.TOP):layer.set_anchor(receiver,edge,True);layer.set_margin(receiver,edge,20)
  receiver.show_all();pump(.1)
  pointer.move(40,40,rect.width,rect.height);pump(.05);pointer.button(True);pointer.button(False);pump(.4)
  assert not w.is_active(),'Test receiver must take actual focus'

  assert not w.closed,'Pinned window disappeared after outside click'
  w.copy('1\tWindow pin drag test');pump(.2);assert not w.closed
  w.window_pin_button.set_active(False);w.had_focus=True;w.focus_out();pump(.3)
  assert w.closed,'Unpinned inactive popup should close'
  print('WAYLAND slow/fast actual drag, focus loss, copy stay-open and unpin dismissal passed',flush=True)
 finally:
  if pointer:pointer.close()
  if receiver:receiver.destroy()
  w.destroy();pump(.05)
  if previous:subprocess.run(['niri','msg','action','focus-window','--id',str(previous['id'])],stdout=subprocess.DEVNULL)

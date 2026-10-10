"""Isolated UI check; never read or overwrite the user's real clipboard."""
import os,sys,tempfile,time,subprocess
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(os.environ.get('ADWS_TEST_ROOT',Path(__file__).resolve().parents[1]))/'tools'))
base=Path(tempfile.mkdtemp(prefix='adws-clipboard-gui-'))
for env,name in [('HOME','home'),('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_STATE_HOME','state'),('XDG_CACHE_HOME','cache')]:
 p=base/name;p.mkdir();os.environ[env]=str(p)
os.environ.pop('WAYLAND_DISPLAY',None)
os.environ.update(XDG_SESSION_TYPE='x11',GDK_BACKEND='x11',GTK_USE_PORTAL='0',GIO_USE_VFS='local')
from adws_clipboard_gui import Clipboard
from gi.repository import Gtk,Gdk,GdkPixbuf
Gtk.init([]);app=Gtk.Application(application_id='org.adws.ClipboardGuiTest');app.register(None)
def pump(seconds=.35):
 until=time.monotonic()+seconds
 while time.monotonic()<until:
  while Gtk.events_pending():Gtk.main_iteration()
  time.sleep(.005)
records=['1\tADWS — 让桌面按你的方式工作。','2\thttps://forum.akiacg.com','3\t[[ binary data 20 KiB png 320x200 ]]']
pix=GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB,False,8,640,320);pix.fill(0x947bcaff)
_,png=pix.save_to_bufferv('png',[],[])
def decoded(line,**kwargs):return png if 'binary data' in line else ('完整内容\n'+line.split('\t',1)[-1]).encode()
with patch('adws_clipboard.ensure_watcher'),patch('adws_clipboard.entries',return_value=records),patch('adws_clipboard.copy_entry') as copy,patch('adws_clipboard.run',return_value=b'') as run,patch('adws_clipboard.preview_data',side_effect=decoded) as decode:
 w=Clipboard(app);w.motion_settings=(True,240);w.reveal();pump(.7)
 assert len(w.listing.get_children())==3
 assert w.get_allocated_height()>=780
 # Window pin is independent of record pins: copy/focus loss keep it open.
 w.window_pin_button.set_active(True);pump(.1)
 w.had_focus=True
 with patch.object(w,'is_active',return_value=False):w.focus_out();pump(.3)
 assert not w.closed and not w.closing
 w.copy(records[0]);pump(.2);assert not w.closed
 copy.reset_mock()
 ox,oy=w.get_window().get_origin()[-2:];hx,hy=w.drag_handle.translate_coordinates(w,30,16)
 subprocess.run(['xdotool','mousemove',str(ox+hx),str(oy+hy),'mousedown','1'],check=True);pump(.05)
 for step in range(1,9):
  subprocess.run(['xdotool','mousemove',str(ox+hx-20*step),str(oy+hy+10*step)],check=True);pump(.025)
 subprocess.run(['xdotool','mouseup','1'],check=True);pump(.1)
 assert w.manual_position==(ox-160,oy+80),(w.manual_position,ox,oy)
 assert w.drag_origin is None and w.interaction_depth==0
 position=w.manual_position;w.show_records(records);pump(.1)
 assert w.manual_position==position
 w.window_pin_button.set_active(False)
 local=Gtk.Popover.new(w.search)
 assert w.owns_grab(local)
 unrelated=Gtk.Window();button=Gtk.Button();unrelated.add(button)
 assert not w.owns_grab(button)
 local.destroy();unrelated.destroy()
 pump(.5)
 assert w.listing.get_children()[2].thumbnail.get_pixbuf() is not None
 assert decode.call_count==1,decode.call_count
 row=w.listing.get_children()[0];w.show_detail(row.preview_button,row.record);pump(.4)
 popup=w.detail_popup;assert popup is not None and w.owns_grab(popup)
 scroll=popup.get_child().get_children()[0];view=scroll.get_child();buffer=view.get_buffer()
 assert buffer.get_text(buffer.get_start_iter(),buffer.get_end_iter(),True).startswith('完整内容\n')
 popup.popdown();pump()
 # Pinning keeps the entire payload independently of cliphist history.
 w.toggle_pin(records[0]);pump(.4)
 fixed=w.records[0]
 assert fixed.startswith('adws-pin:')
 assert w.listing.get_children()[0].get_style_context().has_class('pinned')
 assert len(w.records)==3
 pix=Gdk.pixbuf_get_from_window(w.get_window(),0,0,w.get_allocated_width(),w.get_allocated_height());pix.savev('/tmp/adws-clipboard-pinned.png','png',[],[])
 w.confirm_clear(w.clear_button);pump(.1)
 confirm_popup=Gtk.grab_get_current();assert isinstance(confirm_popup,Gtk.Popover)
 confirm_popup.get_child().get_children()[-1].get_children()[-1].clicked();pump(.3)
 assert w.records==[fixed],w.records
 w.toggle_pin(fixed);pump(.4)
 assert w.records==records
 pix=Gdk.pixbuf_get_from_window(w.get_window(),0,0,w.get_allocated_width(),w.get_allocated_height());pix.savev('/tmp/adws-clipboard-cards.png','png',[],[])
 w.search.set_text('not present');pump();assert w.stack.get_visible_child_name()=='empty'
 w.show_records([f'{i}\trecord {i}' for i in range(500)])
 w.search.set_text('');pump();assert len(w.listing.get_children())==80
 first=w.listing.get_children()[0]
 for count in (160,240,320,400,480,500):
  w.load_more();pump(.03);assert len(w.listing.get_children())==count
  assert w.listing.get_children()[0]==first
 assert not w.more_button.get_visible()
 target=w.listing.get_children()[100];w.listing.select_row(target)
 w.delete(target.record);pump()
 assert w.listing.get_selected_row().record=='101\trecord 101'
 w.search.set_text('record 499');pump();assert len(w.listing.get_children())==1
 w.search.set_text('');w.show_records(records);pump();w.delete(records[2]);pump()
 assert len(w.records)==2
 assert run.call_args.args[0]==['cliphist','delete']
 assert run.call_args.kwargs['input']==(records[2]+'\n').encode()
 # Hidden images must not be decoded; shutdown drops the thumbnail cache.
 w.show_records([f'{i}\t[[ binary data png ]]' for i in range(80)]);pump(.6)
 assert len(w.thumbnail_cache)<12
 w.show_records(records);pump(.2)
 w.search.set_text('akiacg');pump();w.copy_selected();pump(.7)
 copy.assert_called_once_with(records[1]);assert w.closed
 assert not w.thumbnail_cache and w.thumbnail_stop.is_set()
 # No initial load may survive closing before the first rendered frame.
 w=Clipboard(app);w.motion_settings=(True,240)
 with patch.object(w,'page_changed') as load:
  w.reveal();w.dismiss();pump(.7)
  assert w.closed and not w.popup_sources;load.assert_not_called()
 # Reopening during that fade must still populate the panel once.
 w=Clipboard(app);w.motion_settings=(True,240)
 with patch.object(w,'page_changed') as load:
  w.reveal();w.dismiss();w.closing=False;w.animate(True);pump(.7)
  load.assert_called_once();w.destroy();pump(.05)
print('CLIPBOARD: bounded cards, complete search, delete, exact copy, fade/close passed')

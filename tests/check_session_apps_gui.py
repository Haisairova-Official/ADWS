"""Right-click deletion and named confirmation, using disposable login entries."""
from pathlib import Path
import os
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import gi
gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0')
from gi.repository import Gtk,Gdk
import adws_session_apps as apps

class Host(Gtk.Window):
    accepted=False
    def confirm(self,title,message):
        self.last=(title,message)
        return self.accepted
    def error(self,error):
        raise AssertionError(error)

with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'XDG_CONFIG_HOME':temp,'XDG_CONFIG_DIRS':temp+'/system'}),patch.object(apps,'tr',side_effect=lambda text:text):
    directory=Path(temp)/'autostart';directory.mkdir()
    entry=directory/'music.desktop'
    entry.write_text('[Desktop Entry]\nType=Application\nName=Music <player> 音乐\nExec=true\n')
    host=Host();widget=apps.SessionApps(host);host.add(widget);host.show_all()
    while Gtk.events_pending():Gtk.main_iteration_do(False)
    receiver=widget.list.get_children()[0]
    name,title,enabled,data=apps.read_entries()[0]
    event=Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
    event.button=3;event.window=receiver.get_window();event.time=Gdk.CURRENT_TIME
    event.set_device(Gdk.Display.get_default().get_default_seat().get_pointer())
    assert receiver.emit('button-press-event',event)
    menu=widget.context_popup
    assert len(menu.get_children())==1
    menu.get_children()[0].activate()
    assert title in host.last[0] and title in host.last[1],host.last
    assert '确定要删除该启动项吗？' in host.last[1],host.last
    assert entry.exists(),'Cancel changed the entry'
    if widget.context_popup:widget.context_popup.popdown()
    host.accepted=True
    widget.delete_app(name,title,data)
    assert not entry.exists() and apps.read_entries()==[]
    assert '尚未配置登录应用。'==widget.list.get_children()[0].get_text()
    host.destroy()
print('PASS login-entry right-click, repeated literal name, cancellation and deletion')

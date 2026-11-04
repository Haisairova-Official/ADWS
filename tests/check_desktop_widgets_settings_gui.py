"""Exercise the desktop settings page without touching personal configuration."""
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import gi
gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0')
from gi.repository import Gtk, GLib
import adws_desktop_widgets_model as model
from adws_desktop_widgets_settings import DesktopWidgetsSettings

with tempfile.TemporaryDirectory(prefix='adws-widget-settings-') as folder:
    os.environ['XDG_CONFIG_HOME']=folder;os.environ['ADWS_PLUGIN_DIR']=str(Path(folder)/'plugins')
    window=Gtk.Window();page=DesktopWidgetsSettings(window);window.add(page);window.show_all()
    def settle():
        end=time.monotonic()+.2
        while time.monotonic()<end:
            while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
            time.sleep(.005)
    settle();page.choice.set_active_id('builtin:note');page.add();settle()
    rows=model.load()['instances'];assert len(rows)==1 and rows[0]['component']=='builtin:note'
    def widgets(parent):
        yield parent
        if isinstance(parent,Gtk.Container):
            for child in parent.get_children():yield from widgets(child)
    switches=[w for w in widgets(page) if isinstance(w,Gtk.Switch)]
    assert len(switches)==1 and switches[0].get_allocated_width()<100
    page.edit(rows[0]['instance'],x_percent=32.1,locked=True)
    assert model.load()['instances'][0]['x_percent']==32.1
    spins=[w for w in widgets(page) if isinstance(w,Gtk.SpinButton)]
    assert len(spins)==2, 'Position must be drag-only, not numeric input'
    scopes=[w for w in widgets(page.rows) if isinstance(w,Gtk.ComboBox)]
    assert len(scopes)==1 and len(scopes[0].get_model())==3
    scopes[0].set_active_id('all');settle()
    assert model.load()['instances'][0]['monitor_scope']=='all'
    page.edit(rows[0]['instance'],css='.adws-desktop-card { border-radius: 8px; }')
    page.duplicate(rows[0]['instance']);duplicates=model.load()['instances'];assert len(duplicates)==2
    assert duplicates[0]['css']==duplicates[1]['css']
    for row in duplicates:page.remove(row['instance'])
    assert not model.load()['instances']
    window.destroy();settle();assert page.health_source==0
print('PASS: desktop component add/edit/remove and switch geometry; isolated configuration only.')

# Package UI is shared; uninstalling a package does not erase either host's layout.
with tempfile.TemporaryDirectory(prefix='adws-package-manager-') as folder:
    import shutil
    from unittest.mock import patch
    from adws_plugin_manager import PluginManager,packages
    os.environ['XDG_CONFIG_HOME']=folder;os.environ['ADWS_PLUGIN_DIR']=str(Path(folder)/'plugins')
    installed=Path(folder)/'plugins/org.AkiACG_Community.NCMLyricsBar_1.2.0.mplg';installed.parent.mkdir()
    shutil.copy2(ROOT/'plugins'/installed.name,installed)
    sentinel=Path(folder)/'adws/taskbar-layout.json';sentinel.parent.mkdir();sentinel.write_text('preserved')
    window=Gtk.Window();page=PluginManager(window);window.add(page);window.show_all();settle()
    assert len(packages())==1 and packages()[0]['ok']
    with patch.object(Gtk.MessageDialog,'run',return_value=Gtk.ResponseType.CANCEL):page.uninstall(installed,'NCM')
    assert installed.exists()
    with patch.object(Gtk.MessageDialog,'run',return_value=Gtk.ResponseType.OK):page.uninstall(installed,'NCM')
    assert not installed.exists() and sentinel.read_text()=='preserved'
    window.destroy();settle()
print('PASS: package manager and duplicate instance settings are independent.')

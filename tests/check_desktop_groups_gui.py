"""Folder group settings and default-screen routing in an isolated GTK display."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,Gdk,GLib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT/'src/niri-desktop-layer'))
from adws_desktop_groups import Manager,Layer
from adws_desktop_groups_model import validate
Gtk.init([])

def children(widget):
    yield widget
    if isinstance(widget,Gtk.Container):
        for child in widget.get_children():yield from children(child)

def pump(condition):
    until=time.monotonic()+5
    while time.monotonic()<until:
        while Gtk.events_pending():Gtk.main_iteration()
        if condition():return
        time.sleep(.01)
    raise AssertionError('Timed out')

with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);os.environ['XDG_CONFIG_HOME']=str(root/'config');(root/'a.txt').write_text('fixture')
    application=SimpleNamespace(views=[],hidden=False,overview_active=False)
    manager=Manager(application,root/'groups.json',root,{})
    windows=[]
    try:
        for index in (1,2):
            window=Gtk.Window();window.set_default_size(800,600);window.monitor_key='screen-'+str(index);window.monitor_label='Screen '+str(index);window.monitor=Gdk.Display.get_default().get_monitor(0)
            window.area=Gtk.DrawingArea();window.overlay=Gtk.Overlay();window.overlay.add(window.area);window.add(window.overlay);window.show_all()
            windows.append(window);application.views.append(window)
        layers=[Layer(manager,w) for w in windows]
        pump(lambda:bool(layers[0].cards) and not manager.loading)
        assert len(layers[0].cards)==1 and not layers[1].cards
        def choose_default():
            dialog=next(w for w in Gtk.Window.list_toplevels() if isinstance(w,Gtk.Dialog) and w.get_visible())
            combo=next(w for w in children(dialog) if isinstance(w,Gtk.ComboBoxText));combo.set_active_id('screen-2');dialog.response(Gtk.ResponseType.OK);return False
        GLib.timeout_add(80,choose_default);manager.choose_default(windows[0])
        assert manager.data['default_monitor']=='screen-2'
        assert not layers[0].cards and len(layers[1].cards)==1
        def edit():
            dialog=next(w for w in Gtk.Window.list_toplevels() if isinstance(w,Gtk.Dialog) and w.get_visible())
            assert not dialog.get_resizable(),'Group settings would become a tiled window'
            assert dialog.get_transient_for() is None,'Editor still inherits a layer-surface parent'
            assert dialog.get_header_bar() is not None
            button=dialog.get_widget_for_response(Gtk.ResponseType.OK)
            assert button.get_mapped(),'Save button is hidden or inside scroll content'
            assert dialog.get_allocated_height()<=600
            image=Gdk.pixbuf_get_from_window(dialog.get_window(),0,0,dialog.get_allocated_width(),dialog.get_allocated_height())
            image.savev('/tmp/adws-group-editor.png','png',[],[])
            combos=[w for w in children(dialog) if isinstance(w,Gtk.ComboBox) and not isinstance(w,Gtk.FileChooserButton)]
            combos=[w for w in combos if w.get_active_id() in ('screen','primary','all','mica','acrylic','candy','cover','contain','stretch','center','tile')]
            assert len(combos)==3
            scope=next(w for w in combos if not isinstance(w,Gtk.ComboBoxText))
            assert [r[0] for r in scope.get_model()]==['screen','primary','all']
            assert scope.get_model()[1][2], 'Chosen default display must allow primary scope'
            for widget in combos:
                previous=widget.get_active_id()
                wheel=Gdk.Event.new(Gdk.EventType.SCROLL);wheel.direction=Gdk.ScrollDirection.DOWN;wheel.set_device(Gdk.Display.get_default().get_default_seat().get_pointer())
                assert widget.emit('scroll-event',wheel),'Wheel guard did not consume native combo changes'
                assert widget.get_active_id()==previous
            for widget in combos:
                if widget.get_active_id() in ('mica','acrylic','candy'):widget.set_active_id('candy')
                elif widget.get_active_id() in ('cover','contain','stretch','center','tile'):widget.set_active_id('tile')
                else:widget.set_active_id('all')
            scale=next(w for w in children(dialog) if isinstance(w,Gtk.Scale));scale.set_value(42)
            dialog.response(Gtk.ResponseType.OK);return False
        GLib.timeout_add(250,edit);manager.edit(windows[1],manager.data['groups'][0])
        assert manager.data['groups'][0]['material']=='candy'
        assert manager.data['groups'][0]['image_fit']=='tile'
        assert abs(manager.data['groups'][0]['opacity']-.42)<.0001
        validate(json.loads((root/'groups.json').read_text()))
        pump(lambda:not manager.loading)
        assert manager.data['groups'][0]['monitor']=='all'
        assert all(len(layer.cards)==1 for layer in layers),'All-screen group missing a replica'
        # Changing the state file in the watched parent must not rescan endlessly.
        original=manager.cache
        pump(lambda:not manager.pending)
        for _ in range(20):
            while Gtk.events_pending():Gtk.main_iteration()
            time.sleep(.02)
        assert manager.cache is original,'Own state writes triggered a rescan loop'
        palette=root/'config/waybar/colors.css';palette.parent.mkdir(parents=True,exist_ok=True)
        palette.write_text('@define-color surface #112233;\n@define-color on_surface #eeeeee;\n@define-color primary #99aaff;\n')
        pump(lambda:manager.palette.get('surface')=='#112233')
        cards=[layer.cards[0] for layer in layers];provider=manager.provider
        replacement=palette.with_suffix('.new');replacement.write_text('@define-color surface #332211;\n@define-color on_surface #eeeeee;\n@define-color primary #ffaa99;\n');replacement.replace(palette)
        pump(lambda:manager.palette.get('surface')=='#332211')
        assert provider is manager.provider and cards==[layer.cards[0] for layer in layers],'Theme change recreated live UI'
        print('PASS: palette update and atomic replacement reuse widgets; closed combos ignore wheel')
        print('PASS: default-screen routing, floating settings, material/opacity roundtrip, no state-file rescan loop')
    finally:
        manager.close()
        for window in windows:window.destroy()

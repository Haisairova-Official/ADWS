"""Isolated GTK: relative placement, monitor scopes and disabled primary choice."""
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'src/niri-desktop-layer')]
import gi
gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0')
from gi.repository import Gtk,Gdk
import adws_desktop_widgets_model as model
from adws_desktop_widgets import Manager,DesktopLayer

def pump():
    until=time.monotonic()+.25
    while time.monotonic()<until:
        while Gtk.events_pending():Gtk.main_iteration()
        time.sleep(.005)

def descendants(widget):
    yield widget
    if isinstance(widget,Gtk.Container):
        for child in widget.get_children():yield from descendants(child)

with tempfile.TemporaryDirectory(prefix='adws-relative-widgets-') as folder:
    root=Path(folder);os.environ['XDG_CONFIG_HOME']=str(root/'config');os.environ['ADWS_PLUGIN_DIR']=str(root/'plugins')
    path=root/'widgets.json';data=model.add({}, {'key':'builtin:clock'})
    row=data['instances'][0];row.update(monitor_scope='all',x_percent=50.,y_percent=-50.,width=320,height=200);model.save(data,path)
    app=SimpleNamespace(views=[],hidden=False,overview_active=False)
    manager=Manager(app,path);windows=[]
    try:
        for index,(width,height) in enumerate([(900,700),(1200,800)]):
            window=Gtk.Window();window.monitor_key='screen-'+str(index);window.connector_key=window.monitor_key
            window.monitor=Gdk.Display.get_default().get_monitor(0);window.clear_selection=lambda:None
            window.set_default_size(width,height);window.overlay=Gtk.Overlay();window.area=Gtk.DrawingArea();window.overlay.add(window.area);window.add(window.overlay)
            app.views.append(window);windows.append(window);window.show_all()
        layers=[DesktopLayer(manager,w) for w in windows];pump()
        def check_positions():
            for layer in layers:
                card=layer.cards[row['instance']];w,h=layer.window.area.get_allocated_width(),layer.window.area.get_allocated_height()
                expected=model.geometry(card.row,w,h)
                assert card.placed_geometry==expected,(card.placed_geometry,expected)
                assert tuple(card.box.translate_coordinates(layer.fixed,0,0))==expected[:2]
        check_positions();windows[1].resize(1400,900);pump();check_positions()
        # Global visibility is independent of icon visibility and instance enablement.
        before=path.read_bytes()
        for icons_hidden in (False,True):
            app.hidden=icons_hidden
            for visible in (False,True):
                manager.set_visible(visible);pump()
                assert app.hidden==icons_hidden
                assert all(layer.fixed.get_visible()==visible for layer in layers)
                app.overview_active=True
                for layer in layers:layer.visibility()
                assert all(not layer.fixed.get_visible() for layer in layers)
                app.overview_active=False
                for layer in layers:layer.visibility()
                assert all(layer.fixed.get_visible()==visible for layer in layers)
                manager.reload()
                assert app.widgets_hidden== (not visible)
                assert path.read_bytes()==before
        app.hidden=False
        card=layers[1].cards[row['instance']]
        button=next(w for w in descendants(card.box) if isinstance(w,Gtk.MenuButton));card.rebuild_menu(button)
        choices=button.get_popup().get_children()[:3]
        assert choices[0].get_sensitive() and not choices[1].get_sensitive() and choices[2].get_sensitive()
        choices[0].set_active(True);pump()
        assert not layers[0].cards and len(layers[1].cards)==1
        saved=model.load(path)['instances'][0];assert saved['monitor']=='screen-1' and saved['monitor_scope']=='screen'
        card=layers[1].cards[row['instance']];card.rebuild_menu(button);button.get_popup().get_children()[2].set_active(True);pump()
        assert all(len(layer.cards)==1 for layer in layers)
        card=layers[0].cards[row['instance']];button=next(w for w in descendants(card.box) if isinstance(w,Gtk.MenuButton));card.rebuild_menu(button)
        assert button.get_popup().get_children()[1].get_sensitive()
        button.get_popup().get_children()[1].set_active(True);pump()
        assert len(layers[0].cards)==1 and not layers[1].cards
        # Mirroring plugin UI must share one runner and its event channel.
        from unittest.mock import Mock
        fixture={'key':'org.adws.mirror','kind':'plugin','name':'Mirror fixture','file':'/fixture.mplg','manifest':{'id':'org.adws.mirror','renderer':'panel.rows-v1','version':'1.0.0'}}
        data=model.add({},fixture);data['instances'][0]['monitor_scope']='all';model.save(data,path)
        source=Mock();source.take.side_effect=[{'primary':'shared state'}]+[None]*1000
        with patch('adws_desktop_plugin.PluginStream',return_value=source) as start,patch.object(model,'catalog',return_value=[fixture]):
            manager.reload();pump()
            assert start.call_count==1,start.call_count
            assert all(next(iter(layer.cards.values())).primary.get_text()=='shared state' for layer in layers)
            layers[0].fixed.hide();pump();source.close.assert_not_called()
            layers[1].fixed.hide();pump();source.close.assert_called_once()
            assert not manager.streams
        print('PASS: two screen sizes share relative placement; resize preserves it; scope changes and disabled primary option work')
    finally:
        manager.close()
        for window in windows:window.destroy()

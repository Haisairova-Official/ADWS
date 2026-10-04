"""Real GTK component operations, isolated from live configuration and launchers."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_layout_gui as gui
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk


def settle():
    for _ in range(10):
        while Gtk.events_pending(): Gtk.main_iteration_do(False)


manifest = json.loads((Path(__file__).resolve().parents[1] / 'plugins/netease-lyrics/plugin.json').read_text())
package = {'ok':True, 'manifest':manifest, 'file':Path('/tmp/example.mplg')}
with tempfile.TemporaryDirectory() as directory, patch.object(gui, 'scan_available_plugins', return_value=[package]):
    path = Path(directory)/'layout.json'
    path.write_text(json.dumps({'apiVersion':2,'builtins':[{'id':'start','instance':'start','slot':'left'}, {'id':'clock','instance':'clock','slot':'right'}], 'plugins':[{'package':manifest['id'],'enabled':False,'settings':{'primary_color':'#123456'}}], 'options':{'start_label':'First','start_launcher_mode':'adws'}}))
    host = Gtk.Window()
    host.get_style_context().add_class('adws-system-settings')
    host.set_default_size(960,760)
    app = gui.LayoutWindow(str(path), parent=host)
    host.add(app.content)
    from adws_settings_style import SettingsStyle
    from types import SimpleNamespace
    host.config = SimpleNamespace(live_style_path=gui.adws_layout.live_style_path, read_colors=lambda path: {}, resolve_color=lambda value, colors: value)
    style = SettingsStyle(host)
    notifications = []
    app.on_changed = lambda: notifications.append(1)
    app.add_component('builtin','start')
    starts = [row for row in app.rows if row['key'] == 'start']
    assert len(starts) == 2
    second = starts[1]
    second_id = second['instance']
    app.configure_entry(second)
    assert app.start_instance == second_id
    app.start_label.set_text('Second')
    app.launcher_mode.set_active_id('custom')
    app.launcher_command.set_text('my-launcher --independent')
    app.start_right_mode.set_active_id('custom')
    app.start_right_custom.set_text('fixture-right --second')
    app.start_instance_choice.set_active_id('start')
    assert app.start_label.get_text() == 'First'
    assert app.start_right_mode.get_active_id() == 'settings'
    app.start_right_mode.set_active_id('terminal')
    app.start_label.set_text('First changed')
    second['widgets']['slot'].set_active_id('right')
    app.add_component('builtin','clock')
    app.add_component('plugin',manifest['id'])
    plugin = next(row for row in app.rows if row['kind'] == 'plugin')
    assert plugin['settings']['primary_color'] == '#123456'
    assert app.remove_entry(plugin)
    assert package['file'] == Path('/tmp/example.mplg')
    app.add_component('plugin',manifest['id'])
    windows = next(row for row in app.rows if row['key'] == 'windows')
    assert not app.remove_entry(windows)
    assert not windows['widgets']['switch'].get_sensitive()
    for key in ('windows',):
        try: app.add_component('builtin',key)
        except ValueError: pass
        else: raise AssertionError('A required singleton was duplicated')
    saved = app.collect_layout()
    assert saved['options']['start_label'] == 'First changed'
    assert saved['options']['start_right_mode'] == 'terminal'
    second_saved = next(item for item in saved['builtins'] if item['instance'] == second_id)
    assert second_saved['options']['start_label'] == 'Second'
    assert second_saved['options']['start_right_mode'] == 'custom'
    assert second_saved['options']['start_right_custom'] == 'fixture-right --second'
    assert second_saved['options']['start_launcher_command'] == 'my-launcher --independent'
    path.write_text(json.dumps(saved))
    app.reload()
    for _ in range(3):
        for row in app.rows: app.select_entry(row)
        app.collect_layout()
        app.reload(app.collect_layout())
    assert app.collect_layout() == saved
    second = next(row for row in app.rows if row.get('instance') == second_id)
    assert second['slot'] == 'right'
    app.select_entry(second)
    host.show_all()
    settle()
    assert second['box'].get_parent() == app.sections['right']
    assert second['widgets']['slot']._adws_choice_button.get_visible()
    shot = Gdk.pixbuf_get_from_window(host.get_window(),0,0,host.get_allocated_width(),host.get_allocated_height())
    shot.savev('/tmp/adws-components-layout.png','png',[],[])
    # Preview consumes unsaved changes without running or restarting components.
    app.start_instance_choice.set_active_id(second_id)
    app.start_label.set_text('Live draft')
    settle()
    assert next(row for row in app.preview.rows if row['instance'] == second_id)['text'] == 'Live draft'
    second['widgets']['slot'].set_active_id('center')
    settle()
    assert next(row for row in app.preview.rows if row['instance'] == second_id)['slot'] == 'center'
    app.get_preview_options = lambda: {'position':'left','thickness':60,'surface_color':'#123456'}
    app.schedule_preview();settle()
    assert app.preview.options['thickness'] == 60
    assert app.preview.get_size_request()[1] == 250
    app.get_preview_options = None
    app.schedule_preview();settle()
    assert app.preview.get_size_request()[1] == 112
    rect,identity = next(hit for hit in app.preview.hits if hit[1] == second_id)
    app.select_preview_component(identity)
    assert app.selected_entry is second
    # All section cards are horizontal; drag moves preserve identity/settings.
    assert all(section.get_orientation()==Gtk.Orientation.HORIZONTAL for section in app.sections.values())
    assert app.drag_move(second_id,'center')
    assert second['widgets']['slot'].get_active_id()=='center'
    assert app.drag_move(second_id,'right','clock',False)
    right=[r['instance'] for r in app.rows if r['slot']=='right']
    assert right.index(second_id)<right.index('clock')
    app.schedule_preview();settle()
    rect,identity=next(hit for hit in app.preview.hits if hit[1]==second_id)
    rx,ry,rw,rh=rect
    assert app.preview.drop_location(rx+rw*.25,ry+rh*.5)==('right',second_id,False)
    assert app.preview.drop_location(rx+rw*.75,ry+rh*.5)==('right',second_id,True)
    # Test fixtures must never run a real component process or alter user services.
    # Remove all optional components; save/open must not reconstruct them.
    for row in list(app.rows):
        if row['key'] != 'windows': app.remove_entry(row)
    path.write_text(json.dumps(app.collect_layout()))
    app.reload()
    assert len(app.rows) == 1 and app.rows[0]['key'] == 'windows'
    assert notifications
    host.destroy()
    style.close()
print('Component instances, settings, catalog limits, removal and repeated save/open passed.')

# Repeatable plugins retain independent settings and selection identities.
with tempfile.TemporaryDirectory() as directory, patch.object(gui, 'scan_available_plugins', return_value=[package]):
    path=Path(directory)/'layout.json'
    path.write_text(json.dumps({'apiVersion':2,'builtins':[],'plugins':[],'options':{}}))
    host=Gtk.Window();app=gui.LayoutWindow(str(path),parent=host);host.add(app.content);host.show_all()
    app.add_component('plugin',manifest['id']);first=next(row for row in app.rows if row['kind']=='plugin');first['settings']={'primary_color':'#123456'}
    app.add_component('plugin',manifest['id']);rows=[row for row in app.rows if row['kind']=='plugin'];assert len(rows)==2
    assert len({row['instance'] for row in rows})==2
    second=next(row for row in rows if row['instance']!=first['instance']);second['settings']={'primary_color':'#654321'}
    state=app.collect_layout();assert len(state['plugins'])==2
    app.reload(state);rows=[row for row in app.rows if row['kind']=='plugin'];assert {row['settings']['primary_color'] for row in rows}=={'#123456','#654321'}
    selected=[];app.on_plugin_settings=lambda row:selected.append(row['instance'])
    app.open_plugin_settings(manifest['id']+'#'+second['instance']);assert selected==[second['instance']]
    app.remove_entry(next(row for row in rows if row['instance']==first['instance']))
    assert len([row for row in app.rows if row['kind']=='plugin'])==1
    assert next(row for row in app.rows if row['kind']=='plugin')['instance']==second['instance']
    app.add_component('plugin',manifest['id']);assert len([row for row in app.rows if row['kind']=='plugin'])==2
    package['manifest']['isSingleOnly']=True
    app.refresh_catalog();buttons=[button for button,name in app.catalog_buttons if name==package['manifest']['name']]
    assert buttons and not buttons[0].get_sensitive()
    app.close_preview();host.destroy();settle();package['manifest'].pop('isSingleOnly')
print('PASS plugin instances, removal/restore and singleton catalog')

"""Isolated settings warning-state regression; no live plugins are started."""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_layout_gui as gui
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk
manifest=json.loads((Path(__file__).resolve().parents[1]/'plugins/netease-lyrics/plugin.json').read_text())
package={'ok':True,'manifest':manifest,'file':Path('/tmp/fixture.mplg')}
with tempfile.TemporaryDirectory() as directory, patch.object(gui,'scan_available_plugins',return_value=[package]):
    path=Path(directory)/'layout.json'
    path.write_text(json.dumps({'plugins':[{'package':manifest['id'],'instance':'first','enabled':True},
                                          {'package':manifest['id'],'instance':'second','enabled':True}]}))
    editor=gui.LayoutWindow(str(path))
    rows=[row for row in editor.rows if row['kind']=='plugin']
    with patch('adws_plugin_watchdog.health',side_effect=lambda identity: {'state':'failed','reason':'fixture crash'} if identity=='first' else {'state':'running'}):
        editor.refresh_plugin_health()
    first=next(r for r in rows if r['instance']=='first'); second=next(r for r in rows if r['instance']=='second')
    assert first['health_badge'].get_visible()
    assert first['box'].get_style_context().has_class('plugin-failed')
    assert 'fixture crash' in first['box'].get_tooltip_text()
    assert not second['health_badge'].get_visible()
    with patch('adws_plugin_watchdog.health',return_value={'state':'running'}):editor.refresh_plugin_health()
    assert not first['health_badge'].get_visible()
    assert not first['box'].get_style_context().has_class('plugin-failed')
    editor.window.destroy()
    assert editor.closed and editor.health_source==0
print('plugin warning badge: crash / instance isolation / recovery / cleanup passed')

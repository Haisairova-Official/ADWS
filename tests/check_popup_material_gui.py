"""Quick controls share panel material and radius; never access device services."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import gi
gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0')
from gi.repository import Gtk,Gdk
import adws_layout as layout
from adws_settings_style import PanelStyle
from adws_panel_options import validate,material_css

with tempfile.TemporaryDirectory() as temp:
    root=Path(temp);stylefile=root/'style-bottom.css';stylefile.write_text('')
    palette=root/'colors.css';palette.write_text('@define-color primary #aa88ff;')
    path=root/'layout.json'
    host=Gtk.Window();host.get_style_context().add_class('adws-system-settings');host.get_style_context().add_class('adws-quick-panel')
    host.add(Gtk.Label(label='Quick controls'))
    host.config=SimpleNamespace(live_style_path=lambda:stylefile,
        read_colors=lambda path:{'primary':'#aa88ff','surface_container_high':'#202030'},
        resolve_color=lambda value,colors:value,
        read_taskbar_overrides=lambda:(False,(.2,.3,.4,1.),19,'Sans',14))
    with patch.object(layout,'USER_LAYOUT_PATH',path):
        for material,alpha in [('solid',1.),('mica',.90),('acrylic',.66),('candy',.82)]:
            path.write_text(json.dumps({'apiVersion':2,'builtins':[],'plugins':[],'options':{'panel_material':material}}))
            theme=PanelStyle(host);host.show_all()
            while Gtk.events_pending():Gtk.main_iteration_do(False)
            options=validate({'panel_material':material})
            css=theme.stylesheet({k:'#202030' for k in ('raised','accent','text')},options)
            assert material_css(options,'rgb(51,77,102)') in css
            assert 'border-radius: 19px;' in css
            actual=host.get_style_context().get_background_color(Gtk.StateFlags.NORMAL)
            assert abs(actual.alpha-alpha)<.02,(material,actual.alpha,alpha)
            theme.close()
        host.destroy()
print('PASS all four quick-control materials, custom base and radius')

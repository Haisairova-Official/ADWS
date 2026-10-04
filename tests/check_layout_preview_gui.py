"""Paint real snapshot content in all orientations without running its apps/plugins."""
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import cairo
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk
from adws_layout_preview import create_preview
from adws_layout import default_layout

live={'windows':[{'id':1,'app_id':'firefox','workspace_id':3,'is_focused':True}],
      'workspaces':[{'id':3,'idx':1,'is_active':True}],
      'tray':[{'icons':['firefox']}]*4,
      'plugins':{'lyrics':{'primary':'原文 test 歌词','secondary':'translation','class':'playing'}},
      'sound':{'icon':'audio-volume-high-symbolic'}}
with patch('adws_layout_live.read_snapshot',return_value=live):
    host=Gtk.Window();host.set_default_size(1000,420)
    preview=create_preview(lambda *_:None)
    host.add(preview);host.show_all()
    while Gtk.events_pending():Gtk.main_iteration_do(False)
    preview.live=live
    rows=[{**r,'key':r['id'],'name':r['id']} for r in default_layout()['builtins']]
    rows.append({'key':'test.lyrics','instance':'lyrics','slot':'center','name':'Lyrics',
                 'settings':{'primary_color':'#ffaaaa','secondary_color':'#aaaaff','separator_color':'#55aa55'}})
    for position in ('bottom','top','left','right'):
        preview.update(rows,{'position':position,'split_panel':True,'split_center_corners':'pointed','thickness':36})
        surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,1000,420)
        preview.draw_preview(None,cairo.Context(surface))
        assert len(preview.hits)==7
        assert next(r for r in preview.rows if r['instance']=='lyrics')['text']=='原文 test 歌词\ntranslation'
        if position=='bottom':surface.write_to_png('/tmp/adws-preview-snapshot.png')
    host.destroy()
print('PASS live windows, overflowing tray and bilingual plugin preview in four directions')

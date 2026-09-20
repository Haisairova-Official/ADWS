"""Run under Xvfb: geometry, colors and page transitions without live writes."""
from pathlib import Path
import sys, importlib.util, time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('settings',ROOT/'tools/mnws-config.py')
settings=importlib.util.module_from_spec(spec);spec.loader.exec_module(settings)
Gtk=settings.Gtk

def settle():
    for _ in range(30):
        while Gtk.events_pending():Gtk.main_iteration()
        time.sleep(.005)

with patch('mnws_layout.load_layout',return_value={'options':{'tab_animations':True},'plugins':[],'builtins':[]}):
    pages=settings.AnimatedPages()
    for name in ['Appearance','Components','About']:pages.append_page(Gtk.Label(label=name),Gtk.Label(label=name))
    assert pages.stack.get_transition_type()==Gtk.StackTransitionType.CROSSFADE
    pages.set_current_page(2)
    assert pages.get_current_page()==2
    window=settings.TaskbarStyleWindow()
    window.disconnect_by_func(Gtk.main_quit)
    settle()
    window.window_rows.set_active_id('2')
    assert window.thickness.get_value()>=48
    window.thickness.set_value(64)
    window.position.set_active_id('right')
    window.panel_toggles['window_animations'].set_active(True)
    color,follow=window.panel_colors['hover_color']
    follow.set_active(False)
    rgba=settings.Gdk.RGBA();rgba.parse('#ff0088');color.set_rgba(rgba)
    with patch.object(settings,'write_taskbar_overrides'),patch.object(settings,'write_taskbar_font'),patch('mnws_layout.apply_layout',return_value=(True,'')) as apply,patch('mnws_layout.save_layout') as save:
        assert window.apply_style()
        options=apply.call_args.args[0]['options']
        assert options['position']=='right' and options['window_rows']==2 and options['thickness']==64
        assert options['group_windows'] and options['window_animations']
        assert options['hover_color']=='#ff0088'
        assert save.call_args.args[0]['options']==options
    settle()
    import cairo
    surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,window.get_allocated_width(),window.get_allocated_height())
    window.draw(cairo.Context(surface));surface.write_to_png('/tmp/mnws130-settings.png')
    window.destroy()
print('Panel geometry, color persistence and settings crossfade checks passed.')

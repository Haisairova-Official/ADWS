"""Run under Xvfb: geometry, colors and page transitions without live writes."""
from pathlib import Path
import sys, importlib.util, time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('settings',ROOT/'tools/adws-config.py')
settings=importlib.util.module_from_spec(spec);spec.loader.exec_module(settings)
Gtk=settings.Gtk

def settle():
    for _ in range(80):
        while Gtk.events_pending():Gtk.main_iteration()
        time.sleep(.005)

with patch('adws_layout.load_layout',return_value={'options':{'tab_animations':True},'plugins':[],'builtins':[]}):
    pages=settings.AnimatedPages()
    for name in ['Appearance','Components','About']:pages.append_page(Gtk.Label(label=name),Gtk.Label(label=name))
    assert pages.stack.get_transition_type()==Gtk.StackTransitionType.CROSSFADE
    pages.set_current_page(2)
    assert pages.get_current_page()==2
    window=settings.TaskbarStyleWindow()
    window.disconnect_by_func(settings.on_settings_window_destroy)
    settle()
    # Wheel over each setting scrolls the page, with focused controls included.
    Gdk=settings.Gdk
    scroller=window.thickness.get_ancestor(Gtk.ScrolledWindow)
    adjustment=scroller.get_vadjustment()
    for control, read in [(window.position,lambda:window.position.get_active_id()),
                          (window.window_rows,lambda:window.window_rows.get_active_id()),
                          (window.family,lambda:window.family.get_active_text()),
                          (window.thickness,lambda:window.thickness.get_value()),
                          (window.animation_duration,lambda:window.animation_duration.get_value()),
                          (window.radius,lambda:window.radius.get_value()),
                          (window.font_size,lambda:window.font_size.get_value())]:
        control.grab_focus()
        for direction in [Gdk.ScrollDirection.DOWN,Gdk.ScrollDirection.UP,Gdk.ScrollDirection.SMOOTH]:
            adjustment.set_value((adjustment.get_upper()-adjustment.get_page_size())/2)
            before=read(); position=adjustment.get_value()
            event=Gdk.Event.new(Gdk.EventType.SCROLL)
            event.scroll.direction=direction
            event.scroll.delta_y=1.0
            event.scroll.window=control.get_window()
            event.set_device(Gdk.Display.get_default().get_default_seat().get_pointer())
            assert control.emit('scroll-event',event)
            settle()
            assert read()==before, 'Wheel changed a setting value'
            assert adjustment.get_value()!=position, 'Wheel did not scroll the page'
    window.window_rows.set_active_id('2')
    assert window.thickness.get_value()>=48
    window.thickness.set_value(64)
    window.position.set_active_id('right')
    assert window.notebook.count == 2
    assert window.layout_editor.window is window
    window.notebook.set_current_page(1)
    window.layout_editor.start_mode.set_active_id('custom')
    window.layout_editor.start_label.set_text('Unified Start')
    window.layout_editor.launcher_mode.set_active_id('custom')
    window.layout_editor.launcher_command.set_text('fuzzel --show-actions')
    window.notebook.set_current_page(0)
    assert window.position.get_active_id() == 'right'
    window.panel_toggles['window_animations'].set_active(True)
    color,follow=window.panel_colors['hover_color']
    follow.set_active(False)
    rgba=settings.Gdk.RGBA();rgba.parse('#ff0088');color.set_rgba(rgba)
    with patch.object(settings,'write_taskbar_overrides'),patch.object(settings,'write_taskbar_font'),patch('adws_layout.apply_layout',return_value=(True,'')) as apply,patch('adws_layout.save_layout') as save:
        assert window.apply_style()
        options=apply.call_args.args[0]['options']
        assert options['position']=='right' and options['window_rows']==2 and options['thickness']==64
        assert options['group_windows'] and options['window_animations']
        assert options['hover_color']=='#ff0088'
        assert options['start_label']=='Unified Start'
        assert options['start_launcher_command']=='fuzzel --show-actions'
        assert apply.call_count == 1
        assert save.call_args.args[0]['options']==options
    adjustment.set_value(0)
    settle()
    import cairo
    surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,window.get_allocated_width(),window.get_allocated_height())
    window.draw(cairo.Context(surface));surface.write_to_png('/tmp/adws130-settings.png')
    window.notebook.set_current_page(1);settle()
    surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,window.get_allocated_width(),window.get_allocated_height())
    window.draw(cairo.Context(surface));surface.write_to_png('/tmp/adws-unified-layout.png')
    # Invalid layout is rejected before either page writes any settings.
    window.layout_editor.start_mode.set_active_id('image')
    window.layout_editor.start_images['start_image'].set_text('/definitely-missing-adws-image.png')
    with patch.object(settings,'write_taskbar_overrides') as write, patch('adws_layout.apply_layout') as apply, patch.object(window,'show_error') as error:
        assert not window.apply_style()
        assert error.called and not write.called and not apply.called
    window.destroy()
print('Panel geometry, color persistence and settings crossfade checks passed.')

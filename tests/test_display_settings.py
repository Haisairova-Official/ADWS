import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('display', Path(__file__).resolve().parents[1] / 'tools/adws_display.py')
display = importlib.util.module_from_spec(spec)
spec.loader.exec_module(display)

class DisplaySettingsTests(unittest.TestCase):
    def setUp(self):
        self.output = dict(name='DP-1', mode='1920x1080@60.000', modes=['1920x1080@60.000'], scale=1.25, x=-1920, y=0, transform=0)

    def test_actual_session_overrides_inherited_socket(self):
        env = dict(XDG_CURRENT_DESKTOP='Hyprland', NIRI_SOCKET='stale', HYPRLAND_INSTANCE_SIGNATURE='active')
        self.assertEqual(display.detect_session(env), 'hyprland')
        env['XDG_CURRENT_DESKTOP'] = 'niri'
        self.assertEqual(display.detect_session(env), 'niri')
        self.assertIsNone(display.detect_session({}))

    def test_niri_serialized_transform(self):
        raw = {'DP-1': dict(make='Test', model='Display', modes=[dict(width=1920,height=1080,refresh_rate=60000)], current_mode=0, logical=dict(x=0,y=0,scale=1.25,transform='Normal'))}
        with patch.object(display, 'run', return_value=json.dumps(raw)):
            self.assertEqual(display.outputs('niri')[0]['transform'], 0)
            raw['DP-1']['logical']['transform']='Flipped90'
        with patch.object(display, 'run', return_value=json.dumps(raw)):
            self.assertEqual(display.outputs('niri')[0]['transform'], 5)

    def test_hyprland_modes(self):
        raw = [dict(name='DP-1',width=1920,height=1080,refreshRate=60,scale=1,x=0,y=0,availableModes=['1920x1080@60.00Hz'])]
        with patch.object(display, 'run', return_value=json.dumps(raw)):
            value = display.outputs('hyprland')[0]
            self.assertIn(value['mode'],value['modes'])
            self.assertTrue(all('Hz' not in mode for mode in value['modes']))

    def test_validation_prevents_monitor_command_injection(self):
        for field, value in [('name','DP-1,disable'),('mode','auto;bad'),('scale',float('nan')),('x',40000),('transform',8)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                display.validate(dict(self.output,**{field:value}))

    def test_partial_failure_restores_original(self):
        new = dict(self.output,scale=2)
        with patch.object(display,'apply',side_effect=[RuntimeError('failed'),None]) as apply:
            with self.assertRaises(RuntimeError):
                display.preview('niri',self.output,new)
            self.assertEqual(apply.call_args_list[1].args,('niri',self.output))

    def test_unavailable_modes_not_applied(self):
        with patch.object(display,'apply') as apply:
            with self.assertRaises(ValueError):
                display.preview('niri',self.output,dict(self.output,mode='800x600@60.000'))
            apply.assert_not_called()

    def test_negative_position_is_separate_argv(self):
        with patch.object(display,'run') as run:
            display.apply('niri',self.output)
            self.assertEqual(run.call_args.args[0][-4:],['set','--','-1920','0'])



class MultiMonitorLayoutTests(unittest.TestCase):
    def setUp(self):
        self.left = dict(name='DP-1', mode='2560x1440@144.000', modes=['2560x1440@144.000', '1920x1080@60.000'], scale=1.25, x=0, y=0, transform=0)
        self.right = dict(name='HDMI-A-1', mode='1920x1080@60.000', modes=['1920x1080@60.000'], scale=1, x=2048, y=0, transform=1)

    def test_scaled_and_portrait_monitors_use_logical_coordinates(self):
        self.assertEqual(display.logical_size(self.left), (2048,1152))
        self.assertEqual(display.logical_size(self.right), (1080,1920))
        self.assertEqual(display.layout_bounds([self.left,self.right]),(0,0,3128,1920))
        self.assertEqual(display.logical_size(dict(self.right,transform=5)),(1080,1920))

    def test_snap_edges_but_preserve_distant_placement(self):
        self.assertEqual(display.snapped_position(self.right,[self.left],2037,10,24),(2048,0))
        self.assertEqual(display.snapped_position(self.right,[self.left],2200,100,24),(2200,100))
        self.assertEqual(display.snapped_position(self.right,[self.left],-1070,-7,24),(-1080,0))
        self.assertEqual(display.snapped_position(self.right,[self.left],70000,-70000,24),(32768,-32768))

    def test_batch_validates_every_output_before_any_mutation(self):
        broken = dict(self.right,mode='800x600@60.000')
        with patch.object(display,'apply') as apply:
            with self.assertRaises(ValueError):
                display.preview_all('niri',[self.left,self.right],[dict(self.left,scale=2),broken])
            apply.assert_not_called()

    def test_partial_second_monitor_failure_restores_both_in_reverse_order(self):
        changed = [dict(self.left,scale=2),dict(self.right,x=1280)]
        with patch.object(display,'apply',side_effect=[None,RuntimeError('disconnected'),None,None]) as apply:
            with self.assertRaisesRegex(RuntimeError,'disconnected'):
                display.preview_all('niri',[self.left,self.right],changed)
            self.assertEqual([call.args[1] for call in apply.call_args_list],[*changed,self.right,self.left])

    def test_restore_continues_after_an_output_fails(self):
        with patch.object(display,'apply',side_effect=[RuntimeError('removed'),None]) as apply:
            with self.assertRaisesRegex(RuntimeError,'HDMI-A-1'):
                display.restore_all('niri',[self.left,self.right])
            self.assertEqual(apply.call_count,2)

    def test_unchanged_monitor_is_not_reconfigured(self):
        with patch.object(display,'apply') as apply:
            touched = display.preview_all('hyprland',[self.left,self.right],[self.left,dict(self.right,x=0)])
            self.assertEqual(touched,[self.right])
            self.assertEqual(apply.call_count,1)

    def test_hotplug_and_duplicate_names_rejected(self):
        for values in ([self.left], [self.left,self.left]):
            with patch.object(display,'apply') as apply:
                with self.assertRaises(ValueError):
                    display.preview_all('niri',[self.left,self.right],values)
                apply.assert_not_called()

    def test_mode_precision_does_not_create_false_external_change(self):
        self.assertTrue(display.same_settings(self.right,dict(self.right,mode='1920x1080@60.00')))


# GUI interaction tests run under Xvfb; ordinary unit-test runs need no display.
import os
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'tools'))
try:
    import gi
    gi.require_version('Gtk','3.0')
    from gi.repository import Gtk, Gdk
    gui_available = Gtk.init_check()[0]
except (ImportError,ValueError):
    gui_available = False


@unittest.skipUnless(gui_available, 'GTK display required')
class MonitorCanvasInteractionTests(unittest.TestCase):
    def setUp(self):
        from adws_display_gui import DisplaySettingsPage
        self.left = dict(name='DP-1',description='Main',mode='2560x1440@144.000',modes=['2560x1440@144.000','1920x1080@60.000'],scale=1.25,x=0,y=0,transform=0)
        self.right = dict(name='HDMI-A-1',description='Portrait',mode='1920x1080@60.000',modes=['1920x1080@60.000'],scale=1,x=2048,y=0,transform=1)
        self.host = Gtk.Window()
        self.host.busy,self.host.closed,self.host.display_session,self.host.dirty = False,False,'niri',set()
        self.host.mark_dirty = lambda key:self.host.dirty.add(key)
        self.host.update_footer = lambda:None
        self.host.confirm = lambda *args:True
        self.host.run_worker = lambda job,done:None  # No compositor or session calls.
        self.page = DisplaySettingsPage(self.host)
        self.page.set_outputs([self.left,self.right])
        self.host.add(self.page);self.host.set_default_size(1000,800);self.host.show_all()
        while Gtk.events_pending():Gtk.main_iteration_do(False)

    def tearDown(self):
        self.host.destroy()

    def test_monitor_selection_keeps_pending_values(self):
        self.page.scale.set_value(150)
        self.page.select_monitor('HDMI-A-1')
        self.page.x.set_value(1700)
        self.page.select_monitor('DP-1')
        self.assertEqual(self.page.scale.get_value(),150)
        self.assertEqual(self.page.pending[1]['x'],1700)
        self.assertEqual(self.page.original[1]['x'],2048)
        self.assertIn('displays',self.host.dirty)

    def test_drag_snaps_without_moving_other_monitor(self):
        from types import SimpleNamespace
        canvas = self.page.canvas
        canvas.fit()
        x,y,width,height = canvas.rectangle(self.page.pending[1])
        start_x,start_y = x+width/2,y+height/2
        canvas.press(canvas,SimpleNamespace(button=1,x=start_x,y=start_y))
        viewport = canvas.viewport
        canvas.motion(canvas,SimpleNamespace(x=start_x+8*viewport[0],y=start_y+5*viewport[0]))
        self.assertEqual((self.page.pending[1]['x'],self.page.pending[1]['y']),(2048,0))
        self.assertEqual(canvas.viewport,viewport)
        canvas.motion(canvas,SimpleNamespace(x=start_x+300*viewport[0],y=start_y+300*viewport[0]))
        self.assertEqual((self.page.pending[1]['x'],self.page.pending[1]['y']),(2348,300))
        self.assertEqual(self.page.pending[0],self.left)
        canvas.release(canvas,SimpleNamespace(button=1))
        self.assertIsNone(canvas.drag)
        self.assertTrue(self.page.has_pending())

    def test_rotation_changes_canvas_size_and_reset_restores_layout(self):
        self.page.rotation_changed(None,1)
        self.assertEqual(display.logical_size(self.page.pending[0]),(1152,2048))
        self.page.discard_changes()
        self.assertEqual(self.page.pending,[self.left,self.right])
        self.assertNotIn('displays',self.host.dirty)

    def test_cancelled_preview_restores_every_touched_monitor(self):
        import adws_display_gui as gui
        from unittest.mock import MagicMock
        changed = [dict(self.left,scale=2),dict(self.right,x=1280)]
        self.host.run_worker = lambda job,done: (job(),done())
        dialog = MagicMock()
        dialog.run.return_value = Gtk.ResponseType.CANCEL
        with patch.object(gui.Gtk,'MessageDialog',return_value=dialog), patch.object(gui.backend,'restore_all') as restore:
            self.page.ask_keep([self.left,self.right],changed,[self.left,self.right])
            restore.assert_called_once_with('niri',[self.left,self.right])
            self.assertEqual(self.page.pending,[self.left,self.right])
            self.assertFalse(self.host.busy)
            self.assertEqual(self.page.preview_timer,0)

    def test_preview_timeout_uses_monotonic_deadline(self):
        import adws_display_gui as gui
        from unittest.mock import MagicMock
        dialog = MagicMock()
        def run_dialog():
            callback = timer.call_args.args[1]
            self.assertFalse(callback())
            return Gtk.ResponseType.CANCEL
        dialog.run.side_effect = run_dialog
        self.host.run_worker = lambda job,done: (job(),done())
        with patch.object(gui.Gtk,'MessageDialog',return_value=dialog), patch.object(gui.GLib,'timeout_add',return_value=7) as timer, patch.object(gui.time,'monotonic',side_effect=[10,10,25.1]), patch.object(gui.backend,'restore_all') as restore:
            self.page.ask_keep([self.left,self.right],[dict(self.left,scale=2),self.right],[self.left])
            dialog.response.assert_called_once_with(Gtk.ResponseType.CANCEL)
            restore.assert_called_once_with('niri',[self.left])

    def test_external_monitor_change_blocks_stale_preview(self):
        import adws_display_gui as gui
        self.page.x.set_value(10)
        self.host.run_worker = lambda job,done:(job(),done())
        with patch.object(gui.backend,'outputs',return_value=[dict(self.left,scale=2),self.right]), patch.object(gui.backend,'preview_all') as preview:
            with self.assertRaises(RuntimeError):
                self.page.test_changes()
            preview.assert_not_called()

    def test_editable_scale_presets_and_custom_percentage(self):
        self.assertIsInstance(self.page.scale, Gtk.ComboBoxText)
        self.page.scale.get_child().set_text('137.5%')
        self.assertAlmostEqual(self.page.pending[0]['scale'], 1.375)
        self.page.scale.set_active_id('150')
        self.assertEqual(self.page.pending[0]['scale'], 1.5)
        self.assertIn('displays', self.host.dirty)

    def test_refresh_input_only_selects_modes_for_current_resolution(self):
        self.assertEqual(self.page.refresh_rate.presets, [144])
        self.page.resolution_changed(None, 1920, 1080)
        self.assertEqual(self.page.refresh_rate.presets, [60])
        self.page.refresh_rate.get_child().set_text('60 Hz')
        self.assertEqual(self.page.pending[0]['mode'], '1920x1080@60.000')
        self.page.refresh_rate.get_child().set_text('144')
        self.assertTrue(self.page.refresh_rate.invalid)
        self.assertEqual(self.page.pending[0]['mode'], '1920x1080@60.000')
        self.assertFalse(self.page.test_button.get_sensitive())

    def test_invalid_numeric_drafts_never_reach_compositor(self):
        from unittest.mock import Mock
        self.host.run_worker = Mock()
        for value in ('NaN', '500', '0', '120 foo', '125.'):
            self.page.scale.get_child().set_text(value)
            self.assertTrue(self.page.scale.invalid, value)
            self.assertEqual(self.page.pending[0]['scale'], 1.25)
            self.page.test_changes()
        self.host.run_worker.assert_not_called()
        self.page.discard_changes()
        self.assertFalse(self.page.input_drafts)
        self.assertNotIn('displays', self.host.dirty)

    def test_invalid_draft_is_preserved_when_switching_monitors(self):
        self.page.scale.get_child().set_text('800')
        self.page.select_monitor('HDMI-A-1')
        self.assertFalse(self.page.scale.invalid)
        self.page.select_monitor('DP-1')
        self.assertEqual(self.page.scale.get_child().get_text(), '800')
        self.assertTrue(self.page.scale.invalid)
        self.page.scale.get_child().set_text('125')
        self.assertNotIn('displays', self.host.dirty)

    def test_visible_compound_editor_normalizes_units_and_keeps_state(self):
        from adws_settings_widgets import enhance_choices
        enhance_choices(self.page)
        editor = self.page.scale._adws_choice_button.editor
        editor.set_text('137,5%')
        self.assertAlmostEqual(self.page.pending[0]['scale'], 1.375)
        editor.emit('activate')
        self.assertEqual(editor.get_text(), '137.5 %')
        self.page.refresh_rate._adws_choice_button.editor.set_text('144 hz')
        self.page.refresh_rate._adws_choice_button.editor.emit('activate')
        self.assertEqual(self.page.refresh_rate.get_child().get_text(), '144 Hz')

if __name__ == '__main__':
    unittest.main()


class FractionalGeometryTests(unittest.TestCase):
    def test_fractional_niri_coordinates_use_reported_size(self):
        monitor = dict(name='DP-1', mode='3840x2160@144.000', scale=1.7, transform=0,
                       logical_geometry=['3840x2160@144.000',1.7,0,2258,1270])
        self.assertEqual(display.logical_size(monitor), (2258,1270))
        monitor['scale'] = 2
        self.assertEqual(display.logical_size(monitor), (1920,1080))
    def test_snap_does_not_align_inside_other_display(self):
        monitor=dict(name='one',mode='1920x1080@60.000',scale=1,transform=0,x=0,y=0)
        other=dict(monitor,name='two')
        self.assertEqual(display.snapped_position(monitor,[other],10,300,24),(10,300))

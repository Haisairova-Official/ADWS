"""Regression checks for stretched toggles and serialized audio controls."""
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
from adws_settings_widgets import enhance_choices, settings_tabs
from adws_sound_settings import AudioEdits, volume_percent, snapshot, usable_device, device_choice, sound_sections


def pump(seconds=.2):
    deadline = time.monotonic()+seconds
    while time.monotonic()<deadline:
        while Gtk.events_pending(): Gtk.main_iteration_do(False)
        time.sleep(.002)


class AudioDataTests(unittest.TestCase):
    def test_read_only_snapshot_uses_one_catalog_scan_and_default_queries(self):
        with patch('adws_sound_settings.backend.audio_advanced', return_value={'sinks': []}) as scan, \
             patch('adws_sound_settings.backend.command', side_effect=lambda args: 'speaker\n' if args[-1]=='get-default-sink' else 'microphone\n') as command:
            data = snapshot()
        scan.assert_called_once_with()
        self.assertEqual(data['default_sink'], 'speaker')
        self.assertEqual(data['default_source'], 'microphone')
        self.assertEqual(sorted(c.args[0][-1] for c in command.call_args_list), ['get-default-sink','get-default-source'])

    def test_channel_data_handles_invalid_levels_without_invalid_slider_values(self):
        self.assertEqual(volume_percent({'volume':{'left':{'value':32768},'right':{'value':65536}}}),100)
        for value in (float('nan'),float('inf'),None,'bad',-10):
            self.assertEqual(volume_percent({'volume':{'left':{'value':value}}}),0)

    def test_dummy_endpoints_are_hidden_but_real_virtual_devices_remain(self):
        for item in ({'name':'auto_null'}, {'name':'null'}, {'name':'auto_null.monitor'},
                     {'name':'dummy', 'description':'(null)'},
                     {'name':'custom','driver':'module-null-sink.c'},
                     {'name':'custom','properties':{'factory.name':'support.null-audio-sink'}}):
            self.assertFalse(usable_device(item), item)
        for item in ({'name':'alsa_output.usb'}, {'name':'bluez_output.headset'},
                     {'name':'Mihomo'}, {'name':'remap','driver':'module-remap-sink.c'}):
            self.assertTrue(usable_device(item), item)


class SettingsControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check([])[0]: raise unittest.SkipTest('Requires an isolated GTK display')

    def test_null_only_audio_disables_controls_without_service_writes(self):
        section,host=self.section()
        data={'sinks':[{'index':1,'name':'auto_null'}],
              'sources':[{'index':2,'name':'auto_null.monitor'}],
              'sink-inputs':[{'index':3,'sink':1,'properties':{'application.name':'Fixture'}}],
              'source-outputs':[],'cards':[], 'default_sink':'auto_null'}
        def create(host,parent,title,loader,render,service):
            render(section,data);return section
        with patch('adws_sound_settings.NativeSection',side_effect=create):
            sound_sections(host,Gtk.Box())
        def walk(widget):
            yield widget
            if isinstance(widget,Gtk.Container):
                for child in widget.get_children():yield from walk(child)
        selectors=[w for w in walk(section.content) if isinstance(w,Gtk.ComboBoxText)]
        self.assertEqual(len(selectors),3)  # output, input, app route
        for control in selectors:
            self.assertFalse(control.get_sensitive())
            self.assertEqual(control.get_active_id(),'unavailable')
        section.change.assert_not_called();host.run_worker.assert_not_called()
        section.content.destroy();section.box.destroy()

    def test_switches_keep_natural_size_beside_large_controls(self):
        window=Gtk.Window();body=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=20)
        window.add(body)
        controls=[]
        for title in ('Bluetooth trust','Input addon','Account lock'):
            line=Gtk.Box(spacing=16)
            line.pack_start(Gtk.Label(label=title),True,True,0)
            large=Gtk.Button(label='Settings');large.set_size_request(130,90)
            toggle=Gtk.Switch();line.pack_end(toggle,False,False,0)
            line.pack_end(large,False,False,0);body.pack_start(line,False,False,0)
            controls.append(toggle)
        changes=Mock()
        for control in controls:control.connect('notify::active',changes)
        enhance_choices(body)
        window.show_all()
        for width in (560,1150):
            window.resize(width,410);pump()
            for control in controls:
                self.assertLessEqual(control.get_allocated_height(),control.get_preferred_height()[1]+2)
                self.assertLessEqual(control.get_allocated_width(),control.get_preferred_width()[1]+2)
                self.assertEqual(control.get_valign(),Gtk.Align.CENTER)
        changes.assert_not_called()
        window.destroy();pump(.01)

    def test_tab_switch_preserves_unsaved_input_and_active_values(self):
        one,two=Gtk.Box(),Gtk.Box()
        entry=Gtk.Entry(text='unsaved');one.add(entry)
        toggle=Gtk.Switch(active=True);two.add(toggle)
        tabs=settings_tabs([('one','Keyboard',one),('two','Input methods',two)])
        window=Gtk.Window();window.add(tabs);window.show_all();pump(.01)
        tabs.stack.set_visible_child_name('two');tabs.stack.set_visible_child_name('one')
        self.assertEqual(entry.get_text(),'unsaved');self.assertTrue(toggle.get_active())
        window.destroy();pump(.01)

    def section(self):
        host=Mock(busy=False,closed=False)
        section=Mock(host=host,closed=False,generation=1,content=Gtk.Box(),box=Gtk.Box())
        return section,host

    def test_audio_slider_coalesces_and_never_starts_parallel_writes(self):
        section,host=self.section();edits=AudioEdits(section)
        with patch('adws_system_pages.audio_change') as apply:
            for value in range(15,56):edits.queue('sink',1,'volume',value)
            host.busy=True;pump(.22);host.run_worker.assert_not_called()
            host.busy=False;pump(.2);host.run_worker.assert_called_once()
            job,done=host.run_worker.call_args.args
            job();done();apply.assert_called_once_with('sink',1,'volume',55)
        edits.close()

    def test_closing_or_refreshing_discards_pending_audio_edits(self):
        for cancel in ('close','refresh'):
            section,host=self.section();edits=AudioEdits(section)
            edits.queue('sink',1,'mute',True)
            if cancel=='close':section.box.destroy()
            else:section.generation+=1
            pump(.2);host.run_worker.assert_not_called();self.assertFalse(edits.pending)
            edits.close()

    def test_repeated_audio_refreshes_do_not_retain_edit_controllers(self):
        import gc, weakref
        section,_ = self.section()
        references=[]
        for _ in range(20):
            edits=AudioEdits(section)
            references.append(weakref.ref(edits))
            edits.close()
        del edits
        gc.collect()
        self.assertTrue(all(reference() is None for reference in references))

    def test_audio_failure_reloads_actual_service_state(self):
        section,host=self.section();edits=AudioEdits(section)
        edits.queue('sink',1,'volume',50);pump(.2)
        host.run_worker.call_args.kwargs['on_failure']()
        section.refresh.assert_called_once_with()
        edits.close()

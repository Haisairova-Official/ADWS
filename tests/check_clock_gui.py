"""Exercise real clock dialog widgets without modifying the user's configuration."""
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import adws_clock as clock
from adws_layout_gui import LayoutWindow, _gtk
Gdk, Gtk = _gtk()
from gi.repository import GLib

ui = clock.ClockDialog({})
assert not ui.formats.get_sensitive()
ui.checks['show_date'].set_active(True)
ui.checks['show_seconds'].set_active(True)
ui.checks['show_weekday'].set_active(True)
ui.formats.set_active_id('dmy')
assert ui.formats.get_sensitive()
assert ui.values() == {'show_date': True, 'show_seconds': True, 'show_weekday': True, 'two_lines': True, 'date_format': 'dmy', 'custom_enabled': False, 'custom_format': 'HH:mm:SS\nYYYY-MM-DD'}
ui.custom_enabled.set_active(True)
ui.custom_entries[0].set_text('HH:mm:SS')
ui.custom_entries[1].set_text('YYYY-MM-DD')
assert ui.dialog.get_widget_for_response(Gtk.ResponseType.OK).get_sensitive()
assert '<span' in ui.preview.get_label()
ui.custom_entries[0].set_text('hh:mm')
assert not ui.dialog.get_widget_for_response(Gtk.ResponseType.OK).get_sensitive()
assert ui.error.get_text()
ui.custom_entries[0].set_text('HH:mm')
assert ui.dialog.get_widget_for_response(Gtk.ResponseType.OK).get_sensitive()
GLib.idle_add(lambda: ui.dialog.response(Gtk.ResponseType.OK))
assert ui.run()['show_seconds']
GLib.idle_add(lambda: ui.dialog.response(Gtk.ResponseType.CANCEL))
assert ui.run() is None
ui.dialog.destroy()
assert ui.timer is None

# The layout editor stages changes until Apply, keeping unrelated options and
# preserving the user's in-progress row ordering when opening the clock dialog.
window = LayoutWindow()
clock_row = next(row for row in window.rows if row['key'] == 'clock')
assert any(isinstance(widget, Gtk.Button) and widget.get_label() == clock._tr('设置…') for widget in clock_row['box'].get_children())
values = {'show_date': True, 'show_seconds': True, 'show_weekday': False, 'date_format': 'iso'}
with patch.object(clock.ClockDialog, 'run', return_value=values):
    window.on_clock_settings()
assert window.collect_layout()['options']['clock'] == values
with patch.object(clock.ClockDialog, 'run', return_value=None):
    window.on_clock_settings()
assert window.collect_layout()['options']['clock'] == values
GLib.idle_add(lambda: window.window.destroy())
Gtk.main()

# Saving the standalone dialog reloads the layout, preserving concurrent edits.
initial = {'options': {'clock': {}}}
fresh = {'options': {'thickness': 72}, 'plugins': [{'package': 'keep-me'}]}
with patch('adws_layout.load_layout', side_effect=[initial, fresh]), patch('adws_layout.save_layout') as save, patch('adws_layout.apply_layout', return_value=(True, 'ok')) as apply, patch.object(clock.ClockDialog, 'run', return_value=values):
    assert clock.main() == 0
    saved = save.call_args.args[0]
    assert saved['options'] == {'thickness': 72, 'clock': values}
    assert saved['plugins'] == [{'package': 'keep-me'}]
    apply.assert_called_once_with(saved, restart=True)
print('Clock GUI: settings, preview, cancellation, staged Apply and standalone save passed.')

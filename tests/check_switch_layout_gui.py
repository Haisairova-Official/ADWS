"""Check switch allocation in real GTK, without touching live components."""
import importlib.util
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
spec = importlib.util.spec_from_file_location('adws_config', ROOT / 'tools/adws-config.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
Gtk = config.Gtk

def settle():
    for _ in range(20):
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.005)

for theme in ('Adwaita', 'Adwaita-dark'):
    Gtk.Settings.get_default().set_property('gtk-theme-name', theme)
    for width in (600, 1100):
        window = Gtk.Window()
        window.set_default_size(width, 200)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        window.add(content)
        switches = []
        for label in ('显示桌面图标', 'Show taskbar'):
            switch = Gtk.Switch()
            content.pack_start(config.row_widget(label, switch), False, False, 0)
            switches.append(switch)
        entry = Gtk.Entry()
        content.pack_start(config.row_widget('Font', entry), False, False, 0)
        window.show_all()
        for active in (False, True):
            for switch in switches:
                switch.set_active(active)
            settle()
            for switch in switches:
                minimum, natural = switch.get_preferred_width()
                actual = switch.get_allocated_width()
                assert minimum <= actual <= natural, (theme, width, active, minimum, actual, natural)
            assert entry.get_allocated_width() > switches[0].get_allocated_width() * 2
        window.destroy()
        settle()
print('Switches retain theme size at both window widths, in both states and themes; entries still expand.')

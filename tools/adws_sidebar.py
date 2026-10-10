#!/usr/bin/env python3
"""Independent ADWS dashboard: information, widgets and optional weather."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import threading
import urllib.parse
import urllib.request
import gi

LOCALE_KEYS = ('LANG', 'LANGUAGE', 'LC_ALL', 'LC_MESSAGES')


def request_locale():
    return {key: os.environ[key] for key in LOCALE_KEYS if os.environ.get(key)}


def apply_request_locale(value):
    """Carry the caller's UI language across a reused application process."""
    if not isinstance(value, dict): return False
    if any(key not in LOCALE_KEYS or not isinstance(item, str) or len(item) > 128 or '\0' in item
           for key, item in value.items()): return False
    before = chinese()
    for key in LOCALE_KEYS:
        os.environ.pop(key, None)
        if value.get(key): os.environ[key] = value[key]
    prepare_gtk_language()
    return before != chinese()


def forward_existing_sidebar(anchor, side, prepare=False):
    """A warm toggle needs only GIO, not GTK or the dashboard's widget modules."""
    from gi.repository import Gio, GLib
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        exists = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
            'org.freedesktop.DBus', 'NameHasOwner', GLib.Variant('(s)', ('org.adws.Sidebar',)),
            None, Gio.DBusCallFlags.NO_AUTO_START, 500, None).unpack()[0]
        if not exists: return False
        payload = json.dumps({'anchor': anchor or {}, 'side': side, 'locale': request_locale(), **({'prepare': True} if prepare else {})})
        bus.call_sync('org.adws.Sidebar', '/org/adws/Sidebar', 'org.gtk.Actions', 'Activate',
            GLib.Variant('(sava{sv})', ('open', [GLib.Variant('s', payload)], {})),
            None, Gio.DBusCallFlags.NO_AUTO_START, 1500, None)
        return True
    except GLib.Error as error:
        if Gio.DBusError.is_remote_error(error) and Gio.DBusError.get_remote_error(error) in (
                'org.freedesktop.DBus.Error.ServiceUnknown', 'org.freedesktop.DBus.Error.NameHasNoOwner'):
            return False
        # A timed-out toggle may already have been delivered. Do not send it a
        # second time through Gtk.Application and immediately close the panel.
        print(str(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='ADWS dashboard sidebar')
    parser.add_argument('--anchor', type=json.loads, help=argparse.SUPPRESS)
    parser.add_argument('--side', choices=('left', 'right'))
    parser.add_argument('--prepare', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if forward_existing_sidebar(args.anchor, args.side, args.prepare): raise SystemExit(0)

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gio, GLib, Gtk
from adws_i18n import tr, prepare_gtk_language, chinese
from adws_atomic import replace_files
from adws_calendar import MonthCalendar
from adws_agenda_preview import AgendaPreview
from adws_location import LocationChooser
from adws_tides import TideCard
from adws_weather import WeatherView, parse_weather

ROOT = Path(__file__).resolve().parents[1]


from adws_settings_style import PanelStyle
from adws_popup import PopupBehavior, ease_out, prepare_surface, cache_stack_transitions


class SidebarStyle(PanelStyle):
    """Translucent reading surfaces use compositor blur and quiet card overlays."""
    def stylesheet(self, roles, options):
        self.host.motion_settings = (options['window_animations'], options['animation_duration'])
        for surface in tuple(getattr(self.host,'weather_surfaces',())):surface.sync_motion()
        if hasattr(self.host,'daily_stack'):
            self.host.daily_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE if options['tab_animations'] else Gtk.StackTransitionType.NONE)
            self.host.daily_stack.set_transition_duration(options['animation_duration'])
        style = super().stylesheet(roles, options)
        _, color, _, _, _ = self.host.config.read_taskbar_overrides()
        base = Gdk.RGBA()
        if not base.parse(options['surface_color'] or Gdk.RGBA(*color).to_string()):
            base.parse(roles['bg'])
        if base.alpha <= 0.01 or (not options['surface_color'] and not self.host.config.live_style_path().exists()):
            base.parse(roles['bg'])
        base.alpha = 0.66
        return style + f"""
        window.adws-sidebar {{ transition: none; box-shadow: none; background-image: none; background-color: {base.to_string()}; color: @adws_settings_text; }}
        window.adws-sidebar .settings-card {{ background-image: none; background-color: alpha(@adws_settings_raised,.14); border-color: alpha(@adws_settings_outline,.8); }}
        window.adws-sidebar textview, window.adws-sidebar textview text {{ background-color: alpha(@adws_settings_surface,.45); color: @adws_settings_text; }}
        window.adws-sidebar .dim-label {{ opacity: 1; color: @adws_settings_muted; }}
        window.adws-sidebar .settings-card {{ padding: 14px; border-radius: 16px; border-width: 1px; }}
        window.adws-sidebar .settings-card .settings-card {{ background: transparent; border: none; padding: 4px 0; }}
        window.adws-sidebar .settings-section-title {{ font-size: 13px; font-weight: 600; }}
        window.adws-sidebar .sidebar-clock {{ font-size: 28px; font-weight: 300; letter-spacing: -1px; }}
        window.adws-sidebar .sidebar-timer {{ font-size: 36px; font-weight: 300; }}
        window.adws-sidebar .sidebar-weather {{ font-size: 18px; padding: 10px 0; }}
        window.adws-sidebar button {{ padding: 6px 10px; min-height: 22px; border-radius: 10px; }}
        window.adws-sidebar button.sidebar-icon-button {{ padding: 4px; min-width: 22px; min-height: 22px; background: transparent; border-color: transparent; }}
        window.adws-sidebar button.sidebar-icon-button:hover {{ background: alpha(@adws_settings_accent,.16); }}
        window.adws-sidebar .sidebar-tabs {{ background: alpha(@adws_settings_surface,.45); border-radius: 12px; padding: 4px; }}
        window.adws-sidebar .sidebar-tabs button {{ background: transparent; border-color: transparent; box-shadow: none; padding: 7px; }}
        window.adws-sidebar .sidebar-tabs button:checked {{ background: alpha(@adws_settings_accent,.22); color: @adws_settings_accent; }}
        window.adws-sidebar .sidebar-board-card:drop(active) {{ border-color: @adws_settings_accent; }}
        window.adws-sidebar .sidebar-notification-row {{ background: alpha(@adws_settings_surface,.45); padding: 10px; border-radius: 10px; }}
        window.adws-sidebar .settings-account-header {{ background: transparent; border: none; padding: 0; }}
        window.adws-sidebar .settings-account-name {{ font-size: 15px; }}
        window.adws-sidebar textview text {{ padding: 6px; }}
        window.adws-sidebar scale {{ padding: 6px 0; }}

        window.adws-sidebar .calendar-heading {{ font-size: 17px; font-weight: 600; }}
        window.adws-sidebar .calendar-weekday {{ font-size: 11px; color: @adws_settings_muted; padding: 8px 0; }}
        window.adws-sidebar button.calendar-day {{ padding: 3px 0 0; min-width: 18px; min-height: 28px; border: 1px solid transparent; background: transparent; box-shadow: none; border-radius: 10px; }}
        window.adws-sidebar button.calendar-day:hover {{ background: alpha(@adws_settings_accent,.16); }}
        window.adws-sidebar button.calendar-day.other-month {{ color: alpha(@adws_settings_text,.35); }}
        window.adws-sidebar button.calendar-day.is-today {{ border-color: @adws_settings_accent; color: @adws_settings_accent; }}
        window.adws-sidebar button.calendar-day.is-selected {{ background: @adws_settings_accent; color: @adws_settings_on_accent; }}
        window.adws-sidebar .calendar-dot {{ font-size: 10px; min-height: 8px; }}
        window.adws-sidebar .calendar-today-link {{ font-size: 11px; padding: 3px 7px; min-height: 18px; }}
        window.adws-sidebar .adws-month {{ padding: 2px; }}
        window.adws-sidebar .weather-hero {{ padding: 14px; border-radius: 18px; background-image: linear-gradient(125deg, alpha(@adws_settings_accent,.15), alpha(@adws_settings_raised,.25)); }}
        window.adws-sidebar .weather-city {{ font-size: 18px; font-weight: 600; }}
        window.adws-sidebar .weather-temperature {{ font-size: 64px; font-weight: 300; letter-spacing: -3px; }}
        window.adws-sidebar .weather-condition {{ color: @adws_settings_accent; }}
        window.adws-sidebar .weather-summary {{ font-size: 15px; font-weight: 500; }}
        window.adws-sidebar .weather-tile {{ background: alpha(@adws_settings_raised,.14); border-radius: 12px; padding: 10px; }}
        window.adws-sidebar .weather-forecast-row {{ border-top: 1px solid alpha(@adws_settings_outline,.45); padding: 12px 2px; }}
        window.adws-sidebar .agenda-event {{ border-left: 3px solid @adws_settings_accent; background: alpha(@adws_settings_raised,.35); border-radius: 8px; padding: 10px; }}
        window.adws-sidebar calendar {{ background: transparent; color: @adws_settings_text; border: none; padding: 8px; font-size: 14px; }}
        window.adws-sidebar calendar.header {{ background: transparent; border: none; color: @adws_settings_text; }}
        window.adws-sidebar calendar.highlight {{ background: transparent; color: @adws_settings_muted; }}
        window.adws-sidebar calendar:selected {{ background: @adws_settings_accent; color: @adws_settings_on_accent; border-radius: 8px; }}
        window.adws-sidebar calendar:indeterminate {{ color: alpha(@adws_settings_muted,.45); }}

        """



def config_path():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'adws/sidebar.json'


def load_config():
    try:
        data = json.loads(config_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError): return {}


def save_config(data):
    replace_files({config_path(): json.dumps(data, ensure_ascii=False).encode()})


def memory_usage():
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        name, value = line.split(':', 1)
        values[name] = int(value.split()[0])
    total = values['MemTotal']
    return (total-values['MemAvailable'])/total, total/1048576


def weather(city):
    city = str(city).strip()
    if not city or len(city) > 120:
        raise ValueError(tr('请输入城市名称。'))
    url = 'https://wttr.in/'+urllib.parse.quote(city, safe='')+'?format=j1'+('&lang=zh' if chinese() else '')
    request = urllib.request.Request(url, headers={'User-Agent': 'ADWS-sidebar/1'})
    with urllib.request.urlopen(request, timeout=8) as response:
        raw = response.read(512*1024+1)
    if len(raw) > 512*1024: raise ValueError('Weather response too large')
    return parse_weather(json.loads(raw),city)


def build_settings(host):
    from adws_system_settings import card
    box = card('侧边栏', '信息、小工具和天气分区；仅在打开时更新。天气需要手动指定城市。')
    side = Gtk.ComboBoxText()
    side.append('left', tr('左侧')); side.append('right', tr('右侧'))
    side.set_active_id(load_config().get('side', 'right'))
    def launch(*_):
        settings = load_config(); settings['side'] = side.get_active_id(); save_config(settings)
        subprocess.Popen([str(ROOT/'adws'), 'sidebar', '--side', side.get_active_id()], start_new_session=True)
    box.pack_start(host.config.row_widget(tr('显示位置'), side), False, False, 0)
    from adws_system_settings import label
    box.pack_start(label('任务栏入口跟随按钮所在屏幕与位置；这里的位置用于手动打开。', 'dim-label'), False, False, 0)
    button = Gtk.Button(label=tr('打开侧边栏')); button.connect('clicked', launch)
    box.pack_start(button, False, False, 0)
    return box


def side_for_button(anchor, width, preference='right'):
    """Taskbar anchors override the independent settings/CLI preference."""
    if anchor:
        edge = anchor.get('edge', 'bottom')
        if edge in ('left', 'right'): return edge
        return 'left' if float(anchor.get('x', width/2)) < width/2 else 'right'
    return preference if preference in ('left', 'right') else 'right'


def run(anchor=None, side=None, prepare=False):
    prepare_gtk_language()
    app = Gtk.Application(application_id='org.adws.Sidebar')
    window = None
    expiry_source = 0
    def config_revision():
        try:
            state=config_path().stat()
            return state.st_ino,state.st_mtime_ns,state.st_size
        except OSError:return None
    def window_closed(*_):
        nonlocal window, expiry_source
        window = None
        from adws_sidebar_model import timer_remaining
        state=load_config().get('timer', {})
        if isinstance(state,dict) and state.get('deadline'):
            def expired():
                nonlocal expiry_source
                expiry_source=0
                current=load_config(); current['timer']={'remaining':0}; save_config(current)
                notice=Gio.Notification.new(tr('计时结束')); notice.set_body(tr('侧边栏计时器已完成。'))
                app.send_notification('sidebar-timer',notice)
                app.quit()
                return False
            expiry_source=GLib.timeout_add_seconds(max(1,timer_remaining(state)),expired)
        else: app.quit()
    def window_hidden(*_):
        nonlocal expiry_source
        # Reuse one unmapped window for quick toggles, then release its entire
        # widget tree. No accumulating windows or perpetual hidden rendering.
        if expiry_source: GLib.source_remove(expiry_source)
        window.cached_config_revision=config_revision()
        def release():
            nonlocal expiry_source
            expiry_source=0
            if window is not None: window.destroy()
            return False
        expiry_source=GLib.timeout_add_seconds(60,release)
    payload = json.dumps({'anchor': anchor or {}, 'side': side, 'locale': request_locale(), **({'prepare': True} if prepare else {})})
    def open_sidebar(_, parameter):
        nonlocal window, expiry_source
        request = json.loads(parameter.get_string())
        preparing = request.get('prepare') is True
        if preparing and window is not None: return
        if expiry_source: GLib.source_remove(expiry_source); expiry_source=0
        language_changed=apply_request_locale(request.get('locale'))
        if window and (language_changed or (not window.get_visible() and window.cached_config_revision != config_revision())):
            # Respect changes made in Settings while the panel was hidden.
            window.disconnect(window.cached_hide_handler)
            window.disconnect(window.cached_destroy_handler)
            window.destroy();window=None
        if window:
            target = window.placement(request.get('anchor'), request.get('side'))
            if not window.get_visible():
                window.position(request.get('anchor'), request.get('side'))
                window.reveal()
            elif window.closing:
                window.closing = False
                window.position(request.get('anchor'), request.get('side'))
                window.present(); window.animate(True)
            elif target[2:] == window.placement_identity:
                window.dismiss()
            else:
                window.position(request.get('anchor'), request.get('side'))
                window.present()
            return
        window = Dashboard(app, request.get('anchor'), request.get('side'))
        window.retain_on_close = True
        window.cached_destroy_handler=window.connect('destroy', window_closed)
        window.cached_hide_handler=window.connect('hide', window_hidden)
        if preparing:
            # Build without mapping, grabbing focus or starting map-bound I/O.
            window_hidden()
        else:
            window.reveal()
    action = Gio.SimpleAction.new('open', GLib.VariantType.new('s'))
    action.connect('activate', open_sidebar); app.add_action(action)
    app.register(None)
    if app.get_is_remote():
        app.activate_action('open', GLib.Variant('s', payload)); return 0
    app.hold()
    app.connect('activate', lambda *_: app.activate_action('open', GLib.Variant('s', payload)))
    return app.run([])


class Dashboard(PopupBehavior, Gtk.ApplicationWindow):
    def __init__(self, app, anchor=None, side=None):
        super().__init__(application=app)
        import importlib.util
        # Reuse the same configuration reader as native quick controls.
        config=sys.modules.get('sidebar_config')
        if config is None:
            spec = importlib.util.spec_from_file_location('sidebar_config', ROOT/'tools/adws-config.py')
            config = importlib.util.module_from_spec(spec); sys.modules[spec.name] = config; spec.loader.exec_module(config)
        self.config = config
        self.set_title(tr('ADWS 侧边栏'))
        self.set_default_size(560, 820); self.set_decorated(False)
        self.get_style_context().add_class('adws-system-settings')
        self.get_style_context().add_class('adws-quick-panel')
        self.get_style_context().add_class('adws-sidebar')
        prepare_surface(self)
        self.motion_source = 0; self.focus_source = 0
        self.had_focus = False; self.closing = False
        self.interaction_depth = 0
        self.style = SidebarStyle(self)
        self.settings = load_config(); self.closed = False
        self.timer = 0; self.weather_busy = False; self.note_timer = 0
        self.layer = None
        if os.environ.get('XDG_SESSION_TYPE') != 'x11' and os.environ.get('WAYLAND_DISPLAY'):
            try:
                gi.require_version('GtkLayerShell', '0.1')
                from gi.repository import GtkLayerShell as layer
                if layer.is_supported():
                    layer.init_for_window(self); layer.set_layer(self, layer.Layer.OVERLAY)
                    layer.set_namespace(self, "launcher")
                    layer.set_exclusive_zone(self, 0)
                    layer.set_keyboard_mode(self, layer.KeyboardMode.ON_DEMAND)
                    self.layer = layer
            except (ImportError, ValueError): pass
        self.position(anchor, side)
        from adws_system_settings import card, label
        from adws_account_header import AccountHeader
        from adws_sidebar_widgets import LevelCard, MediaCard, SystemCard, QuickActions
        from adws_sidebar_board import CardBoard, TodoCard, TimerCard, icon_button
        from adws_sidebar_notifications import NotificationCard
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_border_width(18); self.add(outer); self.content_root=outer
        header = Gtk.Box(spacing=12)
        account = AccountHeader(lambda: self.launch('config', '--tab', 'region'))
        account.role.set_no_show_all(True); account.role.hide()
        header.pack_start(account, True, True, 0)
        self.time_label = label('', 'sidebar-clock'); self.time_label.set_xalign(1)
        header.pack_end(icon_button('window-close-symbolic', '关闭侧边栏', lambda *_: self.dismiss()), False, False, 0)
        clock_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=2)
        self.date_label=label('', 'dim-label'); self.date_label.set_xalign(1)
        clock_box.pack_start(self.time_label,False,False,0); clock_box.pack_start(self.date_label,False,False,0)
        header.pack_end(clock_box, False, False, 0)
        outer.pack_start(header, False, False, 0)
        self.stack = stack = Gtk.Stack(); stack.set_hhomogeneous(True); stack.set_vhomogeneous(False)
        switcher = Gtk.StackSwitcher(); switcher.set_stack(stack)
        switcher.get_style_context().add_class('sidebar-tabs'); switcher.set_halign(Gtk.Align.FILL); switcher.set_homogeneous(True)
        outer.pack_start(switcher, False, False, 0); outer.pack_start(stack, True, True, 0)
        self.pages = pages = {}
        for name, title in [('info','通知'),('widgets','小组件'),('weather','天气')]:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            scroll = Gtk.ScrolledWindow(); scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_overlay_scrolling(False); scroll.add(box)
            if name=='info':
                page=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10)
                page.pack_start(scroll,True,True,0)
                self.quick_dock=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
                page.pack_end(self.quick_dock,False,False,0)
                stack.add_titled(page,name,tr(title))
            else: stack.add_titled(scroll,name,tr(title))
            pages[name]=box
        self.notifications = NotificationCard(self)
        pages['info'].pack_start(self.notifications.box,False,False,0)
        self.quick = QuickActions(self); self.quick_dock.pack_start(self.quick.box,False,False,0)
        self.controls = [LevelCard(self,'sound'), LevelCard(self,'brightness'), MediaCard(self)]
        levels = Gtk.Grid(column_spacing=10); levels.set_column_homogeneous(True)
        for index, control in enumerate(self.controls[:2]): levels.attach(control.box,index,0,1,1)
        self.level_grid=levels
        self.quick_dock.pack_start(levels,False,False,0)
        pages['info'].pack_start(self.controls[2].box,False,False,0)
        daily = card('今日工具')
        self.daily_stack = Gtk.Stack(); self.daily_stack.set_hhomogeneous(True); self.daily_stack.set_vhomogeneous(False)
        daily_switcher=Gtk.StackSwitcher(stack=self.daily_stack); daily_switcher.set_homogeneous(True)
        daily_switcher.get_style_context().add_class('sidebar-tabs')
        daily.pack_start(daily_switcher,False,False,0); daily.pack_start(self.daily_stack,False,False,0)
        calendar_page=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12)
        calendar=MonthCalendar();calendar_page.pack_start(calendar,False,False,0)
        self.upcoming=AgendaPreview();calendar_page.pack_start(self.upcoming,False,False,0)
        self.daily_stack.add_titled(calendar_page,'calendar',tr('日历'))
        self.todo=TodoCard(load_config,save_config); self.daily_stack.add_titled(self.todo.box,'todo',tr('待办'))
        self.countdown=TimerCard(self,load_config,save_config); self.daily_stack.add_titled(self.countdown.box,'timer',tr('计时器'))
        pages['info'].pack_start(daily,False,False,0)
        self.board_controls=[]
        def level(kind):
            item=LevelCard(self,kind); self.board_controls.append(item); return item.box
        def media():
            item=MediaCard(self); self.board_controls.append(item); return item.box
        def calendar_card():
            box=card('日历'); box.pack_start(MonthCalendar(),False,False,0);box.pack_start(AgendaPreview(),False,False,0); return box
        def todo_card():
            item=TodoCard(load_config,save_config); self.board_controls.append(item); return item.box
        def timer_card():
            item=TimerCard(self,load_config,save_config); self.board_controls.append(item); return item.box
        def notes_card():
            box=card('便签'); self.notes=Gtk.TextView(); self.notes.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            self.notes.set_size_request(-1,120); self.notes.get_buffer().set_text(str(load_config().get('notes','')))
            self.note_handler=self.notes.get_buffer().connect('changed',self.note_changed)
            box.pack_start(self.notes,True,True,0); return box
        self.system_card=SystemCard(); self.memory_label=label(''); self.memory_bar=Gtk.ProgressBar()
        self.system_card.box.pack_start(self.memory_label,False,False,0)
        self.system_card.box.pack_start(self.memory_bar,False,False,0)
        factories={'sound':lambda:level('sound'),'brightness':lambda:level('brightness'),'media':media,
                   'system':lambda:self.system_card.box,'notes':notes_card,'calendar':calendar_card,'todo':todo_card,'timer':timer_card}
        self.board=CardBoard(self,factories,load_config,save_config)
        pages['widgets'].pack_start(self.board,False,False,0)
        weather_card=card('当地天气')
        self.city=Gtk.Entry(); self.city.set_max_length(120); self.city.set_placeholder_text(tr('城市名称')); self.city.set_text(str(self.settings.get('city','')))
        self.city.connect('activate',self.fetch_weather)
        city_row=Gtk.Box(spacing=8); city_row.pack_start(self.city,True,True,0)
        self.weather_button=icon_button('view-refresh-symbolic','读取天气',self.fetch_weather)
        city_row.pack_end(self.weather_button,False,False,0); weather_card.pack_start(city_row,False,False,0)
        self.tides=TideCard(self)
        self.tides.set_city(self.city.get_text(),fetch=False)
        self.location_chooser=LocationChooser(self,self.location_changed)
        if self.city.get_text().strip():self.location_chooser.use_city()
        weather_card.pack_start(self.location_chooser,False,False,0)
        self.weather_view=WeatherView()
        cached=self.settings.get('weather_snapshot')
        try:
            if isinstance(cached,dict) and cached.get('version')==1:self.weather_view.display(cached)
            elif self.settings.get('weather_cache'):self.weather_view.empty(self.settings['weather_cache'])
        except (KeyError,TypeError,ValueError):self.weather_view.empty()
        weather_card.pack_start(self.weather_view,False,False,0)
        status_row=Gtk.Box(spacing=8);self.weather_spinner=Gtk.Spinner()
        self.weather_spinner.set_no_show_all(True);city_row.pack_end(self.weather_spinner,False,False,0)
        self.weather_status=label('按需读取 wttr.in 天气；不会自动定位。','dim-label')
        self.weather_status.set_max_width_chars(42)
        if isinstance(cached,dict) and cached.get('updated'):
            self.weather_status.set_text(tr('上次更新')+' '+str(cached['updated']).replace('T',' ')+' · wttr.in')
        status_row.pack_start(self.weather_status,True,True,0);weather_card.pack_start(status_row,False,False,0)
        pages['weather'].pack_start(weather_card,False,False,0)
        pages['weather'].pack_start(self.tides.box,False,False,0)
        self.page_refresh_pending=False
        stack.connect('notify::visible-child-name',self.page_changed)
        stack.connect('notify::transition-running',lambda *_:self.popup_idle(self.flush_page_refresh) if not stack.get_transition_running() else None)
        self.connect('size-allocate',self.responsive_layout)
        self.style.reload()
        self.daily_stack.set_transition_type(self.stack.get_transition_type()); self.daily_stack.set_transition_duration(self.stack.get_transition_duration())
        cache_stack_transitions(self.stack)
        cache_stack_transitions(self.daily_stack)
        self.connect('key-press-event', lambda _, event: (self.dismiss() or True) if event.keyval == Gdk.KEY_Escape else False)
        self.connect('focus-in-event', self.focus_in)
        self.connect('focus-out-event', self.focus_out)
        self.connect('destroy', self.cleanup)
        self.tick(); self.timer = GLib.timeout_add_seconds(5, self.tick)

    def placement(self, anchor=None, side=None):
        display = self.get_display(); anchor = anchor or {}
        index = anchor.get('monitor')
        monitor = display.get_monitor(index) if type(index) is int and 0 <= index < display.get_n_monitors() else None
        if monitor is None:
            pointer = display.get_default_seat().get_pointer()
            _, x, y = pointer.get_position()
            monitor = display.get_monitor_at_point(x, y) or display.get_primary_monitor() or display.get_monitor(0)
        rect = monitor.get_geometry()
        index = next((i for i in range(display.get_n_monitors()) if display.get_monitor(i) == monitor), 0)
        selected = side_for_button(anchor, rect.width, side or self.settings.get('side', 'right'))
        return monitor, rect, index, selected

    def position(self, anchor=None, side=None):
        anchor = anchor or {}
        monitor, rect, index, selected = self.placement(anchor, side)
        self.placement_identity = (index, selected)
        inset = max(12, min(256, int(anchor.get('inset', 12))))
        margins = {'top': 12, 'bottom': 12, 'left': 12, 'right': 12}
        edge = anchor.get('edge')
        if edge in margins: margins[edge] = inset
        self.monitor_rect=rect
        self.set_size_request(min(560,max(1,rect.width-24)),min(820,max(1,rect.height-margins['top']-margins['bottom'])))
        self.base_margins = margins
        self.base_position = (rect.x + (margins['left'] if selected == 'left' else rect.width-min(560, max(280, rect.width-24))-margins['right']), rect.y+margins['top'])
        self.set_default_size(min(560, max(280, rect.width-24)), min(820, rect.height-24))
        if self.layer:
            layer = self.layer; layer.set_monitor(self, monitor)
            for name, value in (('left', layer.Edge.LEFT), ('right', layer.Edge.RIGHT), ('top', layer.Edge.TOP), ('bottom', layer.Edge.BOTTOM)):
                layer.set_anchor(self, value, name in (selected, 'top', 'bottom'))
                layer.set_margin(self, value, margins[name])
        else:
            width = min(560, max(280, rect.width - 24))
            height = min(820, max(240, rect.height - margins['top'] - margins['bottom']))
            self.resize(width, height)
            self.move(rect.x + (margins['left'] if selected == 'left' else rect.width-width-margins['right']), rect.y+margins['top'])

    def responsive_layout(self, _, allocation):
        if not self.layer:
            rect=self.monitor_rect; selected=self.placement_identity[1]
            x=rect.x+self.base_margins['left'] if selected=='left' else rect.x+rect.width-allocation.width-self.base_margins['right']
            self.base_position=(max(rect.x,x),rect.y+self.base_margins['top'])
            if not self.motion_source: self.move(*self.base_position)
        columns = 2 if allocation.width >= 510 else 1
        self.board.set_columns(columns)
        if getattr(self, 'level_columns', 2) != columns:
            for child in self.level_grid.get_children(): self.level_grid.remove(child)
            for index, control in enumerate(self.controls[:2]):
                self.level_grid.attach(control.box,index if columns==2 else 0,0 if columns==2 else index,1,1)
            self.level_columns=columns; self.level_grid.show_all()

    def page_changed(self, *_):
        if self.closed or self.closing:return
        if self.stack.get_visible_child_name()=='widgets':self.board.render()
        self.page_refresh_pending=True
        self.popup_idle(self.flush_page_refresh)

    def flush_page_refresh(self):
        if self.closed or self.closing or not self.page_refresh_pending:return
        if self.motion_source or self.stack.get_transition_running():return
        self.page_refresh_pending=False
        if self.stack.get_visible_child_name()=='info':
            self.todo.render();self.upcoming.refresh()
        # Hardware and notification cards refresh on map, with their own bounded
        # polling. Do not enqueue a duplicate refresh for every page switch.

    def launch(self, *args):
        command = [str(ROOT/'adws'), *args]
        if args[0] == 'native-quick': command = ['python3', str(ROOT/'tools/adws_quick_controls.py'), *args[1:]]
        if args[0] == 'clipboard': command = ['python3', str(ROOT/'tools/adws_clipboard.py')]
        subprocess.Popen(command, start_new_session=True)

    def tick(self):
        if self.closed: return False
        if self.closing or (self.get_realized() and not self.get_mapped()): return True
        self.system_card.tick()
        self.time_label.set_text(datetime.now().strftime('%H:%M'))
        self.date_label.set_text(datetime.now().strftime('%x %a'))
        try:
            used, total = memory_usage(); self.memory_label.set_text(f'{tr("内存")} {used*total:.1f} / {total:.1f} GiB')
            self.memory_bar.set_fraction(used)
        except (OSError, ValueError, KeyError): self.memory_label.set_text(tr('无可用数据'))
        return True

    def note_changed(self, *_):
        if self.note_timer: GLib.source_remove(self.note_timer)
        self.note_timer = GLib.timeout_add(600, self.save_notes)

    def save_notes(self):
        self.note_timer = 0
        buffer = self.notes.get_buffer()
        self.settings = load_config()
        self.settings['notes'] = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        save_config(self.settings)
        return False

    def location_changed(self,location):
        self.tides.set_location(location)
        if location is None and getattr(self,'weather_from_location',False):
            self.weather_revision=getattr(self,'weather_revision',0)+1;self.weather_from_location=False
            self.weather_busy=False;self.weather_button.set_sensitive(True);self.weather_spinner.stop();self.weather_spinner.hide()
            cached=load_config().get('weather_snapshot')
            try:
                if isinstance(cached,dict):self.weather_view.display(cached)
                else:self.weather_view.empty();self.weather_view.show_all()
            except (KeyError,ValueError,TypeError):self.weather_view.empty();self.weather_view.show_all()
            self.weather_status.set_text(tr('未获取位置；自动潮汐暂不可用。'))
        # Location is ephemeral. Do not replace the user's saved manual city.
        if location:
            self.fetch_weather(query=f"{location['latitude']},{location['longitude']}",display_name=location['name'])

    def fetch_weather(self, *_, query=None, display_name=None):
        if self.weather_busy: return
        self.settings = load_config()
        if query is None:
            self.settings['city'] = self.city.get_text().strip(); save_config(self.settings)
            if self.settings['city']:self.location_chooser.use_city()
            self.tides.set_city(self.settings['city'])
        if not (query or self.settings.get('city')):
            self.weather_status.set_text(tr('请输入城市名称。'));self.city.grab_focus();return
        self.weather_revision=getattr(self,'weather_revision',0)+1;token=self.weather_revision
        self.weather_from_location=query is not None
        self.weather_busy = True; self.weather_button.set_sensitive(False)
        self.weather_spinner.show();self.weather_spinner.start()
        self.weather_status.set_text(tr('正在更新天气…'))
        city = query or self.settings['city']
        def worker():
            error=None
            try:
                result = weather(city)
                if display_name:result['city']=display_name
            except Exception as exc: result=None; error=tr('天气读取失败：')+str(exc)
            def done():
                if self.closed or token!=self.weather_revision: return False
                try:
                    if result:
                        self.weather_view.display(result)
                        if query is None:
                            settings=load_config(); settings['weather_snapshot']=result; save_config(settings)
                        self.weather_status.set_text(tr('更新时间')+' '+datetime.now().strftime('%H:%M')+' · wttr.in')
                    else:
                        cached=load_config().get('weather_snapshot',{})
                        updated=str(cached.get('updated','')).replace('T',' ') if isinstance(cached,dict) else ''
                        self.weather_status.set_text((error or tr('暂时不可用'))+('\n'+tr('上次更新')+' '+updated if updated else ''))
                except (OSError,ValueError,KeyError,TypeError) as exc:
                    self.weather_status.set_text(tr('天气读取失败：')+str(exc))
                finally:
                    self.weather_spinner.stop();self.weather_spinner.hide()
                    self.weather_busy = False; self.weather_button.set_sensitive(True)
                return False
            if not self.closed: GLib.idle_add(done)
        # A bounded network request cannot retain the application bus after close.
        threading.Thread(target=worker, name='adws-sidebar-weather', daemon=True).start()

    def cleanup(self, *_):
        self.closed = True
        self.stop_motion()
        for source in (self.focus_source,):
            if source: GLib.source_remove(source)
        self.motion_source = self.focus_source = 0
        if self.timer: GLib.source_remove(self.timer)
        if self.note_timer: GLib.source_remove(self.note_timer); self.save_notes()
        self.style.close()
        if getattr(self,"note_handler",0):
            self.notes.get_buffer().disconnect(self.note_handler);self.note_handler=0
        self.city.disconnect_by_func(self.fetch_weather)
        self.weather_button.disconnect_by_func(self.fetch_weather)
        # Gtk.Stack removes its pages on disposal; Python-owned page trees can
        # survive that removal, so explicitly destroy retained pages as well.
        self.board.dispose()
        for page in self.pages.values():page.destroy()
        self.pages.clear()
        self.content_root.destroy()



if __name__ == '__main__':
    raise SystemExit(run(args.anchor, args.side, args.prepare))

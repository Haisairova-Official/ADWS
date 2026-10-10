"""Small interactive dashboard cards; hardware work never runs on the GTK thread."""
from pathlib import Path
import shutil
import threading
import time
from gi.repository import Gtk, Gio, GLib, Pango
from adws_i18n import tr
from adws_system_settings import card, label
import adws_quick_backend as backend


class AsyncCard:
    def __init__(self, host, title):
        self.host = host
        self.box = card(title)
        self.status = label('读取状态…', 'dim-label'); self.status.set_max_width_chars(28)
        # Device descriptions must not grow the quick-control dock after the
        # opening snapshot fades out. Keep one line, with full text in tooltip.
        self.status.set_line_wrap(False)
        self.status.set_single_line_mode(True)
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.box.pack_start(self.status, False, False, 0)
        self.busy = False
        self.pending = {}
        self.closed=False;self.poll_source=0
        host.connect('destroy',self.dispose);self.box.connect('destroy',self.dispose)

    def watch_visible(self, refresh, seconds):
        def poll():
            if self.closed or self.host.closed or not self.box.get_mapped():
                self.poll_source=0;return False
            refresh();return True
        def mapped(*_):
            if self.closed:return
            def ready():
                if not self.closed and self.box.get_mapped(): refresh()
            self.host.after_motion(ready)
            if not self.poll_source:self.poll_source=GLib.timeout_add_seconds(seconds,poll)
        self.box.connect('map',mapped);self.box.connect('unmap',self.stop_poll)
        if self.box.get_mapped():mapped()

    def stop_poll(self,*_):
        if self.poll_source:GLib.source_remove(self.poll_source);self.poll_source=0

    def dispose(self,*_):
        self.closed=True;self.stop_poll();self.pending.clear()

    def job(self, operation, consume, key="refresh"):
        if self.closed or self.host.closed: return
        if self.busy:
            if key=="refresh":return
            # One queued operation per control; volume drags cannot discard mute changes.
            self.pending[key] = (operation, consume)
            return
        self.busy = True
        def worker():
            try: result, error = operation(), None
            except Exception as exc: result, error = None, str(exc)
            def deliver():
                self.busy = False
                if self.closed or self.host.closed: self.pending.clear(); return False
                if error:
                    self.status.set_text(tr('暂时不可用')); self.status.set_tooltip_text(error); self.status.show()
                else:
                    consume(result)
                    self.status.set_tooltip_text(self.status.get_text())
                if self.pending:
                    pending_key=next(iter(self.pending)); next_operation,next_consume=self.pending.pop(pending_key)
                    self.job(next_operation,next_consume,pending_key)
                return False
            if not self.closed and not self.host.closed:
                # Scheduling the deferral itself must happen on the GTK thread.
                def schedule():
                    if not self.closed and not self.host.closed:self.host.after_motion(deliver)
                    return False
                GLib.idle_add(schedule)
        threading.Thread(target=worker, name='adws-sidebar-control', daemon=True).start()


class LevelCard(AsyncCard):
    def __init__(self, host, kind):
        super().__init__(host, '声音' if kind == 'sound' else '亮度')
        self.kind = kind; self.items = []; self.sink = None
        self.updating = False; self.write_timer = 0; self.revision = 0
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0 if kind == 'sound' else 5, 100, 1)
        self.scale.set_digits(0); self.scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.scale.set_sensitive(False); self.scale.connect('value-changed', self.changed)
        self.box.pack_start(self.scale, False, False, 0)
        row = Gtk.Box(spacing=8)
        refresh = Gtk.Button.new_from_icon_name('view-refresh-symbolic', Gtk.IconSize.BUTTON)
        refresh.set_tooltip_text(tr('刷新状态')); refresh.connect('clicked', lambda *_: self.refresh())
        row.pack_end(refresh, False, False, 0)
        if kind == 'sound':
            self.mute = Gtk.ToggleButton(label=tr('静音'))
            self.mute.set_sensitive(False); self.mute.connect('toggled', self.toggle_mute)
            row.pack_start(self.mute, False, False, 0)
        self.box.pack_start(row, False, False, 0)
        if kind == 'brightness':
            cached = backend.cached_brightness()
            if cached: self.loaded(cached)
        self.watch_visible(self.refresh,3 if kind=='sound' else 5)
        host.connect('destroy', self.close)

    def refresh(self):
        if self.closed or self.busy or self.write_timer or not self.box.get_mapped(): return
        revision = self.revision
        self.job(backend.audio if self.kind == 'sound' else backend.brightness,
                 lambda result: self.loaded(result) if revision == self.revision else None)

    def loaded(self, data):
        self.updating = True
        try:
            if self.kind == 'sound':
                sinks = data.get('sinks', [])
                self.sink = next((item for item in sinks if item.get('default')), next(iter(sinks), None))
                available = self.sink is not None
                if available:
                    self.scale.set_value(self.sink['volume'])
                    self.mute.set_active(bool(self.sink.get('mute')))
                self.mute.set_sensitive(available)
                self.status.set_text(self.sink['description'] if available else tr('无可用配置'))
            else:
                self.items = data
                targets = backend.brightness_targets(data); available = bool(targets)
                if targets: self.scale.set_value(sum(item['value'] for item in targets)/len(targets))
                self.status.set_text(tr('所有可调节显示器') if targets else tr('无可用配置'))
            self.scale.set_sensitive(available)
        finally: self.updating = False

    def changed(self, *_):
        if self.updating: return
        self.revision += 1
        if self.write_timer: GLib.source_remove(self.write_timer)
        self.write_timer = GLib.timeout_add(160, self.write)

    def write(self):
        self.write_timer = 0
        value = self.scale.get_value()
        if self.kind == 'sound' and self.sink:
            index = self.sink['index']
            self.job(lambda: backend.audio_write('sink', index, 'volume', value), lambda _: None, 'volume')
        elif self.kind == 'brightness':
            items = self.items
            self.job(lambda: backend.brightness_all(items, value), lambda _: None, 'brightness')
        return False

    def toggle_mute(self, button):
        if self.updating or not self.sink: return
        self.revision+=1
        index, value = self.sink['index'], button.get_active()
        self.job(lambda: backend.audio_write('sink', index, 'mute', value), lambda _: None, 'mute')

    def close(self, *_):
        if self.write_timer: GLib.source_remove(self.write_timer); self.write_timer = 0
        self.pending = {}
        self.dispose()


def media_snapshot():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    names = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                          'ListNames', None, None, Gio.DBusCallFlags.NONE, 700, None).unpack()[0]
    players = []
    for name in sorted(name for name in names if name.startswith('org.mpris.MediaPlayer2.'))[:8]:
        try:
            props = bus.call_sync(name, '/org/mpris/MediaPlayer2', 'org.freedesktop.DBus.Properties',
                                  'GetAll', GLib.Variant('(s)', ('org.mpris.MediaPlayer2.Player',)),
                                  None, Gio.DBusCallFlags.NO_AUTO_START, 500, None).unpack()[0]
            players.append((name, props))
        except GLib.Error: continue
    return next((item for item in players if item[1].get('PlaybackStatus') == 'Playing'), next(iter(players), None))


class MediaCard(AsyncCard):
    def __init__(self, host):
        super().__init__(host, '媒体播放'); self.player = None
        self.status.set_line_wrap(True); self.status.set_max_width_chars(28)
        self.buttons = {}; row = Gtk.Box(spacing=12); row.set_halign(Gtk.Align.CENTER)
        for method, icon, title in [('Previous','media-skip-backward-symbolic','上一首'), ('PlayPause','media-playback-start-symbolic','播放 / 暂停'), ('Next','media-skip-forward-symbolic','下一首')]:
            button = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON); button.set_tooltip_text(tr(title))
            button.set_sensitive(False); button.connect('clicked', lambda _, method=method: self.control(method))
            row.pack_start(button, False, False, 0); self.buttons[method] = button
        self.box.pack_start(row, False, False, 0)
        self.watch_visible(self.refresh,3)
        host.connect('destroy', self.close)

    def refresh(self):
        if self.host.closed: return False
        if not self.busy and self.box.get_mapped(): self.job(media_snapshot, self.loaded)
        return True

    def loaded(self, data):
        self.player = data[0] if data else None
        props = data[1] if data else {}; meta = props.get('Metadata', {})
        self.status.set_text(str(meta.get('xesam:title', tr('没有正在播放的媒体'))) + ('\n'+', '.join(meta.get('xesam:artist', [])) if meta.get('xesam:artist') else ''))
        for method, button in self.buttons.items():
            capability = {'Previous':'CanGoPrevious','Next':'CanGoNext','PlayPause':'CanPause' if props.get('PlaybackStatus')=='Playing' else 'CanPlay'}[method]
            button.set_sensitive(bool(data and props.get('CanControl', True) and props.get(capability, False)))
        icon = 'media-playback-pause-symbolic' if props.get('PlaybackStatus') == 'Playing' else 'media-playback-start-symbolic'
        self.buttons['PlayPause'].set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))

    def control(self, method):
        if not self.player: return
        name = self.player
        def operation():
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            bus.call_sync(name, '/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2.Player', method, None, None,
                          Gio.DBusCallFlags.NO_AUTO_START, 1000, None)
            return media_snapshot()
        self.job(operation, self.loaded)

    def close(self, *_):
        self.dispose()


class SystemCard:
    def __init__(self):
        self.box = card('系统监视'); self.status = label(''); self.box.pack_start(self.status, False, False, 0)
        self.previous = None

    def tick(self):
        try:
            values = [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
            total, idle = sum(values), values[3]+values[4]
            old = self.previous; self.previous = total, idle
            cpu = max(0, min(100, 100*(1-(idle-old[1])/(total-old[0])))) if old and total>old[0] else 0
            disk = shutil.disk_usage(Path.home())
            self.status.set_text(f'CPU  {cpu:.0f}%\n{tr("磁盘")}  {(disk.total-disk.free)/2**30:.1f} / {disk.total/2**30:.1f} GiB')
        except (OSError, ValueError, IndexError): self.status.set_text(tr('无可用数据'))


class QuickActions(AsyncCard):
    def __init__(self, host):
        super().__init__(host, '快捷操作')
        self.state = {}; self.buttons = {}; self.updating = False;self.revision=0
        self.status.set_no_show_all(True); self.status.hide()
        row = Gtk.Box(spacing=8, homogeneous=True)
        for key, icon, title in [('wifi','network-wireless-symbolic','Wi-Fi'), ('bluetooth','bluetooth-active-symbolic','蓝牙')]:
            button = Gtk.ToggleButton(); contents = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=5)
            contents.pack_start(Gtk.Image.new_from_icon_name(icon,Gtk.IconSize.LARGE_TOOLBAR),False,False,0)
            text = Gtk.Label(label=tr(title)); contents.pack_start(text,False,False,0)
            button.add(contents); button.set_sensitive(False)
            button.connect('clicked',lambda _,key=key:self.toggle(key)); row.pack_start(button,True,True,0)
            self.buttons[key] = button
        for title, icon, command in [('设置','preferences-system-symbolic',('config',)),('剪贴板','edit-paste-symbolic',('clipboard',))]:
            button = Gtk.Button(); contents = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=5)
            contents.pack_start(Gtk.Image.new_from_icon_name(icon,Gtk.IconSize.LARGE_TOOLBAR),False,False,0)
            contents.pack_start(Gtk.Label(label=tr(title)),False,False,0); button.add(contents)
            button.connect('clicked',lambda _,command=command:host.launch(*command)); row.pack_start(button,True,True,0)
        self.box.pack_start(row,False,False,0); self.box.reorder_child(row,1)
        self.watch_visible(self.refresh,5)

    @staticmethod
    def snapshot():
        from adws_system_pages import network_snapshot, bluetooth_snapshot
        result = {}
        for key, operation in [('wifi',network_snapshot),('bluetooth',bluetooth_snapshot)]:
            try: result[key]=operation()
            except Exception: result[key]={}
        return result

    def refresh(self):
        revision=self.revision
        if not self.busy and self.box.get_mapped():
            self.job(self.snapshot,lambda result:self.loaded(result) if revision==self.revision else None)

    def loaded(self, data):
        self.state=data; self.updating=True
        for key, button in self.buttons.items():
            item=data.get(key,{})
            available = ('wifi' in item and any(row[1]=='wifi' for row in item.get('devices',[]))) if key=='wifi' else bool(item.get('adapter'))
            enabled = item.get('wifi' if key=='wifi' else 'powered') is True
            button.set_active(enabled); button.set_sensitive(available)
            button.set_tooltip_text(tr('已开启') if enabled else tr('已关闭') if available else tr('不可用'))
        self.updating=False; self.status.set_text(data.get('error') or ''); self.status.set_visible(bool(data.get('error')))

    def toggle(self,key):
        if self.updating: return
        from adws_system_pages import wifi_enabled, bluetooth_power
        desired=self.buttons[key].get_active();self.revision+=1
        for button in self.buttons.values():button.set_sensitive(False)
        def operation():
            error=None
            try: (wifi_enabled if key=='wifi' else bluetooth_power)(desired)
            except Exception as exc: error=str(exc)
            result=self.snapshot(); result['error']=error; return result
        self.job(operation,self.loaded,('toggle',key))

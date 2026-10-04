"""A single audio control surface: output, input, apps and optional hardware details."""
import math
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gtk
from adws_i18n import tr
import adws_native_services as backend
from adws_native_settings_gui import NativeSection, button, caption, choice, row
from adws_settings_widgets import compact_switch, settings_tabs


def snapshot():
    # No duplicate device scan, subscription or persistent polling process.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as pool:
        audio = pool.submit(backend.audio_advanced)
        output = pool.submit(backend.command, ['pactl', 'get-default-sink'])
        microphone = pool.submit(backend.command, ['pactl', 'get-default-source'])
        return {**audio.result(), 'default_sink': output.result().strip(),
                'default_source': microphone.result().strip()}


from adws_audio_values import usable_device, volume_percent


def device_choice(devices, active):
    if not devices:
        control = choice([('unavailable', tr('无可用配置'))], 'unavailable')
        control.set_sensitive(False)
        control.set_tooltip_text(tr('无可用配置'))
        return control
    # A stale default must not silently choose a different endpoint.
    return choice([(d['name'], d.get('description') or d['name']) for d in devices], active)

class AudioEdits:
    """Coalesce slider edits; serialize service writes without rebuilding sliders."""
    def __init__(self, section):
        self.section, self.pending, self.source = section, {}, 0
        self.closed = False
        self.generation = section.generation
        self.handlers = [(widget, widget.connect('destroy', self.close))
                         for widget in (section.content, section.box)]

    def close(self, *_):
        if self.closed: return
        self.closed = True
        self.pending.clear()
        if self.source: GLib.source_remove(self.source); self.source = 0
        for widget, handler in self.handlers:
            if widget.handler_is_connected(handler): widget.disconnect(handler)
        self.handlers.clear()

    def queue(self, kind, index, action, value):
        if self.closed or self.section.closed or self.section.generation != self.generation: return
        self.pending[(kind, index, action)] = value
        if not self.source: self.source = GLib.timeout_add(160, self.flush)

    def flush(self):
        if self.closed or self.section.closed or self.section.host.closed or self.section.generation != self.generation:
            self.source = 0
            self.close()
            return False
        if self.section.host.busy: return True
        self.source = 0
        if not self.pending: return False
        values, self.pending = self.pending, {}
        def apply():
            from adws_system_pages import audio_change
            for (kind, index, action), value in values.items():
                if kind in ('sink', 'source') and action in ('volume', 'mute'):
                    audio_change(kind, index, action, value)
                else: backend.audio_set(kind, index, action, value)
        def done():
            if self.pending and not self.closed and not self.source:
                self.source = GLib.timeout_add(160, self.flush)
        def failed():
            self.pending.clear()
            if not self.closed: self.section.refresh()
        self.section.host.run_worker(apply, done, on_failure=failed)
        return False


def sound_sections(host, parent):
    state = {'tab': 'output', 'edits': None}
    def render(section, data):
        if state['edits']: state['edits'].close()
        edits = state['edits'] = AudioEdits(section)
        pages = {key: Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
                 for key in ('output', 'input', 'apps', 'hardware')}
        tabs = settings_tabs([(key, tr(title), pages[key]) for key, title in
                             [('output', '输出'), ('input', '输入'), ('apps', '应用音量'), ('hardware', '高级')]])
        tabs.stack.set_visible_child_name(state['tab'])
        tabs.stack.connect('notify::visible-child-name', lambda stack, _: state.update(tab=stack.get_visible_child_name()))
        section.content.pack_start(tabs, False, False, 0)

        def card(parent, title, description=None, icon=None):
            panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            panel.get_style_context().add_class('audio-device-card')
            header = Gtk.Box(spacing=12)
            if icon:
                image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.DIALOG)
                image.set_pixel_size(32); header.pack_start(image, False, False, 0)
            labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            labels.pack_start(caption(title, 'settings-section-title'), False, False, 0)
            if description: labels.pack_start(caption(description, 'dim-label'), False, False, 0)
            header.pack_start(labels, True, True, 0)
            panel.pack_start(header, False, False, 0)
            parent.pack_start(panel, False, False, 0)
            return panel

        def volume(panel, item, kind):
            level = volume_percent(item)
            line = Gtk.Box(spacing=12)
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
            scale.set_hexpand(True); scale.set_digits(0); scale.set_value(min(100, level))
            scale.set_value_pos(Gtk.PositionType.RIGHT); scale.set_tooltip_text(tr('音量'))
            line.pack_start(scale, True, True, 0)
            line.pack_start(caption('静音'), False, False, 0)
            mute = compact_switch(Gtk.Switch(active=bool(item.get('mute', False))))
            line.pack_end(mute, False, False, 0)
            panel.pack_start(line, False, False, 0)
            # Signal wiring follows initialization: opening a page never changes audio.
            scale.connect('value-changed', lambda control: edits.queue(kind, item['index'], 'volume', control.get_value()))
            mute.connect('notify::active', lambda control, _: edits.queue(kind, item['index'], 'mute', control.get_active()))
            if level > 100:
                panel.pack_start(caption('设备音量高于 100%；调整滑块才会降低音量。', 'dim-label'), False, False, 0)

        devices_by_kind = {kind: [d for d in data.get(collection, []) if usable_device(d)]
                           for kind, collection in [('sink', 'sinks'), ('source', 'sources')]}
        for key, collection, kind, title, default, empty, icon in [
                ('output', 'sinks', 'sink', '默认输出设备', 'default_sink', '未检测到声音输出设备。', 'audio-speakers-symbolic'),
                ('input', 'sources', 'source', '默认输入设备', 'default_source', '未检测到麦克风。', 'audio-input-microphone-symbolic')]:
            devices = devices_by_kind[kind]
            selected = device_choice(devices, data.get(default))
            row(pages[key], title, selected)
            if not devices:
                pages[key].pack_start(caption('无可用配置', 'dim-label'), False, False, 0); continue
            def select(control, k=kind, ds=devices):
                device = next((d for d in ds if d['name'] == control.get_active_id()), None)
                if device:
                    from adws_system_pages import audio_change
                    section.change(lambda: audio_change(k, device['index'], 'default', device['name']))
            selected.connect('changed', select)
            for device in devices:
                panel = card(pages[key], device.get('description') or device['name'],
                             tr('默认设备') if device['name'] == data.get(default) else None, icon)
                volume(panel, device, kind)

        for collection, kind, targets, target in [
                ('sink-inputs', 'sink-input', 'sinks', 'sink'), ('source-outputs', 'source-output', 'sources', 'source')]:
            for item in data[collection]:
                props = item.get('properties', {})
                name = props.get('application.name') or props.get('media.name') or item.get('name') or str(item['index'])
                panel = card(pages['apps'], name, tr('播放') if kind == 'sink-input' else tr('录音'),
                             'audio-x-generic-symbolic' if kind == 'sink-input' else 'audio-input-microphone-symbolic')
                volume(panel, item, kind)
                device = choice([(str(d['index']), d.get('description') or d['name']) for d in devices_by_kind[target]], item.get(target))
                if not devices_by_kind[target]:
                    device = device_choice([], None)
                device.connect('changed', lambda control, k=kind, i=item['index']:
                               section.change(lambda value=int(control.get_active_id()): backend.audio_set(k, i, 'move', value))
                               if control.get_active_id() is not None else None)
                row(panel, '播放设备' if kind == 'sink-input' else '录音设备', device)
        if not data['sink-inputs'] and not data['source-outputs']:
            pages['apps'].pack_start(caption('当前没有正在播放或录音的应用。', 'dim-label'), False, False, 0)
        pages['hardware'].pack_start(caption('设备模式、插孔与独立声道。通常无需修改。', 'dim-label'), False, False, 0)
        for device in data['cards']:
            profiles = device.get('profiles', {})
            if isinstance(profiles, list): profiles = {p['name']: p for p in profiles}
            active = device.get('active_profile', '')
            if isinstance(active, dict): active = active.get('name', '')
            selector = choice([(k, p.get('description', k)) for k, p in profiles.items() if p.get('available') != 'no'], active)
            selector.connect('changed', lambda control, i=device['index']:
                             section.change(lambda value=control.get_active_id(): backend.audio_set('card', i, 'profile', value)))
            row(pages['hardware'], device.get('properties', {}).get('device.description') or device.get('name', ''), selector)
        for collection, kind in [('sinks', 'sink'), ('sources', 'source')]:
            for device in data[collection]:
                if not usable_device(device): continue
                ports = device.get('ports', [])
                if isinstance(ports, dict): ports = [{'name': k, **v} for k, v in ports.items()]
                active = device.get('active_port', '')
                if isinstance(active, dict): active = active.get('name', '')
                panel = card(pages['hardware'], device.get('description') or device['name'])
                if ports:
                    selector = choice([(p['name'], p.get('description', p['name'])) for p in ports
                                       if p.get('availability') not in ('no', 'not available')], active)
                    selector.connect('changed', lambda control, k=kind, i=device['index']:
                                     section.change(lambda value=control.get_active_id(): backend.audio_set(k, i, 'port', value)))
                    row(panel, '接口', selector)
                levels = []
                for channel, channel_data in device.get('volume', {}).items():
                    value = Gtk.SpinButton.new_with_range(0, 100, 1)
                    value.set_value(min(100, volume_percent({'volume': {channel: channel_data}})))
                    levels.append(value); row(panel, channel, value)
                if levels:
                    apply = button('应用声道音量', lambda k=kind, i=device['index'], cs=levels:
                                   section.change(lambda values=[c.get_value() for c in cs]: backend.audio_set(k, i, 'channels', values)))
                    apply.set_halign(Gtk.Align.END); panel.pack_start(apply, False, False, 0)
    section = NativeSection(host, parent, '声音控制', snapshot, render, 'sound-server')
    return section


class SoundSettingsPage:
    def __init__(self, host):
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.section = sound_sections(host, self.box)
    def refresh(self, *_): self.section.refresh()

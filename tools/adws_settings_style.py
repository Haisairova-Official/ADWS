"""ADWS settings visual language, using the same live palette as its panel."""
from pathlib import Path
import os
from gi.repository import Gdk, Gtk
from adws_theme import Watch, css_snapshot

ROLES = {
    'bg': ('surface', '#18191f'), 'surface': ('surface_container', '#24252e'),
    'raised': ('surface_container_high', '#30313c'), 'text': ('on_surface', '#eeeeF4'),
    'muted': ('on_surface_variant', '#c8c5d0'), 'accent': ('primary', '#c6baff'),
    'on_accent': ('on_primary', '#302458'), 'outline': ('outline_variant', '#484652'),
    'error': ('error', '#ffb4ab'),
}

STYLE = '''
.adws-system-settings { background: @adws_settings_bg; color: @adws_settings_text; }
.adws-system-settings decoration { margin: 0; padding: 0; border-radius: 20px; border: 1px solid alpha(@adws_settings_outline, .75); background: transparent; box-shadow: none; }
.adws-system-settings headerbar { background: @adws_settings_bg; color: @adws_settings_text; border: none; box-shadow: none; min-height: 38px; padding: 5px 14px; }
.adws-system-settings headerbar .title { font-size: .92em; font-weight: 500; }
.adws-system-settings headerbar button { background: transparent; min-width: 26px; min-height: 26px; padding: 2px; }
.adws-system-settings label { color: inherit; }
.adws-system-settings .dim-label, .adws-system-settings .settings-caption { color: @adws_settings_muted; opacity: .86; }
.adws-system-settings .settings-sidebar { background: @adws_settings_bg; padding: 0 6px; }
.adws-system-settings .settings-brand { font-size: 1.65em; font-weight: 800; letter-spacing: 2px; color: @adws_settings_accent; }
.adws-system-settings .settings-sidebar list, .adws-system-settings viewport { background: transparent; }
.adws-system-settings .settings-sidebar row { color: @adws_settings_text; background: transparent; border-radius: 12px; margin: 2px 0; padding: 0; border: 1px solid transparent; transition: background-color 140ms ease; }
.adws-system-settings .settings-sidebar row:hover { background: alpha(@adws_settings_accent,.07); }
.adws-system-settings .settings-sidebar row:selected { background: alpha(@adws_settings_accent,.16); color: @adws_settings_accent; border-color: alpha(@adws_settings_accent,.13); }
.adws-system-settings .settings-sidebar row:selected image { color: @adws_settings_accent; }
.adws-system-settings .settings-detail { background: @adws_settings_surface; border-radius: 24px 0 0 0; }
.adws-system-settings .settings-card { padding: 20px; border: 1px solid alpha(@adws_settings_outline,.4); border-radius: 18px; background: alpha(@adws_settings_raised,.56); }
.adws-system-settings .settings-page-title { font-size: 1.9em; font-weight: 700; }
.adws-system-settings .settings-section-title { font-size: 1.05em; font-weight: 700; }
.adws-system-settings .settings-group { font-size: .84em; color: @adws_settings_muted; padding: 17px 10px 6px; }
.adws-system-settings .settings-breadcrumb { font-size: .82em; color: @adws_settings_accent; }
.adws-system-settings .settings-hero { border-radius: 20px; padding: 25px; background: alpha(@adws_settings_accent,.09); border: 1px solid alpha(@adws_settings_accent,.18); }
.adws-system-settings .settings-hero-title { font-size: 1.65em; font-weight: 700; }
.adws-system-settings .settings-shortcut { border-radius: 16px; padding: 18px; border: 1px solid alpha(@adws_settings_outline,.5); background: @adws_settings_raised; }
.adws-system-settings .settings-shortcut:hover { background: alpha(@adws_settings_accent,.13); border-color: alpha(@adws_settings_accent,.4); }
.adws-system-settings .settings-shortcut image { color: @adws_settings_accent; }
.adws-system-settings .settings-footer { background: @adws_settings_bg; padding: 12px 22px; }
.adws-system-settings button, .adws-settings-popover button { background-image: none; background-color: alpha(@adws_settings_text,.055); color: @adws_settings_text; border: 1px solid alpha(@adws_settings_outline,.65); box-shadow: none; text-shadow: none; border-radius: 10px; padding: 8px 12px; min-height: 22px; transition: background-color 140ms ease; }
.adws-system-settings button:hover, .adws-settings-popover button:hover { background-color: alpha(@adws_settings_accent,.13); border-color: alpha(@adws_settings_accent,.4); }
.adws-system-settings button:checked { background-color: alpha(@adws_settings_accent,.18); color: @adws_settings_accent; border-color: alpha(@adws_settings_accent,.45); }
.adws-system-settings button.suggested-action { background-color: @adws_settings_accent; color: @adws_settings_on_accent; border-color: @adws_settings_accent; font-weight: 700; }
.adws-system-settings button.suggested-action:hover { background-color: shade(@adws_settings_accent,1.08); }
.adws-system-settings button:disabled { opacity: .48; }
.adws-system-settings button.settings-account-header { background: transparent; border-color: transparent; border-radius: 14px; padding: 9px 6px; }
.adws-system-settings button.settings-account-header:hover { background: alpha(@adws_settings_accent,.08); border-color: alpha(@adws_settings_accent,.14); }
.adws-system-settings .settings-account-name { font-size: 1.12em; font-weight: 700; }
.adws-system-settings .settings-account-username { font-size: .82em; }
.adws-system-settings .settings-account-role { font-size: .75em; color: @adws_settings_accent; background: alpha(@adws_settings_accent,.1); padding: 2px 6px; border-radius: 6px; margin-top: 3px; }
.adws-system-settings entry, .adws-system-settings spinbutton, .adws-settings-popover entry { background: alpha(@adws_settings_bg,.7); color: @adws_settings_text; border: 1px solid alpha(@adws_settings_outline,.7); border-radius: 10px; padding: 8px 10px; min-height: 22px; box-shadow: none; }
.adws-system-settings entry:focus, .adws-system-settings spinbutton:focus { border-color: @adws_settings_accent; box-shadow: 0 0 0 2px alpha(@adws_settings_accent,.1); }
.adws-system-settings entry.error { border-color: @adws_settings_error; }
.adws-system-settings .settings-input-error { color: @adws_settings_error; }
.adws-system-settings spinbutton entry { border: none; background: none; padding: 0; }
.adws-system-settings spinbutton button { border: none; background: transparent; padding: 0 7px; }
.adws-system-settings .settings-subnav { padding: 3px; background: alpha(@adws_settings_raised,.55); border-radius: 12px; }
.adws-system-settings .settings-subnav button { min-width: 0; border: 1px solid transparent; background: transparent; padding: 7px 17px; border-radius: 9px; }
.adws-system-settings .settings-subnav button:checked { background: alpha(@adws_settings_accent,.18); color: @adws_settings_accent; border-color: alpha(@adws_settings_accent,.25); }
.adws-system-settings .audio-device-card { padding: 17px; border-radius: 14px; background: alpha(@adws_settings_raised,.45); border: 1px solid alpha(@adws_settings_outline,.4); }
.adws-system-settings .settings-profile-choice { padding: 16px; }
.adws-system-settings .settings-profile-choice.selected-profile { border-color: @adws_settings_accent; background: alpha(@adws_settings_accent,.13); }
.adws-system-settings .settings-user-avatar { background: alpha(@adws_settings_accent,.1); border-radius: 50%; padding: 3px; }
.adws-system-settings switch { min-width: 42px; min-height: 22px; border-radius: 16px; background: @adws_settings_outline; border: none; }
.adws-system-settings switch:checked { background: @adws_settings_accent; }
.adws-system-settings switch slider { min-width: 18px; min-height: 18px; margin: 2px; border-radius: 50%; background: @adws_settings_text; border: none; box-shadow: none; }
.adws-system-settings switch:checked slider { background: @adws_settings_on_accent; }
.adws-system-settings check, .adws-system-settings radio { background: transparent; color: @adws_settings_on_accent; border: 2px solid @adws_settings_outline; border-radius: 5px; min-width: 15px; min-height: 15px; }
.adws-system-settings check:checked, .adws-system-settings radio:checked { background: @adws_settings_accent; border-color: @adws_settings_accent; }
.adws-system-settings scale trough { background: @adws_settings_outline; border: none; border-radius: 9px; min-height: 5px; }
.adws-system-settings scale highlight { background: @adws_settings_accent; border-radius: 9px; }
.adws-system-settings scale slider { background: @adws_settings_accent; border: none; min-width: 16px; min-height: 16px; box-shadow: none; }
.adws-system-settings scrollbar { background: transparent; }
.adws-system-settings scrollbar slider { background: alpha(@adws_settings_muted,.28); border-radius: 8px; min-width: 5px; min-height: 32px; border: 3px solid transparent; }
.adws-system-settings separator { background: alpha(@adws_settings_outline,.5); min-height: 1px; }
.adws-settings-popover { background: @adws_settings_raised; color: @adws_settings_text; border: 1px solid @adws_settings_outline; border-radius: 16px; padding: 8px; }
.adws-settings-popover list, .adws-settings-popover scrolledwindow, .adws-settings-popover viewport { background: transparent; }
.adws-settings-popover row { border-radius: 8px; padding: 10px 12px; color: @adws_settings_text; }
.adws-settings-popover row:hover, .adws-settings-popover row:selected { background: alpha(@adws_settings_accent,.16); color: @adws_settings_accent; }
.adws-system-settings .layout-component { padding: 12px; border-radius: 14px; }
.adws-system-settings .layout-component.selected-component { background: alpha(@adws_settings_accent,.14); border-color: alpha(@adws_settings_accent,.7); }
.adws-system-settings .layout-inspector { padding: 16px; border: 1px solid alpha(@adws_settings_outline,.45); border-radius: 16px; background: alpha(@adws_settings_raised,.6); }
.adws-system-settings .layout-zone-preview { padding: 10px 18px; border: 1px solid alpha(@adws_settings_outline,.4); border-radius: 12px; background: alpha(@adws_settings_raised,.5); }

'''

class SettingsStyle:
    def __init__(self, host):
        self.host, self.provider, self.colors = host, None, {}
        from adws_layout import USER_LAYOUT_PATH
        self.paths = [host.config.live_style_path().parent / 'colors.css', host.config.live_style_path(), USER_LAYOUT_PATH]
        self.reload()
        self.watch = Watch(self.paths, self.reload, host)

    def reload(self):
        colors = {}
        # Include generated palette imports and keep the last complete palette
        # when a generator is halfway through replacing its output.
        for path, content in css_snapshot(self.paths[:1]).items():
            if content is not None:
                colors.update(self.host.config.read_colors(path))
        if self.colors and not colors:
            return False
        if self.colors and any(source in self.colors and source not in colors for source, _ in ROLES.values()):
            return False
        roles = {}
        for role, (source, fallback) in ROLES.items():
            value = self.host.config.resolve_color(colors.get(source, fallback), colors)
            rgba = Gdk.RGBA()
            if not rgba.parse(value):
                return False
            roles[role] = rgba.to_string()
        definitions = '\n'.join(f'@define-color adws_settings_{key} {value};' for key, value in roles.items())
        candidate = Gtk.CssProvider()
        from adws_layout import load_layout
        from adws_panel_options import validate
        options = validate(load_layout().get('options', {}))
        duration = str(options['animation_duration']) + 'ms' if options['tab_animations'] else '0ms'
        if hasattr(self.host, 'stack'):
            self.host.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE if options['tab_animations'] else Gtk.StackTransitionType.NONE)
            self.host.stack.set_transition_duration(options['animation_duration'])
        candidate.load_from_data((definitions + '\n' + self.stylesheet(roles, options).replace('140ms', duration)).encode())
        screen = self.host.get_screen()
        Gtk.StyleContext.add_provider_for_screen(screen, candidate, Gtk.STYLE_PROVIDER_PRIORITY_USER + 10)
        if self.provider:
            Gtk.StyleContext.remove_provider_for_screen(screen, self.provider)
        self.provider, self.colors = candidate, colors
        self.host.queue_draw()
        return True

    def stylesheet(self, roles, options):
        return STYLE

    def close(self):
        self.watch.close()
        if self.provider:
            Gtk.StyleContext.remove_provider_for_screen(self.host.get_screen(), self.provider)
            self.provider = None


class PanelStyle(SettingsStyle):
    """Quick controls use the panel's material and configured corner geometry."""
    def stylesheet(self, roles, options):
        from adws_panel_options import material_css
        _, color, radius, family, size = self.host.config.read_taskbar_overrides()
        base = options['surface_color'] or Gdk.RGBA(*color).to_string()
        # Material palette names follow the taskbar's original roles.
        aliases = {'surface_container_high':'raised','primary':'accent','on_surface':'text'}
        definitions = '\n'.join(f'@define-color {key} {roles[role]};' for key,role in aliases.items())
        material = material_css(options, base)
        radius = max(0, radius)
        return definitions + '\n' + STYLE + f"""
        window.adws-quick-panel {{ {material} border-radius: {radius:g}px; border: 1px solid alpha(@adws_settings_outline,.65); }}
        window.adws-quick-panel decoration {{ background: transparent; border-radius: {radius:g}px; }}
        window.adws-quick-panel > box {{ background: transparent; border-radius: {radius:g}px; }}
        """

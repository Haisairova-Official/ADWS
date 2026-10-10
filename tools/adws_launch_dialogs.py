"""Compact authorization and launch errors, sharing ADWS's live palette."""
import importlib.util
from pathlib import Path
import sys
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gtk, Pango
from adws_i18n import tr
from adws_settings_style import SettingsStyle


class DialogStyle(SettingsStyle):
    def stylesheet(self, roles, options):
        return super().stylesheet(roles, options) + '''
        .adws-launch-dialog headerbar { border-radius: 18px 18px 0 0; }
        .adws-launch-dialog .dialog-title { font-size: 1.2em; font-weight: 700; }
        .adws-launch-dialog .dialog-symbol { color: @adws_settings_accent; }
        .adws-launch-dialog .dialog-status { color: @adws_settings_error; }
        .adws-launch-dialog .dialog-account { border-radius: 10px; background: alpha(@adws_settings_text,.04); padding: 10px 12px; }
        .adws-launch-dialog entry { min-height: 28px; }
        .adws-launch-dialog .dialog-actions { padding: 12px 24px 20px; border-top: 1px solid alpha(@adws_settings_outline,.35); }
        '''


def label(text, css=None):
    widget = Gtk.Label(label=text, xalign=0)
    widget.set_line_wrap(True)
    widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    widget.set_max_width_chars(48)
    if css: widget.get_style_context().add_class(css)
    return widget


class CompactDialog(Gtk.Dialog):
    def __init__(self, host, title, heading, description, icon='dialog-password-symbolic', accept='授权'):
        super().__init__(title=tr(title), transient_for=host, modal=True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_default_size(440, -1)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.get_style_context().add_class('adws-system-settings')
        self.get_style_context().add_class('adws-launch-dialog')
        self.set_titlebar(Gtk.HeaderBar(title=tr(title), show_close_button=True))
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=24)
        self.get_content_area().pack_start(self.body, True, True, 0)
        lead = Gtk.Box(spacing=14)
        image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.DIALOG)
        image.get_style_context().add_class('dialog-symbol')
        image.set_valign(Gtk.Align.START)
        lead.pack_start(image, False, False, 0)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.heading = label(heading, 'dialog-title')
        self.description = label(description, 'dim-label')
        texts.pack_start(self.heading, False, False, 0)
        texts.pack_start(self.description, False, False, 0)
        lead.pack_start(texts, True, True, 0)
        self.body.pack_start(lead, False, False, 0)
        self.get_action_area().get_style_context().add_class('dialog-actions')
        if accept:
            self.add_button(tr('取消'), Gtk.ResponseType.CANCEL)
            button = self.add_button(tr(accept), Gtk.ResponseType.OK)
            button.get_style_context().add_class('suggested-action')
            self.set_default_response(Gtk.ResponseType.OK)
        else:
            self.add_button(tr('关闭'), Gtk.ResponseType.CLOSE)
        self.config = getattr(host, 'config', None)
        if self.config is None:
            name = 'adws_dialog_config'
            if name not in sys.modules:
                spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name('adws-config.py'))
                config = importlib.util.module_from_spec(spec)
                sys.modules[name] = config
                spec.loader.exec_module(config)
            self.config = sys.modules[name]
        self.visual_style = DialogStyle(self)
        self.connect('destroy', lambda *_: self.visual_style.close())

    def details(self, text):
        expander = Gtk.Expander(label=tr('详细信息'))
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(90)
        scroll.set_max_content_height(160)
        scroll.set_propagate_natural_height(True)
        detail = label(text, 'dim-label')
        detail.set_selectable(True)
        scroll.add(detail)
        expander.add(scroll)
        self.body.pack_start(expander, False, False, 0)


def show_launch_error(message):
    summary, _, details = message.partition('\n\n')
    dialog = CompactDialog(None, '无法启动应用', tr('无法启动应用'), summary,
                           icon='dialog-error-symbolic', accept=None)
    if details: dialog.details(details)
    dialog.show_all()
    dialog.present()
    dialog.run()
    dialog.destroy()

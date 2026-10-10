"""Nonblocking application selection; selected files never become shell text."""
from gi.repository import Gio, Gtk
from .i18n import tr


def choose(parent, paths, on_error):
    paths = list(paths)
    if not paths: return None
    import sys
    from pathlib import Path
    tools = str(Path(__file__).resolve().parents[3]/'tools')
    if tools not in sys.path: sys.path.insert(0, tools)
    from adws_settings_widgets import ApplicationChoice, enhance_choices
    first = Gio.File.new_for_path(str(paths[0]))
    try:
        content_type = first.query_info('standard::content-type', Gio.FileQueryInfoFlags.NONE, None).get_content_type()
    except Exception:
        content_type = 'application/octet-stream'
    dialog = Gtk.Dialog(title=tr('用指定应用打开'), transient_for=parent, modal=True)
    dialog.set_default_size(420, 180); dialog.set_resizable(False)
    dialog.add_buttons(tr('取消'), Gtk.ResponseType.CANCEL, tr('打开'), Gtk.ResponseType.OK)
    area = dialog.get_content_area(); area.set_border_width(18); area.set_spacing(12)
    chooser = ApplicationChoice(content_type)
    area.pack_start(chooser, False, False, 0)
    dialog.set_response_sensitive(Gtk.ResponseType.OK, chooser.get_app_info() is not None)
    chooser.connect('changed', lambda *_: dialog.set_response_sensitive(Gtk.ResponseType.OK, chooser.get_app_info() is not None))
    enhance_choices(area, translate=tr)
    def response(_, code):
        app = chooser.get_app_info()
        dialog.destroy()
        if code != Gtk.ResponseType.OK or app is None: return
        try:
            app.launch([Gio.File.new_for_path(str(path)) for path in paths], parent.get_display().get_app_launch_context())
        except Exception as exc: on_error(str(exc))
    dialog.connect('response', response)
    dialog.show_all()
    return dialog

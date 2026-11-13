"""Name prompts for files in a desktop icon group's own directory."""
from concurrent.futures import Future
from pathlib import Path

from gi.repository import GLib, Gtk, Pango

from adws_i18n import tr


def valid_name(name):
    if not name.strip() or name in ('.', '..') or '/' in name or '\x00' in name:
        raise ValueError(tr('名称不能为空，不能包含 /，也不能是 . 或 ..'))
    return name


def prompt_name(manager, view, title, directory, initial_name, submit, accept_label, *, select_stem=False):
    dialog = manager.settings_dialog(view, title)
    accept = dialog.get_widget_for_response(Gtk.ResponseType.OK)
    accept.set_label(accept_label)
    dialog.set_default_response(Gtk.ResponseType.OK)

    form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=16)
    location = Gtk.Label(label=str(directory), xalign=0)
    location.set_max_width_chars(48)
    location.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
    location.set_tooltip_text(str(directory))
    location.get_style_context().add_class('dim-label')
    field = Gtk.Entry(text=initial_name, activates_default=True, width_chars=32)
    field.get_accessible().set_name(tr('名称'))
    error = Gtk.Label(xalign=0)
    error.set_max_width_chars(44)
    error.set_line_wrap(True)
    error.get_style_context().add_class('error')
    error.set_no_show_all(True)
    for control in (location, field, error):
        form.pack_start(control, False, False, 0)
    dialog.get_content_area().add(form)

    busy = False
    closed = False
    def set_busy(value):
        nonlocal busy
        busy = value
        form.set_sensitive(not value)
        accept.set_sensitive(not value)
        dialog.set_response_sensitive(Gtk.ResponseType.CANCEL, not value)
        dialog.set_deletable(not value)

    def show_error(exc):
        message = tr('已有同名项目，请换一个名称。') if isinstance(exc, FileExistsError) else str(exc)
        error.set_text(message)
        error.show()
        field.grab_focus()

    def success():
        dialog.destroy()
        if not manager.closed:
            manager.refresh()

    def finished(future):
        if closed:
            return GLib.SOURCE_REMOVE
        try:
            future.result()
        except (OSError, ValueError, GLib.Error) as exc:
            set_busy(False)
            show_error(exc)
        else:
            success()
        return GLib.SOURCE_REMOVE

    def response(_dialog, result):
        if busy:
            return
        if result != Gtk.ResponseType.OK:
            dialog.destroy()
            return
        try:
            work = submit(valid_name(field.get_text()))
        except (OSError, ValueError, GLib.Error) as exc:
            show_error(exc)
            return
        if isinstance(work, Future):
            set_busy(True)
            work.add_done_callback(lambda future: GLib.idle_add(finished, future))
        else:
            success()

    # Keep a filename prompt alive across scans that rebuild the group's card.
    parent_handler = view.connect('destroy', lambda *_: dialog.destroy())
    def destroyed(*_):
        nonlocal closed
        closed = True
        if view.handler_is_connected(parent_handler):
            view.disconnect(parent_handler)
    dialog.connect('destroy', destroyed)
    dialog.connect('response', response)
    field.connect('changed', lambda *_: error.hide())
    dialog.show_all()
    field.grab_focus()
    field.select_region(0, len(Path(initial_name).stem) if select_stem else -1)
    dialog.present()
    return dialog


def create_item(directory, name, kind):
    target = directory / valid_name(name)
    if kind == 'folder':
        target.mkdir()
    elif kind in ('text', 'markdown'):
        with target.open('x', encoding='utf-8') as stream:
            if kind == 'markdown':
                stream.write(tr('# 新文档\n'))
    else:
        raise ValueError(kind)


def new_item(card, kind):
    manager = card.manager
    directory = Path(card.row['directory'])
    title, suffix = {
        'folder': (tr('新建文件夹'), ''),
        'text': (tr('新建文本文档'), '.txt'),
        'markdown': (tr('新建 Markdown 文档'), '.md'),
    }[kind]
    entries, _error = manager.cache.get(str(directory), ([], None))
    names = {entry.path.name for entry in entries}
    suggestion = title + suffix
    index = 1
    while suggestion in names:
        index += 1
        suggestion = f'{title} ({index}){suffix}'
    return prompt_name(manager, card.layer.window, title, directory, suggestion,
                       lambda name: manager.pool.submit(create_item, directory, name, kind),
                       tr('创建'), select_stem=bool(suffix))

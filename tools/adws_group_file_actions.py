"""File actions scoped to the entry clicked in a desktop icon group."""
import ctypes
import errno
import os
from pathlib import Path

from gi.repository import Gio, GLib, Gtk

from adws_group_names import prompt_name, valid_name
from adws_i18n import tr


def launcher_display_name(entry):
    return entry.kind in ('application', 'link') and not entry.error and not entry.path.is_symlink()


def rename_on_disk(entry, new_name):
    """Rename a file in place, or update a regular desktop launcher's visible name."""
    valid_name(new_name)
    path = entry.path
    if launcher_display_name(entry):
        if new_name == entry.name:
            return path
        file = Gio.File.new_for_path(str(path))
        _, contents, etag = file.load_contents(None)
        data = GLib.KeyFile()
        data.load_from_data(contents.decode('utf-8'), len(contents),
                            GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
        for key in data.get_keys('Desktop Entry')[0]:
            if key == 'Name' or key.startswith('Name['):
                data.set_string('Desktop Entry', key, new_name)
        payload, _ = data.to_data()
        file.replace_contents(payload.encode('utf-8'), etag, False, Gio.FileCreateFlags.NONE, None)
        return path
    target = path.with_name(new_name)
    if target == path:
        return path
    # Gio.File.move(NONE) can race its destination existence check. A single
    # same-filesystem rename must protect files, directories and dangling links.
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, 'renameat2', None)
    if renameat2 is None:
        raise OSError(errno.ENOTSUP, os.strerror(errno.ENOTSUP))
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(path), -100, os.fsencode(target), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))
    return target


def matching_folders(directories, source_folder):
    matches = {source_folder}
    for path in directories - matches:
        try:
            if path.samefile(source_folder):
                matches.add(path)
        except OSError:
            continue
    return matches


def rename_cells(rows, source, target, folders):
    """All groups bound to this directory keep their own position for the icon."""
    if source == target:
        return
    for row in rows:
        if Path(row['directory']) in folders and source.name in row['cells']:
            row['cells'][target.name] = row['cells'].pop(source.name)


def rename(card, entry):
    manager, view = card.manager, card.layer.window
    def submit(name):
        candidates = {Path(row['directory']) for row in manager.data['groups']
                      if entry.path.name in row['cells']}
        def move():
            target = rename_on_disk(entry, name)
            folders = matching_folders(candidates, entry.path.parent) if target != entry.path else set()
            return target, folders
        work = manager.pool.submit(move)
        def moved(future):
            if not future.cancelled() and future.exception() is None and not manager.closed:
                target, folders = future.result()
                rename_cells(manager.data['groups'], entry.path, target, folders)
                manager.save()
            return GLib.SOURCE_REMOVE
        work.add_done_callback(lambda future: GLib.idle_add(moved, future))
        return work
    launcher = launcher_display_name(entry)
    name = entry.name if launcher else entry.path.name
    return prompt_name(manager, view, tr('重命名'), entry.path.parent, name, submit, tr('重命名'),
                       select_stem=entry.kind == 'file' and not launcher)


def properties(card, entry):
    return card.layer.window.show_properties([entry])


def trash(card, entry):
    manager = card.manager
    dialog = Gtk.MessageDialog(title=tr('移到回收站'), message_type=Gtk.MessageType.QUESTION,
                               buttons=Gtk.ButtonsType.NONE, text=tr('将此项目移到回收站？'))
    # A normal toplevel keeps Wayland focus and IME popups independent of the layer surface.
    if isinstance(manager.application, Gtk.Application):
        dialog.set_application(manager.application)
    dialog.get_style_context().add_class('adws-group-editor')
    dialog.format_secondary_text(str(entry.path))
    dialog.add_button(tr('取消'), Gtk.ResponseType.CANCEL)
    confirm = dialog.add_button(tr('移到回收站'), Gtk.ResponseType.ACCEPT)
    confirm.get_style_context().add_class('destructive-action')
    dialog.set_default_response(Gtk.ResponseType.CANCEL)
    view = card.layer.window
    closed = False
    def destroyed(*_):
        nonlocal closed
        closed = True
        if view.handler_is_connected(view_handler):
            view.disconnect(view_handler)
    view_handler = view.connect('destroy', lambda *_: dialog.destroy())
    dialog.connect('destroy', destroyed)
    busy = False

    def complete(file, result):
        nonlocal busy
        try:
            file.trash_finish(result)
        except GLib.Error as error:
            if closed:
                return
            busy = False
            dialog.set_deletable(True)
            dialog.set_property('message-type', Gtk.MessageType.ERROR)
            dialog.set_property('text', tr('无法移到回收站'))
            dialog.format_secondary_text(f'{entry.path}\n{error.message}')
            confirm.hide()
            cancel = dialog.get_widget_for_response(Gtk.ResponseType.CANCEL)
            cancel.set_label(tr('关闭'))
            cancel.set_sensitive(True)
            return
        if not manager.closed:
            manager.refresh()
        if not closed:
            dialog.destroy()

    def respond(_dialog, response):
        nonlocal busy
        if busy:
            return
        if response != Gtk.ResponseType.ACCEPT:
            dialog.destroy()
            return
        busy = True
        dialog.set_deletable(False)
        dialog.set_response_sensitive(Gtk.ResponseType.ACCEPT, False)
        dialog.set_response_sensitive(Gtk.ResponseType.CANCEL, False)
        source = Gio.File.new_for_path(str(entry.path))
        source.trash_async(GLib.PRIORITY_DEFAULT, None, complete)

    dialog.connect('response', respond)
    dialog.show_all()
    return dialog

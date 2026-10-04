"""XDG login applications; modify only per-user overrides on explicit actions."""
import os
import tempfile
from pathlib import Path
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gtk, Gio, Gdk
from adws_i18n import tr

TRANSLATIONS = {
 '登录启动应用':'Login applications', '选择登录后自动启动的应用。修改只影响当前用户。':'Choose apps to launch after login. Changes affect only your account.',
 '添加应用':'Add application','尚未配置登录应用。':'No login applications configured.',
 '选择自启应用':'Choose a login application', '你的桌面会话需要支持 XDG 登录自启。':'Your desktop session must support XDG autostart.',
 '登录自启':'Launch at login', '无法读取自启项目':'Could not read login entry',
 '删除启动项：%s':'Delete login entry: %s',
 '启动项：%s\n确定要删除该启动项吗？':'Login entry: %s\nAre you sure you want to delete this login entry?',
}


def user_dir():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'autostart'


def read_entries():
    paths = {}
    dirs = [Path(p)/'autostart' for p in os.environ.get('XDG_CONFIG_DIRS','/etc/xdg').split(':') if p]
    for directory in [*reversed(dirs), user_dir()]:
        for path in sorted(directory.glob('*.desktop')):
            paths[path.name] = path
    result = []
    desktops = set(os.environ.get('XDG_CURRENT_DESKTOP','').split(':'))
    for name, path in paths.items():
        data = GLib.KeyFile()
        try:
            data.load_from_file(str(path), GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
            if data.get_string('Desktop Entry','Type') != 'Application':
                continue
            only = set(data.get_string_list('Desktop Entry','OnlyShowIn')) if 'OnlyShowIn' in data.get_keys('Desktop Entry')[0] else set()
            exclude = set(data.get_string_list('Desktop Entry','NotShowIn')) if 'NotShowIn' in data.get_keys('Desktop Entry')[0] else set()
            if (only and not only.intersection(desktops)) or exclude.intersection(desktops):
                continue
            keys = data.get_keys('Desktop Entry')[0]
            if 'X-ADWS-Removed' in keys and data.get_boolean('Desktop Entry','X-ADWS-Removed'):
                continue
            hidden = data.get_boolean('Desktop Entry','Hidden') if 'Hidden' in data.get_keys('Desktop Entry')[0] else False
            result.append((name, data.get_locale_string('Desktop Entry','Name',None), not hidden, data))
        except GLib.Error:
            continue
    return result


def set_enabled(name, data, enabled):
    if Path(name).name != name or not name.endswith('.desktop'):
        raise ValueError('Invalid desktop entry name')
    if enabled and 'X-ADWS-Removed' in data.get_keys('Desktop Entry')[0]:
        data.remove_key('Desktop Entry','X-ADWS-Removed')
    data.set_boolean('Desktop Entry','Hidden',not enabled)
    text, _ = data.to_data()
    destination = user_dir()/name
    destination.parent.mkdir(parents=True,exist_ok=True)
    # An autostart file is often a symlink to an application launcher. Publish
    # the user override at the link's name; following it would hide/change the
    # launcher itself (or edit a system file) instead of just login behavior.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=destination.parent,
                                         prefix='.adws-autostart-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if destination.exists() and not destination.is_symlink():
            temporary.chmod(destination.stat().st_mode & 0o777)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def delete_entry(name, data):
    """Remove a local login entry, or suppress a system entry for this account."""
    if Path(name).name != name or not name.endswith('.desktop'):
        raise ValueError('Invalid desktop entry name')
    system_dirs = [Path(p)/'autostart' for p in os.environ.get('XDG_CONFIG_DIRS','/etc/xdg').split(':') if p]
    if any((directory/name).is_file() for directory in system_dirs):
        # Unlinking an override alone would reveal the system entry again.
        # A private hidden override preserves the system file and app launcher.
        data.set_boolean('Desktop Entry','X-ADWS-Removed',True)
        set_enabled(name,data,False)
    else:
        (user_dir()/name).unlink(missing_ok=True)


class SessionApps(Gtk.Box):
    def __init__(self, host):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.host = host
        self.get_style_context().add_class('settings-card')
        title = Gtk.Label(label=tr('登录启动应用'),xalign=0)
        title.get_style_context().add_class('settings-section-title')
        self.pack_start(title,False,False,0)
        hint=Gtk.Label(label=tr('选择登录后自动启动的应用。修改只影响当前用户。'),xalign=0);hint.set_line_wrap(True)
        self.pack_start(hint,False,False,0)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12)
        self.pack_start(self.list,False,False,0)
        add=Gtk.Button(label=tr('添加应用'));add.set_halign(Gtk.Align.START);add.connect('clicked',self.add_app)
        self.pack_start(add,False,False,0)
        hint=Gtk.Label(label=tr('你的桌面会话需要支持 XDG 登录自启。'),xalign=0);hint.set_line_wrap(True);hint.get_style_context().add_class('dim-label')
        self.pack_start(hint,False,False,0)
        self.reload()

    def reload(self):
        for child in self.list.get_children():child.destroy()
        for name, title, enabled, data in read_entries():
            row=Gtk.Box(spacing=12)
            text=Gtk.Label(label=title,xalign=0);text.set_line_wrap(True)
            row.pack_start(text,True,True,0)
            control=Gtk.Switch();control.set_active(enabled);control.set_valign(Gtk.Align.CENTER)
            def change(widget, state, name=name, data=data):
                try:set_enabled(name,data,state)
                except Exception as error:
                    self.host.error(error);return True
                return False
            control.connect('state-set',change);row.pack_end(control,False,False,0)
            receiver=Gtk.EventBox();receiver.set_visible_window(False);receiver.add(row)
            receiver.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            receiver.connect('button-press-event',self.context_menu,name,title,data)
            self.list.pack_start(receiver,False,False,0)
        if not self.list.get_children():self.list.pack_start(Gtk.Label(label=tr('尚未配置登录应用。'),xalign=0),False,False,0)
        self.list.show_all()

    def context_menu(self, widget, event, name, title, data):
        if event.button != 3:
            return False
        menu=Gtk.Menu()
        item=Gtk.MenuItem()
        content=Gtk.Box(spacing=8)
        content.pack_start(Gtk.Image.new_from_icon_name('edit-delete-symbolic',Gtk.IconSize.MENU),False,False,0)
        content.pack_start(Gtk.Label(label=tr('删除'),xalign=0),False,False,0)
        item.add(content)
        item.connect('activate',lambda *_: self.delete_app(name,title,data))
        menu.append(item)
        # Hold the popup through activation; release its widgets when closed.
        self.context_popup=menu
        def closed(*_):
            self.context_popup=None
            menu.destroy()
        menu.connect('selection-done',closed)
        menu.show_all();menu.popup_at_pointer(event)
        return True

    def delete_app(self, name, title, data):
        if not self.host.confirm(tr('删除启动项：%s') % title,
                                 tr('启动项：%s\n确定要删除该启动项吗？') % title):
            return
        try:
            delete_entry(name,data)
            self.reload()
        except (OSError, ValueError, GLib.Error) as error:
            self.host.error(error)

    def add_app(self,*_):
        dialog=Gtk.AppChooserDialog(transient_for=self.host,modal=True,content_type='application/octet-stream')
        dialog.set_title(tr('选择自启应用'));dialog.get_widget().set_show_all(True)
        if dialog.run()==Gtk.ResponseType.OK:
            app=dialog.get_app_info()
            if isinstance(app,Gio.DesktopAppInfo):
                try:
                    data=GLib.KeyFile();data.load_from_file(app.get_filename(), GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
                    for key in ('OnlyShowIn','NotShowIn'):
                        if key in data.get_keys('Desktop Entry')[0]:data.remove_key('Desktop Entry',key)
                    set_enabled(Path(app.get_filename()).name,data,True)
                    self.reload()
                except Exception as error:self.host.error(error)
        dialog.destroy()

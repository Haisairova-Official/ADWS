"""Wallpaper selection and preview for the setup wizard."""
from pathlib import Path
import threading
from gi.repository import Gtk, GdkPixbuf, GLib
from adws_i18n import tr as _tr
import adws_wallpaper as wallpaper


class WallpaperPage:
    def __init__(self, parent, box):
        self.parent = parent
        self.selected = None
        self.installing = False
        self.keep = Gtk.CheckButton(label=_tr('保持当前壁纸设置'))
        self.keep.set_active(True)
        box.pack_start(self.keep, False, False, 0)
        self.choose = Gtk.Button(label=_tr('选择壁纸…'))
        self.choose.connect('clicked', self.select_image)
        box.pack_start(self.choose, False, False, 0)
        self.preview = Gtk.Image()
        box.pack_start(self.preview, False, False, 0)
        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.set_max_width_chars(60)
        box.pack_start(self.status, False, False, 0)
        advanced = Gtk.Expander(label=_tr('高级选项：壁纸工具'))
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.engine = Gtk.ComboBoxText()
        controls.pack_start(self.engine, False, False, 0)
        refresh = Gtk.Button(label=_tr('刷新检测'))
        refresh.connect('clicked', lambda *_: self.refresh())
        controls.pack_start(refresh, False, False, 0)
        advanced.add(controls)
        box.pack_start(advanced, False, False, 0)
        self.install = Gtk.Button(label=_tr('安装 awww'))
        self.install.set_no_show_all(True)
        self.install.connect('clicked', self.confirm_install)
        box.pack_start(self.install, False, False, 0)
        self.refresh()

    def refresh(self):
        tools = wallpaper.installed()
        old = self.engine.get_active_id()
        current = list(wallpaper.running().values())
        self.engine.remove_all()
        for tool in tools:
            if tool in wallpaper.ENGINES:
                self.engine.append(tool, _tr('awww（推荐）') if tool == 'awww' else tool)
        supported = [t for t in tools if t in wallpaper.ENGINES]
        preferred = next((wallpaper.PROCESSES[n] for n in current if wallpaper.PROCESSES[n] in supported), None)
        choice = old if old in supported else preferred or next(iter(supported), None)
        if choice: self.engine.set_active_id(choice)
        self.install.set_visible(not tools)
        if not tools:
            self.status.set_text(_tr('尚未检测到支持的壁纸工具。是否下载awww用来管理您的壁纸？'))
        elif not supported:
            self.status.set_text(_tr('已检测到：%s。将保留其配置；请使用该工具设置壁纸，或安装 awww 后刷新。') % ', '.join(tools))
        else:
            self.status.set_text(_tr('选择图片仅预览，完成设置后才应用。'))

    def select_image(self, *_):
        chooser = Gtk.FileChooserDialog(title=_tr('选择壁纸…'), transient_for=self.parent, action=Gtk.FileChooserAction.OPEN)
        chooser.add_buttons(_tr('取消'), Gtk.ResponseType.CANCEL, _tr('选择'), Gtk.ResponseType.OK)
        filter = Gtk.FileFilter();filter.set_name(_tr('图片'));filter.add_pixbuf_formats();chooser.add_filter(filter)
        response = chooser.run(); filename = chooser.get_filename();chooser.destroy()
        if response != Gtk.ResponseType.OK or not filename: return
        try:
            image = GdkPixbuf.Pixbuf.new_from_file_at_scale(filename, 420, 170, True)
            self.preview.set_from_pixbuf(image)
            self.selected = str(Path(filename).resolve())
            self.keep.set_active(False)
            self.status.set_text(Path(filename).name)
        except Exception as exc: self.status.set_text(str(exc))

    def confirm_install(self, *_):
        confirm = Gtk.MessageDialog(transient_for=self.parent, modal=True, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE, text=_tr('是否下载awww用来管理您的壁纸？'))
        confirm.format_secondary_text(_tr('将通过系统软件源安装，可能需要管理员授权；如果软件源没有 awww，可以暂时跳过。'))
        confirm.add_buttons(_tr('暂时跳过'), Gtk.ResponseType.CANCEL, _tr('安装 awww'), Gtk.ResponseType.OK)
        response = confirm.run();confirm.destroy()
        if response != Gtk.ResponseType.OK:return
        self.installing = True
        self.install.set_sensitive(False)
        self.status.set_text(_tr('正在安装 awww…'))
        def finish(error):
            self.installing = False
            self.install.set_sensitive(True)
            self.refresh()
            if error:self.status.set_text(error)
            return False
        def worker():
            error = ''
            try: wallpaper.install_awww()
            except Exception as exc:error = str(exc)
            GLib.idle_add(finish,error)
        threading.Thread(target=worker, daemon=False).start()

    def selection(self):
        if self.installing: raise ValueError(_tr('请等待壁纸工具安装完成。'))
        if self.keep.get_active(): return None
        if not self.selected: raise ValueError(_tr('请先选择壁纸，或保留当前设置。'))
        engine = self.engine.get_active_id()
        image = wallpaper.validate(engine, self.selected)
        current = wallpaper.running()
        conflicts = {pid:name for pid,name in current.items() if wallpaper.PROCESSES[name] != engine or engine == 'swaybg'}
        if conflicts:
            confirm = Gtk.MessageDialog(transient_for=self.parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.OK_CANCEL, text=_tr('切换壁纸工具？'))
            confirm.format_secondary_text(_tr('应用新壁纸后将停止当前会话中的这些壁纸服务：%s。已有自启配置不会删除；若由其他桌面管理器自动拉起，请在原设置中停用。') % ', '.join(sorted(set(conflicts.values()))))
            response = confirm.run();confirm.destroy()
            if response != Gtk.ResponseType.OK: raise ValueError(_tr('已取消壁纸切换，可选择保留当前设置。'))
        return {'engine': engine, 'image': image, 'approved': conflicts}

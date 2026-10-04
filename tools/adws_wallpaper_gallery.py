"""A bounded, asynchronous wallpaper library. Selection never applies wallpaper."""
from concurrent.futures import ThreadPoolExecutor
import ctypes
import errno
import heapq
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import warnings

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf, Gio, GLib, GObject, Gtk, Pango
from adws_i18n import tr

RASTER_SUFFIXES = frozenset(('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff', '.avif'))
MAX_IMAGE_BYTES = 100 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
PAGE_SIZE = 12
MAX_LIBRARY_ITEMS = 10000
THUMBNAIL_SIZE = (220, 132)


def library_config_path():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'adws/wallpaper-library.json'


def default_directory():
    return Path.home() / 'Pictures' / 'Wallpapers'


def library_directory():
    try:
        value = json.loads(library_config_path().read_text()).get('directory')
        if isinstance(value, str) and value and Path(value).expanduser().is_absolute():
            return Path(value).expanduser()
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return default_directory()


def save_directory(directory):
    directory = Path(directory).expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise ValueError(tr('请选择壁纸文件夹。'))
    target = library_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         prefix='.wallpaper-library-', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'directory': str(directory)}, stream, ensure_ascii=False)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def scan_page(directory, page=0, page_size=PAGE_SIZE, cancelled=None):
    """Bound both returned thumbnails and names retained while scanning."""
    directory = Path(directory)
    if not directory.exists():
        return [], False
    page = max(0, min(int(page), (MAX_LIBRARY_ITEMS - 1) // page_size))
    stop = min((page + 1) * page_size + 1, MAX_LIBRARY_ITEMS)
    def candidates():
        with os.scandir(directory) as entries:
            for entry in entries:
                if cancelled and cancelled.is_set():
                    return
                if entry.name.startswith('.') or Path(entry.name).suffix.casefold() not in RASTER_SUFFIXES:
                    continue
                # Do not thumbnail FIFOs/devices or follow links into remote trees.
                try:
                    if entry.is_file(follow_symlinks=False):
                        yield Path(entry.path)
                except OSError:
                    continue
    paths = heapq.nsmallest(stop, candidates(), key=lambda path: (path.name.casefold(), path.name))
    start = page * page_size
    return paths[start:start + page_size], len(paths) > start + page_size


def validate_raster(path):
    from PIL import Image
    path = Path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_IMAGE_BYTES:
        raise ValueError(tr('图片文件过大或不是普通文件。'))
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(path) as image:
            if image.format not in ('PNG', 'JPEG', 'WEBP', 'GIF', 'BMP', 'TIFF', 'AVIF'):
                raise ValueError(tr('不支持此图片格式。'))
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError(tr('图片分辨率过高，无法生成预览。'))
            dimensions = image.size
            image.verify()
    return dimensions


def page_containing(directory, selected):
    """Locate a tile without loading or retaining the complete library."""
    key = (Path(selected).name.casefold(), Path(selected).name)
    before = 0
    with os.scandir(directory) as entries:
        for entry in entries:
            if (not entry.name.startswith('.') and Path(entry.name).suffix.casefold() in RASTER_SUFFIXES
                    and entry.is_file(follow_symlinks=False) and (entry.name.casefold(), entry.name) < key):
                before += 1
    return min(before // PAGE_SIZE, (MAX_LIBRARY_ITEMS - 1) // PAGE_SIZE)


def thumbnail(path):
    from PIL import Image, ImageOps
    validate_raster(path)
    with Image.open(path) as source:
        source.seek(0)
        # JPEG draft decoding avoids allocating a full-size photograph.
        source.draft('RGB', THUMBNAIL_SIZE)
        source.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        image = ImageOps.exif_transpose(source).convert('RGBA')
        image.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        return image.width, image.height, image.tobytes()


def _publish_without_replace(temporary, target):
    """Publish a complete same-filesystem file, never replacing an existing name."""
    try:
        os.link(temporary, target)
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS):
            raise
        # FAT libraries cannot create hard links; Linux renameat2 still supports
        # atomic RENAME_NOREPLACE. Never fall back to a destructive rename.
        library = ctypes.CDLL(None, use_errno=True)
        rename = getattr(library, 'renameat2', None)
        if rename is None:
            raise
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(temporary), -100, os.fsencode(target), 1) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), str(target))


def import_image(source, directory):
    """Copy into a private temporary file, validate, then publish atomically."""
    source, directory = Path(source).expanduser(), Path(directory).expanduser()
    validate_raster(source)
    directory.mkdir(parents=True, exist_ok=True)
    if source.resolve().parent == directory.resolve() and not source.name.startswith('.'):
        return source.resolve()
    suffix = source.suffix.casefold()
    if suffix not in RASTER_SUFFIXES:
        # A valid raster with an unusual suffix still needs a discoverable name.
        from PIL import Image
        with Image.open(source) as image:
            suffix = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'GIF': '.gif',
                      'BMP': '.bmp', 'TIFF': '.tiff', 'AVIF': '.avif'}.get(image.format)
        if not suffix:
            raise ValueError(tr('不支持此图片格式。'))
    stem = source.stem.lstrip('.') or 'wallpaper'
    # Leave room for a disambiguating suffix on common 255-byte filesystems.
    while len(stem.encode('utf-8')) > 180:
        stem = stem[:-1]
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix='.wallpaper-import-', delete=False) as output:
            temporary = Path(output.name)
            with source.open('rb') as input_file:
                total = 0
                while block := input_file.read(1024 * 1024):
                    total += len(block)
                    if total > MAX_IMAGE_BYTES:
                        raise ValueError(tr('图片文件过大或不是普通文件。'))
                    output.write(block)
            output.flush(); os.fsync(output.fileno())
        thumbnail(temporary)  # Verify that the copied image can actually decode.
        for number in range(10000):
            name = stem + (f' ({number})' if number else '') + suffix
            target = directory / name
            try:
                _publish_without_replace(temporary, target)
                return target
            except FileExistsError:
                continue
        raise FileExistsError(tr('同名壁纸过多，请修改文件名后重试。'))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class WallpaperGallery(Gtk.Box):
    __gsignals__ = {'selection-changed': (GObject.SignalFlags.RUN_LAST, None, (str,))}

    def __init__(self, on_selected, initial_path=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.on_selected = on_selected
        self.directory = library_directory()
        self.selected = str(Path(initial_path).expanduser()) if initial_path else None
        self.page, self.alive, self.importing = 0, True, False
        self.cancelled = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='adws-wallpapers')
        self.future = None
        self.tiles = {}
        self.connect('destroy', self.closed)
        toolbar = Gtk.Box(spacing=8)
        self.add_button = Gtk.Button(label=tr('添加壁纸'))
        self.add_button.get_style_context().add_class('suggested-action')
        self.add_button.connect('clicked', self.choose_images)
        toolbar.pack_start(self.add_button, False, False, 0)
        self.folder_button = Gtk.Button(label=tr('选择图库文件夹'))
        self.folder_button.connect('clicked', self.choose_directory)
        toolbar.pack_start(self.folder_button, False, False, 0)
        open_button = Gtk.Button.new_from_icon_name('folder-open-symbolic', Gtk.IconSize.BUTTON)
        open_button.set_tooltip_text(tr('打开壁纸文件夹')); open_button.connect('clicked', self.open_directory)
        toolbar.pack_end(open_button, False, False, 0)
        refresh = Gtk.Button.new_from_icon_name('view-refresh-symbolic', Gtk.IconSize.BUTTON)
        refresh.set_tooltip_text(tr('刷新壁纸图库')); refresh.connect('clicked', lambda *_: self.refresh())
        toolbar.pack_end(refresh, False, False, 0)
        self.pack_start(toolbar, False, False, 0)
        self.path_label = Gtk.Label(xalign=0)
        self.path_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.path_label.get_style_context().add_class('settings-caption')
        self.pack_start(self.path_label, False, False, 0)
        self.grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=12, row_spacing=12)
        self.grid.set_homogeneous(True); self.grid.set_min_children_per_line(1); self.grid.set_max_children_per_line(3)
        self.pack_start(self.grid, False, False, 0)
        self.status = Gtk.Label(xalign=0); self.status.set_line_wrap(True)
        self.status.get_style_context().add_class('settings-caption')
        self.pack_start(self.status, False, False, 0)
        self.selected_label = Gtk.Label(xalign=0)
        self.selected_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.pack_start(self.selected_label, False, False, 0)
        pager = Gtk.Box(spacing=10)
        self.previous = Gtk.Button(label=tr('上一页')); self.previous.connect('clicked', lambda *_: self.change_page(-1))
        self.next = Gtk.Button(label=tr('下一页')); self.next.connect('clicked', lambda *_: self.change_page(1))
        self.page_label = Gtk.Label()
        pager.pack_start(self.previous, False, False, 0); pager.pack_start(self.page_label, True, True, 0)
        pager.pack_end(self.next, False, False, 0); self.pack_start(pager, False, False, 0)
        self.set_filename(self.selected)
        GLib.idle_add(self.refresh)

    def _parent(self):
        root = self.get_toplevel()
        return root if isinstance(root, Gtk.Window) else None

    def _error(self, message):
        dialog = Gtk.MessageDialog(transient_for=self._parent(), modal=True, destroy_with_parent=True,
                                   message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
                                   text=tr('壁纸图库操作失败'))
        dialog.format_secondary_text(str(message)); dialog.run(); dialog.destroy()

    def get_filename(self):
        return self.selected

    def set_filename(self, path, emit=False):
        self.selected = str(Path(path).expanduser()) if path else None
        self.selected_label.set_text((tr('已选择：%s') % Path(self.selected).name) if self.selected else tr('点击图片选择壁纸，再应用更改。'))
        self.selected_label.set_tooltip_text(self.selected)
        for filename, button in self.tiles.items():
            context = button.get_style_context()
            if filename == self.selected:
                context.add_class('suggested-action')
            else:
                context.remove_class('suggested-action')
        if emit and self.selected:
            self.emit('selection-changed', self.selected)
            if self.on_selected:
                self.on_selected(self.selected)
        return bool(self.selected)

    def refresh(self):
        if not self.alive or self.importing:
            return False
        self.cancelled.set()
        if self.future:
            self.future.cancel()
        self.cancelled = threading.Event()
        token = self.cancelled
        directory, page = self.directory, self.page
        self.path_label.set_text(str(directory)); self.path_label.set_tooltip_text(str(directory))
        self.status.set_text(tr('正在读取壁纸图库…'))
        self.previous.set_sensitive(False); self.next.set_sensitive(False)
        self.page_label.set_text(tr('第 %s 页') % (page+1))
        for child in self.grid.get_children():
            child.destroy()
        self.tiles.clear()
        def work():
            try:
                paths, more = scan_page(directory, page, cancelled=token)
                if token.is_set():
                    return
                GLib.idle_add(self.show_paths, token, paths, more)
                for path in paths:
                    if token.is_set():
                        return
                    try:
                        data, error = thumbnail(path), None
                    except Exception:
                        data, error = None, tr('无法预览此图片')
                    if not token.is_set():
                        GLib.idle_add(self.show_thumbnail, token, str(path), data, error)
            except Exception as error:
                if not token.is_set():
                    GLib.idle_add(self.show_scan_error, token, str(error))
        self.future = self.executor.submit(work)
        return False

    def show_paths(self, token, paths, more):
        if not self.alive or token.is_set():
            return False
        self.previous.set_sensitive(self.page > 0); self.next.set_sensitive(more)
        self.status.set_text(tr('图库为空，添加图片后即可在这里预览和选择。') if not paths else tr('选择不会立即更换壁纸，点击“应用更改”后生效。'))
        for path in paths:
            button = Gtk.Button()
            button.get_style_context().add_class('settings-shortcut')
            button.set_tooltip_text(path.name)
            button.connect('clicked', lambda _, path=path: self.set_filename(path, emit=True))
            contents = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            image = Gtk.Image.new_from_icon_name('image-x-generic-symbolic', Gtk.IconSize.DIALOG)
            image.set_size_request(*THUMBNAIL_SIZE)
            text = Gtk.Label(label=path.name)
            text.set_ellipsize(Pango.EllipsizeMode.MIDDLE); text.set_max_width_chars(24)
            contents.pack_start(image, False, False, 0); contents.pack_start(text, False, False, 0)
            button.add(contents); button.thumbnail_image = image
            self.tiles[str(path)] = button; self.grid.add(button)
        self.set_filename(self.selected)
        self.grid.show_all()
        return False

    def show_thumbnail(self, token, filename, data, error):
        if not self.alive or token.is_set() or filename not in self.tiles:
            return False
        button = self.tiles[filename]
        if data:
            width, height, pixels = data
            pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(pixels), GdkPixbuf.Colorspace.RGB,
                                                    True, 8, width, height, width*4)
            button.thumbnail_image.set_from_pixbuf(pixbuf)
        else:
            button.thumbnail_image.set_from_icon_name('dialog-warning-symbolic', Gtk.IconSize.DIALOG)
            button.set_tooltip_text(filename + '\n' + error)
            button.set_sensitive(False)
        return False

    def show_scan_error(self, token, error):
        if self.alive and not token.is_set():
            self.status.set_text(tr('无法读取壁纸文件夹：%s') % error)
        return False

    def change_page(self, change):
        self.page = max(0, self.page + change)
        self.refresh()

    def choose_images(self, *_):
        if self.importing:
            return
        dialog = Gtk.FileChooserDialog(title=tr('添加壁纸'), transient_for=self._parent(),
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(tr('取消'), Gtk.ResponseType.CANCEL, tr('添加'), Gtk.ResponseType.OK)
        dialog.set_select_multiple(True)
        filter_ = Gtk.FileFilter(); filter_.set_name(tr('图片'))
        for suffix in RASTER_SUFFIXES:
            filter_.add_pattern('*' + suffix); filter_.add_pattern('*' + suffix.upper())
        dialog.add_filter(filter_)
        response = dialog.run()
        selected = dialog.get_filenames() if response == Gtk.ResponseType.OK else []
        dialog.destroy()
        if selected:
            self.import_paths(selected)

    def import_paths(self, paths):
        if not self.alive or self.importing:
            return
        self.importing = True
        self.cancelled.set()
        if self.future:
            self.future.cancel()
        self.add_button.set_sensitive(False); self.folder_button.set_sensitive(False)
        self.previous.set_sensitive(False); self.next.set_sensitive(False)
        self.status.set_text(tr('正在添加壁纸…'))
        directory = self.directory
        def work():
            added, errors = [], []
            for path in paths:
                try:
                    added.append(import_image(path, directory))
                except Exception as error:
                    errors.append(Path(path).name + ': ' + str(error))
            page = 0
            if added:
                try:
                    page = page_containing(directory, added[-1])
                except OSError:
                    pass
            GLib.idle_add(self.import_finished, added, errors, page)
        self.future = self.executor.submit(work)

    def import_finished(self, added, errors, page=0):
        if not self.alive:
            return False
        self.importing = False
        self.add_button.set_sensitive(True); self.folder_button.set_sensitive(True)
        if added:
            self.page = page
            self.set_filename(added[-1], emit=True)
        self.refresh()
        if errors:
            self._error('\n'.join(errors))
        return False

    def choose_directory(self, *_):
        if self.importing:
            return
        dialog = Gtk.FileChooserDialog(title=tr('选择图库文件夹'), transient_for=self._parent(),
                                       action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.add_buttons(tr('取消'), Gtk.ResponseType.CANCEL, tr('选择'), Gtk.ResponseType.OK)
        if self.directory.is_dir():
            dialog.set_filename(str(self.directory))
        response = dialog.run()
        chosen = dialog.get_filename() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if chosen:
            try:
                save_directory(chosen)
            except Exception as error:
                self._error(error); return
            self.directory = Path(chosen); self.page = 0; self.refresh()

    def open_directory(self, *_):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            Gio.AppInfo.launch_default_for_uri(self.directory.resolve().as_uri(), None)
        except Exception as error:
            self._error(error)

    def closed(self, *_):
        self.alive = False
        self.cancelled.set()
        # Finish an explicit import; cancel queued thumbnail work. Files already
        # requested by the user must not be left as partial imports on close.
        self.executor.shutdown(wait=False, cancel_futures=not self.importing)


TRANSLATIONS = {
    '请选择壁纸文件夹。': 'Choose a wallpaper folder.',
    '图片文件过大或不是普通文件。': 'The image is too large or is not a regular file.',
    '图片分辨率过高，无法生成预览。': 'The image resolution is too large to preview.',
    '不支持此图片格式。': 'This image format is not supported.',
    '同名壁纸过多，请修改文件名后重试。': 'Too many wallpapers share this name. Rename the file and try again.',
    '添加壁纸': 'Add wallpapers',
    '选择图库文件夹': 'Choose library folder',
    '打开壁纸文件夹': 'Open wallpaper folder',
    '刷新壁纸图库': 'Refresh wallpaper library',
    '壁纸图库操作失败': 'Wallpaper library operation failed',
    '已选择：%s': 'Selected: %s',
    '点击图片选择壁纸，再应用更改。': 'Select an image, then apply your changes.',
    '正在读取壁纸图库…': 'Reading wallpaper library…',
    '第 %s 页': 'Page %s',
    '无法预览此图片': 'Cannot preview this image',
    '图库为空，添加图片后即可在这里预览和选择。': 'Your library is empty. Add images to preview and select them here.',
    '选择不会立即更换壁纸，点击“应用更改”后生效。': 'Selecting an image does not change the wallpaper until you apply your changes.',
    '无法读取壁纸文件夹：%s': 'Cannot read wallpaper folder: %s',
    '正在添加壁纸…': 'Adding wallpapers…',
    '添加': 'Add',
    '上一页': 'Previous',
    '下一页': 'Next',
}

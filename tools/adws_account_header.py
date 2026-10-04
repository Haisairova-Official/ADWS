"""Session-cached account identity for the ADWS settings sidebar."""
from concurrent.futures import ThreadPoolExecutor
import grp
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import stat
import tempfile
import warnings

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf, Gio, GLib, Gtk, Pango
from adws_i18n import tr

MAX_AVATAR_BYTES = 8 * 1024 * 1024
MAX_AVATAR_PIXELS = 40_000_000
ROLE_LABELS = {'root': '根用户', 'administrator': '管理员', 'standard': '标准账户', 'unknown': '账户类型未知'}


def display_name(value):
    return ''.join(character for character in str(value) if ord(character) >= 32 and ord(character) != 127).strip()[:512]


def session_key(env=None):
    env = os.environ if env is None else env
    if not env.get('XDG_RUNTIME_DIR') or not env.get('WAYLAND_DISPLAY'):
        return None
    socket = Path(env['XDG_RUNTIME_DIR']) / env['WAYLAND_DISPLAY']
    try:
        info = socket.stat()
    except OSError:
        return None
    seconds, nanos = divmod(info.st_ctime_ns, 1_000_000_000)
    return f"{env.get('XDG_SESSION_ID', '')}:{socket}:{info.st_ino}:{seconds}:{nanos}"


def cache_directory():
    return Path(os.environ.get('XDG_CACHE_HOME') or Path.home()/'.cache')/'adws'


def cache_path(key):
    digest = hashlib.sha256(key.encode()).hexdigest()[:20]
    return cache_directory()/f'account-header-{digest}.json'


def read_json_owned(path, uid):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as file:
            info = os.fstat(file.fileno())
            if info.st_uid != uid or not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
                return None
            data = json.loads(file.read(65537))
            return data if isinstance(data, dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def read_cache(key, uid):
    own = read_json_owned(cache_path(key), uid)
    if (own and own.get('session') == key and own.get('uid') == uid
            and isinstance(own.get('name'), str) and isinstance(own.get('username'), str)
            and own.get('role') in ROLE_LABELS):
        return own
    return None


def read_menu_cache(key, uid):
    """Rust hashes its filenames; match their stored session instead of guessing."""
    try:
        with os.scandir(cache_directory()) as entries:
            checked = 0
            for entry in entries:
                if not entry.name.startswith('account-') or entry.name.startswith('account-header-') or not entry.name.endswith('.json'):
                    continue
                checked += 1
                if checked > 32:
                    break
                data = read_json_owned(entry.path, uid)
                if data and data.get('session') == key and isinstance(data.get('name'), str):
                    return {'name': data['name'], 'avatar': data.get('avatar')}
    except OSError:
        pass
    return None


def account_role(uid, account_type=None, groups=None):
    if uid == 0:
        return 'root'
    if type(account_type) is int and account_type in (0, 1):
        return 'administrator' if account_type == 1 else 'standard'
    if groups is None:
        return 'unknown'
    return 'administrator' if set(groups).intersection(('wheel', 'sudo')) else 'standard'


def query_properties(uid):
    """Bound the AccountsService call; this function only runs in a worker."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        reply = bus.call_sync('org.freedesktop.Accounts', f'/org/freedesktop/Accounts/User{uid}',
                              'org.freedesktop.DBus.Properties', 'GetAll',
                              GLib.Variant('(s)', ('org.freedesktop.Accounts.User',)),
                              GLib.VariantType.new('(a{sv})'), Gio.DBusCallFlags.NONE, 1000, None)
        raw = reply.unpack()[0]
        result = {key: value.unpack() if isinstance(value, GLib.Variant) else value for key,value in raw.items()}
        return result if type(result.get('Uid')) is int and result['Uid'] == uid else {}
    except Exception:
        return {}


def fallback_account(uid):
    try:
        account = pwd.getpwuid(uid)
        username, name = account.pw_name, account.pw_gecos.split(',')[0].strip() or account.pw_name
        directory = Path(account.pw_dir)
        try:
            groups = [grp.getgrgid(gid).gr_name for gid in os.getgrouplist(username, account.pw_gid)]
        except (KeyError, OSError):
            groups = None
    except KeyError:
        username, name, directory, groups = str(uid), str(uid), Path.home(), None
    avatar = next((str(p) for p in (directory/'.face', directory/'.face.icon', Path('/var/lib/AccountsService/icons')/username) if p.is_file()), None)
    return {'uid':uid, 'username':username, 'name':name, 'avatar':avatar,
            'role':account_role(uid, groups=groups), 'groups':groups}


def avatar_png(path):
    if not path:
        return None
    from PIL import Image, ImageDraw, ImageOps
    try:
        image_path = Path(path)
        info = image_path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_AVATAR_BYTES:
            return None
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(image_path) as source:
                if source.format not in ('PNG','JPEG','WEBP','GIF','BMP','TIFF','AVIF') or source.width*source.height > MAX_AVATAR_PIXELS:
                    return None
                source.draft('RGB',(224,224))
                source.thumbnail((448,448))
                image = ImageOps.fit(ImageOps.exif_transpose(source).convert('RGBA'),(224,224),method=Image.Resampling.LANCZOS)
                mask = Image.new('L',image.size,0)
                ImageDraw.Draw(mask).ellipse((0,0,223,223),fill=255)
                # Preserve existing transparency while applying the circle.
                from PIL import ImageChops
                image.putalpha(ImageChops.multiply(image.getchannel('A'),mask))
                image = image.resize((112,112),Image.Resampling.LANCZOS)
                buffer = io.BytesIO();image.save(buffer,format='PNG')
                return buffer.getvalue()
    except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        return None


def avatar_for_user(uid, icon=None):
    """Decode a user's service icon, then their local fallbacks, in a worker."""
    candidates = [icon] if isinstance(icon, str) and icon else []
    try:
        user = pwd.getpwuid(uid)
        home = Path(user.pw_dir)
        candidates.extend((home/'.face', home/'.face.icon',
                           Path('/var/lib/AccountsService/icons')/user.pw_name))
    except KeyError:
        pass
    for candidate in candidates:
        image = avatar_png(candidate)
        if image is not None:
            return image
    return None


def avatar_image(data, size=48, css='settings-user-avatar'):
    """Create only GTK image widgets here; image files are decoded in workers."""
    image = Gtk.Image.new_from_icon_name('avatar-default-symbolic', Gtk.IconSize.DIALOG)
    image.set_pixel_size(size)
    image.set_size_request(size, size)
    image.set_valign(Gtk.Align.CENTER)
    image.get_style_context().add_class(css)
    if data:
        try:
            decoder = GdkPixbuf.PixbufLoader.new_with_type('png')
            decoder.write(data)
            decoder.close()
            image.set_from_pixbuf(decoder.get_pixbuf().scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR))
        except GLib.Error:
            pass
    return image


def atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.account-header-',delete=False) as file:
            temporary = Path(file.name);file.write(data);file.flush();os.fsync(file.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_account(force=False):
    uid, key = os.getuid(), session_key()
    cached = read_cache(key,uid) if key else None
    if cached and not force:
        return cached, avatar_png(cached.get('avatar'))
    account = cached.copy() if cached else fallback_account(uid)
    if key and not force and not cached:
        menu = read_menu_cache(key,uid)
        if menu:
            account.update({key:value for key,value in menu.items() if value})
    properties = query_properties(uid)
    if isinstance(properties.get('RealName'),str) and properties['RealName'].strip():
        account['name'] = properties['RealName'].strip()
    if isinstance(properties.get('IconFile'),str) and properties['IconFile']:
        account['avatar'] = properties['IconFile']
    if properties.get('AccountType') in (0,1):
        account['role'] = account_role(uid,properties['AccountType'])
    if uid == 0:
        account['role'] = 'root'
    image = avatar_png(account.get('avatar'))
    account.pop('groups',None)
    if key:
        account['session'] = key
        try:
            target = cache_path(key)
            if image:
                target_avatar = target.with_suffix('.png')
                atomic_bytes(target_avatar,image)
                account['avatar'] = str(target_avatar)
            atomic_bytes(target,json.dumps(account,ensure_ascii=False).encode())
        except OSError:
            pass
    return account,image


class AccountHeader(Gtk.Button):
    def __init__(self, on_activate=None):
        super().__init__()
        self.get_style_context().add_class('settings-account-header')
        self.set_relief(Gtk.ReliefStyle.NONE)
        self.set_tooltip_text(tr('账户与地区设置'))
        self.alive, self.generation = True, 0
        self.future = None
        self.executor = ThreadPoolExecutor(max_workers=1,thread_name_prefix='adws-account')
        if on_activate:
            self.connect('clicked',lambda *_:on_activate())
        box = Gtk.Box(spacing=12)
        self.avatar = Gtk.Image.new_from_icon_name('avatar-default-symbolic',Gtk.IconSize.DIALOG)
        self.avatar.set_pixel_size(56);self.avatar.set_size_request(56,56)
        self.avatar.set_valign(Gtk.Align.START)
        box.pack_start(self.avatar,False,False,0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=3)
        login = GLib.get_user_name()
        self.nickname = Gtk.Label(label=login,xalign=0)
        self.nickname.set_ellipsize(Pango.EllipsizeMode.END);self.nickname.set_max_width_chars(16)
        self.nickname.get_style_context().add_class('settings-account-name')
        text.pack_start(self.nickname,False,False,0)
        self.username = Gtk.Label(label='@'+login,xalign=0)
        self.username.set_ellipsize(Pango.EllipsizeMode.END);self.username.set_max_width_chars(18)
        self.username.get_style_context().add_class('settings-account-username')
        self.username.get_style_context().add_class('settings-caption')
        text.pack_start(self.username,False,False,0)
        self.role = Gtk.Label(label=tr('正在读取账户…'),xalign=0)
        self.role.set_halign(Gtk.Align.START)
        self.role.set_ellipsize(Pango.EllipsizeMode.END);self.role.set_max_width_chars(18)
        self.role.get_style_context().add_class('settings-account-role')
        text.pack_start(self.role,False,False,0)
        box.pack_start(text,True,True,0);self.add(box)
        self.connect('destroy',self.closed)
        GLib.idle_add(self.refresh,False)

    def refresh(self, force=True):
        if not self.alive:
            return False
        self.generation += 1
        generation = self.generation
        if self.future:
            self.future.cancel()
        def worker():
            try:
                account,image = load_account(force=force)
            except Exception:
                account,image = {'name':GLib.get_user_name(),'username':GLib.get_user_name(),'role':'unknown'},None
            GLib.idle_add(self.update_account,generation,account,image)
        self.future = self.executor.submit(worker)
        return False

    def update_account(self,generation,account,image):
        if not self.alive or generation != self.generation:
            return False
        name = display_name(account['name']) or display_name(account['username'])
        self.nickname.set_text(name)
        self.nickname.set_tooltip_text(name)
        self.username.set_text('@'+display_name(account['username']))
        self.role.set_text(tr(ROLE_LABELS.get(account['role'],'账户类型未知')))
        if image:
            try:
                stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(image))
                pixbuf = GdkPixbuf.Pixbuf.new_from_stream_at_scale(stream,56,56,True,None)
                self.avatar.set_from_pixbuf(pixbuf)
            except GLib.Error:
                self.avatar.set_from_icon_name('avatar-default-symbolic',Gtk.IconSize.DIALOG)
        else:
            self.avatar.set_from_icon_name('avatar-default-symbolic',Gtk.IconSize.DIALOG)
        return False

    def closed(self,*_):
        self.alive = False
        self.executor.shutdown(wait=False,cancel_futures=True)


TRANSLATIONS = {
    '根用户':'Root',
    '管理员':'Administrator',
    '标准账户':'Standard account',
    '账户类型未知':'Account type unknown',
    '正在读取账户…':'Loading account…',
    '账户与地区设置':'Account and region settings',
}

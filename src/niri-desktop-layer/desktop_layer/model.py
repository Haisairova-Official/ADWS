"""Desktop discovery and launching, independent of GTK and a display server.

Discovery only reads metadata.  In particular, a desktop file's Exec value is
never interpreted by a shell here; application launching belongs to GIO.
"""

from __future__ import annotations
from .i18n import tr as _tr

import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

from gi.repository import Gio, GLib


@dataclass
class Entry:
    path: Path
    name: str
    icon: Gio.Icon
    kind: str
    uri: str | None = None
    error: str | None = None
    size: int = 0
    modified: float = 0
    type_name: str = ""


class EntryLaunchError(RuntimeError):
    """An entry cannot be safely or successfully opened."""


class UntrustedLauncher(PermissionError):
    """A local, non-executable application launcher needs user consent."""


_GROUP = "Desktop Entry"
_MAX_DESKTOP_BYTES = 1024 * 1024
_LINK_SCHEMES = frozenset({"file", "http", "https", "trash", "computer", "network"})


def desktop_directory() -> Path:
    """Use the XDG Desktop directory without treating HOME as the desktop.

    Some distributions disable the desktop directory by setting it to HOME.
    Showing the entire home directory in that case is surprising and expensive.
    A missing directory is deliberately not created by this module.
    """
    home = Path.home()
    configured = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP)
    if configured:
        candidate = Path(configured).expanduser()
        try:
            if candidate.is_absolute() and candidate.resolve() != home.resolve():
                return candidate
        except (OSError, RuntimeError):
            pass
    return home / "Desktop"


def _theme(name: str) -> Gio.Icon:
    return Gio.ThemedIcon.new_with_default_fallbacks(name)


def _optional_string(keyfile: GLib.KeyFile, key: str, default: str = "") -> str:
    if key in keyfile.get_keys(_GROUP)[0]:
        return keyfile.get_string(_GROUP, key)
    return default


def _optional_bool(keyfile: GLib.KeyFile, key: str) -> bool:
    return key in keyfile.get_keys(_GROUP)[0] and keyfile.get_boolean(_GROUP, key)


def _validate_link_uri(uri: str) -> str:
    if not uri or any(character.isspace() or ord(character) < 32 for character in uri):
        raise ValueError(_tr('链接 URL 为空或包含未转义的空白字符'))
    parts = urlsplit(uri)
    if parts.scheme.lower() not in _LINK_SCHEMES:
        raise ValueError(_tr('链接仅支持 file、http、https、trash、computer 和 network 协议'))
    if parts.scheme.lower() in {"http", "https"} and not parts.hostname:
        raise ValueError(_tr('网页链接缺少主机名'))
    if parts.scheme.lower() == "file" and not parts.path.startswith("/"):
        raise ValueError(_tr('文件链接必须使用绝对路径'))
    return uri


def _desktop_entry(path: Path) -> Entry | None:
    entry = Entry(path, path.stem, _theme("application-x-desktop"), "application")
    try:
        if not path.is_file():
            raise ValueError(_tr('启动器不是普通文件，或符号链接的目标不存在'))
        if path.stat().st_size > _MAX_DESKTOP_BYTES:
            raise ValueError(_tr('启动器文件超过 1 MiB'))
        keyfile = GLib.KeyFile.new()
        keyfile.load_from_file(str(path), GLib.KeyFileFlags.NONE)
        if not keyfile.has_group(_GROUP):
            raise ValueError(_tr('缺少 [Desktop Entry] 段'))
        if _optional_bool(keyfile, "Hidden") or _optional_bool(keyfile, "NoDisplay"):
            return None
        name = keyfile.get_locale_string(_GROUP, "Name", None).strip()
        if not name:
            raise ValueError(_tr('启动器缺少名称'))
        entry.name = name
        icon_name = _optional_string(keyfile, "Icon")
        if icon_name:
            if os.path.isabs(icon_name):
                entry.icon = Gio.FileIcon.new(Gio.File.new_for_path(icon_name))
            else:
                entry.icon = _theme(icon_name)
        kind = keyfile.get_string(_GROUP, "Type")
        if kind == "Link":
            entry.kind = "link"
            entry.uri = _validate_link_uri(keyfile.get_string(_GROUP, "URL"))
            if not icon_name:
                entry.icon = _theme("text-html")
        elif kind == "Application":
            command = _optional_string(keyfile, "Exec")
            if not command.strip() and not _optional_bool(keyfile, "DBusActivatable"):
                raise ValueError(_tr('应用启动器缺少 Exec'))
            # Construction parses the desktop format, but never starts an app.
            if Gio.DesktopAppInfo.new_from_filename(str(path)) is None:
                raise ValueError(_tr('GIO 无法读取启动器，或所需程序未安装'))
        else:
            raise ValueError(_tr('仅支持 Type=Application 和 Type=Link 启动器'))
    except (GLib.Error, OSError, ValueError, UnicodeError, RuntimeError) as exc:
        entry.error = str(exc)
        entry.icon = _theme("dialog-warning")
    return entry


def _file_entry(path: Path) -> Entry:
    kind = "directory" if path.is_dir() else "file"
    entry = Entry(path, path.name, _theme("folder" if kind == "directory" else "text-x-generic"), kind)
    try:
        if path.is_symlink() and not path.exists():
            entry.error = _tr('符号链接的目标不存在')
            entry.icon = _theme("dialog-warning")
            return entry
        file = Gio.File.new_for_path(str(path))
        entry.uri = file.get_uri()
        info = file.query_info(
            "standard::display-name,standard::icon", Gio.FileQueryInfoFlags.NONE, None
        )
        entry.name = info.get_display_name() or path.name
        entry.icon = info.get_icon() or entry.icon
    except (GLib.Error, OSError, ValueError, UnicodeError) as exc:
        entry.error = str(exc)
        entry.icon = _theme("dialog-warning")
    return entry


def _populate_metadata(entry: Entry) -> None:
    """Read sorting metadata without traversing directories or opening files."""
    try:
        metadata = entry.path.stat()
    except OSError as exc:
        try:
            # A broken symlink still has useful metadata of its own.
            metadata = entry.path.lstat()
        except OSError:
            entry.error = entry.error or str(exc)
            metadata = None
    if metadata is not None:
        entry.size = 0 if entry.kind == "directory" else metadata.st_size
        entry.modified = metadata.st_mtime
    labels = {"directory": _tr('文件夹'), "application": _tr('应用快捷方式'), "link": _tr('链接')}
    entry.type_name = labels.get(entry.kind, _tr('文件'))
    if entry.kind == "file":
        try:
            content_type, _uncertain = Gio.content_type_guess(entry.path.name, None)
            if content_type:
                entry.type_name = Gio.content_type_get_description(content_type) or _tr('文件')
        except (GLib.Error, ValueError, UnicodeError):
            pass


def _natural_key(value: str) -> tuple:
    """Casefold Unicode names, comparing decimal runs by numeric value.

    Normalized decimal strings avoid Python's integer digit limit for unusually
    long names or labels, and also support non-ASCII decimal characters.
    """
    parts = []
    for part in re.split(r"(\d+)", value.casefold()):
        if part and part[0].isdecimal():
            number = "".join(str(unicodedata.decimal(character)) for character in part).lstrip("0") or "0"
            parts.append((1, len(number), number))
        else:
            parts.append((0, part))
    return tuple(parts)


def sort_entries(
    entries: list[Entry], sort_by: str = "name", descending: bool = False, folders_first: bool = True
) -> list[Entry]:
    """Return a naturally sorted snapshot, with deterministic name/path ties.

    Directory grouping is independent of the direction: folders remain first
    for descending order as well.  No entry or input list is modified.
    """
    if sort_by not in {"name", "type", "size", "modified"}:
        raise ValueError(_tr('未知排序方式：') + str(sort_by))

    def key(entry):
        name = (_natural_key(entry.name), entry.name.casefold(), entry.name,
                str(entry.path).casefold(), str(entry.path))
        if sort_by == "name":
            return name
        primary = (_natural_key(entry.type_name) if sort_by == "type" else
                   entry.size if sort_by == "size" else entry.modified)
        return (primary, *name)

    result = sorted(entries, key=key, reverse=descending)
    if folders_first:
        result.sort(key=lambda entry: entry.kind != "directory")
    return result


def scan_desktop(directory: Path, show_hidden: bool = False) -> list[Entry]:
    """Read one directory level, including broken or invalid entries as errors.

    Desktop-file Hidden/NoDisplay are always respected; show_hidden controls
    leading-dot filenames.  Missing Desktop directories simply have no icons.
    """
    directory = Path(directory).expanduser()
    try:
        children = list(directory.iterdir())
    except FileNotFoundError:
        return []
    entries = []
    for path in children:
        if not show_hidden and path.name.startswith("."):
            continue
        if path.suffix.lower() == ".desktop" and not path.is_dir():
            entry = _desktop_entry(path)
        else:
            entry = _file_entry(path)
        if entry is not None:
            _populate_metadata(entry)
            entries.append(entry)
    return sort_entries(entries)


def _installed_launcher(path: Path) -> bool:
    try:
        resolved = path.resolve(strict=True)
        roots = [GLib.get_user_data_dir(), *GLib.get_system_data_dirs()]
        return any(resolved.is_relative_to((Path(root) / "applications").resolve()) for root in roots)
    except (OSError, RuntimeError):
        return False


def _executable_text(path: Path) -> bool:
    """Recognize executable scripts without running them or reading devices."""
    if not path.is_file() or not os.access(path, os.X_OK):
        return False
    with path.open("rb") as stream:
        sample = stream.read(4096)
    if sample.startswith(b"#!"):
        return True
    content_type, _uncertain = Gio.content_type_guess(path.name, sample)
    return bool(content_type and Gio.content_type_is_a(content_type, "text/plain"))


def open_in_thunar(uri: str, context=None) -> bool:
    app = Gio.DesktopAppInfo.new("thunar.desktop")
    if app is None:
        raise EntryLaunchError(_tr('未找到 Thunar，请先安装 thunar'))
    return app.launch_uris([uri], context)


def _folder_uri(uri: str) -> bool:
    if urlsplit(uri).scheme in {"trash", "computer", "network"}:
        return True
    file = Gio.File.new_for_uri(uri)
    path = file.get_path()
    return path is not None and Path(path).is_dir()


def _file_manager_location(path: Path) -> str | None:
    """Recognize plain location shortcuts, never evaluate arbitrary launcher code."""
    try:
        data = GLib.KeyFile.new()
        data.load_from_file(str(path), GLib.KeyFileFlags.NONE)
        valid, args = GLib.shell_parse_argv(data.get_string("Desktop Entry", "Exec"))
        if not valid or len(args) != 2 or Path(args[0]).name not in {"pcmanfm", "pcmanfm-qt", "thunar", "Thunar", "nautilus", "dolphin"}:
            return None
        location = args[1]
        if location.startswith("/"):
            return Path(location).as_uri() if Path(location).is_dir() else None
        return location if _folder_uri(location) else None
    except (GLib.Error, OSError, ValueError):
        return None


def file_manager_location(path: Path) -> str | None:
    """Public wrapper: return the file-manager location a launcher opens, if any."""
    try:
        path = Path(path).expanduser()
        if path.suffix.lower() != ".desktop" or path.is_dir():
            return None
        return _file_manager_location(path)
    except (GLib.Error, OSError, ValueError):
        return None


def launch_entry(entry: Entry, context=None, allow_untrusted: bool = False) -> bool:
    """Open an entry through GIO; never shell-expand or execute plain files.

    A launcher in an XDG applications directory (including a symlink to one),
    or marked executable by its owner, is considered trusted.  Otherwise the UI
    must obtain consent and retry with allow_untrusted=True for that launch only.
    No permissions or trust attributes are changed.
    """
    path = Path(entry.path)
    if path.suffix.lower() == ".desktop" and not path.is_dir():
        current = _desktop_entry(path)
        if current is None:
            raise EntryLaunchError(_tr('启动器已被隐藏'))
        if current.error:
            raise EntryLaunchError(current.error)
        if current.kind == "application":
            location = _file_manager_location(path)
            if location is not None:
                return open_in_thunar(location, context)
            app = Gio.DesktopAppInfo.new_from_filename(str(path))
            if app is None:
                raise EntryLaunchError(_tr('无法读取应用启动器'))
            if not allow_untrusted and not _installed_launcher(path) and not os.access(path, os.X_OK):
                raise UntrustedLauncher(''.join([_tr('尚未信任启动器：'), f'{current.name}']))
            return app.launch([], context)
        if _folder_uri(current.uri):
            return open_in_thunar(current.uri, context)
        return Gio.AppInfo.launch_default_for_uri(current.uri, context)
    if not path.exists():
        raise EntryLaunchError(_tr('文件不存在，或符号链接的目标不存在'))
    if path.is_dir():
        return open_in_thunar(path.as_uri(), context)
    if _executable_text(path):
        editor = Gio.AppInfo.get_default_for_type("text/plain", False)
        if editor is None:
            raise EntryLaunchError(_tr('没有默认文本编辑器，无法安全打开可执行脚本'))
        return editor.launch([Gio.File.new_for_path(str(path))], context)
    return Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(str(path)).get_uri(), context)


def arrange_grid(
    keys: list[str], saved: dict[str, list[int]], columns: int, rows: int
) -> dict[str, tuple[int, int]]:
    """Keep valid saved cells, then fill free cells down each column.

    First occurrence wins for duplicate keys or saved-cell collisions.  Entries
    that exceed capacity are omitted so the caller can display further pages.
    """
    if columns <= 0 or rows <= 0:
        return {}
    unique_keys = list(dict.fromkeys(keys))
    occupied: set[tuple[int, int]] = set()
    positions: dict[str, tuple[int, int]] = {}
    for key in unique_keys:
        cell = saved.get(key)
        if (
            isinstance(cell, (list, tuple))
            and len(cell) == 2
            and all(type(value) is int for value in cell)
            and 0 <= cell[0] < columns
            and 0 <= cell[1] < rows
            and tuple(cell) not in occupied
        ):
            positions[key] = tuple(cell)
            occupied.add(tuple(cell))
    free = ((column, row) for column in range(columns) for row in range(rows) if (column, row) not in occupied)
    for key in unique_keys:
        if key not in positions:
            cell = next(free, None)
            if cell is None:
                break
            positions[key] = cell
    return {key: positions[key] for key in unique_keys if key in positions}


def atomic_save_json(path: Path, data) -> None:
    """Atomically replace a private JSON file, preserving it on write failure."""
    path = Path(path).expanduser()
    # Serialization first means malformed data never touches the filesystem.
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass

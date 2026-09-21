"""Versioned, allowlisted YAML configuration bundles; no executables or caches."""
import json
import os
from pathlib import Path
import tempfile
import tomllib

from adws_i18n import tr as _tr

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 8 * 1024 * 1024


def locations(desktop_state=None):
    config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')
    state = Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')
    result = {name: config/name for name in (
        'adws/taskbar-layout.json', 'adws/taskbar-pins.json', 'adws/setup.json', 'adws/wallpaper.json',
        'niri-desktop-layer/config.toml', 'mimeapps.list',
        'waybar/config-bottom.jsonc', 'waybar/style-bottom.css',
        'waybar/modules.jsonc', 'waybar/colors.css')}
    result['desktop/layout.json'] = desktop_state or state/'niri-desktop-layer/layout.json'
    return result


def yaml_module():
    try:
        import yaml
    except ImportError as exc:
        raise ValueError(_tr('需要 PyYAML，请重新运行安装程序补齐依赖。')) from exc
    return yaml


def export_bundle(destination, desktop_state=None):
    yaml = yaml_module()
    files = {name: path.read_text(encoding='utf-8') for name, path in locations(desktop_state).items() if path.is_file()}
    data = {'format': 'adws-config', 'version': 1,
            'source': {'home': str(Path.home()), 'root': str(ROOT)}, 'files': files}
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    if len(text.encode()) > LIMIT: raise ValueError(_tr('配置文件超过 8 MiB 限制。'))
    atomic_write(Path(destination), text.encode())


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.adws-config-', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream: stream.write(content)
        if path.exists(): temp.chmod(path.stat().st_mode & 0o777)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def read_bundle(source):
    yaml = yaml_module()
    raw = Path(source).read_bytes()
    if len(raw) > LIMIT: raise ValueError(_tr('配置文件超过 8 MiB 限制。'))
    # Reject aliases and duplicate keys instead of accepting ambiguous documents.
    class Loader(yaml.SafeLoader):
        def compose_node(self, parent, index):
            if self.check_event(yaml.AliasEvent): raise ValueError(_tr('配置文件不能包含 YAML 别名。'))
            return super().compose_node(parent, index)
        def construct_mapping(self, node, deep=False):
            pairs = self.construct_pairs(node, deep=deep)
            result = {}
            for key, value in pairs:
                if not isinstance(key, str) or key in result: raise ValueError(_tr('配置文件包含重复或无效字段。'))
                result[key] = value
            return result
    try: data = yaml.load(raw, Loader=Loader)
    except (yaml.YAMLError, RecursionError) as exc: raise ValueError(_tr('无法解析配置文件。')) from exc
    if not isinstance(data, dict) or data.get('format') != 'adws-config' or type(data.get('version')) is not int or data['version'] != 1:
        raise ValueError(_tr('不支持的 ADWS 配置格式或版本。'))
    files = data.get('files')
    if not isinstance(files, dict) or not files: raise ValueError(_tr('配置文件没有可导入的设置。'))
    allowed = locations()
    for name, text in files.items():
        if name not in allowed or not isinstance(text, str): raise ValueError(_tr('配置文件包含不允许的路径或内容。'))
        if name.endswith('.json'):
            value = json.loads(text)
            if not isinstance(value, dict): raise ValueError(_tr('JSON 配置必须是对象。'))
            if name == 'adws/taskbar-layout.json':
                from adws_panel_options import validate
                validate(value.get('options', {}))
                for key in ('builtins', 'plugins'):
                    if key in value and not isinstance(value[key], list): raise ValueError(_tr('组件列表格式无效。'))
        elif name.endswith('.jsonc'):
            from adws_layout import parse_jsonc
            if not isinstance(parse_jsonc(text), dict): raise ValueError(_tr('JSON 配置必须是对象。'))
        elif name.endswith('.toml'):
            tomllib.loads(text)
    return data


def import_bundle(data, desktop_state=None):
    """Import an already validated bundle; retain a persistent recovery copy."""
    targets = locations(desktop_state)
    state = Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/'adws/config-backups'
    state.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='import-', dir=state))
    previous = {}
    try:
        for name in data['files']:
            target = targets[name].resolve()
            previous[target] = target.read_bytes() if target.exists() else None
            if previous[target] is not None:
                copy = backup/name
                copy.parent.mkdir(parents=True, exist_ok=True)
                copy.write_bytes(previous[target])
        for name, text in data['files'].items():
            atomic_write(targets[name].resolve(), text.encode('utf-8'))
    except Exception:
        for path, content in previous.items():
            if content is None: path.unlink(missing_ok=True)
            else: atomic_write(path, content)
        raise
    return backup


def dialog(parent, importing=False, desktop_state=None):
    from gi.repository import Gtk
    title = _tr('导入全局配置') if importing else _tr('导出全局配置')
    chooser = Gtk.FileChooserDialog(title=title, transient_for=parent,
        action=Gtk.FileChooserAction.OPEN if importing else Gtk.FileChooserAction.SAVE)
    chooser.add_buttons(_tr('取消'), Gtk.ResponseType.CANCEL, title, Gtk.ResponseType.OK)
    file_filter = Gtk.FileFilter(); file_filter.set_name('ADWS Config (*.ad-yml)'); file_filter.add_pattern('*.ad-yml')
    chooser.add_filter(file_filter)
    if not importing:
        chooser.set_current_name('Config.ad-yml'); chooser.set_do_overwrite_confirmation(True)
    response = chooser.run(); filename = chooser.get_filename(); chooser.destroy()
    if response != Gtk.ResponseType.OK or not filename: return
    try:
        if importing:
            data = read_bundle(filename)
            confirm = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.OK_CANCEL, text=_tr('导入并覆盖这些设置？'))
            confirm.format_secondary_text('\n'.join(data['files'])+'\n\n'+_tr('配置可能包含启动器和插件命令，请仅导入可信文件。将备份现有配置；导入后重新启动组件生效。'))
            response = confirm.run(); confirm.destroy()
            if response != Gtk.ResponseType.OK: return
            backup = import_bundle(data, desktop_state)
            message = _tr('导入完成，原配置备份在：%s\n请重新打开设置，并重启桌面和任务栏以应用。') % backup
        else:
            # The chooser validates overwrite for exactly this destination.
            if not filename.endswith('.ad-yml'): raise ValueError(_tr('请使用 .ad-yml 文件扩展名。'))
            export_bundle(filename, desktop_state)
            message = _tr('配置已导出：%s') % filename
        result = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK, text=message)
        result.run(); result.destroy()
        if importing: parent.destroy()
    except (OSError, ValueError, TypeError, KeyError) as exc:
        error = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK, text=str(exc))
        error.run(); error.destroy()

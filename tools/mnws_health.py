"""Read-only installation checks; no GTK/display imports at module load."""
from mnws_i18n import tr as _tr
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def config_home():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')


def state_home():
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state')


def validate_waybar(config, style, data=None):
    from mnws_layout import parse_jsonc
    errors = []
    seen = set()
    def read(path):
        path = Path(path).expanduser()
        if path.resolve() in seen:
            return {}
        seen.add(path.resolve())
        try:
            return merge(parse_jsonc(path.read_text()), path.parent)
        except (OSError, ValueError) as error:
            errors.append(''.join([_tr('无法读取任务栏配置 '), f'{path}', ': ', f'{error}']))
            return {}
    def merge(obj, parent):
        result = {}
        includes = obj.get('include', [])
        if isinstance(includes, str):
            includes = [includes]
        if not isinstance(includes, list) or not all(isinstance(name, str) for name in includes):
            errors.append(_tr('任务栏 include 必须是路径字符串或字符串列表'))
            includes = []
        for name in includes:
            path = Path(os.path.expandvars(name)).expanduser()
            result.update(read(path if path.is_absolute() else parent / path))
        result.update(obj)
        return result
    config, style = Path(config), Path(style)
    obj = merge(data, config.parent) if data is not None else read(config)
    active = []
    for slot in ('left', 'center', 'right'):
        modules = obj.get(f'modules-{slot}', [])
        if not isinstance(modules, list) or not all(isinstance(name, str) for name in modules):
            errors.append(''.join(['modules-', f'{slot}', _tr(' 必须是字符串列表')]))
        else:
            active.extend(modules)
    processed = set()
    for module in active:
        if module in processed:
            continue
        processed.add(module)
        definition = obj.get(module, {})
        if not isinstance(definition, dict):
            errors.append(''.join([_tr('组件配置必须是对象：'), f'{module}']))
            continue
        if module.startswith('group/'):
            children = definition.get('modules', [])
            if isinstance(children, list) and all(isinstance(name, str) for name in children):
                active.extend(children)
            else:
                errors.append(''.join([_tr('分组 modules 必须是字符串列表：'), f'{module}']))
        if module.startswith('cffi/'):
            library = definition.get('module_path')
            if not isinstance(library, str) or not library or not Path(os.path.expandvars(library)).expanduser().is_file():
                errors.append(''.join([_tr('缺少组件动态库：'), f'{module}', ' (', f"{library or '未配置 module_path'}", ')']))
        if module.startswith('custom/') and not definition:
            errors.append(''.join([_tr('缺少组件定义：'), f'{module}']))
    visited = set()
    def check_style(path):
        if path.resolve() in visited:
            return
        visited.add(path.resolve())
        try:
            css = path.read_text()
        except OSError as error:
            errors.append(''.join([_tr('无法读取任务栏样式 '), f'{path}', ': ', f'{error}']))
            return
        for name in re.findall(r'@import\s+(?:url\()?\s*["\']([^"\']+)', css):
            if '://' not in name:
                check_style(path.parent / name)
    check_style(style)
    return errors


def dependency_errors():
    errors = []
    if sys.version_info < (3, 11):
        errors.append(_tr('需要 Python 3.11 或更新版本'))
    for program in ('waybar', 'niri', 'systemctl', 'thunar'):
        if not shutil.which(program):
            errors.append(''.join([_tr('缺少运行依赖：'), f'{program}']))
    probe = """import gi, cairo
from PIL import ImageFilter
for name, version in [('Gtk','3.0'),('Gdk','3.0'),('GtkLayerShell','0.1'),('PangoCairo','1.0'),('Gio','2.0')]:
 gi.require_version(name, version)
 __import__('gi.repository', fromlist=[name])
"""
    result = subprocess.run([sys.executable, '-c', probe], capture_output=True, text=True)
    if result.returncode:
        errors.append(_tr('Python/GTK 依赖不完整：') + (result.stderr.strip().splitlines() or [_tr('依赖探测失败')])[-1])
    return errors



def desktop_path():
    sys.path.insert(0, str(ROOT / 'src/niri-desktop-layer'))
    from desktop_layer.config import load_config
    from desktop_layer.model import desktop_directory
    cfg = load_config()
    return Path(cfg.directory).expanduser().absolute() if cfg.directory else desktop_directory()


def initialize_desktop():
    try:
        desktop_path().mkdir(parents=True, exist_ok=True)
        return 0
    except (ImportError, ValueError, OSError) as error:
        print(''.join([_tr('无法初始化桌面目录：'), f'{error}']), file=sys.stderr)
        return 1

def check(preinstall=False):
    errors = dependency_errors()
    live = config_home() / 'waybar'
    if preinstall:
        for name in ('libniri_taskbar.so', 'libwaybar-space.so'):
            path = Path.home() / '.local/lib/waybar' / name
            if not path.is_file():
                errors.append(''.join([_tr('缺少动态库：'), f'{path}', _tr('；请先按 README 构建并安装')]))
        # Preserve existing files; defaults fill only absent destinations.
        for name in ('config-bottom.jsonc', 'style-bottom.css', 'modules.jsonc', 'colors.css'):
            path = live / name
            if path.is_symlink() and not path.exists():
                errors.append(''.join([_tr('配置链接已失效，请先修复：'), f'{path}']))
            elif not path.exists() and not (ROOT / 'config/waybar' / name).is_file():
                errors.append(''.join([_tr('缺少默认配置：'), f'{name}']))
    else:
        errors.extend(validate_waybar(live / 'config-bottom.jsonc', live / 'style-bottom.css'))
        # Inspect planned modules without materializing plugin caches or writing config.
        try:
            from mnws_layout import (load_layout, enabled_builtins, taskbar_library_path,
                                     desktop_space_library_path, read_live_config, scan_available_plugins)
            layout = load_layout()
            libraries = [desktop_space_library_path(layout, read_live_config())]
            if any(item['module'] == 'cffi/niri-taskbar' for item in enabled_builtins(layout)):
                libraries.append(taskbar_library_path(layout))
            packages = {item['manifest']['id']: item['manifest'] for item in scan_available_plugins() if item.get('ok')}
            for plugin in layout.get('plugins', []):
                if plugin.get('enabled'):
                    manifest = packages.get(plugin.get('package'))
                    if manifest is None:
                        errors.append(''.join([_tr('启用的插件包不可用：'), f"{plugin.get('package')}"]))
                    elif 'panel.rows-v1' in manifest.get('interfaces', []):
                        libraries.append(Path.home() / '.local/lib/waybar/libmnws_panel.so')
            for library in libraries:
                if not library.is_file():
                    errors.append(''.join([_tr('布局所需动态库不存在：'), f'{library}']))
        except (OSError, ValueError) as error:
            errors.append(''.join([_tr('布局配置无效：'), f'{error}']))
    if not errors:
        try:
            desktop = desktop_path()
            if desktop.exists() and not desktop.is_dir():
                errors.append(''.join([_tr('桌面路径不是目录：'), f'{desktop}']))
            elif not preinstall and not desktop.is_dir():
                errors.append(''.join([_tr('缺少桌面目录：'), f'{desktop}', _tr('；运行 mnws install 或启动桌面以初始化')]))
        except (ImportError, ValueError, OSError) as error:
            errors.append(''.join([_tr('桌面配置无效：'), f'{error}']))
    modules = live / 'modules.jsonc'
    if preinstall and not modules.exists():
        modules = ROOT / 'config/waybar/modules.jsonc'
    try:
        from mnws_layout import parse_jsonc
        command = parse_jsonc(modules.read_text()).get('custom/applauncher', {}).get('on-click', '')
        if not preinstall and command.strip().startswith('rofi ') and not shutil.which('rofi'):
            errors.append(_tr('应用菜单缺少 rofi；请安装或配置其他启动器'))
        if not preinstall and command.strip() == 'fuzzel' and not shutil.which('fuzzel'):
            errors.append(_tr('应用菜单缺少 fuzzel；请安装或配置其他启动器'))
    except (OSError, ValueError):
        pass
    for error in dict.fromkeys(errors):
        print(_tr('错误：') + error, file=sys.stderr)
    if not errors:
        print(_tr('依赖、配置与组件文件检查通过。') if not preinstall else _tr('安装预检通过。'))
    return 1 if errors else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--preinstall', action='store_true')
    parser.add_argument('--init-desktop', action='store_true')
    args = parser.parse_args()
    raise SystemExit(initialize_desktop() if args.init_desktop else check(args.preinstall))

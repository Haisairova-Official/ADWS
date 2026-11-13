"""Launch a foreground native taskbar using a private snapshot of the ADWS layout."""
import argparse
import glob
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile

import adws_layout as layout
from adws_i18n import chinese
from adws_panel_options import surface_from_css
from adws_waybar import decode

ROOT = Path(__file__).resolve().parents[1]


def choose_binary(path):
    if path:
        executable = path.expanduser().absolute()
        if executable.is_file() and os.access(executable, os.X_OK):
            return executable
        raise ValueError(f'Cannot execute {executable}')
    built = ROOT / 'libexec/taskbar-preview/adws-taskbar'
    if built.is_file() and os.access(built, os.X_OK):
        return built
    target = ROOT / 'src/adws-taskbar/target'
    for profile in ('debug', 'release'):
        candidate = target / profile / 'adws-taskbar'
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise ValueError('Build the native taskbar first: ./adws build-taskbar-preview')


def merge_defaults(current, defaults):
    # Waybar gives the main object and earlier includes precedence, recursively.
    for key, value in defaults.items():
        if key not in current:
            current[key] = value
        elif isinstance(current[key], dict) and isinstance(value, dict):
            merge_defaults(current[key], value)


def expanded_config(path, parents=()):
    path = Path(path).expanduser().absolute()
    resolved = path.resolve()
    if resolved in parents or len(parents) >= 100:
        raise ValueError(f'Recursive or excessively nested config include: {path}')
    obj = decode(path.read_text(encoding='utf-8-sig'))
    if isinstance(obj, list):
        if len(obj) != 1:
            raise ValueError(f'Expected exactly one taskbar configuration in {path}')
        obj = obj[0]
    names = obj.pop('include', [])
    if isinstance(names, str):
        names = [names]
    if not isinstance(names, list) or not all(isinstance(name, str) and name for name in names):
        raise ValueError(f'Invalid include in {path}')
    for name in names:
        included = path.parent / Path(os.path.expandvars(name)).expanduser()
        matches = sorted(glob.glob(str(included))) if glob.has_magic(str(included)) else [included]
        for child in matches:
            merge_defaults(obj, expanded_config(child, (*parents, resolved)))
    return obj


# A relocated style must resolve references against its original directory.
# Leave comments, quoted CSS values and external/resource URLs untouched.
_CSS_REFERENCE = re.compile(
    r'/\*.*?\*/|@import\s+(?P<import>"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')'
    r'|url\(\s*(?P<url>"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|(?:\\.|[^)\s])+?)\s*\)'
    r'|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.I | re.S,
)


def relocate_css(text, origin):
    def replace(match):
        if not match.lastgroup:
            return match.group()
        token = match.group(match.lastgroup)
        value = token[1:-1] if token.startswith(('"', "'")) else token
        if not value or value.startswith(('#', '/')) or re.match(r'[a-zA-Z][\w+.-]*:', value):
            return match.group()
        # Prefix the absolute directory inside the CSS token. Keep the filename's
        # original CSS escapes, including quoted spaces, hex escapes and quotes.
        quote = token[0] if token.startswith(('"', "'")) else '"'
        prefix = (str(origin.parent.absolute()) + '/').replace('\\', '\\\\').replace(quote, '\\' + quote)
        if token == value:
            value = value.replace('"', '\\"')
        start, end = match.span(match.lastgroup)
        return match.group()[:start-match.start()] + quote + prefix + value + quote + match.group()[end-match.start():]
    return _CSS_REFERENCE.sub(replace, text)


def use_preview_modules(bar):
    # Relocate only ADWS's stock libraries. Paths chosen for other modules and
    # custom builds must keep their meaning in both renderers.
    stock = Path.home() / '.local/lib/waybar'
    built = ROOT / 'libexec/taskbar-preview'
    bundled = {name: built / name for name in ('libadws_panel.so', 'libniri_taskbar.so', 'libwaybar-space.so')}
    for key, definition in bar.items():
        if not key.startswith('cffi/') or not isinstance(definition, dict):
            continue
        path = definition.get('module_path')
        if isinstance(path, str):
            origin = Path(path)
            candidate = bundled.get(origin.name)
            if candidate and candidate.is_file() and origin in (
                stock / origin.name, ROOT / 'src/niri-desktop-layer/integration/libwaybar-space.so',
            ):
                definition['module_path'] = str(candidate)


def generate(directory, config=None, style=None, layout_path=None, plugin_dir=None):
    directory = Path(directory)
    shipped = ROOT / 'config/waybar'
    base_path = config or layout.live_config_path()
    if config is None and not base_path.exists():
        base_path = shipped / 'config-bottom.jsonc'
    style_path = (style or layout.live_style_path()).expanduser().absolute()
    if style is None and not style_path.exists():
        style_path = shipped / 'style-bottom.css'
    base = expanded_config(base_path)
    css = style_path.read_text(encoding='utf-8')
    if config is None or layout_path is not None:
        if layout_path is None:
            model = layout.load_layout()
        else:
            # An explicitly named, invalid layout must not silently show defaults.
            raw = json.loads(layout_path.expanduser().read_text(encoding='utf-8'))
            if not isinstance(raw, dict):
                raise ValueError('Expected a layout object')
            model = layout.normalize_layout(raw)
        available = layout.scan_available_plugins(folder=plugin_dir) if plugin_dir is not None else None
        rendered = layout.render_waybar_config(model, available=available, base=base, config_path=base_path,
                                               plugin_cache=directory / 'packages')
        options = {**rendered['_adws_options'], **surface_from_css(css)}
        block = layout.render_css_block(rendered['_adws_css_rules'], options)
        patched = layout.patch_style(css, block)
        if patched != css:
            preview_style = directory / 'bar.css'
            preview_style.write_text(relocate_css(patched, style_path), encoding='utf-8')
            style_path = preview_style
        base = rendered
    use_preview_modules(base)
    bar = directory / 'bar.json'
    bar.write_text(layout.config_to_jsonc(base), encoding='utf-8')
    return bar, style_path


def prepare_workspace(directory, config=None, style=None, layout_path=None):
    config_home = directory / 'config'
    adws = config_home / 'adws'
    waybar = config_home / 'waybar'
    plugins = directory / 'plugins'
    for folder in (adws, waybar, plugins, directory / 'adws/plugin-health', directory / 'adws/plugin-preview'):
        folder.mkdir(mode=0o700, parents=True)
    # Seed copies, never links: pin/unpin, plugin uninstall and settings apply
    # all use their usual paths inside the private XDG tree.
    for package in layout.mplg.scan_packages():
        shutil.copyfile(package, plugins / package.name)
    current = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    for relative in ('adws/taskbar-pins.json', 'adws/sidebar.json', 'adws/power-policy.json',
                     'adws/vm-mode.json', 'gtk-3.0/settings.ini', 'gtk-3.0/gtk.css', 'waybar/colors.css'):
        source = current / relative
        if source.is_file():
            target = config_home / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.suffix == '.css':
                target.write_text(relocate_css(source.read_text(encoding='utf-8'), source), encoding='utf-8')
            else:
                shutil.copyfile(source, target)
    model = layout.load_layout(layout_path)
    layout.save_layout(model, adws / 'taskbar-layout.json')
    bar, original_style = generate(directory, config, style, layout_path, plugin_dir=plugins)
    shutil.copyfile(bar, waybar / 'config-bottom.jsonc')
    private_style = waybar / 'style-bottom.css'
    private_style.write_text(relocate_css(original_style.read_text(encoding='utf-8'), original_style), encoding='utf-8')
    bin_dir = directory / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'adws').symlink_to(ROOT / 'adws')
    env = {**os.environ,
           'PATH': str(bin_dir) + os.pathsep + os.environ.get('PATH', os.defpath),
           'ADWS_TASKBAR_PREVIEW': '1', 'ADWS_PLUGIN_RUNTIME_DIR': str(directory),
           'ADWS_CACHE_DIR': str(directory / 'packages'), 'ADWS_PLUGIN_DIR': str(plugins),
           'ADWS_TASKBAR_PINS_FILE': str(adws / 'taskbar-pins.json'),
           'XDG_CONFIG_HOME': str(config_home), 'XDG_CACHE_HOME': str(directory / 'cache'),
           'XDG_STATE_HOME': str(directory / 'state')}
    return bar, private_style, env


def process_start(pid):
    # proc stat fields after the final ')' begin with field 3 (state).
    return (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[19]


def register_host(proc, env, nested):
    directory = Path(env['ADWS_PLUGIN_RUNTIME_DIR'])
    try:
        start = process_start(proc.pid)
    except FileNotFoundError:
        return  # --check or a failed launch can finish before registration
    (directory / 'native-host.json').write_text(json.dumps({'pid': proc.pid, 'start': start, 'nested': nested}))


def follow_preview(window):
    """Close a preview settings window when its owning native host exits."""
    if os.environ.get('ADWS_TASKBAR_PREVIEW') != '1':
        return
    from gi.repository import GLib
    directory = Path(os.environ['ADWS_PLUGIN_RUNTIME_DIR'])
    try:
        owner = json.loads((directory/'native-host.json').read_text())
        fd = os.pidfd_open(owner['pid'])
        try:
            if process_start(owner['pid']) != owner['start']:
                raise ProcessLookupError('Preview closed')
        except OSError:
            os.close(fd)
            raise
    except (KeyError, OSError, ValueError):
        GLib.idle_add(window.destroy)
        return
    source = None
    def owner_exited(*_):
        nonlocal source
        source = None
        window.destroy()
        return False
    def release(*_):
        if source is not None:
            GLib.source_remove(source)
        os.close(fd)
    try:
        from gi.repository import GLibUnix
        add_watch = GLibUnix.fd_add_full
    except ImportError:  # Older GLib exposes this under the GLib namespace.
        add_watch = GLib.unix_fd_add_full
    source = add_watch(GLib.PRIORITY_DEFAULT, fd, GLib.IO_IN | GLib.IO_HUP, owner_exited)
    window.connect('destroy', release)


def reload_preview():
    # Hold a pidfd before checking process identity. A stale dialog cannot
    # signal a recycled PID or start/stop a regular Waybar.
    directory = Path(os.environ['ADWS_PLUGIN_RUNTIME_DIR'])
    try:
        host = json.loads((directory / 'native-host.json').read_text())
        pid = host['pid']
        handle = os.pidfd_open(pid)
        try:
            if process_start(pid) != host['start']:
                raise ValueError('preview process has exited')
            expected = str(directory / 'bar.json')
            argv = (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')
            if os.fsencode(expected) not in argv:
                raise ValueError('preview process is no longer running this configuration')
            status = (Path('/proc') / str(pid) / 'status').read_text()
            caught = int(re.search(r'^SigCgt:\s*([0-9a-fA-F]+)', status, re.M).group(1), 16)
            if not caught & (1 << (signal.SIGUSR2 - 1)):
                raise ValueError('the preview has not enabled configuration reload')
            bar = expanded_config(layout.live_config_path())
            use_preview_modules(bar)
            if host['nested']:
                bar.pop('output', None)
            from adws_atomic import replace_files
            replace_files({Path(expected): layout.config_to_jsonc(bar).encode('utf-8')})
            signal.pidfd_send_signal(handle, signal.SIGUSR2)
        finally:
            os.close(handle)
    except (KeyError, OSError, ValueError) as error:
        return False, ('无法刷新临时预览：' if chinese() else 'Cannot refresh this preview: ') + str(error)
    return True, '设置已应用到本次预览。' if chinese() else 'Settings applied to this temporary preview.'


def run_host(command, env):
    child = None
    received = None
    def forward(signum, _frame):
        nonlocal received
        received = signum
        if child is not None and child.poll() is None:
            child.send_signal(signum)
    handlers = {sig: signal.signal(sig, forward) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        child = subprocess.Popen(command, env=env, start_new_session=True)
        register_host(child, env, nested=False)
        if received is not None:
            child.send_signal(received)
        code = child.wait()
        return 128 - code if code < 0 else code
    finally:
        for sig, previous in handlers.items():
            signal.signal(sig, previous)


def main(argv=None):
    zh = chinese()
    parser = argparse.ArgumentParser(prog='adws taskbar-preview', description=(
        '在前台试运行原生任务栏，按 Ctrl+C 关闭。' if zh else 'Run the native taskbar in the foreground. Press Ctrl+C to close it.'
    ))
    parser.add_argument('--binary', type=Path, help='原生任务栏程序路径' if zh else 'path to the native taskbar executable')
    parser.add_argument('--config', type=Path, help='直接读取底栏 JSON/JSONC 配置' if zh else 'use a bottom-bar JSON/JSONC configuration directly')
    parser.add_argument('--layout', type=Path, help='根据指定的 ADWS 布局重建底栏配置' if zh else 'render an ADWS layout into the bar configuration')
    parser.add_argument('--style', type=Path, help='底栏 GTK CSS 样式表' if zh else 'GTK stylesheet for the bar')
    session = parser.add_mutually_exclusive_group()
    session.add_argument('--nested', dest='nested', action='store_true', help='在独立的 Niri 窗口内预览（默认）' if zh else 'preview in a separate Niri window (default)')
    session.add_argument('--current-session', dest='nested', action='store_false', help='在当前显示会话中试运行' if zh else 'test directly on the current display')
    parser.set_defaults(nested=True)
    parser.add_argument('--check', action='store_true', help='校验后退出' if zh else 'validate the configuration and exit')
    args = parser.parse_args(argv)
    try:
        binary = choose_binary(args.binary)
        with tempfile.TemporaryDirectory(prefix='adws-taskbar-preview-') as workspace:
            directory = Path(workspace)
            config, style, env = prepare_workspace(directory, args.config, args.style, args.layout)
            command = [str(binary), '--config', str(config), '--style', str(style)]
            if args.check:
                command.append('--check')
            if args.nested and not args.check:
                from adws_taskbar_nested import run_nested
                return run_nested(command, env, directory)
            return run_host(command, env)
    except (OSError, ValueError) as error:
        print(f'adws taskbar-preview: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Validated, backed-up installation of the ADWS VM mode integration."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from adws_atomic import replace_files
from adws_i18n import tr
import adws_vm_mode as mode

MARKER = '# Managed by ADWS virtual machine mode.'


def service_content(script, config):
    def quote(path):
        return json.dumps(str(path), ensure_ascii=False).replace('%', '%%')
    return (MARKER + '\n[Unit]\nDescription=ADWS virtual machine keyboard mode\n'
            'After=niri.service\nPartOf=graphical-session.target\nConditionEnvironment=NIRI_SOCKET\n\n'
            '[Service]\nType=simple\nExecStart=/usr/bin/python3 ' + quote(script) +
            ' daemon --config ' + quote(config) + '\nRestart=on-failure\nRestartSec=1\n'
            'KillMode=control-group\nTimeoutStopSec=15\n\n'
            '[Install]\nWantedBy=graphical-session.target\n')


def service(*args):
    result = subprocess.run(['systemctl', '--user', *args], capture_output=True, text=True, timeout=25)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or tr('虚拟机模式服务操作失败。'))


def check_conflicts(originals, shortcut, excluded):
    identity = shortcut.casefold()
    def inspect(nodes, inactive=False):
        for node in nodes:
            inactive_node = inactive or node.disabled
            if node.name == 'binds' and not inactive_node:
                for bind in node.children:
                    if bind.disabled:
                        continue
                    try:
                        existing = mode.validated_options({'auto_switch': True, 'shortcut': bind.name})['shortcut']
                    except ValueError:
                        continue
                    if existing.casefold() == identity:
                        raise ValueError(tr('快捷键 %s 已被其他桌面动作使用，请选择另一组。') % shortcut)
            inspect(node.children, inactive_node)
    for path, content in originals.items():
        if path not in excluded:
            inspect(mode.parse_nodes(mode.tokens(content)))


def backup(files):
    state = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state')
    directory = state / 'adws/vm-mode-backups' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    directory.mkdir(parents=True, mode=0o700)
    manifest = {}
    for path in files:
        if path.exists():
            name = hashlib.sha256(str(path).encode()).hexdigest()[:12] + '-' + path.name
            shutil.copy2(path, directory / name)
            manifest[str(path)] = name
        else:
            manifest[str(path)] = None
    (directory / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return directory


def apply_options(options, *, config=None, settings=None, script=None, unit=None, wrapper=None):
    options = mode.validated_options(options)
    config = (Path(config) if config is not None else mode.CONFIG).resolve()
    settings = Path(settings) if settings is not None else mode.OPTIONS
    script = Path(script) if script is not None else mode.SCRIPT
    unit = Path(unit) if unit is not None else mode.CONFIG_HOME / 'systemd/user/niri-vm-mode.service'
    wrapper = Path(wrapper) if wrapper is not None else mode.CONFIG_HOME / 'niri/scripts/niri-vm-mode.py'
    old = config.read_text()
    clean = mode.clean_integration(old)
    binding = '// Managed by ADWS virtual machine mode.\n' + mode.toggle_binding(script, options['shortcut'])
    included = config.parent / ('.adws-vm-mode-' + hashlib.sha256(binding.encode()).hexdigest()[:20] + '.kdl')
    created = not included.exists()
    if not created and included.read_text() != binding:
        raise ValueError(tr('虚拟机模式快捷键文件发生冲突，未修改配置。'))
    if created:
        with included.open('x') as stream:
            stream.write(binding)
    updated = clean.rstrip() + '\n\n' + mode.BEGIN + '\ninclude ' + json.dumps(included.name) + '\n' + mode.END + '\n'
    probe = None
    committed = False
    try:
        with tempfile.NamedTemporaryFile(mode='w', prefix='.adws-vm-check-', suffix='.kdl', dir=config.parent, delete=False) as stream:
            probe = Path(stream.name)
            stream.write(updated)
        # Validate the whole prospective config and inspect the include tree,
        # excluding only the newly managed recovery bind.
        mode.validate(probe)
        with tempfile.TemporaryDirectory(prefix='adws-vm-check-') as directory:
            _, originals = mode.snapshot_config(probe, Path(directory), passthrough=False)
            check_conflicts(originals, options['shortcut'], {included})
        if config.read_text() != old:
            raise ValueError(tr('Niri 配置已被其他程序修改，请刷新后重试。'))
        wrapper_text = ('#!/usr/bin/python3\n' + MARKER + '\nimport runpy, sys\nsys.path.insert(0, ' +
                        repr(str(script.parent)) + ')\nrunpy.run_path(' +
                        repr(str(script)) + ', run_name="__main__")\n')
        files = {config: updated.encode(), settings: (json.dumps(options, ensure_ascii=False, indent=2) + '\n').encode(),
                 unit: service_content(script, config).encode(), wrapper: wrapper_text.encode()}
        previous = {path: path.read_bytes() if path.exists() else None for path in files}
        saved = backup(files)
        had_unit = unit.exists()
        if had_unit:
            service('stop', 'niri-vm-mode.service')
        written = False
        try:
            # Recheck after stopping: another settings writer must not be lost.
            if config.read_text() != old:
                raise ValueError(tr('Niri 配置已被其他程序修改，请刷新后重试。'))
            if any(path != probe and path.read_text() != content for path, content in originals.items()):
                raise ValueError(tr('Niri 配置已被其他程序修改，请刷新后重试。'))
            replace_files(files)
            written = True
            wrapper.chmod(0o755)
            service('daemon-reload')
            service('enable', '--now', 'niri-vm-mode.service')
            committed = True
        except BaseException as error:
            failures = []
            def recover(*args):
                try:
                    service(*args)
                except Exception as exc:
                    failures.append(str(exc))
            recover('stop', 'niri-vm-mode.service')
            if written and not had_unit:
                recover('disable', 'niri-vm-mode.service')
            if written:
                # Restore only files still holding our update; preserve outside edits.
                owned = {path: content for path, content in previous.items()
                         if path.exists() and path.read_bytes() == files[path]}
                replace_files({path: content for path, content in owned.items() if content is not None})
                for path, content in owned.items():
                    if content is None:
                        path.unlink(missing_ok=True)
            recover('daemon-reload')
            if had_unit:
                recover('start', 'niri-vm-mode.service')
            if failures:
                raise RuntimeError(str(error) + '; ' + '; '.join(failures)) from error
            raise
        return {'options': options, 'backup': str(saved)}
    finally:
        if probe is not None:
            probe.unlink(missing_ok=True)
        if created and not committed and included.name not in config.read_text():
            included.unlink(missing_ok=True)


def uninstall():
    from adws_health import config_home
    from adws_windows import config_path
    directory = config_home()
    config = config_path()
    unit = directory / 'systemd/user/niri-vm-mode.service'
    if not unit.exists() or MARKER not in unit.read_text():
        return
    service('stop', 'niri-vm-mode.service')
    service('disable', 'niri-vm-mode.service')
    if config.exists():
        text = config.read_text()
        clean = mode.clean_integration(text)
        if clean != text:
            backup([config])
            replace_files({config: clean.encode()})
    unit.unlink()
    wrapper = directory / 'niri/scripts/niri-vm-mode.py'
    if wrapper.exists() and MARKER in wrapper.read_text():
        wrapper.unlink()
    service('daemon-reload')

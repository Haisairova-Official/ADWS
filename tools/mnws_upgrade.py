"""Stage and install one confirmed MNWS release, preserving the installed root path."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

from mnws_i18n import tr as _tr
from mnws_update import ROOT, REPOSITORY, github_urls, release_version, version_key

LIBRARIES = ('libniri_taskbar.so', 'libmnws_panel.so', 'libwaybar-space.so')
MAX_DOWNLOAD = 512 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024
# User-editable templates, custom images and the legacy in-tree desktop state.
PRESERVE = ('config', 'samples', 'assets', 'src/niri-desktop-layer/state')


def state_dir():
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'mnws'


def atomic_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.mnws-update-', dir=target.parent)
    os.close(fd)
    try:
        shutil.copy2(source, name)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


def download(url, target, use_proxy, digest=None):
    errors = []
    for candidate in github_urls(url, use_proxy):
        try:
            request = urllib.request.Request(candidate, headers={'User-Agent': 'MNWS-update'})
            count = 0
            checksum = hashlib.sha256()
            with urllib.request.urlopen(request, timeout=30) as response, target.open('wb') as stream:
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > MAX_DOWNLOAD:
                        raise ValueError(_tr('更新包超过大小限制。'))
                    checksum.update(chunk)
                    stream.write(chunk)
            if digest and checksum.hexdigest() != digest:
                raise ValueError(_tr('更新包校验失败。'))
            # Check ZIP CRC here, so a broken proxy response can fall back to GitHub.
            with zipfile.ZipFile(target) as archive:
                if len(archive.infolist()) > 30000 or sum(info.file_size for info in archive.infolist()) > MAX_EXPANDED:
                    raise ValueError(_tr('更新包超过大小限制。'))
                if archive.testzip() is not None:
                    raise ValueError(_tr('更新包校验失败。'))
            return
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            target.unlink(missing_ok=True)
            errors.append(str(error))
    raise RuntimeError(_tr('下载更新失败：%s') % '\n'.join(errors))


def extract(archive_path, destination):
    """Accept regular files only; do not follow archive paths or links outside staging."""
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if len(entries) > 30000 or sum(item.file_size for item in entries) > MAX_EXPANDED:
            raise ValueError(_tr('更新包超过大小限制。'))
        seen = set()
        for item in entries:
            path = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            if (path.is_absolute() or '..' in path.parts or '\\' in item.filename
                    or item.filename in seen or stat.S_ISLNK(mode)
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise ValueError(_tr('更新包包含不安全的路径或文件。'))
            seen.add(item.filename)
            target = destination.joinpath(*path.parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if mode & 0o111 else 0o644)
    roots = [destination] + [path for path in destination.iterdir() if path.is_dir()]
    roots = [path for path in roots if (path / 'build-info.json').is_file() and (path / 'mnws').is_file()]
    if len(roots) != 1:
        raise ValueError(_tr('更新包不是完整的 MNWS 安装包。'))
    root = roots[0]
    for name in ('tools/mnws_runtime.py', 'tools/mnws_uninstall.py', 'src/niri-desktop-layer/desktop-layer',
                 'src/niri-desktop-layer/start-desktop-layer', 'tools/mnws-config.py'):
        if not (root / name).is_file():
            raise ValueError(_tr('更新包不是完整的 MNWS 安装包。'))
    for name in ('mnws', 'install.sh', 'tools/mnws-config.py', 'scripts/taskbar-toggle.sh',
                 'scripts/taskbar-state.sh', 'src/niri-desktop-layer/desktop-layer',
                 'src/niri-desktop-layer/start-desktop-layer'):
        if (root / name).is_file():
            (root / name).chmod(0o755)
    return root


def package(release):
    tag = release['tag_name']
    version_key(tag)  # Do not accept arbitrary refs or paths.
    prefix = f'https://github.com/{REPOSITORY}/releases/download/' + urllib.parse.quote(tag, safe='') + '/'
    try:
        arch = platform.freedesktop_os_release().get('ID') == 'arch' and platform.machine() == 'x86_64'
    except OSError:
        arch = False
    if arch:
        assets = release.get('assets') or []
        if not isinstance(assets, list):
            raise ValueError(_tr('更新包不是完整的 MNWS 安装包。'))
        for asset in assets:
            name = asset.get('name', '') if isinstance(asset, dict) else ''
            if isinstance(name, str) and re.fullmatch(r'MNWS[\w.-]+_for_arch\.zip', name, re.I):
                checksum = asset.get('digest')
                digest = checksum[7:] if isinstance(checksum, str) and re.fullmatch(r'sha256:[0-9a-fA-F]{64}', checksum) else None
                return prefix + urllib.parse.quote(name, safe=''), digest.lower() if digest else None, True
    return f'https://github.com/{REPOSITORY}/archive/refs/tags/' + urllib.parse.quote(tag, safe='') + '.zip', None, False


def run(command, cwd, log, env=None):
    log.write(('\n$ ' + shlex.join(map(str, command)) + '\n').encode())
    log.flush()
    subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                   stdin=subprocess.DEVNULL, env=env, check=True)


def prepare_libraries(root, prebuilt, log):
    run([sys.executable, '-m', 'compileall', '-q', str(root / 'tools'), str(root / 'src/niri-desktop-layer/desktop_layer')], root, log)
    if prebuilt:
        manifest = json.loads((root / 'prebuilt/manifest.json').read_text())
        if not isinstance(manifest, dict):
            raise ValueError(_tr('更新包校验失败。'))
        if (manifest.get('os') != 'arch' or manifest.get('arch') != 'x86_64'
                or version_key(manifest.get('version', '')) != installed_version(root)):
            raise ValueError(_tr('安装包版本与所选更新不一致。'))
        paths = {name: Path('prebuilt') / name for name in LIBRARIES}
        for name, path in paths.items():
            if hashlib.sha256((root / path).read_bytes()).hexdigest() != manifest.get('sha256', {}).get(name):
                raise ValueError(_tr('更新包校验失败。'))
    else:
        required = ('cargo', 'rustc', 'cc', 'make', 'pkg-config')
        missing = [name for name in required if not shutil.which(name)]
        if missing:
            raise RuntimeError(_tr('缺少构建依赖：%s。请安装后重试，当前版本未修改。') % ', '.join(missing))
        run(['cargo', 'build', '--release', '--locked', '--manifest-path', str(root / 'src/niri-taskbar/Cargo.toml')], root, log, env={key: value for key, value in os.environ.items() if key != 'CARGO_TARGET_DIR'})
        run(['make', '-B', '-C', str(root / 'src/panel-rows')], root, log)
        flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gtk+-3.0', 'gtk-layer-shell-0'], text=True)
        output = root / 'src/niri-desktop-layer/integration/libwaybar-space.so'
        run(['cc', '-shared', '-fPIC', '-O2', str(root / 'src/niri-desktop-layer/integration/waybar-space.c'),
             '-o', str(output), *shlex.split(flags)], root, log)
        paths = {'libniri_taskbar.so': Path('src/niri-taskbar/target/release/libniri_taskbar.so'),
                 'libmnws_panel.so': Path('src/panel-rows/libmnws_panel.so'),
                 'libwaybar-space.so': Path('src/niri-desktop-layer/integration/libwaybar-space.so')}
    for path in paths.values():
        if not (root / path).is_file():
            raise ValueError(_tr('更新包缺少原生组件。'))
        if shutil.which('ldd'):
            result = subprocess.run(['ldd', str(root / path)], capture_output=True, text=True, env={**os.environ, 'LC_ALL': 'C'})
            if result.returncode or 'not found' in result.stdout:
                raise RuntimeError(_tr('更新组件与当前系统不兼容：%s') % (result.stdout + result.stderr))
    return paths


@contextmanager
def update_lock():
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'update.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(_tr('另一个更新正在进行，请稍后重试。')) from error
        yield


def control(root, component, operation, log):
    run(['bash', str(root / 'mnws'), component, operation], root, log)


def replace_installation(root, prepared, libraries, log):
    # Imported before the directory swap: the running updater keeps using its own code.
    from mnws_runtime import pids
    record = state_dir() / 'install-record.json'
    libdir = Path.home() / '.local/lib/waybar'
    backup = root.parent / ('.' + root.name + '-backup-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    backup.mkdir()
    (backup / 'libraries').mkdir()
    existed = {}
    for name in LIBRARIES:
        existed[name] = (libdir / name).exists()
        if existed[name]:
            shutil.copy2(libdir / name, backup / 'libraries' / name)
    old_record = record.read_bytes() if record.exists() else None
    if old_record is not None:
        (backup / 'install-record.json').write_bytes(old_record)
    running = [component for component in ('desktop', 'taskbar') if pids(component)]
    moved = False
    installed = False
    try:
        for component in running:
            control(root, component, '--stop', log)
        # Copy after stopping, so the desktop's final layout write is included.
        for name in PRESERVE:
            source, target = root / name, prepared / name
            if source.is_symlink():
                if target.exists():
                    shutil.rmtree(target) if target.is_dir() else target.unlink()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(os.readlink(source))
            elif source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True, symlinks=True)
        root.rename(backup / 'source')
        moved = True
        prepared.rename(root)
        installed = True
        for name, relative in libraries.items():
            atomic_copy(root / relative, libdir / name)
        data = json.loads(old_record) if old_record else {}
        data['root'] = str(root)
        data['libraries'] = {name: hashlib.sha256((libdir / name).read_bytes()).hexdigest() for name in LIBRARIES}
        data['last_update_backup'] = str(backup)
        temporary = backup / 'new-install-record.json'
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        atomic_copy(temporary, record)
        for component in running:
            control(root, component, '--start', log)
            if not pids(component):
                raise RuntimeError(_tr('更新后组件未能启动：%s') % component)
        return backup
    except BaseException:
        # Roll back even on Ctrl+C during the short replacement phase.
        failures = []
        if installed:
            for component in running:
                try:
                    control(root, component, '--stop', log)
                except Exception as error:
                    failures.append(str(error))
        try:
            if installed:
                root.rename(backup / 'failed-version')
            if moved:
                (backup / 'source').rename(root)
        except OSError as error:
            raise RuntimeError(_tr('更新失败，恢复过程中也遇到问题。备份：%s') % backup + '\n' + str(error)) from error
        for name in LIBRARIES:
            try:
                if existed[name]:
                    atomic_copy(backup / 'libraries' / name, libdir / name)
                else:
                    (libdir / name).unlink(missing_ok=True)
            except Exception as error:
                failures.append(str(error))
        try:
            if old_record is not None:
                atomic_copy(backup / 'install-record.json', record)
            else:
                record.unlink(missing_ok=True)
        except Exception as error:
            failures.append(str(error))
        for component in running:
            try:
                control(root, component, '--start', log)
            except Exception as error:
                failures.append(str(error))
        if failures:
            raise RuntimeError(_tr('更新失败，恢复过程中也遇到问题。备份：%s') % backup + '\n' + '\n'.join(failures))
        raise


def installed_version(root):
    data = json.loads((root / 'build-info.json').read_text())
    if not isinstance(data, dict):
        raise ValueError(_tr('无法识别安装包版本。'))
    text = data.get('display_version') or f"{data.get('major_version', '')} {data.get('release_label') or data.get('minor_version') or 'Release'}"
    if not isinstance(text, str):
        raise ValueError(_tr('无法识别安装包版本。'))
    return version_key(text)


def install_update(result, progress=print):
    release = result.get('release')
    if not result.get('available') or not isinstance(release, dict):
        raise ValueError(_tr('缺少已确认的更新版本，请重新检查更新。'))
    root = ROOT.resolve()
    record = state_dir() / 'install-record.json'
    info = json.loads(record.read_text()) if record.exists() else {}
    if not isinstance(info, dict):
        raise ValueError(_tr('安装记录无效，请重新安装 MNWS 后重试。'))
    if (root / '.git').exists() or (root / '.git').is_symlink() or Path(info.get('root') or root).resolve() != root:
        raise RuntimeError(_tr('请从已安装的 MNWS 更新；开发检出目录不会被覆盖。'))
    expected = release_version(release)
    with update_lock():
        current = installed_version(root)
        if expected <= current:
            raise RuntimeError(_tr('目标版本不比当前版本新，请重新检查更新。'))
        logfile = state_dir() / ('update-' + time.strftime('%Y%m%d-%H%M%S') + '.log')
        try:
            with logfile.open('ab') as log, tempfile.TemporaryDirectory(prefix='.' + root.name + '-update-', dir=root.parent) as temporary:
                directory = Path(temporary)
                progress(_tr('正在下载更新…'))
                url, digest, prebuilt = package(release)
                archive = directory / 'update.zip'
                download(url, archive, result.get('use_proxy', False), digest)
                prepared = extract(archive, directory / 'source')
                if installed_version(prepared) != expected:
                    raise ValueError(_tr('安装包版本与所选更新不一致。'))
                progress(_tr('正在准备更新组件，请稍候…'))
                libraries = prepare_libraries(prepared, prebuilt, log)
                if installed_version(root) != current:
                    raise RuntimeError(_tr('安装版本在准备期间发生变化，请重新检查更新。'))
                progress(_tr('正在安装更新，配置将保留…'))
                backup = replace_installation(root, prepared, libraries, log)
            return _tr('更新已安装。备份：%s') % backup
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
            raise RuntimeError(_tr('更新未完成：%s\n日志：%s') % (error, logfile)) from error

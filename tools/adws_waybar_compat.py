"""Verify Waybar modules and offer an isolated, pinned upstream build."""
import datetime
import hashlib
import json
import mmap
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
import uuid
from adws_i18n import tr as _tr

VERSION = '0.14.0'
COMMIT = '41de8964f1e3278edf07902ad68ca5e01e7abeeb'
REPOSITORY = 'https://github.com/Alexays/Waybar.git'
REQUIRED = ('cffi/', 'niri/workspaces')


def managed_prefix():
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')/'adws-dependencies/waybar'


def compatibility_errors(executable):
    if not executable:
        return [_tr('缺少运行依赖：') + 'waybar']
    try:
        with Path(executable).open('rb') as binary:
            with mmap.mmap(binary.fileno(), 0, access=mmap.ACCESS_READ) as data:
                if data[:4] != b'\x7fELF':
                    return [_tr('无法验证 Waybar 模块支持，请使用原生 Waybar 可执行文件。')]
                missing = [name for name in REQUIRED if data.find(b'\0'+name.encode()+b'\0') < 0]
    except (OSError, ValueError) as error:
        return [_tr('无法验证 Waybar 模块支持：') + str(error)]
    if missing:
        return [_tr('当前 Waybar 缺少 ADWS 必需模块：') + ', '.join(missing)
                + _tr('。请运行 adws check --repair-waybar，或重新运行 install.sh。')]
    return []


def resolve_waybar():
    """Prefer a compatible system package; otherwise use ADWS's private build."""
    system = shutil.which('waybar')
    if system and not compatibility_errors(system):
        return system
    candidate = managed_prefix()/'bin/waybar'
    if os.access(candidate, os.X_OK) and not compatibility_errors(candidate):
        return str(candidate)
    return None


def validate_build(binary):
    errors = compatibility_errors(binary)
    if errors:
        raise RuntimeError('\n'.join(errors))
    result = subprocess.run([str(binary), '--version'], capture_output=True, text=True, timeout=15)
    if result.returncode or '0.14.0' not in result.stdout:
        raise RuntimeError(_tr('构建的 Waybar 无法运行：%s') % (result.stdout+result.stderr).strip())


def run(command, cwd, log, timeout=1200):
    import shlex
    log.write('\n$ '+shlex.join(map(str,command))+'\n');log.flush()
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                   stdin=subprocess.DEVNULL, timeout=timeout, check=True)


def clone_source(directory, log, use_proxy):
    from adws_update import github_urls
    source = directory/'source'
    errors = []
    for url in github_urls(REPOSITORY, use_proxy):
        if source.exists():shutil.rmtree(source)
        try:
            run(['git', '-c', 'http.sslVerify=true', 'clone', '--depth', '1', '--branch', VERSION,
                 '--single-branch', url, str(source)], directory, log, timeout=180)
            revision = subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
            if revision != COMMIT:
                raise ValueError(_tr('Waybar 源码版本校验失败。'))
            return source
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(str(error))
    raise RuntimeError(_tr('下载 Waybar 源码失败：%s') % '\n'.join(errors))


def cache_layer_shell(source, use_proxy):
    """Noble ships GTK Layer Shell 0.8; upstream requires 0.9. Keep wrap hash checks."""
    from adws_update import github_urls
    import configparser
    wrap = configparser.ConfigParser()
    wrap.read(source/'subprojects/gtk-layer-shell.wrap')
    entry = wrap['wrap-file']
    target = source/'subprojects/packagecache'/entry['source_filename']
    target.parent.mkdir(parents=True,exist_ok=True)
    errors=[]
    for url in github_urls(entry['source_url'],use_proxy):
        try:
            digest=hashlib.sha256();count=0
            request=urllib.request.Request(url,headers={'User-Agent':'ADWS-waybar-builder'})
            with urllib.request.urlopen(request,timeout=30) as response,target.open('wb') as output:
                while chunk:=response.read(64*1024):
                    count+=len(chunk)
                    if count>32*1024*1024:raise ValueError('Dependency download exceeds size limit')
                    digest.update(chunk);output.write(chunk)
            if digest.hexdigest()!=entry['source_hash']:raise ValueError('Dependency SHA-256 mismatch')
            return
        except (OSError,ValueError) as error:
            target.unlink(missing_ok=True);errors.append(str(error))
    raise RuntimeError(_tr('下载构建依赖失败：%s') % '\n'.join(errors))


def activate(staged, destination):
    """Atomically install a validated private build; retain/restore the previous build."""
    if destination.is_symlink():raise RuntimeError(_tr('Waybar 专用安装目录不能是软链接。'))
    validate_build(staged/'bin/waybar')
    backup=None
    if destination.exists():
        backup=destination.with_name('waybar-backup-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
        destination.rename(backup)
    try:
        staged.rename(destination)
        validate_build(destination/'bin/waybar')
    except BaseException:
        if destination.exists():shutil.rmtree(destination)
        if backup:backup.rename(destination)
        raise
    return destination/'bin/waybar'


def _build_waybar(progress=print):
    from adws_update import mainland_china
    prefix=managed_prefix();prefix.parent.mkdir(parents=True,exist_ok=True)
    logs=Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/'adws-waybar'
    logs.mkdir(parents=True,exist_ok=True)
    logfile=logs/('build-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.log')
    try:
        with logfile.open('w') as log,tempfile.TemporaryDirectory(prefix='.waybar-build-',dir=prefix.parent) as temporary:
            directory=Path(temporary)
            progress(_tr('正在下载官方 Waybar %s 源码…') % VERSION)
            use_proxy=mainland_china()
            source=clone_source(directory,log,use_proxy)
            # Cache the upstream checksum-pinned fallback for Ubuntu's older library.
            result=subprocess.run(['pkg-config','--atleast-version=0.9.0','gtk-layer-shell-0'],capture_output=True)
            if result.returncode:cache_layer_shell(source,use_proxy)
            build=directory/'build';stage=directory/'stage'
            progress(_tr('正在配置 Waybar 构建，日志：%s') % logfile)
            run(['meson','setup',str(build),str(source),'--prefix='+str(prefix),'--bindir=bin','--libdir=lib',
                 '--sysconfdir=etc','--buildtype=release','--default-library=static','-Dniri=true',
                 '-Dtests=disabled','-Dman-pages=disabled','-Dsystemd=disabled','-Dcava=disabled'],directory,log,timeout=300)
            progress(_tr('正在编译 Waybar，请稍候；日志：%s') % logfile)
            run(['meson','compile','-C',str(build),'-j','2'],directory,log)
            validate_build(build/'waybar')
            run(['meson','install','-C',str(build),'--destdir',str(stage),'--no-rebuild'],directory,log,timeout=180)
            installed=stage/str(prefix).lstrip('/')
            (installed/'adws-build.json').write_text(json.dumps({'version':VERSION,'commit':COMMIT,'log':str(logfile)},indent=2)+'\n')
            progress(_tr('正在验证并安装 ADWS 专用 Waybar…'))
            binary=activate(installed,prefix)
            progress(_tr('兼容的 Waybar 已安装：%s') % binary)
            return str(binary)
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        raise RuntimeError(_tr('Waybar 构建未完成：%s\n日志：%s') % (error,logfile)) from error


def build_waybar(progress=print):
    import fcntl
    prefix=managed_prefix();prefix.parent.mkdir(parents=True,exist_ok=True)
    with (prefix.parent/'waybar-build.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(_tr('另一个 Waybar 构建正在进行，请稍后重试。')) from error
        return _build_waybar(progress)


def ensure_waybar(confirm, install_packages, progress=print):
    binary=resolve_waybar()
    if binary:return binary
    progress('\n'.join(compatibility_errors(shutil.which('waybar'))))
    if confirm(_tr('是否尝试通过系统软件源安装或更新 Waybar？')):
        try:install_packages(['waybar'])
        except (OSError,subprocess.SubprocessError) as error:
            progress(_tr('软件源安装未完成：%s') % error)
        binary=resolve_waybar()
        if binary:return binary
        progress(_tr('软件源未提供兼容的 Waybar，可以改为构建官方版本。'))
    if not confirm(_tr('是否构建官方 Waybar 0.14.0？将补齐构建依赖并安装到用户专用目录，不替换系统 Waybar。')):
        raise RuntimeError(_tr('已取消 Waybar 修复；现有配置保持不变。'))
    install_packages(groups=['waybar-build'])
    return build_waybar(progress)


def main():
    from adws_setup import confirm,install_packages
    try:
        print(ensure_waybar(confirm,install_packages))
        return 0
    except KeyboardInterrupt:return 130
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print(str(error));return 1


if __name__=='__main__':raise SystemExit(main())

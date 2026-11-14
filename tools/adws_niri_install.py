"""Optional Niri bootstrap. Never start a compositor or replace a display manager."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request
import uuid

from adws_i18n import tr
from adws_launcher import ask
from adws_install_transaction import checked_run

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = 'https://github.com/niri-wm/niri.git'
TAG = 'v26.04'
COMMIT = '8ed0da44d974c32c6877d2f4630c314da0717ecb'
MIN_PACKAGE = (26, 4)
BUILD_PACKAGES = {
    'apt-get': ['git','build-essential','clang','pkg-config','libudev-dev','libgbm-dev','libxkbcommon-dev','libegl1-mesa-dev','libwayland-dev','libinput-dev','libdbus-1-dev','libsystemd-dev','libseat-dev','libpipewire-0.3-dev','libpango1.0-dev','libdisplay-info-dev'],
    'pacman': ['git','base-devel','clang','pkgconf','systemd','mesa','libxkbcommon','wayland','libinput','dbus','seatd','pipewire','pango','libdisplay-info'],
    'dnf': ['git','gcc','gcc-c++','clang','pkgconf-pkg-config','systemd-devel','mesa-libgbm-devel','libxkbcommon-devel','mesa-libEGL-devel','wayland-devel','libinput-devel','dbus-devel','libseat-devel','pipewire-devel','pango-devel','cairo-gobject-devel','libdisplay-info-devel'],
}
SESSION_PACKAGES = ['xdg-desktop-portal','xdg-desktop-portal-gnome','xdg-desktop-portal-gtk','gnome-keyring','xwayland-satellite']


def package_manager():
    return next((name for name in BUILD_PACKAGES if shutil.which(name)), None)


def query(command):
    return subprocess.run(command, capture_output=True, text=True, timeout=45,
                          env={**os.environ,'LC_ALL':'C','LANGUAGE':''})


def package_candidates(manager,names):
    """Query configured repositories only. Never enable a PPA/COPR or refresh globally."""
    if not names:return {}
    if manager=='apt-get':
        result=query(['apt-cache','policy',*names]);found={};name=None
        if result.returncode:raise RuntimeError(tr('无法读取软件源信息，请先检查系统软件源后重试。'))
        for line in result.stdout.splitlines():
            if line and not line[0].isspace() and line.endswith(':'):name=line[:-1].split(':')[0]
            match=re.match(r'\s*Candidate:\s*(\S+)',line)
            if name in names and match and match[1]!='(none)':found[name]=match[1]
        return found
    if manager=='pacman':
        result=query(['pacman','-Si',*names]);found={};name=None
        for line in result.stdout.splitlines():
            match=re.match(r'Name\s*:\s*(\S+)',line)
            if match:name=match[1]
            match=re.match(r'Version\s*:\s*(\S+)',line)
            if match and name in names:found[name]=match[1]
        if result.returncode and not found and 'was not found' not in result.stderr:
            raise RuntimeError(tr('无法读取软件源信息，请先检查系统软件源后重试。'))
        return found
    if manager=='dnf':
        result=query(['dnf','-q','repoquery','--available','--latest-limit','1','--qf','%{name} %{version}',*names])
        if result.returncode:raise RuntimeError(tr('无法读取软件源信息，请先检查系统软件源后重试。'))
        return {parts[0]:parts[1] for line in result.stdout.splitlines() if len(parts:=line.split())==2 and parts[0] in names}
    raise RuntimeError(tr('此系统暂不支持自动安装 Niri，请手动安装后重试。'))


def installed_packages(manager,names):
    if not names:
        return set()
    if manager=='apt-get':
        result=query(['dpkg-query','-W','-f=${binary:Package} ${db:Status-Status}\n',*names])
        return {parts[0].split(':')[0] for line in result.stdout.splitlines() if len(parts:=line.split())==2 and parts[1]=='installed'}
    if manager=='pacman':
        # Deptest resolves virtual and versioned Provides through libalpm.
        result = query(['pacman', '-T', '--', *names])
        missing = set(result.stdout.splitlines())
        if (result.returncode not in (0, 127) or not missing.issubset(names)
                or (result.returncode == 127) != bool(missing)):
            raise RuntimeError('无法核对 pacman 已安装依赖：' + result.stderr.strip())
        return set(names) - missing
    result=query(['rpm','-q','--qf','%{NAME}\n',*names])
    return set(result.stdout.splitlines()).intersection(names)


def suitable_package(version):
    match=re.match(r'(?:\d+:)?(\d+)\.(\d+)',version or '')
    return bool(match and tuple(map(int,match.groups()))>=MIN_PACKAGE)


def validate(binary,path):
    result=query([str(binary),'validate','-c',str(path)])
    if result.returncode:
        raise RuntimeError(tr('Niri 配置校验失败：%s') % (result.stderr.strip() or result.stdout.strip()))


def check_binary(binary):
    result=query([str(binary),'--version'])
    if result.returncode:raise RuntimeError(tr('已找到 Niri，但无法运行：%s') % binary)
    # Probe required configuration syntax without opening a display or touching user files.
    validate(binary,ROOT/'config/adws-windows.kdl')
    return result.stdout.strip() or str(binary)


def privileged(command):
    if os.geteuid()!=0:
        sudo=shutil.which('sudo')
        if not sudo:raise RuntimeError(tr('缺少 sudo，请由管理员安装系统组件后重试。'))
        command=[sudo,*command]
    checked_run(command,check=True)


def prepare_rust(env,confirm):
    """Use a current compiler without replacing the distro's Rust installation."""
    cargo_home=Path(env.get('CARGO_HOME') or Path.home()/'.cargo')
    env={**env,'PATH':str(cargo_home/'bin')+os.pathsep+env.get('PATH',os.defpath)}
    def supported():
        for program in ('rustc','cargo'):
            executable=shutil.which(program,path=env['PATH'])
            if not executable:return False
            result=subprocess.run([executable,'--version'],capture_output=True,text=True,timeout=30,env=env)
            match=re.search(r'\b(?:rustc|cargo) (\d+)\.(\d+)\.(\d+)',result.stdout)
            if result.returncode or not match or tuple(map(int,match.groups()))<(1,87,0):return False
        return True
    if supported():return env
    if env.get('ADWS_BUILD_MIRROR')=='1':
        env.setdefault('RUSTUP_DIST_SERVER','https://rsproxy.cn')
        env.setdefault('RUSTUP_UPDATE_ROOT','https://rsproxy.cn/rustup')
    if not confirm(tr('源码构建需要新版本 Rust。是否通过官方 rustup 安装／更新 stable 工具链？不会移除系统 Rust。')):
        raise RuntimeError(tr('已取消 Niri 源码构建。'))
    rustup=shutil.which('rustup',path=env['PATH'])
    if rustup:
        checked_run([rustup,'toolchain','install','stable','--profile','minimal'],check=True,env=env)
    else:
        with tempfile.TemporaryDirectory(prefix='adws-rustup-') as folder:
            script=Path(folder)/'rustup-init.sh'
            with urllib.request.urlopen('https://sh.rustup.rs',timeout=30) as response:
                content=response.read(1024*1024+1)
            if len(content)>1024*1024:raise RuntimeError('Rustup installer exceeds size limit')
            script.write_bytes(content)
            checked_run(['sh',str(script),'-y','--no-modify-path','--profile','minimal','--default-toolchain','stable'],check=True,
                           env={**env,'RUSTUP_INIT_SKIP_PATH_CHECK':'yes'})
    env['RUSTUP_TOOLCHAIN']='stable'
    if not supported():raise RuntimeError(tr('Rust 工具链安装后仍无法使用，请检查终端输出。'))
    return env


def source_files(tree,binary,session_directory=Path('/usr/local/share/wayland-sessions')):
    """Official manual installation layout, with absolute executable paths."""
    resources=tree/'resources'
    service=(resources/'niri.service').read_text()
    service=re.sub(r'^ExecStart=.*$', 'ExecStart=/usr/local/bin/niri --session',service,flags=re.M)
    desktop=(resources/'niri.desktop').read_text()
    desktop=re.sub(r'^Exec=.*$', 'Exec=/usr/local/bin/niri-session',desktop,flags=re.M)
    desktop+='TryExec=/usr/local/bin/niri\n'
    portal=(resources/'niri-portals.conf').read_text()+'org.freedesktop.impl.portal.FileChooser=gtk;\n'
    return {
        Path('/usr/local/bin/niri'):(binary.read_bytes(),0o755),
        Path('/usr/local/bin/niri-session'):((resources/'niri-session').read_bytes(),0o755),
        Path('/etc/systemd/user/niri.service'):(service.encode(),0o644),
        Path('/etc/systemd/user/niri-shutdown.target'):((resources/'niri-shutdown.target').read_bytes(),0o644),
        session_directory/'niri.desktop':(desktop.encode(),0o644),
        Path('/usr/local/share/xdg-desktop-portal/niri-portals.conf'):(portal.encode(),0o644),
        Path('/usr/local/share/licenses/niri/LICENSE'):((tree/'LICENSE').read_bytes(),0o644),
    }


def install_source_files(files,confirm):
    # All destinations must be absent before requesting privilege, including links.
    conflicts=[str(path) for path in files if path.exists() or path.is_symlink()]
    if conflicts:raise RuntimeError(tr('以下 Niri 文件已存在，保留原文件并停止安装：%s') % ', '.join(conflicts))
    print(tr('将安装 Niri 及独立登录会话：')+'\n'+'\n'.join(map(str,files)))
    if not confirm(tr('是否安装以上文件？保留当前登录管理器，不切换当前会话。')):
        raise RuntimeError(tr('已取消 Niri 安装。'))
    installed=[]
    with tempfile.TemporaryDirectory(prefix='adws-niri-stage-') as folder:
        try:
            for index,(target,(content,mode)) in enumerate(files.items()):
                source=Path(folder)/str(index);source.write_bytes(content)
                if target.exists() or target.is_symlink():raise RuntimeError(tr('目标文件在安装期间发生变化：%s') % target)
                temporary=target.with_name('.'+target.name+'.adws-'+uuid.uuid4().hex)
                try:
                    privileged(['install','-D','-m',f'{mode:o}',str(source),str(temporary)])
                    # Atomic publication without overwriting a concurrent install.
                    privileged(['ln','--',str(temporary),str(target)])
                    installed.append(target)
                finally:
                    if temporary.exists():privileged(['rm','--',str(temporary)])
        except BaseException:
            # Remove only successfully-created files whose bytes are still ours.
            for target in reversed(installed):
                try:
                    if not target.is_symlink() and target.read_bytes()==files[target][0]:privileged(['rm','--',str(target)])
                except (OSError,subprocess.SubprocessError):pass
            raise


def build_source(confirm,install_packages,manager):
    if shutil.which('niri'):raise RuntimeError(tr('已存在 Niri，拒绝用源码构建覆盖现有版本。'))
    install_packages(programs=BUILD_PACKAGES[manager])
    cache=Path(os.environ.get('XDG_CACHE_HOME') or Path.home()/'.cache')/'adws/niri-install'
    cache.mkdir(parents=True,exist_ok=True)
    # Retain source and build artifacts for diagnosis; no mutable user checkout.
    workspace=Path(tempfile.mkdtemp(prefix='build-',dir=cache));tree=workspace/'source'
    print(tr('构建目录：%s') % workspace)
    checked_run(['git','clone','--depth','1','--branch',TAG,'--',UPSTREAM,str(tree)],check=True)
    actual=query(['git','-C',str(tree),'rev-parse','HEAD'])
    if actual.returncode or actual.stdout.strip()!=COMMIT:raise RuntimeError(tr('Niri 源码版本不匹配，已停止构建。'))
    from adws_setup import choose_build_mirror,cargo_build_command
    env=choose_build_mirror(dict(os.environ),tree)
    env=prepare_rust(env,confirm)
    env.update(CARGO_BUILD_JOBS='2',CARGO_TARGET_DIR=str(workspace/'target'))
    checked_run(cargo_build_command(env,tree)+['-p','niri'],cwd=tree,env=env,check=True)
    binary=workspace/'target/release/niri';check_binary(binary)
    if shutil.which('niri'):raise RuntimeError(tr('构建期间检测到已安装 Niri，保留现有版本。'))
    from adws_login_manager import detect
    login=detect()
    if not login['session_dirs']:raise RuntimeError(tr('当前登录管理器未启用 Wayland 会话目录，请检查其配置。'))
    install_source_files(source_files(tree,binary,login['session_dirs'][0]),confirm)
    return '/usr/local/bin/niri'


def session_dependencies(manager,confirm,install_packages):
    targets = SESSION_PACKAGES
    if os.environ.get('ADWS_INSTALL_MANAGED') == '1':
        from adws_setup import approved_plan
        plan = approved_plan()
        if plan:
            targets = [name for name in targets if name in plan['package_candidates']]
    installed=installed_packages(manager,targets)
    missing=[name for name in targets if name not in installed]
    candidates=package_candidates(manager,missing)
    if candidates:install_packages(programs=list(candidates))
    unavailable=[name for name in missing if name not in candidates]
    if unavailable:print(tr('软件源中暂不可用的可选组件：%s') % ', '.join(unavailable))
    if 'xwayland-satellite' in unavailable:print(tr('X11 应用兼容尚未就绪；安装 xwayland-satellite 后可用。'))
    from adws_launcher import terminal_argv
    try:terminal=terminal_argv()
    except RuntimeError:
        choices=package_candidates(manager,['foot','alacritty','xterm'])
        selected=next((name for name in ('foot','alacritty','xterm') if name in choices),None)
        if not selected:raise RuntimeError(tr('未找到可安装的终端，请先安装终端后重试。'))
        install_packages(programs=[selected]);terminal=terminal_argv()
    # Polkit UI is supplied by ADWS; its registration already detects an existing agent.
    # No additional session-wide authentication daemon is spawned here.
    return terminal


def initial_config(binary,terminal,confirm):
    from adws_windows import config_path
    path=config_path()
    if path.exists() or path.is_symlink():
        print(tr('保留现有 Niri 配置：%s') % path)
        validate(binary,path)
        return
    if not confirm(tr('是否创建 Niri 基础配置？包含终端、开始菜单和常用窗口快捷键。')):
        raise RuntimeError(tr('未创建基础配置；请准备 Niri 配置后重新安装 ADWS。'))
    def command(argv):return ' '.join(json.dumps(str(arg),ensure_ascii=False) for arg in argv)
    text='''// Niri configuration created by ADWS; this file survives ADWS removal.
input {
    keyboard {
        xkb {}
    }
}
layout { gaps 8; }
binds {
    Mod+Return { spawn TERMINAL; }
    Mod+D { spawn MENU; }
    Mod+Q { close-window; }
    Mod+Left { focus-column-left; }
    Mod+Right { focus-column-right; }
    Mod+Up { focus-window-up; }
    Mod+Down { focus-window-down; }
    Mod+Ctrl+Left { move-column-left; }
    Mod+Ctrl+Right { move-column-right; }
    Mod+Shift+Up { focus-workspace-up; }
    Mod+Shift+Down { focus-workspace-down; }
    Mod+F { maximize-column; }
    Mod+Shift+F { fullscreen-window; }
    Mod+V { toggle-window-floating; }
    Mod+Shift+E { quit; }
    Mod+Shift+Slash { show-hotkey-overlay; }
    Print { screenshot; }
}
'''.replace('TERMINAL',command(terminal)).replace('MENU',command(['bash',str(ROOT/'adws'),'start-menu']))
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',suffix='.kdl',prefix='.adws-niri-',dir=path.parent) as temporary:
        temporary.write(text);temporary.flush();validate(binary,temporary.name)
        # Exclusive creation preserves even a config created while the dialog was open.
        with path.open('x',encoding='utf-8') as stream:stream.write(text)
    print(tr('已创建 Niri 基础配置：%s') % path)


def login_report():
    from adws_login_manager import detect
    login=detect()
    if login['id']:
        print(tr('检测到登录管理器：%s；保留当前配置。') % login['name'])
        if login['active'] and login['configured'] and login['active']!=login['configured']:
            print(tr('当前运行与下次启用的登录管理器不同，请在退出前确认服务选择。'))
    else:print(tr('未检测到已启用的登录管理器，将保留现状；可通过 TTY 的 niri-session 启动。'))
    if login['warning']=='wayland-disabled':print(tr('当前 GDM 配置禁用了 Wayland，Niri 可能不会显示；请检查 GDM 配置，安装器不会擅自修改。'))
    return login


def session_report(binary,confirm=None):
    from adws_login_manager import detect,session_entries
    login=detect();entries=session_entries(login)
    if not entries and confirm and login['id'] and login['session_dirs']:
        # Package sessions normally live in a standard system directory. Copy
        # their upstream entry only when the selected manager uses another path.
        standard={'session_dirs':[Path('/usr/share/wayland-sessions'),Path('/usr/local/share/wayland-sessions')]}
        candidates=session_entries(standard)
        if candidates:
            target=login['session_dirs'][0]/'niri-adws.desktop'
            install_source_files({target:(candidates[0].read_bytes(),0o644)},confirm)
            entries=session_entries(login)
    if entries:print(tr('Niri 登录入口：%s') % entries[0])
    else:print(tr('当前登录管理器的会话目录中未找到 Niri 入口，请检查会话文件。'))
    # No display-manager restarts, global environment changes or GPU driver edits.
    if login['id']:print(tr('安装完成后可自行退出，在 %s 中选择 Niri；TTY 可运行 niri-session。') % login['name'])
    else:print(tr('未切换桌面；TTY 可运行 niri-session。'))


def ensure_niri(confirm,install_packages):
    managed = os.environ.get('ADWS_INSTALL_MANAGED') == '1'
    login_report()
    binary=shutil.which('niri')
    if binary:
        print(tr('沿用已安装的 Niri：%s') % check_binary(binary))
        from adws_windows import config_path
        path=config_path()
        if not managed and not (path.exists() or path.is_symlink()):
            from adws_launcher import terminal_argv
            try:terminal=terminal_argv()
            except RuntimeError:
                manager=package_manager()
                if not manager:raise RuntimeError(tr('请先安装终端并配置 Niri 后重试。'))
                terminal=session_dependencies(manager,confirm,install_packages)
            initial_config(binary,terminal,confirm)
        return binary
    if managed and os.environ.get('ADWS_NIRI_METHOD') not in ('repository', 'source'):
        raise RuntimeError(tr('安装计划未指定 Niri 安装方式，请重新预览并确认安装计划。'))
    if not managed and not confirm(tr('未检测到 Niri。是否安装 Niri 及其独立桌面会话？')):
        raise RuntimeError(tr('已取消 Niri 安装；安装 Niri 后可重新运行 install.sh。'))
    manager=package_manager()
    if not manager:raise RuntimeError(tr('此系统暂不支持自动安装 Niri，请手动安装后重试。'))
    candidates=package_candidates(manager,['niri']);version=candidates.get('niri')
    repository=suitable_package(version)
    if repository:print(tr('系统源可用 Niri：%s') % version)
    else:print(tr('系统源未提供已验证版本的 Niri，将提供官方固定版本源码构建。'))
    if managed and os.environ['ADWS_NIRI_METHOD'] == 'repository' and not repository:
        raise RuntimeError(tr('已确认的系统源 Niri 版本不再可用，未改用源码构建；请重新生成安装计划。'))
    while True:
        prompt=tr('选择 Niri 安装方式：1 系统软件源，2 官方源码构建，0 取消。（默认 1）') if repository else tr('选择 Niri 安装方式：2 官方源码构建，0 取消。（默认 0）')
        choice = ('1' if os.environ['ADWS_NIRI_METHOD'] == 'repository' else '2') if managed else (ask(prompt).strip() or ('1' if repository else '0'))
        if choice=='0':raise RuntimeError(tr('已取消 Niri 安装。'))
        if choice=='1' and repository:
            install_packages(programs=['niri']);binary=shutil.which('niri')
            if not binary:raise RuntimeError(tr('软件包安装后未找到 niri，请检查安装输出。'))
            break
        if choice=='2':binary=build_source(confirm,install_packages,manager);break
        print(tr('请输入列出的选项。'))
    check_binary(binary)
    terminal=session_dependencies(manager,confirm,install_packages)
    if not managed:
        initial_config(binary,terminal,confirm)
    # Managed installation creates a complete validated configuration after all
    # selected applications are installed; avoid a rules-only/minimal config here.
    # Subsequent helpers inherit the standard source-install binary location.
    session_report(binary,confirm)
    return binary

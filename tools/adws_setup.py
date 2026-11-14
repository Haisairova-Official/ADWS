"""Interactive dependency repair and component build for installation."""
from adws_i18n import tr as _tr
import os
import re
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
from adws_cargo import build_environment, cargo_build_command, cargo_source_configuration, choose_build_mirror as cargo_mirror
from adws_launcher import ask
from adws_install_transaction import checked_run
from adws_health import dependency_errors, check
from adws_waybar_compat import ensure_waybar, resolve_waybar

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = {
 'apt-get': {'python': ['python3-gi', 'python3-cairo', 'python3-pil', 'gir1.2-gtk-3.0', 'gir1.2-gtklayershell-0.1', 'gir1.2-polkit-1.0', 'policykit-1'], 'build': ['cargo', 'rustc', 'build-essential', 'pkg-config', 'libgtk-3-dev', 'libgtk-layer-shell-dev', 'libjson-glib-dev']},
 'pacman': {'python': ['python-gobject', 'python-cairo', 'python-pillow', 'gtk3', 'gtk-layer-shell', 'polkit'], 'build': ['rust', 'base-devel', 'pkgconf', 'gtk3', 'gtk-layer-shell', 'json-glib']},
 'dnf': {'python': ['python3-gobject', 'python3-cairo', 'python3-pillow', 'gtk3', 'gtk-layer-shell', 'polkit'], 'build': ['cargo', 'rust', 'gcc', 'make', 'pkgconf-pkg-config', 'gtk3-devel', 'gtk-layer-shell-devel', 'json-glib-devel']},
}

# Runtime functionality is required even when native binaries are prebuilt.
from adws_install_features import legacy_runtime_packages
for manager, groups in legacy_runtime_packages().items():
    PACKAGES[manager].update(groups)

PACKAGES['apt-get']['waybar-build'] = ['git', 'build-essential', 'meson', 'ninja-build', 'cmake', 'pkg-config',
 'libgtkmm-3.0-dev', 'libjsoncpp-dev', 'libsigc++-2.0-dev', 'libfmt-dev', 'libspdlog-dev',
 'libwayland-dev', 'wayland-protocols', 'libgtk-layer-shell-dev', 'libxkbcommon-dev', 'libxkbregistry-dev',
 'libhowardhinnant-date-dev', 'libdbusmenu-gtk3-dev', 'libpulse-dev', 'libnl-3-dev', 'libnl-genl-3-dev',
 'libudev-dev', 'libevdev-dev']
PACKAGES['pacman']['waybar-build'] = ['git', 'base-devel', 'meson', 'ninja', 'cmake', 'pkgconf', 'gtkmm3',
 'jsoncpp', 'libsigc++', 'fmt', 'spdlog', 'wayland', 'wayland-protocols', 'gtk-layer-shell', 'libxkbcommon',
 'libdbusmenu-gtk3', 'libpulse', 'libnl', 'systemd', 'libevdev']
PACKAGES['dnf']['waybar-build'] = ['git', 'gcc-c++', 'meson', 'ninja-build', 'cmake', 'pkgconf-pkg-config',
 'gtkmm30-devel', 'jsoncpp-devel', 'libsigc++20-devel', 'fmt-devel', 'spdlog-devel', 'wayland-devel',
 'wayland-protocols-devel', 'gtk-layer-shell-devel', 'libxkbcommon-devel', 'libdbusmenu-gtk3-devel',
 'pulseaudio-libs-devel', 'libnl3-devel', 'systemd-devel', 'libevdev-devel']


def approved_plan():
    if not (os.environ.get('ADWS_INSTALL_PLAN') or os.environ.get('ADWS_INSTALL_MANAGED') == '1'):
        return None
    from adws_install_workflow import approved_plan as load
    plan = load()
    if plan is None:
        raise RuntimeError('NEW_PLAN_REQUIRED: missing approved installation plan')
    return plan


def confirm(prompt):
    plan = approved_plan()
    if plan is not None:
        # Exact prompts only. A newly added decision must first become part of
        # the plan the user reviewed; it must not silently inherit a blanket yes.
        choices = {
            _tr('是否快速安装预构建组件？无需 Rust/Cargo 或 C 编译器。'): (plan.get('prebuilt', True) is True or isinstance(plan.get('prebuilt'), dict) and plan['prebuilt'].get('status') == 'verified'),
            _tr('是否现在构建并安装这些组件？首次构建可能需要下载依赖。'): plan.get('build_fallback', False),
            _tr('是否构建官方 Waybar 0.14.0？将补齐构建依赖并安装到用户专用目录，不替换系统 Waybar。'): plan.get('build_fallback', False),
            _tr('是否尝试通过系统软件源安装或更新 Waybar？'): 'waybar' in plan.get('package_candidates', []),
            _tr('未检测到 Nerd Fonts。是否安装官方符号字体，避免任务栏图标显示为方框？（约 3 MB）'): plan.get('fonts', True),
            _tr('是否安装以上文件？保留当前登录管理器，不切换当前会话。'): plan.get('niri_method') in ('repository', 'source'),
            _tr('源码构建需要新版本 Rust。是否通过官方 rustup 安装／更新 stable 工具链？不会移除系统 Rust。'): plan.get('niri_method') == 'source',
            '是否为本次构建使用国内 Rust 镜像源（RsProxy）？': plan.get('mirror') == 'rsproxy',
        }
        if prompt not in choices:
            raise RuntimeError('NEW_PLAN_REQUIRED: ' + prompt)
        return choices[prompt] is True
    while True:
        answer = ask(prompt + '（Y/n/Ctrl+C）').lower()
        if answer in ('', 'y'):
            return True
        if answer == 'n':
            return False
        print(_tr('请输入 y 或 n。'))


def install_packages(programs=(), groups=(), *, system_upgrade=False):
    plan = approved_plan()
    manager = (plan.get('features', {}).get('manager') or plan.get('manager')) if plan else None
    if manager and (manager not in PACKAGES or not shutil.which(manager)):
        raise RuntimeError('NEW_PLAN_REQUIRED: package manager changed: ' + str(manager))
    manager = manager or next((name for name in PACKAGES if shutil.which(name)), None)
    if not manager:
        raise RuntimeError(_tr('暂不支持自动补齐此系统的依赖，请按 README 手动安装后重新运行 install.sh。'))
    if system_upgrade and not (manager == 'pacman' and plan is not None and plan.get('system_upgrade') is True):
        raise RuntimeError('NEW_PLAN_REQUIRED: full system upgrade was not approved for this Arch installation')
    packages = list(programs)
    for group in groups:
        packages.extend(PACKAGES[manager][group])
        if group == 'python':
            packages.append({'apt-get': 'python3-yaml', 'pacman': 'python-yaml', 'dnf': 'python3-pyyaml'}[manager])
    packages = list(dict.fromkeys(packages))
    if not packages and not system_upgrade: return
    if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.:@/-]*', name) for name in packages):
        raise ValueError('Invalid package name')
    if plan is not None:
        unexpected = set(packages) - set(plan.get('package_candidates', []))
        if unexpected:
            raise RuntimeError('NEW_PLAN_REQUIRED: unapproved packages: ' + ', '.join(sorted(unexpected)))
        if manager == 'pacman' and plan.get('system_upgrade') and not system_upgrade:
            # The central package step owns the complete reviewed transaction.
            # Build/repair helpers must not refresh and upgrade the system again
            # after configuration deployment has started.
            from adws_niri_install import installed_packages
            missing = set(packages) - installed_packages(manager, packages)
            if missing:
                raise RuntimeError('NEW_PLAN_REQUIRED: dependencies missing after the reviewed system upgrade: ' + ', '.join(sorted(missing)))
            return
    if manager == 'pacman':
        from adws_niri_install import installed_packages
        satisfied = installed_packages(manager, packages)
        packages = [name for name in packages if name not in satisfied]
        if not packages and not system_upgrade:
            return
    if packages:
        print(_tr('准备安装：') + ', '.join(packages))
    elif system_upgrade:
        print('所需依赖均已满足，继续已确认的 Arch 系统升级。')
    if plan is None and not confirm(_tr('是否补齐以上依赖？')):
        raise RuntimeError(_tr('已取消安装；补齐依赖后可重新运行 install.sh。'))
    flags = (['--needed'] if manager == 'pacman' else ['-y']) if plan else []
    if system_upgrade:
        from adws_install_arch_packages import execution_command
        # The package manager presents its freshly resolved transaction for
        # confirmation; a stale preview must not silently approve new upgrades.
        command=execution_command(packages)
    else:
        command = [manager, '-S' if manager == 'pacman' else 'install', *flags, *packages]
    if os.geteuid() != 0:
        if not shutil.which('sudo'):
            raise RuntimeError(_tr('缺少 sudo，请由管理员安装以上软件包后重试。'))
        command.insert(0, 'sudo')
    checked_run(command, check=True)


def atomic_install(source, target, mode=0o644):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.adws-', dir=target.parent)
    os.close(fd)
    try:
        shutil.copyfile(source, temporary)
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)



def choose_build_mirror(env=None, cwd=None):
    return cargo_mirror(env, cwd, confirm)


def prepare():
    print(_tr('欢迎安装 ADWS。我们会检查所需软件和组件，补齐前会先征求你的同意。'))
    from adws_niri_install import ensure_niri
    ensure_niri(confirm, install_packages)
    errors = dependency_errors()
    if errors:
        print('\n'.join(errors))
        missing = [] if shutil.which('systemctl') else ['systemd']
        groups = ['python'] if any('Python/GTK' in error for error in errors) else []
        from adws_runtime_dependencies import missing_dependencies, install_groups
        groups.extend(install_groups(missing_dependencies()))
        if sys.version_info < (3, 11):
            raise RuntimeError(_tr('需要 Python 3.11 或更新版本，请先通过系统的软件管理器升级 Python。'))
        if missing or groups:
            install_packages(missing, groups)
        if not resolve_waybar():
            ensure_waybar(confirm, install_packages)
        errors = dependency_errors()
        if errors:
            raise RuntimeError(_tr('补齐后仍有问题：\n') + '\n'.join(errors) + _tr('\n请检查系统软件源和当前 Python 环境后重试。'))
    from adws_fonts import ensure_fonts, require_text_fonts, ensure_text_fonts
    if approved_plan() is not None:
        # Package decisions belong to the reviewed plan, never add an unseen
        # repair here after configuration deployment has already begun.
        require_text_fonts()
    else:
        manager=next((name for name in PACKAGES if shutil.which(name)),None)
        if manager is None:raise RuntimeError('无法确定文字字体的软件包来源。')
        ensure_text_fonts(install_packages,manager)
    fonts_ready = ensure_fonts(confirm, install_packages)
    if approved_plan() is not None and not fonts_ready:
        raise RuntimeError(_tr('符号字体安装或验证失败；安装尚未完成，请查看前面的下载或依赖错误后重试。'))
    library_dir = Path.home() / '.local/lib/waybar'
    from adws_prebuilt import install as install_prebuilt
    prebuilt = install_prebuilt(ROOT, library_dir, confirm, atomic_install)
    if not prebuilt:
        # File existence does not identify the ABI/source version. Cargo and
        # make reuse their build caches, but every source install checks all libs.
        missing = ['libniri_taskbar.so', 'libwaybar-space.so', 'libadws_panel.so', 'adws-plugin-runner', 'adws-start-menu']
        print(_tr('将构建并更新原生组件：') + ', '.join(missing))
        if not confirm(_tr('是否现在构建并安装这些组件？首次构建可能需要下载依赖。')):
            raise RuntimeError(_tr('已取消安装；也可以按 README 手动构建后重新运行 install.sh。'))
        build_missing = any(not shutil.which(name) for name in ('cargo', 'rustc', 'cc', 'make', 'pkg-config'))
        if not build_missing:
            build_missing = subprocess.run(['pkg-config', '--exists', 'gtk+-3.0', 'gtk-layer-shell-0', 'json-glib-1.0']).returncode != 0
        if build_missing:
            install_packages(groups=['build'])
        build_env = build_environment()
        for component in ('niri-taskbar', 'adws-runtime', 'adws-start-menu'):
            if cargo_source_configuration(build_env, ROOT / 'src' / component):
                build_env = choose_build_mirror(build_env, ROOT / 'src' / component)
                break
        build_env = choose_build_mirror(build_env)
        if 'libniri_taskbar.so' in missing:
            checked_run(['bash', str(ROOT / 'adws'), 'build-taskbar'], check=True, env=build_env)
        checked_run(cargo_build_command(build_env, ROOT / 'src/adws-runtime'),
                       cwd=ROOT / 'src/adws-runtime', check=True,
                       env={key: value for key, value in build_env.items() if key != 'CARGO_TARGET_DIR'})
        atomic_install(ROOT / 'src/adws-runtime/target/release/adws-plugin-runner',
                       ROOT / 'libexec/adws-plugin-runner', mode=0o755)
        checked_run(cargo_build_command(build_env, ROOT / 'src/adws-start-menu'),
                       cwd=ROOT / 'src/adws-start-menu', check=True,
                       env={key: value for key, value in build_env.items() if key != 'CARGO_TARGET_DIR'})
        atomic_install(ROOT / 'src/adws-start-menu/target/release/adws-start-menu',
                       ROOT / 'libexec/adws-start-menu', mode=0o755)
        if 'libadws_panel.so' in missing:
            checked_run(['make', '-C', str(ROOT / 'src/panel-rows')], check=True)
            atomic_install(ROOT / 'src/panel-rows/libadws_panel.so', library_dir / 'libadws_panel.so')
        if 'libwaybar-space.so' in missing:
            flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gtk+-3.0', 'gtk-layer-shell-0', 'wayland-client'], text=True)
            with tempfile.TemporaryDirectory(prefix='adws-build-') as directory:
                output = Path(directory) / 'libwaybar-space.so'
                checked_run(['cc', '-shared', '-fPIC', '-O2', str(ROOT / 'src/niri-desktop-layer/integration/waybar-space.c'), '-o', str(output), *shlex.split(flags), '-lm'], check=True)
                atomic_install(output, library_dir / output.name)
    if check(preinstall=True):
        raise RuntimeError(_tr('仍有配置问题需要处理，请按上面的提示修复后再次运行 install.sh；现有配置不会被强制覆盖。'))
    return 0


def main():
    try:
        if sys.argv[1:] == ['--cargo-build']:
            env = choose_build_mirror(build_environment())
            checked_run(cargo_build_command(env), env=env, check=True)
            return 0
        if sys.argv[1:] == ['--build-path']:
            print(build_environment()['PATH'])
            return 0
        return prepare()
    except (EOFError, KeyboardInterrupt):
        print(_tr('\n已取消。'))
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(''.join([_tr('安装尚未完成：'), f'{error}', _tr('\n解决问题后可重新运行 ./install.sh，已完成的步骤会保留。')]), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

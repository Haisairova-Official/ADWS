"""Interactive dependency repair and component build for installation."""
from adws_i18n import tr as _tr
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
from adws_launcher import ask
from adws_health import dependency_errors, check

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = {
 'apt-get': {'python': ['python3-gi', 'python3-cairo', 'python3-pil', 'gir1.2-gtk-3.0', 'gir1.2-gtklayershell-0.1'], 'build': ['cargo', 'rustc', 'build-essential', 'pkg-config', 'libgtk-3-dev', 'libgtk-layer-shell-dev', 'libjson-glib-dev']},
 'pacman': {'python': ['python-gobject', 'python-cairo', 'python-pillow', 'gtk3', 'gtk-layer-shell'], 'build': ['rust', 'base-devel', 'pkgconf', 'gtk3', 'gtk-layer-shell', 'json-glib']},
 'dnf': {'python': ['python3-gobject', 'python3-cairo', 'python3-pillow', 'gtk3', 'gtk-layer-shell'], 'build': ['cargo', 'rust', 'gcc', 'make', 'pkgconf-pkg-config', 'gtk3-devel', 'gtk-layer-shell-devel', 'json-glib-devel']},
}


def confirm(prompt):
    while True:
        answer = ask(prompt + '（Y/n/Ctrl+C）').lower()
        if answer in ('', 'y'):
            return True
        if answer == 'n':
            return False
        print(_tr('请输入 y 或 n。'))


def install_packages(programs=(), groups=()):
    manager = next((name for name in PACKAGES if shutil.which(name)), None)
    if not manager:
        raise RuntimeError(_tr('暂不支持自动补齐此系统的依赖，请按 README 手动安装后重新运行 install.sh。'))
    packages = list(programs)
    for group in groups:
        packages.extend(PACKAGES[manager][group])
        if group == 'python':
            packages.append({'apt-get': 'python3-yaml', 'pacman': 'python-yaml', 'dnf': 'python3-pyyaml'}[manager])
    packages = list(dict.fromkeys(packages))
    print(_tr('准备安装：') + ', '.join(packages))
    if not confirm(_tr('是否补齐以上依赖？')):
        raise RuntimeError(_tr('已取消安装；补齐依赖后可重新运行 install.sh。'))
    command = [manager, '-S' if manager == 'pacman' else 'install', *packages]
    if os.geteuid() != 0:
        if not shutil.which('sudo'):
            raise RuntimeError(_tr('缺少 sudo，请由管理员安装以上软件包后重试。'))
        command.insert(0, 'sudo')
    subprocess.run(command, check=True)


def atomic_install(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.adws-', dir=target.parent)
    os.close(fd)
    try:
        shutil.copyfile(source, temporary)
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prepare():
    print(_tr('欢迎安装 ADWS。我们会检查所需软件和组件，补齐前会先征求你的同意。'))
    errors = dependency_errors()
    if errors:
        print('\n'.join(errors))
        missing = [name for name in ('waybar', 'niri', 'systemctl', 'thunar') if not shutil.which(name)]
        missing = ['systemd' if name == 'systemctl' else name for name in missing]
        groups = ['python'] if any('Python/GTK' in error for error in errors) else []
        if sys.version_info < (3, 11):
            raise RuntimeError(_tr('需要 Python 3.11 或更新版本，请先通过系统的软件管理器升级 Python。'))
        install_packages(missing, groups)
        errors = dependency_errors()
        if errors:
            raise RuntimeError(_tr('补齐后仍有问题：\n') + '\n'.join(errors) + _tr('\n请检查系统软件源和当前 Python 环境后重试。'))
    library_dir = Path.home() / '.local/lib/waybar'
    from adws_prebuilt import install as install_prebuilt
    install_prebuilt(ROOT, library_dir, confirm, atomic_install)
    missing = [name for name in ('libniri_taskbar.so', 'libwaybar-space.so', 'libadws_panel.so') if not (library_dir / name).is_file()]
    if missing:
        print(_tr('缺少组件：') + ', '.join(missing))
        if not confirm(_tr('是否现在构建并安装这些组件？首次构建可能需要下载依赖。')):
            raise RuntimeError(_tr('已取消安装；也可以按 README 手动构建后重新运行 install.sh。'))
        build_missing = any(not shutil.which(name) for name in ('cargo', 'rustc', 'cc', 'make', 'pkg-config'))
        if not build_missing:
            build_missing = subprocess.run(['pkg-config', '--exists', 'gtk+-3.0', 'gtk-layer-shell-0', 'json-glib-1.0']).returncode != 0
        if build_missing:
            install_packages(groups=['build'])
        if 'libniri_taskbar.so' in missing:
            subprocess.run(['bash', str(ROOT / 'adws'), 'build-taskbar'], check=True)
        if 'libadws_panel.so' in missing:
            subprocess.run(['make', '-C', str(ROOT / 'src/panel-rows')], check=True)
            atomic_install(ROOT / 'src/panel-rows/libadws_panel.so', library_dir / 'libadws_panel.so')
        if 'libwaybar-space.so' in missing:
            flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gtk+-3.0', 'gtk-layer-shell-0'], text=True)
            with tempfile.TemporaryDirectory(prefix='adws-build-') as directory:
                output = Path(directory) / 'libwaybar-space.so'
                subprocess.run(['cc', '-shared', '-fPIC', '-O2', str(ROOT / 'src/niri-desktop-layer/integration/waybar-space.c'), '-o', str(output), *shlex.split(flags)], check=True)
                atomic_install(output, library_dir / output.name)
    if check(preinstall=True):
        raise RuntimeError(_tr('仍有配置问题需要处理，请按上面的提示修复后再次运行 install.sh；现有配置不会被强制覆盖。'))
    return 0


def main():
    try:
        return prepare()
    except (EOFError, KeyboardInterrupt):
        print(_tr('\n已取消。'))
        return 130
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(''.join([_tr('安装尚未完成：'), f'{error}', _tr('\n解决问题后可重新运行 ./install.sh，已完成的步骤会保留。')]), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

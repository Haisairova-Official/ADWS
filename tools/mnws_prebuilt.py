"""Install verified native components shipped in an Arch release archive."""
from mnws_i18n import tr as _tr
import hashlib
import json
from pathlib import Path
import platform

NAMES = ('libniri_taskbar.so', 'libmnws_panel.so', 'libwaybar-space.so')


def install(root, destination, confirm, atomic_install):
    folder = root / 'prebuilt'
    manifest = folder / 'manifest.json'
    if not manifest.is_file():
        return False
    system = platform.freedesktop_os_release()
    if system.get('ID') != 'arch' or platform.machine() != 'x86_64':
        raise RuntimeError(_tr('此预构建包仅支持 Arch Linux x86_64，请使用源码版或匹配系统的安装包。'))
    hashes = json.loads(manifest.read_text())['sha256']
    for name in NAMES:
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != hashes.get(name):
            raise RuntimeError(''.join([_tr('预构建文件校验失败：'), f'{name}', _tr('，请重新下载安装包。')]))
    if not confirm(_tr('是否快速安装预构建组件？无需 Rust/Cargo 或 C 编译器。')):
        raise RuntimeError(_tr('已取消预构建组件安装。'))
    for name in NAMES:
        atomic_install(folder / name, destination / name)
    print(_tr('预构建组件安装完成，已跳过源码编译。'))
    return True

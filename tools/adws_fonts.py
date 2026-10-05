"""Optional user-local Nerd Fonts symbols, pinned to an official release."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from adws_i18n import tr as _tr

VERSION = '3.5.1'
URL = 'https://github.com/ryanoasis/nerd-fonts/releases/download/v3.5.1/NerdFontsSymbolsOnly.zip'
SHA256 = 'fdca3682534f6f65e1ccb2345b0362ccf67d9b8eca7c8025330946e93e2473bc'
FONTS = ('SymbolsNerdFont-Regular.ttf', 'SymbolsNerdFontMono-Regular.ttf')
LIMIT = 8 * 1024 * 1024


def available():
    if not shutil.which('fc-list'):
        return False
    result = subprocess.run(['fc-list', '--format=%{family}\\n'], capture_output=True, text=True, timeout=15)
    return result.returncode == 0 and any('nerd font' in family.lower() or 'nerdfont' in family.lower()
                                        for family in result.stdout.splitlines())


def download(target):
    from adws_update import github_urls, mainland_china
    errors = []
    for url in github_urls(URL, mainland_china()):
        try:
            digest = hashlib.sha256(); size = 0
            request = urllib.request.Request(url, headers={'User-Agent': 'ADWS-font-installer'})
            with urllib.request.urlopen(request, timeout=30) as response, target.open('wb') as output:
                while chunk := response.read(64 * 1024):
                    size += len(chunk)
                    if size > LIMIT:
                        raise ValueError(_tr('字体下载超过大小限制。'))
                    digest.update(chunk); output.write(chunk)
            if digest.hexdigest() != SHA256:
                raise ValueError(_tr('字体包 SHA-256 校验失败。'))
            return
        except (OSError, ValueError) as error:
            target.unlink(missing_ok=True); errors.append(str(error))
    raise RuntimeError(_tr('字体下载失败：%s') % '\n'.join(errors))


def install():
    parent = Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')/'fonts'
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent/'ADWS-NerdSymbols'
    if destination.is_symlink():
        raise RuntimeError(_tr('字体安装目录不能是软链接。'))
    with tempfile.TemporaryDirectory(prefix='.adws-fonts-', dir=parent) as name:
        temporary = Path(name); archive = temporary/'fonts.zip'; staged = temporary/'staged'
        staged.mkdir(); download(archive)
        with zipfile.ZipFile(archive) as package:
            entries = {Path(item.filename).name: item for item in package.infolist() if not item.is_dir()}
            for filename in FONTS:
                info = entries.get(filename)
                if not info or info.file_size > LIMIT:
                    raise ValueError(_tr('字体包内容无效。'))
                data = package.read(info)
                if data[:4] not in (b'\x00\x01\x00\x00', b'OTTO'):
                    raise ValueError(_tr('字体包内容无效。'))
                (staged/filename).write_bytes(data)
            # Preserve upstream notices alongside the fonts. Never extract paths.
            for filename, info in entries.items():
                if filename.upper().startswith(('LICENSE', 'OFL', 'COPYING')) and info.file_size < 128*1024:
                    (staged/filename).write_bytes(package.read(info))
        backup = temporary/'previous'
        if destination.exists():
            destination.rename(backup)
        try:
            staged.rename(destination)
            subprocess.run(['fc-cache', '-f', str(destination)], check=True, timeout=60,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if not available():
                raise RuntimeError(_tr('字体缓存刷新后仍未检测到 Nerd Fonts。'))
        except BaseException:
            if destination.exists():
                shutil.rmtree(destination)
            if backup.exists():
                backup.rename(destination)
            raise
    return destination


def ensure_fonts(confirm, install_packages, progress=print):
    try:
        if available():
            return True
        if not confirm(_tr('未检测到 Nerd Fonts。是否安装官方符号字体，避免任务栏图标显示为方框？（约 3 MB）')):
            progress(_tr('已跳过字体安装，之后可运行 adws check --install-fonts。'))
            return False
        if not shutil.which('fc-list') or not shutil.which('fc-cache'):
            install_packages(['fontconfig'])
        progress(_tr('正在下载并安装 Nerd Fonts 符号字体…'))
        destination = install()
        progress(_tr('图标字体已安装：%s') % destination)
        return True
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        progress(_tr('图标字体未安装，ADWS 安装可以继续：%s') % error)
        return False


if __name__ == '__main__':
    from adws_setup import confirm, install_packages
    raise SystemExit(0 if ensure_fonts(confirm, install_packages) else 1)

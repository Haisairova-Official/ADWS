"""Text glyph coverage and optional user-local Nerd Fonts symbols.

Text dependencies add missing-glyph fallback fonts only. They never rewrite
the user's primary font, Fontconfig rules, terminal configuration or CSS.
"""
import re
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
TEXT_FONT_PACKAGES = {
    'pacman': ['noto-fonts-cjk'],
    'apt-get': ['fonts-noto-cjk'],
    'dnf': ['google-noto-sans-cjk-vf-fonts'],
}
# Probe actual glyphs, including kana and Hangul: a Nerd Font family name or a
# successful fc-match can still mean that every CJK character renders as tofu.
# This is a baseline UI/filename check, not a claim to cover all of Unicode.
TEXT_SAMPLES = {
    'zh': '中文简体繁體桌面设置文件路径截图剪贴板输入法音频通知锁屏壁纸自动配色，。！？',
    'ja': '日本語ひらがなカタカナ設定画像',
    'ko': '한국어한글설정화면파일',
}


def probe_text_fonts(*, run=None, environ=None):
    """Check the union of installed Fontconfig charsets without changing fonts.

    Separate fonts may supply each script. Do not inspect only the first
    matching family or assume the installer's locale describes all filenames.
    """
    run=run or subprocess.run
    required={ord(char) for sample in TEXT_SAMPLES.values() for char in sample}
    missing=set(required);error=None
    try:
        result=run(['fc-list','--format=%{charset}\\n'],capture_output=True,text=True,
                   timeout=15,env=dict(os.environ if environ is None else environ))
        if result.returncode:
            raise ValueError('Fontconfig exited with status '+str(result.returncode))
        if len(result.stdout)>32*1024*1024:raise ValueError('Fontconfig charset output is too large')
        for token in result.stdout.split():
            if not re.fullmatch(r'[0-9a-fA-F]+(?:-[0-9a-fA-F]+)?',token):
                raise ValueError('Fontconfig returned an invalid charset')
            start,_,end=token.partition('-');low=int(start,16);high=int(end or start,16)
            if low>high or high>0x10ffff:raise ValueError('Fontconfig returned an invalid charset range')
            missing.difference_update(char for char in tuple(missing) if low<=char<=high)
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        error=str(exc);missing=set(required)
    result={'status':'unavailable' if error else 'missing' if missing else 'ready',
            'missing':{language:''.join(dict.fromkeys(char for char in sample if ord(char) in missing))
                       for language,sample in TEXT_SAMPLES.items()},
            'checked_characters':len(required),'policy':'CJK baseline glyph coverage, independent of locale'}
    if error:result['detail']=error
    return result


def text_font_plan(manager, *, probe=None):
    if manager not in TEXT_FONT_PACKAGES:raise ValueError('Unsupported font package manager: '+str(manager))
    coverage=(probe or probe_text_fonts)()
    return {'coverage':coverage,'packages':[] if coverage['status']=='ready' else list(TEXT_FONT_PACKAGES[manager]),
            'policy':'Preserve user font preferences; add fallback only when coverage is missing or unverified',
            'acceptance':'Recheck Chinese, Japanese and Korean glyph coverage after package installation'}


def require_text_fonts(*, probe=None):
    coverage=(probe or probe_text_fonts)()
    if coverage['status']!='ready':
        missing='、'.join(language for language,chars in coverage['missing'].items() if chars)
        detail=coverage.get('detail') or missing
        raise RuntimeError('中日韩文字字体覆盖验证失败（'+detail+'）；请检查已审核的字体依赖，不能将本次安装计为完成。')
    return coverage


def ensure_text_fonts(install_packages, manager, *, probe=None):
    """Legacy repair path; managed installations install reviewed packages first."""
    proposal=text_font_plan(manager,probe=probe)
    if proposal['packages']:install_packages(['fontconfig',*proposal['packages']])
    return require_text_fonts(probe=probe)


def _skip_css_token(text, index):
    """Skip comments, strings and escapes without interpreting their contents."""
    if text.startswith('/*', index):
        end = text.find('*/', index + 2)
        return len(text) if end < 0 else end + 2
    if text[index] in ('"', "'"):
        quote = text[index]; index += 1
        while index < len(text):
            if text[index] == chr(92): index += 2
            elif text[index] == quote: return index + 1
            else: index += 1
        return len(text)
    if text[index] == chr(92): return min(len(text), index + 2)
    return index + 1


def _font_value(value):
    boundaries = [0]; index = 0
    while index < len(value):
        if value.startswith('/*', index) or value[index] in ('"', "'", chr(92)):
            index = _skip_css_token(value, index)
        else:
            if value[index] == ',': boundaries.append(index + 1)
            index += 1
    parts = [value[start:(boundaries[i+1]-1 if i+1 < len(boundaries) else len(value))]
             for i, start in enumerate(boundaries)]
    names = [re.sub(r'/\*.*?\*/', '', part, flags=re.S).strip().lower() for part in parts]
    # Global keywords cannot be combined with a font list. Preserve comments.
    if names[0] in ('inherit', 'initial', 'unset', 'revert', 'revert-layer'):
        return value if len(parts) == 1 else parts[0].rstrip()
    existing = {name.strip('"\'') for name in names}
    additions = [name for name in ('Symbols Nerd Font', 'Symbols Nerd Font Mono') if name.lower() not in existing]
    if not additions: return value
    addition = ', '.join('"'+name+'"' for name in additions)
    generic = next((i for i, name in enumerate(names) if name in
                    ('sans-serif', 'serif', 'monospace', 'cursive', 'fantasy', 'system-ui')), None)
    if generic is not None:
        offset = boundaries[generic]
        whitespace = len(parts[generic]) - len(parts[generic].lstrip())
        offset += whitespace
        return value[:offset] + addition + ', ' + value[offset:]
    return value.rstrip() + ', ' + addition + value[len(value.rstrip()):]


def with_symbol_fallbacks(css):
    """Change declarations only; preserve CSS strings, comments and text fonts."""
    output = []; start = index = 0
    while index < len(css):
        if css.startswith('/*', index) or css[index] in ('"', "'", chr(92)):
            index = _skip_css_token(css, index); continue
        match = re.match(r'font-family\s*:', css[index:], re.I)
        if match and (index == 0 or not (css[index-1].isalnum() or css[index-1] in '_-')):
            value_start = index + match.end(); end = value_start
            while end < len(css):
                if css.startswith('/*', end) or css[end] in ('"', "'", chr(92)):
                    end = _skip_css_token(css, end)
                elif css[end] in ';{}': break
                else: end += 1
            if end == len(css) or css[end] != '{':
                output.append(css[start:value_start]); output.append(_font_value(css[value_start:end]))
                start = index = end
                continue
        index += 1
    output.append(css[start:])
    return ''.join(output)


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

"""GitHub Release checks and confirmed updates shared by CLI and GTK settings."""
import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from adws_i18n import tr as _tr, message

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = 'Haisairova-Official/ADWS'
RELEASES_API = f'https://api.github.com/repos/{REPOSITORY}/releases'
API = RELEASES_API + '/latest'
PREVIEW_API = RELEASES_API + '?per_page=100&page=1'
COUNTRY_API = 'https://api.country.is/'
DEFAULT_PROXY = 'https://gh-proxy.com/'


def read_json(url, timeout=5):
    request = urllib.request.Request(url, headers={'User-Agent': 'ADWS-update-check', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read(1024 * 1024 + 1)
    if len(payload) > 1024 * 1024:
        raise ValueError('Response exceeds size limit')
    data = json.loads(payload)
    if not isinstance(data, (dict, list)):
        raise ValueError('Expected a JSON object or array')
    return data


def mainland_china():
    try:
        data = read_json(COUNTRY_API, timeout=2)
        return isinstance(data, dict) and data.get('country') == 'CN'
    except (OSError, ValueError):
        return False


def version_key(text):
    # ADWS's Major is a decimal (1.20 -> 1.30), followed by letter-based Minor.
    match = re.fullmatch(r'v?(\d+\.\d+)(?:\.(\d+))?(?:[\s_-]*(Development|Pre-release|Released?|[A-Za-z]))?', text.strip(), re.I)
    if not match:
        raise ValueError(_tr('无法识别版本号：%s') % text)
    major, patch, minor = match.groups()
    rank = 27 if minor is None or minor.lower() in ('release', 'released') else 26.5 if minor.lower() == 'pre-release' else 0 if minor.lower() == 'development' else ord(minor.upper()) - ord('A') + 1
    return Decimal(major), int(patch or 0), rank


def current_version():
    info = json.loads((ROOT / 'build-info.json').read_text())
    if info.get('display_version'):
        return info['display_version']
    suffix = info.get('release_label') or info.get('minor_version') or 'Release'
    return f"{info['major_version']} {suffix}"


def release_version(release):
    tag = release.get('tag_name')
    if not isinstance(tag, str):
        raise ValueError(_tr('更新源缺少版本号。'))
    remote = version_key(tag)
    name = release.get('name')
    if isinstance(name, str):
        try:
            named = version_key(name)
            if named[:2] == remote[:2]:
                remote = named
        except ValueError:
            pass
    return remote


def preview_release(url):
    # Release lists are not guaranteed to be ordered by ADWS version. Scan pages
    # before selecting; an incomplete/failed response must not report "up to date".
    candidates = []
    unsupported = []
    for page in range(1, 11):
        releases = read_json(url.rsplit('page=', 1)[0] + 'page=' + str(page))
        if not isinstance(releases, list) or any(not isinstance(item, dict) for item in releases):
            raise ValueError(_tr('更新源未返回有效的 Release 列表。'))
        for release in releases:
            if release.get('draft'):
                continue
            try:
                candidates.append((release_version(release), release))
            except ValueError as error:
                unsupported.append(error)
        if len(releases) < 100:
            break
    else:
        raise ValueError(_tr('发布记录过多，未能完成更新检查。'))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    if unsupported:
        raise unsupported[0]
    return None


def github_urls(url, use_proxy):
    urls = [url]
    if use_proxy:
        proxy = os.environ.get('ADWS_GITHUB_PROXY', DEFAULT_PROXY).strip()
        parsed = urllib.parse.urlparse(proxy)
        if parsed.scheme == 'https' and parsed.netloc and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment:
            urls.insert(0, proxy.rstrip('/') + '/' + url)
    return urls


def confirm_install():
    try:
        while True:
            answer = input(_tr('是否现在安装更新？（Y/n）')).strip().lower()
            if answer in ('', 'y', 'yes'):
                return True
            if answer in ('n', 'no'):
                return False
            print(_tr('请输入 y 或 n。'))
    except (EOFError, KeyboardInterrupt):
        return False


def install_update(result, progress=print):
    from adws_upgrade import install_update as install
    return install(result, progress)


def check_update(preview=False):
    current = version_key(current_version())
    api = PREVIEW_API if preview else API
    use_proxy = mainland_china()
    urls = github_urls(api, use_proxy)
    errors = []
    for url in urls:
        try:
            if preview:
                release = preview_release(url)
            else:
                release = read_json(url)
                if not isinstance(release, dict) or release.get('draft') or release.get('prerelease'):
                    raise ValueError(_tr('更新源未返回正式 Release。'))
            if release is None or release_version(release) <= current:
                return {'available': False, 'text': message('updates.none'), 'url': None}
            tag = release['tag_name']
            link = f'https://github.com/{REPOSITORY}/releases/tag/' + urllib.parse.quote(tag, safe='')
            return {'available': True, 'text': _tr('发现新版本：%s') % tag, 'url': link, 'release': release, 'use_proxy': use_proxy}
        except (OSError, ValueError) as error:
            errors.append(str(error))
    raise RuntimeError(_tr('检查更新失败，请检查网络后重试。') + '\n' + '\n'.join(errors))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='adws --update', description=_tr('检查 GitHub Release 更新，并在确认后安装；默认稳定渠道。'))
    parser.add_argument('--preview', action='store_true', help=_tr('使用 Beta 渠道，包含预发布版本。'))
    args = parser.parse_args(argv)
    try:
        result = check_update(preview=args.preview)
        print(result['text'])
        if result['url']:
            print(result['url'])
        if result.get('available'):
            if not confirm_install():
                print(_tr('已取消。'))
                return 0
            print(install_update(result))
        return 0
    except KeyboardInterrupt:
        print(_tr('已取消。'), file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

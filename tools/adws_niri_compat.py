"""Opt-in, pinned Niri compatibility builds. Never replace the system compositor."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

from adws_i18n import tr as _tr
from adws_launcher import ask

ROOT = Path(__file__).resolve().parents[1]
PATCH_DIR = ROOT / 'patches/niri'
UPSTREAM = 'https://github.com/niri-wm/niri.git'


def niri_binary():
    # The side-by-side session wrapper exports its validator to child apps.
    configured = os.environ.get('ADWS_NIRI_BINARY')
    if configured and Path(configured).is_absolute() and os.access(configured, os.X_OK):
        return configured
    return shutil.which('niri')


def cache_root():
    return Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'adws/niri-compat'


def spec():
    data = json.loads((PATCH_DIR / 'manifest.json').read_text())
    patch = PATCH_DIR / data['patch']
    if patch.parent.resolve() != PATCH_DIR.resolve():
        raise ValueError(_tr('Niri 补丁路径无效。'))
    if hashlib.sha256(patch.read_bytes()).hexdigest() != data['sha256']:
        raise ValueError(_tr('Niri 补丁校验失败。'))
    return data, patch


def run(args, cwd=None, capture=False, env=None):
    result = subprocess.run(args, cwd=cwd, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None, env=env)
    return result.stdout.strip() if capture else None


def verify_source(source, expected):
    if run(['git', 'rev-parse', 'HEAD'], cwd=source, capture=True) != expected:
        raise ValueError(_tr('Niri 源码版本不匹配，拒绝应用补丁。'))
    if run(['git', 'status', '--porcelain'], cwd=source, capture=True):
        raise ValueError(_tr('Niri 源码包含本地修改，请使用干净的固定版本。'))


def wrapper(binary):
    return '#!/bin/sh\n# ADWS optional Niri; the system niri is unchanged.\nexport ADWS_NIRI_BINARY=' + shlex.quote(str(binary)) + '\nexec "$ADWS_NIRI_BINARY" "$@"\n'


def build(source=None, jobs=2):
    data, patch = spec()
    missing = [name for name in ('git', 'cargo', 'cc', 'pkg-config') if not shutil.which(name)]
    if missing:
        raise ValueError(_tr('缺少 Niri 构建工具：') + ', '.join(missing))
    cache = cache_root(); cache.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix='build-', dir=cache))
    tree = workspace / 'source'
    if source:
        source = Path(source).resolve()
        verify_source(source, data['commit'])
        run(['git', 'clone', '--no-hardlinks', '--no-checkout', '--', str(source), str(tree)])
        run(['git', 'checkout', '--detach', data['commit']], cwd=tree)
    else:
        run(['git', 'clone', '--depth', '1', '--branch', data['tag'], '--', UPSTREAM, str(tree)])
    verify_source(tree, data['commit'])
    # No fuzzy application and no mutation of the user's supplied checkout.
    run(['git', 'apply', '--check', str(patch)], cwd=tree)
    run(['git', 'apply', str(patch)], cwd=tree)
    env = dict(os.environ, CARGO_BUILD_JOBS=str(jobs), CARGO_TARGET_DIR=str(cache / 'target'))
    run(['cargo', 'test', '--locked', '-p', 'niri', '-p', 'niri-config', 'adws_'], cwd=tree, env=env)
    run(['cargo', 'build', '--release', '--locked', '-p', 'niri'], cwd=tree, env=env)
    binary = cache / 'target/release/niri'
    probe = workspace / 'modifier-probe.kdl'
    from adws_keyboard import bindings
    probe.write_text(bindings('traditional'))
    run([str(binary), 'validate', '-c', str(probe)])
    bundle = workspace / 'bundle'; bundle.mkdir()
    shutil.copy2(binary, bundle / 'niri')
    shutil.copy2(tree / 'LICENSE', bundle / 'LICENSE')
    shutil.copy2(patch, bundle / patch.name)
    manifest = dict(data, binary_sha256=hashlib.sha256((bundle / 'niri').read_bytes()).hexdigest(), source=str(tree))
    (bundle / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    script = bundle / 'niri-adws'; script.write_text(wrapper(bundle / 'niri')); script.chmod(0o755)
    print(_tr('兼容版构建完成，系统 Niri 未被修改：'))
    print(bundle)
    print(_tr('先在嵌套窗口测试；仅在退出原会话后使用 --session 启动。'))
    print(shlex.quote(str(script)))
    print(_tr('可选安装命令：') + ' adws niri-compat install --bundle ' + shlex.quote(str(bundle)))
    return bundle


def install_bundle(bundle):
    data, _ = spec()
    bundle = Path(bundle).resolve()
    built = json.loads((bundle / 'manifest.json').read_text())
    if any(built.get(key) != data[key] for key in ('commit', 'sha256', 'tag', 'patch_id', 'patch_version')):
        raise ValueError(_tr('兼容版构建信息与当前补丁不匹配。'))
    content = (bundle / 'niri').read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != built.get('binary_sha256'):
        raise ValueError(_tr('兼容版可执行文件校验失败。'))
    # A separate command cannot shadow /usr/bin/niri, niri-session or its service.
    destination = Path.home() / '.local/lib/adws-niri' / digest
    entry = Path.home() / '.local/bin/niri-adws'
    expected = wrapper(destination / 'niri')
    if (entry.exists() or entry.is_symlink()) and (entry.is_symlink() or entry.read_text() != expected):
        raise ValueError(_tr('niri-adws 命令已存在且不属于本次构建，请先检查。'))
    from adws_atomic import replace_files
    destination.mkdir(parents=True, exist_ok=True)
    replace_files({destination / 'niri': content, destination / 'manifest.json': (bundle / 'manifest.json').read_bytes(),
                   destination / 'LICENSE': (bundle / 'LICENSE').read_bytes()})
    (destination / 'niri').chmod(0o755)
    entry.parent.mkdir(parents=True, exist_ok=True)
    replace_files({entry: expected.encode()}); entry.chmod(0o755)
    print(_tr('已安装独立命令 niri-adws；未切换当前会话或修改登录管理器。'))
    print(entry)


def restore():
    from adws_keyboard import clean_block
    from adws_windows import config_path
    from adws_autostart import write_config
    path = config_path()
    if path.exists():
        write_config(path, clean_block(path.read_text()))
    print(_tr('已移除 ADWS 键位覆盖。下次登录选择原来的 Niri 会话即可恢复。'))


def offer():
    from adws_keyboard import modifier_taps_supported
    if modifier_taps_supported():
        return 0
    print(_tr('当前 Niri 不支持单修饰键。ADWS 可单独构建官方 26.04 的兼容版，不覆盖系统 Niri。'))
    try:
        if ask(_tr('是否构建可选兼容版？需要下载源码与依赖，耗时较长。（y/N）')).lower() not in ('y', 'yes'):
            return 0
        build()
    except (EOFError, KeyboardInterrupt):
        print(_tr('已取消。'))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(_tr('可选兼容版未完成，ADWS 安装不受影响：') + str(exc), file=sys.stderr)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog='adws niri-compat', description=_tr('可选 Niri 单修饰键补丁；不替换系统 Niri。'))
    parser.add_argument('action', choices=('status', 'build', 'install', 'restore', 'offer'), nargs='?', default='status')
    parser.add_argument('--source', type=Path, help=_tr('使用干净的官方 26.04 源码副本'))
    parser.add_argument('--bundle', type=Path, help=_tr('已构建的兼容版目录'))
    parser.add_argument('--jobs', type=int, default=2, help=_tr('并行构建数量，默认 2'))
    args = parser.parse_args(argv)
    if not 1 <= args.jobs <= 32:
        parser.error(_tr('并行构建数量必须在 1 到 32 之间。'))
    if (args.source and args.action != 'build') or (args.bundle and args.action != 'install'):
        parser.error(_tr('参数与所选操作不匹配。'))
    try:
        if args.action == 'offer': return offer()
        if args.action == 'status':
            data, _ = spec()
            print(f"ADWS {data['patch_id']} {data['patch_version']} (Niri {data['tag']})")
            from adws_keyboard import modifier_taps_supported
            print(_tr('当前 Niri 已支持单修饰键，无需补丁。') if modifier_taps_supported() else _tr('当前 Niri 不支持单修饰键，可选构建兼容版。'))
            return 0
        if args.action == 'build':
            print(_tr('将构建官方 Niri 26.04 加 ADWS 补丁，保留系统版本；不会自动启用或重启桌面。'))
            if ask(_tr('继续？（y/N）')).lower() not in ('y', 'yes'): return 0
            build(args.source, args.jobs)
        elif args.action == 'install':
            if not args.bundle: parser.error('--bundle is required')
            install_bundle(args.bundle)
        elif args.action == 'restore':
            restore()
        return 0
    except (EOFError, KeyboardInterrupt):
        print(_tr('已取消。')); return 1
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr); return 1

if __name__ == '__main__':
    raise SystemExit(main())

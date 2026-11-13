"""Resolve Rust tools and mirror policy for component builds."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tomllib

from adws_i18n import tr as _tr


def build_environment():
    """Use a supported Rust pair, including rustup absent from a GUI's PATH."""
    base = dict(os.environ)
    candidates = [base.get('PATH', os.defpath)]
    cargo_home = Path(base.get('CARGO_HOME') or Path.home() / '.cargo')
    candidates.append(str(cargo_home / 'bin') + os.pathsep + candidates[0])
    for path in dict.fromkeys(candidates):
        env = {**base, 'PATH': path}
        rustc = shutil.which('rustc', path=path)
        cargo = shutil.which('cargo', path=path)
        if not rustc or not cargo:
            continue
        try:
            compiler = subprocess.run([rustc, '--version'], capture_output=True, text=True, timeout=15, env=env)
            driver = subprocess.run([cargo, '--version'], capture_output=True, text=True, timeout=15, env=env)
            versions = [re.search(r'\b(?:rustc|cargo) (\d+)\.(\d+)\.(\d+)', result.stdout or '') for result in (compiler, driver)]
            if all(result.returncode == 0 for result in (compiler, driver)) and all(
                    version and tuple(map(int, version.groups())) >= (1, 87, 0) for version in versions):
                return env
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError(_tr('构建需要 Rust / Cargo 1.87 或更新版本。请通过 rustup 安装或更新 stable 工具链后重试；Ubuntu / Mint 自带的旧版 Rust 不满足要求。'))


def cargo_source_configuration(env, cwd=None):
    """Find existing source policy without overriding Cargo's own merging rules.

    Be conservative: even an unused registry can name the same index as our
    temporary mirror. Let Cargo resolve existing policy rather than adding a
    second source for that URL. Rustup download servers are a separate concern.
    """
    def source_variable(name):
        return (name.startswith('CARGO_SOURCE_') or
                (name.startswith('CARGO_REGISTRIES_') and
                 name.endswith(('_INDEX', '_PROTOCOL'))) or
                name == 'CARGO_REGISTRY_DEFAULT')

    reasons = [key for key, value in env.items() if value and source_variable(key)]
    base = Path(cwd or Path.cwd()).resolve()
    cargo_home = Path(env.get('CARGO_HOME') or Path(env.get('HOME') or Path.home()) / '.cargo')
    if not cargo_home.is_absolute():
        cargo_home = base / cargo_home
    folders = [directory / '.cargo' for directory in (base, *base.parents)] + [cargo_home]
    seen = set()
    for folder in folders:
        # Cargo prefers legacy `config` if both filenames exist.
        path = folder / 'config'
        if not path.exists():
            path = folder / 'config.toml'
        if not path.exists() or path.resolve() in seen:
            continue
        seen.add(path.resolve())
        try:
            data = tomllib.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            raise RuntimeError(_tr('无法读取 Cargo 配置，请修复后重试：%s') % path) from error
        registries = data.get('registries', {})
        registry = data.get('registry', {})
        configured_env = data.get('env', {})
        if (data.get('source') or
                (isinstance(registries, dict) and any(
                    isinstance(value, dict) and ('index' in value or 'protocol' in value)
                    for value in registries.values())) or
                (isinstance(registry, dict) and registry.get('default')) or
                (isinstance(configured_env, dict) and any(source_variable(key) for key in configured_env))):
            reasons.append(str(path))
    return reasons


def choose_build_mirror(env, cwd, confirm):
    """Reuse existing sources; only offer a temporary mirror when none exist."""
    from adws_i18n import chinese
    result = dict(os.environ if env is None else env)
    existing = cargo_source_configuration(result, cwd)
    if existing:
        if result.get('ADWS_BUILD_MIRROR') != '0':
            print(_tr('检测到已有 Cargo 源配置，将沿用，不叠加国内镜像：%s') % ', '.join(existing))
        result['ADWS_BUILD_MIRROR'] = '0'
    elif 'ADWS_BUILD_MIRROR' not in result:
        result['ADWS_BUILD_MIRROR'] = '1' if chinese() and confirm('是否为本次构建使用国内 Rust 镜像源（RsProxy）？') else '0'
    return result


def cargo_build_command(env, cwd=None):
    command = ['cargo']
    # Recheck at each actual build directory, including inherited mirror choices.
    if env.get('ADWS_BUILD_MIRROR') == '1' and not cargo_source_configuration(env, cwd):
        command += ['--config', 'source.crates-io.replace-with="adws-rsproxy"',
                    '--config', 'source.adws-rsproxy.registry="sparse+https://rsproxy.cn/index/"']
    return command + ['build', '--release', '--locked']

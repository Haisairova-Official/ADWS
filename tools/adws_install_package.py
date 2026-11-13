"""Bounded, read-only release payload checks (not a runtime compatibility claim)."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re

# These are required even before newly added files have entered Git's index.
REQUIRED = (
    'build-info.json', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md',
    'tools/adws_about_page.py', 'tools/adws_about_markdown.py', 'tools/adws_sddm_page.py', 'tools/adws_sddm.py',
    'tools/adws_login_manager.py',
    'install.sh', 'adws', 'scripts/adws-install.sh', 'scripts/adws-install-session.sh', 'scripts/adws-i18n.sh',
    'scripts/adws-bootstrap.sh', 'scripts/package-bootstrap.py', 'tools/adws_bootstrap.py', 'tools/adws_download.py',
    'tools/adws_install_workflow.py', 'tools/adws_install_transaction.py', 'tools/adws_install_features.py',
    'tools/adws_install_niri.py', 'tools/adws_install_migration.py', 'tools/adws_install_startup.py',
    'tools/adws_install_source_migration.py',
    'tools/adws_install_topbar_migration.py', 'tools/adws_install_bar_lifecycle.py',
    'tools/adws_install_acceptance.py', 'tools/adws_install_package.py',
    'tools/adws_install_session_config.py', 'tools/adws_install_personal.py', 'tools/adws_install_validation.py', 'tools/adws_install_boot_themes.py',
    'tools/adws_palette_sync.py', 'docs/platform-support.md',
    'tools/adws_setup.py', 'tools/adws_niri_install.py', 'tools/adws_prebuilt.py', 'tools/adws_fonts.py',
    'tools/adws_runtime_dependencies.py', 'docs/installer-roadmap.md', 'docs/installation.md',
    'docs/installer-keybindings.md', 'docs/installer-reference-shorin.md',
    'docs/installer-optional-boot-themes.md', 'docs/installer-arch-validation.md',
    'docs/validation-foot-palette-2026-11-06.md',
    'config/adws-windows.kdl', 'config/taskbar-layout.json', 'config/context-menu.css',
    'tools/adws_group_names.py', 'tools/adws_group_file_actions.py',
    'config/waybar/config-bottom.jsonc', 'config/waybar/modules.jsonc', 'config/waybar/style-bottom.css',
    'config/waybar/config-top.jsonc', 'config/waybar/style-top.css', 'config/waybar/colors.css',
    'config/waybar/arrow-left-symbolic.svg', 'config/waybar/arrow-right-symbolic.svg',
    # The README's standalone taskbar build also compiles its Rust and C modules.
    'tools/adws_build_taskbar_preview.py', 'tools/adws_cargo.py', 'tools/adws_native_taskbar.py',
    'tools/adws_taskbar_backend.py', 'tools/adws_taskbar_nested.py',
    'tests/check_rust_taskbar_wayland.py',
    'src/adws-taskbar/Cargo.toml', 'src/adws-taskbar/Cargo.lock',
    'src/adws-taskbar/src/main.rs', 'src/adws-taskbar/src/host.rs', 'src/adws-taskbar/src/cffi.rs',
    'src/adws-taskbar/src/style.rs', 'src/adws-taskbar/src/widgets.rs',
    'src/adws-taskbar/src/widgets/custom.rs', 'src/adws-taskbar/src/widgets/stream.rs',
    'src/adws-taskbar/src/widgets/workspaces.rs',
    'src/niri-taskbar/Cargo.toml', 'src/niri-taskbar/Cargo.lock', 'src/niri-taskbar/src/paths.rs',
    'src/adws-runtime/Cargo.toml', 'src/adws-runtime/Cargo.lock',
    'src/adws-start-menu/Cargo.toml', 'src/adws-start-menu/Cargo.lock', 'vendor/niri-ipc/Cargo.toml',
    'src/panel-rows/panel.c', 'src/panel-rows/start-image.h', 'src/panel-rows/motion.h',
    'src/adws-i18n.h', 'src/niri-desktop-layer/integration/popup-effect.c',
    'src/niri-desktop-layer/integration/waybar-space.c', 'src/panel-rows/Makefile',
)
NATIVE = ('libniri_taskbar.so', 'libadws_panel.so', 'libwaybar-space.so', 'adws-plugin-runner', 'adws-start-menu')


def packaging_additions(root):
    """New installer helpers are included before a developer stages their commit."""
    root = Path(root)
    return sorted(set(REQUIRED) | {str(p.relative_to(root)) for p in (root/'tools').glob('adws_install_*.py')})


def check(root, *, require_prebuilt=False):
    root = Path(root).resolve()
    errors = []
    checked = set()
    def require(path, context):
        path = Path(path)
        try:
            path.resolve().relative_to(root)
        except ValueError:
            errors.append(f'{context}: reference escapes package: {path}')
            return False
        checked.add(str(path.relative_to(root)))
        if not path.is_file():
            errors.append(f'{context}: missing {path.relative_to(root)}')
            return False
        return True
    for name in REQUIRED: require(root/name, 'required installer payload')
    # Check static local module imports. Third-party imports are handled by the
    # feature dependency manifest; dynamic imports are deliberately not claimed.
    for path in (root/'tools').glob('*.py'):
        if not require(path, 'Python source'): continue
        try: tree = ast.parse(path.read_text(), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as error:
            errors.append(f'{path.name}: invalid Python source: {error}'); continue
        for node in ast.walk(tree):
            names = [alias.name for alias in node.names] if isinstance(node,ast.Import) else [node.module] if isinstance(node,ast.ImportFrom) and not node.level else []
            for name in names:
                if name and name.startswith('adws_'):
                    require(root/'tools'/(name.split('.')[0]+'.py'), path.name)
        if path.name == 'adws_fonts.py':
            constants = {}
            for node in tree.body:
                if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
                    try: constants[node.targets[0].id] = ast.literal_eval(node.value)
                    except (ValueError,TypeError): pass
            if not str(constants.get('URL','')).startswith('https://') or not re.fullmatch(r'[0-9a-f]{64}',str(constants.get('SHA256',''))):
                errors.append('Nerd Font dependency needs a pinned HTTPS source and SHA-256')
    # CSS assets and JSONC include lists in the shipped bar defaults only. Do not
    # execute on-click commands or pretend dynamic generated paths are covered.
    for path in (root/'config/waybar').glob('*.css'):
        if not require(path, 'bar stylesheet'): continue
        css = re.sub(r'/\*.*?\*/','',path.read_text(),flags=re.S)
        refs = re.findall(r'@import\s+["\']([^"\']+)["\']',css)
        refs += re.findall(r'url\(\s*["\']?([^"\')\s]+)',css)
        for reference in refs:
            if not reference.startswith(('data:', 'http:', 'https:', 'resource:')):
                require(path.parent/reference,path.name)
    for path in (root/'config/waybar').glob('*.jsonc'):
        if not require(path, 'bar configuration'): continue
        for group in re.findall(r'"include"\s*:\s*\[([^]]*)\]',path.read_text()):
            for reference in re.findall(r'"([^"\n]+)"',group):
                require(path.parent/reference,path.name)
    if require_prebuilt:
        manifest_path = root/'prebuilt/manifest.json'
        if require(manifest_path,'native manifest'):
            try: hashes = json.loads(manifest_path.read_text())['sha256']
            except (OSError,ValueError,KeyError,TypeError): hashes = {}; errors.append('Invalid native manifest')
            if not isinstance(hashes, dict): hashes = {}; errors.append('Invalid native hash map')
            for name in NATIVE:
                path = root/'prebuilt'/name
                if require(path,'native artifact') and hashlib.sha256(path.read_bytes()).hexdigest() != hashes.get(name):
                    errors.append('Native artifact checksum mismatch: '+name)
    return {'complete': not errors, 'errors': errors, 'checked_files': sorted(checked),
            'scope': 'Required installer payload, static local imports, bundled bar CSS/include assets, pinned font source, optional native hashes.',
            'not_verified': ['dynamic runtime references', 'target distro library ABI', 'clean-machine installation and functionality']}


def assert_complete(root, *, require_prebuilt=False):
    report = check(root,require_prebuilt=require_prebuilt)
    if not report['complete']:
        raise RuntimeError('Incomplete ADWS package:\n'+'\n'.join(report['errors']))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('--prebuilt',action='store_true')
    args = parser.parse_args(argv)
    report = check(args.root,require_prebuilt=args.prebuilt)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['complete'] else 1

if __name__ == '__main__': raise SystemExit(main())

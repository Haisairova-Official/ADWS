"""Build the native trial and its ADWS modules inside this checkout."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

from adws_cargo import build_environment, cargo_build_command, cargo_source_configuration, choose_build_mirror
from adws_setup import confirm

ROOT = Path(__file__).resolve().parents[1]
CRATES = (
    ('adws-taskbar', 'adws-taskbar'),
    ('niri-taskbar', 'libniri_taskbar.so'),
    ('adws-runtime', 'adws-plugin-runner'),
    ('adws-start-menu', 'adws-start-menu'),
)
C_MODULES = (
    ('src/panel-rows/panel.c', 'libadws_panel.so', 'json-glib-1.0'),
    ('src/niri-desktop-layer/integration/waybar-space.c', 'libwaybar-space.so', 'wayland-client'),
)


def main():
    if sys.argv[1:]:
        print('Usage: adws build-taskbar-preview', file=sys.stderr)
        return 0 if sys.argv[1:] in (['--help'], ['-h']) else 2
    destination = ROOT / 'libexec/taskbar-preview'
    destination.mkdir(parents=True, exist_ok=True)
    env = build_environment()
    crates = [ROOT / 'src' / crate for crate, _ in CRATES]
    policy = next((path for path in crates if cargo_source_configuration(env, path)), crates[0])
    env = choose_build_mirror(env, policy, confirm)
    with tempfile.TemporaryDirectory(prefix='.build-', dir=destination) as tmp:
        staged = Path(tmp)
        for component, name in CRATES:
            crate = ROOT / 'src' / component
            build = cargo_build_command(env, crate)
            target = crate / 'target'
            subprocess.run([*build, '--target-dir', str(target)], cwd=crate, env=env, check=True)
            shutil.copy2(target / 'release' / name, staged / name)
        for source, name, dependency in C_MODULES:
            flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gtk+-3.0',
                                             'gtk-layer-shell-0', dependency], text=True, env=env)
            subprocess.run(['cc', '-O2', '-shared', '-fPIC', str(ROOT / source), '-o', str(staged / name),
                            *shlex.split(flags), '-lm'], check=True, env=env)
        for path in staged.iterdir():
            os.replace(path, destination / path.name)
    print(destination)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(f'adws build-taskbar-preview: {error}')

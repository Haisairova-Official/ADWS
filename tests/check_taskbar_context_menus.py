#!/usr/bin/env python3
"""Exercise desktop and native taskbar menus with real input in a private Niri session."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

from PIL import ImageChops
from check_rust_taskbar_wayland import ROOT, wait_for
from nested_niri_input import nested_input


def check(directory, root, bar, library, name):
    output = directory.resolve()
    output.mkdir(parents=True, exist_ok=True)

    def menu_bounds(image, base, point):
        # Window focus borders can change when a layer popup grabs the seat.
        # Measure only the space near the anchor and away from the test window.
        x, y = point
        left = 0 if x < 330 else min(x-4, image.width-340)
        if y < 400:
            rect = (left, y-4, image.width, image.height-48)
        elif x < 330:
            rect = (0, max(0, y-510), 360, image.height-46)
        else:
            rect = (left, max(0, y-325), image.width-6, image.height-47)
        diff = ImageChops.difference(image.crop(rect), base.crop(rect)).convert('L')
        mask = diff.point(lambda v: 255 if v > 12 else 0)
        # Gtk can change focus colors across the entire dock when a grab ends.
        # Count significant horizontal and vertical runs to exclude focus/hover
        # chrome, shadows and a test window border from the popup rectangle.
        min_width = 70
        rows = [y for y in range(mask.height) if mask.crop((0,y,mask.width,y+1)).histogram()[255] >= min_width]
        if len(rows) < 35:
            return None
        top, bottom = rows[0], rows[-1]+1
        cols = [x for x in range(mask.width) if mask.crop((x,top,x+1,bottom)).histogram()[255] >= 25]
        local = (cols[0], top, cols[-1]+1, bottom) if cols else None
        return tuple(v + rect[i%2] for i,v in enumerate(local)) if local else None

    def opened(name, point, *, hold_shift=False):
        move(*point)
        time.sleep(.15)
        base = screen()
        if hold_shift:
            run('xdotool', 'keydown', 'Shift_L')
        run('xdotool', 'click', '3')
        def changed():
            image = screen()
            area = menu_bounds(image, base, point)
            if area and area[2] - area[0] >= 80 and area[3] - area[1] >= 48:
                return image, area
        wait_for(name + ' popup', changed, 4)
        time.sleep(.2)
        image = screen()
        bounds = menu_bounds(image, base, point)
        if not bounds:
            raise RuntimeError(name + ' popup disappeared')
        left, top, right, bottom = bounds
        # All three menus should use the same Matugen surface. The opaque
        # span grows below the menu's first row when both corners are rounded.
        face = (40, 41, 52)
        def face_span(row):
            pixels = [x for x in range(left, right) if image.getpixel((x, row)) == face]
            if not pixels:
                raise RuntimeError(f'{name} is missing the expected popup surface')
            return pixels[0], pixels[-1]
        outer = face_span(top)
        inner = face_span(top + 12)
        if outer[0] - inner[0] < 5 or inner[1] - outer[1] < 5:
            raise RuntimeError(f'{name} has a square corner: {outer}, {inner}')
        image.save(output / (name + '.png'))
        return bounds

    try:
        with nested_input(root) as seat:
            env, run, spawn = seat.env, seat.run, seat.spawn
            move, screen, layers = seat.move, seat.screen, seat.layers
            desktop = root / 'Desktop'
            desktop.mkdir()
            group = desktop / 'ADWS.txt'
            group.write_text('ADWS')
            style = Path(env['XDG_CONFIG_HOME']) / 'waybar'
            style.mkdir(parents=True)
            for css_file in ('style-bottom.css', 'colors.css'):
                shutil.copyfile(ROOT / 'config/waybar' / css_file, style / css_file)
            spawn('wallpaper', ['swaybg', '-c', '#718598'])
            spawn('desktop', [sys.executable, str(ROOT / 'src/niri-desktop-layer/desktop-layer'),
                                     '--directory', str(desktop), '--state', str(root / 'desktop.json')])
            wait_for('desktop', lambda: 'niri-desktop-layer' in layers())
            data = {
                'position': 'bottom', 'layer': 'bottom', 'height': 44,
                'modules-left': ['cffi/niri-taskbar'], 'modules-right': ['clock'],
                'cffi/niri-taskbar': {'module_path': str(library), 'window_animations': True,
                                      'termination_mode': 'shift', 'animation_duration': 600, 'thickness': 44},
                'clock': {'format': '{:%H:%M}'},
            }
            path = root / 'bar.json'
            path.write_text(json.dumps(data))
            bar_proc = spawn('bar', [str(bar), '--config', str(path), '--style', str(style / 'style-bottom.css')])
            wait_for('native taskbar', lambda: 'adws-taskbar' in layers())
            client = spawn('client', [sys.executable, '-c',
                "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk, GLib; "
                "GLib.set_prgname('org.gnome.TextEditor'); w=Gtk.Window(title='ADWS'); "
                "w.set_default_size(380,190); w.add(Gtk.Label(label='ADWS')); "
                "w.connect('destroy',Gtk.main_quit); w.show_all(); Gtk.main()"])
            def windows():
                return json.loads(run('niri', 'msg', '-j', 'windows'))
            wait_for('single test window', lambda: any(w['pid'] == client.pid for w in windows()))
            time.sleep(.5)
            size = screen().size
            y = size[1] - 20
            points = {'card': (24, y), 'shift': (24, y), 'panel': (size[0]-290, y),
                      'desktop': (size[0]-330, 160)}
            bounds = opened(name, points[name], hold_shift=name == 'shift')
            if name != 'shift':
                return bounds
            left, _, right, bottom = bounds
            move(left + (right-left)//2, bottom-15)
            time.sleep(.7)
            shot = screen()
            shot.save(output / 'shift.png')
            def red_area(image):
                return sum(count for count, (r, g, b) in image.crop(bounds).getcolors(1 << 24)
                           if r > 130 and r > g * 1.8 and r > b * 1.8)
            red = red_area(shot)
            if red < 120:
                raise RuntimeError(f'Shift destructive item did not turn red ({red} pixels)')
            run('xdotool', 'keyup', 'Shift_L')
            probe = (right-28, bottom-15)
            intermediate = set()
            deadline = time.monotonic() + 1.2
            while time.monotonic() < deadline:
                plain = screen()
                r, g, b = plain.getpixel(probe)
                if r <= 32:
                    break
                if 38 < r < 192:
                    intermediate.add(r)
            if len(intermediate) < 2:
                raise RuntimeError(f'Destructive highlight did not fade ({intermediate})')
            plain.save(output / 'released.png')
            red_after = red_area(plain)
            if red_after >= red//2:
                raise RuntimeError(f'Close did not return after releasing Shift ({red_after}/{red} red pixels)')
            run('xdotool', 'click', '1')
            wait_for('closed only the test window', lambda: client.poll()==0 and not windows())
            if bar_proc.poll() is not None or 'niri-desktop-layer' not in layers():
                raise RuntimeError('Menu activation stopped the bar or desktop')
            return {'bounds': bounds, 'shift_red': red, 'released_red': red_after, 'fade_samples': len(intermediate), 'closed': True}
    except Exception:
        for log in root.glob('*.log'):
            print(log.name, log.read_text(errors='replace')[-1000:], file=sys.stderr)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=ROOT / 'libexec/taskbar-preview/adws-taskbar')
    parser.add_argument('--task-library', type=Path, default=ROOT / 'libexec/taskbar-preview/libniri_taskbar.so')
    parser.add_argument('--screenshots', type=Path, required=True)
    args = parser.parse_args()
    evidence = {}
    for name in ('desktop', 'panel', 'card', 'shift'):
        with tempfile.TemporaryDirectory(prefix='adws-menu-check-') as path:
            evidence[name] = check(args.screenshots, Path(path), args.binary.resolve(strict=True),
                                   args.task_library.resolve(strict=True), name)
            print(name, evidence[name], flush=True)
    (args.screenshots / 'results.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(f'PASS native menus and window close; screenshots {args.screenshots}')

#!/usr/bin/env python3
"""Exercise grouped desktop right-click hit testing with a real mouse on nested Niri."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

from PIL import ImageChops
from check_rust_taskbar_wayland import ROOT, wait_for
from nested_niri_input import nested_input
sys.path.insert(0, str(ROOT / "tools"))
from adws_desktop_groups_model import geometry, new_group


def setup_desktop(root, seat):
    desktop = root / 'Desktop'
    desktop.mkdir()
    directory = root / '测试图标组'
    directory.mkdir()
    entry = directory / '测试文件.desktop'
    entry.write_text('[Desktop Entry]\nType=Application\nName=测试文件\nIcon=text-x-generic\n'
                     f'Exec=/usr/bin/touch "{root / "opened"}"\n')
    entry.chmod(0o755)
    document = directory / 'source.txt'
    document.write_text('preserve this content')
    group = new_group(directory)
    group.update(x=.12, y=.19, cells={entry.name: [0, 0], document.name: [1, 0]})
    (root / 'desktop-groups.json').write_text(json.dumps({
        'version': 1, 'default_monitor': 'primary', 'groups': [group],
    }))
    seat.spawn('wallpaper', ['swaybg', '-c', '#718598'])
    seat.spawn('desktop', [sys.executable, str(ROOT / 'src/niri-desktop-layer/desktop-layer'),
                           '--directory', str(desktop), '--state', str(root / 'layout.json')])
    wait_for('desktop surface', lambda: 'niri-desktop-layer' in seat.layers())
    time.sleep(.6)
    return geometry(group, *seat.screen().size)


def popup(seat, output, name, point):
    seat.move(*point)
    time.sleep(.12)
    before = seat.screen()
    seat.run('xdotool', 'mousedown', '3')
    time.sleep(.075)
    seat.run('xdotool', 'mouseup', '3')

    return locate_popup(seat, output, name, before)


def locate_popup(seat, output, name, before, excluded=None):
    def locate():
        shot = seat.screen()
        # Exclude the existing parent menu when locating a newly opened submenu.
        target = (40, 41, 52)
        mask = None
        for channel, color in zip(shot.split(), target):
            exact = channel.point(lambda value, wanted=color: 255 if value == wanted else 0)
            mask = exact if mask is None else ImageChops.multiply(mask, exact)
        changed = ImageChops.difference(shot, before).convert('L').point(lambda x: 255 if x > 3 else 0)
        mask = ImageChops.multiply(mask, changed)
        if excluded is not None:
            mask.paste(0, excluded)
        bounds = mask.getbbox()
        if bounds and bounds[2]-bounds[0] > 70 and bounds[3]-bounds[1] > 42:
            return shot, bounds
    try:
        shot, bounds = wait_for(name + ' context menu', locate, 3)
    except RuntimeError:
        before.save(output / (name+'-before.png'))
        seat.screen().save(output / (name+'-missing.png'))
        raise
    shot.save(output / (name + '.png'))
    return bounds


def click_item(seat, bounds, yoffset):
    seat.move((bounds[0]+bounds[2])//2, bounds[1]+yoffset)
    seat.run('xdotool', 'click', '1')

def windows(seat):
    return json.loads(seat.run('niri','msg','-j','windows'))


def wait_dialog(seat, *titles):
    return wait_for('/'.join(titles), lambda: next((w for w in windows(seat)
                    if w['title'] in titles and w['is_focused']), None), 4)


def name_and_submit(seat, value):
    seat.run('xdotool', 'key', 'ctrl+a')
    seat.run('xdotool', 'type', '--clearmodifiers', value)
    seat.run('xdotool', 'key', 'Return')


def exercise_create(root, output, seat, point):
    directory = root / '测试图标组'
    def start(kind, row):
        bounds = popup(seat, output, 'create-group', point)
        before = seat.screen()
        seat.move((bounds[0]+bounds[2])//2, bounds[1]+21)
        sub = locate_popup(seat, output, 'new-submenu', before, bounds)
        click_item(seat, sub, 21+32*row)
        wait_dialog(seat, *kind)

    folders = ('新建文件夹', 'New folder')
    text = ('新建文本文档', 'New text document')
    markdown = ('新建 Markdown 文档', 'New Markdown document')
    start(folders, 0)
    seat.run('xdotool', 'key', 'Escape')
    wait_for('cancelled create', lambda: not windows(seat))
    assert sorted(path.name for path in directory.iterdir()) == ['source.txt','测试文件.desktop']
    for kind, row, name in [(folders,0,'folder-test'), (text,1,'notes.txt'), (markdown,2,'notes.md')]:
        start(kind, row)
        if row == 1:
            name_and_submit(seat, 'source.txt')
            wait_dialog(seat, *text)
            # The async collision response selects the conflicting name for editing.
            # Wait for its error-colour glyphs before starting the next submission.
            def collision_shown():
                shot = seat.screen()
                colors = shot.getcolors(shot.width * shot.height)
                if sum(count for count, (r,g,b) in colors if r >= 230 and 140 < g < 205
                       and 130 < b < 205 and r > g + 47) > 10:
                    return shot
            shot = wait_for('visible name collision message', collision_shown, 4)
            assert (directory / 'source.txt').read_text() == 'preserve this content'
            shot.save(output/'create-collision.png')
        name_and_submit(seat, name)
        destination = directory / name
        wait_for('new item in the selected group', destination.exists, 4)
        assert destination.is_dir() if row == 0 else destination.is_file()
        assert not any((root/'Desktop').iterdir())
        wait_for('accepted creation', lambda: not windows(seat))


def exercise_file_actions(root, output, seat, point):
    directory = root / '测试图标组'
    source = directory/'source.txt'
    original = source.read_bytes()
    def select(label, offset):
        bounds = popup(seat, output, label, point)
        click_item(seat, bounds, offset)

    select('properties-file', 215)
    wait_dialog(seat, '属性', 'Properties')
    seat.run('xdotool', 'key', 'Escape')
    wait_for('closed file properties', lambda: not windows(seat))
    seat.move(*point)
    seat.run('xdotool', 'click', '1', 'key', 'F2')
    wait_dialog(seat, '重命名', 'Rename')
    seat.run('xdotool', 'key', 'Escape')
    wait_for('cancelled rename', lambda: not windows(seat))
    assert source.read_bytes() == original
    select('rename-file', 151)
    wait_dialog(seat, '重命名', 'Rename')
    name_and_submit(seat, 'changed.txt')
    target = directory/'changed.txt'
    wait_for('renamed file', target.exists, 4)
    assert not source.exists() and target.read_bytes() == original
    statefile = root/'desktop-groups.json'
    def same_cell():
        cells = json.loads(statefile.read_text())['groups'][0]['cells']
        return cells.get('changed.txt') == [1,0] and 'source.txt' not in cells
    wait_for('preserved file position', same_cell)
    select('trash-file', 183)
    wait_dialog(seat, '移到回收站', 'Move to Trash')
    seat.run('xdotool','key','Escape')
    wait_for('cancelled trash', lambda: not windows(seat))
    assert target.read_bytes() == original
    select('trash-file', 183)
    wait_dialog(seat, '移到回收站', 'Move to Trash')
    seat.screen().save(output/'trash-confirm.png')
    seat.run('xdotool','key','Tab','space')
    trash = Path(seat.env['XDG_DATA_HOME'])/'Trash'/'files'
    wait_for('trashed file in isolated XDG trash', lambda: not target.exists() and trash.is_dir()
             and any(w.read_bytes()==original for w in trash.glob('changed*.txt')), 4)
    assert not any((root/'Desktop').iterdir())


def exercise(root, output, name):
    with nested_input(root) as seat:
        x, y, width, height = setup_desktop(root, seat)
        points = {'file': (x+54,y+76), 'group': (x+width-80,y+height-72),
                  'header': (x+95,y+21), 'desktop': (x+width+150,y+85)}
        if name == 'create':
            exercise_create(root, output, seat, points['group'])
            return True
        if name == 'file-actions':
            exercise_file_actions(root, output, seat, (x+142,y+76))
            return True
        bounds = popup(seat, output, name, points[name])
        if name == 'file':
            seat.move(x+width+100,y+height+70)
            seat.run('xdotool','click','1')
            time.sleep(.15)
            assert not (root/'opened').exists(), 'Dismissing a menu launched the file'
            bounds = popup(seat, output, name, points[name])
            click_item(seat, bounds, 21)
            wait_for('launch of the file selected in the group', (root/'opened').exists, 4)
        elif name in ('group', 'header'):
            # Open group settings through the real menu, including from its title.
            click_item(seat, bounds, 118)
            def editor():
                windows = json.loads(seat.run('niri','msg','-j','windows'))
                return any(w.get('title') in ('图标组设置', 'Icon group settings') for w in windows)
            wait_for('group settings from '+name, editor, 4)
        else:
            marker = Path(seat.env['XDG_STATE_HOME']) / 'desktop-hidden'
            click_item(seat, bounds, 85)
            wait_for('hide groups from desktop menu', marker.exists, 3)
            # The desktop must remain interactive when no groups are visible.
            hidden_menu = popup(seat, output, 'hidden', points[name])
            click_item(seat, hidden_menu, 85)
            wait_for('show groups again', lambda: not marker.exists(), 3)
            bounds = popup(seat, output, name, points[name])
            # Opening 'Create icon group' also distinguishes this entry point from
            # a file or group menu even when all of them share the same dimensions.
            click_item(seat, bounds, 21)
            def creation():
                windows = json.loads(seat.run('niri','msg','-j','windows'))
                return any(w.get('title') in ('创建图标组', 'Create icon group') for w in windows)
            wait_for('new group settings on the desktop', creation, 4)
        return bounds


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshots', type=Path, required=True)
    cases = ('file','group','header','desktop','create','file-actions')
    parser.add_argument('--only', choices=cases)
    args = parser.parse_args()
    args.screenshots.mkdir(parents=True, exist_ok=True)
    result = {}
    for name in ((args.only,) if args.only else cases):
        with tempfile.TemporaryDirectory(prefix='adws-desktop-menu-') as folder:
            root = Path(folder)
            try:
                result[name] = exercise(root, args.screenshots, name)
            except Exception:
                for log in root.glob('*.log'):
                    print(log.name, log.read_text(errors='replace')[-1800:], file=sys.stderr)
                raise
        print(name, result[name], flush=True)
    (args.screenshots / 'results.json').write_text(json.dumps(result, indent=2)+'\n')

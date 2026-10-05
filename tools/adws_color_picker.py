"""ADWS screen-color UI. Uses grim for capture and wl-copy for clipboard IO."""
from concurrent.futures import ThreadPoolExecutor
import shutil
import os
import re
import fcntl
from pathlib import Path
import subprocess
import sys
from adws_i18n import tr


def capture(rectangles):
    if not shutil.which('grim'):
        raise RuntimeError(tr('屏幕取色需要 grim。'))
    images = []
    for x, y, width, height in rectangles:
        result = subprocess.run(['grim', '-g', f'{x},{y} {width}x{height}', '-t', 'png', '-'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12, check=True)
        images.append(result.stdout)
    return images


def pixel_hex(pixels, width, height, stride, channels, x, y, view_width, view_height):
    """Map logical pointer coordinates to captured pixels, including scaled outputs."""
    if min(width, height, view_width, view_height) <= 0 or channels < 3:
        raise ValueError('Invalid pixel geometry')
    px = min(width - 1, max(0, int(x * width / view_width)))
    py = min(height - 1, max(0, int(y * height / view_height)))
    offset = py * stride + px * channels
    return '#' + ''.join(f'{value:02X}' for value in pixels[offset:offset + 3])


def copy_color(color):
    subprocess.run(['wl-copy'], input=color.encode(), stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, timeout=5, check=True)


def notify(text):
    print(text, file=sys.stderr)
    if shutil.which('notify-send'):
        subprocess.run(['notify-send', 'ADWS', text], timeout=5, check=False)


def picker():
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    gi.require_version('GtkLayerShell', '0.1')
    gi.require_version('PangoCairo', '1.0')
    from gi.repository import Gtk, Gdk, Gio, GLib, GdkPixbuf, PangoCairo, GtkLayerShell as layer
    app = Gtk.Application(application_id='org.akiacg.ADWS.ColorPicker', flags=Gio.ApplicationFlags.FLAGS_NONE)
    pool = ThreadPoolExecutor(max_workers=1)
    state = {'busy': False, 'closing': False}

    def close():
        state['closing'] = True
        for window in list(app.get_windows()):
            window.destroy()
        app.quit()

    def activate(app):
        if app.get_windows() or state['busy']:
            return
        if not layer.is_supported():
            notify(tr('屏幕取色需要支持图层窗口的 Wayland 会话。'))
            app.quit()
            return
        if not shutil.which('wl-copy'):
            notify(tr('屏幕取色需要 wl-clipboard。'))
            app.quit()
            return
        display = Gdk.Display.get_default()
        monitors = [display.get_monitor(i) for i in range(display.get_n_monitors())]
        rectangles = [(r.x, r.y, r.width, r.height) for r in (m.get_geometry() for m in monitors)]
        # Take all captures before mapping overlays; never capture our own UI.
        state['busy'] = True
        app.hold()
        future = pool.submit(capture, rectangles)

        def loaded(future):
            state['busy'] = False
            try:
                images = future.result()
                for monitor, image in zip(monitors, images):
                    loader = GdkPixbuf.PixbufLoader.new_with_type('png')
                    loader.write(image)
                    loader.close()
                    show(monitor, loader.get_pixbuf())
            except Exception as error:
                notify(tr('无法获取屏幕颜色：%s') % str(error))
                close()
            finally:
                app.release()
            return False
        future.add_done_callback(lambda f: GLib.idle_add(loaded, f))

    def show(monitor, image):
        window = Gtk.ApplicationWindow(application=app)
        window.set_decorated(False)
        layer.init_for_window(window)
        layer.set_namespace(window, 'adws-color-picker')
        layer.set_monitor(window, monitor)
        layer.set_layer(window, layer.Layer.OVERLAY)
        layer.set_keyboard_mode(window, layer.KeyboardMode.EXCLUSIVE)
        layer.set_exclusive_zone(window, 0)
        for edge in (layer.Edge.TOP, layer.Edge.BOTTOM, layer.Edge.LEFT, layer.Edge.RIGHT):
            layer.set_anchor(window, edge, True)
        area = Gtk.DrawingArea()
        area.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
        window.add(area)
        position = [0., 0.]
        pixels = image.get_pixels()

        def color(x, y):
            return pixel_hex(pixels, image.get_width(), image.get_height(), image.get_rowstride(),
                             image.get_n_channels(), x, y, area.get_allocated_width(), area.get_allocated_height())

        def draw(_, context):
            width, height = area.get_allocated_width(), area.get_allocated_height()
            context.save()
            context.scale(width / image.get_width(), height / image.get_height())
            Gdk.cairo_set_source_pixbuf(context, image, 0, 0)
            context.paint()
            context.restore()
            x, y = position
            # HUD stays inside the output and never affects the sampled snapshot.
            bx, by = max(0, min(x + 20, width - 260)), max(0, min(y + 22, height - 70))
            context.set_source_rgba(.06, .06, .08, .93)
            context.rectangle(bx, by, 260, 64)
            context.fill()
            value = color(x, y)
            context.set_source_rgb(*(int(value[i:i+2], 16)/255 for i in (1, 3, 5)))
            context.rectangle(bx + 12, by + 12, 35, 35)
            context.fill()
            layout = area.create_pango_layout(value + '\n' + tr('单击复制 · Esc / 右键取消'))
            context.set_source_rgb(1, 1, 1)
            context.move_to(bx + 57, by + 12)
            PangoCairo.show_layout(context, layout)
            return False

        def motion(_, event):
            position[:] = [event.x, event.y]
            area.queue_draw()
            return True

        def pressed(_, event):
            if event.button == 3:
                close()
            elif event.button == 1 and not state['busy']:
                state['busy'] = True
                value = color(event.x, event.y)
                future = pool.submit(copy_color, value)
                def copied(future):
                    try:
                        future.result()
                    except Exception as error:
                        notify(tr('复制颜色失败：%s') % str(error))
                    close()
                    return False
                future.add_done_callback(lambda f: GLib.idle_add(copied, f))
            return True

        area.connect('draw', draw)
        area.connect('motion-notify-event', motion)
        area.connect('button-press-event', pressed)
        window.connect('key-press-event', lambda _, event: (close() or True) if event.keyval == Gdk.KEY_Escape else False)
        window.connect('realize', lambda w: w.get_window().set_cursor(Gdk.Cursor.new_from_name(w.get_display(), 'crosshair')))
        window.show_all()

    app.connect('activate', activate)
    try:
        return app.run([])
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def launch_picker():
    """Prefer the system picker; an ADWS UI remains available without it."""
    binary=shutil.which('hyprpicker')
    if not binary:return picker()
    if not shutil.which('wl-copy'):raise RuntimeError(tr('屏幕取色需要 wl-clipboard。'))
    runtime=Path(os.environ.get('XDG_RUNTIME_DIR') or '/tmp')
    fd=os.open(runtime/('adws-color-picker-'+str(os.getuid())+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return 0
        result=subprocess.run([binary,'--autocopy','--format','hex','--no-fancy'],capture_output=True,text=True)
        if result.returncode:
            raise RuntimeError(tr('屏幕取色失败：%s') % result.stderr[-1200:])
        # Cancellation does not play a success sound or open another picker.
        if re.search(r'#[0-9a-fA-F]{6}',result.stdout):
            sound=Path('/usr/share/sounds/freedesktop/stereo/message.oga')
            if sound.is_file() and shutil.which('pw-play'):
                subprocess.Popen(['pw-play',str(sound)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        return 0


if __name__ == '__main__':
    try:
        raise SystemExit(picker() if '--builtin' in sys.argv else launch_picker())
    except (ImportError, ValueError, RuntimeError, OSError) as error:
        notify(str(error))
        raise SystemExit(1)

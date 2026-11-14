"""GTK frontend for the reviewed ADWS installer. GTK stays on the main thread."""
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

# The transaction runs in a separate interpreter attached to a VTE-controlled
# terminal. Its process groups, sudo prompts and interpreter handoff work as usual.
def run_transaction(directory):
    from adws_install_workflow import execute
    path = Path(directory)
    plan = json.loads((path / 'plan.json').read_text())
    return execute(plan, path)


if __name__ == '__main__':
    try:
        raise SystemExit(run_transaction(sys.argv[1]))
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1)


import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Vte', '2.91')
from gi.repository import Gdk, GLib, Gtk, Pango, Vte

from adws_install_ui import Back
from adws_install_progress import duration, measure, stages


def label(text, style=None):
    widget = Gtk.Label(label=text, xalign=0)
    widget.set_line_wrap(True)
    widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    widget.set_hexpand(True)
    if style:
        widget.get_style_context().add_class(style)
    return widget


class Installer:
    def __init__(self):
        self.window = Gtk.Window(title='ADWS 安装')
        self.window.set_default_size(640, 500)
        self.window.set_size_request(390, 320)
        self.window.set_icon_name('system-software-install')
        self.header = Gtk.HeaderBar(title='ADWS 安装', show_close_button=True)
        self.window.set_titlebar(self.header)
        self.window.connect('delete-event', self.close)
        self.window.connect('key-press-event', self.keypress)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=22)
        self.window.add(self.body)
        self.reply = self.escape = None
        self.pid = None
        self.installing = self.stopping = self.closed = False
        self.code = 1
        self.styles = Gtk.CssProvider()
        self.styles.load_from_data(b'.install-title { font-size: 20pt; font-weight: bold; }'
                                   b'.install-subtitle { opacity: .78; }')
        self.window.get_style_context().add_provider_for_screen(self.window.get_screen(), self.styles, 600)

    def close(self, *_):
        if self.installing:
            self.stop()
        else:
            self.closed = True
            self.window.hide()
            self.answer(KeyboardInterrupt())
        return True

    def keypress(self, _window, event):
        if event.keyval == Gdk.KEY_Escape and self.escape:
            self.escape()
            return True
        return False

    def stop(self, *_):
        if self.installing and not self.stopping:
            self.stopping = True
            if self.pid:
                self.terminate_child()
            self.primary.set_sensitive(False)
            self.primary.set_label('正在取消…')

    def terminate_child(self):
        try:
            os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def answer(self, value):
        if self.reply:
            reply, self.reply = self.reply, None
            self.escape = None
            reply(value)

    def request(self, build):
        """Wait in the planner thread for one GTK page or transaction result."""
        done = threading.Event()
        result = []
        def deliver(value):
            result.append(value)
            done.set()
        def display():
            if self.closed:
                deliver(KeyboardInterrupt())
                return False
            self.reply = deliver
            try:
                build()
            except Exception as error:
                self.answer(error)
            return False
        GLib.idle_add(display)
        done.wait()
        if isinstance(result[0], BaseException):
            raise result[0]
        return result[0]

    def page(self, title):
        for child in self.body.get_children():
            child.destroy()
        self.body.pack_start(label(title, 'install-title'), False, False, 0)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.body.pack_start(self.scroll, True, True, 0)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        self.scroll.add(self.content)
        self.body.pack_start(Gtk.Separator(), False, False, 0)
        self.footer = Gtk.Box(spacing=8)
        self.body.pack_end(self.footer, False, False, 0)

    def buttons(self, text, action, back=False):
        if back:
            self.escape = lambda: self.answer(Back())
            button = Gtk.Button.new_with_label('上一步')
            button.connect('clicked', lambda *_: self.answer(Back()))
            self.footer.pack_start(button, False, False, 0)
        self.primary = Gtk.Button.new_with_label(text)
        self.primary.get_style_context().add_class('suggested-action')
        self.primary.set_can_default(True)
        self.primary.connect('clicked', lambda *_: action())
        self.footer.pack_end(self.primary, False, False, 0)
        self.window.show_all()
        self.primary.grab_default()

    def waiting(self, message):
        def display():
            if not self.closed:
                self.page('请稍候')
                row = Gtk.Box(spacing=12)
                spinner = Gtk.Spinner()
                row.pack_start(spinner, False, False, 0)
                row.pack_start(label(message), True, True, 0)
                self.content.pack_start(row, False, False, 8)
                spinner.start()
                self.window.show_all()
            return False
        GLib.idle_add(display)

    def choose(self, title, labels, default, detail, descriptions, back):
        def build():
            self.page(title)
            if detail:
                self.content.pack_start(label(detail, 'install-subtitle'), False, False, 4)
            items = []
            for index, name in enumerate(labels):
                button = Gtk.RadioButton.new_from_widget(items[0] if items else None)
                column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, margin=5)
                column.pack_start(label(name), False, False, 0)
                if descriptions:
                    column.pack_start(label(descriptions[index], 'install-subtitle'), False, False, 0)
                button.add(column)
                self.content.pack_start(button, False, False, 0)
                items.append(button)
            items[default].set_active(True)
            def selected():
                return next(index for index, button in enumerate(items) if button.get_active())
            self.buttons('继续', lambda: self.answer(selected()), back)
            items[default].grab_focus()
        return self.request(build)

    def checklist(self, title, targets, enabled, labels, back):
        def build():
            self.page(title)
            items = {}
            for key in targets:
                item = Gtk.CheckButton.new_with_label(labels.get(key, key))
                item.set_active(key in enabled)
                self.content.pack_start(item, False, False, 2)
                items[key] = item
            self.buttons('继续', lambda: self.answer([k for k,b in items.items() if b.get_active()]), back)
        return self.request(build)

    def text_entry(self, title, initial, back):
        def build():
            self.page(title)
            entry = Gtk.Entry(text=initial, activates_default=True)
            self.content.pack_start(entry, False, False, 0)
            self.buttons('继续', lambda: self.answer(entry.get_text()), back)
            entry.grab_focus()
        return self.request(build)

    def show_text(self, title, text):
        def build():
            self.page(title)
            view = label(text)
            view.set_selectable(True)
            self.content.pack_start(view, False, False, 0)
            self.buttons('返回', lambda: self.answer(None))
            self.escape = lambda: self.answer(None)
        self.request(build)

    def execute(self, plan, directory):
        directory = Path(directory)
        def build():
            self.page('正在安装')
            self.installing = True
            self.stopping = False
            status = label('正在准备…')
            bar = Gtk.ProgressBar(show_text=True)
            self.body.pack_start(status, False, False, 0)
            self.body.reorder_child(status, 1)
            self.body.pack_start(bar, False, False, 0)
            self.body.reorder_child(bar, 2)
            terminal = Vte.Terminal()
            terminal.set_scrollback_lines(3000)
            self.scroll.remove(self.scroll.get_child())
            self.scroll.add(terminal)
            self.buttons('取消安装', self.stop)
            terminal.grab_focus()
            expected = stages(plan)
            start = changed = time.monotonic()
            previous = None
            def update():
                nonlocal previous, changed
                try:
                    journal = json.loads((directory/'progress.json').read_text())
                except FileNotFoundError:
                    journal = {}
                now = time.monotonic()
                phase = (journal.get('status'), tuple((k,v.get('status')) for k,v in journal.get('steps', {}).items()))
                if phase != previous:
                    previous, changed = phase, now
                stage, done, percent, eta = measure(expected, journal, now - changed)
                status.set_text(f'{stage}　·　已完成 {done} 步　·　已用 {duration(now-start)}')
                bar.set_text(f'估算 {percent}%　·　预计剩余 {eta}')
                bar.set_fraction(percent / 100)
                return True
            update()
            timer = GLib.timeout_add(400, update)
            def finish(code):
                GLib.source_remove(timer)
                self.pid = None
                self.installing = False
                if self.stopping:
                    code = 130
                self.stopping = False
                if code in (0, 2):
                    status.set_text('安装完成' if code == 0 else '配置已部署 · 待验收')
                    bar.set_fraction(1)
                    bar.set_text(status.get_text())
                else:
                    status.set_text('安装已取消' if code == 130 else '安装未完成')
                self.primary.set_label('查看结果' if code in (0, 2) else '继续')
                self.primary.set_sensitive(True)
                self.primary.connect('clicked', lambda *_: self.answer(code))
            terminal.connect('child-exited', lambda _, status: finish(os.waitstatus_to_exitcode(status)))
            def spawned(_term, pid, error, *_):
                if error:
                    GLib.source_remove(timer)
                    self.installing = False
                    self.answer(RuntimeError(str(error)))
                else:
                    self.pid = pid
                    if self.stopping:
                        self.terminate_child()
            terminal.spawn_async(Vte.PtyFlags.DEFAULT, None,
                                 [sys.executable, '-u', str(Path(__file__).resolve()), str(directory)],
                                 None, GLib.SpawnFlags.DEFAULT, None, None, -1, None, spawned, None)
        code = self.request(build)
        if code == 130:
            raise KeyboardInterrupt
        if code not in (0, 2):
            failure = directory/'failure.json'
            reason = json.loads(failure.read_text()).get('error') if failure.is_file() else None
            raise RuntimeError(reason or f'安装程序退出 ({code})，请查看 {directory}/install.log')
        report = directory/'result.md'
        self.show_text('安装结果', report.read_text() if report.exists() else str(directory))
        return code


def run(pages, args):
    import adws_install_ui as ui
    GLib.set_prgname('adws-setup')
    if not Gtk.init_check()[0]:
        raise RuntimeError('无法连接图形桌面；请在 Wayland/X11 会话中启动，或使用 ./install.sh。')
    app = Installer()
    ui.graphics = app
    def worker():
        try:
            app.code = pages(args)
        except KeyboardInterrupt:
            app.code = 130
        except BaseException as error:
            print(str(error), file=sys.stderr, flush=True)
            app.code = 1
        finally:
            GLib.idle_add(Gtk.main_quit)
    app.waiting('正在打开安装向导…')
    thread = threading.Thread(target=worker)
    thread.start()
    try:
        Gtk.main()
    finally:
        app.closed = True
        app.answer(KeyboardInterrupt())
        thread.join()
        app.window.destroy()
        ui.graphics = None
    return app.code

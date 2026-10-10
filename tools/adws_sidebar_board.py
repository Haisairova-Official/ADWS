"""Independent ADWS card board and daily tools, inspired by dashboard interaction patterns."""
import time
from gi.repository import Gtk, Gdk, Gio, GLib, Pango
from adws_i18n import tr
from adws_system_settings import card, label
from adws_sidebar_model import CATALOG, normalize_board, placements, move_card, normalized_tasks, timer_remaining


def icon_button(icon, title, callback):
    button = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
    button.get_style_context().add_class('sidebar-icon-button')
    button.set_tooltip_text(tr(title)); button.connect('clicked', callback)
    return button


class CardBoard(Gtk.Box):
    def __init__(self, host, factories, read, save):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.host, self.factories, self.read, self.save = host, factories, read, save
        self.model = normalize_board(read().get('board'))
        self.cards = {}; self.columns = 2; self.dragging = False; self.layout_signature=None
        toolbar = Gtk.Box(spacing=8)
        title = label('我的小组件', 'settings-section-title'); toolbar.pack_start(title, True, True, 0)
        self.add_button = Gtk.MenuButton(); self.add_button.set_label(tr('添加小组件'))
        toolbar.pack_end(self.add_button, False, False, 0); self.pack_start(toolbar, False, False, 0)
        hint = label('拖动卡片标题调整顺序；通过卡片菜单调整大小或移除。', 'dim-label')
        self.pack_start(hint, False, False, 0)
        self.grid = Gtk.Grid(column_spacing=10, row_spacing=10); self.grid.set_column_homogeneous(True)
        self.pack_start(self.grid, False, False, 0)
        self.empty = label('添加你需要的小组件。', 'dim-label'); self.empty.set_no_show_all(True)
        self.pack_start(self.empty, False, False, 20)
        self.connect("destroy", self.dispose)
        self.render()

    def dispose(self,*_):
        # Removed cards are cached outside the GTK child tree: destroy them too.
        for child in self.cards.values():child.destroy()
        self.cards.clear()
        popup=self.add_button.get_popup()
        if popup:popup.destroy()

    def persist(self):
        settings = self.read(); settings['board'] = self.model; self.save(settings)

    def menu(self, key):
        menu = Gtk.Menu()
        def action(title, fn):
            item = Gtk.MenuItem(label=tr(title)); item.connect('activate', lambda *_: fn()); menu.append(item)
        action('紧凑卡片', lambda: self.resize_card(key, 1))
        action('宽卡片', lambda: self.resize_card(key, 2))
        action('向前移动', lambda: self.step(key, -1))
        action('向后移动', lambda: self.step(key, 1))
        menu.append(Gtk.SeparatorMenuItem())
        action('移除小组件', lambda: self.remove_card(key))
        menu.show_all(); return menu

    def create_card(self, key):
        box = self.factories[key]()
        # Content factories use the shared card helper; replace only its title.
        first = box.get_children()[0]
        if isinstance(first, Gtk.Label): box.remove(first)
        box.get_style_context().add_class('sidebar-board-card'); box.set_valign(Gtk.Align.START)
        header = Gtk.Box(spacing=8)
        handle = Gtk.EventBox(); handle.set_visible_window(False)
        title = Gtk.Box(spacing=7)
        title.pack_start(Gtk.Image.new_from_icon_name(CATALOG[key][1], Gtk.IconSize.MENU), False, False, 0)
        text = Gtk.Label(label=tr(CATALOG[key][0]), xalign=0)
        text.set_ellipsize(Pango.EllipsizeMode.END); text.get_style_context().add_class('settings-section-title')
        title.pack_start(text, True, True, 0); handle.add(title)
        handle.set_tooltip_text(tr('拖动调整顺序'))
        header.pack_start(handle, True, True, 0)
        menu = Gtk.MenuButton(); menu.set_image(Gtk.Image.new_from_icon_name('view-more-symbolic', Gtk.IconSize.MENU))
        menu.get_style_context().add_class('sidebar-icon-button'); menu.set_tooltip_text(tr('小组件选项'))
        menu.set_popup(self.menu(key)); header.pack_end(menu, False, False, 0)
        box.pack_start(header, False, False, 0); box.reorder_child(header, 0)
        target = [Gtk.TargetEntry.new('application/x-adws-sidebar-card', Gtk.TargetFlags.SAME_APP, 0)]
        handle.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, target, Gdk.DragAction.MOVE)
        handle.connect('drag-data-get', lambda _, ctx, data, info, stamp: data.set(data.get_target(), 8, key.encode()))
        handle.connect('drag-begin', self.drag_begin)
        handle.connect('drag-end', self.drag_end)
        box.drag_dest_set(Gtk.DestDefaults.ALL, target, Gdk.DragAction.MOVE)
        def drop(_, ctx, x, y, data, info, stamp):
            try: source = data.get_data().decode()
            except (UnicodeError, AttributeError): source = ''
            valid = source in self.model['order']
            Gtk.drag_finish(ctx, valid, False, stamp)
            if valid:
                self.model['order'] = move_card(self.model, source, key); self.persist()
                GLib.idle_add(self.render)
        box.connect('drag-data-received', drop)
        return box

    def drag_begin(self, *_):
        self.dragging = True; self.host.interaction_depth += 1

    def drag_end(self, *_):
        self.dragging = False; self.host.interaction_depth = max(0, self.host.interaction_depth-1)
        self.host.focus_out()

    def render(self):
        if self.host.closed: return False
        if not self.cards and self.host.stack.get_visible_child_name() != 'widgets': return False
        placement=tuple(placements(self.model,self.columns))
        if placement==self.layout_signature:return False
        self.layout_signature=placement
        for child in self.grid.get_children(): self.grid.remove(child)
        for key, col, row, span in placement:
            if key not in self.cards: self.cards[key] = self.create_card(key)
            self.grid.attach(self.cards[key], col, row, span, 1)
        menu = Gtk.Menu()
        for key, (title, _, _) in CATALOG.items():
            item = Gtk.MenuItem(label=tr(title)); item.set_sensitive(key not in self.model['order'])
            item.connect('activate', lambda _, key=key: self.add_card(key)); menu.append(item)
        previous=self.add_button.get_popup()
        self.add_button.set_popup(menu)
        if previous:previous.destroy()
        menu.show_all()
        self.grid.show_all(); self.empty.set_visible(not self.model['order'])
        return False

    def add_card(self, key):
        if key not in self.model['order']: self.model['order'].append(key)
        self.persist(); self.render()

    def remove_card(self, key):
        if key in self.model['order']: self.model['order'].remove(key)
        self.persist(); self.render()

    def resize_card(self, key, size):
        self.model['sizes'][key] = size; self.persist(); self.render()

    def step(self, key, delta):
        order = self.model['order']; old = order.index(key); new = max(0, min(len(order)-1, old+delta))
        order.insert(new, order.pop(old)); self.persist(); self.render()

    def set_columns(self, columns):
        if columns != self.columns: self.columns = columns; self.render()


class TodoCard:
    def __init__(self, read, save):
        self.read, self.save = read, save
        self.box = card('待办'); self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.box.pack_start(self.list, False, False, 0)
        row = Gtk.Box(spacing=6); self.entry = Gtk.Entry(); self.entry.set_placeholder_text(tr('添加待办事项'))
        self.entry.set_max_length(256); self.entry.connect('activate', self.add)
        row.pack_start(self.entry, True, True, 0)
        row.pack_end(icon_button('list-add-symbolic', '添加', self.add), False, False, 0)
        self.box.pack_start(row, False, False, 0); self.render()

    def render(self):
        for child in self.list.get_children(): child.destroy()
        tasks = normalized_tasks(self.read().get('tasks'))
        if not tasks: self.list.pack_start(label('没有待办，享受今天。', 'dim-label'), False, False, 10)
        for index, task in enumerate(tasks):
            row = Gtk.Box(spacing=6)
            check = Gtk.CheckButton(); check.set_active(task['done'])
            text = label(task['text']); text.set_max_width_chars(30)
            if task['done']: text.get_style_context().add_class('dim-label')
            check.add(text); check.connect('toggled', lambda button, i=index: self.edit(i, button.get_active()))
            row.pack_start(check, True, True, 0)
            row.pack_end(icon_button('edit-delete-symbolic', '删除', lambda _, i=index: self.edit(i, None)), False, False, 0)
            self.list.pack_start(row, False, False, 0)
        self.list.show_all()

    def edit(self, index, done):
        settings = self.read(); tasks = normalized_tasks(settings.get('tasks'))
        if index >= len(tasks): return
        if done is None: tasks.pop(index)
        else: tasks[index]['done'] = done
        settings['tasks'] = tasks; self.save(settings); self.render()

    def add(self, *_):
        text = self.entry.get_text().strip()
        if not text: return
        settings = self.read(); tasks = normalized_tasks(settings.get('tasks'))
        if len(tasks) >= 100: return
        tasks.append({'text':text,'done':False}); settings['tasks'] = tasks; self.save(settings)
        self.entry.set_text(''); self.render()


class TimerCard:
    def __init__(self, host, read, save):
        self.host, self.read, self.save = host, read, save
        self.box = card('计时器'); self.display = label('', 'sidebar-timer')
        self.display.set_xalign(.5); self.box.pack_start(self.display, False, False, 0)
        self.minutes = Gtk.SpinButton.new_with_range(1, 1440, 1); self.minutes.set_value(25)
        self.minutes.set_tooltip_text(tr('分钟'))
        row = Gtk.Box(spacing=8); row.pack_start(self.minutes, True, True, 0)
        self.toggle = icon_button('media-playback-start-symbolic', '开始 / 暂停', self.toggle_timer)
        row.pack_start(self.toggle, False, False, 0)
        row.pack_start(icon_button('view-refresh-symbolic', '重置', self.reset), False, False, 0)
        self.box.pack_start(row, False, False, 0)
        self.caption = label('关闭侧边栏后继续计时，结束时发送通知。', 'dim-label')
        self.box.pack_start(self.caption, False, False, 0)
        self.tick(); self.source = GLib.timeout_add_seconds(1, self.tick)
        host.connect('destroy', self.close)

    def state(self):
        state = self.read().get('timer', {})
        return state if isinstance(state, dict) else {}

    def store(self, state):
        settings = self.read(); settings['timer'] = state; self.save(settings)

    def toggle_timer(self, *_):
        state = self.state(); remaining = timer_remaining(state)
        if state.get('deadline'): self.store({'remaining': remaining})
        else: self.store({'deadline':time.time()+(remaining if state and remaining else self.minutes.get_value_as_int()*60)})
        self.tick()

    def reset(self, *_):
        self.store({'remaining':self.minutes.get_value_as_int()*60}); self.tick()

    def tick(self):
        if self.host.closed: return False
        state = self.state(); remaining = timer_remaining(state or {'remaining':self.minutes.get_value_as_int()*60})
        self.display.set_text(f'{remaining//60:02d}:{remaining%60:02d}')
        running = bool(state.get('deadline'))
        self.minutes.set_sensitive(not running)
        self.toggle.set_image(Gtk.Image.new_from_icon_name('media-playback-pause-symbolic' if running else 'media-playback-start-symbolic', Gtk.IconSize.BUTTON))
        if running and remaining == 0:
            self.store({'remaining': 0})
            self.caption.set_text(tr('计时结束'))
            notification = Gio.Notification.new(tr('计时结束')); notification.set_body(tr('侧边栏计时器已完成。'))
            app = self.host.get_application()
            if app and app.get_is_registered(): app.send_notification('sidebar-timer', notification)
        return True

    def close(self, *_):
        if self.source: GLib.source_remove(self.source); self.source = 0

"""One searchable settings window; existing controllers keep owning their data."""
from dataclasses import dataclass
import json
import os
import platform
from pathlib import Path
import threading
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango
from adws_i18n import tr as tr


@dataclass(frozen=True)
class Page:
    key: str
    title: str
    description: str
    icon: str
    group: str
    keywords: str


PAGES = (
    Page('home', '概览', '从常用设置开始，打造你的工作空间。', 'preferences-system-symbolic', '概览', 'overview home 常用 首页'),
    Page('desktop', '桌面与文字', '调整桌面图标、字体与网格。', 'video-display-symbolic', '工作空间', 'desktop appearance font icons 外观 字体 图标 网格'),
    Page('taskbar', '任务栏外观', '位置、分体、材质、配色与动效。', 'view-grid-symbolic', '工作空间', 'taskbar panel color animation radius split 颜色 动效 圆角 尖角 高度'),
    Page('waybar', 'Waybar 配置', '管理独立 Waybar 的尺寸、间距与组件排列。', 'view-top-bar-symbolic', '工作空间', 'waybar top panel 顶部栏 配置'),
    Page('layout', '组件与插件', '排列组件，管理插件和时钟。', 'application-x-addon-symbolic', '工作空间', 'layout plugin component clock lyrics 布局 插件 组件 时钟 歌词'),
    Page('start', '开始菜单', '启动器、按钮图样、菜单主题与键位。', 'view-app-grid-symbolic', '工作空间', 'start launcher keyboard rofi fuzzel 开始 启动器 快捷键'),
    Page('wallpaper', '壁纸', '选择图片与壁纸管理工具。', 'preferences-desktop-wallpaper-symbolic', '个性化', 'wallpaper background awww swww swaybg 壁纸 背景'),
    Page('sidebar', '侧边栏', '信息、小工具与天气。', 'view-list-symbolic', '工作空间', 'sidebar widgets weather 侧边栏 小工具 天气'),
    Page('apps', '默认应用', '选择打开网页、文件夹与文本的应用。', 'application-x-executable-symbolic', '个性化', 'default browser files editor 默认 浏览器 文件管理器 编辑器'),
    Page('components', '会话与组件', '管理桌面、任务栏的运行与登录自启。', 'system-run-symbolic', '系统', 'session services autostart restart 组件 自启 重启 会话'),
    Page('about', '更新与配置', '检查更新、导入导出配置或重新运行向导。', 'help-about-symbolic', '系统', 'about update beta import export setup 关于 更新 导入 导出 向导'),
)


def matches(page, query):
    terms = query.casefold().split()
    haystack = ' '.join((page.title, tr(page.title), page.description, tr(page.description), page.keywords)).casefold()
    return all(term in haystack for term in terms)


def label(text, style=None):
    item = Gtk.Label(label=tr(text), xalign=0)
    item.set_line_wrap(True)
    item.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if style:
        item.get_style_context().add_class(style)
    return item


def card(title, description=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
    box.set_border_width(0)
    box.get_style_context().add_class('settings-card')
    box.pack_start(label(title, 'settings-section-title'), False, False, 0)
    if description:
        box.pack_start(label(description, 'dim-label'), False, False, 0)
    return box


def distribution_logo(release, size=80):
    distro_id = release.get('ID', '')
    aliases = {'arch': 'archlinux', 'opensuse-tumbleweed': 'opensuse',
               'opensuse-leap': 'opensuse'}
    identity = aliases.get(distro_id, distro_id)
    names = [release.get('LOGO', ''), f'distributor-logo-{identity}',
             f'{identity}-logo', f'distributor-logo-{distro_id}', distro_id]
    theme = Gtk.IconTheme.get_default()
    for name in filter(None, names):
        if theme.has_icon(name):
            image = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.DIALOG)
            image.set_pixel_size(size)
            return image
        # Some distributions install their logo only in pixmaps; icon themes
        # do not consistently include that directory in their search path.
        if Path(name).name != name:
            continue
        for extension in ('.svg', '.png', '.xpm'):
            filename = Path('/usr/share/pixmaps') / (name + extension)
            if filename.is_file():
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(filename), size, size, True)
                    return Gtk.Image.new_from_pixbuf(pixbuf)
                except GLib.Error:
                    continue
    image = Gtk.Image.new_from_icon_name('distributor-logo' if theme.has_icon('distributor-logo') else 'computer', Gtk.IconSize.DIALOG)
    image.set_pixel_size(size)
    return image


def run_settings(config, tab=None, window_factory=None, start_instance=None):
    """Route repeated launches to the existing window without losing its edits."""
    app = Gio.Application(application_id='org.AkiACGCommunity.ADWS.Settings',
                          flags=Gio.ApplicationFlags.FLAGS_NONE)
    window = None
    factory = window_factory or SystemSettingsWindow

    def open_page(_, parameter):
        nonlocal window
        target = parameter.get_string()
        if window is None:
            window = factory(config, tab=target or None)
            if window_factory is None:
                try:
                    from adws_native_auth import start
                    window.authentication_agent=start(window)
                except (ImportError,ValueError):
                    window.authentication_agent=None
        elif target and target in window.rows:
            window.show_page(target)
        window.present()

    action = Gio.SimpleAction.new('open-page', GLib.VariantType.new('s'))
    action.connect('activate', open_page)
    app.add_action(action)
    def open_start(_, parameter):
        open_page(_, GLib.Variant('s', 'start'))
        window.select_start_instance(parameter.get_string())
    start_action = Gio.SimpleAction.new('open-start', GLib.VariantType.new('s'))
    start_action.connect('activate', open_start)
    app.add_action(start_action)
    # Use the session bus, whose ownership is released when the process exits.
    # Without a session bus Gio falls back to an independent local instance.
    app.register(None)
    if start_instance and app.has_action('open-start'):
        app.activate_action('open-start', GLib.Variant('s', start_instance))
    else:
        # A settings window opened before this update still understands open-page.
        app.activate_action('open-page', GLib.Variant('s', 'start' if start_instance else tab or ''))
    if app.get_is_remote():
        connection = app.get_dbus_connection()
        if connection:
            connection.flush_sync(None)
    else:
        Gtk.main()
    return 0


class SystemSettingsWindow(Gtk.Window):
    def __init__(self, config, tab=None):
        super().__init__(title=tr('ADWS 系统设置'))
        self.config = config
        from adws_display import detect_session
        self.display_session = detect_session()
        self.page_definitions = list(PAGES)
        if self.display_session:
            self.page_definitions.insert(7, Page('displays', '显示器', '分辨率、刷新率、缩放、旋转与显示器位置。', 'video-display-symbolic', '设备与连接', 'display monitor resolution refresh scale rotation niri hyprland 显示器 分辨率 刷新率 缩放 旋转'))
        from adws_system_pages import available_pages
        self.system_page_keys = set()
        for definition in available_pages():
            self.page_definitions.append(Page(*definition))
            self.system_page_keys.add(definition[0])
        self.page_definitions.append(Page('input', '输入与快捷键', '键盘、输入法与桌面快捷键。', 'input-keyboard-symbolic', '设备与连接', 'input keyboard mouse shortcuts 输入 键盘 鼠标 快捷键'))
        group_order = {'概览':0, '工作空间':1, '个性化':2, '设备与连接':3, '系统':4}
        self.page_definitions.sort(key=lambda page: (group_order.get(page.group, 3), page.key == 'about'))
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_default_size(1140, 820)
        self.set_size_request(880, 620)
        self.set_role('adws-system-settings')
        self.get_style_context().add_class('adws-system-settings')
        self.pages, self.rows, self.owners = {}, {}, {}
        self.service_pages = {}
        self.dirty = set()
        self.busy = False
        self.closed = False
        self.loading = False
        self.current = 'home'
        self.app_dirty = set()
        self.install_style()
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)
        header = Gtk.HeaderBar(title=tr('ADWS 系统设置'), show_close_button=True)
        header.get_style_context().add_class('settings-titlebar')
        self.set_titlebar(header)
        body = Gtk.Box(spacing=0)
        outer.pack_start(body, True, True, 0)
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.sidebar.set_size_request(264, -1)
        self.sidebar.set_border_width(16)
        self.sidebar.get_style_context().add_class('settings-sidebar')
        body.pack_start(self.sidebar, False, False, 0)
        from adws_account_header import AccountHeader
        self.account_header = AccountHeader(lambda: self.show_page('region'))
        self.account_header.set_margin_bottom(10)
        self.sidebar.pack_start(self.account_header, False, False, 0)
        self.search = Gtk.SearchEntry(placeholder_text=tr('搜索设置'))
        self.search.connect('search-changed', self.filter_navigation)
        self.search.connect('activate', self.activate_first_result)
        self.sidebar.pack_start(self.search, False, False, 0)
        nav_scroll = Gtk.ScrolledWindow()
        nav_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.navigation = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.navigation.set_header_func(self.nav_header)
        self.navigation.set_filter_func(lambda row: matches(row.page, self.search.get_text()))
        self.navigation.connect('row-selected', self.select_row)
        nav_scroll.add(self.navigation)
        self.sidebar.pack_start(nav_scroll, True, True, 0)
        for page in self.page_definitions:
            row = Gtk.ListBoxRow()
            row.page = page
            content = Gtk.Box(spacing=12)
            content.set_border_width(9)
            content.pack_start(Gtk.Image.new_from_icon_name(page.icon, Gtk.IconSize.MENU), False, False, 0)
            name = Gtk.Label(label=tr(page.title), xalign=0)
            name.set_tooltip_text(tr(page.title))
            name.set_ellipsize(Pango.EllipsizeMode.END)
            content.pack_start(name, True, True, 0)
            row.add(content)
            self.navigation.add(row)
            self.rows[page.key] = row
        self.empty_search = label('没有匹配的设置。', 'dim-label')
        self.empty_search.set_no_show_all(True)
        self.sidebar.pack_start(self.empty_search, False, False, 0)
        version = config.load_json(config.PROJECT_ROOT / 'build-info.json').get('display_version', '')
        self.sidebar.pack_end(label('ADWS ' + version, 'dim-label'), False, False, 0)
        detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        detail.get_style_context().add_class('settings-detail')
        body.pack_start(detail, True, True, 0)
        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        heading.set_border_width(28)
        self.breadcrumb = label('', 'settings-breadcrumb')
        heading.pack_start(self.breadcrumb, False, False, 0)
        self.page_title = label('', 'settings-page-title')
        self.page_description = label('', 'dim-label')
        heading.pack_start(self.page_title, False, False, 0)
        heading.pack_start(self.page_description, False, False, 0)
        detail.pack_start(heading, False, False, 0)
        self.stack = Gtk.Stack(hhomogeneous=False, vhomogeneous=False)
        from adws_layout import load_layout
        from adws_panel_options import validate
        options = validate(load_layout().get('options', {}))
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE if options['tab_animations'] else Gtk.StackTransitionType.NONE)
        self.stack.set_transition_duration(options['animation_duration'])
        detail.pack_start(self.stack, True, True, 0)
        footer = Gtk.Box(spacing=12)
        footer.get_style_context().add_class('settings-footer')
        self.status = label('所有设置均已保存。', 'dim-label')
        footer.pack_start(self.status, True, True, 0)
        self.apply_button = Gtk.Button(label=tr('应用更改'))
        self.apply_button.get_style_context().add_class('suggested-action')
        self.apply_button.connect('clicked', self.apply_changes)
        footer.pack_end(self.apply_button, False, False, 0)
        self.restore_button = Gtk.Button(label=tr('恢复默认外观'))
        self.restore_button.set_no_show_all(True)
        self.restore_button.connect('clicked', lambda *_: self.restore_appearance())
        footer.pack_end(self.restore_button, False, False, 0)
        outer.pack_end(footer, False, False, 0)
        self.connect('delete-event', self.request_close)
        self.connect('destroy', self.cleanup)
        self.connect('key-press-event', self.key_pressed)
        self.show_page(tab if tab in self.rows else 'home')
        self.show_all()
        self.empty_search.hide()
        self.update_footer()

    def install_style(self):
        from adws_settings_style import SettingsStyle
        self.visual_style = SettingsStyle(self)

    def nav_header(self, row, previous):
        if row.page.key != 'home' and (previous is None or previous.page.group != row.page.group):
            row.set_header(label(row.page.group, 'settings-group'))
        else:
            row.set_header(None)

    def filter_navigation(self, *_):
        self.navigation.invalidate_filter()
        self.navigation.invalidate_headers()
        visible = any(matches(p, self.search.get_text()) for p in self.page_definitions)
        self.empty_search.set_visible(not visible)

    def activate_first_result(self, *_):
        for page in self.page_definitions:
            if matches(page, self.search.get_text()):
                self.show_page(page.key)
                break

    def select_row(self, _, row):
        if row:
            self.show_page(row.page.key)

    def scroll(self, widget):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_overlay_scrolling(False)
        widget.set_margin_start(28)
        widget.set_margin_end(28)
        widget.set_margin_bottom(20)
        scroll.add(widget)
        self.config.keep_scroll_for_page(widget, scroll)
        return scroll

    def select_start_instance(self, instance):
        self.show_page('start')
        editor = self.owner('taskbar').layout_editor
        choices = editor.start_instance_choice
        if any(row[0] == instance for row in choices.get_model()):
            choices.set_active_id(instance)

    def owner(self, key):
        if key not in self.owners:
            owner = self.config.ConfigWindow(embedded=True) if key == 'desktop' else self.config.TaskbarSettingsWindow(embedded=True)
            owner.settings_host = self
            owner.set_transient_for(self)
            self.owners[key] = owner
            if key == 'taskbar':
                owner.layout_editor.window = self
                owner.layout_editor.on_start_settings = lambda: self.show_page('start')
            else:
                owner.action_open_taskbar_style = lambda *_: self.show_page('taskbar')
                owner.action_open_layout = lambda *_: self.show_page('layout')
        return self.owners[key]

    def detach(self, widget):
        parent = widget.get_parent()
        if parent:
            parent.remove(widget)
        return widget

    def build_page(self, key):
        if key in self.system_page_keys:
            from adws_system_pages import build_page
            content = build_page(key, self)
            self.service_pages[key] = content.system_service_page
            return self.scroll(content)
        if key == 'input':
            from adws_input_settings import InputSettingsPage
            self.input_page = InputSettingsPage(self)
            return self.scroll(self.input_page)
        if key == 'home':
            return self.scroll(self.build_home())
        if key in ('desktop', 'components', 'about'):
            owner = self.owner('desktop')
            index = {'desktop': 0, 'components': 1, 'about': 2}[key]
            widget = self.detach(owner.notebook.stack.get_child_by_name(str(index)))
            self.group_sections(widget, key)
            if key == 'components':
                from adws_session_apps import SessionApps
                widget.pack_start(SessionApps(self), False, False, 0)
            if key == 'desktop':
                self.track(widget, 'desktop')
            return self.scroll(widget)
        if key in ('taskbar', 'layout', 'start'):
            owner = self.owner('taskbar')
            index = {'taskbar': 0, 'layout': 1, 'start': 2}[key]
            widget = self.detach(owner.notebook.stack.get_child_by_name(str(index)))
            if key == 'taskbar':
                self.group_taskbar_controls(widget, owner)
            elif key == 'start':
                viewport = widget.get_child()
                content = viewport.get_child() if isinstance(viewport, Gtk.Viewport) else viewport
                self.group_sections(content, key)
            self.track(widget, 'taskbar')
            if not getattr(owner, '_layout_watched', False):
                owner._layout_watched = True
                owner.layout_editor.on_changed = lambda: self.mark_dirty('taskbar')
                owner.layout_editor.list_box.connect('add', lambda _, child: GLib.idle_add(self.prepare_dynamic_row, child))
            if isinstance(widget, Gtk.ScrolledWindow):
                widget.set_overlay_scrolling(False)
                content = widget.get_child()
                if isinstance(content, Gtk.Viewport):
                    content = content.get_child()
                content.set_margin_start(28)
                content.set_margin_end(28)
                content.set_margin_bottom(20)
            return widget
        if key == 'displays':
            from adws_display_gui import DisplaySettingsPage
            self.display_page = DisplaySettingsPage(self)
            return self.scroll(self.display_page)
        if key == 'waybar':
            from adws_waybar_gui import WaybarPage
            self.waybar_page = WaybarPage(self)
            return self.scroll(self.waybar_page)
        if key == 'sidebar':
            from adws_sidebar import build_settings
            return self.scroll(build_settings(self))
        if key == 'apps':
            return self.scroll(self.build_apps())
        if key == 'wallpaper':
            return self.scroll(self.build_wallpaper())
        raise ValueError(key)

    def prepare_dynamic_row(self, child):
        if self.closed or child.get_parent() is None:
            return False
        from adws_settings_widgets import enhance_choices
        enhance_choices(child, translate=tr)
        self.track(child, 'taskbar')
        return False

    def show_page(self, key):
        if key == self.current and key in self.pages:
            return
        self.loading = True
        try:
            if key not in self.pages:
                widget = self.build_page(key)
                self.pages[key] = widget
                self.stack.add_named(widget, key)
                from adws_settings_widgets import enhance_choices
                enhance_choices(widget, translate=tr)
                widget.show_all()
            self.current = key
            page = next(p for p in self.page_definitions if p.key == key)
            self.breadcrumb.set_text('ADWS  /  ' + tr(page.group))
            self.page_title.set_text(tr(page.title))
            self.page_description.set_text(tr(page.description))
            self.stack.set_visible_child_name(key)
            self.restore_button.set_visible(key == 'taskbar')
            if self.navigation.get_selected_row() != self.rows[key]:
                self.navigation.select_row(self.rows[key])
        finally:
            self.loading = False

    def build_home(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        hero = Gtk.Box(spacing=24)
        hero.get_style_context().add_class('settings-hero')
        try:
            release = platform.freedesktop_os_release()
        except OSError:
            release = {}
        distro_name = release.get('PRETTY_NAME') or release.get('NAME') or 'Linux'
        logo = distribution_logo(release)
        logo.set_valign(Gtk.Align.CENTER)
        logo.set_tooltip_text(distro_name)
        hero.pack_start(logo, False, False, 0)
        information = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        information.pack_start(label(distro_name, 'settings-hero-title'), False, False, 0)
        information.pack_start(label('Linux ' + platform.release(), 'settings-caption'), False, False, 0)
        desktop = self.display_session or os.environ.get('XDG_CURRENT_DESKTOP') or 'Wayland'
        desktop_names = {'niri':'Niri', 'hyprland':'Hyprland', 'kde':'KDE Plasma', 'gnome':'GNOME', 'xfce':'Xfce'}
        desktop = ' / '.join(desktop_names.get(part.casefold(), part) for part in desktop.split(':') if part)
        version = self.config.load_json(self.config.PROJECT_ROOT / 'build-info.json').get('display_version', '')
        information.pack_start(label(desktop + ' · ADWS ' + version, 'settings-caption'), False, False, 0)
        hero.pack_start(information, True, True, 0)
        box.pack_start(hero, False, False, 0)
        box.pack_start(label('常用设置', 'settings-section-title'), False, False, 0)
        keys = ['taskbar', 'desktop', 'displays', 'wallpaper', 'sound', 'network', 'input', 'about']
        keys = [key for key in keys if key in self.rows]
        grid = Gtk.Grid(column_spacing=14, row_spacing=14, column_homogeneous=True)
        for i, key in enumerate(keys):
            page = next(p for p in self.page_definitions if p.key == key)
            button = Gtk.Button()
            button.get_style_context().add_class('settings-shortcut')
            content = Gtk.Box(spacing=16)
            image = Gtk.Image.new_from_icon_name(page.icon, Gtk.IconSize.DIALOG)
            content.pack_start(image, False, False, 0)
            captions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            captions.pack_start(label(page.title, 'settings-section-title'), False, False, 0)
            description = label(page.description, 'dim-label')
            description.set_max_width_chars(30)
            captions.pack_start(description, False, False, 0)
            content.pack_start(captions, True, True, 0)
            button.add(content)
            button.connect('clicked', lambda _, key=key: self.show_page(key))
            grid.attach(button, i % 2, i // 2, 1, 1)
        box.pack_start(grid, False, False, 0)
        return box

    def group_sections(self, content, key):
        if not isinstance(content, Gtk.Box):
            return
        children = list(content.get_children())
        if not children:
            return
        for child in children:
            content.remove(child)
        content.set_border_width(0)
        for setter in (content.set_margin_start, content.set_margin_end, content.set_margin_top, content.set_margin_bottom):
            setter(0)
        content.set_spacing(18)
        section = None
        default = {'desktop':'桌面图标', 'components':'运行与自启', 'about':'ADWS', 'start':'开始按钮'}[key]
        for child in children:
            if child.get_no_show_all():
                content.pack_start(child, False, False, 0)
                continue
            is_title = isinstance(child, Gtk.Label) and child.get_style_context().has_class('title')
            if isinstance(child, Gtk.Separator) or is_title:
                section = None
                if is_title:
                    section = card(child.get_text())
                    content.pack_start(section, False, False, 0)
                continue
            if section is None:
                section = card(default if not content.get_children() else '更多选项')
                content.pack_start(section, False, False, 0)
            section.pack_start(child, False, False, 0)

    def track(self, widget, group):
        from adws_settings_widgets import SelectionButton
        if isinstance(widget, SelectionButton):
            return
        if getattr(widget, '_adws_tracked', False):
            return
        widget._adws_tracked = True
        signal = None
        if isinstance(widget, (Gtk.SpinButton, Gtk.Range)):
            signal = 'value-changed'
        elif isinstance(widget, (Gtk.Entry, Gtk.ComboBox)):
            signal = 'changed'
        elif isinstance(widget, Gtk.ToggleButton):
            signal = 'toggled'
        elif isinstance(widget, Gtk.ColorButton):
            signal = 'color-set'
        if signal:
            widget.connect(signal, lambda *_: self.mark_dirty(group))
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                self.track(child, group)

    def mark_dirty(self, group):
        if not self.loading and not self.closed:
            self.dirty.add(group)
            self.update_footer()

    def update_footer(self):
        self.apply_button.set_sensitive(bool(self.dirty) and not self.busy)
        self.status.set_text(tr('正在应用更改…') if self.busy else tr('有尚未应用的修改。') if self.dirty else tr('所有设置均已保存。'))

    def restore_appearance(self):
        self.owners['taskbar'].apply_restore()
        self.mark_dirty('taskbar')

    def app_changed(self, mime):
        if not self.loading:
            self.app_dirty.add(mime)
            self.mark_dirty('apps')

    def group_taskbar_controls(self, scroll, owner):
        viewport = scroll.get_child()
        box = viewport.get_child() if isinstance(viewport, Gtk.Viewport) else viewport
        groups = {name: card(name) for name in ('布局与位置', '窗口与预览', '动效', '配色与材质', '文字与圆角')}
        assignment = {}
        def assign(widget, section):
            while widget.get_parent() is not None and widget.get_parent() != box:
                widget = widget.get_parent()
            assignment[widget] = section
        for control in (owner.position, owner.split_panel, owner.panel_choices['split_center_corners'], owner.panel_choices['panel_mode'], owner.thickness):
            assign(control, '布局与位置')
        for control in (owner.window_rows, owner.panel_choices['termination_mode'], owner.panel_toggles['group_windows'], owner.panel_toggles['window_peek']):
            assign(control, '窗口与预览')
        for key in ('window_animations', 'tab_animations'):
            assign(owner.panel_toggles[key], '动效')
        assign(owner.animation_duration, '动效')
        assign(owner.panel_choices['panel_material'], '配色与材质')
        for picker, follow in owner.panel_colors.values():
            assign(picker, '配色与材质')
            assign(follow, '配色与材质')
        for control in (owner.theme_background, owner.color_button):
            assign(control, '配色与材质')
        for child in list(box.get_children()):
            box.remove(child)
            if isinstance(child, Gtk.Separator):
                continue
            if isinstance(child, Gtk.Label) and child.get_style_context().has_class('title'):
                continue
            section = assignment.get(child, '文字与圆角')
            if isinstance(child, Gtk.Label) and child.get_text() == tr('透明材质的背景模糊由窗口管理器提供。'):
                section = '配色与材质'
            groups[section].pack_start(child, False, False, 0)
        box.set_border_width(0)
        box.set_spacing(18)
        for group in groups.values():
            box.pack_start(group, False, False, 0)

    def build_apps(self):
        box = card('默认应用', '应用更改后生效。只列出系统中已安装的应用。')
        self.app_choices = {}
        from adws_settings_widgets import ApplicationChoice
        applications = Gio.AppInfo.get_all()
        for title, mime in [('网页浏览器', 'x-scheme-handler/https'), ('文件管理器', 'inode/directory'), ('文本编辑器', 'text/plain'), ('图片查看器', 'image/png'), ('音乐播放器', 'audio/mpeg'), ('视频播放器', 'video/mp4'), ('PDF 阅读器', 'application/pdf')]:
            chooser = ApplicationChoice(mime, applications=applications, translate=tr)
            row = self.config.row_widget(tr(title), chooser)
            box.pack_start(row, False, False, 0)
            chooser.connect('changed', lambda *_, mime=mime: self.app_changed(mime))
            self.app_choices[mime] = chooser
        from desktop_layer.terminal import choices, current
        self.terminal_choice = Gtk.ComboBoxText()
        self.terminal_choice.append('__system__', tr('跟随系统默认终端'))
        terminals = choices(applications)
        for app in terminals: self.terminal_choice.append(app.get_id(), app.get_display_name())
        self.terminal_choice.set_active_id(current() or '__system__')
        if self.terminal_choice.get_active() < 0: self.terminal_choice.set_active(0)
        box.pack_start(self.config.row_widget(tr('默认终端'), self.terminal_choice), False, False, 0)
        self.terminal_choice.connect('changed', lambda *_: self.app_changed('terminal'))
        section = card('终端外观预设', '保存当前 Kitty 的字体、透明度、内边距与配色，并提供 Alacritty 同款。部署前自动备份，缺少字体时使用等宽字体。')
        line = Gtk.Box(spacing=12)
        for terminal in ('kitty', 'alacritty'):
            button = Gtk.Button(label=tr('部署 %s 预设') % ('Kitty' if terminal == 'kitty' else 'Alacritty'))
            button.connect('clicked', lambda _, name=terminal: self.deploy_terminal_preset(name))
            line.pack_start(button, False, False, 0)
        section.pack_start(line, False, False, 0)
        box.pack_start(section, False, False, 0)
        from adws_app_scaling import build_card
        box.pack_start(build_card(self), False, False, 0)
        return box

    def deploy_terminal_preset(self, name):
        if not self.confirm('部署终端外观预设？', '将备份并替换所选终端配置；不会更改默认终端。'):
            return
        from adws_terminal_presets import deploy
        result = {}
        def job(): result.update(deploy(name))
        def done():
            dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.CLOSE, text=tr('终端预设已部署。'))
            dialog.format_secondary_text(tr('重新打开终端即可使用。备份：%s') % result['backup'])
            dialog.run();dialog.destroy()
        self.run_worker(job, done)

    def build_wallpaper(self):
        from adws_wallpaper import config_path, installed, ENGINES
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        section = card('壁纸', '选择已安装的壁纸工具；应用前会确认需要替换的壁纸服务。')
        saved = self.config.load_json(config_path())
        self.wallpaper_engine = Gtk.ComboBoxText()
        for engine in installed():
            if engine in ENGINES:
                self.wallpaper_engine.append(engine, engine + (' (' + tr('推荐') + ')' if engine == 'awww' else ''))
        self.wallpaper_engine.set_active_id(saved.get('engine', 'awww'))
        if self.wallpaper_engine.get_active() < 0:
            self.wallpaper_engine.set_active(0)
        section.pack_start(self.config.row_widget(tr('壁纸管理工具'), self.wallpaper_engine), False, False, 0)
        from adws_wallpaper_gallery import WallpaperGallery
        gallery_card = card('壁纸库', '选择一张壁纸，点击应用后生效。添加的图片会复制到壁纸库。')
        self.wallpaper_file = WallpaperGallery(lambda path: self.mark_dirty('wallpaper'), saved.get('image'))
        gallery_card.pack_start(self.wallpaper_file, False, False, 0)
        box.pack_start(gallery_card, False, False, 0)
        self.wallpaper_engine.connect('changed', lambda *_: self.mark_dirty('wallpaper'))
        if not any(e in ENGINES for e in installed()):
            section.pack_start(label('没有检测到可用的壁纸工具。', 'dim-label'), False, False, 0)
            install = Gtk.Button(label=tr('安装 awww'))
            install.connect('clicked', self.install_wallpaper_engine)
            section.pack_start(install, False, False, 0)
        box.pack_start(section, False, False, 0)
        colors = card('自动提取主体色', '使用 Matugen 从新壁纸提取配色，任务栏和设置实时跟随。卸载工具会保留当前配色。')
        from adws_settings_widgets import compact_switch
        self.wallpaper_extract = compact_switch(Gtk.Switch(active=bool(saved.get('extract_colors', False))))
        self.wallpaper_extract.connect('notify::active', lambda *_: self.mark_dirty('wallpaper'))
        line = self.config.row_widget(tr('更换壁纸时自动配色'), self.wallpaper_extract)
        self.palette_button = Gtk.Button(label=tr('检测中…'))
        self.palette_button.set_sensitive(False)
        self.palette_button.connect('clicked', self.manage_wallpaper_colors)
        line.pack_end(self.palette_button, False, False, 0)
        colors.pack_start(line, False, False, 0)
        self.palette_status = label('', 'dim-label')
        colors.pack_start(self.palette_status, False, False, 0)
        box.pack_start(colors, False, False, 0)
        self.refresh_wallpaper_colors()
        return box

    def refresh_wallpaper_colors(self):
        from adws_wallpaper_colors import status
        def worker():
            result = status()
            def done():
                if self.closed: return False
                self.palette_info = result
                self.palette_button.set_label(tr('卸载 Matugen' if result['installed'] else '安装 Matugen'))
                self.palette_button.set_sensitive(bool(result['package'] if result['installed'] else result['manager']))
                self.wallpaper_extract.set_sensitive(result['installed'])
                self.palette_status.set_text(tr('Matugen 已安装。' if result['installed'] else '安装后可启用自动配色。'))
                if result['installed'] and not result['package']:
                    self.palette_status.set_text(tr('Matugen 不是由系统软件包安装的，请通过原安装方式卸载。'))
                return False
            GLib.idle_add(done)
        threading.Thread(target=worker, daemon=True).start()

    def manage_wallpaper_colors(self, *_):
        from adws_wallpaper_colors import manage
        remove = bool(self.palette_info['installed'])
        if not self.confirm('卸载 Matugen？' if remove else '安装 Matugen？',
                            '通过系统软件仓库操作；卸载只移除工具，保留当前配色与壁纸。'):
            return
        def done():
            if remove: self.wallpaper_extract.set_active(False)
            self.refresh_wallpaper_colors()
        self.run_worker(lambda: manage(remove), done)

    def install_wallpaper_engine(self, *_):
        if not self.confirm('是否安装 awww？', '将通过系统软件仓库安装，并使用系统授权窗口。'):
            return
        from adws_wallpaper import install_awww
        def refresh():
            self.wallpaper_engine.append('awww', 'awww (' + tr('推荐') + ')')
            self.wallpaper_engine.set_active_id('awww')
        self.run_worker(install_awww, refresh)

    def confirm(self, title, description=''):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, destroy_with_parent=True,
                                   message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.OK_CANCEL, text=tr(title))
        dialog.format_secondary_text(tr(description))
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        result = dialog.run(); dialog.destroy()
        return result == Gtk.ResponseType.OK

    def error(self, message):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, destroy_with_parent=True,
                                   message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK, text=tr('应用失败'))
        dialog.format_secondary_text(str(message)); dialog.run(); dialog.destroy()

    def apply_changes(self, *_):
        if self.busy:
            return
        try:
            if 'desktop' in self.dirty:
                owner = self.owners['desktop']
                # Reparented pages are not in the old stack: use the existing
                # desktop save method's page guard through a tiny adapter.
                previous = owner.notebook.get_current_page
                owner.notebook.get_current_page = lambda: 0
                try:
                    if not owner.apply_current():
                        return
                finally:
                    owner.notebook.get_current_page = previous
                self.dirty.discard('desktop')
            if 'taskbar' in self.dirty:
                if not self.owners['taskbar'].apply_style():
                    return
                self.dirty.discard('taskbar')
            if 'waybar' in self.dirty:
                self.waybar_page.apply()
                return
            if 'apps' in self.dirty:
                self.apply_apps()
                self.dirty.discard('apps')
                self.app_dirty.clear()
            if 'wallpaper' in self.dirty:
                self.apply_wallpaper()
                return
            if 'input' in self.dirty:
                self.input_page.apply_changes(after=self.apply_changes)
                return
            if 'region' in self.dirty:
                self.service_pages['region'].apply_pending(after=self.apply_changes)
                return
            if 'displays' in self.dirty:
                self.display_page.test_changes()
                return
        except Exception as exc:
            self.error(exc)
        finally:
            self.update_footer()

    def apply_apps(self):
        selected = [(mime, self.app_choices[mime].get_app_info()) for mime in self.app_dirty if mime != 'terminal']
        rollback = []
        try:
            for mime, app in selected:
                if app is None:
                    continue
                types = (mime, 'x-scheme-handler/http', 'text/html') if mime.endswith('/https') else (mime,)
                for content_type in types:
                    old = Gio.AppInfo.get_default_for_type(content_type, False)
                    rollback.append((content_type, old))
                    if not app.set_as_default_for_type(content_type):
                        raise RuntimeError(tr('无法设置默认应用。'))
            if 'terminal' in self.app_dirty:
                from desktop_layer.terminal import set_default
                selected = self.terminal_choice.get_active_id()
                if selected: set_default(None if selected == '__system__' else selected)
        except Exception:
            for content_type, app in reversed(rollback):
                if app:
                    app.set_as_default_for_type(content_type)
                else:
                    Gio.AppInfo.reset_type_associations(content_type)
            raise

    def apply_wallpaper(self):
        from adws_wallpaper import apply, config_path, running, validate
        engine, image = self.wallpaper_engine.get_active_id(), self.wallpaper_file.get_filename()
        if not image:
            raise ValueError(tr('请先选择壁纸图片。'))
        prepared = {}
        extract_colors = self.wallpaper_extract.get_active()
        def prepare():
            # Reading and verifying an image can be slow on external drives.
            if extract_colors:
                from adws_wallpaper_colors import status
                if not status()['installed']: raise ValueError(tr('请先安装 Matugen，再启用自动提取主体色。'))
            prepared['image'] = validate(engine, image)
            prepared['approved'] = running()
        def job():
            apply(engine, prepared['image'], prepared['approved'])
            self.config.save_json_atomic(config_path(), {'engine': engine, 'image': prepared['image'], 'extract_colors': extract_colors})
            if extract_colors:
                from adws_wallpaper_colors import extract
                extract(prepared['image'])
        def confirm_and_apply():
            from adws_wallpaper import PROCESSES
            conflicts = any(PROCESSES.get(name) != engine or engine == 'swaybg'
                            for name in prepared['approved'].values())
            if conflicts and not self.confirm('替换当前壁纸服务？', '其他壁纸工具会在新壁纸成功应用后停止。'):
                return
            self.run_worker(job, lambda: (self.dirty.discard('wallpaper'), self.apply_changes()))
        self.run_worker(prepare, confirm_and_apply)

    def run_worker(self, job, on_success, on_failure=None):
        self.busy = True
        self.stack.set_sensitive(False)
        self.sidebar.set_sensitive(False)
        self.update_footer()
        def done(error):
            if self.closed:
                return False
            self.busy = False
            self.stack.set_sensitive(True)
            self.sidebar.set_sensitive(True)
            try:
                if error:
                    self.error(error)
                    if on_failure:on_failure()
                else:
                    on_success()
            except Exception as exc:
                self.error(exc)
            finally:
                self.update_footer()
            return False
        def worker():
            try:
                job(); error = None
            except Exception as exc:
                error = str(exc)
            GLib.idle_add(done, error)
        threading.Thread(target=worker, daemon=False).start()

    def key_pressed(self, _, event):
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        if ctrl and event.keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.search.grab_focus(); return True
        if ctrl and event.keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self.apply_changes(); return True
        if event.keyval == Gdk.KEY_Escape and self.search.get_text():
            self.search.set_text(''); return True
        return False

    def request_close(self, *_):
        if self.busy:
            return True
        if self.dirty and not self.confirm('放弃尚未应用的修改？', '已应用的设置会保留。'):
            return True
        return False

    def cleanup(self, *_):
        self.closed = True
        agent=getattr(self,'authentication_agent',None)
        if agent:agent.close()
        for owner in self.owners.values():
            owner.destroy()
        self.visual_style.close()
        self.config.on_settings_window_destroy()

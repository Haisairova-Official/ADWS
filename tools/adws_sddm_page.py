"""SDDM login theme management in the unified settings window."""
import threading

from gi.repository import GLib, Gtk

import adws_sddm
from adws_i18n import tr
from adws_system_settings import card, label


class SddmPage(Gtk.Box):
    def __init__(self, host):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.host = host
        self.snapshot = None
        self.read_generation = 0
        self.writing = False

        identity = card('登录管理器')
        manager_row = Gtk.Box(spacing=12)
        icon = Gtk.Image.new_from_icon_name('system-lock-screen-symbolic', Gtk.IconSize.LARGE_TOOLBAR)
        manager_row.pack_start(icon, False, False, 0)
        self.manager_name = label('正在检测…', 'settings-section-title')
        manager_row.pack_start(self.manager_name, True, True, 0)
        self.refresh_button = Gtk.Button(label=tr('重新检测'))
        self.refresh_button.connect('clicked', self.refresh)
        manager_row.pack_end(self.refresh_button, False, False, 0)
        identity.pack_start(manager_row, False, False, 0)
        self.management = label('', 'dim-label')
        identity.pack_start(self.management, False, False, 0)
        self.pack_start(identity, False, False, 0)

        self.theme_card = card('登录主题', '主题变更将在下次显示 SDDM 登录界面时生效。')
        self.theme_card.set_no_show_all(True)
        self.current = label('')
        self.theme_card.pack_start(self.current, False, False, 0)
        select_row = Gtk.Box(spacing=12)
        select_row.pack_start(label('已安装的主题'), True, True, 0)
        self.choices = Gtk.ComboBoxText()
        self.choices.get_accessible().set_name(tr('已安装的主题'))
        self.choices.set_halign(Gtk.Align.END)
        self.choices.connect('changed', self.update_controls)
        select_row.pack_end(self.choices, False, False, 0)
        self.theme_card.pack_start(select_row, False, False, 0)
        buttons = Gtk.Box(spacing=10)
        self.apply_button = Gtk.Button()
        self.apply_button.get_style_context().add_class('suggested-action')
        self.apply_button.connect('clicked', self.apply)
        buttons.pack_start(self.apply_button, False, False, 0)
        self.restore_button = Gtk.Button(label=tr('撤销 ADWS 接管'))
        self.restore_button.set_no_show_all(True)
        self.restore_button.connect('clicked', self.restore)
        buttons.pack_start(self.restore_button, False, False, 0)
        self.theme_card.pack_start(buttons, False, False, 0)
        # The page may initially detect a different display manager. Build and
        # show the card's children even when the card itself stays hidden.
        for child in self.theme_card.get_children():
            child.show_all()
        self.pack_start(self.theme_card, False, False, 0)
        self.result = label('')
        self.result.set_selectable(True)
        self.result.set_no_show_all(True)
        self.pack_start(self.result, False, False, 0)
        self.connect('map', self.refresh)
        self.connect('destroy', self.closed)
        self.update_controls()

    def closed(self, *_):
        self.read_generation += 1

    def report(self, message):
        self.result.set_text(message)
        self.result.set_visible(bool(message))

    def refresh(self, *_, selection=None):
        if self.writing:
            return
        self.read_generation += 1
        generation = self.read_generation
        self.snapshot = None
        self.update_controls()
        self.refresh_button.set_sensitive(False)
        self.manager_name.set_text(tr('正在检测…'))

        def read():
            try:
                state = adws_sddm.inspect()
                error = ''
            except Exception as exc:
                state, error = None, str(exc)

            def finish():
                if generation != self.read_generation:
                    return False
                self.refresh_button.set_sensitive(True)
                if state is None:
                    self.manager_name.set_text(tr('检测失败'))
                    self.management.set_text(error)
                    self.theme_card.hide()
                else:
                    self.render(state, selection)
                return False
            GLib.idle_add(finish)
        threading.Thread(target=read, daemon=True).start()

    def render(self, state, selection=None):
        self.snapshot = state
        use_sddm = state['manager'] == 'sddm'
        name = state['manager_name'] if state['manager'] else tr('未检测到登录管理器')
        self.manager_name.set_text(name)
        self.theme_card.set_visible(use_sddm)
        if not use_sddm:
            self.management.set_text(tr('使用 SDDM 登录的系统可以在此管理主题。'))
            return
        if state['conflict']:
            detail = state['conflict']
        elif not state['themes']:
            detail = tr('未找到已安装的 SDDM 主题。')
        elif state['managed']:
            detail = tr('登录主题由 ADWS 管理。')
        else:
            detail = tr('登录主题由系统配置管理。')
        self.management.set_text(detail)
        current = state['current'] or tr('SDDM 内置主题')
        self.current.set_text(tr('当前主题：%s') % current)
        self.choices.remove_all()
        for theme in state['themes']:
            self.choices.append(theme, theme)
        selected = selection if selection in state['themes'] else state['current']
        self.choices.set_active_id(selected)
        self.apply_button.set_label(tr('应用主题') if state['managed'] else tr('接管并应用主题'))
        self.restore_button.set_visible(state['managed'])
        self.update_controls()

    def update_controls(self, *_):
        state = self.snapshot
        selected = self.choices.get_active_id()
        enabled = bool(state and not self.writing and state['manager'] == 'sddm')
        choose = enabled and state['can_apply'] and bool(state['themes'])
        self.choices.set_sensitive(choose)
        self.apply_button.set_sensitive(bool(choose and selected and
                                             (not state['managed'] or selected != state['current'])))
        self.restore_button.set_sensitive(bool(enabled and state['can_restore']))

    def apply(self, *_):
        if not self.apply_button.get_sensitive():
            return
        theme, state = self.choices.get_active_id(), self.snapshot
        self.change(lambda: adws_sddm.apply(theme, state), tr('已应用登录主题「%s」。') % theme)

    def restore(self, *_):
        if not self.restore_button.get_sensitive():
            return
        if not self.host.confirm('撤销 ADWS 接管？', 'SDDM 将恢复使用系统配置指定的主题。'):
            return
        state = self.snapshot
        self.change(lambda: adws_sddm.restore(state), tr('已恢复系统登录主题配置。'))

    def change(self, operation, success):
        self.writing = True
        self.refresh_button.set_sensitive(False)
        self.update_controls()
        self.report(tr('正在请求管理员授权…'))
        message = success
        retry = self.choices.get_active_id()

        def job():
            nonlocal message, retry
            try:
                result = operation()
            except adws_sddm.AuthorizationCancelled:
                message = tr('已取消授权。')
                return
            retry = None
            if result.get('backup'):
                message += '\n' + tr('备份位置：%s') % result['backup']

        def complete(feedback):
            self.writing = False
            self.report(feedback)
            self.refresh(selection=retry)

        self.host.run_worker(job, lambda: complete(message),
                             lambda: complete(tr('更改失败，请查看错误详情。')))

"""Project information and offline license documents for the system settings."""
from pathlib import Path
from urllib.parse import unquote, urlsplit

from gi.repository import Gdk, GLib, Gtk

from adws_about_markdown import MarkdownView

from adws_i18n import tr
from adws_runtime import build_info, version_text
from adws_system_settings import card, label
from adws_update import REPOSITORY


ROOT = Path(__file__).resolve().parents[1]
PROJECT_URL = f'https://github.com/{REPOSITORY}'


def show_document(parent, caption, filename):
    dialog = Gtk.Dialog(title=tr(caption), transient_for=parent, modal=True,
                        destroy_with_parent=True, use_header_bar=True)
    dialog.get_style_context().add_class('adws-system-settings')
    dialog.add_button(tr('关闭'), Gtk.ResponseType.CLOSE)
    dialog.set_default_size(660, 480)
    path = ROOT / filename

    def open_link(target, title):
        try:
            url = urlsplit(target)
            if url.scheme in ('http', 'https') and url.netloc:
                Gtk.show_uri_on_window(dialog, target, Gdk.CURRENT_TIME)
                return
            if url.scheme or url.netloc or not url.path:
                raise ValueError(target)
            relative = (path.parent / unquote(url.path)).resolve().relative_to(ROOT.resolve())
            if relative.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
                Gtk.show_uri_on_window(dialog, (ROOT / relative).as_uri(), Gdk.CURRENT_TIME)
            else:
                show_document(dialog, title, relative)
        except (GLib.Error, OSError, ValueError, RuntimeError) as error:
            message = Gtk.MessageDialog(transient_for=dialog, modal=True, destroy_with_parent=True,
                                        message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE,
                                        text=tr('无法打开链接'))
            message.format_secondary_text(str(error))
            message.connect('response', lambda widget, _: widget.destroy())
            message.show_all()

    try:
        contents = path.read_text(encoding='utf-8')
        markdown = path.suffix.lower() == '.md'
    except (OSError, UnicodeError):
        contents = tr('无法读取随安装提供的文件：%s') % filename
        markdown = False
    if markdown:
        text = MarkdownView(contents, open_link)
    else:
        text = Gtk.TextView(editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            left_margin=18, right_margin=18, top_margin=16, bottom_margin=16)
        text.get_buffer().set_text(contents)
    text.get_accessible().set_name(tr(caption))
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.add(text)
    dialog.get_content_area().pack_start(scroll, True, True, 0)
    dialog.connect('response', lambda widget, _: widget.destroy())
    dialog.show_all()
    return dialog


def document_button(window, caption, filename):
    button = Gtk.Button(label=tr(caption))
    button.connect('clicked', lambda _: show_document(window, caption, filename))
    return button


def link(caption, suffix=''):
    button = Gtk.LinkButton.new_with_label(PROJECT_URL + suffix, tr(caption))
    button.set_halign(Gtk.Align.START)
    return button


def build_page(window):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
    info = build_info()
    version = version_text(info) if info else tr('未知')
    hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    hero.get_style_context().add_class('settings-hero')
    title = label(f'ADWS {version}', 'settings-hero-title')
    title.set_selectable(True)
    hero.pack_start(title, False, False, 0)
    hero.pack_start(label("Akizuki’s Desktop Workspace Solution"), False, False, 0)
    channel = info.get('release_label') or ''
    channel = {'pre-release': tr('预发布'), 'prerelease': tr('预发布'),
               'stable': tr('正式版'), 'release': tr('正式版')}.get(channel.lower(), channel)
    details = [part for part in (channel, info.get('build_date')) if part]
    if details:
        hero.pack_start(label(' · '.join(details), 'settings-caption'), False, False, 0)
    links = Gtk.Box(spacing=8)
    links.pack_start(link('项目主页'), False, False, 0)
    links.pack_start(link('反馈问题', '/issues'), False, False, 0)
    links.pack_start(document_button(window, '更新记录', 'CHANGELOG.md'), False, False, 0)
    hero.pack_start(links, False, False, 0)
    box.pack_start(hero, False, False, 0)

    licenses = card('开源许可', 'ADWS 原创代码使用 GNU GPL 第 3 版或更新版本（GPL-3.0-or-later）。各组件的作者与许可见第三方声明。')
    documents = Gtk.Box(spacing=8)
    documents.pack_start(document_button(window, '许可全文', 'LICENSE'), False, False, 0)
    documents.pack_start(document_button(window, '第三方声明', 'THIRD_PARTY_NOTICES.md'), False, False, 0)
    licenses.pack_start(documents, False, False, 0)
    box.pack_start(licenses, False, False, 0)

    # The published Git history credits this author. Keep upstream credits from
    # THIRD_PARTY_NOTICES separate; installed archives don't contain a .git tree.
    contributors = card('贡献者')
    contributors.pack_start(label('南雲　あづき  ·  ' + tr('ADWS 开发与维护')), False, False, 0)
    contributors.pack_start(link('查看项目贡献记录', '/graphs/contributors'), False, False, 0)
    contributors.pack_start(label('上游致谢', 'settings-section-title'), False, False, 0)
    contributors.pack_start(label('Adam Harvey  ·  niri-taskbar'), False, False, 0)
    contributors.pack_start(label('Ivan Molodetskikh、Niri 贡献者及 SHORiN-KiWATA  ·  Niri 兼容支持'), False, False, 0)
    box.pack_start(contributors, False, False, 0)
    return box

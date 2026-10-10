"""Read the existing notification service without becoming a notification daemon."""
import html
import os
from pathlib import Path
import re
from gi.repository import Gio, GLib, Gtk, Pango
from adws_i18n import tr
from adws_sidebar_widgets import AsyncCard
from adws_sidebar_board import icon_button
from adws_system_settings import label

DEST = 'org.freedesktop.Notifications'
PATH = '/org/freedesktop/Notifications'
MAKO_PATH = '/fr/emersion/Mako'


def call(interface, method, args=None, path=PATH):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    return bus.call_sync(DEST, path, interface, method, args, None,
                         Gio.DBusCallFlags.NO_AUTO_START, 1200, None).unpack()


def plain(value, limit=600):
    return html.unescape(re.sub(r'<[^>]*>', '', str(value)))[:limit]


def rows(raw, historical=False):
    result = []
    for item in raw[:50] if isinstance(raw, (list, tuple)) else []:
        if not isinstance(item, dict): continue
        identity = item.get('id')
        if type(identity) is not int or not 0 <= identity <= 2**32-1: continue
        result.append({'id':identity, 'app':plain(item.get('appname', item.get('app-name', item.get('app_name', ''))), 100),
                       'title':plain(item.get('summary', ''), 200), 'body':plain(item.get('body', '')),
                       'historical':historical})
    return result


def grouped(items):
    """Keep arrival order inside each application and between first occurrences."""
    groups={}
    for item in items:
        name=item.get('app','').strip() or '通知'
        key=name.casefold()
        if key not in groups:groups[key]=(name,[])
        groups[key][1].append(item)
    return list(groups.values())


def mako_dnd_mode():
    # Mako modes only affect rendering when the user has configured a rule.
    path = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'mako/config'
    try: text = path.read_text()
    except OSError: return None
    for mode in ('adws-do-not-disturb','do-not-disturb','dnd'):
        pattern = r'\[mode='+re.escape(mode)+r'\]([^\[]*)'
        if any(re.search(r'(?m)^\s*invisible\s*=\s*1\s*$', body) for body in re.findall(pattern, text)):
            return mode
    return None


def snapshot():
    try: provider = call(DEST, 'GetServerInformation')[0].lower()
    except GLib.Error: return {'provider':None,'items':[],'dnd':None}
    if 'dunst' in provider:
        items = call('org.dunstproject.cmd0','NotificationListHistory')[0]
        paused = call('org.freedesktop.DBus.Properties','Get', GLib.Variant('(ss)',('org.dunstproject.cmd0','paused')))[0]
        return {'provider':'dunst','items':rows(items,True),'dnd':bool(paused)}
    if 'mako' in provider:
        active = rows(call('fr.emersion.Mako','ListNotifications',path=MAKO_PATH)[0])
        history = rows(call('fr.emersion.Mako','ListHistory',path=MAKO_PATH)[0],True)
        known = {item['id'] for item in active}
        modes = call('fr.emersion.Mako','ListModes',path=MAKO_PATH)[0]
        mode = mako_dnd_mode()
        return {'provider':'mako','items':active+[item for item in history if item['id'] not in known],
                'dnd':mode in modes if mode else None,'mode':mode,'modes':modes}
    return {'provider':provider,'items':[],'dnd':None,'unsupported':True}


def change(data, action, identity=None):
    provider = data.get('provider')
    if provider == 'dunst':
        if action == 'dnd':
            call('org.freedesktop.DBus.Properties','Set',GLib.Variant('(ssv)',('org.dunstproject.cmd0','paused',GLib.Variant('b',not data['dnd']))))
        elif action == 'clear': call('org.dunstproject.cmd0','NotificationClearHistory')
        elif action == 'remove': call('org.dunstproject.cmd0','NotificationRemoveFromHistory',GLib.Variant('(u)',(identity,)))
    elif provider == 'mako':
        if action == 'dnd' and data.get('mode'):
            modes = list(data.get('modes', [])); mode = data['mode']
            if mode in modes: modes.remove(mode)
            else: modes.append(mode)
            call('fr.emersion.Mako','SetModes',GLib.Variant('(as)',(modes,)),MAKO_PATH)
        elif action in ('clear','remove'):
            from adws_system_pages import command
            command(['makoctl','dismiss', '-a'] if action=='clear' else ['makoctl','dismiss','-n',str(identity)], timeout=2)
    return snapshot()


class NotificationCard(AsyncCard):
    def __init__(self, host):
        super().__init__(host, '通知中心'); self.data = {}
        self.expanded={};self.limits={};self.groups={};self.history_expander=None
        self.box.get_style_context().add_class('sidebar-notifications')
        top = Gtk.Box(spacing=8)
        self.dnd = Gtk.ToggleButton(label=tr('勿扰')); self.dnd.set_sensitive(False)
        self.updating = False; self.dnd.connect('clicked', self.toggle_dnd)
        top.pack_start(self.dnd, False, False, 0)
        self.clear = Gtk.Button(label=tr('清除记录')); self.clear.set_sensitive(False)
        self.clear.connect('clicked', lambda *_: self.act('clear'))
        top.pack_end(self.clear, False, False, 0)
        top.pack_end(icon_button('view-refresh-symbolic','刷新状态', lambda *_: self.refresh()), False, False, 0)
        self.box.pack_start(top, False, False, 0)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        self.box.pack_start(self.list, False, False, 0)
        self.watch_visible(self.refresh,5)

    def refresh(self):
        if self.host.closed: return False
        if not self.busy and self.box.get_mapped():
            self.job(snapshot,self.loaded)
        return True

    def loaded(self, data):
        if data == self.data: return
        self.data = data
        self.updating = True; self.dnd.set_active(data.get('dnd') is True); self.updating = False
        self.dnd.set_sensitive(data.get('dnd') is not None)
        self.dnd.set_tooltip_text(tr('通知服务尚未配置勿扰模式。') if data.get('dnd') is None else tr('勿扰'))
        self.clear.set_label(tr('关闭全部通知') if data.get('provider')=='mako' else tr('清除记录'))
        actionable = [item for item in data.get('items',[]) if data.get('provider')=='dunst' or not item['historical']]
        self.clear.set_sensitive(bool(actionable))
        if not data.get('provider'): self.status.set_text(tr('未检测到通知服务'))
        elif data.get('unsupported'): self.status.set_text(tr('当前通知服务未提供可用的历史接口。'))
        elif not data['items'] or (data.get('provider')=='mako' and not actionable): self.status.set_text(tr('没有新通知，稍作休息吧。'))
        else: self.status.set_text(tr('通知记录') + f" · {len(data['items'])}")
        scroll=self.list.get_ancestor(Gtk.ScrolledWindow)
        adjustment=scroll.get_vadjustment() if scroll else None
        previous=adjustment.get_value() if adjustment else 0
        for child in self.list.get_children(): child.destroy()
        self.groups={}
        active=[item for item in data.get('items',[]) if not item['historical']]
        history=[item for item in data.get('items',[]) if item['historical']]
        keys={(scope,name.casefold()) for scope,items in (('active',active),('history',history)) for name,_ in grouped(items)}
        self.expanded={key:value for key,value in self.expanded.items() if key=='history' or key in keys}
        self.limits={key:value for key,value in self.limits.items() if key in keys}
        for name,items in grouped(active):self.list.pack_start(self.make_group('active',name,items),False,False,0)
        self.history_expander=None
        if history:
            history_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
            expander=Gtk.Expander(label=tr('历史记录')+f' ({len(history)})');expander.add(history_box)
            expander.set_expanded(self.expanded.get('history',data.get('provider')=='dunst'))
            expander.connect('notify::expanded',lambda widget,*_:self.expanded.update(history=widget.get_expanded()))
            self.history_expander=expander
            for name,items in grouped(history):history_box.pack_start(self.make_group('history',name,items),False,False,0)
            self.list.pack_start(expander,False,False,0)
        self.list.show_all()
        if adjustment:
            def restore():
                if not self.closed and not self.host.closed:adjustment.set_value(min(previous,max(0,adjustment.get_upper()-adjustment.get_page_size())))
                return False
            GLib.idle_add(restore)

    def make_group(self,scope,name,items):
        key=(scope,name.casefold())
        expander=Gtk.Expander();heading=Gtk.Box(spacing=8)
        title=label(tr(name) if name=='通知' else name,'settings-section-title')
        title.set_max_width_chars(28);title.set_ellipsize(Pango.EllipsizeMode.END)
        heading.pack_start(title,True,True,0);heading.pack_end(label(str(len(items)),'dim-label'),False,False,0)
        expander.set_label_widget(heading)
        content=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6,margin_top=8)
        expander.add(content);self.groups[key]=expander
        def populate():
            for child in content.get_children():child.destroy()
            if not expander.get_expanded():return
            limit=self.limits.get(key,5)
            for item in items[:limit]:content.pack_start(self.make_row(item),False,False,0)
            if len(items)>limit:
                more=Gtk.Button(label=tr('显示更多（剩余 %s 条）') % (len(items)-limit))
                def expand(*_):self.limits[key]=limit+10;populate()
                more.connect('clicked',expand);content.pack_start(more,False,False,0)
            content.show_all()
        def toggled(widget,*_):
            self.expanded[key]=widget.get_expanded();populate()
        expander.set_expanded(self.expanded.get(key,scope=='active'))
        expander.connect('notify::expanded',toggled);populate()
        return expander

    def make_row(self,item):
        row=Gtk.Box(spacing=6);row.get_style_context().add_class('sidebar-notification-row')
        body=label(item['title']+('\n'+item['body'] if item['body'] else ''))
        body.set_max_width_chars(45);body.set_lines(3);body.set_ellipsize(Pango.EllipsizeMode.END)
        row.pack_start(body,True,True,0)
        if self.data.get('provider')=='dunst' or not item['historical']:
            button=icon_button('window-close-symbolic','关闭',lambda _,identity=item['id']:self.act('remove',identity))
            button.set_valign(Gtk.Align.START);row.pack_end(button,False,False,0)
        return row

    def toggle_dnd(self, *_):
        if not self.updating and self.data.get('dnd') is not None: self.act('dnd')

    def act(self, action, identity=None):
        self.job(lambda: change(self.data,action,identity),self.loaded,('action',action,identity))

    def close(self,*_):
        self.dispose()

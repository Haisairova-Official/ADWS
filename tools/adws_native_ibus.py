"""ADWS input-method UI for IBus, without launching ibus-setup."""
import json
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gio,GLib,Gtk
from adws_i18n import tr
from adws_native_settings_gui import NativeSection,Form,caption,choice,entry,button,row


def ibus_bus():
    gi.require_version('IBus','1.0')
    from gi.repository import IBus
    IBus.init();bus=IBus.Bus.new()
    if not bus.is_connected():raise RuntimeError(tr('IBus 尚未运行，请先启动输入法服务。'))
    return bus


def snapshot():
    bus=ibus_bus();settings=Gio.Settings.new('org.freedesktop.ibus.general')
    engines=[(e.get_name(),e.get_longname() or e.get_name()) for e in bus.list_engines()]
    return {'engines':engines,'enabled':list(settings.get_strv('preload-engines'))}


def set_engines(expected,names):
    current=snapshot();known={name for name,_ in current['engines']}
    if current['enabled']!=expected['enabled']:raise RuntimeError(tr('输入法列表已被修改，请刷新后重试。'))
    if not names or len(set(names))!=len(names) or any(name not in known for name in names):raise ValueError(tr('输入法列表无效；请至少保留一种输入法。'))
    settings=Gio.Settings.new('org.freedesktop.ibus.general');settings.delay()
    if not settings.set_strv('preload-engines',names) or not settings.set_strv('engines-order',names):
        settings.revert();raise RuntimeError(tr('系统不允许修改此输入法设置。'))
    settings.apply();Gio.Settings.sync()


def schemas():
    source=Gio.SettingsSchemaSource.get_default()
    return sorted(name for name in source.list_schemas(True)[0] if name.startswith('org.freedesktop.ibus.') and name!='org.freedesktop.ibus') if source else []


def config_form(host,name):
    source=Gio.SettingsSchemaSource.get_default();schema=source.lookup(name,True) if source else None
    if schema is None or not schema.get_path():host.error(tr('此输入法没有可编辑的配置。'));return
    settings=Gio.Settings.new_full(schema,None,None);expected={};controls={}
    form=Form(host,'IBus 设置');form.body.pack_start(caption(name,'dim-label'),False,False,0)
    for key in sorted(schema.list_keys()):
        if key in ('preload-engines','engines-order','version','x','y'):continue
        value=settings.get_value(key);signature=value.get_type_string();expected[key]=value
        if signature=='b':control=Gtk.Switch(active=value.unpack());getter=lambda w=control:w.get_active()
        elif signature=='s':control=entry(value.unpack());getter=lambda w=control:w.get_text()
        elif signature in ('i','u'):
            control=Gtk.SpinButton.new_with_range(-2147483648 if signature=='i' else 0,2147483647,1);control.set_value(value.unpack());getter=lambda w=control:w.get_value_as_int()
        elif signature=='as':
            control=entry(', '.join(value.unpack()));getter=lambda w=control:[v.strip() for v in w.get_text().split(',') if v.strip()]
        else:continue
        controls[key]=(signature,getter)
        row(form.body,schema.get_key(key).get_summary() or key,control)
    form.show_all()
    try:
        if form.run()!=Gtk.ResponseType.OK:return
        values={key:GLib.Variant(signature,getter()) for key,(signature,getter) in controls.items()}
        for key,value in values.items():
            if not schema.get_key(key).range_check(value):raise ValueError(tr('输入法设置值超出支持范围。'))
    except Exception as error:host.error(str(error));return
    finally:form.destroy()
    def apply():
        for key in values:
            if settings.get_value(key)!=expected[key]:raise RuntimeError(tr('输入法设置已被其他程序修改，请刷新后重试。'))
        settings.delay()
        for key,value in values.items():
            if not settings.set_value(key,value):settings.revert();raise RuntimeError(tr('系统不允许修改此输入法设置。'))
        settings.apply();Gio.Settings.sync()
    host.run_worker(apply,lambda:None)


def input_sections(host,parent):
    def render(section,data):
        known=dict(data['engines'])
        for index,name in enumerate(data['enabled']):
            controls=Gtk.Box(spacing=6)
            if index:controls.pack_start(button('上移',lambda i=index:move(section,data,i,-1)),False,False,0)
            if index<len(data['enabled'])-1:controls.pack_start(button('下移',lambda i=index:move(section,data,i,1)),False,False,0)
            controls.pack_start(button('移除',lambda i=index:section.change(lambda:set_engines(data,[n for j,n in enumerate(data['enabled']) if j!=i]))),False,False,0)
            row(section.content,known.get(name,name),controls)
        selected=choice([(n,title) for n,title in data['engines'] if n not in data['enabled']]);row(section.content,'添加输入法',selected)
        def add():
            name=selected.get_active_id()
            if name:section.change(lambda:set_engines(data,[*data['enabled'],name]))
        section.content.pack_start(button('添加',add),False,False,0)
        for name in schemas():section.content.pack_start(button(name,lambda name=name:config_form(host,name)),False,False,0)
    def move(section,data,index,delta):
        values=list(data['enabled']);values[index],values[index+delta]=values[index+delta],values[index]
        section.change(lambda:set_engines(data,values))
    NativeSection(host,parent,'IBus 输入法与配置',snapshot,render,'ibus')

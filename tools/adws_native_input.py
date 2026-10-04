"""Fcitx 5 settings generated from its schema, plus native resource managers."""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile
from gi.repository import GLib,Gtk
from adws_i18n import tr
from adws_native_settings_gui import NativeSection,Form,caption,choice,entry,button,row
import adws_native_services as backend
from adws_settings_widgets import settings_tabs


def raw_variant(value):
    if isinstance(value,dict):return GLib.Variant('a{sv}',{str(k):raw_variant(v) for k,v in value.items()})
    if isinstance(value,str):return GLib.Variant('s',value)
    raise ValueError('Invalid Fcitx raw config')


def themes():
    result={}
    for directory in [Path('/usr/share/fcitx5/themes'),Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'fcitx5/themes']:
        if directory.is_dir():
            for folder in directory.iterdir():
                if folder.is_dir() and (folder/'theme.conf').is_file():result[folder.name]=folder
    return sorted(result)


def fcitx_sections(host,parent):
    selected = ['methods']
    def render(section,data):
        pages = {key:Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=14) for key in ('methods','appearance','addons')}
        tabs = settings_tabs([(key,tr(title),pages[key]) for key,title in [('methods','输入方式'),('appearance','候选框与词库'),('addons','附加组件')]])
        tabs.stack.set_visible_child_name(selected[0])
        tabs.stack.connect('notify::visible-child-name',lambda stack,_:selected.__setitem__(0,stack.get_visible_child_name()))
        section.content.pack_start(tabs,False,False,0)
        known={item[0]:item[1] for item in data['available']}
        row(pages['methods'],'输入法组',caption(data['group']))
        for index,(name,layout) in enumerate(data['enabled']):
            controls=Gtk.Box(spacing=6)
            if index:controls.pack_start(button('上移',lambda i=index:move(section,data,i,-1)),False,False,0)
            if index<len(data['enabled'])-1:controls.pack_start(button('下移',lambda i=index:move(section,data,i,1)),False,False,0)
            controls.pack_start(button('移除',lambda i=index:remove(section,data,i)),False,False,0)
            if any(item[0]==name and item[6] for item in data['available']):
                controls.pack_start(button('设置',lambda n=name:config_form(host,'fcitx://config/inputmethod/'+n)),False,False,0)
            row(pages['methods'],known.get(name,name),controls)
        available=choice([(item[0],item[1]) for item in data['available'] if item[0] not in {e[0] for e in data['enabled']}])
        addrow=Gtk.Box(spacing=10)
        addrow.pack_start(available,True,True,0)
        def add():
            name=available.get_active_id()
            if name:section.change(lambda:backend.fcitx_set_group(data,[*data['enabled'],(name,'')]))
        addrow.pack_end(button('添加',add),False,False,0)
        row(pages['methods'],'添加输入法',addrow)
        row(pages['methods'],'快捷键与输入行为',button('设置',lambda:config_form(host,'fcitx://config/global')))
        for title,detail,action in [
                ('候选框、字体与皮肤','调整候选列表、字体和已有皮肤。',lambda:config_form(host,'fcitx://config/addon/classicui')),
                ('词库管理','导入词库、编辑自定义词组。',lambda:dictionary_form(host)),
                ('安装主题…','从本地导入新的输入法皮肤。',lambda:import_theme(host,section))]:
            row(pages['appearance'],title,button('打开',action),detail)
        for name,title,description,category,configurable,enabled in data['addons']:
            controls=Gtk.Box(spacing=8)
            state=Gtk.Switch(active=enabled)
            state.connect('notify::active',lambda control,_,n=name:set_addon(section,n,control.get_active()))
            controls.pack_end(state,False,False,0)
            if configurable:controls.pack_start(button('设置',lambda n=name:config_form(host,'fcitx://config/addon/'+n)),False,False,0)
            row(pages['addons'],title or name,controls,description)
    def move(section,data,index,delta):
        values=list(data['enabled']);values[index],values[index+delta]=values[index+delta],values[index]
        section.change(lambda:backend.fcitx_set_group(data,values))
    def remove(section,data,index):
        values=[item for i,item in enumerate(data['enabled']) if i!=index]
        section.change(lambda:backend.fcitx_set_group(data,values))
    def set_addon(section,name,enabled):
        if not enabled and not host.confirm('禁用输入法组件？',tr('禁用核心组件可能会影响输入法，请确认此组件的用途。')):
            section.refresh();return
        section.change(lambda:(backend.fcitx_call('SetAddonsState','(a(sb))',([(name,enabled)],)),backend.fcitx_call('Save')))
    NativeSection(host,parent,'Fcitx 5',backend.fcitx_snapshot,render,'input')


def config_form(host,uri):
    # Loading descriptions can activate an addon. Never perform it in GTK's
    # input handler, where a stalled addon would freeze the settings window.
    result=[]
    def loaded():
        reply=result[0];expected=reply.get_child_value(0)
        raw=expected.get_variant().unpack()
        description=reply.get_child_value(1).unpack()
        form=Form(host,'输入法设置')
        getters=[];schema=dict(description)
        def fields(group,node,path=()):
            for name,kind,title,default,options in schema.get(group,[]):
                current=node.get(name,default)
                location=path+(name,)
                if kind in schema:
                    nested=node.get(name)
                    if not isinstance(nested,dict):nested={};node[name]=nested
                    form.body.pack_start(caption(title,'settings-section-title'),False,False,0)
                    fields(kind,nested,location);continue
                if kind=='External':
                    target=options.get('External','')
                    if target.endswith('/dictmanager'):
                        callback=lambda:dictionary_form(host)
                    elif target.endswith('/customphrase'):
                        callback=lambda:phrase_form(host,'pinyin/customphrase')
                    elif target.endswith('/quickphrase/editor'):
                        callback=lambda:phrase_form(host,'data/QuickPhrase.mb')
                    else:callback=lambda target=target:config_form(host,target)
                    form.body.pack_start(button(title,callback),False,False,0);continue
                if kind=='Boolean':
                    control=Gtk.Switch(active=str(current).casefold()=='true')
                    getter=lambda w=control:'True' if w.get_active() else 'False'
                elif kind=='Integer':
                    minimum=int(options.get('IntMin',-2147483648));maximum=int(options.get('IntMax',2147483647))
                    control=Gtk.SpinButton.new_with_range(minimum,maximum,1)
                    control.set_value(int(current or 0));getter=lambda w=control:str(w.get_value_as_int())
                elif kind=='Enum' or options.get('IsEnum')=='True':
                    values=options.get('Enum',{});labels=options.get('EnumI18n',{})
                    control=choice([(value,labels.get(index,value)) for index,value in values.items()],current)
                    getter=lambda w=control:w.get_active_id() or ''
                    paths=options.get('SubConfigPath',{})
                    if paths:
                        def edit_selected(w=control,values=values,paths=paths):
                            index=next((key for key,value in values.items() if value==w.get_active_id()),None)
                            target=paths.get(index)
                            if target:config_form(host,target)
                        form.body.pack_start(button('编辑所选配置…',edit_selected),False,False,0)
                elif kind.startswith('List|'):
                    control=Gtk.TextView();control.set_size_request(260,90)
                    simple=not isinstance(current,dict) or all(isinstance(v,str) for v in current.values())
                    if simple:
                        content='\n'.join(v for _,v in sorted(current.items(),key=lambda p:int(p[0]) if str(p[0]).isdigit() else 0)) if isinstance(current,dict) else str(current)
                    else:content=json.dumps(current,ensure_ascii=False,indent=2)
                    control.get_buffer().set_text(content)
                    def getter(w=control,simple=simple):
                        buffer=w.get_buffer();value=buffer.get_text(buffer.get_start_iter(),buffer.get_end_iter(),True)
                        return {str(i):line for i,line in enumerate(value.splitlines()) if line} if simple else json.loads(value)
                elif name in ('Theme','DarkTheme') and uri.endswith('/classicui'):
                    names=themes();control=choice([(value,value) for value in sorted(set([str(current),*names]))],current)
                    getter=lambda w=control:w.get_active_id() or ''
                elif options.get('Font')=='True':
                    control=Gtk.FontButton(font=str(current));getter=lambda w=control:w.get_font_name()
                else:
                    control=entry(current if isinstance(current,str) else json.dumps(current,ensure_ascii=False))
                    getter=lambda w=control:w.get_text()
                row(form.body,title or name,control,options.get('Tooltip'))
                getters.append((location,getter))
        if description:fields(description[0][0],raw)
        else:
            editor=Gtk.TextView();editor.set_size_request(420,300)
            editor.get_buffer().set_text(json.dumps(raw,ensure_ascii=False,indent=2))
            form.body.pack_start(editor,True,True,0)
            def read_raw():
                buffer=editor.get_buffer()
                return json.loads(buffer.get_text(buffer.get_start_iter(),buffer.get_end_iter(),True))
            getters.append(((),read_raw))
        form.show_all()
        from adws_settings_widgets import enhance_choices
        enhance_choices(form.body,translate=tr)
        try:
            if form.run()!=Gtk.ResponseType.OK:return
            value=copy.deepcopy(raw)
            for path,getter in getters:
                if not path:value=getter();continue
                parent=value
                for key in path[:-1]:parent=parent.setdefault(key,{})
                parent[path[-1]]=getter()
            encoded=raw_variant(value)
        except Exception as error:host.error(str(error));return
        finally:form.destroy()
        host.run_worker(lambda:backend.fcitx_set_config(uri,expected,encoded),lambda:None)
    host.run_worker(lambda:result.append(backend.fcitx_config(uri)),loaded)


def dictionaries():
    root=Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'fcitx5/pinyin/dictionaries'
    return root,sorted([*root.glob('*.dict'),*root.glob('*.dict.disable')])


def import_dictionary(filename):
    root,_=dictionaries();root.mkdir(parents=True,exist_ok=True)
    source=Path(filename).resolve(strict=True)
    if not source.is_file() or source.stat().st_size>32*1024*1024 or source.suffix not in ('.dict','.txt'):
        raise ValueError(tr('请选择 Fcitx .dict 或纯文本词库文件。'))
    name=source.stem+'.dict';target=root/name
    if target.exists() or target.with_name(target.name+'.disable').exists():raise ValueError(tr('同名词库已存在，请先重命名文件。'))
    fd,temporary=tempfile.mkstemp(prefix='.adws-dict-',dir=root);os.close(fd)
    try:
        if source.suffix=='.txt':
            from adws_system_pages import command
            command(['libime_pinyindict',str(source),temporary],timeout=30)
        else:shutil.copyfile(source,temporary)
        # A decode pass verifies the native format; conversion is a backend
        # library utility rather than an external settings window.
        if not shutil.which('libime_pinyindict'):raise RuntimeError(tr('需要 libime_pinyindict 以验证词库。'))
        from adws_system_pages import command
        with tempfile.TemporaryDirectory(prefix='adws-dict-verify-') as folder:
            command(['libime_pinyindict','-d',temporary,str(Path(folder)/'words.txt')],timeout=30)
        os.link(temporary,target)
    finally:Path(temporary).unlink(missing_ok=True)
    backend.fcitx_call('ReloadAddonConfig','(s)',('pinyin',))


def dictionary_form(host):
    form=Form(host,'词库管理')
    def render(section,data):
        root,files=data
        section.content.pack_start(button('导入词库…',lambda:choose_file(host,lambda name:section.change(lambda:import_dictionary(name)))),False,False,0)
        for path in files:
            control=Gtk.Switch(active=path.suffix!='.disable')
            def toggle(widget,_,path=path):
                enabled=widget.get_active()
                destination=path.with_name(path.name.removesuffix('.disable')) if enabled else path.with_name(path.name+'.disable')
                def apply():
                    if destination.exists():raise ValueError(tr('同名词库已存在，请先重命名文件。'))
                    path.rename(destination);backend.fcitx_call('ReloadAddonConfig','(s)',('pinyin',))
                section.change(apply)
            control.connect('notify::active',toggle)
            row(section.content,path.name,control)
    NativeSection(host,form.body,'个人拼音词库',dictionaries,render)
    form.read()


def choose_file(host,callback):
    dialog=Gtk.FileChooserDialog(title=tr('选择文件'),transient_for=host,modal=True,action=Gtk.FileChooserAction.OPEN)
    dialog.add_buttons(tr('取消'),Gtk.ResponseType.CANCEL,tr('打开'),Gtk.ResponseType.OK)
    filename=dialog.get_filename() if dialog.run()==Gtk.ResponseType.OK else None
    dialog.destroy()
    if filename:callback(filename)


def install_theme_archive(filename):
    root=Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'fcitx5/themes'
    root.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(filename) as archive,tempfile.TemporaryDirectory(prefix='.adws-theme-',dir=root) as temporary:
        total=0
        entries=archive.infolist()
        if len(entries)>1024:raise ValueError(tr('主题压缩包文件过多。'))
        for item in entries:
            path=Path(item.filename);total+=item.file_size
            if path.is_absolute() or '..' in path.parts or total>32*1024*1024 or (item.external_attr>>16)&0o170000==0o120000:
                raise ValueError(tr('主题压缩包无效或过大。'))
        archive.extractall(temporary)
        configs=list(Path(temporary).glob('*/theme.conf'))
        if len(configs)!=1:raise ValueError(tr('主题压缩包须包含一个带 theme.conf 的主题目录。'))
        source=configs[0].parent;target=root/source.name
        if target.exists():raise ValueError(tr('同名主题已存在。'))
        source.rename(target)


def import_theme(host,section):
    choose_file(host,lambda filename:section.change(lambda:install_theme_archive(filename)))


def phrase_form(host,relative):
    root=Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'fcitx5'
    target=root/relative
    try:
        original=target.read_bytes() if target.exists() else b''
        if len(original)>2*1024*1024:raise ValueError(tr('词组文件过大。'))
        content=original.decode('utf-8')
    except Exception as error:host.error(str(error));return
    form=Form(host,'自定义词组')
    form.body.pack_start(caption('每行一个词组。保留已有格式；以 # 开头的行是注释。','dim-label'),False,False,0)
    editor=Gtk.TextView();editor.set_wrap_mode(Gtk.WrapMode.WORD_CHAR);editor.set_size_request(420,300)
    editor.get_buffer().set_text(content);form.body.pack_start(editor,True,True,0)
    form.show_all()
    if form.run()==Gtk.ResponseType.OK:
        buffer=editor.get_buffer();updated=buffer.get_text(buffer.get_start_iter(),buffer.get_end_iter(),True).encode('utf-8')
        form.destroy()
        def save():
            if (target.read_bytes() if target.exists() else b'')!=original:raise RuntimeError(tr('词组文件已被修改，请重新打开。'))
            if len(updated)>2*1024*1024 or b'\0' in updated:raise ValueError(tr('词组内容无效或过大。'))
            target.parent.mkdir(parents=True,exist_ok=True)
            fd,temp=tempfile.mkstemp(prefix='.adws-phrases-',dir=target.parent)
            try:
                with os.fdopen(fd,'wb') as stream:stream.write(updated)
                os.replace(temp,target)
            finally:Path(temp).unlink(missing_ok=True)
            backend.fcitx_call('ReloadConfig')
        host.run_worker(save,lambda:None)
    else:form.destroy()


def input_sections(host,parent):
    from gi.repository import Gio
    # Discovery is cheap and read-only; choose the running framework in a
    # worker, without activating either daemon or replacing the user's choice.
    def detect():
        try:
            return backend.bus_call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','NameHasOwner','(s)',(backend.FCITX,),session=True).unpack()[0]
        except Exception:return False
    def render(section,fcitx):
        source=Gio.SettingsSchemaSource.get_default()
        ibus=source is not None and source.lookup('org.freedesktop.ibus.general',True) is not None
        if not fcitx and ibus:
            from adws_native_ibus import input_sections as ibus_sections
            ibus_sections(host,section.content)
        elif fcitx:
            fcitx_sections(host,section.content)
        else:
            section.content.pack_start(caption('输入法服务尚未运行。请启动现有输入法，或安装 Fcitx 5。','dim-label'),False,False,0)
            if not fcitx:
                def start():
                    if host.confirm('启动 Fcitx 5？','将启动输入法服务，不修改系统输入法环境变量。'):
                        section.change(lambda:backend.command(['fcitx5','-d']))
                section.content.pack_start(button('启动 Fcitx 5',start),False,False,0)
                section.content.pack_start(button('安装所需系统服务',section.install),False,False,0)
    NativeSection(host,parent,'输入法服务',detect,render,'input')

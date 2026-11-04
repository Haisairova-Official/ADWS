"""Package management shared by the independent desktop and taskbar hosts."""
from pathlib import Path
from gi.repository import Gtk
from adws_i18n import tr
import adws_plugin as mplg
from adws_components import components


def packages():
    result=[]
    for path in mplg.scan_packages():
        ok,errors,manifest=mplg.validate_package(path)
        result.append({'file':path,'ok':ok,'errors':errors,'manifest':manifest})
    return result


class PluginManager(Gtk.Box):
    def __init__(self,parent):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=16)
        self.parent=parent
        self.pack_start(Gtk.Label(label=tr('统一管理模组包。安装或更新后，请分别前往任务栏插件配置、桌面插件配置添加组件。'),xalign=0,wrap=True),False,False,0)
        toolbar=Gtk.Box(spacing=10);self.pack_start(toolbar,False,False,0)
        for title,callback in [('安装／更新模组包…',self.install),('刷新',self.refresh)]:
            button=Gtk.Button(label=tr(title));button.connect('clicked',callback);toolbar.pack_start(button,False,False,0)
        self.message=Gtk.Label(xalign=0,wrap=True);self.pack_start(self.message,False,False,0)
        self.rows=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12);self.pack_start(self.rows,False,False,0)
        self.connect('map',self.refresh)
        self.refresh()

    def refresh(self,*_):
        for child in self.rows.get_children():child.destroy()
        try:items=packages()
        except (OSError,ValueError) as error:self.message.set_text(str(error));return
        if not items:self.rows.pack_start(Gtk.Label(label=tr('尚未安装模组包。'),xalign=0),False,False,0)
        for item in items:
            row=Gtk.Box(spacing=12);row.set_border_width(16);row.get_style_context().add_class('settings-card')
            row.pack_start(Gtk.Image.new_from_icon_name('application-x-addon-symbolic' if item['ok'] else 'dialog-warning-symbolic',Gtk.IconSize.LARGE_TOOLBAR),False,False,0)
            texts=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6);row.pack_start(texts,True,True,0)
            manifest=item['manifest'] or {};name=item['file'].name
            if item['ok']:
                name=manifest.get('name',manifest['id'])
                targets={c['target'] for c in components(manifest)}
                detail=' · '.join(tr(t) for key,t in [('taskbar','任务栏'),('desktop','桌面')] if key in targets)
                title=name+'  '+manifest['version'];detail+='\n'+item['file'].name
            else:title=name;detail='; '.join(item['errors'])
            texts.pack_start(Gtk.Label(label=title,xalign=0,wrap=True),False,False,0)
            subtitle=Gtk.Label(label=detail,xalign=0,wrap=True);subtitle.get_style_context().add_class('dim-label');texts.pack_start(subtitle,False,False,0)
            remove=Gtk.Button(label=tr('卸载'));remove.set_valign(Gtk.Align.CENTER);remove.connect('clicked',lambda _,p=item['file'],n=name:self.uninstall(p,n));row.pack_end(remove,False,False,0)
            self.rows.pack_start(row,False,False,0)
        self.rows.show_all()

    def install(self,*_):
        dialog=Gtk.FileChooserDialog(title=tr('安装／更新模组包'),transient_for=self.parent,action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(tr('取消'),Gtk.ResponseType.CANCEL,tr('安装'),Gtk.ResponseType.OK)
        file_filter=Gtk.FileFilter();file_filter.set_name('ADWS .mplg');file_filter.add_pattern('*.mplg');dialog.add_filter(file_filter)
        try:
            if dialog.run()==Gtk.ResponseType.OK:
                path=Path(dialog.get_filename());ok,errors,_=mplg.validate_package(path)
                if not ok:raise ValueError('; '.join(errors))
                mplg.copy_into(mplg.plugin_dir(),path)
                self.message.set_text(tr('模组已安装，两类组件可分别添加。'));self.refresh()
        except (OSError,ValueError) as error:self.message.set_text(str(error))
        finally:dialog.destroy()

    def uninstall(self,path,name):
        dialog=Gtk.MessageDialog(transient_for=self.parent,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.OK_CANCEL,text=tr('确定要卸载此模组包吗？'))
        dialog.format_secondary_text(name+'\n'+path.name+'\n'+tr('此操作同时影响该包的桌面和任务栏组件；保留组件配置，重新安装后可恢复。'))
        try:
            if dialog.run()!=Gtk.ResponseType.OK:return
            # Only the selected installed file/link is removed; never its target.
            if path.parent!=mplg.plugin_dir():raise ValueError('Package is outside the plugin directory')
            path.unlink();self.message.set_text(tr('模组包已卸载。'));self.refresh()
        except (OSError,ValueError) as error:self.message.set_text(str(error))
        finally:dialog.destroy()

"""Native controls and a source editor for an existing standalone Waybar."""
import threading
from pathlib import Path
from gi.repository import Gtk, GLib, Gdk
from adws_i18n import tr
from adws_settings_widgets import compact_switch
import adws_waybar as backend

class WaybarPage(Gtk.Box):
    def __init__(self,host):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=20)
        self.host=host;self.loading=True;self.original=None;self.modified=set();self.index=0;self.preset_style=None;self.imported_files=None
        from adws_system_settings import card,label
        files=card('Waybar 配置','管理独立 Waybar，保留现有主题、注释与组件定义。')
        self.config=Gtk.Entry();self.config.set_text(str(backend.default_config()))
        files.pack_start(host.config.row_widget(tr('配置文件'),self.config),False,False,0)
        line=Gtk.Box(spacing=10)
        load=Gtk.Button(label=tr('读取配置'));load.connect('clicked',self.load)
        self.refresh=Gtk.Button(label=tr('刷新 Waybar'));self.refresh.connect('clicked',self.reload)
        line.pack_start(load,False,False,0);line.pack_start(self.refresh,False,False,0)
        import_button=Gtk.Button(label=tr('导入配置文件…'));import_button.connect('clicked',self.import_config)
        line.pack_start(import_button,False,False,0)
        self.restart_button=Gtk.Button(label=tr('启动 / 重启 Waybar'));self.restart_button.connect('clicked',self.restart)
        line.pack_start(self.restart_button,False,False,0);files.pack_start(line,False,False,0)
        backup=Gtk.Button(label=tr('备份当前配置'));backup.connect('clicked',self.backup_current);line.pack_start(backup,False,False,0)
        restore=Gtk.Button(label=tr('恢复备份…'));restore.connect('clicked',self.restore_backup);line.pack_start(restore,False,False,0)
        self.autostart=compact_switch(Gtk.Switch());self.autostart.set_sensitive(False)
        files.pack_start(host.config.row_widget(tr('随 Niri 登录自启'),self.autostart),False,False,0)
        self.autostart.connect('notify::active',lambda *_:self.changed('autostart'))
        self.info=label('正在检测 Waybar…','dim-label');files.pack_start(self.info,False,False,0)
        self.pack_start(files,False,False,0)
        presets=card('Waybar 预设','载入只修改待应用内容；应用时备份并替换所选栏与样式。')
        from adws_waybar_presets import PRESETS
        self.preset=Gtk.ComboBoxText()
        for key,title,_ in PRESETS:self.preset.append(key,tr(title))
        self.preset.set_active_id('standard')
        presets.pack_start(host.config.row_widget(tr('预设'),self.preset),False,False,0)
        self.preset_description=label(PRESETS[0][2],'dim-label');presets.pack_start(self.preset_description,False,False,0)
        self.preset.connect('changed',self.preset_changed)
        actions=Gtk.Box(spacing=10)
        for title,handler in [('载入预设',self.load_preset),('预览所选预设',self.preview_preset),('关闭预览',self.stop_preview)]:
            button=Gtk.Button(label=tr(title));button.connect('clicked',handler);actions.pack_start(button,False,False,0)
        presets.pack_start(actions,False,False,0);self.pack_start(presets,False,False,0)
        self.controls=card('栏与布局','高度为 0 时跟随内容。拖动组件卡片调整布局。')
        self.bar=Gtk.ComboBoxText();self.bar.connect('changed',self.bar_changed)
        self.controls.pack_start(host.config.row_widget(tr('选择栏'),self.bar),False,False,0)
        self.position=Gtk.ComboBoxText()
        for value,title in [('top','顶部'),('bottom','底部'),('left','左侧'),('right','右侧')]:self.position.append(value,tr(title))
        self.controls.pack_start(host.config.row_widget(tr('位置'),self.position),False,False,0)
        self.widgets={'position':self.position}
        for key,title,maximum in [('height','高度',256),('spacing','组件间距',100),('margin-top','顶部边距',200),('margin-bottom','底部边距',200),('margin-left','左侧边距',200),('margin-right','右侧边距',200)]:
            widget=Gtk.SpinButton.new_with_range(0,maximum,1);self.widgets[key]=widget
            self.controls.pack_start(host.config.row_widget(tr(title),widget),False,False,0)
        for key,title in [('fixed-center','中间区域居中'),('exclusive','为窗口预留空间')]:
            widget=compact_switch(Gtk.Switch());self.widgets[key]=widget
            self.controls.pack_start(host.config.row_widget(tr(title),widget),False,False,0)
        for key,widget in self.widgets.items():
            event='notify::active' if isinstance(widget,Gtk.Switch) else 'value-changed' if isinstance(widget,Gtk.SpinButton) else 'changed'
            widget.connect(event,lambda *_,key=key:self.changed(key))
        self.updater=Gtk.ComboBoxText()
        for value,title in [('yay','yay -Syu'),('paru','paru -Syu'),('custom','自定义命令')]:self.updater.append(value,tr(title))
        self.update_command=Gtk.Entry();self.update_command.set_placeholder_text(tr('请输入自定义更新命令'))
        self.controls.pack_start(host.config.row_widget(tr('系统更新按钮'),self.updater),False,False,0)
        self.command_row=host.config.row_widget(tr('更新命令'),self.update_command)
        self.command_row.show_all()
        self.command_row.set_no_show_all(True);self.command_row.hide()
        self.controls.pack_start(self.command_row,False,False,0)
        self.updater.connect('changed',self.updater_changed)
        self.update_command.connect('changed',lambda *_:self.changed('update-action'))
        from adws_waybar_modules import ModuleEditor
        self.modules=ModuleEditor(lambda:self.changed('module-layout'))
        self.controls.pack_start(self.modules,False,False,0)
        self.controls.reorder_child(self.modules,4)
        self.pack_start(self.controls,False,False,0)
        self.appearance=card('颜色与样式','默认保留系统配色；自定义颜色仅追加独立覆盖，不改动原有主题。')
        self.style_path=Gtk.Entry();self.style_path.set_editable(False)
        self.appearance.pack_start(host.config.row_widget(tr('样式文件'),self.style_path),False,False,0)
        self.style_path.connect('changed',lambda *_:self.changed('appearance'))
        self.follow=compact_switch(Gtk.Switch());self.follow.connect('notify::active',self.colors_changed)
        self.appearance.pack_start(host.config.row_widget(tr('跟随系统配色'),self.follow),False,False,0)
        self.font_follow=compact_switch(Gtk.Switch());self.font_follow.set_active(True)
        self.appearance.pack_start(host.config.row_widget(tr('跟随系统字体'),self.font_follow),False,False,0)
        self.font_button=Gtk.FontButton();self.font_button.set_level(Gtk.FontChooserLevel.FAMILY | Gtk.FontChooserLevel.SIZE);self.font_button.set_use_font(True);self.font_button.set_use_size(True);self.font_button.set_sensitive(False)
        self.appearance.pack_start(host.config.row_widget(tr('文字字体'),self.font_button),False,False,0)
        self.font_follow.connect('notify::active',lambda *_:(self.font_button.set_sensitive(not self.font_follow.get_active()),self.changed('font')))
        self.font_button.connect('font-set',lambda *_:self.changed('font'))
        self.color_controls=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10)
        self.color_buttons={}
        for key,title in [('background','组件背景'),('foreground','文字颜色'),('hover','悬停背景'),('primary','主强调色'),('secondary','次强调色'),('tertiary','第三强调色')]:
            button=Gtk.ColorButton();button.set_use_alpha(True)
            button.connect('color-set',lambda *_:self.changed('appearance'))
            self.color_buttons[key]=button
            self.color_controls.pack_start(host.config.row_widget(tr(title),button),False,False,0)
        self.color_controls.show_all();self.color_controls.set_no_show_all(True)
        self.appearance.pack_start(self.color_controls,False,False,0)
        self.appearance.set_sensitive(False);self.pack_start(self.appearance,False,False,0)
        self.advanced=Gtk.Expander(label=tr('高级：编辑 JSONC 配置'))
        self.editor=Gtk.TextView();self.editor.set_monospace(True);self.editor.set_wrap_mode(Gtk.WrapMode.NONE)
        self.buffer=self.editor.get_buffer();self.buffer.connect('changed',lambda *_:self.changed('source'))
        scroll=Gtk.ScrolledWindow();scroll.set_size_request(-1,300);scroll.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.AUTOMATIC);scroll.add(self.editor)
        self.advanced.add(scroll);self.pack_start(self.advanced,False,False,0)
        self.controls.set_sensitive(False);self.advanced.set_sensitive(False);self.appearance.set_sensitive(False);self.refresh.set_sensitive(False);self.restart_button.set_sensitive(False)
        self.config.connect('changed',self.path_changed)
        def detect():
            result=backend.detect()
            def finish():
                if self.host.closed:return False
                self.config.set_text(str(result['config']));self.load();return False
            GLib.idle_add(finish)
        threading.Thread(target=detect,daemon=True).start()

    def path_changed(self,*_):
        if self.loading:return
        self.controls.set_sensitive(False);self.advanced.set_sensitive(False);self.appearance.set_sensitive(False);self.refresh.set_sensitive(False);self.restart_button.set_sensitive(False)
        self.host.update_footer()
        self.info.set_text(tr('点击重新加载以读取所选配置。'))

    def load(self,*_):
        if 'waybar' in self.host.dirty and not self.host.confirm('丢弃尚未应用的 Waybar 修改？'):return
        path=Path(self.config.get_text()).expanduser()
        if backend.is_adws(path):self.host.error(tr('请使用任务栏外观设置修改 ADWS 底栏。'));return
        if not path.is_file():
            self.loading=False
            self.info.set_text(tr('未找到 Waybar 配置，可填写现有配置文件路径后重新加载。'))
            return
        result={}
        def job():
            result['text']=path.read_text();result['data']=backend.decode(result['text'])
            result['catalog']=backend.module_catalog(path,result['data'])
            result['style']=backend.load_style(path)
            result['autostart']=backend.autostart_status(path)
            result['running']=len([p for p in backend.processes() if p['config'].resolve()==path.resolve()])
        def done():
            self.loading=True
            try:
                self.original_autostart=result['autostart']['enabled'];self.autostart.set_active(self.original_autostart);self.autostart.set_sensitive(result['autostart']['available'])
                self.original=result['text'];self.loaded_path=path;self.data=result['data'];self.catalog=result['catalog'];self.modified.clear();self.preset_style=None;self.imported_files=None
                self.style_original=result['style']['text'];self.loaded_style=result['style']['path']
                self.style_path.set_text(str(self.loaded_style))
                fonts=result['style'].get('font_settings',{});self.font_follow.set_active(fonts.get('follow',True))
                self.font_button.set_font_name((str(fonts.get('family','Sans'))+' '+str(fonts.get('size',10))) if fonts else Gtk.Settings.get_default().get_property('gtk-font-name'))
                settings=result['style']['settings'];self.follow.set_active(settings.get('follow',True))
                self.color_controls.set_visible(not self.follow.get_active())
                for key,value in [('background','#303030'),('foreground','#ffffff'),('hover','#555555'),('primary','#ffb59e'),('secondary','#eedbcf'),('tertiary','#e8c6df')]:
                    rgba=Gdk.RGBA();rgba.parse(settings.get(key,value));self.color_buttons[key].set_rgba(rgba)
                self.appearance.set_sensitive(True)
                self.buffer.set_text(self.original);self.bar.remove_all()
                bars=self.data if isinstance(self.data,list) else [self.data]
                for i,bar in enumerate(bars):self.bar.append(str(i),str(bar.get('name') or tr('Waybar 栏'))+' '+str(i+1)+' · '+str(bar.get('position','top')))
                self.bar.set_active(0);self.index=0;self.fill()
                self.controls.set_sensitive(True);self.advanced.set_sensitive(True);self.refresh.set_sensitive(True);self.restart_button.set_sensitive(True)
                self.info.set_text(tr('已读取配置；运行中的匹配实例：%s') % result['running'])
                self.host.dirty.discard('waybar')
            finally:self.loading=False
        self.host.run_worker(job,done)

    def import_config(self,*_):
        if self.original is None:self.host.error(tr('请先加载当前配置。'));return
        if 'waybar' in self.host.dirty and not self.host.confirm('丢弃尚未应用的 Waybar 修改？'):return
        chooser=Gtk.FileChooserDialog(title=tr('导入 Waybar 配置'),transient_for=self.get_toplevel(),action=Gtk.FileChooserAction.OPEN)
        chooser.add_buttons(tr('取消'),Gtk.ResponseType.CANCEL,tr('导入'),Gtk.ResponseType.OK)
        file_filter=Gtk.FileFilter();file_filter.set_name(tr('Waybar 配置文件'));file_filter.add_pattern('*.json');file_filter.add_pattern('*.jsonc');file_filter.add_pattern('config');chooser.add_filter(file_filter)
        all_files=Gtk.FileFilter();all_files.set_name(tr('所有文件'));all_files.add_pattern('*');chooser.add_filter(all_files)
        response=chooser.run();path=chooser.get_filename();chooser.destroy()
        if response!=Gtk.ResponseType.OK or not path:return
        css=Path(path).parent/'style.css'
        if not css.is_file():
            chooser=Gtk.FileChooserDialog(title=tr('选择配套 CSS'),transient_for=self.get_toplevel(),action=Gtk.FileChooserAction.OPEN)
            chooser.add_buttons(tr('取消'),Gtk.ResponseType.CANCEL,tr('导入'),Gtk.ResponseType.OK)
            response=chooser.run();chosen=chooser.get_filename();chooser.destroy()
            if response!=Gtk.ResponseType.OK or not chosen:return
            css=Path(chosen)
        self.stage_import(path,css)

    def stage_import(self,path,source_style=None):
        result={}
        def job():result.update(backend.import_bundle(path,self.loaded_path,self.loaded_style,source_style))
        def done():
            self.loading=True
            try:
                self.data=result['data'];self.catalog=result['catalog'];self.buffer.set_text(result['text'])
                self.modified.clear();self.preset_style=result['style'];self.imported_files=result['files'];self.bar.remove_all();self.index=0
                for i,bar in enumerate(self.data if isinstance(self.data,list) else [self.data]):
                    self.bar.append(str(i),str(bar.get('name') or tr('Waybar 栏'))+' '+str(i+1))
                self.bar.set_active(0);self.fill();self.controls.set_sensitive(True)
            finally:self.loading=False
            self.changed('preset')
            self.info.set_text(tr('已暂存整套配置（%s 个文件）；应用前不会修改当前配置。') % result['count'])
        self.host.run_worker(job,done)

    def fill(self):
        old=self.loading;self.loading=True
        try:
            bar=(self.data if isinstance(self.data,list) else [self.data])[self.index]
            from adws_waybar_presets import PRESETS
            self.preset.set_active_id(bar.get('adws-preset') if bar.get('adws-preset') in {item[0] for item in PRESETS} else 'standard')
            from adws_topbar_update import module_settings
            manager,custom=module_settings(bar.get('custom/updates',{}))
            if manager=='auto':
                import shutil
                manager='yay' if shutil.which('yay') or not shutil.which('paru') else 'paru'
            self.updater.set_active_id(manager);self.update_command.set_text(custom)
            self.command_row.set_visible(manager=='custom')
            self.modules.set_data(bar,self.catalog)
            for key,widget in self.widgets.items():
                value=bar.get(key)
                if isinstance(widget,Gtk.Switch):widget.set_active(bar.get(key,True))
                elif isinstance(widget,Gtk.SpinButton):widget.set_value(value if isinstance(value,(float,int)) else 0)
                elif isinstance(widget,Gtk.ComboBoxText):widget.set_active_id(value or 'top')
                else:widget.set_text(', '.join(value) if isinstance(value,list) and all(isinstance(v,str) for v in value) else '')
        finally:self.loading=old

    def bar_changed(self,*_):
        if self.loading or not self.bar.get_active_id():return
        self.sync_source();self.index=int(self.bar.get_active_id());self.fill()

    def changed(self,key):
        if self.loading:return
        self.modified.add(key);self.host.mark_dirty('waybar')
        if key=='source':self.controls.set_sensitive(False)

    def updater_changed(self,*_):
        self.command_row.set_visible(self.updater.get_active_id()=='custom')
        if self.updater.get_active_id()=='custom':self.update_command.show()
        self.changed('update-action')

    def colors_changed(self,*_):
        self.color_controls.set_visible(not self.follow.get_active())
        self.changed('appearance')

    def content(self):
        text=self.buffer.get_text(*self.buffer.get_bounds(),True)
        if 'source' in self.modified:return text
        changes={}
        for key in self.modified:
            if key in ('appearance','preset','font','autostart'):continue
            if key=='module-layout':
                changes.update(self.modules.values)
                continue
            if key=='update-action':
                from adws_topbar_update import configure_module
                bar=(self.data if isinstance(self.data,list) else [self.data])[self.index]
                changes['custom/updates']=configure_module(bar.get('custom/updates',{}),self.updater.get_active_id() or 'auto',self.update_command.get_text(),Path(__file__).resolve().parents[1])
                continue
            widget=self.widgets[key]
            if isinstance(widget,Gtk.Switch):value=widget.get_active()
            elif isinstance(widget,Gtk.SpinButton):value=widget.get_value_as_int()
            elif isinstance(widget,Gtk.ComboBoxText):value=widget.get_active_id()
            else:value=[v for v in __import__('re').split(r'[\s,]+',widget.get_text()) if v]
            changes[key]=value
        return backend.patch(text,self.index,changes) if changes else text

    def sync_source(self):
        content=self.content();self.data=backend.decode(content)
        old=self.loading;self.loading=True
        self.buffer.set_text(content);self.modified.clear();self.loading=old

    def apply(self):
        if self.original is None:return
        if Path(self.config.get_text()).expanduser() != self.loaded_path:
            raise ValueError(tr('请先重新加载所选配置。'))
        content=self.content();backend.decode(content);result={}
        style_content=self.preset_style
        style_path=Path(self.style_path.get_text()).expanduser()
        if 'appearance' in self.modified or ('module-layout' in self.modified and not self.follow.get_active()):
            if style_path!=self.loaded_style:raise ValueError(tr('请重新加载配置后再修改样式文件。'))
            settings={'follow':self.follow.get_active(),**{key:button.get_rgba().to_string() for key,button in self.color_buttons.items()}}
            style_content=backend.color_style(style_content if style_content is not None else self.style_original,settings,backend.decode(content))
            provider=Gtk.CssProvider();provider.load_from_data(backend.color_style('',settings,backend.decode(content)).encode())
        if 'font' in self.modified or (self.preset_style is not None and self.imported_files is None):
            from gi.repository import Pango
            description=Pango.FontDescription.from_string(Gtk.Settings.get_default().get_property('gtk-font-name') if self.font_follow.get_active() else self.font_button.get_font_name())
            size=(description.get_size()/Pango.SCALE) or 10
            if description.get_size_is_absolute():size*=.75
            style_content=backend.font_style(style_content if style_content is not None else self.style_original,{'follow':self.font_follow.get_active(),'family':description.get_family() or 'Sans','size':size})
        if (self.preset_style is not None and self.imported_files is None) or self.modified.intersection({'height','source','module-layout'}):
            style_content=backend.geometry_style(style_content if style_content is not None else self.style_original,backend.decode(content))
        startup_changed='autostart' in self.modified;startup_enabled=self.autostart.get_active()
        def job():
            if self.imported_files is not None:result.update(backend.save_bundle(self.loaded_path,self.original,content,style_path,self.style_original,style_content,self.imported_files))
            elif style_content is None:result.update(backend.save(self.loaded_path,self.original,content))
            else:result.update(backend.save_with_style(self.loaded_path,self.original,content,style_path,self.style_original,style_content))
            if startup_changed:backend.set_autostart(self.loaded_path,style_path,startup_enabled)
        def done():
            self.original_autostart=startup_enabled
            self.original=content;self.preset_style=None;self.imported_files=None
            if style_content is not None:self.style_original=style_content
            self.sync_source();self.fill();self.controls.set_sensitive(True)
            self.host.dirty.discard('waybar')
            self.info.set_text((tr('已保存并刷新 Waybar。') if result['reloaded'] else tr('已保存配置；请点击启动 / 重启 Waybar 使其生效。'))+' '+tr('备份：%s') % result['backup'])
            self.host.apply_changes()
        self.host.run_worker(job,done)

    def reload(self,*_):
        if 'waybar' in self.host.dirty:self.host.error(tr('请先应用或重新加载尚未保存的修改。'));return
        result={}
        self.host.run_worker(lambda:result.update(count=backend.reload(self.loaded_path)),lambda:self.info.set_text((tr('已刷新实例：%s') % result['count']) if result['count'] else tr('没有可刷新的匹配实例，请点击启动 / 重启 Waybar。')))

    def restart(self,*_):
        if 'waybar' in self.host.dirty:self.host.error(tr('请先应用或重新加载尚未保存的修改。'));return
        if self.original is None or Path(self.config.get_text()).expanduser()!=self.loaded_path:
            self.host.error(tr('请先重新加载所选配置。'));return
        result={}
        self.host.run_worker(lambda:result.update(backend.restart(self.loaded_path,self.loaded_style)),lambda:self.info.set_text(tr('Waybar 已启动，进程：%s') % result['pid']))

    def stop_preview(self,*_):
        from adws_topbar import stop_preview
        self.host.run_worker(stop_preview,lambda:self.info.set_text(tr('已关闭临时预览。')))

    def preset_changed(self,*_):
        from adws_waybar_presets import PRESETS
        key=self.preset.get_active_id()
        self.preset_description.set_text(tr(next(item[2] for item in PRESETS if item[0]==key)))

    def load_preset(self,*_):
        if self.original is None:self.host.error(tr('请先加载当前配置。'));return
        if Path(self.config.get_text()).expanduser()!=self.loaded_path:self.host.error(tr('请先重新加载所选配置。'));return
        if self.modified and not self.host.confirm('替换尚未应用的 Waybar 修改？'):return
        from adws_waybar_presets import rendered
        text,css=rendered(self.preset.get_active_id())
        content=backend.replace_bar(self.original if 'source' in self.modified else self.content(),self.index,backend.decode(text))
        colors=backend.folder()/'colors.css'
        if not colors.is_file():colors=Path(__file__).resolve().parents[1]/'config/waybar/colors.css'
        import json
        css=css.replace('@import "colors.css";', '@import '+json.dumps(str(colors))+';')
        self.loading=True
        try:
            self.data=backend.decode(content);self.buffer.set_text(content);self.modified.clear();self.preset_style=css;self.imported_files=None
            self.follow.set_active(True);self.color_controls.hide();self.fill();self.controls.set_sensitive(True)
        finally:self.loading=False
        self.changed('preset');self.info.set_text(tr('预设已载入；点击应用后生效。'))

    def preview_preset(self,*_):
        from adws_topbar import preview
        key=self.preset.get_active_id()
        self.host.run_worker(lambda:preview(preset=key),lambda:self.info.set_text(tr('已打开独立预览，原有 Waybar 保持不变。')))

    def backup_current(self,*_):
        if self.original is None:self.host.error(tr('请先加载当前配置。'));return
        result={}
        self.host.run_worker(lambda:result.update(path=backend.backup_current(self.loaded_path,self.loaded_style)),lambda:self.info.set_text(tr('当前配置已备份：%s') % result['path']))

    def restore_backup(self,*_):
        if self.original is None:self.host.error(tr('请先加载当前配置。'));return
        backups=backend.list_backups(self.loaded_path)
        if not backups:self.host.error(tr('没有可恢复的备份。'));return
        dialog=Gtk.Dialog(title=tr('恢复 Waybar 备份'),transient_for=self.get_toplevel(),modal=True)
        dialog.add_buttons(tr('取消'),Gtk.ResponseType.CANCEL,tr('恢复'),Gtk.ResponseType.OK)
        choice=Gtk.ComboBoxText()
        for path in backups:choice.append(str(path),path.name+(' · '+tr('旧版部分备份') if path.is_file() or not (path/'manifest.json').exists() else ''))
        choice.set_active(0);choice.set_margin_top(16);choice.set_margin_bottom(16);choice.set_margin_start(16);choice.set_margin_end(16)
        dialog.get_content_area().add(choice);dialog.show_all()
        response=dialog.run();chosen=choice.get_active_id();dialog.destroy()
        if response!=Gtk.ResponseType.OK or not chosen:return
        if not self.host.confirm(tr('恢复该备份并重启 Waybar？当前配置会先备份，未应用的修改将被丢弃。')):return
        result={}
        def job():result.update(backend.restore_backup(chosen,self.loaded_path,self.loaded_style))
        def done():
            self.host.dirty.discard('waybar');self.load()
        self.host.run_worker(job,done)

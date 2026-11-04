"""Desktop-only component management using the shared .mplg installation directory."""
from gi.repository import Gtk, Gdk, GLib
from adws_i18n import tr
import adws_desktop_widgets_model as model


class DesktopWidgetsSettings(Gtk.Box):
    def __init__(self,parent):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=16)
        self.output_map=[];self.output_loading=False
        self.parent=parent;self.health_source=0;self.health_labels={};self.closed=False
        description=Gtk.Label(label=tr('桌面组件与任务栏组件独立配置；一个模组包可同时提供两类组件。拖动桌面组件标题移动，右下角调整大小，组件菜单中可锁定。'),xalign=0,wrap=True)
        self.pack_start(description,False,False,0)
        toolbar=Gtk.Box(spacing=10);self.pack_start(toolbar,False,False,0)
        self.choice=Gtk.ComboBoxText();toolbar.pack_start(self.choice,True,True,0)
        add=Gtk.Button(label=tr('添加到桌面'));add.connect('clicked',self.add);toolbar.pack_start(add,False,False,0)
        refresh=Gtk.Button.new_from_icon_name('view-refresh-symbolic',Gtk.IconSize.BUTTON);refresh.set_tooltip_text(tr('刷新组件'));refresh.connect('clicked',lambda *_:self.render());toolbar.pack_end(refresh,False,False,0)
        self.message=Gtk.Label(xalign=0,wrap=True);self.pack_start(self.message,False,False,0)
        self.rows=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12);self.pack_start(self.rows,False,False,0)
        self.connect('map',self.map_page);self.connect('unmap',self.unmap_page);self.connect('destroy',self.destroy_page)
        self.render()

    def read(self):
        self.data=model.load();self.available=model.catalog()

    def error(self,error):self.message.set_text(str(error))

    def render(self):
        try:self.read()
        except (OSError,ValueError) as error:self.error(error);return
        previous=self.choice.get_active_id();self.choice.remove_all()
        for definition in self.available:
            if not definition.get('selectable',True):continue
            title=tr(definition['name'])
            self.choice.append(definition['key'],title)
        if previous:self.choice.set_active_id(previous)
        if self.choice.get_active()<0:self.choice.set_active(0)
        for child in self.rows.get_children():child.destroy()
        self.health_labels={};lookup={v['key']:v for v in self.available}
        if not self.data['instances']:
            self.rows.pack_start(Gtk.Label(label=tr('尚未添加桌面组件。'),xalign=0),False,False,0)
        for row in self.data['instances']:
            box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10);box.set_border_width(16);box.get_style_context().add_class('settings-card')
            head=Gtk.Box(spacing=12);box.pack_start(head,False,False,0)
            definition=lookup.get(row['component'],{'name':'组件未安装','icon':'dialog-warning-symbolic'})
            head.pack_start(Gtk.Image.new_from_icon_name(definition.get('icon','application-x-addon-symbolic'),Gtk.IconSize.LARGE_TOOLBAR),False,False,0)
            title=Gtk.Label(label=tr(definition['name']),xalign=0);head.pack_start(title,True,True,0)
            enabled=Gtk.Switch();enabled.set_halign(Gtk.Align.END);enabled.set_valign(Gtk.Align.CENTER);enabled.set_active(row['enabled']);enabled.connect('notify::active',lambda w,_,identity=row['instance']:self.edit(identity,enabled=w.get_active()));head.pack_end(enabled,False,False,0)
            if row['component'] not in lookup:title.set_tooltip_text(row['component'])
            health=Gtk.Label(xalign=0,wrap=True)
            warning_css=Gtk.CssProvider();warning_css.load_from_data(b'label.warning {color:#e9bc46;}')
            health.get_style_context().add_provider(warning_css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+10)
            self.health_labels[row['instance']]=health;box.pack_start(health,False,False,0)
            grid=Gtk.Grid(column_spacing=12,row_spacing=10);box.pack_start(grid,False,False,0)
            for col,(key,caption,low,high) in enumerate([('width','宽度',200,2000),('height','高度',120,1600)]):
                field=Gtk.SpinButton.new_with_range(low,high,1);field.set_value(row[key]);field.set_width_chars(6)
                field.connect('value-changed',lambda w,k=key,identity=row['instance']:self.edit(identity,**{k:w.get_value_as_int()}))
                grid.attach(Gtk.Label(label=tr(caption),xalign=0),col,0,1,1);grid.attach(field,col,1,1,1)
            footer=Gtk.Box(spacing=12);box.pack_start(footer,False,False,0)
            monitor,is_primary=self.screen_context(row)
            choices=Gtk.ListStore(str,str,bool)
            for scope,caption in [('screen','仅限本屏幕'),('primary','仅限主屏幕'),('all','所有屏幕的相同位置')]:
                choices.append([scope,tr(caption),scope!='primary' or is_primary])
            output=Gtk.ComboBox.new_with_model(choices);output.set_id_column(0)
            renderer=Gtk.CellRendererText();output.pack_start(renderer,True);output.add_attribute(renderer,'text',1);output.add_attribute(renderer,'sensitive',2)
            output.set_active_id(row['monitor_scope'])
            output.connect('changed',lambda w,identity=row['instance'],m=monitor,p=is_primary:self.change_scope(identity,w.get_active_id(),m,p))
            footer.pack_start(output,True,True,0)
            lock=Gtk.CheckButton(label=tr('锁定位置'));lock.set_active(row['locked']);lock.connect('toggled',lambda w,identity=row['instance']:self.edit(identity,locked=w.get_active()));footer.pack_start(lock,False,False,0)
            if definition.get('kind')=='plugin':
                settings=Gtk.Button(label=tr('组件设置'));settings.connect('clicked',lambda _,identity=row['instance']:self.plugin_settings(identity));footer.pack_start(settings,False,False,0)
            css=Gtk.Button(label=tr('自定义 CSS'));css.connect('clicked',lambda _,identity=row['instance']:self.edit_css(identity));footer.pack_start(css,False,False,0)
            duplicate=Gtk.Button(label=tr('复制组件'));duplicate.set_sensitive(row['component'] in lookup and definition.get('repeatable',True));duplicate.connect('clicked',lambda _,identity=row['instance']:self.duplicate(identity));footer.pack_start(duplicate,False,False,0)
            remove=Gtk.Button(label=tr('移除'));remove.connect('clicked',lambda _,identity=row['instance']:self.remove(identity));footer.pack_end(remove,False,False,0)
            self.rows.pack_start(box,False,False,0)
        from adws_settings_widgets import guard_combo_scroll
        guard_combo_scroll(self.rows)
        self.rows.show_all();self.update_health()

    def screen_context(self,row):
        from desktop_layer.app import connector_name
        display=Gdk.Display.get_default()
        if not display or not display.get_n_monitors():return row['monitor'],row['monitor_scope']=='primary'
        from types import SimpleNamespace
        from adws_desktop_preferences import choose
        views=[]
        for index in range(display.get_n_monitors()):
            monitor=display.get_monitor(index);connector=connector_name(monitor,index)
            geometry=monitor.get_geometry()
            output=next((item for item in self.output_map if item['name']==connector),None)
            if output is None:
                matches=[item for item in self.output_map if item['x']==geometry.x and item['y']==geometry.y]
                output=matches[0] if len(matches)==1 else {}
            views.append(SimpleNamespace(monitor=monitor,monitor_key=output.get('monitor_id',connector),connector_key=connector))
        primary=choose(views,display.get_primary_monitor())
        at_window=display.get_monitor_at_window(self.get_toplevel().get_window()) if self.get_toplevel().get_window() else primary.monitor
        view=next((v for v in views if v.monitor==at_window),primary)
        if row['monitor_scope']=='screen':
            matched=next((v for v in views if row['monitor'] in (v.monitor_key,v.connector_key)),None)
            if matched is None:return row['monitor'],False
            view=matched
        elif row['monitor_scope']=='primary':view=primary
        return view.monitor_key,view is primary

    def refresh_output_map(self):
        if self.output_loading:return
        self.output_loading=True
        def read():
            try:
                from adws_display import outputs,detect_session
                result=outputs(detect_session())
            except Exception:result=[]
            def ready():
                self.output_loading=False
                if not self.closed:
                    self.output_map=result;self.render()
                return False
            GLib.idle_add(ready)
        import threading
        threading.Thread(target=read,daemon=True,name='adws-widget-output-map').start()

    def change_scope(self,identity,scope,monitor,is_primary):
        try:self.edit(identity,**model.scope_values(scope,monitor,is_primary))
        except ValueError as error:self.error(error)

    def edit(self,identity,**values):
        try:
            # Always reload before writing so dragging or note edits are preserved.
            def change(data):
                row=next((r for r in data['instances'] if r['instance']==identity),None)
                if row is not None:row.update(values)
                return model.validate_instances(data,self.available)
            model.mutate(change);self.message.set_text(tr('桌面组件已更新。'))
        except (OSError,ValueError) as error:self.error(error)

    def add(self,*_):
        try:
            self.read();definition=next(d for d in self.available if d['key']==self.choice.get_active_id())
            def add(data):
                result=model.add(data,definition)
                return result
            model.mutate(add);self.message.set_text(tr('已添加到桌面。'));self.render()
        except (OSError,ValueError,StopIteration) as error:self.error(error)

    def remove(self,identity):
        try:
            def change(data):
                data['instances']=[r for r in data['instances'] if r['instance']!=identity];return data
            model.mutate(change);self.render()
        except (OSError,ValueError) as error:self.error(error)

    def plugin_settings(self,identity):
        from adws_plugin_settings import SettingsDialog,validate_settings
        self.read();row=next(r for r in self.data['instances'] if r['instance']==identity)
        definition=next(d for d in self.available if d['key']==row['component'])
        manifest=definition['manifest']
        dialog=SettingsDialog(self.parent,manifest['name'],manifest.get('settingsSchema',[]),row['settings'],validator=validate_settings if manifest.get('packageId')=='org.AkiACG_Community.NCMLyricsBar' else None)
        values=dialog.run()
        if values is not None:self.edit(identity,settings=values)

    def edit_css(self,identity):
        from adws_widget_style import edit
        row=next(r for r in model.load()['instances'] if r['instance']==identity)
        css=edit(self.parent,row.get('css',''))
        if css is not None:self.edit(identity,css=css)

    def duplicate(self,identity):
        try:
            self.read();model.mutate(lambda data:model.duplicate(data,identity,self.available));self.render()
        except (OSError,ValueError,StopIteration) as error:self.error(error)

    def update_health(self):
        from adws_plugin_watchdog import health
        for identity,label in self.health_labels.items():
            record=health(identity)
            failed=record and record.get('state')=='failed'
            label.set_text(tr('组件运行异常')+' · '+str(record.get('reason','')) if failed else '')
            context=label.get_style_context();(context.add_class if failed else context.remove_class)('warning')
        return not self.closed

    def map_page(self,*_):
        self.render();self.refresh_output_map()
        if not self.health_source:self.health_source=GLib.timeout_add_seconds(2,self.update_health)

    def unmap_page(self,*_):
        if self.health_source:GLib.source_remove(self.health_source);self.health_source=0

    def destroy_page(self,*_):self.closed=True;self.unmap_page()

"""Folder groups on per-monitor desktop surfaces, with shared change-driven scans."""
import copy
import cairo
from concurrent.futures import ThreadPoolExecutor
import json
import logging
from pathlib import Path

from gi.repository import Gtk, Gdk, Gio, GLib, Pango, GdkPixbuf
from adws_i18n import tr
import adws_desktop_groups_model as model
import adws_desktop_preferences as preferences
from desktop_layer.model import scan_desktop, atomic_save_json

LOG=logging.getLogger('adws.desktop-groups')
TARGET='application/x-adws-desktop-group'
ICON_TARGET='application/x-adws-desktop-group-icon'


class Manager:
    def __init__(self, application, path, directory, old_positions):
        self.application=application; self.path=path; self.directory=directory; self.layers=[]; self.closed=False
        self.images={}; self.watchers=[]; self.pending=0; self.generation=0; self.cache={};self.loading=False;self.again=False
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='adws-folders')
        self.data=model.load(path,directory,old_positions)
        if not preferences.path().exists() and self.data.get('default_monitor','primary') != 'primary':
            preferences.save(self.data['default_monitor'])
        self.data['default_monitor']=preferences.load()['default_monitor']
        preferences.path().parent.mkdir(parents=True,exist_ok=True)
        self.preference_watch=Gio.File.new_for_path(str(preferences.path().parent)).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES,None)
        self.preference_watch.connect('changed',self.preference_changed)
        self.palette=None;self.theme_pending=0;self.theme_watchers=[]
        self.provider=Gtk.CssProvider();self.reload_theme()
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),self.provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+10)
        self.save();self.watch();self.watch_theme();self.refresh()

    def reload_theme(self):
        self.theme_pending=0
        if self.closed:return False
        from desktop_layer.app import read_palette_colors
        palette=read_palette_colors()
        if palette==self.palette:return False
        self.palette=palette
        foreground=self.palette.get('on_surface','#eceaf5')
        background=self.palette.get('surface','#24242c')
        accent=self.palette.get('primary','#b8b9ff')
        field=self.palette.get('surface_container_high','#353541')
        on_accent=self.palette.get('on_primary','#171836')
        css = '.adws-folder-group, .adws-folder-group label { color:'+foreground+'; } .adws-folder-group button { background-image:none; background-color:transparent; border:0; box-shadow:none; color:'+foreground+'; } .adws-folder-group button:hover { background-color:alpha('+foreground+',0.12); border-radius:10px; }'
        css += ('window.adws-group-editor, .adws-group-editor headerbar { background-image:none; background-color:'+background+'; color:'+foreground+'; }'
                '.adws-group-editor headerbar { padding:8px 12px; border-bottom:1px solid alpha('+foreground+',0.10); box-shadow:none; }'
                '.adws-group-editor label { color:'+foreground+'; }'
                '.adws-group-editor entry, .adws-group-editor spinbutton, .adws-group-editor button { border-radius:10px; background-image:none; background-color:'+field+'; color:'+foreground+'; }'
                '.adws-group-editor stackswitcher button { padding:7px 20px; }'
                '.adws-group-editor stackswitcher button:checked { background-image:none; background-color:alpha('+accent+',0.18); color:'+accent+'; }'
                '.adws-group-editor button.suggested-action { background-color:'+accent+'; color:'+on_accent+'; }'
                '.adws-group-editor .dim-label { opacity:0.65; }')
        self.provider.load_from_data(css.encode())
        for layer in self.layers:
            for card in layer.cards:card.queue_draw()
        return False

    def watch_theme(self):
        from desktop_layer.app import palette_file_candidates
        for watcher in self.theme_watchers:watcher.cancel()
        self.theme_watchers=[]
        paths=set(palette_file_candidates())
        paths.update(path.resolve() for path in list(paths))
        self.theme_paths=paths
        folders=set()
        for path in paths:
            parent=path.parent
            while not parent.is_dir() and parent!=parent.parent:parent=parent.parent
            folders.add(parent)
        for folder in folders:
            try:
                watcher=Gio.File.new_for_path(str(folder)).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES,None)
                watcher.connect('changed',self.theme_changed);self.theme_watchers.append(watcher)
            except GLib.Error as error:LOG.warning('Group theme watch: %s',error)

    def theme_changed(self,watcher,file,other,event):
        if self.closed:return
        touched=[Path(f.get_path()) for f in (file,other) if f and f.get_path()]
        if not any(path==p or path.is_relative_to(p) for path in self.theme_paths for p in touched):return
        if not self.theme_pending:self.theme_pending=GLib.timeout_add(120,self.apply_theme_change)

    def apply_theme_change(self):
        self.reload_theme();self.watch_theme();return False

    def preference_changed(self, watcher, file, other, event):
        if self.closed or not any(f and f.get_path()==str(preferences.path()) for f in (file,other)):
            return
        requested=preferences.load()['default_monitor']
        if requested==self.data.get('default_monitor'):return
        self.data['default_monitor']=requested
        self.save();self.render()
        widgets=getattr(self.application,'widget_manager',None)
        if widgets:
            for controller in list(widgets.controllers):controller.render()

    def save(self):
        model.validate(self.data)
        payload=json.dumps(self.data,ensure_ascii=False,sort_keys=True)
        if payload != getattr(self,'saved_payload',None):
            atomic_save_json(self.path,self.data)
            self.saved_payload=payload

    def watch(self):
        for watcher in self.watchers: watcher.cancel()
        self.watchers=[]
        directories={Path(row['directory']) for row in self.data['groups']}
        watched=set()
        for directory in directories:
            # A parent watch catches removal/recreation, including removable disks.
            parent=directory.parent
            while not parent.is_dir() and parent!=parent.parent: parent=parent.parent
            for path in (directory,parent):
                if path in watched or not path.is_dir():continue
                watched.add(path)
                watcher=Gio.File.new_for_path(str(path)).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES,None)
                watcher.connect('changed',self.changed);self.watchers.append(watcher)

    def changed(self,watcher,file,other,event):
        paths=[Path(f.get_path()) for f in (file,other) if f is not None and f.get_path() and Path(f.get_path()) != self.path]
        paths=[path for path in paths if not (path.parent==self.path.parent and path.name.startswith('.'+self.path.name+'.'))]
        directories=[Path(row['directory']) for row in self.data['groups']]
        relevant=any(path==directory or path.parent==directory or directory.is_relative_to(path)
                     for path in paths for directory in directories)
        if relevant and not self.closed and not self.pending:
            self.pending=GLib.timeout_add(180,self.refresh)

    def refresh(self):
        self.pending=0
        if self.closed:return False
        if self.loading:self.again=True;return False
        self.loading=True
        directories={row['directory'] for row in self.data['groups']}
        def scan():
            result={}
            for directory in directories:
                try:result[directory]=(scan_desktop(Path(directory),False),None)
                except OSError as error:result[directory]=([],str(error))
            return result
        future=self.pool.submit(scan)
        def finished(_):
            if not self.closed:GLib.idle_add(self.loaded,future)
        future.add_done_callback(finished)
        return False

    def loaded(self,future):
        if self.closed:return False
        self.loading=False
        try:self.cache=future.result()
        except Exception as error:LOG.warning('Folder scan failed: %s',error)
        self.render();self.save();self.watch()
        if self.again:self.again=False;self.refresh()
        return False

    def render(self):
        for layer in list(self.layers):layer.rebuild()

    def edit(self,window,row=None):
        new=row is None
        candidate=model.new_group(self.directory) if new else copy.deepcopy(row)
        # An xdg-toplevel must not inherit a layer-surface as its transient
        # parent: GTK popup/IME coordinates cannot traverse that relationship.
        dialog=self.settings_dialog(window,tr('创建图标组' if new else '图标组设置'))
        dialog.set_default_size(500,min(520,max(320,window.monitor.get_geometry().height-100)))
        contents=dialog.get_content_area()
        pages=Gtk.Stack();pages.set_hhomogeneous(True);pages.set_vhomogeneous(False)
        switcher=Gtk.StackSwitcher();switcher.set_stack(pages);switcher.set_halign(Gtk.Align.CENTER)
        switcher.set_margin_top(12);switcher.set_margin_bottom(8)
        contents.pack_start(switcher,False,False,0)
        contents.pack_start(pages,True,True,0)
        def page(key,title):
            scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
            box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=14);box.set_border_width(18)
            scroll.add(box);pages.add_titled(scroll,key,tr(title));return box
        layout=page('layout','布局');appearance=page('appearance','外观')
        def field(box,title,control):
            line=Gtk.Box(spacing=16)
            label=Gtk.Label(label=tr(title),xalign=0);label.set_size_request(90,-1)
            line.pack_start(label,False,False,0);line.pack_start(control,True,True,0)
            box.pack_start(line,False,False,0);return line
        name=Gtk.Entry(text=candidate['name']);field(layout,'名称',name)
        folder=Gtk.FileChooserButton(title=tr('选择图标组文件夹'),action=Gtk.FileChooserAction.SELECT_FOLDER)
        folder.set_filename(candidate['directory']);field(layout,'文件夹',folder)
        display=Gdk.Display.get_default()
        is_primary=window is preferences.choose(self.application.views,display.get_primary_monitor() if display else None)
        choices=Gtk.ListStore(str,str,bool)
        for key,title in [('screen','仅限本屏幕'),('primary','仅限主屏幕'),('all','所有屏幕的相同位置')]:
            choices.append([key,tr(title),key!='primary' or is_primary])
        screen=Gtk.ComboBox.new_with_model(choices);screen.set_id_column(0)
        renderer=Gtk.CellRendererText();screen.pack_start(renderer,True);screen.add_attribute(renderer,'text',1);screen.add_attribute(renderer,'sensitive',2)
        screen.set_active_id(candidate['monitor'] if candidate['monitor'] in ('primary','all') else 'screen')
        field(layout,'显示范围',screen)
        fields={};grid=Gtk.Grid(column_spacing=16,row_spacing=10);layout.pack_start(grid,False,False,0)
        for index,(label,key,lo,hi) in enumerate([('网格列数','columns',1,16),('图标大小','icon_size',24,96),('宽度','width',220,2400),('高度','height',160,2000)]):
            spin=Gtk.SpinButton.new_with_range(lo,hi,1);spin.set_value(candidate[key]);spin.set_width_chars(4);spin.set_hexpand(True)
            fields[key]=spin;col=(index%2)*2;line=index//2
            grid.attach(Gtk.Label(label=tr(label),xalign=0),col,line,1,1);grid.attach(spin,col+1,line,1,1)
        hint=Gtk.Label(label=tr('拖动标题移动图标组，拖动右下角调整大小；位置按屏幕比例保存。'),xalign=0,wrap=True)
        hint.get_style_context().add_class('dim-label');layout.pack_start(hint,False,False,4)
        material=Gtk.ComboBoxText()
        for key,title in [('mica','云母'),('acrylic','亚克力'),('candy','糖果')]:material.append(key,tr(title))
        material.set_active_id(candidate.get('material','mica'));field(appearance,'背景风格',material)
        use_color=Gtk.CheckButton(label=tr('自定义背景色'));use_color.set_active(bool(candidate.get('background_color')))
        color=Gtk.ColorButton();rgba=Gdk.RGBA();rgba.parse(candidate.get('background_color') or '#252630');color.set_rgba(rgba)
        color.set_sensitive(use_color.get_active());use_color.connect('toggled',lambda w:color.set_sensitive(w.get_active()))
        color_row=Gtk.Box(spacing=12);color_row.pack_start(use_color,True,True,0);color_row.pack_end(color,False,False,0);appearance.pack_start(color_row,False,False,0)
        image=Gtk.FileChooserButton(title=tr('选择背景图片'),action=Gtk.FileChooserAction.OPEN)
        image_filter=Gtk.FileFilter();image_filter.set_name(tr('图片'));image_filter.add_pixbuf_formats();image.add_filter(image_filter)
        if candidate.get('background_image'):image.set_filename(candidate['background_image'])
        use_image=Gtk.CheckButton(label=tr('使用背景图片'));use_image.set_active(bool(candidate.get('background_image')))
        appearance.pack_start(use_image,False,False,0);appearance.pack_start(image,False,False,0)
        fit=Gtk.ComboBoxText()
        for key,title in [('cover','填充裁切'),('contain','完整适应'),('stretch','拉伸'),('center','居中'),('tile','平铺')]:fit.append(key,tr(title))
        fit.set_active_id(candidate.get('image_fit','cover'));field(appearance,'图片覆盖方式',fit)
        def image_enabled(*_):
            image.set_sensitive(use_image.get_active());fit.set_sensitive(use_image.get_active())
        use_image.connect('toggled',image_enabled);image_enabled()
        opacity=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,100,1);opacity.set_value(candidate.get('opacity',.78)*100)
        opacity.set_digits(0);opacity.set_value_pos(Gtk.PositionType.RIGHT);field(appearance,'不透明度',opacity)
        note=Gtk.Label(label=tr('背景透明度不影响图标与文字。'),xalign=0,wrap=True);note.get_style_context().add_class('dim-label');appearance.pack_start(note,False,False,0)
        from adws_settings_widgets import guard_combo_scroll
        guard_combo_scroll(contents)
        dialog.show_all();name.grab_focus()
        if dialog.run()==Gtk.ResponseType.OK:
            candidate.update(name=name.get_text().strip() or tr('图标组'),directory=folder.get_filename() or candidate['directory'],monitor=('all' if screen.get_active_id()=='all' else 'primary' if screen.get_active_id()=='primary' and is_primary else window.monitor_key))
            for key,spin in fields.items():candidate[key]=spin.get_value_as_int()
            candidate.update(material=material.get_active_id(),background_color=color.get_rgba().to_string() if use_color.get_active() else '',background_image=(image.get_filename() or '') if use_image.get_active() else '',image_fit=fit.get_active_id(),opacity=opacity.get_value()/100)
            if new:self.data['groups'].append(candidate)
            else:row.clear();row.update(candidate)
            self.save();self.watch();self.refresh()
        dialog.destroy()

    def settings_dialog(self,window,title):
        dialog=Gtk.Dialog(title=title,use_header_bar=True)
        dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG);dialog.set_resizable(False)
        # Keep this a normal floating toplevel, including for IME candidates.
        if isinstance(self.application,Gtk.Application):dialog.set_application(self.application)
        dialog.set_position(Gtk.WindowPosition.CENTER)
        dialog.add_buttons(tr('取消'),Gtk.ResponseType.CANCEL,tr('保存'),Gtk.ResponseType.OK)
        dialog.get_widget_for_response(Gtk.ResponseType.OK).get_style_context().add_class('suggested-action')
        dialog.get_style_context().add_class('adws-group-editor')
        return dialog

    def choose_default(self,window):
        dialog=self.settings_dialog(window,tr('ADWS 默认屏幕'))
        choice=Gtk.ComboBoxText();choice.append('primary',tr('跟随系统默认'))
        for view in self.application.views:choice.append(view.monitor_key,getattr(view,'monitor_label',view.monitor_key))
        choice.set_active_id(self.data.get('default_monitor','primary'))
        dialog.get_content_area().set_border_width(18);dialog.get_content_area().add(choice)
        from adws_settings_widgets import guard_combo_scroll
        guard_combo_scroll(dialog.get_content_area());dialog.show_all()
        if dialog.run()==Gtk.ResponseType.OK:
            identity=choice.get_active_id() or 'primary'
            view=next((v for v in self.application.views if v.monitor_key==identity),None)
            preferences.save(identity,getattr(view,'connector_key',''),getattr(view,'monitor_label',''))
            self.preference_changed(None,Gio.File.new_for_path(str(preferences.path())),None,None)
        dialog.destroy()

    def remove(self,window,row):
        dialog=Gtk.MessageDialog(transient_for=window,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.OK_CANCEL,text=tr('移除图标组：')+row['name'])
        dialog.format_secondary_text(tr('只移除桌面上的图标组，文件夹和文件不会删除。'))
        if dialog.run()==Gtk.ResponseType.OK:
            self.data['groups'].remove(row);self.save();self.watch();self.render()
        dialog.destroy()

    def close(self):
        self.closed=True
        self.preference_watch.cancel()
        if self.theme_pending:GLib.source_remove(self.theme_pending)
        for watcher in self.theme_watchers:watcher.cancel()
        if self.pending:GLib.source_remove(self.pending)
        for watcher in self.watchers:watcher.cancel()
        self.pool.shutdown(wait=False,cancel_futures=True)
        Gtk.StyleContext.remove_provider_for_screen(Gdk.Screen.get_default(),self.provider)
        self.save()


class Layer:
    def __init__(self,manager,window):
        self.manager=manager;self.window=window;self.cards=[]
        self.fixed=Gtk.Fixed();self.fixed.set_hexpand(True);self.fixed.set_vexpand(True)
        window.overlay.add_overlay(self.fixed)
        self.fixed.drag_dest_set(Gtk.DestDefaults.ALL,[Gtk.TargetEntry.new(TARGET,Gtk.TargetFlags.SAME_APP,0)],Gdk.DragAction.MOVE)
        self.fixed.connect('drag-data-received',self.drop)
        window.area.drag_dest_set(Gtk.DestDefaults.ALL,[Gtk.TargetEntry.new(TARGET,Gtk.TargetFlags.SAME_APP,0)],Gdk.DragAction.MOVE)
        window.area.connect('drag-data-received',self.drop)
        self.fixed.connect('size-allocate',lambda *_:self.place())
        self.fixed.connect('destroy',self.destroyed)
        manager.layers.append(self);self.rebuild()

    def rows(self):
        views=self.manager.application.views
        if not views:return []
        display=Gdk.Display.get_default()
        primary=preferences.choose(views,display.get_primary_monitor() if display else None)
        keys={v.monitor_key for v in views}
        # Disconnected groups are temporarily shown on the first screen without
        # overwriting their home screen or saved relative position.
        return [r for r in self.manager.data['groups'] if r['monitor']=='all' or r['monitor']==self.window.monitor_key or (r['monitor'] not in keys and self.window is primary)]

    def rebuild(self):
        for card in self.cards:card.destroy()
        self.cards=[]
        for row in self.rows():
            card=Card(self,row);self.cards.append(card);self.fixed.put(card,0,0)
        self.fixed.show_all();self.visibility();self.place()

    def place(self):
        w,h=self.window.area.get_allocated_width(),self.window.area.get_allocated_height()
        for card in self.cards:
            x,y,cw,ch=model.geometry(card.row,w,h)
            card.set_size_request(cw,ch);self.fixed.move(card,x,y)
        surface=self.fixed.get_window()
        if surface and surface not in (self.window.get_window(),self.window.area.get_window()):
            region=cairo.Region()
            for card in self.cards:
                x,y,cw,ch=model.geometry(card.row,w,h)
                region.union(cairo.RectangleInt(x,y,cw,ch))
            surface.input_shape_combine_region(region,0,0)

    def drop(self,widget,context,x,y,data,info,timestamp):
        identity=(data.get_data() or b'').decode('utf-8','replace')
        row=next((r for r in self.manager.data['groups'] if r['id']==identity),None)
        if row:
            if row['monitor']!='all':row['monitor']=self.window.monitor_key
            model.move(row,x-60,y-18,self.window.area.get_allocated_width(),self.window.area.get_allocated_height())
            self.manager.save();GLib.idle_add(self.manager.render)
        Gtk.drag_finish(context,row is not None,False,timestamp)

    def visibility(self):
        self.fixed.set_visible(not self.manager.application.hidden and not self.manager.application.overview_active)

    def destroyed(self,*_):
        if self in self.manager.layers:self.manager.layers.remove(self)


class Card(Gtk.Box):
    def __init__(self,layer,row):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=4)
        self.layer=layer;self.row=row;self.manager=layer.manager;self.icon_drag=None
        self.get_style_context().add_class('adws-folder-group')
        css=Gtk.CssProvider();css.load_from_data(b'.adws-folder-group {background: transparent; color:@theme_fg_color; border:1px solid alpha(@theme_fg_color,0.2); border-radius:16px; padding:8px;}')
        self.get_style_context().add_provider(css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.connect('draw',self.background)
        self.background_pixbuf=None
        image=row.get('background_image','')
        if image:
            try:
                stamp=Path(image).stat().st_mtime_ns
                key=(image,stamp)
                if key not in self.manager.images:
                    if len(self.manager.images)>=8:self.manager.images.clear()
                    self.manager.images[key]=GdkPixbuf.Pixbuf.new_from_file_at_scale(image,1024,1024,True)
                self.background_pixbuf=self.manager.images[key]
            except (OSError,GLib.Error) as error:LOG.warning('Group background: %s',error)
        header=Gtk.Box(spacing=8)
        handle=Gtk.EventBox();label=Gtk.Label(label=row['name'],xalign=0);label.set_ellipsize(Pango.EllipsizeMode.END);handle.add(label)
        handle.set_tooltip_text(tr('拖动移动图标组，也可拖到其他屏幕。'))
        handle.add_events(Gdk.EventMask.BUTTON_PRESS_MASK|Gdk.EventMask.BUTTON_RELEASE_MASK|Gdk.EventMask.POINTER_MOTION_MASK)
        self.move_origin=None
        handle.connect('button-press-event',self.move_press);handle.connect('motion-notify-event',self.move_motion);handle.connect('button-release-event',self.move_release)
        header.pack_start(handle,True,True,0)
        for icon,callback in [('preferences-system-symbolic',lambda *_:self.manager.edit(layer.window,row)),('window-close-symbolic',lambda *_:self.manager.remove(layer.window,row))]:
            button=Gtk.Button.new_from_icon_name(icon,Gtk.IconSize.MENU);button.set_relief(Gtk.ReliefStyle.NONE);button.connect('clicked',callback);header.pack_end(button,False,False,0)
        self.pack_start(header,False,False,0)
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.AUTOMATIC);scroll.set_min_content_height(80)
        self.pack_start(scroll,True,True,0)
        self.grid=Gtk.Fixed();scroll.add(self.grid)
        entries,error=self.manager.cache.get(row['directory'],([],tr('正在读取文件夹…')))
        if error:
            status=Gtk.Label(label=tr('文件夹不可用：')+error);status.set_line_wrap(True);status.set_max_width_chars(25);self.grid.put(status,8,8)
        cells=model.grid(row,[entry.path.name for entry in entries])
        cell_width=max(88,row['icon_size']+36);cell_height=row['icon_size']+48
        for entry in entries:
            cell=cells[entry.path.name]
            button=Gtk.Button();button.set_relief(Gtk.ReliefStyle.NONE);button.set_size_request(cell_width,cell_height)
            content=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4)
            icon=Gtk.Image.new_from_gicon(entry.icon,Gtk.IconSize.DIALOG);icon.set_pixel_size(row['icon_size']);content.pack_start(icon,False,False,0)
            label=Gtk.Label(label=entry.name);label.set_max_width_chars(12);label.set_ellipsize(Pango.EllipsizeMode.END);content.pack_start(label,False,False,0)
            button.add(content);button.set_tooltip_text(entry.name)
            button.connect('button-press-event',self.press,entry)
            button.add_events(Gdk.EventMask.POINTER_MOTION_MASK|Gdk.EventMask.BUTTON_RELEASE_MASK)
            button.connect('motion-notify-event',self.icon_motion,entry,cell_width,cell_height)
            button.connect('button-release-event',self.icon_release,entry,cell_width,cell_height)
            self.grid.put(button,cell[0]*cell_width,cell[1]*cell_height)
        self.grid.set_size_request(max(row['columns'],max((c[0]+1 for c in cells.values()),default=1))*cell_width,max((c[1]+1 for c in cells.values()),default=1)*cell_height)
        self.grid.drag_dest_set(Gtk.DestDefaults.ALL,[Gtk.TargetEntry.new(ICON_TARGET,Gtk.TargetFlags.SAME_APP,0),Gtk.TargetEntry.new(TARGET,Gtk.TargetFlags.SAME_APP,1)],Gdk.DragAction.MOVE)
        self.grid.connect('drag-data-received',self.drop_icon,cell_width,cell_height)
        footer=Gtk.Box();count=Gtk.Label(label=tr('%s 项')%len(entries),xalign=0);footer.pack_start(count,True,True,0)
        resize=Gtk.EventBox();resize.add(Gtk.Label(label='◢'));resize.set_tooltip_text(tr('拖动调整大小'));resize.add_events(Gdk.EventMask.BUTTON_PRESS_MASK|Gdk.EventMask.BUTTON_RELEASE_MASK|Gdk.EventMask.POINTER_MOTION_MASK)
        self.resize_origin=None
        resize.connect('button-press-event',self.resize_press);resize.connect('motion-notify-event',self.resize_motion);resize.connect('button-release-event',self.resize_release)
        footer.pack_end(resize,False,False,0);self.pack_end(footer,False,False,0)

    def background(self,widget,cr):
        import math
        from desktop_layer.app import read_palette_colors
        palette=self.manager.palette
        color=Gdk.RGBA();color.parse(self.row.get('background_color') or palette.get('surface_container','#252630'))
        accent=Gdk.RGBA();accent.parse(palette.get('primary','#bcbcff'))
        w,h=self.get_allocated_width(),self.get_allocated_height();radius=16
        cr.save()
        for x,y,a,b in [(w-radius,radius,-math.pi/2,0),(w-radius,h-radius,0,math.pi/2),(radius,h-radius,math.pi/2,math.pi),(radius,radius,math.pi,math.pi*1.5)]:cr.arc(x,y,radius,a,b)
        cr.close_path();cr.clip()
        cr.push_group()
        cr.set_source_rgb(color.red,color.green,color.blue);cr.paint()
        material=self.row.get('material','mica')
        gradient=cairo.LinearGradient(0,0,w if material=='mica' else 0,h)
        if material=='candy':
            gradient.add_color_stop_rgba(0,1,1,1,.25);gradient.add_color_stop_rgba(.48,accent.red,accent.green,accent.blue,.18);gradient.add_color_stop_rgba(.51,0,0,0,.1);gradient.add_color_stop_rgba(1,accent.red,accent.green,accent.blue,.12)
        else:
            gradient.add_color_stop_rgba(0,accent.red,accent.green,accent.blue,.18 if material=='mica' else .08);gradient.add_color_stop_rgba(1,1,1,1,.03)
        cr.set_source(gradient);cr.paint()
        pixbuf=self.background_pixbuf
        if pixbuf:
            iw,ih=pixbuf.get_width(),pixbuf.get_height();fit=self.row.get('image_fit','cover')
            cr.save()
            if fit=='tile':
                for y in range(0,h,ih):
                    for x in range(0,w,iw):Gdk.cairo_set_source_pixbuf(cr,pixbuf,x,y);cr.paint()
            else:
                sx,sy=w/iw,h/ih
                if fit in ('cover','contain'):sx=sy=(max if fit=='cover' else min)(sx,sy)
                elif fit=='center':sx=sy=1
                cr.translate((w-iw*sx)/2,(h-ih*sy)/2);cr.scale(sx,sy);Gdk.cairo_set_source_pixbuf(cr,pixbuf,0,0);cr.paint()
            cr.restore()
        cr.pop_group_to_source();cr.paint_with_alpha(self.row.get('opacity',.78));cr.restore()
        return False

    def press(self,widget,event,entry):
        if event.button==1 and event.type==Gdk.EventType._2BUTTON_PRESS:
            self.launch(entry,event);return True
        if event.button==3:
            menu=Gtk.Menu()
            for title,callback in [('打开',lambda:self.launch(entry,event)),('用指定应用打开…',lambda:self.open_with(entry)),('打开所在文件夹',lambda:Gio.AppInfo.launch_default_for_uri(entry.path.parent.as_uri(),None))]:
                item=Gtk.MenuItem(label=tr(title));item.connect('activate',lambda _i,cb=callback:cb());menu.append(item)
            menu.connect('selection-done',lambda w:w.destroy());menu.show_all();menu.popup_at_pointer(event);return True
        if event.button==1:
            self.icon_drag=(entry.path.name,event.x_root,event.y_root,list(self.row['cells'][entry.path.name]),False)
            return True
        return False

    def launch(self,entry,event=None):
        # Reuse the original trust-confirmation and application launch behavior.
        view=self.layer.window
        self.manager.application.by_path[str(entry.path)]=entry
        view.open_entry(str(entry.path),event)

    def open_with(self,entry):
        self.manager.application.by_path[str(entry.path)]=entry
        self.layer.window.open_with(str(entry.path))

    def icon_motion(self,widget,event,entry,cw,ch):
        if self.icon_drag is None or self.icon_drag[0]!=entry.path.name:return False
        name,sx,sy,cell,moved=self.icon_drag
        dx,dy=event.x_root-sx,event.y_root-sy
        if not moved and abs(dx)+abs(dy)<8:return True
        self.icon_drag=(name,sx,sy,cell,True)
        self.grid.move(widget,round(cell[0]*cw+dx),round(cell[1]*ch+dy))
        return True

    def icon_release(self,widget,event,entry,cw,ch):
        if event.button!=1 or self.icon_drag is None:return False
        name,sx,sy,cell,moved=self.icon_drag;self.icon_drag=None
        if moved:
            model.move_icon(self.row,name,round(cell[0]+(event.x_root-sx)/cw),round(cell[1]+(event.y_root-sy)/ch))
            self.manager.save();GLib.idle_add(self.manager.render)
        return True

    def drop_icon(self,widget,context,x,y,data,info,timestamp,cw,ch):
        if info == 1:
            position=widget.translate_coordinates(self.layer.fixed,x,y)
            if position:self.layer.drop(self.layer.fixed,context,*position,data,0,timestamp)
            return
        success=False
        try:
            identity,name=json.loads((data.get_data()or b'').decode())
            if identity==self.row['id'] and name in self.row['cells']:
                model.move_icon(self.row,name,int(x/cw),int(y/ch));self.manager.save();success=True
                GLib.idle_add(self.manager.render)
        except (ValueError,TypeError):pass
        Gtk.drag_finish(context,success,False,timestamp)

    def move_press(self,widget,event):
        if event.button!=1:return False
        x,y,_,_=model.geometry(self.row,self.layer.window.area.get_allocated_width(),self.layer.window.area.get_allocated_height())
        self.move_origin=(event.x_root,event.y_root,x,y)
        self.move_target=None
        return True

    def move_motion(self,widget,event):
        if not self.move_origin:return False
        sx,sy,x,y=self.move_origin
        model.move(self.row,x+event.x_root-sx,y+event.y_root-sy,self.layer.window.area.get_allocated_width(),self.layer.window.area.get_allocated_height())
        # Pointer grab motion remains relative to the origin surface even
        # after crossing a monitor boundary. Convert that delta to layout space.
        geometry=self.layer.window.monitor.get_geometry()
        gx,gy=geometry.x+x+event.x_root-sx,geometry.y+y+event.y_root-sy
        self.move_target=None
        for view in [self.layer.window]+[v for v in self.manager.application.views if v is not self.layer.window]:
            target=view.monitor.get_geometry()
            if target.x<=gx+60<target.x+target.width and target.y<=gy+20<target.y+target.height:
                if view is not self.layer.window:self.move_target=(view,gx-target.x,gy-target.y)
                break
        self.layer.place();return True

    def move_release(self,widget,event):
        if self.move_origin and event.button==1:
            self.move_origin=None
            if self.move_target:
                view,x,y=self.move_target
                if self.row['monitor']!='all':self.row['monitor']=view.monitor_key
                model.move(self.row,x,y,view.area.get_allocated_width(),view.area.get_allocated_height())
                GLib.idle_add(self.manager.render)
            self.manager.save()
            if self.row['monitor']=='all':
                for layer in self.manager.layers:layer.place()
            return True
        return False

    def resize_press(self,widget,event):
        if event.button==1:self.resize_origin=(event.x_root,event.y_root,self.row['width'],self.row['height']);return True
        return False

    def resize_motion(self,widget,event):
        if self.resize_origin:
            x,y,w,h=self.resize_origin
            self.row['width']=max(220,min(2400,round(w+event.x_root-x)))
            self.row['height']=max(160,min(2000,round(h+event.y_root-y)))
            self.layer.place();return True
        return False

    def resize_release(self,widget,event):
        if self.resize_origin:
            self.resize_origin=None;self.manager.save()
            for layer in self.manager.layers:layer.place()
            return True
        return False

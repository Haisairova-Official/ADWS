"""Interactive desktop cards. No plugin code executes in the desktop process."""
from datetime import datetime
import copy
import json
import logging
from pathlib import Path
import subprocess
import sys
from gi.repository import Gtk, Gdk, Gio, GLib, Pango
from adws_i18n import tr
import adws_desktop_widgets_model as model
import adws_desktop_preferences as preferences

LOG=logging.getLogger('adws.desktop-widgets')


class Manager:
    def __init__(self, application, path=None):
        self.application=application;self.path=Path(path or model.layout_path());self.controllers=[]
        self.migrations={};self.migration_source=0;self.streams={}
        self.data={'version':1,'instances':[]};self.available=[];self.pending=0;self.monitors=[];self.closed=False
        try:self.path.parent.mkdir(parents=True,exist_ok=True)
        except OSError as error:LOG.warning('Desktop widget directory: %s',error)
        self.reload()
        from adws_plugin import plugin_dir
        from desktop_layer.app import palette_file_candidates
        folders={self.path.parent,plugin_dir(),preferences.path().parent}
        folders.update(p.parent for p in palette_file_candidates() if p.parent.is_dir())
        for folder in folders:
            try:
                folder.mkdir(parents=True,exist_ok=True)
                watcher=Gio.File.new_for_path(str(folder)).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES,None)
                watcher.connect('changed',self.changed);self.monitors.append(watcher)
            except (OSError,GLib.Error) as error:LOG.warning('Desktop widget watch: %s',error)

    def changed(self,*_):
        if not self.pending and not self.closed:self.pending=GLib.timeout_add(180,self.reload)

    def reload(self):
        self.pending=0
        if self.closed:return False
        self.application.widgets_hidden=not preferences.widgets_visible()
        for controller in list(self.controllers):controller.visibility()
        try:
            data=model.load(self.path);available=model.catalog();model.validate_instances(data,available)
            if data!=self.data or available!=self.available:
                self.data,self.available=data,available
                for controller in list(self.controllers):controller.render()
            else:
                for controller in list(self.controllers):controller.theme()
        except (OSError,ValueError) as error:LOG.warning('Desktop widget configuration: %s',error)
        return False

    def set_visible(self, visible):
        try:preferences.save_widgets_visibility(visible)
        except OSError as error:
            LOG.warning('Desktop widget visibility: %s',error);return
        self.application.widgets_hidden=not bool(visible)
        for controller in list(self.controllers):controller.visibility()

    def persist(self):
        self.data=model.save(self.data,self.path)

    def edit(self,identity,**values):
        def change(data):
            row=next((r for r in data['instances'] if r['instance']==identity),None)
            if row is not None:row.update(values)
            return data
        try:self.data=model.mutate(change,self.path)
        except (OSError,ValueError) as error:
            LOG.warning('Desktop widget save failed: %s',error);return
        for controller in list(self.controllers):controller.render()

    def subscribe(self,definition,row):
        from adws_desktop_plugin import SharedStream,PluginStream
        key=(row['instance'],str(definition['file']),json.dumps(definition.get('manifest',{}),sort_keys=True),json.dumps(row['settings'],sort_keys=True))
        if key not in self.streams:
            self.streams[key]=SharedStream(PluginStream(definition,row),lambda:self.streams.pop(key,None))
        return self.streams[key].subscribe()

    def restart_instance(self,identity):
        cards=[controller.cards[identity] for controller in self.controllers if identity in controller.cards]
        for card in cards:card.stop()
        for card in cards:
            if card.box.get_mapped():card.start()

    def migrate_position(self,identity,values):
        if self.migrations.get(identity)==values:return
        self.migrations[identity]=values
        if self.migration_source:GLib.source_remove(self.migration_source)
        # GTK first allocates a tiny provisional window; migrate only after the
        # actual layer-surface allocation settles, never from its startup size.
        self.migration_source=GLib.timeout_add(180,self.flush_migrations)

    def flush_migrations(self):
        self.migration_source=0
        pending,self.migrations=self.migrations,{}
        def change(data):
            migrating=[row for row in data['instances'] if row['instance'] in pending and 'x_percent' not in row]
            if migrating:
                backup=self.path.with_name(self.path.name+'.pixels-backup')
                try:
                    with backup.open('x',encoding='utf-8') as stream:json.dump(data,stream,ensure_ascii=False,indent=2)
                except FileExistsError:pass
            for row in migrating:row.update(pending[row['instance']])
            return data
        try:self.data=model.mutate(change,self.path)
        except (OSError,ValueError) as error:LOG.warning('Desktop widget position migration failed: %s',error);return False
        if not self.closed:
            for controller in list(self.controllers):controller.render()
        return False

    def remove(self,identity):
        def change(data):
            data['instances']=[r for r in data['instances'] if r['instance']!=identity];return data
        try:self.data=model.mutate(change,self.path)
        except (OSError,ValueError) as error:
            LOG.warning('Desktop widget removal failed: %s',error);return
        for controller in list(self.controllers):controller.render()

    def close(self):
        self.closed=True
        if self.migration_source:GLib.source_remove(self.migration_source);self.flush_migrations()
        if self.pending:GLib.source_remove(self.pending);self.pending=0
        for monitor in self.monitors:monitor.cancel()
        self.monitors.clear()
        for controller in list(self.controllers):controller.close()


class DesktopLayer:
    def __init__(self, manager, window):
        self.manager,self.window=manager,window;self.cards={};self.closed=False
        self.fixed=Gtk.Fixed();self.fixed.set_hexpand(True);self.fixed.set_vexpand(True)
        self.fixed.set_halign(Gtk.Align.FILL);self.fixed.set_valign(Gtk.Align.FILL)
        self.fixed.set_no_show_all(True);window.overlay.add_overlay(self.fixed)
        self.geometry_handlers=[(self.fixed,self.fixed.connect('size-allocate',lambda *_:self.place())),
                                (window.area,window.area.connect('size-allocate',lambda *_:self.place()))]
        import weakref
        weak=weakref.ref(self)
        window.connect('destroy',lambda *_:weak() and weak().close())
        manager.controllers.append(self)
        self.provider=Gtk.CssProvider();self.theme();self.render()

    def theme(self):
        from desktop_layer.app import read_palette_colors
        palette=read_palette_colors()
        def color(key,fallback):
            value=palette.get(key,fallback);parsed=Gdk.RGBA()
            return value if parsed.parse(value) else fallback
        surface=color('surface_container','#252630');foreground=color('on_surface','#eceaf5')
        accent=color('primary','#bcbcff')
        css=f'''.adws-desktop-card {{ background-color: alpha({surface},0.91); color: {foreground}; border: 1px solid alpha({foreground},0.16); border-radius: 18px; padding: 12px; }}
.adws-desktop-card label {{ color: {foreground}; }}
.adws-desktop-card button {{ background-image:none; background-color:alpha({foreground},0.07); color:{foreground}; border-radius:9px; border:0; box-shadow:none; padding:4px; min-height:16px; min-width:16px; }}
.adws-desktop-card button:hover {{ background-color:alpha({accent},0.22); }}
.adws-desktop-card .desktop-primary {{ font-size:23px; font-weight:600; }}
.adws-desktop-card .desktop-clock {{ font-size:46px; font-weight:300; }}
.adws-desktop-card .desktop-secondary {{ opacity:0.75; }}
.adws-desktop-card .desktop-context {{ font-size:13px; opacity:0.48; }}
.adws-desktop-card .desktop-romanization {{ font-size:14px; opacity:0.8; }}
.desktop-ruby flowboxchild {{ padding:0; margin:0; background:none; border:0; }}
.desktop-ruby .desktop-furigana {{ font-size:12px; opacity:0.85; }}
.adws-desktop-card.desktop-error {{ border-color:#d9ae52; }}
.adws-desktop-card.desktop-lyrics {{ background-color:transparent; border-color:transparent; }}
.adws-desktop-card.desktop-lyrics:hover {{ background-color:alpha({surface},0.7); border-color:alpha({foreground},0.15); }}
.desktop-lyrics label {{ text-shadow:0 1px 3px rgba(0,0,0,0.85); }}
.desktop-lyrics .desktop-primary {{ font-size:28px; }}
.desktop-lyrics .desktop-secondary {{ font-size:16px; opacity:0.82; }}
.desktop-interactive .basic-clock {{ font-size:34px; font-weight:300; }}
.desktop-interactive .basic-eyebrow {{ font-size:13px; font-weight:600; color:{accent}; }}
.desktop-interactive .basic-muted {{ font-size:12px; opacity:0.7; }}
.desktop-interactive .basic-tile {{ min-height:34px; padding:3px; font-size:21px; font-weight:700; border-radius:10px; background-color:alpha({accent},0.13); transition:background-color 160ms ease-out; }}
.desktop-interactive .tile-4 {{ background-color:alpha({accent},0.24); }}
.desktop-interactive .tile-8, .desktop-interactive .tile-16 {{ background-color:alpha({accent},0.38); }}
.desktop-interactive .tile-32, .desktop-interactive .tile-64 {{ background-color:alpha({accent},0.5); }}
.desktop-interactive .tile-128, .desktop-interactive .tile-256, .desktop-interactive .tile-512, .desktop-interactive .tile-1024, .desktop-interactive .tile-2048 {{ background-color:alpha({accent},0.65); }}
.desktop-interactive .basic-accent {{ background-color:alpha({accent},0.22); }}
.desktop-interactive .basic-puzzle-tile {{ padding:2px; border:2px solid transparent; border-radius:7px; }}
.desktop-interactive .basic-selected {{ border-color:{accent}; }}
.desktop-interactive .basic-hidden-image {{ opacity:0; }}
.desktop-interactive .basic-empty {{ background-color:alpha({foreground},0.025); border:1px dashed alpha({foreground},0.16); }}
.desktop-interactive .basic-puzzle-tile:disabled {{ opacity:1; }}
.adws-desktop-card.desktop-analog-clock, .adws-desktop-card.desktop-analog-clock:hover {{ background:transparent; border-color:transparent; box-shadow:none; }}
.desktop-analog-clock .desktop-toolbar {{ opacity:1; }}
.adws-desktop-card.desktop-basic-pack {{ padding:6px; border-radius:14px; font-size:12px; }}
.desktop-basic-pack .basic-text {{ padding:6px; font-size:14px; }}
.desktop-interactive progressbar progress {{ background-image:none; background-color:{accent}; }}
.desktop-interactive .basic-text {{ padding:10px; font-size:16px; }}
.desktop-media label {{ font-size:10px; opacity:0.65; }}
.desktop-spectrum {{ color:{accent}; }}
.desktop-progress {{ padding:8px 0; }}
.desktop-progress slider {{ min-width:10px; min-height:10px; border-radius:50%; background:{accent}; border:0; box-shadow:none; }}
.desktop-progress trough {{ min-height:3px; background-color:alpha({foreground},0.14); border:0; }}
.desktop-progress highlight {{ min-height:3px; background-color:{accent}; border:0; }}
.desktop-lyrics .desktop-toolbar {{ opacity:0; transition:opacity 150ms ease-out; }}
.desktop-lyrics:hover .desktop-toolbar {{ opacity:1; }}
.adws-desktop-card viewport, .adws-desktop-card scrolledwindow {{ background-color:transparent; border:0; }}
.adws-desktop-card textview, .adws-desktop-card textview text {{ background-color:transparent; color:{foreground}; }}'''
        self.provider.load_from_data(css.encode())
        def apply(widget):
            widget.get_style_context().add_provider(self.provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+10)
            if isinstance(widget,Gtk.Container):
                for child in widget.get_children():apply(child)
        for card in self.cards.values():
            apply(card.box);card.text_theme();card.custom_theme()
            if hasattr(card,'ruby'):card.reflow_ruby(card.ruby_width)

    def primary_window(self):
        views=self.manager.application.views
        display=Gdk.Display.get_default();monitor=display.get_primary_monitor() if display else None
        from adws_desktop_preferences import choose
        return choose(views,monitor) or self.window

    def rows(self):
        return [r for r in self.manager.data['instances'] if model.visible_on(r,self.window.monitor_key,
            self.window is self.primary_window(),(getattr(self.window,'connector_key',self.window.monitor_key),))]

    def render(self):
        if self.closed:return
        definitions={d['key']:d for d in self.manager.available}
        rows={r['instance']:r for r in self.rows()}
        for identity in set(self.cards)-set(rows):self.cards.pop(identity).destroy()
        for identity,row in rows.items():
            definition=definitions.get(row['component'],{'key':row['component'],'name':'组件未安装','kind':'missing'})
            signature=(definition, row['settings'],row.get('css',''))
            old=self.cards.get(identity)
            if old is not None and old.signature!=signature:
                old.destroy();del self.cards[identity];old=None
            if old is None:
                old=Card(self,row,definition);self.cards[identity]=old
                self.fixed.put(old.box,0,0);old.box.show_all()
            old.row=copy.deepcopy(row)
            old.title.set_text(tr(definition['name'])+(' · '+tr('已锁定') if row['locked'] else ''))
            old.grip.set_sensitive(not row['locked'])
            if hasattr(old,'lock_button'):old.lock_button.set_image(Gtk.Image.new_from_icon_name('changes-prevent-symbolic' if row['locked'] else 'changes-allow-symbolic',Gtk.IconSize.BUTTON))
        self.place();self.theme();self.visibility()

    def place(self):
        if self.closed:return
        width,height=self.window.area.get_allocated_width(),self.window.area.get_allocated_height()
        if width<=1 or height<=1:return
        for card in self.cards.values():
            if 'x_percent' not in card.row:
                values=model.percentages(card.row,width,height)
                source=next((view for view in self.manager.application.views if card.row['monitor'] in (view.monitor_key,getattr(view,'connector_key',view.monitor_key))),None) or self.primary_window()
                if card.row['monitor_scope']!='all' or self.window is source:
                    self.manager.migrate_position(card.row['instance'],values)
            x,y,w,h=model.geometry(card.row,width,height)
            if hasattr(card,'ruby'):card.reflow_ruby(max(1,w-48))
            if card.lyrics:
                natural=card.content.get_preferred_height_for_width(max(1,w-48))[1]
                # Reserve real layout space for all lines and the separate footer.
                # Keep a stable minimum per width, avoiding jumps on each lyric.
                old_width,old_height=getattr(card,'lyrics_minimum',(w,0))
                natural=max(natural,old_height if old_width==w else 0)
                card.lyrics_minimum=(w,natural)
                card.viewport.set_min_content_height(min(natural,max(1,height-180)))
                context=card.box.get_style_context();state=card.box.get_state_flags()
                padding=context.get_padding(state);border=context.get_border(state)
                inner=max(1,w-padding.left-padding.right-border.left-border.right)
                h=max(h,card.body.get_preferred_height_for_width(inner)[0]+padding.top+padding.bottom+border.top+border.bottom)
                y=max(0,min(y,height-h))
            if card.lyrics:
                x,y,_,_=model.geometry({**card.row,'width':w,'height':h},width,height)
            card.placed_geometry=(x,y,w,h)
            card.box.set_size_request(w,h);self.fixed.move(card.box,x,y)
        self.shape_input()

    def shape_input(self):
        # GtkOverlay gives its overlay child a separate GDK window. Restrict
        # that window to the cards, so empty desktop space reaches icon input.
        surface=self.fixed.get_window()
        if surface is None or surface in (self.window.get_window(),self.window.area.get_window()):return
        import cairo
        region=cairo.Region()
        width,height=self.window.area.get_allocated_width(),self.window.area.get_allocated_height()
        for card in self.cards.values():
            x,y,w,h=getattr(card,'placed_geometry',model.geometry(card.row,width,height))
            region.union(cairo.RectangleInt(x,y,max(w,card.box.get_allocated_width()),max(h,card.box.get_allocated_height())))
        surface.input_shape_combine_region(region,0,0)

    def visibility(self):
        owner=self.manager.application
        self.fixed.set_visible(not getattr(owner,'widgets_hidden',False) and not owner.overview_active)
        self.shape_input()

    def close(self):
        if self.closed:return
        self.closed=True
        for widget,handler in self.geometry_handlers:widget.disconnect(handler)
        self.geometry_handlers.clear()
        for card in list(self.cards.values()):card.destroy()
        self.cards.clear()
        if self in self.manager.controllers:self.manager.controllers.remove(self)
        self.fixed.destroy()


class Card:
    def __init__(self,layer,row,definition):
        self.layer,self.definition,self.row=layer,definition,copy.deepcopy(row)
        self.signature=copy.deepcopy((definition,row['settings'],row.get('css','')))
        self.source=0;self.stream=None;self.closed=False;self.gesture=None;self.note=None;self.control_busy=False;self.text_provider=None;self.text_css=None;self.note_source=0;self.custom_provider=None;self.custom_css=None;self.control_buttons={};self.control_result=None;self.media_player=None;self.media_capabilities={}
        self.box=Gtk.EventBox();self.box.set_can_focus(True);self.box.connect('button-press-event',self.focus_card);self.box.get_style_context().add_class('adws-desktop-card')
        self.lyrics=definition.get('manifest',{}).get('desktopStyle')=='lyrics'
        self.interactive=None
        basic=definition.get('manifest',{}).get('packageId')=='org.AkiACG-Community.desktopBasicPack'
        if basic:self.box.get_style_context().add_class('desktop-basic-pack')
        analog=basic and definition['manifest'].get('componentId')=='clock' and row['settings'].get('display')=='analog'
        if analog:
            self.box.get_style_context().add_class('desktop-analog-clock')
            self.box.connect('button-press-event',self.clock_double_click)
        if self.lyrics:self.box.get_style_context().add_class('desktop-lyrics')
        body=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4 if self.lyrics or basic else 10);body.set_border_width(6 if self.lyrics or basic else 12);self.box.add(body);self.body=body
        header=Gtk.Box(spacing=8);header.get_style_context().add_class('desktop-toolbar');body.pack_start(header,False,False,0)
        handle=Gtk.EventBox();handle.set_visible_window(False)
        self.title=Gtk.Label(xalign=0);self.title.set_ellipsize(Pango.EllipsizeMode.END);handle.add(self.title)
        handle.set_tooltip_text(tr('拖动移动桌面组件'))
        header.pack_start(handle,True,True,0)
        menu=Gtk.MenuButton();menu.add(Gtk.Image.new_from_icon_name('view-more-symbolic',Gtk.IconSize.MENU));header.pack_end(menu,False,False,0)
        menu.connect('button-press-event',lambda *_:self.rebuild_menu(menu));self.rebuild_menu(menu)
        if analog:
            # Transparent cards still need discoverable controls. Hiding a parent
            # toolbar also hides its buttons; CSS :hover isn't reliable here.
            self.title.set_opacity(0)
            self.clock_settings_button=Gtk.Button.new_from_icon_name('preferences-system-symbolic',Gtk.IconSize.MENU)
            self.clock_settings_button.set_tooltip_text(tr('时钟设置'))
            self.clock_settings_button.get_accessible().set_name(tr('时钟设置'))
            self.clock_settings_button.connect('clicked',lambda *_:self.settings())
            header.pack_end(self.clock_settings_button,False,False,0)
            menu.set_tooltip_text(tr('更多操作'))
        if self.lyrics:
            self.lock_button=Gtk.Button.new_from_icon_name('changes-prevent-symbolic' if row['locked'] else 'changes-allow-symbolic',Gtk.IconSize.BUTTON)
            self.lock_button.set_tooltip_text(tr('锁定／解锁位置'));self.lock_button.connect('clicked',lambda *_:self.layer.manager.edit(self.row['instance'],locked=not self.row['locked']));header.pack_end(self.lock_button,False,False,0)
        content=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        viewport=Gtk.ScrolledWindow();viewport.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
        viewport.set_shadow_type(Gtk.ShadowType.NONE);viewport.add(content);body.pack_start(viewport,True,True,0)
        self.content=content;self.viewport=viewport
        if self.lyrics:content.set_spacing(2);content.set_valign(Gtk.Align.CENTER)
        key=row['component']
        if key=='builtin:clock':
            self.primary=self.label(content,'desktop-clock');self.secondary=self.label(content,'desktop-secondary')
        elif key=='builtin:calendar':content.pack_start(Gtk.Calendar(),True,True,0)
        elif key=='builtin:note':
            self.note=Gtk.TextView();self.note.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            self.note.get_buffer().set_text(row['settings'].get('text',''))
            scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.AUTOMATIC);scroll.add(self.note);content.pack_start(scroll,True,True,0)
            self.note.connect('focus-out-event',lambda *_:(self.save_note(),False)[1])
            self.note.get_buffer().connect('changed',self.note_changed)
        elif definition['kind']=='plugin' and definition['manifest'].get('renderer')=='desktop.widgets-v1':
            from adws_desktop_interactive import Interactive
            self.interactive=Interactive(self,content)
            self.box.get_style_context().add_class('desktop-interactive')
        elif definition['kind']=='plugin':
            self.previous=self.label(content,'desktop-context');self.previous.set_no_show_all(True)
            self.primary=self.label(content,'desktop-primary');self.primary.set_no_show_all(True)
            self.ruby=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4)
            self.ruby.set_no_show_all(True);self.ruby.get_style_context().add_class('desktop-ruby')
            self.ruby_value=None;self.fit_signature=None;self.ruby_tokens=[];content.pack_start(self.ruby,False,False,0)
            self.romanization=self.label(content,'desktop-romanization');self.romanization.set_no_show_all(True)
            self.separator=Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL);self.separator.get_style_context().add_class('desktop-separator')
            self.separator.set_no_show_all(True);content.pack_start(self.separator,False,False,0)
            self.secondary=self.label(content,'desktop-secondary');self.secondary.set_no_show_all(True)
            self.following=self.label(content,'desktop-context');self.following.set_no_show_all(True)
            for label in (self.previous,self.romanization,self.following):
                label.set_lines(1);content.set_child_packing(label,False,False,0,Gtk.PackType.START)
            align=definition['manifest'].get('defaults',{}).get('align',0.0)
            if self.lyrics:align={'left':0.,'center':.5,'right':1.}.get(str(self.row['settings'].get('text_align','center')),.5)
            self.primary.set_xalign(align);self.secondary.set_xalign(align)
            self.lyric_align=align
            self.ruby.set_halign(Gtk.Align.FILL)
            self.ruby_width=max(1,row['width']-48)
            for label in (self.previous,self.romanization,self.following):label.set_xalign(align)
            if self.lyrics:
                content.reorder_child(self.secondary,3)
                self.previous.set_margin_bottom(10);self.following.set_margin_top(10)
                for label in (self.primary,self.secondary):content.set_child_packing(label,False,False,0,Gtk.PackType.START);label.set_lines(2)
                self.primary.set_justify(Gtk.Justification.CENTER)
            self.primary.set_text(tr('正在启动桌面组件…'));self.primary.show()
            if definition['manifest'].get('controls'):
                buttons=Gtk.Box(spacing=6)
                if self.lyrics:header.pack_end(buttons,False,False,0)
                else:content.pack_end(buttons,False,False,0)
                for control,icon in [('previous','media-skip-backward-symbolic'),('play-pause','media-playback-start-symbolic'),('next','media-skip-forward-symbolic')]:
                    if control not in definition['manifest']['controls']:continue
                    button=Gtk.Button.new_from_icon_name(icon,Gtk.IconSize.BUTTON);button.set_tooltip_text(tr({'previous':'上一首','play-pause':'播放／暂停','next':'下一首'}[control]))
                    button.connect('clicked',lambda _,action=control:self.control(action));buttons.pack_start(button,True,True,0);self.control_buttons[control]=button
            if self.lyrics:
                from adws_lyrics_media import media_widget
                self.media=media_widget(self.row['settings'],lambda position,player,track_id,token:self.control('seek',position,player,track_id,token));body.pack_start(self.media,False,False,0)
            self.control_message=Gtk.Label(xalign=0,wrap=True);self.control_message.set_no_show_all(True);content.pack_end(self.control_message,False,False,0)
        else:self.label(content,'desktop-secondary').set_text(tr('组件未安装，请在桌面小组件设置中安装对应模组。'))
        grip=Gtk.EventBox();self.grip=grip;grip.set_visible_window(False);grip.add(Gtk.Label(label='◢',xalign=1));grip.get_style_context().add_class('desktop-toolbar');grip.set_halign(Gtk.Align.END);grip.set_tooltip_text(tr('拖动调整大小'));body.pack_end(grip,False,False,0)
        for widget,resizing in [(handle,False),(grip,True)]:
            widget.add_events(Gdk.EventMask.BUTTON_PRESS_MASK|Gdk.EventMask.BUTTON_RELEASE_MASK|Gdk.EventMask.POINTER_MOTION_MASK)
            widget.connect('button-press-event',self.press,resizing);widget.connect('motion-notify-event',self.motion)
            widget.connect('button-release-event',self.release)
        if self.lyrics:
            self.box.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK|Gdk.EventMask.LEAVE_NOTIFY_MASK)
            self.box.connect('enter-notify-event',self.hover,True);self.box.connect('leave-notify-event',self.hover,False)
        self.box.connect('map',self.start);self.box.connect('unmap',self.stop)
        self.box.connect('destroy',lambda *_:self.dispose())

    def hover(self,widget,event,inside):
        if event.detail==Gdk.NotifyType.INFERIOR:return False
        if inside:self.box.set_state_flags(Gtk.StateFlags.PRELIGHT,False)
        else:self.box.unset_state_flags(Gtk.StateFlags.PRELIGHT)
        return False

    def label(self,parent,style):
        label=Gtk.Label(xalign=0,wrap=True);label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR);label.set_ellipsize(Pango.EllipsizeMode.END);label.set_lines(3);label.set_max_width_chars(32)
        label.get_style_context().add_class(style);parent.pack_start(label,True,True,0);return label

    def text_theme(self):
        if self.definition['kind']!='plugin' or self.interactive:return
        css=[]
        if self.lyrics:
            try:size=max(16,min(64,float(self.row['settings'].get('lyric_font_size',28))))
            except (TypeError,ValueError):size=28
            css.append('.desktop-primary { font-size: %spx; }'%size)
            css.append('.desktop-furigana { font-size: %spx; }'%max(10,size*.45))
        for field,style in [('primary_color','desktop-primary'),('secondary_color','desktop-secondary')]:
            value=self.row['settings'].get(field,'');color=Gdk.RGBA()
            if isinstance(value,str) and value and color.parse(value):css.append('.'+style+' {color:'+color.to_string()+';}')
        value=self.row['settings'].get('separator_color','');color=Gdk.RGBA()
        if isinstance(value,str) and value and color.parse(value):css.append('.desktop-separator {background-color:'+color.to_string()+';border-color:'+color.to_string()+';}')
        font=self.row['settings'].get('font_family','')
        if isinstance(font,str) and font:
            family=Pango.FontDescription.from_string(font).get_family()
            if family:css.append('label {font-family:'+json.dumps(family,ensure_ascii=False)+';}')
        text='\n'.join(css)
        if text and text!=self.text_css:
            if self.text_provider is None:
                self.text_provider=Gtk.CssProvider()
                for label in (self.primary,self.secondary,self.separator):label.get_style_context().add_provider(self.text_provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+20)
            self.text_provider.load_from_data(text.encode());self.text_css=text

    def custom_theme(self):
        css=self.row.get('css','')
        if css==self.custom_css:return
        from adws_widget_style import provider
        try:replacement=provider(css) if css else None
        except (GLib.Error,ValueError) as error:
            LOG.warning('Invalid CSS for %s: %s',self.row['instance'],error);return
        def apply(widget):
            context=widget.get_style_context()
            if self.custom_provider:context.remove_provider(self.custom_provider)
            if replacement:context.add_provider(replacement,Gtk.STYLE_PROVIDER_PRIORITY_USER+10)
            if isinstance(widget,Gtk.Container):
                for child in widget.get_children():apply(child)
        apply(self.box);self.custom_provider=replacement;self.custom_css=css

    def edit_css(self):
        from adws_widget_style import edit
        css=edit(self.layer.window,self.row.get('css',''))
        if css is not None:self.layer.manager.edit(self.row['instance'],css=css)

    def duplicate(self):
        manager=self.layer.manager
        try:
            model.mutate(lambda data:model.duplicate(data,self.row['instance'],manager.available),manager.path)
            manager.reload()
        except (OSError,ValueError,StopIteration) as error:LOG.warning('Duplicate widget: %s',error)

    def rebuild_menu(self,button):
        menu=Gtk.Menu()
        group=None;is_primary=self.layer.window is self.layer.primary_window()
        for scope,caption in [('screen','仅限本屏幕'),('primary','仅限主屏幕'),('all','所有屏幕的相同位置')]:
            item=Gtk.RadioMenuItem.new_with_label(group,tr(caption));group=item.get_group()
            item.set_active(self.row['monitor_scope']==scope);item.set_sensitive(scope!='primary' or is_primary)
            item.connect('toggled',lambda w,s=scope,primary=is_primary:w.get_active() and self.layer.manager.edit(self.row['instance'],**model.scope_values(s,getattr(self.layer.window,'connector_key',self.layer.window.monitor_key),primary)))
            menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        if self.lyrics:
            for key,caption,default in [('show_translation','显示翻译',True),('show_romanization','显示罗马音',False),('show_furigana','日语汉字注音',False),('show_progress','显示播放进度',True),('show_spectrum','显示条状频谱',True),('show_context','显示上下句',True)]:
                toggle=Gtk.CheckMenuItem(label=tr(caption));toggle.set_active(self.row['settings'].get(key,default))
                toggle.connect('toggled',lambda w,k=key:self.layer.manager.edit(self.row['instance'],settings={**self.row['settings'],k:w.get_active()}));menu.append(toggle)
            menu.append(Gtk.SeparatorMenuItem())
        for caption,callback in [('解锁位置' if self.row['locked'] else '锁定位置',lambda:self.layer.manager.edit(self.row['instance'],locked=not self.row['locked'])),('组件设置',self.settings),('自定义 CSS',self.edit_css),('复制组件',self.duplicate),('重新启动',self.restart),('移除组件',lambda:self.layer.manager.remove(self.row['instance']))]:
            item=Gtk.MenuItem(label=tr(caption));item.set_sensitive((caption!='组件设置' or self.definition['kind']=='plugin') and (caption!='复制组件' or self.definition.get('repeatable',True)));item.connect('activate',lambda _,cb=callback:cb());menu.append(item)
        old=button.get_popup();button.set_popup(menu)
        if old:old.destroy()
        menu.show_all();return False

    def settings(self):
        if self.definition['kind']!='plugin':return
        from adws_plugin_settings import SettingsDialog,validate_settings
        manifest=self.definition['manifest']
        dialog=SettingsDialog(self.layer.window,manifest['name'],manifest.get('settingsSchema',[]),self.row['settings'],validator=validate_settings if manifest.get('packageId')=='org.AkiACG_Community.NCMLyricsBar' else None)
        values=dialog.run()
        if values is not None:self.layer.manager.edit(self.row['instance'],settings=values)

    def clock_double_click(self,widget,event):
        if event.button!=1 or event.type!=Gdk.EventType.DOUBLE_BUTTON_PRESS:return False
        target=Gtk.get_event_widget(event)
        while target is not None and target is not self.box:
            if isinstance(target,Gtk.Button):return False
            target=target.get_parent()
        self.settings();return True

    def focus_card(self,widget=None,event=None):
        self.layer.window.clear_selection()
        target=Gtk.get_event_widget(event) if event is not None else None
        while target is not None and target is not self.box:
            if isinstance(target,(Gtk.TextView,Gtk.Entry,Gtk.Range,Gtk.Button,Gtk.ComboBox)):
                return False  # Preserve the text/control focus established by its click.
            target=target.get_parent()
        self.box.grab_focus();return False

    def press(self,widget,event,resizing):
        self.focus_card()
        if event.button!=1 or self.row['locked']:return False
        start=copy.deepcopy(self.row)
        x,y,w,h=getattr(self,'placed_geometry',model.geometry(start,self.layer.window.area.get_allocated_width(),self.layer.window.area.get_allocated_height()))
        start.update(x=x,y=y,width=max(200,w),height=max(120,h))
        self.gesture=(event.x_root,event.y_root,start,resizing)
        return True

    def motion(self,widget,event):
        if not self.gesture:return False
        x,y,start,resizing=self.gesture;dx=round(event.x_root-x);dy=round(event.y_root-y)
        if resizing:self.row.update(width=max(200,min(2000,start['width']+dx)),height=max(120,min(1600,start['height']+dy)))
        width,height=self.layer.window.area.get_allocated_width(),self.layer.window.area.get_allocated_height()
        # Keep the top-left under the pointer while resizing; persist its new ratio.
        effective=self.row if resizing else {**self.row,'width':start['width'],'height':start['height']}
        self.row.update(model.position(effective,start['x']+(0 if resizing else dx),start['y']+(0 if resizing else dy),width,height))
        self.row.pop('x',None);self.row.pop('y',None)
        self.layer.place();return True

    def release(self,widget,event):
        if event.button!=1 or not self.gesture:return False
        self.gesture=None
        self.layer.manager.edit(self.row['instance'],**{key:self.row[key] for key in ('x_percent','y_percent','width','height')})
        return True

    def note_changed(self,buffer):
        if buffer.get_char_count()>20000:
            buffer.delete(buffer.get_iter_at_offset(20000),buffer.get_end_iter())
        if self.note_source:GLib.source_remove(self.note_source)
        self.note_source=GLib.timeout_add(500,self.save_note)

    def save_note(self):
        if self.note_source:GLib.source_remove(self.note_source);self.note_source=0
        if self.note is None:return
        buffer=self.note.get_buffer();text=buffer.get_text(buffer.get_start_iter(),buffer.get_end_iter(),True)[:20000]
        if text!=self.row['settings'].get('text',''):
            settings={**self.row['settings'],'text':text};self.row['settings']=settings
            # Update the signature too; typing a note must not destroy its editor.
            self.signature=copy.deepcopy((self.definition,settings,self.row.get('css','')))
            self.layer.manager.edit(self.row['instance'],settings=settings)

    def start(self,*_):
        if self.closed or self.source:return
        if self.definition['kind']=='plugin':
            self.stream=self.layer.manager.subscribe(self.definition,self.row)
        if self.row['component']=='builtin:clock' or self.definition['kind']=='plugin':
            self.tick();self.source=GLib.timeout_add(100 if self.stream else 1000,self.tick)

    def update_ruby(self, value):
        # Bound and validate data from external packages; never interpret markup.
        valid=(self.lyrics and self.row['settings'].get('show_furigana',False)
               and isinstance(value,list) and 0<len(value)<=200
               and all(isinstance(r,dict) and isinstance(r.get('base'),str)
                       and isinstance(r.get('reading'),str) and len(r['base'])<=200
                       and len(r['reading'])<=64 for r in value)
               and ''.join(r['base'] for r in value)==self.primary.get_text())
        runs=tuple((r['base'],r['reading']) for r in value) if valid else ()
        self.ruby_value=runs
        self.reflow_ruby(self.ruby_width)

    def reflow_ruby(self, available):
        self.ruby_width=available
        if not self.lyrics:return
        text=self.primary.get_text()
        font=self.primary.get_style_context().get_font(Gtk.StateFlags.NORMAL).copy()
        # Convert CSS/Pango point sizes to logical pixels, independent of output scale.
        from gi.repository import PangoCairo
        dpi=PangoCairo.context_get_resolution(self.primary.get_pango_context())
        base=font.get_size()/Pango.SCALE
        if not font.get_size_is_absolute():base*=((dpi if dpi>0 else 96)/72)
        base=max(1,min(256,base or 28));minimum=min(base,max(18,int(base*.72)))
        signature=(text,self.ruby_value,available,font.to_string(),self.text_css,self.custom_css)
        if signature==self.fit_signature:return
        self.fit_signature=signature
        def width(value,size):
            layout=self.primary.create_pango_layout(value)
            desc=font.copy();desc.set_absolute_size(size*Pango.SCALE);layout.set_font_description(desc)
            return layout.get_pixel_size()[0]
        def run_widths(runs,size):
            return [max(width(b,size),width(r,max(10,size*.45))) for b,r in runs]
        runs=self.ruby_value or ()
        plain_width=width(text,base)
        natural=sum(run_widths(runs,base)) if runs else plain_width
        size=base if natural<=available else max(minimum,int(base*available/max(1,natural)))
        wrapped=natural>available
        def size_attrs(label,pixels):
            attrs=Pango.AttrList();attrs.insert(Pango.attr_size_new_absolute(round(pixels*Pango.SCALE)));label.set_attributes(attrs)
        size_attrs(self.primary,size)
        self.primary.set_xalign(.5 if wrapped else self.lyric_align)
        self.primary.set_justify(Gtk.Justification.CENTER)
        self.fit_font_size=size;self.fit_minimum=minimum;self.fit_rows=1
        rows=[]
        if runs:
            widths=run_widths(runs,size);total=sum(widths)
            if total<=available:rows=[runs]
            elif len(runs)>1:
                # Split only between source-aligned groups, keeping readings over their kanji.
                cuts=[];left=0
                for index,w in enumerate(widths[:-1],1):
                    left+=w;right=total-left
                    if max(left,right)<=available:cuts.append((abs(left-right),index))
                if cuts:
                    cut=min(cuts)[1];rows=[runs[:cut],runs[cut:]]
        # Extremely long/unbreakable readings fall back to two centered original-text lines.
        # GTK ellipsizes only if even two lines cannot fit at the readable minimum.
        for child in self.ruby.get_children():child.destroy()
        self.ruby_tokens=[]
        for row in rows:
            line=Gtk.Box(spacing=0)
            line.set_halign(Gtk.Align.CENTER if wrapped else Gtk.Align.START if self.lyric_align==0 else Gtk.Align.END if self.lyric_align==1 else Gtk.Align.CENTER)
            self.ruby.pack_start(line,False,False,0)
            for original,reading in row:
                box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=0)
                annotation=Gtk.Label(label=reading or ' ');annotation.get_style_context().add_class('desktop-furigana')
                label=Gtk.Label(label=original);label.get_style_context().add_class('desktop-primary')
                box.pack_start(annotation,False,False,0);box.pack_start(label,False,False,0)
                line.pack_start(box,False,False,0);self.ruby_tokens.append(box)
                for widget in (line,box,annotation,label):
                    context=widget.get_style_context()
                    context.add_provider(self.layer.provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+10)
                    if self.text_provider:context.add_provider(self.text_provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+20)
                    if self.custom_provider:context.add_provider(self.custom_provider,Gtk.STYLE_PROVIDER_PRIORITY_USER+10)
                size_attrs(label,size);size_attrs(annotation,max(10,size*.45))
            line.show_all()
        self.fit_rows=len(rows) if rows else (2 if width(text,size)>available else 1)
        self.ruby.set_visible(bool(rows));self.primary.set_visible(not rows)

    def tick(self):
        if self.closed:return False
        if self.interactive:
            value=self.stream.take() if self.stream else None
            if value:
                if value.get('class')=='error':
                    self.interactive.error.set_text(str(value.get('primary',tr('桌面组件运行失败'))));self.interactive.error.show()
                else:self.interactive.update(value)
            return True
        if self.stream:
            value=self.stream.take()
            if value:
                self.primary.set_text(str(value.get('primary',value.get('text','')))[:4096])
                self.update_ruby(value.get('ruby'))
                source=value.get('romanization_source')
                hint=tr('罗马音来源：')+source if isinstance(source,str) and source else None
                self.ruby.set_tooltip_text(hint);self.romanization.set_tooltip_text(hint)
                secondary=str(value.get('secondary',''))[:4096]
                self.secondary.set_text(secondary);self.secondary.set_visible(bool(secondary));self.separator.set_visible(bool(secondary) and not self.lyrics)
                for field,label in [('previous',self.previous),('romanization',self.romanization),('next',self.following)]:
                    text=value.get(field,'')
                    text=text[:4096] if isinstance(text,str) else ''
                    label.set_text(text);label.set_visible(bool(text))
                self.media_player=value.get('player')
                self.media_capabilities=value.get('controls',{}) if isinstance(value.get('controls',{}),dict) else {}
                if self.lyrics:
                    self.media.update(value)
                    layout_key=tuple(str(value.get(k,'')) for k in ('primary','secondary','previous','next','romanization','ruby'))
                    if getattr(self,'media_layout_key',None)!=layout_key:
                        self.media_layout_key=layout_key;self.layer.place()
                    self.title.set_text(str(value.get('title') or tr('桌面歌词'))[:256])
                    play=self.control_buttons.get('play-pause')
                    if play:play.set_image(Gtk.Image.new_from_icon_name('media-playback-pause-symbolic' if value.get('playing') else 'media-playback-start-symbolic',Gtk.IconSize.BUTTON))
                failed=value.get('class')=='error'
                context=self.box.get_style_context()
                (context.add_class if failed else context.remove_class)('desktop-error')
        else:
            now=datetime.now();self.primary.set_text(now.strftime('%H:%M:%S'));self.secondary.set_text(now.strftime('%Y-%m-%d · %A'))
        if self.definition['kind']=='plugin':
            if self.control_result is not None:
                (message,was_seek),self.control_result=self.control_result,None
                if was_seek and hasattr(self,'media'):self.media.seek_finished(not message)
                self.control_message.set_text(message);self.control_message.set_visible(bool(message))
            for action,button in self.control_buttons.items():
                button.set_sensitive(not self.control_busy and self.media_capabilities.get(action,True) is not False)
        return True

    def stop(self,*_):
        if self.interactive:self.interactive.stop()
        if hasattr(self,'media'):self.media.suspend()
        if self.source:GLib.source_remove(self.source);self.source=0
        if self.stream:self.stream.close();self.stream=None
        self.save_note()

    def restart(self):
        self.layer.manager.restart_instance(self.row['instance'])

    def control(self,action,position=None,player=None,track_id=None,token=None):
        if self.control_busy or self.closed:return False
        self.control_busy=True
        for button in self.control_buttons.values():button.set_sensitive(False)
        player=player or self.media_player
        import threading
        def run():
            message=''
            try:
                import adws_plugin as mplg
                root=mplg.materialize(self.definition['file']);manifest=self.definition['manifest']
                command=[sys.executable,str(root/manifest['entry']),'--settings-json',json.dumps(self.row['settings'])]
                command+=['--seek',str(position),'--track-id',track_id,'--track-token',token] if action=='seek' else ['--control',action]
                if manifest.get('packageId')=='org.AkiACG_Community.NCMLyricsBar' and isinstance(player,str) and player.startswith('org.mpris.MediaPlayer2.'):
                    command+=['--player',player]
                process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                try:
                    if process.wait(timeout=4)!=0:message=tr('播放器未能执行操作，请检查音乐页面是否仍在播放且允许媒体控制。')
                except subprocess.TimeoutExpired:
                    process.kill();process.wait();message=tr('播放器响应超时，请重试。')
            except (OSError,ValueError) as error:
                LOG.warning('Desktop media control failed: %s',error);message=tr('无法执行播放控制，请检查插件状态。')
            finally:self.control_result=(message,action=='seek');self.control_busy=False
        threading.Thread(target=run,daemon=True).start()
        return True

    def dispose(self):
        if self.closed:return
        self.closed=True;self.stop()
        if self.interactive:self.interactive.close()
        if hasattr(self,'media'):self.media.close()

    def destroy(self):
        self.dispose();self.box.destroy()

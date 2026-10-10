"""ADWS clipboard cards, sharing the dashboard's frosted popup lifecycle."""
import importlib.util
from collections import OrderedDict
from pathlib import Path
import sys
import threading
import gi
gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0')
from gi.repository import Gtk,Gdk,Gio,GLib,Pango
from adws_i18n import tr, prepare_gtk_language
from adws_popup import PopupBehavior, prepare_surface
from adws_sidebar import SidebarStyle
from adws_sidebar_board import icon_button
from adws_control_center import ControlCenter
from adws_system_settings import label
import adws_clipboard as backend
from adws_clipboard_preview import thumbnail
ROOT=Path(__file__).resolve().parents[1]


def preview(line):
    content=line.split('\t',1)[-1]
    binary=content.startswith('[[ binary data ')
    link=content.strip().lower().startswith(('https://','http://'))
    kind='图片 / 文件' if binary else '链接' if link else '文本'
    icon='image-x-generic-symbolic' if binary else 'web-browser-symbolic' if link else 'text-x-generic-symbolic'
    # Labels are always plain text. Bound layout work even for oversized records.
    text=(content.removeprefix('[[ binary data ').removesuffix(' ]]') if binary else content)[:1200]
    return kind,icon,text


class Clipboard(PopupBehavior,Gtk.ApplicationWindow):
    def __init__(self,app):
        super().__init__(application=app)
        self.closed=False;self.closing=False;self.had_focus=False;self.interaction_depth=0
        self.motion_source=0;self.focus_source=0;self.layer=None;self.busy=False
        self.records=[];self.matching=[];self.visible_limit=80
        self.thumbnail_cache=OrderedDict();self.thumbnail_active=False;self.thumbnail_source=0
        self.thumbnail_stop=threading.Event();self.detail_popup=None
        self.window_pinned=False;self.manual_position=None;self.drag_origin=None
        self.drag_source=0;self.drag_target=None
        spec=importlib.util.spec_from_file_location('adws_clipboard_config',ROOT/'tools/adws-config.py')
        self.config=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.config;spec.loader.exec_module(self.config)
        self.set_title(tr('剪贴板'));self.set_decorated(False);self.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        self.set_skip_taskbar_hint(True)
        for name in ('adws-system-settings','adws-quick-panel','adws-sidebar','adws-clipboard'):self.get_style_context().add_class(name)
        prepare_surface(self)
        import os
        if os.environ.get('XDG_SESSION_TYPE')!='x11' and os.environ.get('WAYLAND_DISPLAY'):
            try:
                gi.require_version('GtkLayerShell','0.1');from gi.repository import GtkLayerShell as layer
                if layer.is_supported():
                    self.layer=layer;layer.init_for_window(self);layer.set_layer(self,layer.Layer.OVERLAY)
                    layer.set_namespace(self,'launcher');layer.set_keyboard_mode(self,layer.KeyboardMode.ON_DEMAND);layer.set_exclusive_zone(self,0)
            except (ImportError,ValueError):pass
        self.position({'edge':'top','inset':55})
        outer=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12,margin=16);self.add(outer)
        header=Gtk.Box(spacing=8);heading=label('剪贴板','settings-page-title')
        self.drag_handle=Gtk.EventBox();self.drag_handle.set_visible_window(False);self.drag_handle.add(heading)
        self.drag_handle.add_events(Gdk.EventMask.BUTTON_PRESS_MASK|Gdk.EventMask.BUTTON_RELEASE_MASK|Gdk.EventMask.POINTER_MOTION_MASK)
        self.drag_handle.connect('button-press-event',self.drag_press)
        self.drag_handle.connect('motion-notify-event',self.drag_motion)
        self.drag_handle.connect('button-release-event',self.drag_release)
        header.pack_start(self.drag_handle,True,True,0)
        self.refresh_button=icon_button('view-refresh-symbolic','刷新',self.load)
        header.pack_end(icon_button('window-close-symbolic','关闭',lambda *_:self.dismiss()),False,False,0)
        self.window_pin_button=Gtk.ToggleButton()
        self.window_pin_button.add(Gtk.Image.new_from_icon_name('view-pin-symbolic',Gtk.IconSize.BUTTON))
        self.window_pin_button.get_style_context().add_class('sidebar-icon-button')
        self.window_pin_button.set_tooltip_text(tr('窗口置顶（可拖动）'))
        self.window_pin_button.connect('toggled',self.toggle_window_pin)
        header.pack_end(self.window_pin_button,False,False,0)
        header.pack_end(self.refresh_button,False,False,0);outer.pack_start(header,False,False,0)
        hint=label('选择记录复制，回到目标窗口粘贴。','dim-label');hint.set_max_width_chars(35);outer.pack_start(hint,False,False,0)
        self.search=Gtk.SearchEntry();self.search.set_placeholder_text(tr('搜索剪贴板'))
        if self.layer:self.search.set_property('im-module','wayland')
        self.search.connect('search-changed',self.filter_changed)
        self.search.connect('activate',self.copy_selected)
        outer.pack_start(self.search,False,False,0)
        self.stack=Gtk.Stack();self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_hhomogeneous(True);self.stack.set_vhomogeneous(True)
        self.listing=Gtk.ListBox();self.listing.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listing.get_style_context().add_class('clipboard-list')
        self.listing.connect('row-activated',lambda _,row:self.copy(row.record))
        self.scroll=Gtk.ScrolledWindow();self.scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC);self.scroll.set_overlay_scrolling(False)
        self.scroll.get_vadjustment().connect('value-changed',self.queue_thumbnails)
        self.scroll.connect('size-allocate',self.queue_thumbnails)
        history=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        history.pack_start(self.listing,False,False,0)
        self.more_button=Gtk.Button(label=tr('显示更多'));self.more_button.set_no_show_all(True)
        self.more_button.connect('clicked',self.load_more);history.pack_start(self.more_button,False,False,0)
        self.scroll.add(history);self.stack.add_named(self.scroll,'history')
        empty=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12);empty.set_valign(Gtk.Align.CENTER)
        image=Gtk.Image.new_from_icon_name('edit-paste-symbolic',Gtk.IconSize.DIALOG);image.set_pixel_size(48);empty.pack_start(image,False,False,0)
        self.empty_title=label('暂无剪贴板历史');self.empty_title.set_halign(Gtk.Align.CENTER);empty.pack_start(self.empty_title,False,False,0)
        self.empty_hint=label('复制一些文字或图片，它们会出现在这里。','dim-label');self.empty_hint.set_max_width_chars(30);self.empty_hint.set_halign(Gtk.Align.CENTER);empty.pack_start(self.empty_hint,False,False,0)
        self.stack.add_named(empty,'empty');outer.pack_start(self.stack,True,True,0)
        footer=Gtk.Box(spacing=8);self.count=label('','dim-label');footer.pack_start(self.count,True,True,0)
        self.spinner=Gtk.Spinner();footer.pack_end(self.spinner,False,False,0)
        self.clear_button=Gtk.Button(label=tr('清空历史'));self.clear_button.connect('clicked',self.confirm_clear);footer.pack_end(self.clear_button,False,False,0)
        outer.pack_end(footer,False,False,0)
        self.status=label('','dim-label');self.status.set_max_width_chars(36);self.status.set_no_show_all(True);outer.pack_end(self.status,False,False,0)
        self.style=ClipboardStyle(self)
        self.connect('focus-in-event',self.focus_in);self.connect('focus-out-event',self.focus_out)
        self.connect('key-press-event',self.key_pressed);self.connect('destroy',self.cleanup)
        self.connect('size-allocate',lambda *_:self.position(self.anchor,resize=False))
        self.show_records([])

    def position(self,anchor,resize=True):
        if self.manual_position is None:
            return ControlCenter.position(self,anchor,resize)
        if not self.closed:self.move_pinned(*self.manual_position)

    def toggle_window_pin(self,button):
        self.window_pinned=button.get_active()
        if self.focus_source:GLib.source_remove(self.focus_source);self.focus_source=0
        if self.window_pinned:
            self.manual_position=tuple(self.base_position)
            if self.layer:
                for name in ('left','right','top','bottom'):
                    self.layer.set_anchor(self,getattr(self.layer.Edge,name.upper()),name in ('left','top'))
                # Position over the entire output rather than its reserved work area.
                self.layer.set_exclusive_zone(self,-1)
            else:self.set_keep_above(True)
            self.move_pinned(*self.manual_position)
        else:
            self.stop_drag()
            if not self.layer:self.set_keep_above(False)
        button.set_tooltip_text(tr('取消窗口置顶') if self.window_pinned else tr('窗口置顶（可拖动）'))
        self.drag_handle.set_tooltip_text(tr('拖动标题移动窗口；点击 × 关闭。') if self.window_pinned else None)
        if self.drag_handle.get_window():
            cursor=Gdk.Cursor.new_from_name(self.get_display(),'grab') if self.window_pinned else None
            self.drag_handle.get_window().set_cursor(cursor)

    def focus_out(self,*args):
        if self.window_pinned:return False
        return PopupBehavior.focus_out(self,*args)

    def move_pinned(self,x,y):
        rect=self.popup_monitor.get_geometry()
        width,height=self.get_allocated_width(),self.get_allocated_height()
        x=max(rect.x,min(round(x),rect.x+max(0,rect.width-width)))
        y=max(rect.y,min(round(y),rect.y+max(0,rect.height-height)))
        self.manual_position=self.base_position=(x,y)
        if self.layer:
            self.layer.set_margin(self,self.layer.Edge.LEFT,x-rect.x)
            self.layer.set_margin(self,self.layer.Edge.TOP,y-rect.y)
            self.queue_draw()
        else:self.move(x,y)

    def drag_press(self,widget,event):
        if not self.window_pinned or event.button!=1 or self.closing:return False
        if self.motion_source:
            self.stop_motion();self.motion_opacity=1;self.queue_draw()
        self.drag_origin=(event.x,event.y,event.x_root,event.y_root,*self.manual_position)
        self.interaction_depth+=1;widget.grab_add()
        return True

    def drag_motion(self,widget,event):
        if self.drag_origin is None:return False
        x,y,root_x,root_y,start_x,start_y=self.drag_origin
        # Keep the button grab's coordinate frame. Adding the displacement to
        # the last requested margin accumulates the same movement repeatedly.
        self.drag_target=(start_x+event.x_root-root_x,start_y+event.y_root-root_y)
        if not self.drag_source:self.drag_source=GLib.timeout_add(16,self.apply_drag)
        return True

    def apply_drag(self):
        self.drag_source=0
        if not self.closed and self.drag_target is not None:
            self.move_pinned(*self.drag_target);self.drag_target=None
        return False

    def drag_release(self,widget,event):
        if self.drag_origin is None or event.button!=1:return False
        self.stop_drag();return True

    def stop_drag(self):
        if self.drag_source:GLib.source_remove(self.drag_source);self.drag_source=0
        self.apply_drag()
        if self.drag_origin is not None:
            self.drag_handle.grab_remove();self.interaction_depth=max(0,self.interaction_depth-1)
        self.drag_origin=None

    def page_changed(self,*_):
        self.search.grab_focus();self.load();return False

    def work(self,operation,consume):
        if self.closed or self.busy:return
        self.busy=True;self.spinner.start();self.refresh_button.set_sensitive(False);self.clear_button.set_sensitive(False)
        self.listing.set_sensitive(False);self.status.hide()
        def worker():
            try:result,error=operation(),None
            except Exception as exc:result,error=None,str(exc)
            def done():
                if self.closed:return False
                self.busy=False;self.spinner.stop();self.refresh_button.set_sensitive(True);self.listing.set_sensitive(True)
                self.clear_button.set_sensitive(any(not backend.pins.identity(line) for line in self.records))
                if error:self.status.set_text(error);self.status.show()
                else:consume(result)
                return False
            if not self.closed:GLib.idle_add(done)
        threading.Thread(target=worker,name='adws-clipboard',daemon=True).start()

    def load(self,*_):
        def read():backend.ensure_watcher();return backend.list_records()
        self.work(read,self.show_records)

    def show_records(self,records):
        self.records=records
        retained=set(records)
        for line in list(self.thumbnail_cache):
            if line not in retained:del self.thumbnail_cache[line]
        self.filter_changed(reset=False)
        self.clear_button.set_sensitive(any(not backend.pins.identity(line) for line in records))

    def render_records(self,records,append=False):
        if not append:
            for row in self.listing.get_children():row.destroy()
        for line in records:
            row=Gtk.ListBoxRow();row.record=line;row.get_style_context().add_class('clipboard-card')
            box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8,margin=12)
            kind,icon,text=preview(line)
            head=Gtk.Box(spacing=8);head.pack_start(Gtk.Image.new_from_icon_name(icon,Gtk.IconSize.MENU),False,False,0)
            pinned=bool(backend.pins.identity(line))
            head.pack_start(label(tr('已固定')+' · '+tr(kind) if pinned else kind,'dim-label'),True,True,0)
            if pinned:row.get_style_context().add_class('pinned')
            delete=icon_button('edit-delete-symbolic','删除记录',lambda _,line=line:self.delete(line));head.pack_end(delete,False,False,0)
            row.pin_button=icon_button('view-pin-symbolic','取消固定' if pinned else '固定',lambda _,line=line:self.toggle_pin(line))
            row.pin_button.get_style_context().add_class('clipboard-pin')
            head.pack_end(row.pin_button,False,False,0)
            row.preview_button=icon_button('document-properties-symbolic','查看内容',lambda button,line=line:self.show_detail(button,line))
            head.pack_end(row.preview_button,False,False,0)
            box.pack_start(head,False,False,0)
            row.thumbnail=None
            if kind=='图片 / 文件':
                row.thumbnail=Gtk.Image.new_from_icon_name('image-x-generic-symbolic',Gtk.IconSize.DIALOG)
                row.thumbnail.set_size_request(-1,160);box.pack_start(row.thumbnail,False,False,0)
            content=Gtk.Label(label=text,xalign=0);content.set_line_wrap(True);content.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            content.set_ellipsize(Pango.EllipsizeMode.END);content.set_lines(3);content.set_max_width_chars(34)
            box.pack_start(content,False,False,0);row.add(box);self.listing.add(row)
        self.listing.show_all()
        self.queue_thumbnails()

    def queue_thumbnails(self,*_):
        if self.closed or self.thumbnail_source:return
        self.thumbnail_source=GLib.timeout_add(60,self.load_visible_thumbnail)

    def load_visible_thumbnail(self):
        self.thumbnail_source=0
        if self.closed:return False
        adjustment=self.scroll.get_vadjustment();top=adjustment.get_value();bottom=top+adjustment.get_page_size()
        pending=None
        for row in self.listing.get_children():
            if row.thumbnail is None:continue
            allocation=row.get_allocation()
            visible=allocation.height>1 and allocation.y+allocation.height>top and allocation.y<bottom
            if not visible:
                row.thumbnail.clear();continue
            line=row.record
            if line in self.thumbnail_cache:
                pixbuf=self.thumbnail_cache[line];self.thumbnail_cache.move_to_end(line)
                if pixbuf is not None:row.thumbnail.set_from_pixbuf(pixbuf)
                else:row.thumbnail.set_from_icon_name('image-x-generic-symbolic',Gtk.IconSize.DIALOG)
            elif pending is None:pending=line
        if pending is None or self.thumbnail_active:return False
        self.thumbnail_active=True
        def worker():
            try:pixbuf=thumbnail(backend.preview_data(pending,cancelled=self.thumbnail_stop))
            except (OSError,ValueError,TimeoutError,GLib.Error):pixbuf=None
            def done():
                if self.closed:return False
                self.thumbnail_active=False
                if pending in self.records:self.thumbnail_cache[pending]=pixbuf
                while len(self.thumbnail_cache)>24:self.thumbnail_cache.popitem(last=False)
                self.queue_thumbnails();return False
            if not self.closed:GLib.idle_add(done)
        threading.Thread(target=worker,name='adws-clipboard-thumbnail',daemon=True).start()
        return False

    def show_detail(self,button,line):
        if self.closed or self.busy:return
        if self.detail_popup:self.detail_popup.destroy()
        popup=self.detail_popup=Gtk.Popover.new(button);stop=threading.Event()
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10,margin=12)
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(min(340,max(160,self.get_allocated_width()-72)),280)
        view=Gtk.TextView(editable=False,wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.get_buffer().set_text(tr('正在读取内容…'));scroll.add(view);box.pack_start(scroll,True,True,0)
        actions=Gtk.Box(spacing=8);close=Gtk.Button(label=tr('关闭'));close.connect('clicked',lambda *_:popup.popdown())
        copy=Gtk.Button(label=tr('复制'));copy.connect('clicked',lambda *_:(popup.popdown(),self.copy(line)))
        actions.pack_end(copy,False,False,0);actions.pack_end(close,False,False,0);box.pack_start(actions,False,False,0)
        def destroyed(*_):
            stop.set()
            if self.detail_popup==popup:self.detail_popup=None
        popup.connect('destroy',destroyed);popup.connect('closed',lambda *_:popup.destroy())
        popup.add(box);popup.show_all();popup.popup()
        if preview(line)[0]=='图片 / 文件':
            view.get_buffer().set_text(tr('图片或文件保留原始内容，点击复制即可使用。'));return
        def read():
            try:return backend.preview_data(line,limit=64*1024,cancelled=stop).decode('utf-8',errors='replace')
            except (OSError,ValueError,TimeoutError):return tr('内容过大或暂时无法预览，仍可复制完整内容。')
        def consume(text):
            if not self.closed and self.detail_popup==popup:view.get_buffer().set_text(text)
            return False
        def worker():
            text=read()
            if not stop.is_set():GLib.idle_add(consume,text)
        threading.Thread(target=worker,name='adws-clipboard-detail',daemon=True).start()

    def filter_changed(self,*_,reset=True):
        selected=self.listing.get_selected_row()
        record=selected.record if selected else None
        index=selected.get_index() if selected else 0
        focused=bool(selected and self.get_focus() and self.get_focus().is_ancestor(selected))
        focused=focused or bool(selected and selected.has_focus())
        if reset:self.visible_limit=80
        needle=self.search.get_text().casefold()
        matching=self.matching=[line for line in self.records if needle in line.split('\t',1)[-1].casefold()]
        self.render_records(matching[:self.visible_limit]);self.update_count()
        self.stack.set_visible_child_name('history' if matching else 'empty')
        self.empty_title.set_text(tr('没有匹配的记录') if self.records else tr('暂无剪贴板历史'))
        self.empty_hint.set_text(tr('试试其他关键词。') if self.records else tr('复制一些文字或图片，它们会出现在这里。'))
        rows=self.listing.get_children()
        if rows:
            row=next((row for row in rows if row.record==record),rows[min(index,len(rows)-1)] if not reset else rows[0])
            self.listing.select_row(row)
            if focused:row.grab_focus()

    def update_count(self):
        shown=len(self.listing.get_children());total=len(self.matching)
        self.count.set_text(tr('%s / %s 条记录') % (shown,total) if shown<total else tr('%s 条记录') % total)
        self.more_button.set_visible(shown<total)

    def load_more(self,*_):
        if self.busy or self.closed:return
        start=len(self.listing.get_children());self.visible_limit=start+80
        # Append one bounded batch; keep existing rows, selection and scroll position.
        self.render_records(self.matching[start:self.visible_limit],append=True);self.update_count()
        if self.more_button.has_focus() or not self.more_button.get_visible():
            rows=self.listing.get_children()
            if start<len(rows):rows[start].grab_focus()

    def copy(self,line):
        def copied(_):
            if self.window_pinned:self.status.set_text(tr('已复制'));self.status.show()
            else:self.dismiss()
        self.work(lambda:backend.copy_entry(line),copied)
    def toggle_pin(self,line):
        def updated(records):
            self.show_records(records)
            content=line.split('\t',1)[-1]
            row=next((row for row in self.listing.get_children() if row.record.split('\t',1)[-1]==content),None)
            if row:self.listing.select_row(row)
        self.work(lambda:backend.toggle_pin(line),updated)
    def copy_selected(self,*_):
        row=self.listing.get_selected_row()
        if row and row.get_child_visible():self.copy(row.record)
    def delete(self,line):
        self.work(lambda:backend.delete_entry(line),lambda _:self.show_records([item for item in self.records if item!=line]))

    def confirm_clear(self,button):
        if not self.records:return
        popup=Gtk.Popover.new(button);box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10,margin=12)
        caption=label('确定要清空普通历史吗？固定的记录会保留。');caption.set_max_width_chars(28);box.pack_start(caption,False,False,0)
        row=Gtk.Box(spacing=8);cancel=Gtk.Button(label=tr('取消'));cancel.connect('clicked',lambda *_:popup.popdown())
        confirm=Gtk.Button(label=tr('清空历史'));confirm.get_style_context().add_class('destructive-action')
        def wipe(*_):
            popup.popdown();self.work(lambda:backend.run(['cliphist','wipe']),lambda _:self.show_records([item for item in self.records if backend.pins.identity(item)]))
        confirm.connect('clicked',wipe);row.pack_start(cancel,True,True,0);row.pack_start(confirm,True,True,0);box.pack_start(row,False,False,0)
        popup.add(box);popup.connect('closed',lambda *_:popup.destroy());popup.show_all();popup.popup()

    def key_pressed(self,_,event):
        if event.keyval==Gdk.KEY_Escape:
            if self.window_pinned:
                if self.detail_popup:self.detail_popup.popdown()
            else:self.dismiss()
            return True
        if event.state&Gdk.ModifierType.CONTROL_MASK and event.keyval in (Gdk.KEY_f,Gdk.KEY_F):
            self.search.grab_focus();return True
        if event.keyval==Gdk.KEY_Down and self.search.has_focus():
            row=self.listing.get_selected_row()
            if row:row.grab_focus();return True
        row=self.listing.get_selected_row()
        if row and row.has_focus() and event.keyval==Gdk.KEY_space:
            self.show_detail(row.preview_button,row.record);return True
        if row and row.has_focus() and event.keyval==Gdk.KEY_Delete:
            self.delete(row.record);return True
        return False

    def cleanup(self,*_):
        self.closed=True
        self.stop_drag()
        self.thumbnail_stop.set();self.thumbnail_cache.clear()
        if self.detail_popup:self.detail_popup.destroy()
        self.stop_motion()
        for source in (self.focus_source,self.thumbnail_source):
            if source:GLib.source_remove(source)
        self.motion_source=self.focus_source=0;self.style.close()


class ClipboardStyle(SidebarStyle):
    def stylesheet(self,roles,options):
        return super().stylesheet(roles,options)+'''
        window.adws-clipboard .clipboard-list { background: transparent; }
        window.adws-clipboard .clipboard-card { background: alpha(@adws_settings_raised,.45); color: @adws_settings_text; border: 1px solid alpha(@adws_settings_outline,.6); border-radius: 14px; margin: 0 0 8px; padding: 0; }
        window.adws-clipboard .clipboard-card:hover { background: alpha(@adws_settings_accent,.13); border-color: alpha(@adws_settings_accent,.45); }
        window.adws-clipboard .clipboard-card:selected { background: alpha(@adws_settings_accent,.18); border-color: @adws_settings_accent; }
        window.adws-clipboard .clipboard-card label { color: inherit; }
        window.adws-clipboard .clipboard-card.pinned { border-color: alpha(@adws_settings_accent,.65); }
        window.adws-clipboard .clipboard-card.pinned .clipboard-pin { color: @adws_settings_accent; }
        window.adws-clipboard button.sidebar-icon-button:checked { background: alpha(@adws_settings_accent,.22); color: @adws_settings_accent; }
        '''


def picker():
    prepare_gtk_language()
    app=Gtk.Application(application_id='org.akiacg.ADWS.Clipboard');window=None;idle=0
    def closed(*_):
        nonlocal window,idle
        window=None;idle=GLib.timeout_add_seconds(60,lambda:app.quit() or False)
    def activate(*_):
        nonlocal window,idle
        if idle:GLib.source_remove(idle);idle=0
        if window:
            if window.closing:window.closing=False;window.present();window.animate(True)
            elif window.window_pinned:window.present()
            else:window.dismiss()
            return
        window=Clipboard(app);window.connect('destroy',closed);window.reveal()
    app.connect('activate',activate);app.hold();return app.run([])

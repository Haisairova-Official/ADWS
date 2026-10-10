#!/usr/bin/env python3
"""Clock-anchored calendar, local agenda and quick controls."""
import argparse
from datetime import date, datetime
import importlib.util
import json
import locale
import os
from pathlib import Path
import subprocess
import sys
import gi
gi.require_version('Gtk','3.0'); gi.require_version('Gdk','3.0')
from gi.repository import Gtk, Gdk, Gio, GLib, Pango
from adws_i18n import tr, prepare_gtk_language
from adws_popup import PopupBehavior, prepare_surface
from adws_sidebar import SidebarStyle
from adws_sidebar_board import icon_button
from adws_sidebar_widgets import QuickActions, LevelCard
from adws_system_settings import card, label
from adws_calendar import MonthCalendar
from adws_agenda_preview import AgendaPreview
from adws_agenda import load_events, save_event, delete_event

ROOT=Path(__file__).resolve().parents[1]


def popup_geometry(rect, width, height, anchor):
    """Keep the popup inside its actual output and clear of all four taskbar edges."""
    edge=anchor.get('edge','bottom')
    if edge not in ('left','right','top','bottom'):edge='bottom'
    def integer(value, fallback):
        try: return int(value)
        except (TypeError, ValueError, OverflowError): return fallback
    gap=min(10,max(0,(min(rect.width,rect.height)-1)//2))
    extent=rect.width if edge in ('left','right') else rect.height
    inset=min(max(gap,integer(anchor.get('inset'),48)),256,max(gap,extent-gap-1))
    width=max(1,min(width,rect.width-gap-(inset if edge in ('left','right') else gap)))
    height=max(1,min(height,rect.height-gap-(inset if edge in ('top','bottom') else gap)))
    x=max(gap,min(rect.width-width-gap,integer(anchor.get('x'),rect.width-width//2)-width//2))
    y=max(gap,min(rect.height-height-gap,integer(anchor.get('y'),rect.height//2)-height//2))
    if edge=='bottom':y=max(gap,rect.height-inset-height)
    elif edge=='top':y=inset
    elif edge=='left':x=inset
    else:x=max(gap,rect.width-inset-width)
    return x,y,width,height,edge,inset


class ControlCenter(PopupBehavior,Gtk.ApplicationWindow):
    def __init__(self,app,anchor=None):
        super().__init__(application=app)
        self.closed=False; self.closing=False; self.had_focus=False; self.interaction_depth=0
        self.motion_source=0;self.focus_source=0;self.timer=0;self.layer=None
        self.selected=date.today();self.editing=None;self.loading_calendar=False
        self.events=[];self.agenda_error=None
        self.config=sys.modules.get('adws_center_config')
        if self.config is None:
            spec=importlib.util.spec_from_file_location('adws_center_config',ROOT/'tools/adws-config.py')
            self.config=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.config;spec.loader.exec_module(self.config)
        self.set_title(tr('控制中心'));self.set_decorated(False);self.set_default_size(440,780)
        self.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU);self.set_skip_taskbar_hint(True)
        prepare_surface(self)
        for name in ('adws-system-settings','adws-quick-panel','adws-sidebar','adws-control-center'):self.get_style_context().add_class(name)
        if os.environ.get('XDG_SESSION_TYPE')!='x11' and os.environ.get('WAYLAND_DISPLAY'):
            try:
                gi.require_version('GtkLayerShell','0.1')
                from gi.repository import GtkLayerShell as layer
                if layer.is_supported():
                    self.layer=layer;layer.init_for_window(self);layer.set_layer(self,layer.Layer.OVERLAY)
                    layer.set_namespace(self,'launcher');layer.set_keyboard_mode(self,layer.KeyboardMode.ON_DEMAND)
                    layer.set_exclusive_zone(self,0)
            except (ImportError,ValueError):pass
        self.position(anchor or {})
        outer=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10,margin=16);self.add(outer)
        header=Gtk.Box(spacing=10)
        titles=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=3)
        self.clock=label('','sidebar-clock');self.today_label=label('','dim-label')
        titles.pack_start(self.clock,False,False,0);titles.pack_start(self.today_label,False,False,0)
        header.pack_start(titles,True,True,0)
        header.pack_end(icon_button('window-close-symbolic','关闭',lambda *_:self.dismiss()),False,False,0)
        outer.pack_start(header,False,False,0)
        self.stack=Gtk.Stack();self.stack.set_hhomogeneous(True);self.stack.set_vhomogeneous(False)
        tabs=Gtk.StackSwitcher(stack=self.stack);tabs.set_homogeneous(True);tabs.get_style_context().add_class('sidebar-tabs')
        outer.pack_start(tabs,False,False,0);outer.pack_start(self.stack,True,True,0)
        calendar_page=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10)
        calendar_card=card('日历')
        self.calendar=MonthCalendar();self.calendar.set_hexpand(True)
        self.calendar.connect('day-selected',self.day_selected)
        self.calendar.connect('month-changed',lambda *_:self.mark_days())
        calendar_card.pack_start(self.calendar,False,False,0);calendar_page.pack_start(calendar_card,False,False,0)
        agenda_card=card('当天日程');self.agenda_title=agenda_card.get_children()[0]
        self.agenda_list=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        agenda_card.pack_start(self.agenda_list,False,False,0)
        add=Gtk.Button(label=tr('添加日程'));add.connect('clicked',lambda *_:self.edit_event())
        agenda_card.pack_start(add,False,False,0);calendar_page.pack_start(agenda_card,False,False,0)
        self.editor=self.make_editor();self.editor.set_no_show_all(True)
        calendar_page.pack_start(self.editor,False,False,0)
        self.upcoming=AgendaPreview(self.open_upcoming)
        upcoming_box=card('日程概览');upcoming_box.pack_start(self.upcoming,False,False,0)
        calendar_page.pack_start(upcoming_box,False,False,0)
        calendar_page.reorder_child(self.editor,-1)
        self.calendar_scroll=self.add_page(calendar_page,'calendar','日历与日程')
        quick_page=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10)
        self.quick=QuickActions(self);quick_page.pack_start(self.quick.box,False,False,0)
        self.controls=[LevelCard(self,'sound'),LevelCard(self,'brightness')]
        for control in self.controls:quick_page.pack_start(control.box,False,False,0)
        self.add_page(quick_page,'controls','快捷开关')
        self.style=SidebarStyle(self)
        self.stack.connect('notify::visible-child-name',self.page_changed)
        self.connect('focus-in-event',self.focus_in);self.connect('focus-out-event',self.focus_out)
        self.connect('key-press-event',self.key_pressed)
        self.connect('size-allocate',lambda *_:self.position(self.anchor,resize=False))
        self.connect('destroy',self.cleanup)
        self.reload_agenda();self.tick();self.timer=GLib.timeout_add_seconds(1,self.tick)

    def add_page(self,content,name,title):
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
        scroll.set_overlay_scrolling(False);scroll.add(content);self.stack.add_titled(scroll,name,tr(title))
        return scroll

    def position(self,anchor,resize=True):
        if not resize and self.motion_source:
            self.popup_reposition=lambda:self.position(self.anchor,resize=False)
            return
        self.anchor=dict(anchor);display=self.get_display();index=anchor.get('monitor')
        monitors=[display.get_monitor(i) for i in range(display.get_n_monitors())]
        if not monitors:return
        # Allocations must stay on the opening output even if the pointer moves.
        retained=getattr(self,'popup_monitor',None)
        monitor=retained if not resize and retained in monitors else None
        if monitor is None and type(index)is int and 0<=index<len(monitors):monitor=monitors[index]
        if monitor is None:
            seat=display.get_default_seat();pointer=seat.get_pointer() if seat else None
            if pointer:
                _,x,y=pointer.get_position();monitor=display.get_monitor_at_point(x,y)
            monitor=monitor or display.get_primary_monitor() or monitors[0]
        self.popup_monitor=monitor;rect=monitor.get_geometry()
        _,_,width,height,_,_=popup_geometry(rect,440,780,anchor)
        if resize:
            self.set_size_request(width,height)
            self.set_default_size(width,height);self.resize(width,height)
        else:width,height=self.get_allocated_width(),self.get_allocated_height()
        x,y,_,_,edge,inset=popup_geometry(rect,width,height,anchor)
        self.slide_edge=edge
        self.placement_identity=(next((i for i in range(display.get_n_monitors()) if display.get_monitor(i)==monitor),0),edge,anchor.get('x'),anchor.get('y'))
        self.base_position=(rect.x+x,rect.y+y)
        self.base_margins={'left':x,'top':y,'right':max(10,rect.width-x-width),'bottom':max(10,rect.height-y-height)}
        if self.layer:
            layer=self.layer;layer.set_monitor(self,monitor)
            if resize:
                for name in ('left','right','top','bottom'):layer.set_anchor(self,getattr(layer.Edge,name.upper()),False)
            for name in ((edge,'left') if edge in ('top','bottom') else (edge,'top')):
                if resize:layer.set_anchor(self,getattr(layer.Edge,name.upper()),True)
                layer.set_margin(self,getattr(layer.Edge,name.upper()),self.base_margins[name])
        elif not self.motion_source:self.move(*self.base_position)

    def make_editor(self):
        box=card('编辑日程');self.fields={}
        for key,title,placeholder in [('title','日程名称',''),('date','日期','YYYY-MM-DD'),('time','开始时间','HH:mm'),('end','结束时间','HH:mm'),('notes','备注','')]:
            entry=Gtk.Entry();entry.set_placeholder_text(placeholder);entry.set_max_length(2000 if key=='notes' else 240)
            if self.layer:entry.set_property('im-module','wayland')
            row=Gtk.Box(spacing=8);caption=label(title);caption.set_width_chars(8)
            row.pack_start(caption,False,False,0);row.pack_start(entry,True,True,0);box.pack_start(row,False,False,0)
            self.fields[key]=entry
        self.all_day=Gtk.CheckButton(label=tr('全天'));self.all_day.connect('toggled',self.all_day_changed)
        box.pack_start(self.all_day,False,False,0)
        self.form_error=label('');box.pack_start(self.form_error,False,False,0)
        row=Gtk.Box(spacing=8)
        cancel=Gtk.Button(label=tr('取消'));cancel.connect('clicked',lambda *_:self.editor.hide())
        save=Gtk.Button(label=tr('保存'));save.get_style_context().add_class('suggested-action');save.connect('clicked',self.save_form)
        row.pack_end(save,False,False,0);row.pack_end(cancel,False,False,0);box.pack_start(row,False,False,0)
        return box

    def all_day_changed(self,*_):
        for key in ('time','end'):self.fields[key].set_sensitive(not self.all_day.get_active())

    def edit_event(self,event=None):
        self.editing=event['id'] if event else None
        for key,entry in self.fields.items():entry.set_text(str((event or {}).get(key,self.selected.isoformat() if key=='date' else '')))
        self.all_day.set_active(not (event or {}).get('time'));self.all_day_changed()
        self.form_error.set_text('');self.editor.set_no_show_all(False);self.editor.show_all();self.editor.set_no_show_all(True)
        self.fields['title'].grab_focus()
        def scroll():
            if not self.closed:
                adjustment=self.calendar_scroll.get_vadjustment();adjustment.set_value(adjustment.get_upper()-adjustment.get_page_size())
            return False
        GLib.idle_add(scroll)

    def save_form(self,*_):
        value={key:entry.get_text() for key,entry in self.fields.items()}
        if self.editing:value['id']=self.editing
        if self.all_day.get_active():value['time']='';value['end']=''
        try:event=save_event(value)
        except (OSError,ValueError) as exc:self.form_error.set_text(str(exc));return
        self.selected=date.fromisoformat(event['date']);self.editor.hide();self.select_date(self.selected);self.reload_agenda()

    def select_date(self,day):
        self.loading_calendar=True
        self.calendar.select_month(day.month-1,day.year);self.calendar.select_day(day.day)
        self.loading_calendar=False;self.selected=day

    def go_today(self,*_):
        self.select_date(date.today());self.editor.hide();self.reload_agenda()

    def day_selected(self,*_):
        if self.loading_calendar:return
        year,month,day=self.calendar.get_date()
        if day:
            self.selected=date(year,month+1,day);self.editor.hide();self.reload_agenda()

    def mark_days(self):
        self.calendar.clear_marks();year,month,_=self.calendar.get_date()
        for event in self.events:
            day=date.fromisoformat(event['date'])
            if day.year==year and day.month==month+1:self.calendar.mark_day(day.day)

    def open_upcoming(self,event):
        self.select_date(date.fromisoformat(event['date']));self.reload_agenda();self.edit_event(event)

    def reload_agenda(self):
        self.upcoming.refresh()
        try:self.events=load_events();self.agenda_error=None
        except (OSError,ValueError) as exc:self.agenda_error=str(exc)
        self.mark_days()
        for child in self.agenda_list.get_children():child.destroy()
        self.agenda_title.set_text(self.selected.strftime('%x')+' · '+tr('日程'))
        if self.agenda_error:self.agenda_list.pack_start(label(self.agenda_error),False,False,0)
        selected=[event for event in self.events if event['date']==self.selected.isoformat()]
        if not selected and not self.agenda_error:self.agenda_list.pack_start(label('当天暂无日程，给自己留一点空闲。','dim-label'),False,False,8)
        for event in selected:
            row=Gtk.Box(spacing=8);row.get_style_context().add_class('agenda-event');text=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=3)
            time=event['time']+('–'+event['end'] if event['end'] else '') if event['time'] else tr('全天')
            text.pack_start(label(time,'dim-label'),False,False,0)
            title=label(event['title']);title.set_max_width_chars(28);text.pack_start(title,False,False,0)
            if event['notes']:
                notes=label(event['notes'],'dim-label');notes.set_max_width_chars(28);text.pack_start(notes,False,False,0)
            row.pack_start(text,True,True,0)
            row.pack_end(icon_button('edit-delete-symbolic','删除日程',lambda button,event=event:self.confirm_delete(button,event)),False,False,0)
            row.pack_end(icon_button('document-edit-symbolic','编辑日程',lambda _,event=event:self.edit_event(event)),False,False,0)
            self.agenda_list.pack_start(row,False,False,0)
        self.agenda_list.show_all()

    def confirm_delete(self,button,event):
        popup=Gtk.Popover.new(button);box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10,margin=12)
        caption=label(tr('删除日程“%s”？') % event['title']);caption.set_max_width_chars(30);box.pack_start(caption,False,False,0)
        remove=Gtk.Button(label=tr('删除'));box.pack_start(remove,False,False,0)
        def remove_event(*_):
            try:delete_event(event['id'])
            except (OSError,ValueError) as exc:caption.set_text(str(exc));return
            popup.popdown();self.reload_agenda()
        remove.connect('clicked',remove_event);popup.add(box);popup.connect('closed',lambda *_:popup.destroy());popup.show_all();popup.popup()

    def page_changed(self,*_):
        if self.stack.get_visible_child_name()=='controls':
            self.quick.refresh()
            for control in self.controls:control.refresh()
        else:self.reload_agenda()
        return False

    def launch(self,*args):
        command=[str(ROOT/'adws'),*args]
        if args[0]=='clipboard':command=[sys.executable,str(ROOT/'tools/adws_clipboard.py')]
        subprocess.Popen(command,start_new_session=True)

    def tick(self):
        if self.closed:return False
        now=datetime.now();self.clock.set_text(now.strftime('%H:%M:%S'));self.today_label.set_text(now.strftime('%A · %x'))
        return True

    def key_pressed(self,_,event):
        if event.keyval==Gdk.KEY_Escape:
            if self.editor.get_visible():self.editor.hide()
            else:self.dismiss()
            return True
        return False

    def cleanup(self,*_):
        self.closed=True
        self.stop_motion()
        for source in (self.timer,self.focus_source):
            if source:GLib.source_remove(source)
        self.timer=self.motion_source=self.focus_source=0;self.style.close()


def run(anchor):
    prepare_gtk_language()
    try:locale.setlocale(locale.LC_TIME,'')
    except locale.Error:pass
    app=Gtk.Application(application_id='org.adws.ControlCenter');window=None;idle_source=0
    def closed(*_):
        nonlocal window,idle_source
        window=None
        idle_source=GLib.timeout_add_seconds(60,lambda:app.quit() or False)
    def opened(_,parameter):
        nonlocal window,idle_source
        if idle_source:GLib.source_remove(idle_source);idle_source=0
        target=json.loads(parameter.get_string())
        if window:
            if window.closing:window.closing=False;window.position(target);window.present();window.animate(True)
            elif window.anchor==target:window.dismiss()
            else:window.position(target);window.present()
        else:
            window=ControlCenter(app,target);window.connect('destroy',closed);window.reveal()
    action=Gio.SimpleAction.new('open',GLib.VariantType.new('s'));action.connect('activate',opened);app.add_action(action)
    app.register(None);payload=GLib.Variant('s',json.dumps(anchor))
    if app.get_is_remote():app.activate_action('open',payload);return 0
    app.hold();app.connect('activate',lambda *_:app.activate_action('open',payload));return app.run([])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='ADWS clock control center')
    parser.add_argument('--anchor',type=json.loads)
    parser.add_argument('--edge',choices=('top','bottom','left','right'),default='bottom')
    parser.add_argument('--inset',type=int,default=48)
    args=parser.parse_args()
    raise SystemExit(run(args.anchor or {'edge':args.edge,'inset':args.inset}))

"""A bounded upcoming-agenda view shared by both calendar surfaces."""
from datetime import date,timedelta
from gi.repository import Gtk
from adws_agenda import load_events
from adws_i18n import tr
from adws_system_settings import label


def upcoming(events,today=None):
    today=today or date.today();end=today+timedelta(days=min(6,date.max.toordinal()-today.toordinal()))
    return sorted((e for e in events if today.isoformat()<=e['date']<=end.isoformat()),key=lambda e:(e['date'],e['time'],e['title']))


class AgendaPreview(Gtk.Box):
    def __init__(self,activate=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        self.activate=activate;self.signature=None;self.limit=4
        self.connect('map',lambda *_:self.refresh())

    def refresh(self):
        try:items=upcoming(load_events());error=None
        except (OSError,ValueError) as exc:items=[];error=str(exc)
        signature=(repr(items),error,self.limit)
        if signature==self.signature:return
        self.signature=signature
        for child in self.get_children():child.destroy()
        self.pack_start(label('未来七天日程','settings-section-title'),False,False,0)
        if error:self.pack_start(label(error,'dim-label'),False,False,0)
        elif not items:self.pack_start(label('未来七天暂无日程。','dim-label'),False,False,0)
        for item in items[:self.limit]:
            content=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4)
            content.pack_start(label(item['date']+' · '+(item['time'] or tr('全天')),'dim-label'),False,False,0)
            title=label(item['title']);title.set_max_width_chars(26);content.pack_start(title,False,False,0)
            if self.activate:
                button=Gtk.Button();button.add(content);button.connect('clicked',lambda _,item=item:self.activate(item));row=button
            else:row=content
            row.get_style_context().add_class('agenda-event');self.pack_start(row,False,False,0)
        if len(items)>self.limit:
            more=Gtk.Button(label=tr('显示更多（剩余 %s 条）')%(len(items)-self.limit))
            more.connect('clicked',self.more);self.pack_start(more,False,False,0)
        self.show_all()

    def more(self,*_):self.limit+=6;self.refresh()

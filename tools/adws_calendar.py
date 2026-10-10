"""Shared month grid for the dashboard and clock, with distinct date states."""
import calendar
from datetime import date, timedelta
from gi.repository import Gtk, GObject, Gdk
from adws_i18n import tr, chinese


def month_cells(year, month):
    first=date(year,month,1)
    offset=first.weekday()
    # date.min has no preceding days; ordinary month boundaries include neighbours.
    start=first-timedelta(days=min(offset,first.toordinal()-1))
    return [start+timedelta(days=i) if start.toordinal()+i<=date.max.toordinal() else None for i in range(42)]


class MonthCalendar(Gtk.Box):
    __gsignals__={name:(GObject.SignalFlags.RUN_FIRST,None,()) for name in ('day-selected','month-changed')}

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        self.selected=date.today();self.year=self.selected.year;self.month=self.selected.month;self.marks=set()
        self.get_style_context().add_class('adws-month')
        head=Gtk.Box(spacing=4);self.heading=Gtk.Label(xalign=0)
        self.heading.get_style_context().add_class('calendar-heading');head.pack_start(self.heading,True,True,0)
        self.previous=self.nav('go-previous-symbolic','上个月',lambda *_:self.navigate(-1))
        self.next=self.nav('go-next-symbolic','下个月',lambda *_:self.navigate(1))
        head.pack_end(self.next,False,False,0);head.pack_end(self.previous,False,False,0)
        self.pack_start(head,False,False,0)
        self.grid=Gtk.Grid(column_spacing=3,row_spacing=3,column_homogeneous=True)
        for col in range(7):
            title=Gtk.Label(label='一二三四五六日'[col] if chinese() else str(calendar.day_abbr[col]));title.get_style_context().add_class('calendar-weekday')
            self.grid.attach(title,col,0,1,1)
        self.buttons=[]
        for i in range(42):
            button=Gtk.Button();button.set_hexpand(True);button.get_style_context().add_class('calendar-day')
            content=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            number=Gtk.Label();dot=Gtk.Label(label='•');dot.get_style_context().add_class('calendar-dot')
            content.pack_start(number,False,False,0);content.pack_start(dot,False,False,0);button.add(content)
            button.connect('clicked',lambda _,index=i:self.pick(index))
            button.connect('key-press-event',self.key_pressed)
            self.grid.attach(button,i%7,1+i//7,1,1);self.buttons.append((button,number,dot))
        self.pack_start(self.grid,False,False,0)
        foot=Gtk.Box(spacing=5);legend=Gtk.Label(label=tr('圆点表示日程'),xalign=0)
        legend.get_style_context().add_class('dim-label');foot.pack_start(legend,True,True,0)
        today=Gtk.Button(label=tr('今天'));today.connect('clicked',lambda *_:self.choose(date.today()))
        today.get_style_context().add_class('calendar-today-link');foot.pack_end(today,False,False,0)
        self.pack_start(foot,False,False,0);self.render()
        self.connect('map',lambda *_:self.refresh_agenda())
        self.connect('month-changed',lambda *_:self.refresh_agenda())

    def refresh_agenda(self):
        from adws_agenda import load_events
        try:
            events=load_events()
            self.marks={date.fromisoformat(event['date']).day for event in events if event['date'].startswith(f'{self.year:04d}-{self.month:02d}-')}
        except (OSError,ValueError):self.marks=set()
        self.render()

    def nav(self,icon,title,callback):
        button=Gtk.Button.new_from_icon_name(icon,Gtk.IconSize.BUTTON)
        button.get_style_context().add_class('sidebar-icon-button');button.set_tooltip_text(tr(title));button.connect('clicked',callback)
        return button

    def get_date(self):return self.year,self.month-1,self.selected.day if (self.selected.year,self.selected.month)==(self.year,self.month) else 0

    def select_month(self,month,year):
        date(year,month+1,1)
        if (self.year,self.month)==(year,month+1):return
        self.year,self.month=year,month+1;self.marks.clear();self.render();self.emit('month-changed')

    def select_day(self,day):
        self.selected=date(self.year,self.month,day);self.render();self.emit('day-selected')

    def choose(self,day):
        self.select_month(day.month-1,day.year);self.select_day(day.day)

    def navigate(self,delta):
        index=(self.year-1)*12+self.month-1+delta
        if 0<=index<9999*12:self.select_month(index%12,index//12+1)

    def pick(self,index):
        day=self.cells[index]
        if day:self.choose(day)

    def key_pressed(self,button,event):
        delta={Gdk.KEY_Left:-1,Gdk.KEY_Right:1,Gdk.KEY_Up:-7,Gdk.KEY_Down:7}.get(event.keyval)
        if delta is None:return False
        index=next(i for i,item in enumerate(self.buttons) if item[0] is button)
        day=self.cells[index]
        if day and 1<=day.toordinal()+delta<=date.max.toordinal():
            day+=timedelta(days=delta);self.choose(day)
            self.buttons[self.cells.index(day)][0].grab_focus()
        return True

    def clear_marks(self):self.marks.clear();self.update_states()
    def mark_day(self,day):self.marks.add(day);self.update_states()

    def render(self):
        self.cells=month_cells(self.year,self.month)
        self.heading.set_text(f'{self.year}年{self.month}月' if chinese() else date(self.year,self.month,1).strftime('%B %Y'))
        self.previous.set_sensitive((self.year,self.month)>(1,1));self.next.set_sensitive((self.year,self.month)<(9999,12))
        self.update_states()

    def update_states(self):
        for day,(button,number,dot) in zip(self.cells,self.buttons):
            button.set_sensitive(day is not None);number.set_text(str(day.day) if day else '')
            ctx=button.get_style_context()
            current=day is not None and (day.year,day.month)==(self.year,self.month)
            for cls,active in [('other-month',not current),('is-today',day==date.today()),('is-selected',day==self.selected)]:
                (ctx.add_class if active else ctx.remove_class)(cls)
            marked=current and day.day in self.marks
            dot.set_opacity(1 if marked else 0)
            button.set_tooltip_text(day.strftime('%x')+(' · '+tr('有日程') if marked else '') if day else None)

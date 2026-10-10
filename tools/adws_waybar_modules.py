"""Visual, instance-aware module ordering for standalone Waybar bars."""
import json
import gi
gi.require_version("Gtk","3.0")
gi.require_version("Gdk","3.0")
from gi.repository import Gtk, Gdk, Pango
from adws_i18n import tr

SLOTS=('modules-left','modules-center','modules-right')
TITLES=('左侧组件','中间组件','右侧组件')
TARGET='application/x-adws-waybar-module'
NAMES={
 'audio':('音量展开组','audio-volume-high-symbolic'),
 'brightness':('亮度展开组','display-brightness-symbolic'),
 'powermenu':('电源展开组','system-shutdown-symbolic'),
 'clipboard':('剪贴板历史','edit-paste-symbolic'),
 'cava':('音频频谱','audio-x-generic-symbolic'),
 'taskbar-toggle':('任务栏显隐','view-bottom-bar-symbolic'),
 'clock':('时钟','preferences-system-time-symbolic'),
 'tray':('系统托盘','view-grid-symbolic'),
 'pulseaudio':('声音','audio-volume-high-symbolic'),
 'wireplumber':('声音','audio-volume-high-symbolic'),
 'backlight':('亮度','display-brightness-symbolic'),
 'battery':('电池','battery-symbolic'),
 'network':('网络','network-wireless-symbolic'),
 'bluetooth':('蓝牙','bluetooth-symbolic'),
 'cpu':('处理器','computer-symbolic'),
 'memory':('内存','media-flash-symbolic'),
 'mpris':('媒体播放','multimedia-player-symbolic'),
 'idle_inhibitor':('保持唤醒','weather-clear-night-symbolic'),
 'power-profiles-daemon':('电源模式','preferences-system-power-symbolic'),
 'workspaces':('工作区','view-paged-symbolic'),
 'window':('当前窗口','window-symbolic'),
 'applauncher':('开始','view-app-grid-symbolic'),
 'updates':('系统更新','software-update-available-symbolic'),
 'settings':('设置','preferences-system-symbolic'),
 'adws-brightness':('亮度','display-brightness-symbolic'),
 'wlogout':('电源与会话','system-shutdown-symbolic'),
 'actions':('终端','utilities-terminal-symbolic'),
 'wallpapers':('壁纸','preferences-desktop-wallpaper-symbolic'),
}

def presentation(module):
 base=module.split('#',1)[0].rsplit('/',1)[-1]
 if base in ('left_div','right_div'):return tr('分隔箭头'),'go-next-symbolic'
 title,icon=NAMES.get(base,(module,'application-x-addon-symbolic'))
 return tr(title),icon

def move(values,source,index,target,before=None):
 """Move one occurrence, preserving duplicate names and unaffected slots."""
 if source not in SLOTS or target not in SLOTS or not 0<=index<len(values[source]):return False
 destination=len(values[target]) if before is None else max(0,min(before,len(values[target])))
 if source==target and index<destination:destination-=1
 if source==target and index==destination:return False
 module=values[source].pop(index);values[target].insert(destination,module)
 return True

class ModuleEditor(Gtk.Box):
 def __init__(self,changed):
  super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=12)
  self.changed=changed;self.values={key:[] for key in SLOTS};self.catalog=[]
  heading=Gtk.Label(label=tr('组件布局'),xalign=0);heading.get_style_context().add_class('title');self.pack_start(heading,False,False,0)
  hint=Gtk.Label(label=tr('拖动卡片调整顺序或跨区域移动；点击卡片可移动或移除。'),xalign=0);hint.set_line_wrap(True);hint.get_style_context().add_class('dim-label');self.pack_start(hint,False,False,0)
  toolbar=Gtk.Box(spacing=8)
  self.available=Gtk.ComboBoxText();self.available.set_hexpand(True);toolbar.pack_start(self.available,True,True,0)
  self.destination=Gtk.ComboBoxText()
  for key,title in zip(SLOTS,TITLES):self.destination.append(key,tr(title))
  self.destination.set_active(0);toolbar.pack_start(self.destination,False,False,0)
  add=Gtk.Button.new_from_icon_name('list-add-symbolic',Gtk.IconSize.BUTTON);add.set_tooltip_text(tr('添加组件'));add.connect('clicked',self.add);toolbar.pack_start(add,False,False,0)
  self.pack_start(toolbar,False,False,0)
  self.zones={}
  for key,title in zip(SLOTS,TITLES):
   box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8);box.get_style_context().add_class('settings-card')
   label=Gtk.Label(label=tr(title),xalign=0);box.pack_start(label,False,False,0)
   flow=Gtk.FlowBox();flow.set_selection_mode(Gtk.SelectionMode.NONE);flow.set_column_spacing(8);flow.set_row_spacing(8);flow.set_max_children_per_line(20);flow.set_min_children_per_line(1)
   box.pack_start(flow,False,False,0);self.bind_drop(box,key);self.zones[key]=flow;self.pack_start(box,False,False,0)
 def set_data(self,bar,catalog):
  self.values={key:list(bar.get(key,[])) for key in SLOTS}
  self.catalog=sorted(set(catalog)|{name for values in self.values.values() for name in values})
  self.available.remove_all()
  for name in self.catalog:self.available.append(name,presentation(name)[0]+' · '+name)
  if self.catalog:self.available.set_active(0)
  self.render()
 def card(self,module,key,index):
  title,icon=presentation(module)
  divider=module.split('#',1)[0].rsplit('/',1)[-1] in ('left_div','right_div')
  button=Gtk.Button();button.set_tooltip_text(module);button.set_hexpand(False)
  box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=5);box.set_margin_top(8);box.set_margin_bottom(8);box.set_margin_start(10);box.set_margin_end(10)
  if divider:
   button.set_halign(Gtk.Align.CENTER)
   glyph='‹' if 'left_div' in module else '›'
   small=Gtk.Label(label=glyph);small.get_style_context().add_class('dim-label');box.pack_start(small,False,False,0)
   box.set_margin_start(2);box.set_margin_end(2);box.set_margin_top(4);box.set_margin_bottom(4)
  else:box.pack_start(Gtk.Image.new_from_icon_name(icon,Gtk.IconSize.LARGE_TOOLBAR),False,False,0)
  label=Gtk.Label(label=title);label.set_max_width_chars(15);label.set_ellipsize(Pango.EllipsizeMode.END)
  if not divider:box.pack_start(label,False,False,0)
  button.set_valign(Gtk.Align.CENTER);button.add(box)
  button.connect('clicked',lambda *_:self.actions(button,key,index))
  button.drag_source_set(Gdk.ModifierType.BUTTON1_MASK,[Gtk.TargetEntry.new(TARGET,Gtk.TargetFlags.SAME_APP,0)],Gdk.DragAction.MOVE)
  button.connect('drag-data-get',lambda _,ctx,data,info,time:data.set(data.get_target(),8,json.dumps([key,index]).encode()))
  self.bind_drop(button,key,index)
  return button
 def bind_drop(self,widget,key,before=None):
  widget.drag_dest_set(Gtk.DestDefaults.ALL,[Gtk.TargetEntry.new(TARGET,Gtk.TargetFlags.SAME_APP,0)],Gdk.DragAction.MOVE)
  def received(widget,context,x,y,data,info,time):
   try:
    source,index=json.loads(bytes(data.get_data()).decode())
    success=move(self.values,source,index,key,before)
   except (ValueError,TypeError,KeyError):success=False
   Gtk.drag_finish(context,success,False,time)
   if success:GLib.idle_add(self.commit)
  from gi.repository import GLib
  widget.connect('drag-data-received',received)
 def render(self):
  for key,flow in self.zones.items():
   for child in flow.get_children():flow.remove(child)
   for index,module in enumerate(self.values[key]):flow.add(self.card(module,key,index))
   if not self.values[key]:
    label=Gtk.Label(label=tr('拖入或添加组件'));label.set_margin_top(12);label.set_margin_bottom(12);label.get_style_context().add_class('dim-label');flow.add(label)
   flow.show_all()
 def commit(self):
  self.render();self.changed();return False
 def add(self,*_):
  name=self.available.get_active_id();key=self.destination.get_active_id()
  if name and key:self.values[key].append(name);self.commit()
 def actions(self,button,key,index):
  pop=Gtk.Popover.new(button);box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6);box.set_margin_top(8);box.set_margin_bottom(8);box.set_margin_start(8);box.set_margin_end(8)
  def action(title,callback,sensitive=True):
   item=Gtk.Button(label=tr(title));item.set_sensitive(sensitive)
   def click(*_):pop.popdown();callback()
   item.connect('clicked',click);box.pack_start(item,False,False,0)
  def relocate(target,before=None):
   if move(self.values,key,index,target,before):self.commit()
  action('前移',lambda:relocate(key,index-1),index>0)
  action('后移',lambda:relocate(key,index+2),index<len(self.values[key])-1)
  for target,title in zip(SLOTS,TITLES):action(title,lambda target=target:relocate(target),target!=key)
  def remove():self.values[key].pop(index);self.commit()
  action('移除',remove);pop.add(box);pop.show_all();pop.popup()

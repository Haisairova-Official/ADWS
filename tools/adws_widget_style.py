"""Per-instance GTK3 CSS editor; providers are attached to one card only."""
from gi.repository import Gtk, Gdk, GLib
from adws_i18n import tr

EXAMPLE='''.adws-desktop-card {
  background-color: rgba(35, 38, 52, 0.90);
  border-radius: 20px;
}
.desktop-primary { font-size: 26px; color: #ffffff; }
.desktop-secondary { color: #c0c8ef; }
'''


def provider(css):
    if not isinstance(css,str) or len(css)>65536:raise ValueError(tr('CSS 不能超过 64 KiB。'))
    result=Gtk.CssProvider();result.load_from_data(css.encode('utf-8'));return result


def edit(parent,css):
    dialog=Gtk.Dialog(title=tr('组件 CSS'),transient_for=parent,modal=True)
    dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG);dialog.set_resizable(False)
    dialog.set_default_size(540,420);dialog.add_buttons(tr('取消'),Gtk.ResponseType.CANCEL,tr('保存'),Gtk.ResponseType.OK)
    content=dialog.get_content_area();content.set_spacing(12);content.set_border_width(16)
    content.pack_start(Gtk.Label(label=tr('仅影响当前组件实例。使用 GTK 3 CSS；清空内容可恢复主题样式。'),xalign=0,wrap=True),False,False,0)
    buttons=Gtk.Box(spacing=8);content.pack_start(buttons,False,False,0)
    editor=Gtk.TextView();editor.set_monospace(True);editor.set_wrap_mode(Gtk.WrapMode.WORD_CHAR);buffer=editor.get_buffer();buffer.set_text(css)
    for name,value in [('填入示例',EXAMPLE),('恢复主题样式','')]:
        button=Gtk.Button(label=tr(name));button.connect('clicked',lambda _,text=value:buffer.set_text(text));buttons.pack_start(button,False,False,0)
    scroll=Gtk.ScrolledWindow();scroll.add(editor);content.pack_start(scroll,True,True,0)
    error=Gtk.Label(xalign=0,wrap=True);content.pack_start(error,False,False,0);dialog.show_all()
    try:
        while dialog.run()==Gtk.ResponseType.OK:
            value=buffer.get_text(buffer.get_start_iter(),buffer.get_end_iter(),True)
            try:provider(value)
            except (GLib.Error,ValueError) as failure:error.set_text(str(failure));continue
            return value
        return None
    finally:dialog.destroy()

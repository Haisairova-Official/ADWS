"""Run with GDK_BACKEND=x11 under Xvfb; no user settings are changed."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from adws_settings_widgets import *
Gtk.init([])
w=Gtk.Window();box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL);w.add(box)
a=Gtk.ComboBoxText();[a.append(str(i),'Choice '+str(i)) for i in range(10)];a.set_active_id('3');box.pack_start(a,False,False,0)
b=Gtk.ComboBoxText.new_with_entry();b.append_text('Editable');box.pack_start(b,False,False,0)
count=[];a.connect('changed',lambda *_:count.append(a.get_active_id()))
adapters=enhance_choices(box);assert len(adapters)==2;adapter=adapters[0]
w.show_all()
def pump():
 while Gtk.events_pending(): Gtk.main_iteration_do(False)
pump();assert not a.get_visible();assert adapter.get_visible();assert a.get_parent() is box;assert adapter.caption.get_text()=='Choice 3'
a.set_active_id('5');pump();assert adapter.caption.get_text()=='Choice 5';assert count==['5']
adapter.set_active(True);pump();assert adapter.search.get_visible()
adapter.search.set_text('Choice 9');adapter._filter();adapter._activate_first();pump();assert a.get_active_id()=='9';assert count==['5','9']
a.remove_all();a.append('new','A new choice');a.set_active_id('new');pump();assert adapter.caption.get_text()=='A new choice'
a.set_sensitive(False);assert not adapter.get_sensitive();a.set_sensitive(True);assert adapter.get_sensitive()
editable = b._adws_choice_button
entry = editable.editor
assert entry is not None
assert entry.get_buffer() is b.get_child().get_buffer()
entry.set_text("My custom font")
assert b.get_active_text() == "My custom font"
b.get_child().set_text("Noto Sans")
assert entry.get_text() == "Noto Sans"
editable.set_active(True);pump()
editable._activate_row(editable.listbox, editable.listbox.get_row_at_index(0));pump()
assert entry.get_text() == "Editable" and b.get_active_text() == "Editable"
b.set_sensitive(False);assert not editable.presentation.get_sensitive()
b.set_sensitive(True);assert editable.presentation.get_sensitive()
assert enhance_choices(box)==[]
grid=Gtk.Grid();box.pack_start(grid,False,False,0);c=Gtk.ComboBoxText();c.append_text('Grid');c.set_active(0);grid.attach(c,2,3,2,1);cc=enhance_choices(grid)[0]
assert c.get_parent() is grid;assert grid.child_get_property(cc,'left-attach')==2;assert grid.child_get_property(cc,'width')==2
# pack_end reverses the source/adapter disposal order. Synchronously removing
# the adapter from the combo's destroy callback used to corrupt GtkBox's child
# traversal and crash in g_object_run_dispose after a language selection.
end_row = Gtk.Box(spacing=12)
box.pack_start(end_row, False, False, 0)
end_row.pack_start(Gtk.Label(label="Language"), True, True, 0)
end_choice = Gtk.ComboBoxText()
end_choice.append('en', 'English');end_choice.append('zh', '中文')
end_choice.set_active_id('en')
end_row.pack_end(end_choice, False, False, 0)
end_adapter = enhance_choices(end_row)[0]
w.show_all();end_choice.set_active_id('zh');pump()
w.destroy();pump();assert adapter._destroyed and cc._destroyed and end_adapter._destroyed
# Removing just a source combo must still remove its presentation once the
# main loop can do so safely, without retaining model signal handlers.
standalone = Gtk.Box()
source = Gtk.ComboBoxText();source.append_text('Only');source.set_active(0)
standalone.pack_end(source, False, False, 0)
mirror = enhance_choices(standalone)[0]
source.destroy();pump()
assert mirror._destroyed and not mirror._deferred_destroy
assert mirror.get_parent() is None
standalone.destroy()
print('PASS choices: selection callback, popup search, model rebuild, editable entry buffer and presets, sensitivity, ancestry, grid placement, destruction')

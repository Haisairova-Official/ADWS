"""ADWS clipboard picker over cliphist; no terminal or external menu frontend."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys
from adws_i18n import tr

def run(args,**kwargs):return subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8,**kwargs).stdout

def entries():
    # cliphist caps its own history; cap the displayed list too.
    text=run(['cliphist','list']).decode(errors='replace')
    return [line for line in text.splitlines() if '\t' in line][:500]

def copy_entry(line):
    data=run(['cliphist','decode'],input=(line+'\n').encode())
    run(['wl-copy'],input=data)

def watcher_exists():
    for path in Path('/proc').iterdir():
        if not path.name.isdecimal():continue
        try:
            if path.stat().st_uid!=os.getuid():continue
            argv=path.joinpath('cmdline').read_bytes().decode().rstrip('\0').split('\0')
            if argv and Path(argv[0]).name=='wl-paste' and '--watch' in argv and any(Path(a).name=='cliphist' for a in argv[1:]):return True
        except (OSError,UnicodeError):pass
    return False

def ensure_watcher():
    if not all(shutil.which(name) for name in ('cliphist','wl-paste','wl-copy')):raise RuntimeError(tr('剪贴板历史需要 cliphist 和 wl-clipboard。'))
    runtime=Path(os.environ.get('XDG_RUNTIME_DIR') or '/tmp')/('adws-clipboard-'+str(os.getuid())+'.lock')
    with runtime.open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if not watcher_exists():
            subprocess.Popen(['wl-paste','--watch','cliphist','store'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)

def picker():
    import gi
    gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0')
    from gi.repository import Gtk,Gio,GLib,Pango,Gdk
    from adws_launch_dialogs import CompactDialog
    app=Gtk.Application(application_id='org.akiacg.ADWS.Clipboard',flags=Gio.ApplicationFlags.FLAGS_NONE)
    def activate(app):
        if app.get_windows():app.get_windows()[0].present();return
        dialog=CompactDialog(None,'剪贴板历史',tr('剪贴板历史'),tr('选择一项复制，然后在目标窗口粘贴。'),icon='edit-paste-symbolic',accept=None)
        app.add_window(dialog);dialog.set_default_size(520,460);dialog.set_resizable(True)
        try:
            gi.require_version('GtkLayerShell','0.1');from gi.repository import GtkLayerShell as layer
            if layer.is_supported():
                layer.init_for_window(dialog);layer.set_namespace(dialog,'waybar');layer.set_layer(dialog,layer.Layer.OVERLAY);layer.set_keyboard_mode(dialog,layer.KeyboardMode.ON_DEMAND);layer.set_exclusive_zone(dialog,0);layer.set_anchor(dialog,layer.Edge.TOP,True);layer.set_margin(dialog,layer.Edge.TOP,55)
        except (ImportError,ValueError):pass
        search=Gtk.SearchEntry();search.set_placeholder_text(tr('搜索剪贴板'));dialog.body.pack_start(search,False,False,0)
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC);scroll.set_min_content_height(230)
        listing=Gtk.ListBox();listing.set_selection_mode(Gtk.SelectionMode.SINGLE);scroll.add(listing);dialog.body.pack_start(scroll,True,True,0)
        status=Gtk.Label(xalign=0);status.set_line_wrap(True);dialog.body.pack_start(status,False,False,0)
        controls=Gtk.Box(spacing=8);refresh=Gtk.Button(label=tr('刷新'));clear=Gtk.Button(label=tr('清空历史'));controls.pack_start(refresh,False,False,0);controls.pack_start(clear,False,False,0);dialog.body.pack_start(controls,False,False,0)
        pool=ThreadPoolExecutor(max_workers=1);closed=[False];busy=[False]
        def work(job,done):
            if busy[0]:return
            busy[0]=True;listing.set_sensitive(False);refresh.set_sensitive(False);clear.set_sensitive(False)
            def complete(f):
                def deliver():
                    if closed[0]:return False
                    busy[0]=False;listing.set_sensitive(True);refresh.set_sensitive(True);clear.set_sensitive(True)
                    try:done(f.result())
                    except Exception as error:status.set_text(str(error))
                    return False
                GLib.idle_add(deliver)
            pool.submit(job).add_done_callback(complete)
        def show(rows):
            for row in listing.get_children():listing.remove(row)
            for line in rows:
                row=Gtk.ListBoxRow();row.record=line
                label=Gtk.Label(label=line.split('\t',1)[1],xalign=0);label.set_ellipsize(Pango.EllipsizeMode.END);label.set_max_width_chars(60);label.set_margin_top(10);label.set_margin_bottom(10);row.add(label);listing.add(row)
            status.set_text(tr('暂无剪贴板历史') if not rows else '');listing.show_all();listing.invalidate_filter()
        def load(*_):work(entries,show)
        listing.set_filter_func(lambda row:search.get_text().casefold() in row.record.casefold())
        search.connect('search-changed',lambda *_:listing.invalidate_filter())
        listing.connect('row-activated',lambda _,row:work(lambda:copy_entry(row.record),lambda _:dialog.destroy()))
        def wipe(*_):
            confirm=CompactDialog(dialog,'清空历史',tr('清空历史'),tr('确定要清空剪贴板历史吗？'),icon='edit-clear-symbolic',accept='确定');confirm.show_all();accepted=confirm.run()==Gtk.ResponseType.OK;confirm.destroy()
            if accepted:work(lambda:run(['cliphist','wipe']),lambda _:show([]))
        clear.connect('clicked',wipe);refresh.connect('clicked',load)
        def close(*_):closed[0]=True;pool.shutdown(wait=False,cancel_futures=True)
        dialog.connect('destroy',close);dialog.connect('response',lambda *_:dialog.destroy());dialog.show_all();search.grab_focus();load()
    app.connect('activate',activate);return app.run([])

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--watch-start',action='store_true');args=parser.parse_args()
    try:
        ensure_watcher()
        if args.watch_start:print('ready');return 0
        return picker()
    except Exception as error:
        print(str(error),file=sys.stderr)
        if shutil.which('notify-send'):subprocess.run(['notify-send','ADWS',str(error)],check=False,timeout=5)
        return 1
if __name__=='__main__':raise SystemExit(main())

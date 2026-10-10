"""ADWS palette strategy selector; no dotfile scripts or external menu frontend."""
import configparser
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from adws_i18n import tr
import adws_wallpaper_colors as colors

LABELS = ('默认点调','鲜艳模式','水果沙拉','忠实还原','表现增强','中性柔和','单色黑白','彩虹混色','内容优先')


def current_image():
    root=Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')
    try:
        data=json.loads((root/'adws/wallpaper.json').read_text())
        image=data.get('image') or data.get('path')
        if image and Path(image).expanduser().is_file():return str(Path(image).expanduser())
    except (OSError,ValueError,AttributeError):pass
    # Import only the current image path from legacy user data; never run hooks.
    try:
        data=configparser.ConfigParser(interpolation=None);data.read(root/'waypaper/config.ini')
        image=data.get('Settings','wallpaper',fallback='')
        if image and Path(image).expanduser().is_file():return str(Path(image).expanduser())
    except (OSError,configparser.Error):pass
    return ''


def menu_items(selected):
    return [('mode',tr('切换到亮色模式' if selected['mode']=='dark' else '切换到暗色模式')),
            ('index',tr('使用第一主色' if selected.get('index_mode')=='cycle' else '轮换壁纸主色')),
            ('regenerate',tr('重新生成配色'))] + [(key,tr(label)) for key,label in zip(colors.SCHEMES,LABELS)]


def changed_preferences(selected, action):
    result=dict(selected)
    if action=='mode':result['mode']='light' if result['mode']=='dark' else 'dark'
    elif action=='index':result['index_mode']='first' if result.get('index_mode')=='cycle' else 'cycle'
    elif action in colors.SCHEMES:result['scheme']=action
    elif action!='regenerate':raise ValueError(tr('配色方案无效。'))
    return colors.validate_preferences(result)


def picker():
    import gi
    gi.require_version('Gtk','3.0')
    from gi.repository import Gtk,Gio,GLib,Gdk
    from adws_launch_dialogs import CompactDialog, DialogStyle
    class PaletteStyle(DialogStyle):
        def stylesheet(self,roles,options):
            return super().stylesheet(roles,options)+"""
            .adws-palette-menu list { background: transparent; }
            .adws-palette-menu row { margin: 2px 0; padding: 9px 12px; border-radius: 10px; border: 1px solid transparent; transition: background-color 180ms ease-out; }
            .adws-palette-menu row:hover, .adws-palette-menu row:selected { background: alpha(@adws_settings_accent,.14); border-color: alpha(@adws_settings_accent,.22); }
            .adws-palette-menu row.scheme-active { background: alpha(@adws_settings_accent,.10); }
            .adws-palette-menu row.scheme-active image { color: @adws_settings_accent; }
            .adws-palette-menu .palette-group { font-size: .88em; font-weight: bold; opacity: .65; margin: 12px 8px 4px; }
            """
    app=Gtk.Application(application_id='org.akiacg.ADWS.ColorScheme',flags=Gio.ApplicationFlags.FLAGS_NONE)
    pool=ThreadPoolExecutor(max_workers=1)
    def activate(app):
        if app.get_windows():app.get_windows()[0].present();return
        selected=colors.preferences()
        active_name=tr(LABELS[colors.SCHEMES.index(selected['scheme'])])
        description=active_name+' · '+tr('深色' if selected['mode']=='dark' else '浅色')
        dialog=CompactDialog(None,'ADWS 配色',tr('配色方案'),description,icon='applications-graphics-symbolic',accept=None)
        dialog.get_style_context().add_class('adws-palette-menu')
        dialog.visual_style.close();dialog.visual_style=PaletteStyle(dialog)
        app.add_window(dialog);dialog.set_default_size(520,-1)
        dialog.get_action_area().set_no_show_all(True);dialog.get_action_area().hide()
        try:
            gi.require_version('GtkLayerShell','0.1');from gi.repository import GtkLayerShell as layer
            if layer.is_supported():
                layer.init_for_window(dialog);layer.set_namespace(dialog,'waybar');layer.set_layer(dialog,layer.Layer.OVERLAY);layer.set_keyboard_mode(dialog,layer.KeyboardMode.EXCLUSIVE);layer.set_exclusive_zone(dialog,0)
        except (ImportError,ValueError):pass
        search=Gtk.SearchEntry();search.set_placeholder_text(tr('搜索配色方案或操作'));dialog.body.pack_start(search,False,False,0)
        listing=Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE);listing.set_activate_on_single_click(True)
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC);scroll.set_min_content_height(440);scroll.set_max_content_height(580);scroll.set_propagate_natural_height(True);scroll.add(listing);dialog.body.pack_start(scroll,True,True,0)
        quick={'mode','index','regenerate'}
        def section_header(row,previous):
            title=None
            if previous is None:title='快捷操作' if row.action in quick else '配色方案'
            elif row.action not in quick and previous.action in quick:title='配色方案'
            header=Gtk.Label(label=tr(title),xalign=0) if title else None
            if header:header.get_style_context().add_class('palette-group')
            row.set_header(header)
        listing.set_header_func(section_header)
        for action,text in menu_items(selected):
            row=Gtk.ListBoxRow();row.action=action;row.text=text
            box=Gtk.Box(spacing=12)
            active=action==selected['scheme']
            icon={'mode':'display-brightness-symbolic','index':'view-refresh-symbolic','regenerate':'view-refresh-symbolic'}.get(action,'object-select-symbolic' if active else 'applications-graphics-symbolic')
            box.pack_start(Gtk.Image.new_from_icon_name(icon,Gtk.IconSize.MENU),False,False,0)
            box.pack_start(Gtk.Label(label=text,xalign=0),True,True,0)
            if active:row.get_style_context().add_class('scheme-active')
            row.add(box);listing.add(row)
        status=Gtk.Label(xalign=0);status.set_line_wrap(True);dialog.body.pack_start(status,False,False,0)
        listing.set_filter_func(lambda row:search.get_text().casefold() in row.text.casefold())
        search.connect('search-changed',lambda *_:listing.invalidate_filter())
        closed=[False];busy=[False]
        def choose(_,row):
            if not row or busy[0]:return
            image=current_image()
            if not image:
                status.set_text(tr('请先在壁纸设置中选择图片。'));return
            settings=changed_preferences(selected,row.action)
            busy[0]=True;listing.set_sensitive(False);search.set_sensitive(False);status.set_text(tr('正在生成配色…'))
            def done(future):
                def deliver():
                    if closed[0]:return False
                    busy[0]=False;listing.set_sensitive(True);search.set_sensitive(True)
                    try:future.result();dialog.destroy()
                    except Exception as error:status.set_text(str(error))
                    return False
                GLib.idle_add(deliver)
            pool.submit(colors.extract,image,settings).add_done_callback(done)
        listing.connect('row-activated',choose)
        search.connect('activate',lambda *_:choose(listing,listing.get_selected_row() or next((r for r in listing.get_children() if r.get_child_visible()),None)))
        dialog.connect('key-press-event',lambda _,e:(dialog.destroy() or True) if e.keyval==Gdk.KEY_Escape else False)
        dialog.connect('destroy',lambda *_:closed.__setitem__(0,True));dialog.connect('response',lambda *_:dialog.destroy());dialog.show_all();search.grab_focus()
    app.connect('activate',activate)
    try:return app.run([])
    finally:pool.shutdown(wait=False,cancel_futures=True)

def menu():
    return picker()


if __name__=='__main__':
    try:raise SystemExit(menu())
    except Exception as error:
        from adws_color_picker import notify
        notify(str(error));raise SystemExit(1)

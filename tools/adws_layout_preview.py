"""Taskbar-faithful drawing and drag/drop, using bounded read-only live snapshots."""
from datetime import datetime
import math
from pathlib import Path

from adws_i18n import tr as _tr
from adws_clock import preferences, display_pattern


def snapshot(rows, options, current_time=None):
    """Produce preview content from unsaved instance preferences."""
    result = []
    now = current_time or datetime.now()
    for row in rows:
        if not row.get('enabled', True) and row['key'] != 'windows':
            continue
        own = {**options, **row.get('options', {})}
        key = row['key']
        if key == 'start':
            if own.get('start_icon_mode') == 'distro':
                from adws_layout import distro_logo
                text = distro_logo()[1]
            else:
                text = own.get('start_label') or _tr('开始')
        elif key == 'clock':
            try: text = now.strftime(display_pattern(preferences(own)))
            except ValueError: text = _tr('格式无效')
        elif key == 'windows':
            text = ''
        elif key == 'workspaces':
            text = '1  2  3'
        else:
            text = row['name']
        result.append({**row, 'text': text, 'options': own})
    return result


def create_preview(select, move=None):
    import cairo
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('PangoCairo', '1.0')
    from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango, PangoCairo
    from concurrent.futures import ThreadPoolExecutor
    from adws_layout_live import read_snapshot, window_cards

    class LayoutPreview(Gtk.DrawingArea):
        def __init__(self):
            super().__init__()
            self.rows, self.options, self.hits = [], {}, []
            self.source_rows, self.live, self.zones = [], {}, []
            self.pool = ThreadPoolExecutor(max_workers=1)
            self.closed, self.reading = False, False
            self.read_tick = 0
            self.pressed = None
            targets = [Gtk.TargetEntry.new('application/x-adws-layout-instance', Gtk.TargetFlags.SAME_APP, 0)]
            self.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, targets, Gdk.DragAction.MOVE)
            self.drag_dest_set(Gtk.DestDefaults.ALL, targets, Gdk.DragAction.MOVE)
            self.connect('drag-data-get', self.drag_data)
            self.connect('drag-data-received', self.drop_data)
            self.hover = None
            self.images, self.icons = {}, {}
            self.timer = 0
            self.set_size_request(-1, 112)
            self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
            self.connect('draw', self.draw_preview)
            self.connect('button-press-event', self.click)
            self.connect('motion-notify-event', self.motion)
            self.connect('leave-notify-event', self.leave)
            self.connect('map', self.mapped)
            self.connect('unmap', self.unmapped)
            self.connect('destroy', self.close)
            self.connect('style-updated', lambda *_: self.queue_draw())
            self.set_tooltip_text(_tr('拖动组件可改变顺序或移到其他区域；点击可打开组件设置。'))

        def mapped(self, *_):
            self.read_live()
            if not self.timer: self.timer = GLib.timeout_add_seconds(1, self.tick)

        def unmapped(self, *_):
            if self.timer: GLib.source_remove(self.timer)
            self.timer = 0

        def tick(self):
            self.read_tick += 1
            if self.get_mapped() and self.read_tick % 3 == 0: self.read_live()
            if self.get_mapped() and any(row['key'] == 'clock' for row in self.rows):
                self.update(self.source_rows, self.options)
            return True

        def update(self, rows, options):
            self.source_rows, self.options = rows, dict(options)
            self.rows = snapshot(rows, options)
            for row in self.rows:
                if row['key'] == 'windows': row['cards'] = window_cards(self.live, options)
                elif row['key'] == 'tray': row['tray'] = self.live.get('tray', [])
                elif row['key'] in ('sound', 'brightness'):
                    row['icon'] = self.live.get(row['key'], {}).get('icon', 'audio-volume-high-symbolic' if row['key']=='sound' else 'display-brightness-symbolic')
                    row['text'] = ''
                elif row['instance'] in self.live.get('plugins', {}):
                    payload=self.live['plugins'][row['instance']]
                    row['payload']=payload
                    row['text']='\n'.join(str(payload.get(k,'')) for k in ('primary','secondary')).strip() if 'primary' in payload else payload.get('text','')
                elif row['key'] == 'workspaces':
                    row['text'] = '  '.join(str(w.get('idx', '')) for w in self.live.get('workspaces', []))
            vertical = options.get('position') in ('left', 'right')
            self.set_size_request(-1, 250 if vertical else max(112, options.get('thickness', 36) + 56))
            self.queue_draw()

        def read_live(self):
            if self.closed or self.reading: return
            self.reading = True
            future = self.pool.submit(read_snapshot)
            def completed(future):
                if self.closed: return
                try: result = future.result()
                except Exception: result = None
                def commit():
                    self.reading = False
                    if self.closed or not self.get_mapped(): return False
                    if result is not None:
                        self.live = result
                        self.icons.clear()
                        self.update(self.source_rows, self.options)
                    return False
                GLib.idle_add(commit)
            future.add_done_callback(completed)

        def close(self, *_):
            self.closed = True
            self.unmapped()
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.images.clear(); self.icons.clear()

        def drag_data(self, _, context, selection, info, time):
            if self.pressed:
                selection.set(selection.get_target(), 8, self.pressed.encode())

        def drop_location(self, x, y):
            vertical = self.options.get('position') in ('left','right')
            position = y if vertical else x
            for rect, identity in self.hits:
                rx,ry,rw,rh = rect
                if rx <= x <= rx+rw and ry <= y <= ry+rh:
                    row = next(r for r in self.rows if r['instance']==identity)
                    return row['slot'], identity, position > (ry+rh/2 if vertical else rx+rw/2)
            return min(self.zones, key=lambda zone: abs(position-zone[1]))[0] if self.zones else 'center', None, False

        def drop_data(self, _, context, x, y, selection, info, time):
            try: identity = bytes(selection.get_data()).decode('utf-8')
            except (TypeError, UnicodeError): identity = ''
            slot, anchor, after = self.drop_location(x,y)
            success = bool(move and move(identity,slot,anchor,after))
            Gtk.drag_finish(context, success, False, time)

        def color(self, value, fallback):
            color = Gdk.RGBA()
            if value and color.parse(value): return color
            ok, theme = self.get_style_context().lookup_color(fallback)
            return theme if ok else Gdk.RGBA(.25,.25,.3,1)

        def image(self, path):
            if not path: return None
            if path not in self.images:
                if len(self.images) >= 16: self.images.clear()
                try: self.images[path] = GdkPixbuf.Pixbuf.new_from_file(str(Path(path).expanduser()))
                except (GLib.Error, OSError): self.images[path] = None
            return self.images[path]

        def icon(self, name, size=32, theme_path=''):
            key = (name, size, theme_path)
            if key not in self.icons:
                if len(self.icons) >= 256: self.icons.clear()
                try:
                    if Path(name).is_absolute():
                        image = GdkPixbuf.Pixbuf.new_from_file_at_scale(name,size,size,True)
                    else:
                        theme = Gtk.IconTheme.get_default()
                        if theme_path:
                            theme = Gtk.IconTheme.new()
                            theme.set_custom_theme(Gtk.Settings.get_default().get_property('gtk-icon-theme-name'))
                            theme.prepend_search_path(theme_path)
                        info = theme.lookup_by_gicon(Gio.Icon.new_for_string(name),size,Gtk.IconLookupFlags.FORCE_SIZE)
                        image = (info.load_symbolic_for_context(self.get_style_context())[0] if info.is_symbolic() else info.load_icon()) if info else None
                    self.icons[key] = image
                except (GLib.Error, OSError): self.icons[key] = None
            return self.icons[key]

        def tray_icon(self, item):
            for name in item.get('icons', []):
                image = self.icon(name,32,item.get('theme_path',''))
                if image is not None: return image
            if item.get('pixmap'):
                w,h,data = item['pixmap']
                rgba = bytearray(data)
                for i in range(0,len(rgba),4): rgba[i:i+4] = rgba[i+1:i+4]+rgba[i:i+1]
                return GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(rgba)),GdkPixbuf.Colorspace.RGB,True,8,w,h,w*4)
            return self.icon('application-x-executable-symbolic')

        def text_layout(self, text, font_size, family=None):
            layout = self.create_pango_layout(str(text))
            font = Pango.FontDescription(family or self.options.get('font_family') or 'Sans')
            font.set_absolute_size(font_size * Pango.SCALE)
            layout.set_font_description(font)
            layout.set_alignment(Pango.Alignment.CENTER)
            return layout

        def lyric_layouts(self,row,thickness):
            payload=row.get('payload',{})
            family=row.get('settings',{}).get('font_family')
            primary=self.text_layout(payload.get('primary',''),thickness*.34,family)
            secondary=self.text_layout(payload.get('secondary',''),thickness*.34*2/3,family)
            return primary,secondary

        def draw_lyrics(self,cr,row,rect,scale,vertical,fg,bg,accent,thickness):
            primary,secondary=self.lyric_layouts(row,thickness)
            settings=row.get('settings',{})
            def blend(a,b,t):return Gdk.RGBA(a.red*t+b.red*(1-t),a.green*t+b.green*(1-t),a.blue*t+b.blue*(1-t),1.)
            def distance(a,b):return sum((getattr(a,k)-getattr(b,k))**2 for k in ('red','green','blue'))
            translation=accent
            if distance(translation,bg)<distance(fg,bg)*.3:translation=blend(fg,translation,.65)
            if distance(translation,fg)<.04:translation=blend(fg,bg,.72)
            colors=[fg,translation,blend(translation,bg,.40)]
            for i,key in enumerate(('primary_color','secondary_color','separator_color')):
                if settings.get(key):colors[i]=self.color(settings[key],'adws_settings_text')
            x,y,w,h=rect
            cr.save();cr.rectangle(x,y,w,h);cr.clip();cr.translate(x+w/2,y+h/2)
            if vertical:cr.rotate(math.pi/2)
            cr.scale(scale,scale)
            extent=(h if vertical else w)/scale
            bilingual=bool(row['payload'].get('secondary'))
            ph=primary.get_pixel_size()[1];sh=secondary.get_pixel_size()[1]
            total=ph+sh+max(1,thickness/36) if bilingual else ph
            offset=-total/2
            for i,layout in enumerate((primary,secondary) if bilingual else (primary,)):
                if vertical:
                    # Cairo's rotated matrix plus natural gravity keeps CJK
                    # upright and turns Latin with the vertical text flow.
                    context=layout.get_context()
                    context.set_base_gravity(Pango.Gravity.AUTO)
                    context.set_gravity_hint(Pango.GravityHint.NATURAL)
                    PangoCairo.update_layout(cr,layout)
                tw,th=layout.get_pixel_size()
                cr.move_to(-tw/2,offset);Gdk.cairo_set_source_rgba(cr,colors[i]);PangoCairo.show_layout(cr,layout)
                offset+=th
                if i==0 and bilingual:
                    Gdk.cairo_set_source_rgba(cr,colors[2]);cr.set_line_width(max(1,thickness/36))
                    cr.move_to(-extent*.45,offset);cr.line_to(extent*.45,offset);cr.stroke()
                    offset+=max(1,thickness/36)
            cr.restore()

        def rounded(self, cr, x, y, w, h, radius):
            r = min(max(radius, 0),w/2,h/2)
            cr.new_sub_path()
            for cx,cy,start in [(x+w-r,y+r,-math.pi/2),(x+w-r,y+h-r,0),(x+r,y+h-r,math.pi/2),(x+r,y+r,math.pi)]:
                cr.arc(cx,cy,r,start,start+math.pi/2)
            cr.close_path()

        def pixbuf(self, cr, image, rect):
            if image is None: return
            x,y,w,h = rect
            scale = min(w/image.get_width(),h/image.get_height())
            iw,ih = image.get_width()*scale,image.get_height()*scale
            cr.save();cr.translate(x+(w-iw)/2,y+(h-ih)/2);cr.scale(scale,scale)
            Gdk.cairo_set_source_pixbuf(cr,image,0,0);cr.paint();cr.restore()

        def draw_preview(self, _, cr):
            from adws_panel_options import validate
            values = validate(self.options)
            vertical = values['position'] in ('left','right')
            w,h = self.get_allocated_width(),self.get_allocated_height()
            thickness = values['thickness']
            font_size = min(float(self.options.get('font_size',14)),thickness*.38)
            bg = self.color(values['surface_color'] or self.options.get('_surface_background'),'adws_settings_raised')
            fg = self.color('', 'adws_settings_text')
            accent = self.color(values['focus_color'],'adws_settings_accent')
            hover_color = self.color(values['hover_color'],'adws_settings_accent')
            radius = float(self.options.get('preview_radius',12))
            extent = (h if vertical else w)-32
            measured = []
            for row in self.rows:
                layout = self.text_layout(row['text'],font_size)
                tw,th = layout.get_pixel_size()
                if 'primary' in row.get('payload',{}):
                    layouts=self.lyric_layouts(row,thickness)
                    tw=max(part.get_pixel_size()[0] for part in layouts)
                image = self.image(row['options'].get('start_image')) if row['key']=='start' and row['options'].get('start_icon_mode')=='image' else None
                if row['key']=='windows': length=max(thickness,len(row.get('cards',[]))*thickness/values['window_rows'])
                elif row['key']=='tray': length=max(thickness,(min(3,len(row.get('tray',[])))+bool(len(row.get('tray',[]))>3))*thickness*.66)
                elif row.get('icon'): length=thickness*.8
                elif image: length=max(thickness,thickness*image.get_width()/image.get_height()) if not vertical else max(thickness,thickness*image.get_height()/image.get_width())
                elif row.get('width',0): length=row['width']
                else: length=max(thickness,(th if vertical and row['key']=='clock' else tw)+20)
                measured.append((row,layout,image,length))
            # Fit long layouts uniformly while retaining a geometric centre.
            padding={slot:((thickness/2+5 if slot!='left' else 5),(thickness/2+5 if slot!='right' else 5))
                     if values['split_panel'] and values['split_center_corners']=='pointed' else (5,5) for slot in ('left','center','right')}
            lengths={slot:sum(item[3]+6 for item in measured if item[0]['slot']==slot)+sum(padding[slot])
                     if any(item[0]['slot']==slot for item in measured) else 0 for slot in ('left','center','right')}
            if lengths['center']:
                demand=max(lengths['center']+2*lengths['left'],lengths['center']+2*lengths['right'])
            else: demand=lengths['left']+lengths['right']
            scale=min(1.,max(1,extent)/max(1,demand+24))
            cross=16 if values['position'] in ('top','left') else (w if vertical else h)-thickness*scale-16
            cursors={'left':16+padding['left'][0]*scale,'center':16+extent/2-lengths['center']*scale/2+padding['center'][0]*scale,'right':16+extent-lengths['right']*scale+padding['right'][0]*scale}
            self.zones=[('left',16+lengths['left']*scale/2),('center',16+extent/2),('right',16+extent-lengths['right']*scale/2)]
            slots={'left':[],'center':[],'right':[]}
            self.hits=[]
            for row,layout,image,length in measured:
                length*=scale
                pos=cursors[row['slot']]
                rect=(cross,pos,thickness*scale,length) if vertical else (pos,cross,length,thickness*scale)
                cursors[row['slot']]+=length+6*scale
                slots[row['slot']].append((row,layout,image,rect))
                self.hits.append((rect,row['instance']))
            workspaces={w['id'] for w in self.live.get('workspaces',[]) if w.get('is_active')}
            docked=values['panel_mode']=='docked' or (values['panel_mode']=='auto' and any(
                not w.get('is_floating') and not w.get('is_minimized') and (not workspaces or w.get('workspace_id') in workspaces)
                for w in self.live.get('windows',[])))
            def fill(rect,slot=None):
                x,y,rw,rh=rect
                pointed=values['split_panel'] and values['split_center_corners']=='pointed' and slot is not None
                cr.save()
                if pointed:
                    # Exact same gap-facing tips and content buffers as the bar.
                    if vertical: cr.translate(x+rw,y);cr.rotate(math.pi/2);rw,rh=rh,rw
                    else: cr.translate(x,y)
                    front,back=slot!='left',slot!='right'
                    r=0 if docked else min(radius*scale,rh/2)
                    tip=min(rh/2,rw/2)
                    cr.move_to(tip if front else r,0)
                    if back:
                        cr.line_to(rw-tip,0);cr.line_to(rw,rh/2);cr.line_to(rw-tip,rh)
                    else:
                        cr.line_to(rw-r,0);cr.arc(rw-r,r,r,-math.pi/2,0);cr.line_to(rw,rh-r);cr.arc(rw-r,rh-r,r,0,math.pi/2)
                    if front:
                        cr.line_to(tip,rh);cr.line_to(0,rh/2);cr.line_to(tip,0)
                    else:
                        cr.line_to(r,rh);cr.arc(r,rh-r,r,math.pi/2,math.pi);cr.line_to(0,r);cr.arc(r,r,r,math.pi,math.pi*1.5)
                    cr.close_path();cr.clip()
                    x,y=0,0
                else:
                    self.rounded(cr,*rect,0 if docked and slot is None else radius*scale);cr.clip()
                mode=values['panel_material']
                alpha={'solid':1.,'mica':.90,'acrylic':.66,'candy':.82}[mode]
                cr.set_source_rgba(bg.red,bg.green,bg.blue,bg.alpha*alpha);cr.paint()
                if mode in ('mica','candy'):
                    gradient=cairo.LinearGradient(x,y,x+rw if mode=='mica' else x,y+rh)
                    stops=[(0,accent,.13),(1,bg,.04)] if mode=='mica' else [(0,fg,.24),(.48,accent,.18),(.51,bg,.12),(1,accent,.09)]
                    for pos,c,a in stops:gradient.add_color_stop_rgba(pos,c.red,c.green,c.blue,c.alpha*a)
                    cr.set_source(gradient);cr.paint()
                elif mode=='acrylic':
                    cr.set_source_rgba(fg.red,fg.green,fg.blue,.018);cr.set_line_width(scale)
                    for i in range(-int(rh),int(rw+rh),3):cr.move_to(x+i,y);cr.line_to(x+i+rh,y+rh)
                    cr.stroke()
                cr.restore()
            if not values['split_panel']:
                fill((cross,16,thickness*scale,extent) if vertical else (16,cross,extent,thickness*scale))
            for slot,items in slots.items():
                if not items:continue
                if values['split_panel']:
                    first,last=items[0][3],items[-1][3]
                    front,back=padding[slot]
                    rect=(first[0],first[1]-front*scale,first[2],last[1]+last[3]-first[1]+(front+back)*scale) if vertical else (first[0]-front*scale,first[1],last[0]+last[2]-first[0]+(front+back)*scale,first[3])
                    fill(rect, slot)
                for row,layout,image,rect in items:
                    x,y,rw,rh=rect
                    if row['instance']==self.hover:
                        self.rounded(cr,*rect,6*scale);Gdk.cairo_set_source_rgba(cr,hover_color);cr.fill()
                    if image:
                        if row['instance']==self.hover:
                            image=self.image(row['options'].get('start_hover_image')) or image
                        self.pixbuf(cr,image,rect)
                    elif row['key']=='windows':
                        cards=row.get('cards',[])
                        lanes=values['window_rows']
                        count=max(1,math.ceil(len(cards)/lanes))
                        for i,card in enumerate(cards):
                            ir=(x+(i%lanes)*rw/lanes,y+(i//lanes)*rh/count,rw/lanes,rh/count) if vertical else (x+(i//lanes)*rw/count,y+(i%lanes)*rh/lanes,rw/count,rh/lanes)
                            if card['focused']:
                                self.rounded(cr,*ir,6*scale);Gdk.cairo_set_source_rgba(cr,accent);cr.fill()
                            ix,iy,iw,ih=ir
                            self.pixbuf(cr,self.icon(card['icon']) or self.icon('application-x-executable'),(ix+4*scale,iy+4*scale,iw-8*scale,ih-8*scale))
                            if card['count']>1:
                                badge=self.text_layout(card['count'],max(8,font_size*.7))
                                cr.arc(ix+iw-7*scale,iy+ih-7*scale,7*scale,0,math.pi*2);Gdk.cairo_set_source_rgba(cr,accent);cr.fill()
                                bw,bh=badge.get_pixel_size();cr.move_to(ix+iw-7*scale-bw/2,iy+ih-7*scale-bh/2);Gdk.cairo_set_source_rgba(cr,fg);PangoCairo.show_layout(cr,badge)
                    elif row['key']=='tray':
                        tray=row.get('tray',[])
                        images=[self.tray_icon(item) for item in tray[:3]]
                        if len(tray)>3:images.append(self.icon('pan-end-symbolic' if vertical else 'pan-up-symbolic'))
                        for i,img in enumerate(images):
                            ir=(x+5*scale,y+i*rh/max(1,len(images)),rw-10*scale,rh/max(1,len(images))) if vertical else (x+i*rw/max(1,len(images)),y+5*scale,rw/max(1,len(images)),rh-10*scale)
                            self.pixbuf(cr,img,ir)
                    elif 'primary' in row.get('payload',{}):
                        self.draw_lyrics(cr,row,rect,scale,vertical,fg,bg,accent,thickness)
                    elif row.get('icon'):
                        self.pixbuf(cr,self.icon(row['icon']),(x+5*scale,y+5*scale,rw-10*scale,rh-10*scale))
                    else:
                        cr.save();cr.rectangle(x,y,rw,rh);cr.clip();cr.translate(x+rw/2,y+rh/2)
                        if vertical and row['key']!='clock':cr.rotate(math.pi/2)
                        cr.scale(scale,scale)
                        tw,th=layout.get_pixel_size();cr.move_to(-tw/2,-th/2);Gdk.cairo_set_source_rgba(cr,fg)
                        PangoCairo.show_layout(cr,layout);cr.restore()
            return False

        def hit(self,x,y):
            return next((identity for (rx,ry,rw,rh),identity in self.hits if rx<=x<=rx+rw and ry<=y<=ry+rh),None)

        def motion(self, _, event):
            identity=self.hit(event.x,event.y)
            if identity!=self.hover:self.hover=identity;self.queue_draw()
            return True

        def leave(self, *_):
            self.hover=None;self.queue_draw()
            return True

        def click(self, _, event):
            identity=self.hit(event.x,event.y)
            if event.button==1:
                self.pressed=identity
                if identity: select(identity)
            return True

    return LayoutPreview()

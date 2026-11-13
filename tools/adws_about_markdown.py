"""GTK text formatting for the Markdown shipped with ADWS."""
import re

from gi.repository import Gdk, Gtk, Pango


HEADING = re.compile(r'^(#{1,6})\s+(.+)$')
ITEM = re.compile(r'^(\s*)([-+*]|\d+[.)])\s+(.+)$')
FENCE = re.compile(r'^\s*(`{3,}|~{3,})(.*)$')
INLINE = re.compile(
    r'(?P<code>`+(?!`))(?P<literal>.+?)(?P=code)(?!`)|'
    r'!?\[(?P<label>[^\]\n]+)\]\((?P<url>[^()\s]+(?:\([^()\s]*\)[^()\s]*)*)\)|'
    r'(?P<strong>\*\*|(?<!\w)__)(?=\S)(?P<bold>.+?)(?<=\S)(?P=strong)|'
    r'(?P<em>\*(?!\*)|(?<!\w)_(?!_))(?=\S)(?P<italic>.+?)(?<=\S)(?P=em)(?!\w)|'
    r'(?P<autolink>https?://[^\s<>`]+)'
)


def blocks(source):
    """Join wrapped prose and list continuations, preserving literal code lines."""
    lines = iter(source.splitlines())
    pending = None
    while True:
        line = pending if pending is not None else next(lines, None)
        pending = None
        if line is None:
            return
        if not line.strip():
            continue
        fence = FENCE.match(line)
        if fence:
            marker = fence[1]
            code = []
            for row in lines:
                end = row.strip()
                if len(end) >= len(marker) and not end.strip(marker[0]):
                    break
                code.append(row)
            yield 'code-block', '\n'.join(code)
            continue
        heading = HEADING.match(line)
        if heading:
            yield 'h' + str(len(heading[1])), heading[2]
            continue
        if line.startswith('|') and line.endswith('|'):
            cells = [s.strip() for s in line[1:-1].split('|')]
            if not all(re.fullmatch(r':?-{3,}:?', s) for s in cells):
                yield 'row', cells
            continue
        item = ITEM.match(line)
        kind = 'item' if item else 'paragraph'
        if item:
            marker = item[2] if item[2][0].isdigit() else '•'
            first = item[1] + marker + '  ' + item[3]
        else:
            first = line.strip()
        pieces = [first]
        for row in lines:
            if (not row.strip() or HEADING.match(row) or ITEM.match(row)
                    or FENCE.match(row) or row.startswith('|')):
                pending = row
                break
            pieces.append(row.strip())
        yield kind, ' '.join(pieces)


class MarkdownView(Gtk.TextView):
    def __init__(self, source, open_link):
        super().__init__(editable=False, accepts_tab=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                         left_margin=22, right_margin=22, top_margin=14, bottom_margin=20)
        self.open_link = open_link
        self.links = []
        self.pressed_link = None
        buf = self.get_buffer()
        buf.create_tag('md-paragraph', pixels_above_lines=5, pixels_below_lines=4)
        buf.create_tag('md-item', left_margin=37, indent=-16, pixels_above_lines=3,
                       pixels_below_lines=3)
        for depth, scale in enumerate((1.5, 1.26, 1.12, 1.06, 1.0, 1.0), 1):
            buf.create_tag(f'md-h{depth}', weight=Pango.Weight.BOLD, scale=scale,
                           pixels_above_lines=14, pixels_below_lines=6)
        buf.create_tag('md-code-block', family='monospace', left_margin=36,
                       pixels_above_lines=2, pixels_below_lines=2)
        buf.create_tag('md-code', family='monospace')
        buf.create_tag('md-strong', weight=Pango.Weight.BOLD)
        buf.create_tag('md-emphasis', style=Pango.Style.ITALIC)
        link_tag = buf.create_tag('md-link', underline=Pango.Underline.SINGLE)

        def update_link_color(*_):
            color = self.get_style_context().get_color(Gtk.StateFlags.LINK)
            link_tag.set_property('foreground-rgba', color)

        update_link_color()
        self.connect('style-updated', update_link_color)
        self._render(source)
        self.connect('button-press-event', self._press)
        self.connect('button-release-event', self._release)
        self.connect('motion-notify-event', self._motion)
        self.connect('key-press-event', self._key)

    def _render(self, source):
        strings, spans = [], []
        offset = 0

        def write(piece):
            nonlocal offset
            strings.append(piece)
            offset += len(piece)

        def inline(text, inside_link=False):
            end = 0
            for match in INLINE.finditer(text):
                write(text[end:match.start()])
                start = offset
                end = match.end()
                if match['literal'] is not None:
                    write(match['literal'])
                    spans.append(('md-code', start, offset))
                elif match['bold'] or match['italic']:
                    inline(match['bold'] or match['italic'], inside_link)
                    spans.append(('md-strong' if match['bold'] else 'md-emphasis', start, offset))
                else:
                    if match['url']:
                        url, label = match['url'], match['label']
                        inline(label, True)
                    else:
                        raw = match['autolink']
                        url = raw.rstrip('.,;:!?，。；')
                        while url.endswith(')') and url.count(')') > url.count('('):
                            url = url[:-1]
                        label = url
                        write(url)
                        end -= len(raw) - len(url)
                    if not inside_link:
                        self.links.append((start, offset, url, label))
                        spans.append(('md-link', start, offset))
            write(text[end:])

        for kind, value in blocks(source):
            if strings:
                write('\n')
            start = offset
            if kind == 'code-block':
                write(value)
            elif kind == 'row':
                for i, cell in enumerate(value):
                    if i:
                        write('    ')
                    cell_start = offset
                    inline(cell)
                    if i == 0:
                        spans.append(('md-strong', cell_start, offset))
                kind = 'paragraph'
            else:
                inline(value)
            spans.append(('md-' + kind, start, offset))
        buf = self.get_buffer()
        buf.set_text(''.join(strings))
        for tag, start, end in spans:
            buf.apply_tag_by_name(tag, buf.get_iter_at_offset(start), buf.get_iter_at_offset(end))
        buf.place_cursor(buf.get_start_iter())

    def _link_at(self, offset):
        return next((link for link in self.links if link[0] <= offset < link[1]), None)

    def _pointer_link(self, event):
        kind = self.get_window_type(event.window)
        x, y = self.window_to_buffer_coords(kind, int(event.x), int(event.y))
        inside, location = self.get_iter_at_location(x, y)
        return self._link_at(location.get_offset()) if inside else None

    def _press(self, _, event):
        self.pressed_link = self._pointer_link(event) if event.button == 1 else None
        return False

    def _release(self, _, event):
        pressed, self.pressed_link = self.pressed_link, None
        if (event.button == 1 and pressed and self._pointer_link(event) == pressed
                and not self.get_buffer().get_has_selection()):
            self.open_link(pressed[2], pressed[3])
            return True
        return False

    def _motion(self, _, event):
        cursor = 'pointer' if self._pointer_link(event) else 'text'
        event.window.set_cursor(Gdk.Cursor.new_from_name(self.get_display(), cursor))
        return False

    def activate_current_link(self):
        buf = self.get_buffer()
        link = self._link_at(buf.get_iter_at_mark(buf.get_insert()).get_offset())
        if link:
            self.open_link(link[2], link[3])
        return bool(link)

    def _key(self, _, event):
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return self.activate_current_link()
        if event.keyval not in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            return False
        buf = self.get_buffer()
        offset = buf.get_iter_at_mark(buf.get_insert()).get_offset()
        backwards = event.state & Gdk.ModifierType.SHIFT_MASK
        links = reversed(self.links) if backwards else self.links
        target = next((link for link in links if (link[0] < offset if backwards else link[0] > offset)), None)
        if not target:
            return False
        buf.place_cursor(buf.get_iter_at_offset(target[0]))
        self.scroll_mark_onscreen(buf.get_insert())
        return True

"""Shared animated popup lifecycle for ADWS layer-shell panels."""
import time
import logging
from collections import deque
import cairo
from gi.repository import Gtk, GLib


def prepare_surface(window):
    # An RGBA visual is necessary for translucent GTK windows on X11 too.
    visual = window.get_screen().get_rgba_visual()
    if visual is not None: window.set_visual(visual)
    window.set_app_paintable(True)
    window.motion_opacity = 1.0
    window.motion_shift = 0.0
    from adws_popup_effect import PopupEffect
    window.popup_effect = PopupEffect(window)
    window.popup_sources = set()
    window.deferred_sources = set()
    window.deferred_updates = deque()
    window._motion_snapshot = None
    window.motion_deadline = 0
    window.connect("destroy", window.cancel_popup_callbacks)
    window.connect("destroy", window.cancel_deferred_callbacks)
    window.connect("draw", window.draw_surface)


def ease_out(progress):
    """Cubic Bezier (0.2, 0, 0, 1), solved for elapsed time rather than t."""
    x = max(0.0, min(1.0, progress))
    lo, hi = 0.0, 1.0
    for _ in range(18):
        t = (lo + hi) / 2
        curve_x = 0.6 * (1-t)**2 * t + t**3
        if curve_x < x: lo = t
        else: hi = t
    t = (lo + hi) / 2
    return 3 * (1-t) * t*t + t**3


def cache_stack_transitions(stack):
    """Keep the incoming page static while GTK blends it with its old snapshot.

    GTK caches the outgoing page, but otherwise redraws the incoming widget tree
    on every crossfade frame. One device-resolution surface avoids repeatedly
    painting calendars, translucent cards and weather text at monitor refresh rate.
    """
    state = {'snapshot': None, 'painting': False}

    def clear(*_):
        state['snapshot'] = None

    def draw(page, cr):
        if state['painting'] or not stack.get_transition_running():
            return False
        if page != stack.get_visible_child():
            return False
        width, height, scale = page.get_allocated_width(), page.get_allocated_height(), page.get_scale_factor()
        key = (page, width, height, scale)
        if state['snapshot'] is None or state['snapshot'][0] != key:
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, width*scale), max(1, height*scale))
            surface.set_device_scale(scale, scale)
            state['painting'] = True
            try:
                page.draw(cairo.Context(surface))
            finally:
                state['painting'] = False
            state['snapshot'] = (key, surface)
        cr.set_source_surface(state['snapshot'][1], 0, 0)
        cr.paint()
        return True

    for page in stack.get_children():
        page.connect('draw', draw)
    stack.connect('notify::visible-child', clear)
    stack.connect('notify::transition-running', clear)
    stack.connect('unmap', clear)
    stack.connect('destroy', clear)


class PopupBehavior:
    def popup_idle(self, callback):
        def run():
            self.popup_sources.discard(source)
            if not self.closed and not self.closing:
                callback()
            return False
        source = GLib.idle_add(run)
        self.popup_sources.add(source)

    def stop_motion(self):
        if getattr(self,"motion_source",0):
            self.remove_tick_callback(self.motion_source);self.motion_source=0
        if self.motion_deadline:
            GLib.source_remove(self.motion_deadline);self.motion_deadline=0
        self._motion_snapshot=None

    def motion_active(self):
        return bool(self.motion_source or getattr(self, '_reveal_pending', False) or any(
            stack.get_transition_running() for stack in
            (getattr(self, 'stack', None), getattr(self, 'daily_stack', None)) if stack is not None))

    def after_motion(self, callback):
        """Deliver layout-changing refreshes only after the visible transition."""
        self.deferred_updates.append(callback)
        if self.deferred_sources: return
        def run():
            if not self.closed and self.get_mapped() and self.motion_active():
                return True
            if not self.closed and self.deferred_updates:
                try:
                    self.deferred_updates.popleft()()
                except Exception:
                    logging.getLogger(__name__).exception('Deferred popup update failed')
            if not self.closed and self.deferred_updates:
                return True
            self.deferred_sources.discard(source)
            return False
        source = GLib.timeout_add(32, run)
        self.deferred_sources.add(source)

    def cancel_deferred_callbacks(self, *_):
        for source in self.deferred_sources:
            GLib.source_remove(source)
        self.deferred_sources.clear()
        self.deferred_updates.clear()

    def cancel_popup_callbacks(self, *_):
        self.stop_motion()
        self._reveal_pending = False
        for source in self.popup_sources:
            GLib.source_remove(source)
        self.popup_sources.clear()

    def draw_surface(self, _, cr):
        # Clear the previous frame, including rounded corners. Never animate the
        # native surface opacity or layer margins: those renegotiate Wayland
        # geometry and can leave the compositor displaying an old buffer.
        cr.save(); cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0); cr.paint(); cr.restore()
        cr.save()
        scale=max(1,self.get_scale_factor())
        offset = round(self.motion_shift*scale)/scale
        edge = getattr(self, 'slide_edge', None) or getattr(self, 'placement_identity', (None, 'right'))[1]
        dx = -offset if edge == 'left' else offset if edge == 'right' else 0
        dy = -offset if edge == 'top' else offset if edge == 'bottom' else 0
        cr.translate(dx, dy)
        radius = getattr(self, 'popup_corner_radius', 14)
        # Opening only moves by 18 px. Keep its background effect stable so the
        # compositor can reuse blur instead of invalidating its rounded region
        # on every frame. Closing must move the region to prevent residual blur.
        self.popup_effect.update(dx if self.closing else 0, dy if self.closing else 0,
                                 self.get_allocated_width(), self.get_allocated_height(), radius)
        fading = self.motion_opacity < 1.0
        def paint(context):
            Gtk.render_background(self.get_style_context(),context,0,0,self.get_allocated_width(),self.get_allocated_height())
            Gtk.render_frame(self.get_style_context(),context,0,0,self.get_allocated_width(),self.get_allocated_height())
            child=self.get_child()
            if child is not None:self.propagate_draw(child,context)
        if fading:
            width,height,scale=self.get_allocated_width(),self.get_allocated_height(),self.get_scale_factor()
            key=(width,height,scale)
            if self._motion_snapshot is None or self._motion_snapshot[0]!=key:
                surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,max(1,width*scale),max(1,height*scale))
                surface.set_device_scale(scale,scale);paint(cairo.Context(surface))
                self._motion_snapshot=(key,surface)
            cr.set_source_surface(self._motion_snapshot[1],0,0)
            # The cached surface already matches device resolution. Pixel-aligned
            # movement needs no per-pixel bilinear filtering at fractional scale.
            cr.get_source().set_filter(cairo.FILTER_NEAREST)
            cr.paint_with_alpha(self.motion_opacity)
        else:
            self._motion_snapshot=None;paint(cr)
        cr.restore()
        if getattr(self, '_reveal_pending', False):
            self._reveal_pending = False
            # Begin timing only once GTK has produced a real first frame.
            self.popup_idle(self._begin_reveal)
        return True

    def _begin_reveal(self):
        if not self.closed and not self.closing:
            self.animate(True)
        return False

    def load_popup_page(self):
        if not getattr(self, '_popup_page_started', False):
            self._popup_page_started = True
            self.page_changed()

    def reveal(self):
        self.closing = False
        self.had_focus = False
        enabled, _ = self.motion_settings
        self.motion_opacity = .04 if enabled else 1.0
        self.motion_shift = 18.0 if enabled else 0.0
        self._reveal_pending = True
        self.show_all(); self.present(); self.queue_draw()

    def dismiss(self):
        if self.closed or self.closing: return
        self.closing = True; self._reveal_pending = False
        self.cancel_popup_callbacks()
        self.animate(False)

    def animate(self, opening):
        snapshot = self._motion_snapshot
        self.stop_motion()
        # The first map already rendered this frame. Reuse it for the reveal or
        # a direction reversal instead of repainting the whole widget tree.
        self._motion_snapshot = snapshot
        enabled, duration = self.motion_settings
        initial = self.motion_opacity; target = 1.0 if opening else 0.0
        initial_shift = self.motion_shift
        edge = getattr(self, 'slide_edge', None) or getattr(self, 'placement_identity', (None, 'right'))[1]
        distance = self.get_allocated_width() if edge in ('left', 'right') else self.get_allocated_height()
        target_shift = 0.0 if opening else float(distance if self.popup_effect.handle else 18)
        started = time.monotonic()
        def frame(*args):
            if self.closed: self.motion_source = 0; return False
            now = args[1].get_frame_time()/1_000_000 if len(args)>1 else time.monotonic()
            progress = max(0.0, min(1.0, (now-started)*1000/max(1, duration))) if enabled else 1.0
            eased = ease_out(progress)
            self.motion_opacity = initial + (target-initial)*eased
            self.motion_shift = initial_shift + (target_shift-initial_shift)*eased
            self.queue_draw()
            if progress >= 1:
                if self.motion_deadline:
                    GLib.source_remove(self.motion_deadline);self.motion_deadline=0
                self.motion_opacity = target; self.motion_shift = target_shift; self.motion_source = 0
                if not opening:
                    # Unmap immediately; leave no transparent input surface or
                    # partially-painted closing snapshot in the compositor.
                    self.hide()
                    self._motion_snapshot = None
                    if not getattr(self, 'retain_on_close', False): self.destroy()
                else:
                    if not getattr(self, '_popup_page_started', False):
                        self.popup_idle(self.load_popup_page)
                    reposition = getattr(self, 'popup_reposition', None)
                    if reposition:
                        self.popup_reposition = None
                        self.popup_idle(reposition)
                return False
            return True
        if frame():
            self.motion_source = self.add_tick_callback(frame)
            def deadline():
                self.motion_deadline = 0
                # Occluded Wayland surfaces may stop receiving frame callbacks.
                # Finish the lifecycle independently so a closing panel cannot
                # remain mapped and intercept input indefinitely.
                if self.motion_source:
                    self.remove_tick_callback(self.motion_source);self.motion_source=0
                    frame()
                return False
            self.motion_deadline = GLib.timeout_add(max(1,duration)+80, deadline)

    def focus_in(self, *_):
        self.had_focus = True
        if self.focus_source:
            GLib.source_remove(self.focus_source); self.focus_source = 0
        return False

    def focus_out(self, *_):
        if self.closed: return False
        if self.focus_source: GLib.source_remove(self.focus_source)
        def check():
            self.focus_source = 0
            grab = Gtk.grab_get_current()
            # Dropdowns and other local GTK popups must not dismiss their parent.
            if self.owns_grab(grab) or self.interaction_depth:
                if not self.closed: self.focus_source=GLib.timeout_add(180,check)
                return False
            if self.had_focus and not self.closed and not self.is_active(): self.dismiss()
            return False
        self.focus_source = GLib.timeout_add(180, check)
        return False

    def owns_grab(self, grab):
        """Only our own popovers/transient windows may postpone focus dismissal."""
        seen = set()
        while grab is not None and grab not in seen:
            if grab == self: return True
            seen.add(grab)
            if isinstance(grab, Gtk.Popover): grab = grab.get_relative_to()
            elif isinstance(grab, Gtk.Menu): grab = grab.get_attach_widget()
            elif isinstance(grab, Gtk.Window): grab = grab.get_transient_for()
            else: grab = grab.get_parent()
        return False

//! A single active preview, with cancellable hover delays and live group contents.
use crate::state::State;
use std::{
    cell::{Cell, RefCell},
    collections::HashMap,
    rc::{Rc, Weak},
    time::Duration,
};
use waybar_cffi::gtk::{self as gtk, glib, prelude::*};

type Members = Rc<RefCell<Vec<(u64, String)>>>;
thread_local! { static ACTIVE: RefCell<Weak<HoverPreview>> = RefCell::new(Weak::new()); }

pub(crate) struct HoverPreview {
    popup: gtk::Popover,
    button: glib::WeakRef<gtk::Button>,
    state: State,
    members: Members,
    generation: Cell<u64>,
    over_button: Cell<bool>,
    over_popup: Cell<bool>,
    capture: RefCell<Option<crate::preview::Capture>>,
    titles: RefCell<HashMap<u64, gtk::Label>>,
    cards: RefCell<HashMap<u64, gtk::Button>>,
    items: RefCell<Option<gtk::Box>>,
    animation: RefCell<Option<gtk::TickCallbackId>>,
    progress: Cell<f64>,
}

impl HoverPreview {
    pub fn new(
        button: &gtk::Button,
        popup: &gtk::Popover,
        state: State,
        members: Members,
    ) -> Rc<Self> {
        let this = Rc::new(Self {
            popup: popup.clone(),
            button: button.downgrade(),
            state,
            members,
            generation: Cell::new(0),
            over_button: Cell::new(false),
            over_popup: Cell::new(false),
            capture: RefCell::new(None),
            titles: RefCell::new(HashMap::new()),
            cards: RefCell::new(HashMap::new()),
            items: RefCell::new(None),
            animation: RefCell::new(None),
            progress: Cell::new(1.),
        });
        for (widget, is_button) in [
            (button.clone().upcast::<gtk::Widget>(), true),
            (popup.clone().upcast(), false),
        ] {
            widget.add_events(
                gtk::gdk::EventMask::ENTER_NOTIFY_MASK | gtk::gdk::EventMask::LEAVE_NOTIFY_MASK,
            );
            let weak = Rc::downgrade(&this);
            widget.connect_enter_notify_event(move |_, event| {
                if event.state().contains(gtk::gdk::ModifierType::BUTTON1_MASK)
                    || event.detail() == gtk::gdk::NotifyType::Inferior
                    || event.mode() != gtk::gdk::CrossingMode::Normal
                {
                    return glib::Propagation::Proceed;
                }
                if let Some(this) = weak.upgrade() {
                    if is_button {
                        this.over_button.set(true);
                    } else {
                        this.over_popup.set(true);
                    }
                    let ticket = this.advance();
                    if this.popup.is_visible() {
                        this.animate(1.);
                    }
                    if is_button && !this.popup.is_visible() {
                        let switching = ACTIVE.with(|active| {
                            active
                                .borrow()
                                .upgrade()
                                .is_some_and(|p| p.popup.is_visible())
                        });
                        let weak = Rc::downgrade(&this);
                        glib::timeout_add_local_once(
                            Duration::from_millis(if switching { 50 } else { 120 }),
                            move || {
                                if let Some(this) = weak.upgrade() {
                                    if this.generation.get() == ticket
                                        && this.over_button.get()
                                        && this.button.upgrade().is_some_and(|b| b.is_mapped())
                                    {
                                        this.show();
                                    }
                                }
                            },
                        );
                    }
                }
                glib::Propagation::Proceed
            });
            let weak = Rc::downgrade(&this);
            widget.connect_leave_notify_event(move |_, event| {
                if event.detail() == gtk::gdk::NotifyType::Inferior
                    || event.mode() != gtk::gdk::CrossingMode::Normal
                {
                    return glib::Propagation::Proceed;
                }
                if let Some(this) = weak.upgrade() {
                    if is_button {
                        this.over_button.set(false);
                    } else {
                        this.over_popup.set(false);
                    }
                    let ticket = this.advance();
                    let weak = Rc::downgrade(&this);
                    glib::timeout_add_local_once(Duration::from_millis(200), move || {
                        if let Some(this) = weak.upgrade() {
                            if this.generation.get() == ticket
                                && !this.over_button.get()
                                && !this.over_popup.get()
                            {
                                this.animate(0.);
                            }
                        }
                    });
                }
                glib::Propagation::Proceed
            });
        }
        let weak = Rc::downgrade(&this);
        popup.connect_hide(move |_| {
            if let Some(this) = weak.upgrade() {
                this.advance();
                this.over_button.set(false);
                this.over_popup.set(false);
                this.stop_capture();
                this.cancel_animation();
            }
        });
        let weak = Rc::downgrade(&this);
        button.connect_unmap(move |_| {
            if let Some(this) = weak.upgrade() {
                this.dismiss();
            }
        });
        let weak = Rc::downgrade(&this);
        popup.connect_key_press_event(move |_, event| {
            if event.keyval() == gtk::gdk::keys::constants::Escape {
                if let Some(this) = weak.upgrade() {
                    this.dismiss();
                }
                glib::Propagation::Stop
            } else {
                glib::Propagation::Proceed
            }
        });
        this
    }

    fn animations_enabled(&self) -> bool {
        self.state.config().window_animations()
            && self
                .popup
                .settings()
                .is_some_and(|s| s.is_gtk_enable_animations())
    }
    fn cancel_animation(&self) {
        if let Some(tick) = self.animation.borrow_mut().take() {
            tick.remove();
        }
    }
    fn set_progress(&self, value: f64) {
        self.progress.set(value);
        self.popup.set_opacity(value);
        // Opposing margins always sum to 16. The popup's size and input region
        // remain stationary throughout the float, so it cannot retrigger hover.
        if let Some(items) = self.items.borrow().as_ref() {
            let offset = ((1. - value) * 6.).round() as i32;
            let (x, y) = match self.state.config().position() {
                "top" => (0, -offset),
                "left" => (-offset, 0),
                "right" => (offset, 0),
                _ => (0, offset),
            };
            items.set_margin_start(8 + x);
            items.set_margin_end(8 - x);
            items.set_margin_top(8 + y);
            items.set_margin_bottom(8 - y);
        }
    }
    fn animate(self: &Rc<Self>, target: f64) {
        self.cancel_animation();
        if !self.animations_enabled() {
            if target == 0. {
                self.dismiss();
            } else {
                self.set_progress(1.);
            }
            return;
        }
        let from = self.progress.get();
        if (from - target).abs() < 0.001 {
            if target == 0. {
                self.dismiss();
            }
            return;
        }
        let start = Cell::new(None::<i64>);
        let duration =
            self.state.config().animation_duration() as f64 * 1000. * (from - target).abs();
        let weak = Rc::downgrade(self);
        let tick = self.popup.add_tick_callback(move |_, clock| {
            let Some(this) = weak.upgrade() else {
                return glib::ControlFlow::Break;
            };
            let now = clock.frame_time();
            let began = start.get().unwrap_or_else(|| {
                start.set(Some(now));
                now
            });
            let t = ((now - began) as f64 / duration).clamp(0., 1.);
            let eased = t * t * (3. - 2. * t);
            this.set_progress(from + (target - from) * eased);
            if t >= 1. {
                this.animation.borrow_mut().take();
                if target == 0. {
                    this.dismiss();
                }
                glib::ControlFlow::Break
            } else {
                glib::ControlFlow::Continue
            }
        });
        *self.animation.borrow_mut() = Some(tick);
    }

    fn advance(&self) -> u64 {
        let next = self.generation.get().wrapping_add(1);
        self.generation.set(next);
        next
    }
    fn stop_capture(&self) {
        self.capture.borrow_mut().take();
    }
    pub fn dismiss_active() {
        let current = ACTIVE.with(|active| active.borrow().upgrade());
        if let Some(current) = current { current.dismiss(); }
    }
    pub fn dismiss(&self) {
        // hide() alone does not emit a signal if the popup has not appeared yet.
        self.advance();
        self.over_button.set(false);
        self.over_popup.set(false);
        self.stop_capture();
        self.cancel_animation();
        self.popup.hide();
    }
    fn show(self: &Rc<Self>) {
        let previous = ACTIVE.with(|active| active.replace(Rc::downgrade(self)).upgrade());
        if let Some(previous) = previous {
            if !Rc::ptr_eq(&previous, self) {
                previous.dismiss();
            }
        }
        self.render();
        if self.animations_enabled() {
            self.set_progress(0.);
            self.animate(1.);
        }
    }
    pub fn refresh(self: &Rc<Self>) {
        if !self.popup.is_visible() {
            return;
        }
        let members = self.members.borrow();
        let titles = self.titles.borrow();
        if titles.len() == members.len() && members.iter().all(|(id, _)| titles.contains_key(id)) {
            // Retain live captures; only reorder if desktop tile positions changed.
            for (index, (id, title)) in members.iter().enumerate() {
                titles[id].set_text(title);
                if let Some(items) = self.items.borrow().as_ref() {
                    items.reorder_child(&self.cards.borrow()[id], index as i32);
                }
            }
        } else {
            drop(titles);
            drop(members);
            self.render();
        }
    }
    fn render(self: &Rc<Self>) {
        self.stop_capture();
        if let Some(child) = self.popup.child() {
            self.popup.remove(&child);
            unsafe {
                child.destroy();
            }
        }
        self.titles.borrow_mut().clear();
        self.cards.borrow_mut().clear();
        if self.members.borrow().is_empty() {
            if let Some(title) = self.button.upgrade().and_then(|b|b.tooltip_text()) {
                let items=gtk::Box::new(gtk::Orientation::Vertical,0);
                let label=gtk::Label::new(Some(&title));
                label.set_max_width_chars(48);
                label.set_ellipsize(gtk::pango::EllipsizeMode::End);
                items.add(&label);
                *self.items.borrow_mut()=Some(items.clone());
                self.set_progress(self.progress.get());
                self.popup.add(&items);
                if !self.animations_enabled() { self.set_progress(1.); }
                items.show_all();
                self.popup.show();
            } else {self.dismiss();}
            return;
        }
        let peek = self.state.config().window_peek();
        let vertical = self.state.config().vertical();
        let items = gtk::Box::new(
            if peek && !vertical {
                gtk::Orientation::Horizontal
            } else {
                gtk::Orientation::Vertical
            },
            6,
        );
        *self.items.borrow_mut() = Some(items.clone());
        self.set_progress(self.progress.get());
        let mut images = Vec::new();
        for (id, title) in self.members.borrow().iter() {
            let text = gtk::Label::new(Some(title));
            text.set_max_width_chars(if peek { 24 } else { 48 });
            if peek {
                text.set_width_chars(24);
            }
            text.set_ellipsize(gtk::pango::EllipsizeMode::End);
            self.titles.borrow_mut().insert(*id, text.clone());
            let content = gtk::Box::new(gtk::Orientation::Vertical, 6);
            if peek {
                let image = gtk::Image::from_icon_name(
                    Some("application-x-executable"),
                    gtk::IconSize::Dialog,
                );
                image.set_size_request(240, 150);
                content.pack_start(&image, false, false, 0);
                let status =
                    gtk::Label::new(Some(crate::i18n::text("正在加载预览…", "Loading preview…")));
                content.pack_start(&status, false, false, 0);
                images.push((*id, image, status));
            }
            content.pack_start(&text, false, false, 0);
            let select = gtk::Button::new();
            self.cards.borrow_mut().insert(*id, select.clone());
            select.add(&content);
            let weak = Rc::downgrade(self);
            let id = *id;
            select.connect_clicked(move |_| {
                if let Some(this) = weak.upgrade() {
                    this.dismiss();
                    if let Err(error) = this.state.niri().activate_window(id) {
                        tracing::warn!(%error, id, "preview activation failed");
                    }
                }
            });
            items.pack_start(&select, false, false, 0);
        }
        let scroll = gtk::ScrolledWindow::new(None::<&gtk::Adjustment>, None::<&gtk::Adjustment>);
        let horizontal = peek && !vertical;
        scroll.set_policy(
            if horizontal {
                gtk::PolicyType::Automatic
            } else {
                gtk::PolicyType::Never
            },
            if horizontal {
                gtk::PolicyType::Never
            } else {
                gtk::PolicyType::Automatic
            },
        );
        scroll.set_propagate_natural_width(true);
        scroll.set_propagate_natural_height(true);
        let monitor = self
            .button
            .upgrade()
            .and_then(|b| b.window().and_then(|w| w.display().monitor_at_window(&w)));
        let area = monitor.map(|m| m.workarea());
        scroll.set_max_content_width(
            area.as_ref()
                .map_or(760, |r| (r.width() - 32).clamp(100, 760)),
        );
        scroll.set_max_content_height(
            area.as_ref()
                .map_or(600, |r| (r.height() - 32).clamp(100, 600)),
        );
        if !self.animations_enabled() {
            self.set_progress(1.);
        }
        scroll.add(&items);
        self.popup.add(&scroll);
        scroll.show_all();
        self.popup.show();
        if peek {
            *self.capture.borrow_mut() =
                crate::preview::start(self.state.config().preview_helper(), images, &self.popup);
        }
    }
}

impl Drop for HoverPreview {
    fn drop(&mut self) {
        self.stop_capture();
        self.cancel_animation();
        unsafe {
            self.popup.destroy();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn pump(ms: u64) {
        let until = std::time::Instant::now() + Duration::from_millis(ms);
        while std::time::Instant::now() < until {
            while glib::MainContext::default().pending() {
                glib::MainContext::default().iteration(false);
            }
            std::thread::sleep(Duration::from_millis(3));
        }
    }
    #[test]
    #[ignore = "requires an isolated GTK display"]
    fn floating_fade_preserves_popup_geometry_and_can_reverse() {
        gtk::init().unwrap();
        let settings = gtk::Settings::default().unwrap();
        settings.set_gtk_enable_animations(true);
        for position in ["bottom", "top", "left", "right"] {
            let config=serde_json::from_value(serde_json::json!({"window_animations":true,"animation_duration":160,"position":position,"window_peek":true,"vertical":position=="left"||position=="right"})).unwrap();
            let window = gtk::Window::new(gtk::WindowType::Toplevel);
            let button = gtk::Button::with_label("preview");
            window.add(&button);
            window.set_default_size(300, 100);
            window.show_all();
            pump(30);
            let popup = gtk::Popover::new(Some(&button));
            popup.set_modal(false);
            let hover = HoverPreview::new(
                &button,
                &popup,
                State::new(config),
                Rc::new(RefCell::new(vec![(1, "Window".into())])),
            );
            hover.show();
            pump(35);
            assert!(popup.is_visible());
            assert!(popup.opacity() > 0. && popup.opacity() < 1.);
            let geometry = popup.allocation();
            pump(60);
            assert_eq!(
                popup.allocation(),
                geometry,
                "floating animation changed popup geometry"
            );
            pump(100);
            assert!((popup.opacity() - 1.).abs() < 0.01);
            hover.animate(0.);
            pump(60);
            assert!(popup.is_visible());
            assert!(popup.opacity() < 1.);
            hover.animate(1.);
            pump(200);
            assert!(popup.is_visible());
            assert!((popup.opacity() - 1.).abs() < 0.01);
            hover.animate(0.);
            pump(200);
            assert!(!popup.is_visible());
            assert!(hover.animation.borrow().is_none());
            settings.set_gtk_enable_animations(false);
            hover.show();
            assert!((popup.opacity() - 1.).abs() < 0.01);
            hover.animate(0.);
            assert!(!popup.is_visible());
            settings.set_gtk_enable_animations(true);
            drop(hover);
            unsafe {
                window.destroy();
            }
        }
    }
}

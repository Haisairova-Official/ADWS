use waybar_cffi::gtk::{self as gtk, prelude::*};

/// Request the icons' natural width while allowing GTK to shrink the viewport
/// before taking space from the other modules. Never set a content-sized minimum.
#[allow(dead_code)] // Used by standalone examples.
pub fn create(content: &impl IsA<gtk::Widget>, max_width: Option<u32>) -> gtk::ScrolledWindow {
    create_oriented(content, max_width, false)
}

pub fn create_oriented(content: &impl IsA<gtk::Widget>, max_width: Option<u32>, vertical: bool) -> gtk::ScrolledWindow {
    let scroll = gtk::ScrolledWindow::new(None::<&gtk::Adjustment>, None::<&gtk::Adjustment>);
    scroll.style_context().add_class("niri-taskbar-scroll");
    scroll.set_policy(if vertical { gtk::PolicyType::Never } else { gtk::PolicyType::External },
                      if vertical { gtk::PolicyType::External } else { gtk::PolicyType::Never });
    scroll.set_propagate_natural_height(vertical);
    scroll.set_min_content_height(0);
    scroll.set_propagate_natural_width(!vertical);
    scroll.set_min_content_width(0);
    scroll.set_hexpand(false);
    if let Some(width) = max_width {
        if vertical { scroll.set_max_content_height(width.min(i32::MAX as u32) as i32); }
        else { scroll.set_max_content_width(width.min(i32::MAX as u32) as i32); }
    }
    scroll.add(content);
    scroll.add_events(gtk::gdk::EventMask::SCROLL_MASK | gtk::gdk::EventMask::SMOOTH_SCROLL_MASK);
    scroll.connect_scroll_event(move |widget, event| {
        let (dx, dy) = match event.direction() {
            gtk::gdk::ScrollDirection::Up => (0.0, -1.0),
            gtk::gdk::ScrollDirection::Down => (0.0, 1.0),
            gtk::gdk::ScrollDirection::Left => (-1.0, 0.0),
            gtk::gdk::ScrollDirection::Right => (1.0, 0.0),
            _ => event.delta(),
        };
        let amount = if dx.abs() >= dy.abs() { dx } else { dy };
        let adjustment = if vertical { widget.vadjustment() } else { widget.hadjustment() };
        let upper = (adjustment.upper() - adjustment.page_size()).max(adjustment.lower());
        adjustment.set_value((adjustment.value() + amount * 56.0).clamp(adjustment.lower(), upper));
        gtk::glib::Propagation::Stop
    });
    scroll
}

/// Legacy optional limit; recompute for each allocation, including output changes.
pub fn limit_fraction(scroll: &gtk::ScrolledWindow, fraction: f32) {
    if !fraction.is_finite() || fraction <= 0.0 {
        return;
    }
    let weak = scroll.downgrade();
    gtk::glib::idle_add_local_once(move || {
        let Some(scroll) = weak.upgrade() else { return };
        let Some(top) = scroll.toplevel() else { return };
        let weak = scroll.downgrade();
        top.connect_size_allocate(move |_, allocation| {
            let Some(scroll) = weak.upgrade() else { return };
            let width = (allocation.width() as f32 * fraction.min(1.0)).round() as i32;
            if scroll.max_content_width() != width {
                scroll.set_max_content_width(width.max(0));
            }
        });
    });
}

//! Exercise the production scroller in a real GTK allocation under Xvfb.
use gtk::glib::translate::ToGlibPtr;
use waybar_cffi::gtk::{self as gtk, prelude::*};
#[path = "../src/menu_style.rs"]
mod menu_style;
#[path = "../src/scroll.rs"]
mod scroll;

fn settle() {
    for _ in 0..30 {
        while gtk::events_pending() {
            gtk::main_iteration();
        }
        std::thread::sleep(std::time::Duration::from_millis(5));
    }
}

fn main() {
    gtk::init().unwrap();
    let window = gtk::Window::new(gtk::WindowType::Toplevel);
    window.set_default_size(800, 40);
    let row = gtk::Box::new(gtk::Orientation::Horizontal, 4);
    let left = gtk::Label::new(Some("Start"));
    left.set_size_request(100, -1);
    let right = gtk::Label::new(Some("Clock"));
    right.set_size_request(120, -1);
    let content = gtk::Box::new(gtk::Orientation::Horizontal, 0);
    let viewport = scroll::create(&content, None);
    row.pack_start(&left, false, false, 0);
    row.pack_start(&viewport, false, false, 0);
    row.pack_end(&right, false, false, 0);
    window.add(&row);
    window.show_all();
    for (width, count) in [
        (800, 0),
        (800, 1),
        (800, 4),
        (800, 40),
        (480, 40),
        (960, 40),
        (960, 1),
    ] {
        for child in content.children() {
            content.remove(&child);
        }
        for _ in 0..count {
            let item = gtk::DrawingArea::new();
            item.set_size_request(50, 36);
            content.pack_start(&item, false, false, 0);
        }
        content.show_all();
        window.resize(width, 40);
        settle();
        let allocated = viewport.allocated_width();
        let adjustment = viewport.hadjustment();
        println!(
            "bar={} icons={} viewport={} content={} fixed={}/{}",
            window.allocated_width(),
            count,
            allocated,
            adjustment.upper(),
            left.allocated_width(),
            right.allocated_width()
        );
        assert_eq!(window.allocated_width(), width);
        assert_eq!(left.allocated_width(), 100);
        assert_eq!(right.allocated_width(), 120);
        if count > 0 {
            assert_eq!(allocated, (count * 50).min(width - 228));
        }
        adjustment.set_value(0.0);
        let event = gtk::gdk::Event::new(gtk::gdk::EventType::Scroll);
        // GDK has no safe Rust setter for a scroll direction.
        unsafe {
            let raw: *const gtk::gdk::ffi::GdkEvent = event.to_glib_none().0;
            (*(raw as *mut gtk::gdk::ffi::GdkEventScroll)).direction =
                gtk::gdk::ffi::GDK_SCROLL_DOWN;
        }
        assert!(viewport.emit_by_name::<bool>("scroll-event", &[&event]));
        assert!(viewport.emit_by_name::<bool>("scroll-event", &[&event]));
        settle();
        if count == 40 {
            assert_eq!(adjustment.value(), 112.0);
        } else {
            assert_eq!(adjustment.value(), 0.0);
        }
    }
    viewport.set_max_content_width(30);
    settle();
    assert_eq!(viewport.allocated_width(), 30);
    scroll::limit_fraction(&viewport, 0.5);
    println!("GTK layout checks passed");
    window.close();

    // Render the exact production menu CSS over Waybar's global CSS.
    let base = gtk::CssProvider::new();
    base.load_from_path("../../config/waybar/style-bottom.css")
        .unwrap();
    gtk::StyleContext::add_provider_for_screen(
        &gtk::gdk::Screen::default().unwrap(),
        &base,
        gtk::STYLE_PROVIDER_PRIORITY_APPLICATION,
    );
    let parent = gtk::Window::new(gtk::WindowType::Toplevel);
    parent.set_default_size(440, 200);
    parent.show_all();
    settle();
    let menu = gtk::Menu::new();
    menu.append(&gtk::MenuItem::with_label("任务栏样式设置… (ADWS)"));
    menu.append(&gtk::MenuItem::with_label("组件与插件… (ADWS)"));
    menu_style::apply(&menu);
    menu.show_all();
    menu.popup_at_rect(
        &parent.window().unwrap(),
        &gtk::gdk::Rectangle::new(10, 10, 1, 1),
        gtk::gdk::Gravity::NorthWest,
        gtk::gdk::Gravity::NorthWest,
        None::<&gtk::gdk::Event>,
    );
    settle();
    let top = menu.toplevel().unwrap();
    println!("popup classes {:?}", top.style_context().list_classes());
    let surface = gtk::cairo::ImageSurface::create(
        gtk::cairo::Format::ARgb32,
        top.allocated_width(),
        top.allocated_height(),
    )
    .unwrap();
    let cr = gtk::cairo::Context::new(&surface).unwrap();
    top.draw(&cr);
    let pixbuf =
        gtk::gdk::pixbuf_get_from_surface(&surface, 0, 0, surface.width(), surface.height())
            .unwrap();
    pixbuf
        .savev("/tmp/adws-menu-check.png", "png", &[])
        .unwrap();
    menu.popdown();
    parent.close();
}

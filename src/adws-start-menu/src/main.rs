mod power;
mod account;
use glib::translate::ToGlibPtr;
use gtk::{gdk, gio, glib, prelude::*};
use serde_json::Value;
use std::{
    cell::RefCell,
    collections::HashSet,
    path::{Path, PathBuf},
    rc::Rc,
    time::Duration,
};

static MENU_STARTED: std::sync::OnceLock<std::time::Instant> = std::sync::OnceLock::new();
fn timing(stage: &str) {
    if std::env::var_os("ADWS_MENU_TIMING").is_some() {
        if let Some(start) = MENU_STARTED.get() {
            eprintln!("ADWS menu: {stage}: {} ms", start.elapsed().as_millis());
        }
    }
}

#[link(name = "gtk-layer-shell")]
extern "C" {
    fn gtk_layer_is_supported() -> i32;
    fn gtk_layer_init_for_window(window: *mut gtk::ffi::GtkWindow);
    fn gtk_layer_set_monitor(window: *mut gtk::ffi::GtkWindow, monitor: *mut gdk::ffi::GdkMonitor);
    fn gtk_layer_set_layer(window: *mut gtk::ffi::GtkWindow, layer: i32);
    fn gtk_layer_set_anchor(window: *mut gtk::ffi::GtkWindow, edge: i32, anchor: i32);
    fn gtk_layer_set_margin(window: *mut gtk::ffi::GtkWindow, edge: i32, margin: i32);
    fn gtk_layer_set_exclusive_zone(window: *mut gtk::ffi::GtkWindow, zone: i32);
    fn gtk_layer_set_keyboard_mode(window: *mut gtk::ffi::GtkWindow, mode: i32);
    fn gtk_layer_set_namespace(window: *mut gtk::ffi::GtkWindow, name: *const std::ffi::c_char);

}

// Button coordinates are output-local logical pixels, including bar margins.
fn menu_origin(
    anchor: &Value,
    width: i32,
    height: i32,
    screen_w: i32,
    screen_h: i32,
) -> (i32, i32) {
    let coordinate = |key| anchor[key].as_i64().unwrap_or(0).clamp(0, 100_000) as i32;
    let (x, y, w, h) = (
        coordinate("x"),
        coordinate("y"),
        coordinate("w"),
        coordinate("h"),
    );
    let (left, top) = match anchor["edge"].as_str().unwrap_or("bottom") {
        "top" => (x, y + h + 8),
        "left" => (x + w + 8, y),
        "right" => (x - width - 8, y),
        _ => (x, y - height - 8),
    };
    (
        left.clamp(0, (screen_w - width).max(0)),
        top.clamp(0, (screen_h - height).max(0)),
    )
}

fn config_home() -> PathBuf {
    std::env::var_os("XDG_CONFIG_HOME")
        .filter(|s| !s.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".config")
        })
}
fn chinese() -> bool {
    let get = |key| std::env::var(key).ok().filter(|s| !s.is_empty());
    let locale = get("LC_ALL")
        .or_else(|| get("LC_MESSAGES"))
        .or_else(|| get("LANG"))
        .unwrap_or_else(|| "C".into());
    if locale == "C" || locale.starts_with("C.") || locale == "POSIX" {
        return false;
    }
    get("LANGUAGE")
        .unwrap_or(locale)
        .split(':')
        .next()
        .unwrap_or("")
        .to_lowercase()
        .starts_with("zh")
}
#[derive(Clone)]
struct Text {
    zh: bool,
    table: Value,
}
impl Text {
    fn new(root: &Path) -> Self {
        Self {
            zh: chinese(),
            table: std::fs::read(root.join("language/en.json"))
                .ok()
                .and_then(|d| serde_json::from_slice(&d).ok())
                .unwrap_or(Value::Null),
        }
    }
    fn get(&self, zh: &str) -> String {
        if self.zh {
            zh.into()
        } else {
            self.table
                .get(zh)
                .and_then(Value::as_str)
                .unwrap_or(zh)
                .into()
        }
    }
}
fn json_file(path: &Path) -> Value {
    std::fs::read(path)
        .ok()
        .and_then(|d| serde_json::from_slice(&d).ok())
        .unwrap_or(Value::Null)
}
fn theme_name(value: &str) -> &str {
    match value {
        "aero" | "xp" | "akiacg" => value,
        _ => "kde",
    }
}
fn grid_theme(theme: &str) -> bool {
    matches!(theme, "kde" | "akiacg")
}
fn add_class(widget: &impl IsA<gtk::Widget>, name: &str) {
    widget.style_context().add_class(name);
}

// Read imported files too: palette generators commonly replace links atomically.
fn css_tree(path: &Path, seen: &mut HashSet<PathBuf>) -> Result<String, String> {
    if seen.len() > 64 {
        return Err("Too many CSS imports".into());
    }
    if !seen.insert(path.to_path_buf()) {
        return Ok(String::new());
    }
    let source = std::fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let pattern =
        regex::Regex::new(r#"@import\s+(?:url\(\s*)?["']([^"']+)["']\s*\)?\s*;"#).unwrap();
    let mut result = String::new();
    for item in pattern.captures_iter(&source) {
        let name = &item[1];
        if name.contains("://") {
            return Err("Only local CSS imports are supported".into());
        }
        result.push_str(&css_tree(
            &path.parent().unwrap_or(Path::new(".")).join(name),
            seen,
        )?);
    }
    result.push_str(&pattern.replace_all(&source, ""));
    Ok(result)
}
fn stylesheet(root: &Path, theme: &str, custom: Option<&Path>) -> Result<String, String> {
    let palette = config_home().join("waybar/colors.css");
    let mut css = String::from("@define-color adws_bg @theme_bg_color; @define-color adws_fg @theme_fg_color; @define-color adws_accent @theme_selected_bg_color; @define-color adws_on_accent @theme_selected_fg_color; @define-color adws_border mix(@theme_bg_color,@theme_fg_color,0.25);\n");
    if palette.exists() {
        let data = css_tree(&palette, &mut HashSet::new())?;
        css.push_str(&data);
        for (target, source) in [
            ("adws_bg", "surface_container_high"),
            ("adws_fg", "on_surface"),
            ("adws_accent", "primary"),
            ("adws_on_accent", "on_primary"),
            ("adws_border", "outline_variant"),
        ] {
            let definition = regex::Regex::new(&format!(r"@define-color\s+{}\s", source)).unwrap();
            if definition.is_match(&data) {
                css.push_str(&format!("\n@define-color {target} @{source};\n"));
            }
        }
    }
    for file in ["base.css".into(), format!("{theme}.css")] {
        css.push_str(&css_tree(
            &root.join("config/start-menu").join(file),
            &mut HashSet::new(),
        )?);
    }
    if theme == "akiacg" {
        let artwork = glib::filename_to_uri(root.join("config/start-menu/akiacg-orbit.svg"), None)
            .map_err(|error| error.to_string())?;
        css = css.replace("akiacg-orbit.svg", artwork.as_str());
    }
    if let Some(path) = custom {
        css.push_str(&css_tree(path, &mut HashSet::new())?);
    }
    Ok(css)
}
fn matches(query: &str, category: &str, searchable: &str, categories: &str) -> bool {
    query
        .split_whitespace()
        .all(|word| searchable.contains(word))
        && (category.is_empty() || categories.split(';').any(|c| c == category))
}
struct App {
    info: gio::AppInfo,
    searchable: String,
    categories: String,
}
fn applications() -> Vec<App> {
    let mut apps: Vec<_> = gio::AppInfo::all()
        .into_iter()
        .filter(|info| info.should_show())
        .map(|info| {
            let desktop = info.clone().downcast::<gio::DesktopAppInfo>().ok();
            let categories = desktop
                .as_ref()
                .and_then(|d| d.categories())
                .map(|s| s.to_string())
                .unwrap_or_default();
            let keywords = desktop
                .as_ref()
                .map(|d| {
                    d.keywords()
                        .iter()
                        .map(|s| s.as_str())
                        .collect::<Vec<_>>()
                        .join(" ")
                })
                .unwrap_or_default();
            let searchable = format!(
                "{} {} {} {}",
                info.display_name(),
                info.name(),
                info.description().unwrap_or_default(),
                keywords
            )
            .to_lowercase();
            App {
                info,
                searchable,
                categories,
            }
        })
        .collect();
    apps.sort_by_key(|app| app.info.display_name().to_lowercase());
    apps
}
fn icon_button(text: &str, icon: &str) -> gtk::Button {
    let button = gtk::Button::new();
    let content = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    content.pack_start(
        &gtk::Image::from_icon_name(Some(icon), gtk::IconSize::Button),
        false,
        false,
        0,
    );
    let label = gtk::Label::new(Some(text));
    label.set_xalign(0.0);
    content.pack_start(&label, true, true, 0);
    button.add(&content);
    button
}
const CATEGORIES: &[(&str, &str, &str)] = &[
    ("全部应用", "", "view-app-grid-symbolic"),
    ("网络", "Network", "network-workgroup-symbolic"),
    ("办公", "Office", "x-office-document-symbolic"),
    ("多媒体", "AudioVideo", "applications-multimedia-symbolic"),
    ("图形", "Graphics", "applications-graphics-symbolic"),
    ("开发", "Development", "applications-development-symbolic"),
    ("游戏", "Game", "applications-games-symbolic"),
    ("系统", "System", "applications-system-symbolic"),
];
fn scrolled(widget: &impl IsA<gtk::Widget>) -> gtk::ScrolledWindow {
    let scroll = gtk::ScrolledWindow::new(None::<&gtk::Adjustment>, None::<&gtk::Adjustment>);
    scroll.set_policy(gtk::PolicyType::Never, gtk::PolicyType::Automatic);
    scroll.add(widget);
    scroll
}
fn select_navigation(side: &gtk::Box, button: &gtk::Button) {
    for child in side.children() {
        child.style_context().remove_class("active-category");
    }
    add_class(button, "active-category");
}
fn launch(info: &gio::AppInfo, application: &gtk::Application, error: &gtk::Label) {
    let context = gdk::Display::default().and_then(|d| d.app_launch_context());
    match info.launch(&[], context.as_ref()) {
        Ok(()) => dismiss(application),
        Err(e) => {
            error.set_text(&e.to_string());
            error.show();
        }
    }
}
// Only an explicit activation of the search entry executes its exact contents.
// App-row activation remains a separate path; typing/filtering never runs code.
fn run_command(command: &str) -> Result<(), std::io::Error> {
    if command.trim().is_empty() {
        return Ok(());
    }
    std::process::Command::new("/bin/sh")
        .args(["-c", command])
        .stdin(std::process::Stdio::null())
        .spawn()
        .map(|_| ())
}
thread_local! {static CLOSE:RefCell<Option<Rc<dyn Fn()>>>=RefCell::new(None);}
fn dismiss(application: &gtk::Application) {
    let close = CLOSE.with(|slot| slot.borrow().clone());
    if let Some(close) = close {
        close();
    } else {
        application.quit();
    }
}
struct Motion {
    menu: gtk::EventBox,
    stage: gtk::Box,
    window: gtk::ApplicationWindow,
    backdrop: Option<gtk::ApplicationWindow>,
    one_shot: bool,
    hidden_at: std::cell::Cell<std::time::Instant>,
    application: gtk::Application,
    edge: String,
    duration: f64,
    progress: std::cell::Cell<f64>,
    tick: RefCell<Option<gtk::TickCallbackId>>,
    deadline: RefCell<Option<glib::SourceId>>,
    snapshot: RefCell<Option<((i32, i32, i32), gtk::cairo::ImageSurface)>>,
    busy: Rc<std::cell::Cell<bool>>,
    closing: std::cell::Cell<bool>,
}
impl Motion {
    fn bind(self: &Rc<Self>) {
        // The layout and input surface stay fixed. Render only the menu-sized
        // subtree once, then composite it during motion instead of reallocating
        // every row, icon and label on every frame.
        self.menu.set_margin_start(8);
        self.menu.set_margin_end(8);
        self.menu.set_margin_top(8);
        self.menu.set_margin_bottom(8);
        let weak = Rc::downgrade(self);
        self.stage.connect_draw(move |stage, cr| {
            let Some(this) = weak.upgrade() else { return glib::Propagation::Proceed; };
            let value = this.progress.get();
            if value >= 1. { return glib::Propagation::Proceed; }
            if value <= 0. { return glib::Propagation::Stop; }
            let key = (stage.allocated_width(), stage.allocated_height(), stage.scale_factor().max(1));
            if this.snapshot.borrow().as_ref().is_none_or(|(old, _)| *old != key) {
                let began = std::time::Instant::now();
                let Ok(surface) = gtk::cairo::ImageSurface::create(
                    gtk::cairo::Format::ARgb32, key.0.max(1) * key.2, key.1.max(1) * key.2)
                    else { return glib::Propagation::Proceed; };
                surface.set_device_scale(key.2 as f64, key.2 as f64);
                let Ok(context) = gtk::cairo::Context::new(&surface)
                    else { return glib::Propagation::Proceed; };
                stage.propagate_draw(&this.menu, &context);
                this.snapshot.replace(Some((key, surface)));
                if std::env::var_os("ADWS_MENU_TIMING").is_some() {
                    eprintln!("ADWS menu: motion snapshot {} us", began.elapsed().as_micros());
                }
            }
            let snapshot = this.snapshot.borrow();
            let (_, surface) = snapshot.as_ref().unwrap();
            let offset = ((1. - value) * 8. * key.2 as f64).round() / key.2 as f64;
            let (x, y) = match this.edge.as_str() {
                "top" => (0., -offset), "left" => (-offset, 0.),
                "right" => (offset, 0.), _ => (0., offset),
            };
            let _ = cr.save();
            let _ = cr.set_source_surface(surface, x, y);
            cr.source().set_filter(gtk::cairo::Filter::Nearest);
            let _ = cr.paint_with_alpha(value);
            let _ = cr.restore();
            glib::Propagation::Stop
        });
        let weak = Rc::downgrade(self);
        self.window.connect_destroy(move |_| {
            if let Some(this) = weak.upgrade() { this.cancel(); }
        });
    }
    fn cancel(&self) {
        if let Some(tick) = self.tick.borrow_mut().take() { tick.remove(); }
        if let Some(deadline) = self.deadline.borrow_mut().take() { deadline.remove(); }
        self.snapshot.borrow_mut().take();
        self.busy.set(false);
    }
    fn arm_deadline(self: &Rc<Self>, target: f64, wait: u64) {
        if let Some(deadline) = self.deadline.borrow_mut().take() { deadline.remove(); }
        let weak = Rc::downgrade(self);
        self.deadline.replace(Some(glib::timeout_add_local_once(Duration::from_millis(wait), move || {
            if let Some(this) = weak.upgrade() {
                this.deadline.borrow_mut().take();
                if let Some(tick) = this.tick.borrow_mut().take() { tick.remove(); }
                this.set(target);
                this.busy.set(false);
                if target == 0. { this.finish_close(); }
            }
        })));
    }
    fn finish_close(&self) {
        if self.one_shot { self.application.quit(); }
        else {
            unsafe { if gtk_layer_is_supported() != 0 { gtk_layer_set_keyboard_mode(self.window.upcast_ref::<gtk::Window>().to_glib_none().0, 0); } }
            self.hidden_at.set(std::time::Instant::now());
            self.window.hide();
            if let Some(backdrop) = &self.backdrop { backdrop.hide(); }
        }
    }
    fn set(&self, value: f64) {
        if self.progress.get() == 0. && value > 0. { timing("animation visible"); }
        self.progress.set(value);
        if value == 0. || value == 1. {
            self.snapshot.borrow_mut().take();
        }
        self.stage.queue_draw();
    }
    fn animate(self: &Rc<Self>, target: f64) {
        if let Some(tick) = self.tick.borrow_mut().take() {
            tick.remove();
        }
        if let Some(deadline) = self.deadline.borrow_mut().take() { deadline.remove(); }
        if self.duration <= 0. {
            self.busy.set(false);
            self.set(target);
            if target == 0. {
                self.finish_close();
            }
            return;
        }
        let from = self.progress.get();
        self.busy.set(true);
        // Mapping/configuring the layer surface is not part of the animation.
        // Starting before map skipped its first frames on cold opens.
        let start = std::cell::Cell::new(None);
        let wait = (self.duration * (target - from).abs().max(0.01) / 1000.).ceil() as u64 + 80;
        let measure = std::env::var_os("ADWS_MENU_TIMING").is_some();
        let frames = RefCell::new(Vec::new());
        let weak = Rc::downgrade(self);
        let tick = self.menu.add_tick_callback(move |_, clock| {
            let Some(this) = weak.upgrade() else {
                return glib::ControlFlow::Break;
            };
            let now = clock.frame_time();
            let began = match start.get() {
                Some(value) => value,
                None => { start.set(Some(now)); this.arm_deadline(target, wait); now },
            };
            if measure { frames.borrow_mut().push(now); }
            let t = ((now - began) as f64 / (this.duration * (target - from).abs().max(0.01)))
                .clamp(0., 1.);
            // Reveal promptly, then settle; closing retains a smooth fade.
            let eased = if target > from { 1. - (1. - t).powi(3) } else { t * t * (3. - 2. * t) };
            this.set(from + (target - from) * eased);
            if t >= 1. {
                this.busy.set(false);
                if measure {
                    let frames = frames.borrow();
                    let mut gaps: Vec<_> = frames.windows(2).map(|pair| pair[1] - pair[0]).collect();
                    gaps.sort_unstable();
                    if !gaps.is_empty() {
                        eprintln!("ADWS menu: motion target={target} frames={} median_us={} max_us={}",
                            frames.len(), gaps[gaps.len()/2], gaps[gaps.len()-1]);
                    }
                }
                this.tick.borrow_mut().take();
                if let Some(deadline) = this.deadline.borrow_mut().take() { deadline.remove(); }
                if target == 0. {
                    this.finish_close();
                }
                glib::ControlFlow::Break
            } else {
                glib::ControlFlow::Continue
            }
        });
        self.tick.replace(Some(tick));
        // A covered Wayland surface can stop receiving frame callbacks. Never
        // leave a closing fullscreen input surface waiting on the compositor.
        self.arm_deadline(target, wait);
    }
}
// Discovery and parsing happen off the GTK thread; only small batches create
// widgets. Each menu invocation obtains a fresh catalog, including new installs.
#[allow(clippy::too_many_arguments)]
fn load_catalog(
    list: &gtk::ListBox,
    favorites: &gtk::FlowBox,
    apps: &Rc<RefCell<Vec<App>>>,
    theme: &str,
    application: &gtk::Application,
    status: &gtk::Label,
    empty: &gtk::Label,
    text: &Text,
    motion_busy: Rc<std::cell::Cell<bool>>,
) {
    let (send, recv) = std::sync::mpsc::sync_channel(1);
    let favorite_count = if theme == "kde" { 9 } else { 8 };
    std::thread::spawn(move || {
        let catalog = applications();
        let pins = json_file(&config_home().join("adws/taskbar-pins.json"));
        let pinned: Vec<_> = pins["apps"].as_array().into_iter().flatten()
            .filter_map(|v| v["desktop_id"].as_str()).collect();
        let mut featured: Vec<_> = catalog.iter().enumerate().collect();
        featured.sort_by_key(|(i, app)| (
            pinned.iter().position(|id| app.info.id().as_deref() == Some(*id)).unwrap_or(usize::MAX),
            !app.categories.split(';').any(|v| matches!(v, "WebBrowser" | "FileManager" | "TerminalEmulator")), *i));
        let featured: Vec<_> = featured.into_iter().take(favorite_count)
            .filter_map(|(_, app)| app.info.clone().downcast::<gio::DesktopAppInfo>().ok()?.filename()).collect();
        let records: Vec<_> = catalog
            .into_iter()
            .filter_map(|app| {
                let desktop = app.info.downcast::<gio::DesktopAppInfo>().ok()?;
                Some((desktop.filename()?, app.searchable, app.categories))
            })
            .collect();
        let _ = send.send((records, featured));
    });
    let list = list.clone();
    let favorites = favorites.clone();
    let apps = apps.clone();
    let theme = theme.to_string();
    let application = application.clone();
    let status = status.clone();
    let empty = empty.clone();
    let text = text.clone();
    let mut pending = None::<std::collections::VecDeque<(PathBuf, String, String)>>;
    glib::timeout_add_local(Duration::from_millis(8), move || {
        if pending.is_none() {
            match recv.try_recv() {
                Ok((data, featured)) => {
                    fill_favorites(&featured, &favorites, &theme, &application, &status);
                    pending = Some(data.into());
                },
                Err(std::sync::mpsc::TryRecvError::Empty) => return glib::ControlFlow::Continue,
                Err(_) => {
                    empty.set_text(&text.get("没有匹配的应用程序"));
                    return glib::ControlFlow::Break;
                }
            }
        }
        // Home shortcuts are available first. Building the full catalog can
        // invalidate hundreds of rows and load icons; keep that work out of
        // the opening/closing animation's frame budget.
        if motion_busy.get() { return glib::ControlFlow::Continue; }
        let began = std::time::Instant::now();
        let queue = pending.as_mut().unwrap();
        for _ in 0..12 {
            let Some((path, searchable, categories)) = queue.pop_front() else {
                break;
            };
            let Some(info) =
                gio::DesktopAppInfo::from_filename(path).map(|v| v.upcast::<gio::AppInfo>())
            else {
                continue;
            };
            let row = gtk::ListBoxRow::new();
            let line = gtk::Box::new(gtk::Orientation::Horizontal, 8);
            let image = app_image(&info, 24);
            line.pack_start(&image, false, false, 0);
            let label = gtk::Label::new(Some(&info.display_name()));
            label.set_xalign(0.);
            label.set_ellipsize(gtk::pango::EllipsizeMode::End);
            label.set_max_width_chars(26);
            line.pack_start(&label, true, true, 0);
            row.add(&line);
            row.set_tooltip_text(info.description().as_deref());
            apps.borrow_mut().push(App {
                info,
                searchable,
                categories,
            });
            list.add(&row);
            row.show_all();
            if began.elapsed() > Duration::from_millis(4) {
                break;
            }
        }
        if !queue.is_empty() {
            return glib::ControlFlow::Continue;
        }
        empty.set_text(&text.get("没有匹配的应用程序"));

        glib::ControlFlow::Break
    });
}
// Home shortcuts do not wait for every installed application row and icon.
fn fill_favorites(paths: &[PathBuf], favorites: &gtk::FlowBox, theme: &str,
                  application: &gtk::Application, status: &gtk::Label) {
        for path in paths {
            let Some(info) = gio::DesktopAppInfo::from_filename(path).map(|v| v.upcast::<gio::AppInfo>()) else { continue; };
            let button = gtk::Button::new();
            add_class(&button, "shortcut");
            let line = gtk::Box::new(
                if theme == "kde" {
                    gtk::Orientation::Vertical
                } else {
                    gtk::Orientation::Horizontal
                },
                8,
            );
            line.pack_start(
                &app_image(&info, if theme == "kde" { 40 } else { 32 }),
                false,
                false,
                0,
            );
            let label = gtk::Label::new(Some(&info.display_name()));
            label.set_ellipsize(gtk::pango::EllipsizeMode::End);
            label.set_max_width_chars(if theme == "kde" { 15 } else { 24 });
            label.set_xalign(if theme == "kde" { 0.5 } else { 0. });
            line.pack_start(&label, true, true, 0);
            button.add(&line);
            let info = info.clone();
            let a = application.clone();
            let error = status.clone();
            button.connect_clicked(move |_| launch(&info, &a, &error));
            favorites.insert(&button, -1);
        }
        favorites.show_all();
}
fn app_image(info: &gio::AppInfo, size: i32) -> gtk::Image {
    let image = info
        .icon()
        .map(|icon| gtk::Image::from_gicon(&icon, gtk::IconSize::LargeToolbar))
        .unwrap_or_else(|| {
            gtk::Image::from_icon_name(
                Some("application-x-executable"),
                gtk::IconSize::LargeToolbar,
            )
        });
    image.set_pixel_size(size);
    image
}

// Fetch current geometry from the taskbar instead of estimating the button's
// position from configured padding. Missing/older taskbars retain the fallback.
async fn taskbar_anchor() -> Option<Value> {
    let display = gdk::Display::default()?;
    let monitor = display.default_seat().and_then(|s| s.pointer()).and_then(|p| {
        let (_, x, y) = p.position(); display.monitor_at_point(x, y)
    }).or_else(|| display.primary_monitor()).or_else(|| display.monitor(0))?;
    let index = (0..display.n_monitors()).find(|&i| display.monitor(i).as_ref() == Some(&monitor))?;
    let bus = gio::bus_get_future(gio::BusType::Session).await.ok()?;
    let reply = bus.call_future(Some("org.ADWS.Taskbar.Start"), "/org/ADWS/Taskbar/Start",
        "org.ADWS.Taskbar.Start", "GetAnchors", None, None,
        gio::DBusCallFlags::NO_AUTO_START, 150).await.ok()?;
    let (anchors,) = reply.get::<(Vec<String>,)>()?;
    anchors.iter().filter_map(|s| serde_json::from_str::<Value>(s).ok())
        .find(|a| a["monitor"].as_i64() == Some(index as i64))
}

struct CachedMenu {
    window: gtk::ApplicationWindow,
    motion: Rc<Motion>,
    search: gtk::SearchEntry,
    pages: gtk::Stack,
    power: Rc<power::PowerMenu>,
    width: i32,
    height: i32,
    layered: bool,
    xp: bool,
    reload: Rc<dyn Fn()>,
    home: gtk::Stack,
    category: Rc<RefCell<String>>,
    list: gtk::ListBox,
}
impl CachedMenu {
    fn reopen(&self, anchor: Option<&Value>) {
        if self.layered {
            if let Some(anchor) = anchor {
                if let Some(display) = gdk::Display::default() {
                    if let Some(monitor) = anchor["monitor"].as_i64().and_then(|i| display.monitor(i as i32)) {
                        let area = monitor.geometry();
                        let (x, y) = menu_origin(anchor, self.width, self.height, area.width(), area.height());
                        unsafe {
                            let ptr = self.window.upcast_ref::<gtk::Window>().to_glib_none().0;
                            gtk_layer_set_margin(ptr, 0, x);
                            gtk_layer_set_margin(ptr, 2, y);
                        }
                    }
                }
            }
            unsafe { gtk_layer_set_keyboard_mode(self.window.upcast_ref::<gtk::Window>().to_glib_none().0, 1); }
        }
        (self.reload)();
        self.category.borrow_mut().clear();
        self.list.invalidate_filter();
        self.list.unselect_all();
        self.home.set_visible_child_name("home");
        self.power.back();
        self.pages.set_visible_child_name("launcher");
        self.search.set_text("");
        self.motion.closing.set(false);
        self.motion.menu.set_sensitive(true);
        if let Some(backdrop) = &self.motion.backdrop { backdrop.show_all(); }
        self.window.show();
        self.motion.animate(1.);
        if !self.xp { self.search.grab_focus(); }
        timing("cached menu reopened");
    }
}

fn main() {
    let _ = MENU_STARTED.set(std::time::Instant::now());
    timing("process entry");
    let args: Vec<_> = std::env::args().collect();
    if args.iter().any(|s| s == "--help" || s == "-h") {
        println!("adws-start-menu --root PATH [--theme kde|aero|xp|akiacg] [--css PATH] [--one-shot]");
        return;
    }
    if !args.iter().any(|s| s == "--root") {
        eprintln!("Missing --root"); std::process::exit(2);
    }
    if !chinese() { std::env::set_var("LANGUAGE", "en"); }
    let isolated = args.iter().any(|s| s == "--smoke-test" || s == "--one-shot");
    let mut flags = gio::ApplicationFlags::HANDLES_COMMAND_LINE | gio::ApplicationFlags::SEND_ENVIRONMENT;
    if isolated { flags |= gio::ApplicationFlags::NON_UNIQUE; }
    let app = gtk::Application::new(Some("org.ADWS.StartMenu"), flags);
    app.connect_startup(|_| timing("GTK startup"));
    let cache = Rc::new(RefCell::new(None::<(Value, CachedMenu)>));
    let opening = Rc::new(std::cell::Cell::new(false));
    let catalog_dirty = Rc::new(std::cell::Cell::new(false));
    let dirty = catalog_dirty.clone();
    let monitor = gio::AppInfoMonitor::get();
    monitor.connect_changed(move |_| dirty.set(true));
    let last_used = Rc::new(std::cell::Cell::new(std::time::Instant::now()));
    let state = cache.clone(); let application = app.downgrade();
    glib::timeout_add_seconds_local(5, move || {
        if state.borrow().as_ref().is_some_and(|(_, menu)| !menu.window.is_visible()
            && menu.motion.hidden_at.get().elapsed() > Duration::from_secs(180)) {
            if let Some(application) = application.upgrade() { application.quit(); }
            return glib::ControlFlow::Break;
        }
        glib::ControlFlow::Continue
    });
    app.connect_command_line(move |application, command| {
        last_used.set(std::time::Instant::now());
        let args: Vec<String> = command.arguments().iter().map(|s| s.to_string_lossy().into_owned()).collect();
        if args.iter().any(|s| s == "--exit") { application.quit(); return 0; }
        let value = |name: &str| args.iter().position(|s| s == name).and_then(|i| args.get(i + 1)).cloned();
        let Some(root) = value("--root").map(PathBuf::from) else { return 2; };
        let layout = json_file(&config_home().join("adws/taskbar-layout.json"));
        let options = options_owned(&layout);
        let chosen = value("--theme").unwrap_or_else(|| options["start_menu_theme"].as_str().unwrap_or("kde").into());
        let theme = theme_name(&chosen).to_string();
        let custom = value("--css").or_else(|| options["start_menu_css"].as_str().map(str::to_owned))
            .filter(|s| !s.is_empty()).map(PathBuf::from);
        let smoke = value("--smoke-test").map(PathBuf::from);
        let one_shot = smoke.is_some() || args.iter().any(|s| s == "--one-shot");
        let layer_probe = args.iter().any(|s| s == "--check-wayland");
        let anchor = command.getenv("ADWS_START_ANCHOR").and_then(|s| serde_json::from_str::<Value>(&s).ok());
        if opening.replace(true) { return 0; }
        let opening = opening.clone(); let application = application.clone();
        let cache = cache.clone(); let dirty = catalog_dirty.clone();
        let hold = application.hold();
        glib::MainContext::default().spawn_local(async move {
            let anchor = if anchor.is_some() || (smoke.is_some() && !layer_probe) { anchor } else { taskbar_anchor().await };
            let signature = serde_json::json!([root, theme, custom, options,
                json_file(&config_home().join("adws/taskbar-pins.json")),
                anchor.as_ref().and_then(|v| v["monitor"].as_i64()),
                anchor.as_ref().and_then(|v| v["edge"].as_str())]);
            let refresh = dirty.replace(false);
            let reusable = cache.borrow().as_ref().is_some_and(|(key, _)| *key == signature) && !refresh;
            if reusable {
                if let Some((_, menu)) = cache.borrow().as_ref() {
                    if menu.window.is_visible() && !menu.motion.closing.get() { dismiss(&application); }
                    else { menu.reopen(anchor.as_ref()); }
                }
            } else {
                if let Some((_, old)) = cache.borrow_mut().take() { unsafe { old.window.destroy(); } }
                CLOSE.with(|slot| { slot.borrow_mut().take(); });
                let menu = build(&application, &root, &theme, custom.as_deref(), &options,
                    smoke.as_deref(), MenuPlacement { layer_probe, anchor, one_shot });
                cache.replace(Some((signature, menu)));
            }
            opening.set(false); drop(hold);
        });
        0
    });
    app.run_with_args(&args);
}
fn options_owned(layout: &Value) -> Value {
    layout["options"].clone()
}
struct MenuPlacement { layer_probe: bool, anchor: Option<Value>, one_shot: bool }

fn build(
    application: &gtk::Application,
    root: &Path,
    theme: &str,
    custom: Option<&Path>,
    options: &Value,
    smoke: Option<&Path>,
    placement: MenuPlacement,
) -> CachedMenu {
    let MenuPlacement { layer_probe, anchor, one_shot } = placement;
    timing("activation");
    let started = std::time::Instant::now();
    let text = Text::new(root);
    let window = gtk::ApplicationWindow::new(application);
    window.set_title(&text.get("开始菜单"));
    window.set_decorated(false);
    window.set_resizable(false);
    window.set_app_paintable(true);
    window.set_type_hint(gdk::WindowTypeHint::PopupMenu);
    add_class(&window, "adws-start-overlay");
    if let Some(screen) = gtk::prelude::GtkWindowExt::screen(&window) {
        if let Some(visual) = screen.rgba_visual() {
            window.set_visual(Some(&visual));
        }
    }
    let layered = (smoke.is_none() || layer_probe) && unsafe { gtk_layer_is_supported() != 0 };
    let display = gdk::Display::default().expect("GTK display");
    let monitor = anchor
        .as_ref()
        .and_then(|a| a["monitor"].as_i64())
        .and_then(|i| i32::try_from(i).ok())
        .and_then(|i| display.monitor(i))
        .or_else(|| {
            display
                .default_seat()
                .and_then(|s| s.pointer())
                .and_then(|p| {
                    let (_, x, y) = p.position();
                    display.monitor_at_point(x, y)
                })
        })
        .or_else(|| display.primary_monitor())
        .or_else(|| display.monitor(0));
    let geometry = monitor.as_ref().map(|m| m.geometry());
    let height = geometry
        .as_ref()
        .map(|g| {
            (g.height() - 120).clamp(
                180,
                if theme == "akiacg" {
                    620
                } else if theme == "kde" {
                    550
                } else if theme == "aero" {
                    570
                } else {
                    540
                },
            )
        })
        .unwrap_or(520);
    let width = geometry
        .as_ref()
        .map(|g| (g.width() - 40).clamp(300, if grid_theme(theme) { 680 } else { 500 }))
        .unwrap_or(600);
    window.set_default_size(width, height);
    if layered {
        window.set_resizable(true);
        // SAFETY: borrowed GTK objects remain live; calls happen before realization.
        unsafe {
            let ptr = window.upcast_ref::<gtk::Window>().to_glib_none().0;
            gtk_layer_init_for_window(ptr);
            if let Some(monitor) = monitor.as_ref() {
                gtk_layer_set_monitor(ptr, monitor.to_glib_none().0);
            }
            gtk_layer_set_layer(ptr, 3);
            gtk_layer_set_namespace(ptr, c"adws-start-menu".as_ptr());
            gtk_layer_set_exclusive_zone(ptr, -1);
            gtk_layer_set_keyboard_mode(ptr, 1);
            gtk_layer_set_anchor(ptr, 0, 1);
            gtk_layer_set_anchor(ptr, 2, 1);
        }
    } else {
        window.set_default_size(width, height);
        window.set_position(gtk::WindowPosition::Center);
        window.set_keep_above(true);
    }
    // A static click catcher may cover the monitor, but animated pixels must
    // only allocate a menu-sized Wayland buffer (especially at HiDPI/4K).
    let backdrop = layered.then(|| {
        let catcher = gtk::ApplicationWindow::new(application);
        catcher.set_decorated(false);
        catcher.set_app_paintable(true);
        add_class(&catcher, "adws-start-overlay");
        if let Some(screen) = gtk::prelude::GtkWindowExt::screen(&catcher) {
            if let Some(visual) = screen.rgba_visual() { catcher.set_visual(Some(&visual)); }
        }
        if let Some(area) = &geometry { catcher.set_default_size(area.width(), area.height()); }
        unsafe {
            let ptr = catcher.upcast_ref::<gtk::Window>().to_glib_none().0;
            gtk_layer_init_for_window(ptr);
            if let Some(monitor) = &monitor { gtk_layer_set_monitor(ptr, monitor.to_glib_none().0); }
            gtk_layer_set_layer(ptr, 2);
            gtk_layer_set_namespace(ptr, c"adws-start-dismiss".as_ptr());
            gtk_layer_set_exclusive_zone(ptr, -1);
            gtk_layer_set_keyboard_mode(ptr, 0);
            for edge in 0..4 { gtk_layer_set_anchor(ptr, edge, 1); }
        }
        let background = gtk::EventBox::new();
        background.set_visible_window(false);
        catcher.add(&background);
        let app = application.clone();
        background.connect_button_press_event(move |_, _| {
            dismiss(&app);
            glib::Propagation::Stop
        });
        let cleanup = catcher.clone();
        window.connect_destroy(move |_| unsafe { cleanup.destroy(); });
        // Power actions temporarily hide the menu and may restore it on error.
        // The click catcher must follow those paths too, not just Motion.
        let hidden = catcher.clone();
        window.connect_hide(move |_| hidden.hide());
        let shown = catcher.clone();
        window.connect_show(move |_| shown.show_all());
        catcher
    });
    let menu = gtk::EventBox::new();
    add_class(&menu, "adws-start-menu");
    add_class(&menu, theme);
    menu.connect_button_press_event(|_, _| glib::Propagation::Stop);
    let stage = gtk::Box::new(gtk::Orientation::Vertical, 0);
    stage.pack_start(&menu, true, true, 0);
    stage.set_size_request(width, height);
    if layered {
        let position = options["position"].as_str().unwrap_or("bottom");
        let margin = (options["thickness"].as_i64().unwrap_or(36).clamp(20, 160) + 16) as i32;
        if let Some(area) = &geometry {
            let (x, y) = if let Some(anchor) = &anchor {
                menu_origin(anchor, width, height, area.width(), area.height())
            } else {
                (if position == "right" { (area.width()-width-margin).max(0) } else if position == "left" { margin } else { 12 },
                 if position == "bottom" { (area.height()-height-margin).max(0) } else if position == "top" { margin } else { 12 })
            };
            unsafe {
                let ptr = window.upcast_ref::<gtk::Window>().to_glib_none().0;
                gtk_layer_set_margin(ptr, 0, x);
                gtk_layer_set_margin(ptr, 2, y);
            }
        }
    }
    window.add(&stage);
    let content = gtk::Box::new(gtk::Orientation::Vertical, 0);
    let menu_pages = gtk::Stack::new();
    menu_pages.set_transition_type(gtk::StackTransitionType::Crossfade);
    menu_pages.set_transition_duration(if options["tab_animations"].as_bool().unwrap_or(false) {
        150
    } else {
        0
    });
    menu.add(&menu_pages);
    menu_pages.add_named(&content, "launcher");
    for edge in [
        gtk::PositionType::Left,
        gtk::PositionType::Right,
        gtk::PositionType::Top,
        gtk::PositionType::Bottom,
    ] {
        let pad = if theme == "akiacg" { 12 } else if theme == "aero" { 8 } else { 1 };
        match edge {
            gtk::PositionType::Left => content.set_margin_start(pad),
            gtk::PositionType::Right => content.set_margin_end(pad),
            gtk::PositionType::Top => content.set_margin_top(pad),
            _ => content.set_margin_bottom(pad),
        }
    }
    let status = gtk::Label::new(None);
    add_class(&status, "menu-status");
    status.set_line_wrap(true);
    status.set_no_show_all(true);
    let user = std::env::var("USER").unwrap_or_default();
    let avatar = gtk::Image::from_icon_name(Some("avatar-default"), gtk::IconSize::Dialog);
    avatar.set_pixel_size(if theme == "aero" { 52 } else if theme == "akiacg" { 48 } else { 40 });
    add_class(&avatar, "menu-avatar");
    let search = gtk::SearchEntry::new();
    search.set_placeholder_text(Some(&text.get("请输入搜索内容或命令")));
    add_class(&search, "menu-search");
    let header = gtk::Box::new(gtk::Orientation::Horizontal, 12);
    add_class(&header, "menu-header");
    if theme != "aero" {
        header.pack_start(&avatar, false, false, 0);
        let name = gtk::Label::new(Some(&user));
        account::populate(&avatar, &name, theme == "akiacg");
        name.set_xalign(0.);
        name.set_ellipsize(gtk::pango::EllipsizeMode::End);
        name.set_max_width_chars(24);
        add_class(&name, "menu-title");
        header.pack_start(&name, theme == "xp" || theme == "akiacg", theme == "xp" || theme == "akiacg", 0);
        if theme == "akiacg" {
            let signature = gtk::Box::new(gtk::Orientation::Vertical, 3);
            let title = gtk::Label::new(Some("AkiACG"));
            title.set_xalign(1.);
            add_class(&title, "aki-signature");
            signature.pack_start(&title, false, false, 0);
            let subtitle = gtk::Label::new(Some("Community Works"));
            subtitle.set_xalign(1.);
            add_class(&subtitle, "menu-subtitle");
            signature.pack_start(&subtitle, false, false, 0);
            header.pack_end(&signature, false, false, 0);
        }
        if theme == "kde" {
            header.pack_end(&search, true, true, 0);
        }
        content.pack_start(&header, false, false, 0);
    }
    if theme == "akiacg" {
        content.pack_start(&search, false, false, 0);
    }
    let body = gtk::Box::new(gtk::Orientation::Horizontal, 0);
    add_class(&body, "menu-body");
    content.pack_start(&body, true, true, 0);
    let sidebar = gtk::Box::new(gtk::Orientation::Vertical, 2);
    add_class(&sidebar, "menu-sidebar");
    let pane = gtk::Box::new(gtk::Orientation::Vertical, 0);
    add_class(&pane, "menu-programs");
    let stack = gtk::Stack::new();
    stack.set_hhomogeneous(false);
    stack.set_vhomogeneous(false);
    stack.set_transition_type(gtk::StackTransitionType::Crossfade);
    stack.set_transition_duration(if options["tab_animations"].as_bool().unwrap_or(false) {
        150
    } else {
        0
    });
    pane.pack_start(&stack, true, true, 0);
    let home = gtk::Box::new(gtk::Orientation::Vertical, 4);
    add_class(&home, "menu-home");
    let heading = gtk::Label::new(Some(&text.get("快捷应用")));
    heading.set_xalign(0.);
    add_class(&heading, "section-title");
    home.pack_start(&heading, false, false, 0);
    let favorites = gtk::FlowBox::new();
    favorites.set_selection_mode(gtk::SelectionMode::None);
    favorites.set_homogeneous(grid_theme(theme));
    favorites.set_max_children_per_line(if theme == "akiacg" { 2 } else if theme == "kde" { 3 } else { 1 });
    favorites.set_min_children_per_line(if theme == "akiacg" { 2 } else if theme == "kde" { 3 } else { 1 });
    favorites.set_valign(gtk::Align::Start);
    home.pack_start(&favorites, false, false, 0);
    let home_scroll = scrolled(&home);
    stack.add_named(&home_scroll, "home");
    let apps = Rc::new(RefCell::new(Vec::<App>::new()));
    let query = Rc::new(RefCell::new(String::new()));
    let category = Rc::new(RefCell::new(String::new()));
    let list = gtk::ListBox::new();
    list.set_selection_mode(gtk::SelectionMode::Single);
    list.set_activate_on_single_click(true);
    let data = apps.clone();
    let q = query.clone();
    let c = category.clone();
    list.set_filter_func(Some(Box::new(move |row| {
        data.borrow()
            .get(row.index() as usize)
            .is_some_and(|app| matches(&q.borrow(), &c.borrow(), &app.searchable, &app.categories))
    })));
    let empty = gtk::Label::new(Some(&text.get("正在加载应用…")));
    list.set_placeholder(Some(&empty));
    let scroll = scrolled(&list);
    stack.add_named(&scroll, "apps");
    stack.set_visible_child_name("home");
    let side_scroll = scrolled(&sidebar);
    side_scroll.set_size_request(if theme == "kde" { 156 } else { 160 }, -1);
    if grid_theme(theme) {
        body.pack_start(&side_scroll, false, false, 0);
        body.pack_start(&pane, true, true, 0);
    } else {
        body.pack_start(&pane, true, true, 0);
        body.pack_start(&side_scroll, false, false, 0);
    }
    if grid_theme(theme) {
        let shortcuts = icon_button(&text.get("快捷应用"), "starred-symbolic");
        let s = stack.clone();
        let side = sidebar.clone();
        shortcuts.connect_clicked(move |button| {
            select_navigation(&side, button);
            s.set_visible_child_name("home");
        });
        add_class(&shortcuts, "active-category");
        sidebar.pack_start(&shortcuts, false, false, 0);
        for &(caption, key, icon) in CATEGORIES {
            let button = icon_button(&text.get(caption), icon);
            let s = stack.clone();
            let c = category.clone();
            let l = list.clone();
            let side = sidebar.clone();
            button.connect_clicked(move |button| {
                select_navigation(&side, button);
                *c.borrow_mut() = key.into();
                l.invalidate_filter();
                s.set_visible_child_name("apps");
            });
            sidebar.pack_start(&button, false, false, 0);
        }
    } else if theme == "aero" {
        sidebar.pack_start(&avatar, false, false, 4);
        let name = gtk::Label::new(Some(&user));
        account::populate(&avatar, &name, theme == "akiacg");
        add_class(&name, "menu-title");
        name.set_ellipsize(gtk::pango::EllipsizeMode::End);
        name.set_max_width_chars(18);
        sidebar.pack_start(&name, false, false, 6);
    }
    if grid_theme(theme) {
        sidebar.pack_start(
            &gtk::Separator::new(gtk::Orientation::Horizontal),
            false,
            false,
            6,
        );
    }
    let home_dir = PathBuf::from(std::env::var_os("HOME").unwrap_or_default());
    for (caption, path, icon) in [
        ("主目录", Some(home_dir.clone()), "user-home"),
        (
            "文档",
            glib::user_special_dir(glib::UserDirectory::Documents),
            "folder-documents",
        ),
        (
            "图片",
            glib::user_special_dir(glib::UserDirectory::Pictures),
            "folder-pictures",
        ),
        (
            "音乐",
            glib::user_special_dir(glib::UserDirectory::Music),
            "folder-music",
        ),
        (
            "下载",
            glib::user_special_dir(glib::UserDirectory::Downloads),
            "folder-download",
        ),
    ] {
        if grid_theme(theme) && !matches!(caption, "主目录" | "下载") {
            continue;
        }
        let Some(path) = path else { continue };
        let button = if theme == "aero" {
            gtk::Button::with_label(&text.get(caption))
        } else {
            icon_button(&text.get(caption), icon)
        };
        let a = application.clone();
        let error = status.clone();
        button.connect_clicked(move |_| {
            let uri = gio::File::for_path(&path).uri();
            match gio::AppInfo::launch_default_for_uri(&uri, None::<&gio::AppLaunchContext>) {
                Ok(()) => dismiss(&a),
                Err(e) => {
                    error.set_text(&e.to_string());
                    error.show();
                }
            }
        });
        sidebar.pack_start(&button, false, false, 0);
    }
    let all = icon_button(&text.get("全部应用"), "pan-end-symbolic");
    add_class(&all, "all-programs");
    if theme == "xp" {
        let data = apps.clone();
        let a = application.clone();
        let error = status.clone();
        let t = text.clone();
        all.connect_clicked(move |button| {
            let popup = gtk::Menu::new();
            add_class(&popup, "xp-programs");
            for &(caption, key, _) in CATEGORIES.iter().skip(1) {
                let group = gtk::MenuItem::with_label(&t.get(caption));
                let sub = gtk::Menu::new();
                add_class(&sub, "xp-programs");
                for app in data
                    .borrow()
                    .iter()
                    .filter(|app| app.categories.split(';').any(|v| v == key))
                {
                    let item = gtk::MenuItem::with_label(&app.info.display_name());
                    let info = app.info.clone();
                    let a = a.clone();
                    let error = error.clone();
                    item.connect_activate(move |_| launch(&info, &a, &error));
                    sub.append(&item);
                }
                if !sub.children().is_empty() {
                    group.set_submenu(Some(&sub));
                    popup.append(&group);
                }
            }
            let other = gtk::MenuItem::with_label(&t.get("其他应用"));
            let sub = gtk::Menu::new();
            add_class(&sub, "xp-programs");
            for app in data.borrow().iter().filter(|app| {
                !CATEGORIES
                    .iter()
                    .skip(1)
                    .any(|(_, key, _)| app.categories.split(';').any(|v| v == *key))
            }) {
                let item = gtk::MenuItem::with_label(&app.info.display_name());
                let info = app.info.clone();
                let a = a.clone();
                let error = error.clone();
                item.connect_activate(move |_| launch(&info, &a, &error));
                sub.append(&item);
            }
            if !sub.children().is_empty() {
                other.set_submenu(Some(&sub));
                popup.append(&other);
            }
            popup.set_attach_widget(Some(button));
            popup.connect_deactivate(|menu| {
                menu.detach();
                unsafe {
                    menu.destroy();
                }
            });
            popup.show_all();
            popup.popup_at_widget(
                button,
                gdk::Gravity::NorthEast,
                gdk::Gravity::SouthWest,
                gtk::current_event().as_ref(),
            );
        });
    } else {
        let s = stack.clone();
        let c = category.clone();
        let l = list.clone();
        let t = text.clone();
        all.connect_clicked(move |button| {
            let showing = s.visible_child_name().as_deref() == Some("apps");
            *c.borrow_mut() = String::new();
            l.invalidate_filter();
            s.set_visible_child_name(if showing { "home" } else { "apps" });
            if let Some(line) = button.child().and_then(|w| w.downcast::<gtk::Box>().ok()) {
                for child in line.children() {
                    if let Ok(label) = child.downcast::<gtk::Label>() {
                        label.set_text(&t.get(if showing { "全部应用" } else { "返回" }));
                    }
                }
            }
        });
    }
    if !grid_theme(theme) {
        pane.pack_start(&all, false, false, 0);
    }
    if theme == "aero" {
        pane.pack_end(&search, false, false, 0);
    }
    if theme == "xp" {
        let reveal = gtk::Revealer::new();
        reveal.add(&search);
        pane.pack_end(&reveal, false, false, 0);
        let find = icon_button(&text.get("搜索"), "system-search");
        let e = search.clone();
        find.connect_clicked(move |_| {
            reveal.set_reveal_child(true);
            e.grab_focus();
        });
        sidebar.pack_start(&find, false, false, 0);
        // Typing anywhere still reaches search, without a permanent modern search strip.
    }
    let settings = gtk::Box::new(gtk::Orientation::Vertical, 4);
    let settings_button = icon_button(&text.get("设置"), "preferences-system-symbolic");
    add_class(&settings_button, "settings-entry");
    let script = root.join("adws");
    let a = application.clone();
    let error = status.clone();
    settings_button.connect_clicked(move |_| {
        match std::process::Command::new(&script).arg("config").spawn() {
            Ok(_) => dismiss(&a),
            Err(e) => { error.set_text(&e.to_string()); error.show(); }
        }
    });
    settings.pack_start(&settings_button, false, false, 0);
    if !grid_theme(theme) {
        sidebar.pack_start(
            &gtk::Separator::new(gtk::Orientation::Horizontal),
            false,
            false,
            6,
        );
        sidebar.pack_start(&settings, false, false, 0);
    }
    content.pack_start(&status, false, false, 0);
    let footer = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    add_class(&footer, "menu-footer");
    content.pack_start(&footer, false, false, 0);
    let build = json_file(&root.join("build-info.json"));
    let version = build["display_version"].as_str().unwrap_or("").trim();
    let inscription = if version.is_empty() {
        "ADWS".to_owned()
    } else {
        format!("ADWS {version}")
    };
    let brand = gtk::Label::new(Some(&inscription));
    brand.set_ellipsize(gtk::pango::EllipsizeMode::End);
    brand.set_max_width_chars(28);
    add_class(&brand, "menu-subtitle");
    if theme == "akiacg" {
        let badge = gtk::Box::new(gtk::Orientation::Vertical, 2);
        add_class(&badge, "aki-version");
        let mark = gtk::Label::new(Some("ADWS"));
        mark.set_xalign(0.);
        add_class(&mark, "aki-version-mark");
        brand.set_text(version);
        brand.set_xalign(0.);
        badge.pack_start(&mark, false, false, 0);
        badge.pack_start(&brand, false, false, 0);
        footer.pack_start(&badge, false, false, 0);
    } else {
        footer.pack_start(&brand, false, false, 0);
    }
    if grid_theme(theme) {
        footer.pack_end(&settings, false, false, 0);
    }
    let close = icon_button(&text.get("关闭菜单"), "window-close-symbolic");
    add_class(&close, "close-entry");
    if theme == "akiacg" {
        if let Some(child) = close.child() { close.remove(&child); }
        close.add(&gtk::Image::from_icon_name(Some("window-close-symbolic"), gtk::IconSize::Button));
        close.set_tooltip_text(Some(&text.get("关闭菜单")));
        if let Some(accessible) = close.accessible() { accessible.set_name(&text.get("关闭菜单")); }
    }
    let a = application.clone();
    close.connect_clicked(move |_| dismiss(&a));
    footer.pack_end(&close, false, false, 0);
    let power = power::PowerMenu::new(&menu_pages, &footer, &text);
    power.connect(application, &window);
    menu_pages.set_visible_child_name("launcher");
    let q = query.clone();
    let c = category.clone();
    let l = list.clone();
    let s = stack.clone();
    search.connect_search_changed(move |e| {
        *q.borrow_mut() = e.text().to_lowercase();
        *c.borrow_mut() = String::new();
        l.invalidate_filter();
        s.set_visible_child_name(if e.text().is_empty() { "home" } else { "apps" });
    });
    let data = apps.clone();
    let a = application.clone();
    let error = status.clone();
    list.connect_row_activated(move |_, row| {
        if let Some(app) = data.borrow().get(row.index() as usize) {
            launch(&app.info, &a, &error);
        }
    });
    let motion_busy = Rc::new(std::cell::Cell::new(false));
    load_catalog(
        &list,
        &favorites,
        &apps,
        theme,
        application,
        &status,
        &empty,
        &text,
        motion_busy.clone(),
    );
    let a = application.clone();
    let error = status.clone();
    let t = text.clone();
    search.connect_activate(move |entry| {
        if let Err(message) = run_command(entry.text().as_str()) {
            error.set_text(&format!("{} {message}", t.get("命令启动失败：")));
            error.show();
        } else if !entry.text().trim().is_empty() {
            dismiss(&a);
        }
    });
    let a = application.clone();
    let entry = search.clone();
    let power_keys = power.clone();
    window.connect_key_press_event(move |_, event| {
        if power_keys.active() {
            if event.keyval() == gdk::keys::constants::Escape {
                power_keys.back();
                return glib::Propagation::Stop;
            }
            return glib::Propagation::Proceed;
        }
        if event.keyval() == gdk::keys::constants::Escape {
            dismiss(&a);
            glib::Propagation::Stop
        } else if !entry.has_focus()
            && !event
                .state()
                .intersects(gdk::ModifierType::CONTROL_MASK | gdk::ModifierType::MOD1_MASK)
        {
            if let Some(ch) = event.keyval().to_unicode().filter(|c| !c.is_control()) {
                if let Some(parent) = entry
                    .parent()
                    .and_then(|w| w.downcast::<gtk::Revealer>().ok())
                {
                    parent.set_reveal_child(true);
                }
                entry.grab_focus();
                entry.set_text(&format!("{}{ch}", entry.text()));
                entry.set_position(-1);
                glib::Propagation::Stop
            } else {
                glib::Propagation::Proceed
            }
        } else {
            glib::Propagation::Proceed
        }
    });
    let focus_list = list.clone();
    search.connect_key_press_event(move |_, event| {
        if event.keyval() == gdk::keys::constants::Down {
            if let Some(row) = focus_list
                .children()
                .iter()
                .filter_map(|w| w.clone().downcast::<gtk::ListBoxRow>().ok())
                .find(|r| r.is_child_visible())
            {
                focus_list.select_row(Some(&row));
                row.grab_focus();
            }
            glib::Propagation::Stop
        } else {
            glib::Propagation::Proceed
        }
    });
    let providers = Rc::new(RefCell::new(None::<gtk::CssProvider>));
    let last = Rc::new(RefCell::new(String::new()));
    let screen = gtk::prelude::GtkWindowExt::screen(&window).expect("GTK screen");
    let root = root.to_path_buf();
    let xp_theme = theme == "xp";
    let theme = theme.to_string();
    let custom = custom.map(Path::to_path_buf);
    let seen_palette = RefCell::new(config_home().join("waybar/colors.css").exists());
    let last_error = RefCell::new(String::new());
    let cleanup_providers = providers.clone();
    let reload = Rc::new(move || {
        let palette_exists = config_home().join("waybar/colors.css").exists();
        if *seen_palette.borrow() && !palette_exists {
            return;
        }
        if palette_exists {
            *seen_palette.borrow_mut() = true;
        }
        let source = match stylesheet(&root, &theme, custom.as_deref()) {
            Ok(s) => s,
            Err(e) => {
                if *last_error.borrow() != e {
                    eprintln!("Start menu CSS: {e}");
                    *last_error.borrow_mut() = e;
                }
                if last.borrow().is_empty() {
                    stylesheet(&root, &theme, None).unwrap_or_default()
                } else {
                    return;
                }
            }
        };
        if *last.borrow() == source {
            return;
        }
        let provider = gtk::CssProvider::new();
        if let Err(e) = provider.load_from_data(source.as_bytes()) {
            let detail = e.to_string();
            if *last_error.borrow() != detail {
                eprintln!("Start menu CSS: {detail}");
                *last_error.borrow_mut() = detail;
            }
            if !last.borrow().is_empty() {
                return;
            }
            let Ok(fallback) = stylesheet(&root, &theme, None) else {
                return;
            };
            if provider.load_from_data(fallback.as_bytes()).is_err() {
                return;
            }
            // Keep retrying invalid user CSS, but retain a usable preset meanwhile.
        }
        gtk::StyleContext::add_provider_for_screen(
            &screen,
            &provider,
            gtk::STYLE_PROVIDER_PRIORITY_USER + 1,
        );
        if let Some(old) = providers.borrow_mut().replace(provider) {
            gtk::StyleContext::remove_provider_for_screen(&screen, &old);
        }
        *last.borrow_mut() = source;
    });
    timing("widgets constructed");
    reload();
    timing("styles loaded");
    let palette_window = window.downgrade();
    let reload_tick = reload.clone();
    let palette_source = Rc::new(RefCell::new(Some(glib::timeout_add_local(Duration::from_millis(750), move || {
        if let Some(window) = palette_window.upgrade() {
            if window.is_visible() { reload_tick(); }
            glib::ControlFlow::Continue
        } else { glib::ControlFlow::Break }
    }))));
    let cleanup = palette_source.clone();
    window.connect_destroy(move |window| {
        if let Some(source) = cleanup.borrow_mut().take() { source.remove(); }
        if let Some(provider) = cleanup_providers.borrow_mut().take() {
            if let Some(screen) = gtk::prelude::GtkWindowExt::screen(window) { gtk::StyleContext::remove_provider_for_screen(&screen, &provider); }
        }
    });
    if !layered && smoke.is_none() {
        let a = application.clone();
        let power = power.clone();
        window.connect_focus_out_event(move |_, _| {
            if !power.busy() {
                dismiss(&a);
            }
            glib::Propagation::Proceed
        });
    }
    let motion = Rc::new(Motion {
        menu: menu.clone(),
        stage: stage.clone(),
        window: window.clone(),
        backdrop: backdrop.clone(),
        one_shot,
        hidden_at: std::cell::Cell::new(std::time::Instant::now()),
        application: application.clone(),
        edge: options["position"].as_str().unwrap_or("bottom").into(),
        duration: if options["window_animations"].as_bool().unwrap_or(false)
            && gtk::Settings::default().is_none_or(|s| s.is_gtk_enable_animations())
        {
            options["animation_duration"]
                .as_u64()
                .unwrap_or(280)
                .clamp(80, 1000) as f64
                * 1000.
        } else {
            0.
        },
        progress: std::cell::Cell::new(0.),
        tick: RefCell::new(None),
        deadline: RefCell::new(None),
        snapshot: RefCell::new(None),
        busy: motion_busy,
        closing: std::cell::Cell::new(false),
    });
    motion.bind();
    let close = motion.clone();
    CLOSE.with(|slot| {
        slot.replace(Some(Rc::new(move || {
            if !close.closing.replace(true) {
                close.menu.set_sensitive(false);
                close.animate(0.);
            }
        })))
    });
    if smoke.is_some() {
        window.connect_map(move |_| {
            eprintln!(
                "Start menu mapped after {} ms",
                started.elapsed().as_millis()
            )
        });
    }
    window.connect_map(|_| timing("window mapped"));
    let drawn = std::cell::Cell::new(false);
    window.connect_draw(move |_, _| {
        if !drawn.replace(true) { timing("first draw"); }
        glib::Propagation::Proceed
    });
    motion.set(0.);
    if let Some(backdrop) = &backdrop { backdrop.show_all(); }
    window.show_all();
    motion.animate(1.);
    if !xp_theme {
        search.grab_focus();
    }
    if let Some(path) = smoke {
        let path = path.to_path_buf();
        let w = window.clone();
        let a = application.clone();
        let list = list.clone();
        let search = search.clone();
        glib::timeout_add_local_once(Duration::from_millis(700), move || {
            assert!(!list.children().is_empty(), "No applications in smoke test");
            search.set_text("adws-test-no-such-application-9201783");
            search.emit_by_name::<()>("search-changed", &[]);
            assert!(
                list.children().iter().all(|w| !w.is_child_visible()),
                "Search did not filter rows"
            );
            search.set_text("");
            search.emit_by_name::<()>("search-changed", &[]);
            assert!(
                list.children().iter().any(|w| w.is_child_visible()),
                "Search did not restore rows"
            );
            println!(
                "Menu search/restore passed; layer_surface={layered}; theme={}",
                w.title().unwrap_or_default()
            );
            glib::timeout_add_local_once(Duration::from_millis(250), move || {
                w.check_resize();
                assert!(
                    w.is_mapped() && w.allocated_width() > 100 && w.allocated_height() > 100,
                    "Menu layer did not receive a usable allocation"
                );
                let surface = gtk::cairo::ImageSurface::create(
                    gtk::cairo::Format::ARgb32,
                    w.allocated_width(),
                    w.allocated_height(),
                )
                .unwrap();
                w.draw(&gtk::cairo::Context::new(&surface).unwrap());
                surface
                    .write_to_png(&mut std::fs::File::create(path).unwrap())
                    .unwrap();
                a.quit();
            });
        });
    }
    CachedMenu { window, motion, search, pages: menu_pages, power,
                 width, height, layered, xp: xp_theme, reload, home: stack, category, list }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    #[ignore = "requires an isolated GTK display"]
    fn motion_reverses_without_resizing_the_input_surface() {
        gtk::init().unwrap();
        let app = gtk::Application::new(None, gio::ApplicationFlags::NON_UNIQUE);
        app.register(None::<&gio::Cancellable>).unwrap();
        let window = gtk::ApplicationWindow::new(&app);
        window.set_default_size(400, 300);
        let stage = gtk::Box::new(gtk::Orientation::Vertical, 0);
        window.add(&stage);
        let menu = gtk::EventBox::new();
        let label = gtk::Label::new(Some("Motion"));
        menu.add(&label);
        stage.pack_start(&menu, true, true, 0);
        let allocations = Rc::new(std::cell::Cell::new(0));
        let counted = allocations.clone();
        menu.connect_size_allocate(move |_, _| counted.set(counted.get() + 1));
        let motion = Rc::new(Motion {
            menu,
            stage: stage.clone(),
            window: window.clone(),
            backdrop: None,
            one_shot: true,
            hidden_at: std::cell::Cell::new(std::time::Instant::now()),
            application: app,
            edge: "bottom".into(),
            duration: 200_000.,
            progress: std::cell::Cell::new(0.),
            tick: RefCell::new(None),
            deadline: RefCell::new(None),
            snapshot: RefCell::new(None),
            busy: Rc::new(std::cell::Cell::new(false)),
            closing: std::cell::Cell::new(false),
        });
        motion.bind();
        fn drain(ms: u64) {
            let start = std::time::Instant::now();
            while start.elapsed() < Duration::from_millis(ms) {
                while gtk::events_pending() {
                    gtk::main_iteration();
                }
                std::thread::sleep(Duration::from_millis(1));
            }
        }
        motion.set(0.);
        window.show_all();
        drain(30);
        let size = window.size();
        allocations.set(0);
        motion.animate(1.);
        drain(95);
        assert!(motion.progress.get() > 0. && motion.progress.get() < 1.);
        // Capture must contain actual menu pixels, remain the same buffer over
        // successive frames and not invoke another widget-tree allocation.
        let image = gtk::cairo::ImageSurface::create(gtk::cairo::Format::ARgb32, 400, 300).unwrap();
        let cr = gtk::cairo::Context::new(&image).unwrap();
        stage.draw(&cr);
        let cached = motion.snapshot.borrow().as_ref().unwrap().1.clone();
        let mut png = Vec::new();
        cached.write_to_png(&mut png).unwrap();
        let mut pixels = gtk::cairo::ImageSurface::create_from_png(&mut std::io::Cursor::new(png)).unwrap();
        assert!(pixels.data().unwrap().iter().any(|byte| *byte != 0), "blank animation snapshot");
        stage.draw(&cr);
        assert_eq!(motion.snapshot.borrow().as_ref().unwrap().1.to_raw_none(), cached.to_raw_none());
        assert_eq!(window.size(), size);
        assert_eq!(motion.menu.margin_top() + motion.menu.margin_bottom(), 16);
        motion.animate(0.);
        drain(20);
        motion.animate(1.);
        drain(250);
        assert_eq!(motion.progress.get(), 1.);
        assert!(motion.tick.borrow().is_none());
        assert!(motion.deadline.borrow().is_none());
        assert!(motion.snapshot.borrow().is_none(), "snapshot retained after animation");
        assert_eq!(allocations.get(), 0, "motion triggered widget reallocation");
        assert_eq!(window.size(), size);
        // Fresh content must be rendered after completion, not an old snapshot.
        label.set_text("Changed after animation");
        drain(30);
        allocations.set(0);
        for _ in 0..8 {
            motion.set(0.5);
            stage.draw(&cr);
            assert!(motion.snapshot.borrow().is_some());
            motion.set(1.);
            assert!(motion.snapshot.borrow().is_none());
        }
        assert_eq!(allocations.get(), 0);
        // Exercise the no-frame deadline by explicitly suppressing the tick.
        motion.animate(0.);
        motion.tick.borrow_mut().take().unwrap().remove();
        drain(310);
        assert_eq!(motion.progress.get(), 0.);
        assert!(motion.deadline.borrow().is_none());
        unsafe {
            window.destroy();
        }
    }
    #[test]
    #[ignore = "requires an isolated GTK display, or a temporary Wayland session"]
    fn themed_motion_reopens_and_releases_buffers() {
        gtk::init().unwrap();
        let app = gtk::Application::new(None, gio::ApplicationFlags::NON_UNIQUE);
        app.register(None::<&gio::Cancellable>).unwrap();
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().parent().unwrap();
        let options = serde_json::json!({"window_animations":true,"animation_duration":280,"position":"bottom"});
        let menu = build(&app, root, "akiacg", None, &options, None,
            MenuPlacement { layer_probe:true, anchor:None, one_shot:false });
        fn isolate_input(menu: &CachedMenu) {
            if menu.layered {
                unsafe { gtk_layer_set_keyboard_mode(menu.window.upcast_ref::<gtk::Window>().to_glib_none().0, 0); }
                // A real-session performance probe must not consume typing or
                // be dismissed by unrelated clicks while it is measuring.
                if let Some(backdrop) = &menu.motion.backdrop { backdrop.set_sensitive(false); }
            }
        }
        isolate_input(&menu);
        fn run_for(ms: u64) {
            let main = glib::MainLoop::new(None, false);
            let quit = main.clone();
            glib::timeout_add_local_once(Duration::from_millis(ms), move || quit.quit());
            main.run();
        }
        run_for(700);
        for _ in 0..3 {
            assert_eq!(menu.motion.progress.get(), 1.);
            assert!(!menu.motion.busy.get());
            assert!(menu.motion.snapshot.borrow().is_none());
            dismiss(&app);
            run_for(420);
            assert!(!menu.window.is_visible());
            assert!(menu.motion.backdrop.as_ref().is_none_or(|w| !w.is_visible()));
            assert!(menu.motion.snapshot.borrow().is_none());
            assert!(menu.motion.tick.borrow().is_none());
            assert!(menu.motion.deadline.borrow().is_none());
            menu.reopen(None);
            isolate_input(&menu);
            run_for(420);
        }
        if let Some(backdrop) = &menu.motion.backdrop {
            assert!(backdrop.is_visible());
            assert!(menu.window.allocated_width() < backdrop.allocated_width(), "animated surface still spans the monitor");
            let child = backdrop.child().unwrap();
            let event = gdk::Event::new(gdk::EventType::ButtonPress);
            child.emit_by_name::<bool>("button-press-event", &[&event]);
            run_for(420);
            assert!(!menu.window.is_visible() && !backdrop.is_visible(), "outside click left an input surface mapped");
            menu.reopen(None);
            isolate_input(&menu);
            run_for(420);
            menu.window.hide();
            assert!(!backdrop.is_visible(), "power-action hide left a catcher behind");
            menu.window.show_all();
            assert!(backdrop.is_visible(), "failed power action did not restore the catcher");
        }
        unsafe { menu.window.destroy(); }
        CLOSE.with(|slot| { slot.borrow_mut().take(); });
        assert!(menu.motion.snapshot.borrow().is_none());
        assert!(menu.motion.deadline.borrow().is_none());
    }
    #[test]
    fn search_and_categories() {
        assert!(matches(
            "browser fox",
            "Network",
            "firefox browser",
            "Network;WebBrowser;"
        ));
        assert!(!matches("fox", "Office", "firefox", "Network;"));
        assert!(!matches("missing", "", "firefox", ""));
    }
    #[test]
    fn anchor_placement_all_edges() {
        for (edge, expected) in [
            ("bottom", (400, 132)),
            ("top", (400, 378)),
            ("left", (458, 340)),
            ("right", (92, 340)),
        ] {
            let anchor = serde_json::json!({"x":400,"y":340,"w":50,"h":30,"edge":edge});
            assert_eq!(menu_origin(&anchor, 300, 200, 1920, 1080), expected);
        }
        let anchor = serde_json::json!({"x":1900,"y":20,"edge":"bottom"});
        assert_eq!(menu_origin(&anchor, 600, 560, 1920, 1080), (1320, 0));
    }
    #[test]
    fn known_theme_only() {
        assert_eq!(theme_name("../../x"), "kde");
        assert_eq!(theme_name("xp"), "xp");
        assert_eq!(theme_name("akiacg"), "akiacg");
        assert!(grid_theme("akiacg"));
        assert!(!grid_theme("aero"));
    }
}

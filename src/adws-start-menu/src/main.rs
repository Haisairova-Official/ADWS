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

#[link(name = "gtk-layer-shell")]
extern "C" {
    fn gtk_layer_is_supported() -> i32;
    fn gtk_layer_init_for_window(window: *mut gtk::ffi::GtkWindow);
    fn gtk_layer_set_monitor(window: *mut gtk::ffi::GtkWindow, monitor: *mut gdk::ffi::GdkMonitor);
    fn gtk_layer_set_layer(window: *mut gtk::ffi::GtkWindow, layer: i32);
    fn gtk_layer_set_anchor(window: *mut gtk::ffi::GtkWindow, edge: i32, anchor: i32);
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
        "aero" | "xp" => value,
        _ => "kde",
    }
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
    application: gtk::Application,
    edge: String,
    duration: f64,
    progress: std::cell::Cell<f64>,
    tick: RefCell<Option<gtk::TickCallbackId>>,
    closing: std::cell::Cell<bool>,
}
impl Motion {
    fn set(&self, value: f64) {
        self.progress.set(value);
        self.menu.set_opacity(value);
        let offset = ((1. - value) * 8.).round() as i32;
        let (x, y) = match self.edge.as_str() {
            "top" => (0, -offset),
            "left" => (-offset, 0),
            "right" => (offset, 0),
            _ => (0, offset),
        };
        self.menu.set_margin_start(8 + x);
        self.menu.set_margin_end(8 - x);
        self.menu.set_margin_top(8 + y);
        self.menu.set_margin_bottom(8 - y);
    }
    fn animate(self: &Rc<Self>, target: f64) {
        if let Some(tick) = self.tick.borrow_mut().take() {
            tick.remove();
        }
        if self.duration <= 0. {
            self.set(target);
            if target == 0. {
                self.application.quit();
            }
            return;
        }
        let from = self.progress.get();
        let start = std::cell::Cell::new(None::<i64>);
        let weak = Rc::downgrade(self);
        let tick = self.menu.add_tick_callback(move |_, clock| {
            let Some(this) = weak.upgrade() else {
                return glib::ControlFlow::Break;
            };
            let now = clock.frame_time();
            let began = start.get().unwrap_or_else(|| {
                start.set(Some(now));
                now
            });
            let t = ((now - began) as f64 / (this.duration * (target - from).abs().max(0.01)))
                .clamp(0., 1.);
            this.set(from + (target - from) * t * t * (3. - 2. * t));
            if t >= 1. {
                this.tick.borrow_mut().take();
                if target == 0. {
                    this.application.quit();
                }
                glib::ControlFlow::Break
            } else {
                glib::ControlFlow::Continue
            }
        });
        self.tick.replace(Some(tick));
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
) {
    let (send, recv) = std::sync::mpsc::sync_channel(1);
    std::thread::spawn(move || {
        let records: Vec<_> = applications()
            .into_iter()
            .filter_map(|app| {
                let desktop = app.info.downcast::<gio::DesktopAppInfo>().ok()?;
                Some((desktop.filename()?, app.searchable, app.categories))
            })
            .collect();
        let _ = send.send(records);
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
                Ok(data) => pending = Some(data.into()),
                Err(std::sync::mpsc::TryRecvError::Empty) => return glib::ControlFlow::Continue,
                Err(_) => {
                    empty.set_text(&text.get("没有匹配的应用程序"));
                    return glib::ControlFlow::Break;
                }
            }
        }
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
        let pins = json_file(&config_home().join("adws/taskbar-pins.json"));
        let pinned: Vec<_> = pins["apps"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|v| v["desktop_id"].as_str())
            .collect();
        let data = apps.borrow();
        let mut featured: Vec<_> = data.iter().enumerate().collect();
        // User pins first, then common launchers, then alphabetical fallback.
        featured.sort_by_key(|(i, app)| {
            (
                pinned
                    .iter()
                    .position(|id| app.info.id().as_deref() == Some(*id))
                    .unwrap_or(usize::MAX),
                !app.categories.split(';').any(|v| {
                    matches!(
                        v,
                        "WebBrowser" | "FileManager" | "TerminalEmulator" | "TextEditor"
                    )
                }),
                *i,
            )
        });
        for (_, app) in featured
            .into_iter()
            .take(if theme == "kde" { 9 } else { 8 })
        {
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
                &app_image(&app.info, if theme == "kde" { 40 } else { 32 }),
                false,
                false,
                0,
            );
            let label = gtk::Label::new(Some(&app.info.display_name()));
            label.set_ellipsize(gtk::pango::EllipsizeMode::End);
            label.set_max_width_chars(if theme == "kde" { 15 } else { 24 });
            label.set_xalign(if theme == "kde" { 0.5 } else { 0. });
            line.pack_start(&label, true, true, 0);
            button.add(&line);
            let info = app.info.clone();
            let a = application.clone();
            let error = status.clone();
            button.connect_clicked(move |_| launch(&info, &a, &error));
            favorites.insert(&button, -1);
        }
        favorites.show_all();
        glib::ControlFlow::Break
    });
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

fn account_widgets(avatar: &gtk::Image, name: &gtk::Label) {
    let login = glib::user_name().to_string_lossy().into_owned();
    let home = PathBuf::from(std::env::var_os("HOME").unwrap_or_default());
    let size = avatar.pixel_size();
    let set_avatar = |path: &Path| {
        if let Ok(pixbuf) = gtk::gdk_pixbuf::Pixbuf::from_file_at_scale(path, size, size, true) {
            avatar.set_from_pixbuf(Some(&pixbuf));
            true
        } else {
            false
        }
    };
    for path in [
        home.join(".face"),
        home.join(".face.icon"),
        PathBuf::from("/var/lib/AccountsService/icons").join(&login),
    ] {
        if path.is_file() && set_avatar(&path) {
            break;
        }
    }
    let avatar = avatar.downgrade();
    let name = name.downgrade();
    glib::MainContext::default().spawn_local(async move {
        let Ok(bus) = gio::bus_get_future(gio::BusType::System).await else {
            return;
        };
        let Ok(reply) = bus
            .call_future(
                Some("org.freedesktop.Accounts"),
                "/org/freedesktop/Accounts",
                "org.freedesktop.Accounts",
                "FindUserByName",
                Some(&(login,).to_variant()),
                None,
                gio::DBusCallFlags::NONE,
                1000,
            )
            .await
        else {
            return;
        };
        let Some((path,)) = reply.get::<(glib::variant::ObjectPath,)>() else {
            return;
        };
        let Ok(reply) = bus
            .call_future(
                Some("org.freedesktop.Accounts"),
                &path,
                "org.freedesktop.DBus.Properties",
                "GetAll",
                Some(&("org.freedesktop.Accounts.User",).to_variant()),
                None,
                gio::DBusCallFlags::NONE,
                1000,
            )
            .await
        else {
            return;
        };
        let Some((props,)) = reply.get::<(std::collections::HashMap<String, glib::Variant>,)>()
        else {
            return;
        };
        if let Some(real) = props
            .get("RealName")
            .and_then(|v| v.str())
            .filter(|s| !s.trim().is_empty())
        {
            if let Some(label) = name.upgrade() {
                label.set_text(real);
            }
        }
        if let Some(path) = props
            .get("IconFile")
            .and_then(|v| v.str())
            .filter(|s| !s.is_empty())
        {
            if let (Some(image), Ok(pixbuf)) = (
                avatar.upgrade(),
                gtk::gdk_pixbuf::Pixbuf::from_file_at_scale(path, size, size, true),
            ) {
                image.set_from_pixbuf(Some(&pixbuf));
            }
        }
    });
}

fn main() {
    let args: Vec<_> = std::env::args().collect();
    if args.iter().any(|s| s == "--help" || s == "-h") {
        println!("adws-start-menu --root PATH [--theme kde|aero|xp] [--css PATH]");
        return;
    }
    let value = |name: &str| {
        args.iter()
            .position(|s| s == name)
            .and_then(|i| args.get(i + 1))
            .cloned()
    };
    let Some(root) = value("--root").map(PathBuf::from) else {
        eprintln!("Missing --root");
        std::process::exit(2);
    };
    let layout = json_file(&config_home().join("adws/taskbar-layout.json"));
    let options = &layout["options"];
    let chosen = value("--theme")
        .unwrap_or_else(|| options["start_menu_theme"].as_str().unwrap_or("kde").into());
    let theme = theme_name(&chosen).to_string();
    let custom = match value("--css") {
        Some(path) => (!path.is_empty()).then(|| PathBuf::from(path)),
        None => options["start_menu_css"]
            .as_str()
            .filter(|s| !s.is_empty())
            .map(PathBuf::from),
    };
    let smoke = value("--smoke-test").map(PathBuf::from);
    if !chinese() {
        std::env::set_var("LANGUAGE", "en");
    }
    let layer_probe = args.iter().any(|s| s == "--check-wayland");
    let flags = if smoke.is_some() {
        gio::ApplicationFlags::NON_UNIQUE
    } else {
        gio::ApplicationFlags::empty()
    };
    let app = gtk::Application::new(Some("org.ADWS.StartMenu"), flags);
    app.connect_activate(move |application| {
        if !application.windows().is_empty() {
            dismiss(application);
            return;
        }
        build(
            application,
            &root,
            &theme,
            custom.as_deref(),
            &options_owned(&layout),
            smoke.as_deref(),
            layer_probe,
        );
    });
    app.run_with_args(&["adws-start-menu"]);
}
fn options_owned(layout: &Value) -> Value {
    layout["options"].clone()
}
fn build(
    application: &gtk::Application,
    root: &Path,
    theme: &str,
    custom: Option<&Path>,
    options: &Value,
    smoke: Option<&Path>,
    layer_probe: bool,
) {
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
    let anchor = std::env::var("ADWS_START_ANCHOR")
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok());
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
                if theme == "kde" {
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
        .map(|g| (g.width() - 40).clamp(300, if theme == "kde" { 680 } else { 500 }))
        .unwrap_or(600);
    if layered {
        // GtkOverlay excludes overlay children from its natural size. A zero-size
        // main child otherwise leaves the layer surface at 1x1 before configure.
        window.set_resizable(true);
        if let Some(area) = geometry.as_ref() {
            window.set_default_size(area.width(), area.height());
        }
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
            for edge in 0..4 {
                gtk_layer_set_anchor(ptr, edge, 1);
            }
        }
    } else {
        window.set_default_size(width, height);
        window.set_position(gtk::WindowPosition::Center);
        window.set_keep_above(true);
    }
    let overlay = gtk::Overlay::new();
    window.add(&overlay);
    let background = gtk::EventBox::new();
    background.set_visible_window(false);
    overlay.add(&background);
    let app = application.clone();
    background.connect_button_press_event(move |_, _| {
        dismiss(&app);
        glib::Propagation::Stop
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
        stage.set_halign(if position == "right" {
            gtk::Align::End
        } else {
            gtk::Align::Start
        });
        stage.set_valign(if position == "bottom" {
            gtk::Align::End
        } else {
            gtk::Align::Start
        });
        stage.set_margin_start(if position == "left" { margin } else { 12 });
        stage.set_margin_end(if position == "right" { margin } else { 12 });
        stage.set_margin_top(if position == "top" { margin } else { 12 });
        stage.set_margin_bottom(if position == "bottom" { margin } else { 12 });
        if let (Some(anchor), Some(area)) = (anchor.as_ref(), geometry.as_ref()) {
            let (x, y) = menu_origin(anchor, width, height, area.width(), area.height());
            stage.set_halign(gtk::Align::Start);
            stage.set_valign(gtk::Align::Start);
            stage.set_margin_start(x);
            stage.set_margin_top(y);
            stage.set_margin_end(0);
            stage.set_margin_bottom(0);
        }
    }
    overlay.add_overlay(&stage);
    let content = gtk::Box::new(gtk::Orientation::Vertical, 0);
    menu.add(&content);
    for edge in [
        gtk::PositionType::Left,
        gtk::PositionType::Right,
        gtk::PositionType::Top,
        gtk::PositionType::Bottom,
    ] {
        let pad = if theme == "aero" { 8 } else { 1 };
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
    let user = glib::real_name().to_string_lossy().into_owned();
    let user = if user.is_empty() || user == "Unknown" {
        glib::user_name().to_string_lossy().into_owned()
    } else {
        user
    };
    let avatar = gtk::Image::from_icon_name(Some("avatar-default"), gtk::IconSize::Dialog);
    avatar.set_pixel_size(if theme == "aero" { 52 } else { 40 });
    add_class(&avatar, "menu-avatar");
    let search = gtk::SearchEntry::new();
    search.set_placeholder_text(Some(&text.get("搜索应用程序…")));
    add_class(&search, "menu-search");
    let header = gtk::Box::new(gtk::Orientation::Horizontal, 12);
    add_class(&header, "menu-header");
    if theme != "aero" {
        header.pack_start(&avatar, false, false, 0);
        let name = gtk::Label::new(Some(&user));
        account_widgets(&avatar, &name);
        name.set_xalign(0.);
        add_class(&name, "menu-title");
        header.pack_start(&name, theme == "xp", theme == "xp", 0);
        if theme == "kde" {
            header.pack_end(&search, true, true, 0);
        }
        content.pack_start(&header, false, false, 0);
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
    favorites.set_homogeneous(theme == "kde");
    favorites.set_max_children_per_line(if theme == "kde" { 3 } else { 1 });
    favorites.set_min_children_per_line(if theme == "kde" { 3 } else { 1 });
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
    if theme == "kde" {
        body.pack_start(&side_scroll, false, false, 0);
        body.pack_start(&pane, true, true, 0);
    } else {
        body.pack_start(&pane, true, true, 0);
        body.pack_start(&side_scroll, false, false, 0);
    }
    if theme == "kde" {
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
        account_widgets(&avatar, &name);
        add_class(&name, "menu-title");
        name.set_ellipsize(gtk::pango::EllipsizeMode::End);
        name.set_max_width_chars(18);
        sidebar.pack_start(&name, false, false, 6);
    }
    if theme == "kde" {
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
        if theme == "kde" && !matches!(caption, "主目录" | "下载") {
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
    if theme != "kde" {
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
    let settings = icon_button(&text.get("桌面设置"), "preferences-system");
    let script = root.join("adws");
    let a = application.clone();
    let error = status.clone();
    settings.connect_clicked(move |_| {
        match std::process::Command::new(&script).arg("config").spawn() {
            Ok(_) => dismiss(&a),
            Err(e) => {
                error.set_text(&e.to_string());
                error.show();
            }
        }
    });
    if theme != "kde" {
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
    let brand = gtk::Label::new(Some("ADWS"));
    add_class(&brand, "menu-subtitle");
    footer.pack_start(&brand, false, false, 0);
    if theme == "kde" {
        footer.pack_end(&settings, false, false, 0);
    }
    let close = icon_button(&text.get("关闭"), "window-close-symbolic");
    let a = application.clone();
    close.connect_clicked(move |_| dismiss(&a));
    footer.pack_end(&close, false, false, 0);
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
    load_catalog(
        &list,
        &favorites,
        &apps,
        theme,
        application,
        &status,
        &empty,
        &text,
    );
    let l = list.clone();
    search.connect_activate(move |_| {
        if let Some(row) = l
            .children()
            .iter()
            .filter_map(|w| w.clone().downcast::<gtk::ListBoxRow>().ok())
            .find(|r| r.is_child_visible())
        {
            l.emit_by_name::<()>("row-activated", &[&row]);
        }
    });
    let a = application.clone();
    let entry = search.clone();
    window.connect_key_press_event(move |_, event| {
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
    let reload = move || {
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
    };
    reload();
    glib::timeout_add_local(Duration::from_millis(750), move || {
        reload();
        glib::ControlFlow::Continue
    });
    if !layered && smoke.is_none() {
        let a = application.clone();
        window.connect_focus_out_event(move |_, _| {
            dismiss(&a);
            glib::Propagation::Proceed
        });
    }
    let motion = Rc::new(Motion {
        menu: menu.clone(),
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
        closing: std::cell::Cell::new(false),
    });
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
    motion.set(0.);
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
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    #[ignore = "requires an isolated GTK display"]
    fn motion_reverses_without_resizing_the_input_surface() {
        gtk::init().unwrap();
        let app = gtk::Application::new(None, gio::ApplicationFlags::NON_UNIQUE);
        let window = gtk::Window::new(gtk::WindowType::Toplevel);
        window.set_default_size(400, 300);
        let stage = gtk::Box::new(gtk::Orientation::Vertical, 0);
        window.add(&stage);
        let menu = gtk::EventBox::new();
        menu.add(&gtk::Label::new(Some("Motion")));
        stage.pack_start(&menu, true, true, 0);
        let motion = Rc::new(Motion {
            menu,
            application: app,
            edge: "bottom".into(),
            duration: 200_000.,
            progress: std::cell::Cell::new(0.),
            tick: RefCell::new(None),
            closing: std::cell::Cell::new(false),
        });
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
        motion.animate(1.);
        drain(95);
        assert!(motion.progress.get() > 0. && motion.progress.get() < 1.);
        assert_eq!(window.size(), size);
        assert_eq!(motion.menu.margin_top() + motion.menu.margin_bottom(), 16);
        motion.animate(0.);
        drain(20);
        motion.animate(1.);
        drain(250);
        assert_eq!(motion.progress.get(), 1.);
        assert!(motion.tick.borrow().is_none());
        assert_eq!(window.size(), size);
        unsafe {
            window.destroy();
        }
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
    }
}

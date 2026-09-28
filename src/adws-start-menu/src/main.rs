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
            application.quit();
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
        .map(|g| (g.height() - 120).clamp(180, 560))
        .unwrap_or(520);
    let width = geometry
        .as_ref()
        .map(|g| (g.width() - 40).clamp(300, 600))
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
        app.quit();
        glib::Propagation::Stop
    });
    let menu = gtk::EventBox::new();
    add_class(&menu, "adws-start-menu");
    add_class(&menu, theme);
    menu.connect_button_press_event(|_, _| glib::Propagation::Stop);
    menu.set_size_request(width, height);
    if layered {
        let position = options["position"].as_str().unwrap_or("bottom");
        let margin = (options["thickness"].as_i64().unwrap_or(36).clamp(20, 160) + 16) as i32;
        menu.set_halign(if position == "right" {
            gtk::Align::End
        } else {
            gtk::Align::Start
        });
        menu.set_valign(if position == "bottom" {
            gtk::Align::End
        } else {
            gtk::Align::Start
        });
        menu.set_margin_start(if position == "left" { margin } else { 12 });
        menu.set_margin_end(if position == "right" { margin } else { 12 });
        menu.set_margin_top(if position == "top" { margin } else { 12 });
        menu.set_margin_bottom(if position == "bottom" { margin } else { 12 });
        if let (Some(anchor), Some(area)) = (anchor.as_ref(), geometry.as_ref()) {
            let (x, y) = menu_origin(anchor, width, height, area.width(), area.height());
            menu.set_halign(gtk::Align::Start);
            menu.set_valign(gtk::Align::Start);
            menu.set_margin_start(x);
            menu.set_margin_top(y);
            menu.set_margin_end(0);
            menu.set_margin_bottom(0);
        }
    }
    overlay.add_overlay(&menu);
    let content = gtk::Box::new(gtk::Orientation::Vertical, 0);
    menu.add(&content);
    let header = gtk::Box::new(gtk::Orientation::Horizontal, 12);
    add_class(&header, "menu-header");
    header.pack_start(
        &gtk::Image::from_icon_name(Some("avatar-default-symbolic"), gtk::IconSize::Dialog),
        false,
        false,
        0,
    );
    let titles = gtk::Box::new(gtk::Orientation::Vertical, 3);
    let title = gtk::Label::new(Some(&text.get("应用程序")));
    title.set_xalign(0.0);
    add_class(&title, "menu-title");
    titles.pack_start(&title, false, false, 0);
    let subtitle = gtk::Label::new(Some("ADWS"));
    subtitle.set_xalign(0.0);
    add_class(&subtitle, "menu-subtitle");
    titles.pack_start(&subtitle, false, false, 0);
    header.pack_start(&titles, true, true, 0);
    content.pack_start(&header, false, false, 0);
    let search = gtk::SearchEntry::new();
    search.set_placeholder_text(Some(&text.get("搜索应用程序…")));
    add_class(&search, "menu-search");
    if theme == "kde" {
        content.pack_start(&search, false, false, 0);
    }
    let body = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    add_class(&body, "menu-body");
    content.pack_start(&body, true, true, 0);
    let sidebar = gtk::Box::new(gtk::Orientation::Vertical, 3);
    add_class(&sidebar, "menu-sidebar");
    let apps = Rc::new(applications());
    let query = Rc::new(RefCell::new(String::new()));
    let category = Rc::new(RefCell::new(String::new()));
    let list = gtk::ListBox::new();
    list.set_selection_mode(gtk::SelectionMode::Single);
    list.set_activate_on_single_click(true);
    for app in apps.iter() {
        let row = gtk::ListBoxRow::new();
        let line = gtk::Box::new(gtk::Orientation::Horizontal, 10);
        let image = app
            .info
            .icon()
            .map(|icon| gtk::Image::from_gicon(&icon, gtk::IconSize::LargeToolbar))
            .unwrap_or_else(|| {
                gtk::Image::from_icon_name(
                    Some("application-x-executable"),
                    gtk::IconSize::LargeToolbar,
                )
            });
        image.set_pixel_size(24);
        line.pack_start(&image, false, false, 0);
        let label = gtk::Label::new(Some(&app.info.display_name()));
        label.set_xalign(0.0);
        label.set_ellipsize(gtk::pango::EllipsizeMode::End);
        label.set_max_width_chars(30);
        line.pack_start(&label, true, true, 0);
        row.add(&line);
        row.set_tooltip_text(app.info.description().as_deref());
        list.add(&row);
    }
    let data = apps.clone();
    let q = query.clone();
    let c = category.clone();
    list.set_filter_func(Some(Box::new(move |row| {
        data.get(row.index() as usize)
            .is_some_and(|app| matches(&q.borrow(), &c.borrow(), &app.searchable, &app.categories))
    })));
    let status = gtk::Label::new(None);
    add_class(&status, "menu-status");
    status.set_line_wrap(true);
    status.set_no_show_all(true);
    let empty = gtk::Label::new(Some(&text.get("没有匹配的应用程序")));
    list.set_placeholder(Some(&empty));
    let scroll = gtk::ScrolledWindow::new(None::<&gtk::Adjustment>, None::<&gtk::Adjustment>);
    scroll.set_policy(gtk::PolicyType::Never, gtk::PolicyType::Automatic);
    scroll.add(&list);
    let side_scroll = gtk::ScrolledWindow::new(None::<&gtk::Adjustment>, None::<&gtk::Adjustment>);
    side_scroll.set_policy(gtk::PolicyType::Never, gtk::PolicyType::Automatic);
    side_scroll.set_size_request(165, -1);
    side_scroll.add(&sidebar);
    if theme == "kde" {
        body.pack_start(&side_scroll, false, false, 0);
        body.pack_start(&scroll, true, true, 0);
    } else {
        body.pack_start(&scroll, true, true, 0);
        body.pack_start(&side_scroll, false, false, 0);
    }
    for (caption, key, icon) in [
        ("全部应用", "", "view-app-grid-symbolic"),
        ("网络", "Network", "network-workgroup-symbolic"),
        ("办公", "Office", "x-office-document-symbolic"),
        ("多媒体", "AudioVideo", "applications-multimedia-symbolic"),
        ("图形", "Graphics", "applications-graphics-symbolic"),
        ("开发", "Development", "applications-development-symbolic"),
        ("游戏", "Game", "applications-games-symbolic"),
        ("系统", "System", "applications-system-symbolic"),
    ] {
        let button = icon_button(&text.get(caption), icon);
        let c = category.clone();
        let l = list.clone();
        let side = sidebar.downgrade();
        if key.is_empty() {
            add_class(&button, "active-category");
        }
        button.connect_clicked(move |button| {
            if let Some(side) = side.upgrade() {
                for child in side.children() {
                    child.style_context().remove_class("active-category");
                }
            }
            add_class(button, "active-category");
            *c.borrow_mut() = key.into();
            l.invalidate_filter();
        });
        sidebar.pack_start(&button, false, false, 0);
    }
    sidebar.pack_start(
        &gtk::Separator::new(gtk::Orientation::Horizontal),
        false,
        false,
        5,
    );
    let home = PathBuf::from(std::env::var_os("HOME").unwrap_or_default());
    for (caption, path, icon) in [
        ("主目录", home, "user-home-symbolic"),
        (
            "下载",
            glib::user_special_dir(glib::UserDirectory::Downloads).unwrap_or_else(|| {
                config_home()
                    .parent()
                    .unwrap_or(Path::new("/"))
                    .join("Downloads")
            }),
            "folder-download-symbolic",
        ),
    ] {
        let button = icon_button(&text.get(caption), icon);
        let a = application.clone();
        let error = status.clone();
        button.connect_clicked(move |_| {
            let uri = gio::File::for_path(&path).uri();
            match gio::AppInfo::launch_default_for_uri(&uri, None::<&gio::AppLaunchContext>) {
                Ok(()) => a.quit(),
                Err(e) => {
                    error.set_text(&e.to_string());
                    error.show();
                }
            }
        });
        sidebar.pack_start(&button, false, false, 0);
    }
    if theme != "kde" {
        content.pack_start(&search, false, false, 0);
    }
    content.pack_start(&status, false, false, 0);
    let footer = gtk::Box::new(gtk::Orientation::Horizontal, 6);
    add_class(&footer, "menu-footer");
    content.pack_start(&footer, false, false, 0);
    let settings = icon_button(&text.get("桌面设置"), "preferences-system-symbolic");
    let script = root.join("adws");
    let a = application.clone();
    let error = status.clone();
    settings.connect_clicked(move |_| {
        match std::process::Command::new(&script).arg("config").spawn() {
            Ok(_) => a.quit(),
            Err(e) => {
                error.set_text(&e.to_string());
                error.show();
            }
        }
    });
    footer.pack_start(&settings, false, false, 0);
    let close = icon_button(&text.get("关闭"), "window-close-symbolic");
    let a = application.clone();
    close.connect_clicked(move |_| a.quit());
    footer.pack_end(&close, false, false, 0);
    let q = query.clone();
    let l = list.clone();
    search.connect_search_changed(move |e| {
        *q.borrow_mut() = e.text().to_lowercase();
        l.invalidate_filter();
    });
    let data = apps.clone();
    let a = application.clone();
    let error = status.clone();
    let d = display.clone();
    list.connect_row_activated(move |_, row| {
        if let Some(app) = data.get(row.index() as usize) {
            let context = d.app_launch_context();
            match app.info.launch(&[], context.as_ref()) {
                Ok(()) => a.quit(),
                Err(e) => {
                    error.set_text(&e.to_string());
                    error.show();
                }
            }
        }
    });
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
    window.connect_key_press_event(move |_, event| {
        if event.keyval() == gdk::keys::constants::Escape {
            a.quit();
            glib::Propagation::Stop
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
            a.quit();
            glib::Propagation::Proceed
        });
    }
    window.show_all();
    search.grab_focus();
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
            glib::timeout_add_local_once(Duration::from_millis(120), move || {
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

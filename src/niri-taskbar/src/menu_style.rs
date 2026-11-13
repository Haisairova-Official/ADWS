use std::{collections::HashMap, path::PathBuf, sync::LazyLock};

use regex::Regex;
use waybar_cffi::gtk::{
    self as gtk, CssProvider,
    prelude::{CssProviderExt, WidgetExt},
};

thread_local! {
    static MENU_PROVIDER: CssProvider = {
        let provider = CssProvider::new();
        if let Some(screen) = gtk::gdk::Screen::default() {
            gtk::StyleContext::add_provider_for_screen(
                &screen, &provider, gtk::STYLE_PROVIDER_PRIORITY_USER + 1,
            );
        }
        provider
    };
}

static COLOR_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"@define-color\s+([\w-]+)\s+([^;]+);").expect("valid color regex")
});
fn config_home() -> Option<PathBuf> {
    std::env::var_os("XDG_CONFIG_HOME")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".config")))
}

fn waybar_config_file(name: &str) -> Option<PathBuf> {
    let path = config_home()?.join("waybar").join(name);
    path.is_file().then_some(path)
}

fn read_colors() -> HashMap<String, String> {
    let installed = std::iter::once_with(|| crate::paths::application_tool_candidates("config/waybar/colors.css")).flatten();
    for path in waybar_config_file("colors.css").into_iter().chain(installed) {
        let Ok(text) = std::fs::read_to_string(path) else { continue };
        let colors: HashMap<_, _> = COLOR_RE.captures_iter(&text)
            .map(|m| (m[1].to_string(), m[2].trim().to_string()))
            .collect();
        if !colors.is_empty() {
            return colors;
        }
    }
    HashMap::new()
}

fn desktop_font() -> String {
    let value = config_home()
        .and_then(|dir| std::fs::read_to_string(dir.join("niri-desktop-layer/config.toml")).ok())
        .and_then(|text| text.parse::<toml::Table>().ok())
        .and_then(|config| config.get("font_family")?.as_str().map(str::to_owned))
        .filter(|name| !name.trim().is_empty())
        .unwrap_or_else(|| "Noto Sans CJK SC".into());
    value.replace('\\', "\\\\").replace('"', "\\\"").replace(['\n', '\r'], " ")
}

/// 让菜单使用与底部任务栏一致的 matugen 调色板（每次弹出重读 colors.css）。
fn refresh_menu_palette() {
    let colors = read_colors();
    fn pick<'a>(colors: &'a HashMap<String, String>, name: &str, fallback: &'a str) -> &'a str {
        colors.get(name).map(String::as_str).unwrap_or(fallback)
    }
    let background = pick(&colors, "surface_container_high", "#282934");
    let foreground = pick(&colors, "on_surface", "#e2e1ef");
    let hover = pick(&colors, "surface_container", "#1e1f29");
    let outline = pick(&colors, "outline_variant", "#454651");

    let radius = bar_radius();
    let font_css = format!("font-family: \"{}\";", desktop_font());
    let context_menu = include_str!("../../../config/context-menu.css")
        .replace("__ADWS_MENU_FONT_RULE__", &font_css)
        .replace("__ADWS_MENU_RADIUS__", "12px")
        .replace("__ADWS_MENU_TRANSITION__", "none")
        .replace("__ADWS_MENU_LABEL_TRANSITION__", "none");
    let css = format!(
        "@define-color adws_menu_bg {background};
         @define-color adws_menu_fg {foreground};
         @define-color adws_menu_hover {hover};
         @define-color adws_menu_outline {outline};
         {context_menu}
         .adws-tray-item, .adws-quick-button {{ background: transparent; border: none; padding: 3px; border-radius: {radius}; box-shadow: none; min-width: 0; min-height: 0; color: {foreground}; }}
         .adws-tray-item:hover, .adws-quick-button:hover {{ background: {hover}; }}
         popover.adws-tray-overflow {{ background: {background}; color: {foreground}; border: 1px solid {outline}; border-radius: {radius}; }}"
    );

    MENU_PROVIDER.with(|provider| {
        if let Err(error) = provider.load_from_data(css.as_bytes()) {
            tracing::warn!(%error, "menu palette CSS parse error");
        }
    });
}

pub fn apply(menu: &gtk::Menu) {
    refresh_menu_palette();
    style_menu_tree(menu);
}

fn style_menu_tree(menu: &gtk::Menu) {
    use gtk::prelude::*;
    for child in menu.children() {
        if let Some(submenu) = child.downcast_ref::<gtk::MenuItem>()
            .and_then(|item| item.submenu())
            .and_then(|widget| widget.downcast::<gtk::Menu>().ok())
        {
            style_menu_tree(&submenu);
        }
    }
    let context = menu.style_context();
    if !context.has_class("adws-context-menu") {
        context.add_class("adws-menu");
        context.add_class("adws-context-menu");
        if !menu.is_realized() {
            if let Some(visual) = menu.screen().and_then(|s| s.rgba_visual()) {
                menu.set_visual(Some(&visual));
            }
        }
        prepare_popup_shell(menu);
        menu.connect_realize(prepare_popup_shell);
    }
}

pub fn action_item(title: &str, icon: &str) -> gtk::MenuItem {
    use gtk::prelude::*;
    let item = gtk::MenuItem::new();
    let row = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    let image = gtk::Image::from_icon_name(Some(icon), gtk::IconSize::Menu);
    let label = gtk::Label::new(Some(title));
    label.set_xalign(0.);
    row.pack_start(&image, false, false, 0);
    row.pack_start(&label, false, false, 0);
    item.add(&row);
    if let Some(accessible) = item.accessible() {
        gtk::atk::prelude::AtkObjectExt::set_name(&accessible, title);
    }
    item
}

// GtkMenu owns a separate popup GtkWindow. Setting the visual on the menu
// alone leaves that window RGB-only, filling the transparent rounded corners.
fn prepare_popup_shell(menu: &gtk::Menu) {
    use gtk::prelude::*;
    if let Some(top) = menu.toplevel().and_then(|w| w.downcast::<gtk::Window>().ok()) {
        top.style_context().add_class("adws-menu-popup");
        top.style_context().add_class("adws-context-popup");
        if !top.is_realized() {
            if let Some(visual) = gtk::prelude::WidgetExt::screen(&top).and_then(|s| s.rgba_visual()) {
                top.set_visual(Some(&visual));
            }
        }
    }
}

/// Named colors alone do not reliably invalidate GTK's custom drawing nodes.
/// Content polling also survives atomic replacement and symlink retargeting.
pub fn watch_palette() {
    use std::{cell::Cell, time::Duration};
    thread_local! { static STARTED: Cell<bool> = const { Cell::new(false) }; }
    if STARTED.with(|started| started.replace(true)) {
        return;
    }
    let provider = CssProvider::new();
    let Some(screen) = gtk::gdk::Screen::default() else {
        return;
    };
    gtk::StyleContext::add_provider_for_screen(
        &screen,
        &provider,
        gtk::STYLE_PROVIDER_PRIORITY_USER,
    );
    let mut previous = None;
    gtk::glib::timeout_add_local(Duration::from_millis(500), move || {
        let current = waybar_config_file("colors.css").and_then(|p| {
            let waybar = std::fs::read(&p).ok()?;
            if waybar.iter().all(u8::is_ascii_whitespace) {
                return None;
            }
            // GTK popovers use GTK roles, whereas bar widgets use Waybar roles.
            let gtk_palette = p.parent()?.parent()?.join("gtk-3.0/colors.css");
            let mut data = std::fs::read(gtk_palette).unwrap_or_default();
            data.push(b'\n');
            data.extend(waybar);
            Some(data)
        });
        if current != previous {
            if let Some(data) = current.as_ref() {
                // Validate before touching the active provider; preserve valid colors
                // while a generator is partway through writing its output.
                let candidate = CssProvider::new();
                if !data.is_empty()
                    && candidate.load_from_data(data).is_ok()
                    && provider.load_from_data(data).is_ok()
                {
                    previous = current;
                    refresh_menu_palette();
                    gtk::StyleContext::reset_widgets(&screen);
                    for window in gtk::Window::list_toplevels() {
                        window.queue_draw();
                    }
                }
            }
        }
        gtk::glib::ControlFlow::Continue
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use gtk::prelude::*;
    #[test]
    fn radius_follows_final_appearance_override() {
        assert_eq!(bar_radius_from_css("window#waybar > box {border-radius:0.7em;} window#waybar > box {border-radius:18px;}"),"18px");
    }
    #[test]
    #[ignore = "requires an isolated GTK display"]
    fn popup_has_transparent_corners() {
        gtk::init().unwrap();
        let root=std::env::temp_dir().join(format!("adws-menu-test-{}",std::process::id()));
        std::fs::create_dir_all(root.join("waybar")).unwrap();
        std::fs::write(root.join("waybar/style-bottom.css"),"window#waybar > box {border-radius:0;}").unwrap();
        std::fs::create_dir_all(root.join("niri-desktop-layer")).unwrap();
        std::fs::write(root.join("niri-desktop-layer/config.toml"), "font_family = 'Serif'").unwrap();
        let old=std::env::var_os("XDG_CONFIG_HOME");
        unsafe {std::env::set_var("XDG_CONFIG_HOME",&root);}

        let base=CssProvider::new();
        base.load_from_data(b"* {border-radius:0;} window {background-color:#282934;}").unwrap();
        gtk::StyleContext::add_provider_for_screen(&gtk::gdk::Screen::default().unwrap(),&base,gtk::STYLE_PROVIDER_PRIORITY_USER+1);
        let window=gtk::Window::new(gtk::WindowType::Toplevel);window.show_all();
        let menu=gtk::Menu::new();menu.append(&gtk::MenuItem::with_label("Open window"));
        apply(&menu);menu.show_all();
        menu.popup_at_rect(&window.window().unwrap(),&gtk::gdk::Rectangle::new(20,20,1,1),gtk::gdk::Gravity::SouthWest,gtk::gdk::Gravity::NorthWest,None);
        settle();
        assert_eq!(desktop_font(), "Serif");
        assert_eq!(bar_radius(), "0");
        let top=menu.toplevel().unwrap();
        assert!(top.style_context().has_class("adws-context-popup"));
        assert_eq!(top.visual().unwrap().depth(),32,"popup must use RGBA visual");
        let bg=top.style_context().style_property_for_state("background-color",gtk::StateFlags::NORMAL).get::<gtk::gdk::RGBA>().unwrap();
        assert_eq!(bg.alpha(),0.0,"popup shell must be transparent");
        let mut surface=gtk::cairo::ImageSurface::create(gtk::cairo::Format::ARgb32,80,80).unwrap();
        {let cr=gtk::cairo::Context::new(&surface).unwrap();gtk::render_background(&menu.style_context(),&cr,0.,0.,80.,80.);}
        surface.flush();let data=surface.data().unwrap();assert_eq!(data[3],0,"menu corner must be transparent");assert!(data[(40*80+40)*4+3]>200);
        menu.popdown();unsafe{
            menu.destroy();window.destroy();
            if let Some(value)=old {std::env::set_var("XDG_CONFIG_HOME",value);}else{std::env::remove_var("XDG_CONFIG_HOME");}
        }
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn popup_radius_does_not_follow_docked_surface_override() {
        let css="window#waybar > box {border-radius:18px;} window#waybar.adws-panel.adws-docked > box {border-radius:0;} window#waybar.adws-panel.adws-split.adws-docked > box > box.modules-left {border-radius:0 18px 18px 0;}";
        assert_eq!(bar_radius_from_css(css),"18px");
    }
    use std::time::{Duration, Instant};
    fn settle() {
        let until = Instant::now() + Duration::from_millis(650);
        while Instant::now() < until {
            while gtk::glib::MainContext::default().pending() {
                gtk::glib::MainContext::default().iteration(false);
            }
            std::thread::sleep(Duration::from_millis(5));
        }
    }
    #[test]
    #[ignore = "requires an isolated GTK display"]
    fn live_palette_replacement() {
        gtk::init().unwrap();
        let root = std::env::temp_dir().join(format!("adws-theme-test-{}", std::process::id()));
        let dir = root.join("waybar");
        std::fs::create_dir_all(&dir).unwrap();
        let old = std::env::var_os("XDG_CONFIG_HOME");
        unsafe {
            std::env::set_var("XDG_CONFIG_HOME", &root);
        }
        let palette = dir.join("colors.css");
        std::fs::write(&palette, "@define-color primary #ff0000;\n").unwrap();
        let style = dir.join("style-bottom.css");
        std::fs::write(&style,"@import 'colors.css'; button {background-image:none;background-color:@primary;transition:none;}").unwrap();
        let css = CssProvider::new();
        css.load_from_path(style.to_str().unwrap()).unwrap();
        gtk::StyleContext::add_provider_for_screen(
            &gtk::gdk::Screen::default().unwrap(),
            &css,
            gtk::STYLE_PROVIDER_PRIORITY_USER,
        );
        let window = gtk::Window::new(gtk::WindowType::Toplevel);
        let button = gtk::Button::with_label("theme");
        window.add(&button);
        window.show_all();
        let manual = CssProvider::new();
        manual.load_from_data(b"button {color:#123456;}").unwrap();
        button
            .style_context()
            .add_provider(&manual, gtk::STYLE_PROVIDER_PRIORITY_USER);
        watch_palette();
        settle();
        let context = button.style_context();
        assert!(
            context
                .style_property_for_state("background-color", gtk::StateFlags::NORMAL)
                .get::<gtk::gdk::RGBA>()
                .unwrap()
                .red()
                > 0.9
        );
        std::fs::write(dir.join("new.css"), "@define-color primary #0000ff;\n").unwrap();
        std::fs::rename(dir.join("new.css"), &palette).unwrap();
        settle();
        assert!(context.lookup_color("primary").unwrap().blue() > 0.9);
        assert!(
            context
                .style_property_for_state("background-color", gtk::StateFlags::NORMAL)
                .get::<gtk::gdk::RGBA>()
                .unwrap()
                .blue()
                > 0.9,
            "computed CSS must refresh as well as named-color lookup"
        );
        std::fs::write(&palette, "invalid css {").unwrap();
        settle();
        assert!(
            context
                .style_property_for_state("background-color", gtk::StateFlags::NORMAL)
                .get::<gtk::gdk::RGBA>()
                .unwrap()
                .blue()
                > 0.9
        );
        std::fs::write(&palette, "@define-color primary #00ff00;\n").unwrap();
        settle();
        assert!(
            context
                .style_property_for_state("background-color", gtk::StateFlags::NORMAL)
                .get::<gtk::gdk::RGBA>()
                .unwrap()
                .green()
                > 0.9
        );
        let manual_color = context.color(gtk::StateFlags::NORMAL);
        assert!(
            (manual_color.red() - 18.0 / 255.0).abs() < 0.01,
            "manual color changed"
        );
        unsafe {
            window.destroy();
            if let Some(v) = old {
                std::env::set_var("XDG_CONFIG_HOME", v);
            } else {
                std::env::remove_var("XDG_CONFIG_HOME");
            }
        }
        std::fs::remove_dir_all(root).unwrap();
    }
}

/// Local provider keeps dangerous actions distinct without changing normal close.
pub fn destructive(item: &gtk::MenuItem, animations: bool, duration: u32) {
    use gtk::prelude::*;
    item.style_context().add_class("adws-destructive");
    item.style_context().add_class("adws-destructive-transition");
    // Each bar can select a different duration. The common template supplies
    // the colors, while this item's transition survives releasing Shift.
    let transition = if animations {
        format!("background-color {duration}ms ease-in-out, color {duration}ms ease-in-out")
    } else {
        "none".into()
    };
    let provider = CssProvider::new();
    let css = format!("menuitem {{ transition: {transition}; }}");
    if provider.load_from_data(css.as_bytes()).is_ok() {
        item.style_context().add_provider(&provider, gtk::STYLE_PROVIDER_PRIORITY_USER + 2);
    }
    if let Some(label) = item.child() {
        let label_provider = CssProvider::new();
        let transition = if animations { format!("color {duration}ms ease-in-out") } else { "none".into() };
        let css = format!("label {{ transition: {transition}; }}");
        if label_provider.load_from_data(css.as_bytes()).is_ok() {
            label.style_context().add_provider(&label_provider, gtk::STYLE_PROVIDER_PRIORITY_USER + 2);
        }
    }
}

// GTK3 does not expose computed corner radii through get_property. Use the
// same final bar rule as the appearance settings, retaining em units.
pub fn bar_radius() -> String {
    let Some(path)=waybar_config_file("style-bottom.css") else {return "12px".into();};
    let Ok(css)=std::fs::read_to_string(path) else {return "12px".into();};
    bar_radius_from_css(&css)
}
fn bar_radius_from_css(css: &str) -> String {
    static BLOCK: LazyLock<Regex> = LazyLock::new(||Regex::new(r"(?s)window#waybar\s*>\s*box\s*\{([^}]*)\}").unwrap());
    static RADIUS: LazyLock<Regex> = LazyLock::new(||Regex::new(r"border-radius\s*:\s*([0-9.]+(?:px|em|rem)?(?:\s+[0-9.]+(?:px|em|rem)?){0,3})\s*;").unwrap());
    BLOCK.captures_iter(css).filter_map(|b| RADIUS.captures(&b[1]).map(|c|c[1].to_string())).last().unwrap_or_else(||"12px".into())
}

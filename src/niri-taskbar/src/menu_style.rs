use std::{collections::HashMap, path::PathBuf, sync::LazyLock};

use regex::Regex;
use waybar_cffi::gtk::{
    self as gtk, CssProvider,
    prelude::{CssProviderExt, StyleContextExt, WidgetExt},
};

thread_local! {
    static MENU_PROVIDER: CssProvider = {
        let provider = CssProvider::new();
        if let Some(screen) = gtk::gdk::Screen::default() {
            gtk::StyleContext::add_provider_for_screen(
                &screen, &provider, gtk::STYLE_PROVIDER_PRIORITY_USER,
            );
        }
        provider
    };
}

static COLOR_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"@define-color\s+([\w-]+)\s+([^;]+);").expect("valid color regex")
});
static FONT_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"font-family\s*:\s*([^;}]+);").expect("valid font regex"));

fn waybar_config_file(name: &str) -> Option<PathBuf> {
    let config = std::env::var_os("XDG_CONFIG_HOME")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".config")))?;
    let path = config.join("waybar").join(name);
    path.is_file().then_some(path)
}

fn read_colors() -> HashMap<String, String> {
    let mut colors = HashMap::new();
    let Some(path) = waybar_config_file("colors.css") else {
        return colors;
    };
    let Ok(text) = std::fs::read_to_string(path) else {
        return colors;
    };
    for captures in COLOR_RE.captures_iter(&text) {
        let name = captures
            .get(1)
            .map(|m| m.as_str().trim())
            .unwrap_or_default();
        let value = captures
            .get(2)
            .map(|m| m.as_str().trim())
            .unwrap_or_default();
        if !name.is_empty() && !value.is_empty() {
            colors.insert(name.to_string(), value.to_string());
        }
    }
    colors
}

fn read_font_family() -> Option<String> {
    let path = waybar_config_file("style-bottom.css")?;
    let text = std::fs::read_to_string(path).ok()?;
    // 样式文件后面出现的 font-family 会覆盖前面的，取最后一段的第一族字体。
    let captures = FONT_RE.captures_iter(&text).last()?;
    let value = captures.get(1)?.as_str();
    let family = value.split(',').next()?.trim().trim_matches('"').trim();
    (!family.is_empty()).then(|| family.to_string())
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

    let font_family = read_font_family();
    let font_css = match font_family {
        Some(family) => format!("font-family: \"{}\";", family.replace('"', "")),
        None => String::new(),
    };

    let css = format!(
        "menu.adws-menu {{\n\
             background-color: {background};\n\
             color: {foreground};\n\
             {font_css}\n\
             padding: 4px;\n\
             margin: 4px;\n\
             border-radius: 9px;\n\
             border: none;\n\
             box-shadow: none;\n\
             background-image: none;\n\
         }}\n\
         menu.adws-menu menuitem {{\n\
             color: {foreground};\n\
             padding: 5px 12px;\n\
             min-height: 16px;\n\
             border-radius: 9px;\n\
         }}\n\
         menu.adws-menu menuitem:hover,\n\
         menu.adws-menu menuitem:selected {{\n\
             background-color: {hover};\n\
             color: {foreground};\n\
             border-radius: 9px;\n\
         }}\n\
         menu.adws-menu separator {{\n\
             background-color: {outline};\n\
             margin: 6px 0;\n\
         }}\n\
         window.adws-menu-popup, window.adws-menu-popup decoration {{\n\
             background-color: transparent;\n\
             background-image: none;\n\
             border: none;\n\
             box-shadow: none;\n\
         }}\n"
    );

    MENU_PROVIDER.with(|provider| {
        if let Err(error) = provider.load_from_data(css.as_bytes()) {
            tracing::warn!(%error, "menu palette CSS parse error");
        }
    });
}

pub fn apply(menu: &gtk::Menu) {
    refresh_menu_palette();
    // Screen-scoped selectors also reach menu items and the popup decoration;
    // a provider attached to the menu widget alone does not style those nodes.
    menu.style_context().add_class("adws-menu");
    if let Some(top) = menu.toplevel() {
        top.style_context().add_class("adws-menu-popup");
    }
    menu.connect_realize(|menu| {
        if let Some(top) = menu.toplevel() {
            top.style_context().add_class("adws-menu-popup");
        }
    });
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

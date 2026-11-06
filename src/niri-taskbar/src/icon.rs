use std::{
    collections::HashMap,
    path::PathBuf,
    sync::{Arc, LazyLock, Mutex},
};

use waybar_cffi::gtk::{
    self as gtk,
    gio::{DesktopAppInfo, FileIcon, ThemedIcon},
    prelude::*,
};

/// Cache desktop-entry metadata, never a resolved path from a particular theme.
/// GTK resolves themed names at the actual size/scale and owns theme invalidation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Source {
    Themed(Vec<String>),
    File(PathBuf),
}

#[derive(Debug, Clone, Default)]
pub struct Cache(Arc<Mutex<HashMap<String, Option<Source>>>>);

impl Cache {
    #[tracing::instrument(level = "TRACE", ret)]
    pub fn lookup(&self, id: &str) -> Option<Source> {
        if let Some(result) = self.0.lock().expect("icon cache lock").get(id).cloned() {
            return result;
        }
        // Desktop-file discovery runs on a worker without holding the cache lock.
        let result = lookup(id);
        self.0.lock().expect("icon cache lock").insert(id.to_string(), result.clone());
        result
    }
}

fn desktop_icon(info: &DesktopAppInfo) -> Option<Source> {
    let icon = info.icon()?;
    if let Some(themed) = icon.downcast_ref::<ThemedIcon>() {
        let names: Vec<_> = themed.names().iter().map(ToString::to_string).collect();
        if !names.is_empty() { return Some(Source::Themed(names)); }
    }
    if let Some(file) = icon.downcast_ref::<FileIcon>() {
        return file.file().path().map(Source::File);
    }
    None
}

fn lookup(id: &str) -> Option<Source> {
    if id.is_empty() { return None; }
    // Icon= is authoritative. Looking up the app ID in hicolor first bypasses
    // the active theme when the desktop entry uses a different icon name.
    let desktop_id = if id.ends_with(".desktop") { id.to_string() } else { format!("{id}.desktop") };
    if let Some(source) = DesktopAppInfo::new(&desktop_id).as_ref().and_then(desktop_icon) {
        return Some(source);
    }
    for dir in XDG_DATA_DIRS.iter() {
        for prefix in ["applications/", "applications/kde/", "applications/org.kde."] {
            for suffix in ["", ".desktop"] {
                let path = dir.join(format!("{prefix}{id}{suffix}"));
                if let Some(source) = DesktopAppInfo::from_filename(&path).as_ref().and_then(desktop_icon) {
                    return Some(source);
                }
            }
        }
    }
    for possible in DesktopAppInfo::search(id).into_iter().flatten() {
        if let Some(source) = DesktopAppInfo::new(&possible).as_ref().and_then(desktop_icon) {
            return Some(source);
        }
    }
    // GTK performs current-theme -> inherited themes -> hicolor fallback.
    Some(Source::Themed(vec![id.trim_end_matches(".desktop").to_string()]))
}

static XDG_DATA_DIRS: LazyLock<Vec<PathBuf>> = LazyLock::new(|| {
    let mut dirs = Vec::new();
    if let Some(home) = std::env::var_os("XDG_DATA_HOME").filter(|v| !v.is_empty()) {
        dirs.push(PathBuf::from(home));
    } else if let Some(home) = std::env::var_os("HOME") {
        dirs.push(PathBuf::from(home).join(".local/share"));
    }
    let paths = std::env::var_os("XDG_DATA_DIRS")
        .filter(|v| !v.is_empty()).unwrap_or_else(|| "/usr/local/share:/usr/share".into());
    dirs.extend(std::env::split_paths(&paths));
    dirs
});

/// Keep GTK in charge of theme rendering, but only use the generic app icon
/// after checking the complete inheritance chain for the application's names.
pub fn themed_image(names: &[String], size: i32) -> gtk::Image {
    let image = gtk::Image::new();
    image.set_pixel_size(size);
    let Some(theme) = gtk::IconTheme::default() else {
        image.set_from_icon_name(Some("application-x-executable"), gtk::IconSize::Invalid);
        return image;
    };
    fn apply(image: &gtk::Image, theme: &gtk::IconTheme, names: &[String]) {
        if names.iter().any(|name| theme.has_icon(name)) {
            let names: Vec<&str> = names.iter().map(String::as_str).collect();
            image.set_from_gicon(&ThemedIcon::from_names(&names), gtk::IconSize::Invalid);
        } else {
            image.set_from_icon_name(Some("application-x-executable"), gtk::IconSize::Invalid);
        }
    }
    apply(&image, &theme, names);
    let weak = image.downgrade();
    let names = names.to_vec();
    let handler = theme.connect_changed(move |theme| {
        if let Some(image) = weak.upgrade() {
            if !image.in_destruction() { apply(&image, theme, &names); }
        }
    });
    // A replaced/closed window card must not leave a theme listener behind.
    let handler = std::cell::RefCell::new(Some(handler));
    image.connect_destroy(move |_| {
        if let Some(handler) = handler.borrow_mut().take() { theme.disconnect(handler); }
    });
    image
}

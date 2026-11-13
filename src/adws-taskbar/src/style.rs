//! Load the user's GTK stylesheet and follow local imports through atomic saves.
use gtk::{gdk, gio, glib, prelude::*};
use std::{
    cell::RefCell,
    collections::HashSet,
    fs,
    path::{Path, PathBuf},
    rc::Rc,
    time::Duration,
};

fn imports(text: &str) -> Vec<String> {
    let mut imports = Vec::new();
    let mut rest = text;
    while !rest.is_empty() {
        if let Some(comment) = rest.strip_prefix("/*") {
            rest = comment.split_once("*/").map_or("", |(_, tail)| tail);
            continue;
        }
        if let Some(tail) = rest.strip_prefix("@import") {
            let arg = tail.trim_start();
            let arg = arg.strip_prefix("url(").unwrap_or(arg).trim_start();
            if let Some(quote @ ('\'' | '"')) = arg.chars().next() {
                if let Some((name, tail)) = arg[1..].split_once(quote) {
                    imports.push(name.to_string());
                    rest = tail;
                    continue;
                }
            } else if tail.trim_start().starts_with("url(") {
                if let Some((name, tail)) = arg.split_once(')') {
                    imports.push(name.trim().to_string());
                    rest = tail;
                    continue;
                }
            }
        }
        let first = rest.chars().next().unwrap();
        rest = &rest[first.len_utf8()..];
        if matches!(first, '\'' | '"') {
            let mut escaped = false;
            for (i, c) in rest.char_indices() {
                if c == first && !escaped {
                    rest = &rest[i + c.len_utf8()..];
                    break;
                }
                escaped = c == '\\' && !escaped;
            }
        }
    }
    imports
}

fn local_files(root: &Path) -> HashSet<PathBuf> {
    let mut paths = HashSet::new();
    let mut pending = vec![root.to_path_buf()];
    while let Some(path) = pending.pop() {
        if paths.len() >= 128 || !paths.insert(path.clone()) {
            continue;
        }
        if let Ok(resolved) = path.canonicalize() {
            paths.insert(resolved);
        }
        let Ok(meta) = fs::metadata(&path) else {
            continue;
        };
        if meta.len() > 2 * 1024 * 1024 {
            continue;
        }
        let Ok(text) = fs::read_to_string(&path) else {
            continue;
        };
        for name in imports(&text) {
            if name.starts_with("file://") {
                if let Some(path) = gio::File::for_uri(&name).path() {
                    pending.push(path);
                }
            } else if !name.contains("://") {
                pending.push(path.parent().unwrap_or(Path::new(".")).join(name));
            }
        }
    }
    paths
}

// GTK themes give buttons their own foreground. Let taskbar controls inherit
// the bar palette, while allowing any explicit color in the user's stylesheet.
const CONTROL_STYLE: &[u8] = b"
window#waybar .adws-quick-button, window#waybar .niri-workspace,
window#waybar .adws-tray button, window#waybar .niri-taskbar button {
    color: inherit;
}";

pub struct Style {
    root: PathBuf,
    screen: gdk::Screen,
    baseline: gtk::CssProvider,
    provider: RefCell<Option<gtk::CssProvider>>,
    watchers: RefCell<Vec<gio::FileMonitor>>,
    queued: RefCell<Option<glib::SourceId>>,
    watch: bool,
}

impl Style {
    pub fn load(root: &Path, screen: &gdk::Screen, watch: bool) -> Result<Rc<Self>, String> {
        let baseline = gtk::CssProvider::new();
        baseline
            .load_from_data(CONTROL_STYLE)
            .map_err(|e| e.to_string())?;
        gtk::StyleContext::add_provider_for_screen(
            screen,
            &baseline,
            gtk::STYLE_PROVIDER_PRIORITY_APPLICATION - 1,
        );
        let style = Rc::new(Self {
            root: root.to_owned(),
            screen: screen.clone(),
            baseline,
            provider: RefCell::default(),
            watchers: RefCell::default(),
            queued: RefCell::default(),
            watch,
        });
        style.reload()?;
        Ok(style)
    }
    pub(crate) fn reload(self: &Rc<Self>) -> Result<(), String> {
        let new = gtk::CssProvider::new();
        new.load_from_file(&gio::File::for_path(&self.root))
            .map_err(|e| format!("Cannot load {}: {e}", self.root.display()))?;
        gtk::StyleContext::add_provider_for_screen(
            &self.screen,
            &new,
            gtk::STYLE_PROVIDER_PRIORITY_USER,
        );
        if let Some(old) = self.provider.replace(Some(new)) {
            gtk::StyleContext::remove_provider_for_screen(&self.screen, &old);
        }
        if !self.watch {
            return Ok(());
        }
        let files = Rc::new(local_files(&self.root));
        let folders: HashSet<_> = files.iter().filter_map(|p| p.parent()).collect();
        let mut watchers = vec![];
        for folder in folders {
            let monitor = gio::File::for_path(folder)
                .monitor_directory(
                    gio::FileMonitorFlags::WATCH_MOVES,
                    None::<&gio::Cancellable>,
                )
                .map_err(|e| format!("Cannot watch {}: {e}", folder.display()))?;
            let weak = Rc::downgrade(self);
            let paths = files.clone();
            monitor.connect_changed(move |_, first, other, _| {
                let relevant = Some(first)
                    .into_iter()
                    .chain(other)
                    .filter_map(|f| f.path())
                    .any(|p| paths.contains(&p));
                if !relevant {
                    return;
                }
                if let Some(style) = weak.upgrade() {
                    if style.queued.borrow().is_none() {
                        let weak = weak.clone();
                        let timer =
                            glib::timeout_add_local_once(Duration::from_millis(125), move || {
                                if let Some(style) = weak.upgrade() {
                                    style.queued.borrow_mut().take();
                                    if let Err(e) = style.reload() {
                                        eprintln!("adws-taskbar: {e}");
                                    }
                                }
                            });
                        style.queued.replace(Some(timer));
                    }
                }
            });
            watchers.push(monitor);
        }
        for old in self.watchers.replace(watchers) {
            old.cancel();
        }
        Ok(())
    }
}
impl Drop for Style {
    fn drop(&mut self) {
        if let Some(id) = self.queued.take() {
            id.remove();
        }
        for monitor in self.watchers.take() {
            monitor.cancel();
        }
        gtk::StyleContext::remove_provider_for_screen(&self.screen, &self.baseline);
        if let Some(css) = self.provider.take() {
            gtk::StyleContext::remove_provider_for_screen(&self.screen, &css);
        }
    }
}

#[cfg(test)]
pub(crate) mod tests {
    pub(crate) fn buttons_inherit_the_bar_foreground_but_respect_user_colors() {
        use super::*;
        gtk::init().unwrap();
        let file =
            std::env::temp_dir().join(format!("adws-control-style-{}.css", std::process::id()));
        fs::write(
            &file,
            "window#waybar { color: #d0a080; } window#waybar button.own-color { color: #103050; }",
        )
        .unwrap();
        let window = gtk::Window::new(gtk::WindowType::Toplevel);
        window.set_widget_name("waybar");
        let row = gtk::Box::new(gtk::Orientation::Horizontal, 0);
        window.add(&row);
        let mut buttons = Vec::new();
        for classes in [
            ["adws-quick-button", ""],
            ["niri-workspace", ""],
            ["adws-quick-button", "own-color"],
        ] {
            let button = gtk::Button::new();
            for class in classes.iter().filter(|c| !c.is_empty()) {
                button.style_context().add_class(class);
            }
            row.add(&button);
            buttons.push(button);
        }
        let screen = gtk::prelude::WidgetExt::screen(&window).unwrap();
        let provider = Style::load(&file, &screen, false).unwrap();
        window.show_all();
        let context = glib::MainContext::default();
        while context.pending() {
            context.iteration(false);
        }
        let colors: Vec<_> = buttons
            .iter()
            .map(|w| {
                let c = w.style_context().color(w.state_flags());
                [c.red(), c.green(), c.blue()].map(|v| (v * 255.).round() as u8)
            })
            .collect();
        assert_eq!(colors, [[208, 160, 128], [208, 160, 128], [16, 48, 80]]);
        drop(provider);
        unsafe {
            window.destroy();
        }
        fs::remove_file(file).unwrap();
    }

    #[test]
    fn local_imports_ignore_comments_and_css_strings() {
        assert_eq!(super::imports("/* @import 'bogus'; */ @import url('nested/colors.css'); label {font-family: \"@import 'ignore'\";} @import \"more.css\";"), ["nested/colors.css","more.css"]);
    }
}

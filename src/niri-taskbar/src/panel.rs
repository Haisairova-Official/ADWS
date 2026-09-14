use std::{cell::RefCell, path::PathBuf, process::Command};

use waybar_cffi::gtk::{
    self as gtk,
    prelude::{GtkMenuExt, GtkMenuItemExt, MenuShellExt, WidgetExt},
};

thread_local! {
    static ACTIVE_MENU: RefCell<Option<gtk::Menu>> = RefCell::new(None);
}

/// 在底栏空白处提供右键菜单，打开统一的 MNWS-Config（任务栏样式页）。
///
/// 菜单挂在 waybar 顶层窗口上，因此只会在不属于任何子组件
/// （开始按钮、窗口图标、时钟等）的背景区域收到事件时弹出。
pub fn connect_panel_menu(toplevel: &gtk::Widget) {
    toplevel.connect_button_press_event(|widget, event| {
        if event.button() != 3 {
            return gtk::glib::Propagation::Proceed;
        }

        // 事件落在某个子组件的窗口上（如时钟、按钮）时不由这里处理，
        // 让那些组件自己的左/右键行为生效。
        if let (Some(event_window), Some(widget_window)) = (event.window(), widget.window()) {
            if event_window != widget_window {
                return gtk::glib::Propagation::Proceed;
            }
        }

        let menu = gtk::Menu::new();
        let style_item = gtk::MenuItem::with_label(crate::i18n::text("任务栏样式设置… (MNWS)", "Taskbar style settings… (MNWS)"));
        style_item.connect_activate(|_| {
            tracing::info!("{}", crate::i18n::text("打开任务栏设置", "Open taskbar settings"));
            open_mnws_config();
        });
        menu.append(&style_item);
        let layout_item = gtk::MenuItem::with_label(crate::i18n::text("组件与插件… (MNWS)", "Components and plugins… (MNWS)"));
        layout_item.connect_activate(|_| {
            tracing::info!("{}", crate::i18n::text("打开组件布局设置", "Open component layout settings"));
            open_layout_gui();
        });
        menu.append(&layout_item);
        crate::menu_style::apply(&menu);
        menu.show_all();
        menu.connect_deactivate(|_| {
            ACTIVE_MENU.with(|slot| slot.borrow_mut().take());
        });

        ACTIVE_MENU.with(|slot| {
            let mut active = slot.borrow_mut();
            if let Some(old) = active.take() {
                old.popdown();
            }
            *active = Some(menu.clone());
        });
        // 传入触发事件，让 GTK 在指针位置弹出菜单；不传时部分 Wayland 环境会定位失败。
        menu.popup_at_pointer(Some(event));
        gtk::glib::Propagation::Stop
    });
}

fn open_mnws_config() {
    let mut candidates = Vec::new();
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let project_root = manifest.parent().and_then(|parent| parent.parent());
    if let Some(root) = project_root {
        candidates.push(root.join("tools/mnws-config.py"));
    }
    if let Ok(home) = std::env::var("HOME") {
        candidates.push(PathBuf::from(home).join(".local/bin/mnws-config"));
    }

    let Some(tool) = candidates.into_iter().find(|path| path.exists()) else {
        tracing::warn!("{}", crate::i18n::text("MNWS-Config 未找到（tools/mnws-config.py 或 ~/.local/bin/mnws-config）", "MNWS-Config not found (tools/mnws-config.py or ~/.local/bin/mnws-config)"));
        return;
    };

    let result = Command::new("python3")
        .arg(&tool)
        .arg("--tab")
        .arg("taskbar")
        .env_remove("GDK_BACKEND")
        .spawn();
    if let Err(e) = result {
        tracing::warn!(%e, "cannot launch MNWS-Config");
    }
}

fn open_layout_gui() {
    let mut candidates = Vec::new();
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let project_root = manifest.parent().and_then(|parent| parent.parent());
    if let Some(root) = project_root {
        candidates.push(root.join("tools/mnws_layout.py"));
    }
    if let Ok(home) = std::env::var("HOME") {
        candidates.push(PathBuf::from(home).join(".local/bin/mnws"));
    }

    let Some(tool) = candidates.into_iter().find(|path| path.exists()) else {
        tracing::warn!("{}", crate::i18n::text("MNWS 布局工具未找到（tools/mnws_layout.py 或 ~/.local/bin/mnws）", "MNWS layout tool not found (tools/mnws_layout.py or ~/.local/bin/mnws)"));
        return;
    };

    let result = if tool.extension().is_some_and(|ext| ext == "py") {
        Command::new("python3")
            .arg(&tool)
            .arg("gui")
            .env_remove("GDK_BACKEND")
            .spawn()
    } else {
        Command::new(&tool)
            .arg("layout")
            .arg("gui")
            .env_remove("GDK_BACKEND")
            .spawn()
    };
    if let Err(e) = result {
        tracing::warn!(%e, "{}", crate::i18n::text("cannot launch MNWS 组件布局", "Cannot launch MNWS component layout"));
    }
}

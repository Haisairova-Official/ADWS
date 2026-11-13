use std::{cell::RefCell, process::Command, rc::Rc};

use crate::paths::application_tool_candidates;
use waybar_cffi::gtk::{
    self as gtk,
    prelude::{Cast, GtkMenuExt, GtkMenuItemExt, IsA, MenuShellExt, WidgetExt, WidgetExtManual},
};

thread_local! {
    pub(super) static ACTIVE_CONTEXT_MENU: RefCell<Option<gtk::Menu>> = const { RefCell::new(None) };
}

/// 在底栏空白处提供右键菜单，提供桌面配置、任务栏设置与 ADWS 系统设置入口。
///
/// 菜单挂在 waybar 顶层窗口上，因此只会在不属于任何子组件
/// （开始按钮、窗口图标、时钟等）的背景区域收到事件时弹出。
pub fn connect_panel_menu(toplevel: &gtk::Widget) {
    guard_popup_configure(toplevel);
    watch_responsiveness();
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

        show_menu(panel_menu(), Some(event), widget);
        gtk::glib::Propagation::Stop
    });
    toplevel.connect_popup_menu(|widget| {
        show_menu(panel_menu(), None, widget);
        true
    });
}

fn panel_menu() -> gtk::Menu {
    let menu = gtk::Menu::new();
    for (title, icon, page) in [
        (crate::i18n::text("桌面配置", "Desktop configuration"), "video-display-symbolic", "desktop"),
        (crate::i18n::text("任务栏设置", "Taskbar settings"), "view-grid-symbolic", "taskbar"),
        (crate::i18n::text("ADWS设置", "ADWS settings"), "preferences-system-symbolic", ""),
    ] {
        let item = crate::menu_style::action_item(title, icon);
        item.connect_activate(move |_| open_adws_config(page));
        menu.append(&item);
    }
    menu
}

pub(crate) fn show_menu(menu: gtk::Menu, event: Option<&gtk::gdk::EventButton>, anchor: &impl IsA<gtk::Widget>) {
    // popdown emits deactivate synchronously. Release the slot before calling it.
    if let Some(previous) = ACTIVE_CONTEXT_MENU.with(|slot| slot.borrow_mut().take()) {
        previous.popdown();
        unsafe { previous.destroy(); }
    }
    let focus = anchor.toplevel()
        .and_then(|widget| widget.downcast::<gtk::Window>().ok())
        .and_then(|window| crate::button::popup_keyboard_focus(&window));
    if let Some(guard) = focus {
        let guard = Rc::new(RefCell::new(Some(guard)));
        let deactivate = guard.clone();
        menu.connect_deactivate(move |_| { deactivate.borrow_mut().take(); });
        let unmap = guard.clone();
        menu.connect_unmap(move |_| { unmap.borrow_mut().take(); });
        menu.connect_destroy(move |_| { guard.borrow_mut().take(); });
    }
    crate::menu_style::apply(&menu);
    menu.connect_deactivate(|menu| {
        ACTIVE_CONTEXT_MENU.with(|slot| {
            let mut active = slot.borrow_mut();
            if active.as_ref() == Some(menu) {
                active.take();
            }
        });
        // GTK dispatches the chosen action after deactivation.
        let menu = menu.clone();
        gtk::glib::idle_add_local_once(move || unsafe { menu.destroy(); });
    });
    ACTIVE_CONTEXT_MENU.with(|slot| { slot.replace(Some(menu.clone())); });
    menu.show_all();
    if let Some(event) = event {
        menu.popup_at_pointer(Some(event));
    } else {
        menu.popup_at_widget(anchor, gtk::gdk::Gravity::NorthWest, gtk::gdk::Gravity::SouthWest, gtk::current_event().as_ref());
        menu.select_first(true);
    }
}

// Filter at GtkWidget's generic event stage, before configure-event is
// dispatched: Waybar registers its own configure callback before our module.
// Popover surface sizes must never replace the parent bar's geometry.
fn guard_popup_configure(toplevel: &gtk::Widget) {
    toplevel.connect_event(|widget, event| {
        if event.event_type() == gtk::gdk::EventType::Configure
            && event.window().zip(widget.window()).is_some_and(|(source, own)| source != own)
        {
            tracing::debug!("ignored popup configure event on taskbar");
            gtk::glib::Propagation::Stop
        } else {
            gtk::glib::Propagation::Proceed
        }
    });
}

fn watch_responsiveness() {
    use std::{cell::Cell, time::{Duration, Instant}};
    thread_local! { static STARTED: Cell<bool> = const { Cell::new(false) }; }
    if STARTED.with(|started| started.replace(true)) { return; }
    let heartbeat = crate::watchdog::start(application_tool_candidates("tools/adws_taskbar_recover.py").into_iter().find(|p| p.is_file()));
    let mut previous = Instant::now();
    gtk::glib::timeout_add_local(Duration::from_millis(200), move || {
        heartbeat.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let now = Instant::now();
        let gap = now.duration_since(previous);
        if gap > Duration::from_millis(700) {
            tracing::warn!(delay_ms=gap.as_millis(), "ADWS taskbar main loop delayed");
        }
        previous = now;
        gtk::glib::ControlFlow::Continue
    });
}

#[cfg(test)]
mod configure_tests {
    use super::*;
    use gtk::glib::translate::*;
    use gtk::prelude::*;
    #[test]
    #[ignore = "requires an isolated GTK display"]
    fn popup_configure_does_not_reach_bar_handler() {
        gtk::init().unwrap();
        let bar=gtk::Window::new(gtk::WindowType::Toplevel);
        let popup=gtk::Window::new(gtk::WindowType::Popup);
        bar.show_all(); popup.show_all();
        let count=std::rc::Rc::new(std::cell::Cell::new(0));
        let observed=count.clone();
        // Register the bar callback first, matching Waybar initialization.
        bar.connect_local("configure-event", false, move |_| {
            observed.set(observed.get()+1);
            Some(false.to_value())
        });
        guard_popup_configure(bar.upcast_ref());
        for (source, expected) in [(popup.window().unwrap(), 0), (bar.window().unwrap(), 1)] {
            let mut event=gtk::gdk::Event::new(gtk::gdk::EventType::Configure)
                .downcast::<gtk::gdk::EventConfigure>().unwrap();
            event.as_mut().window=source.to_glib_full();
            event.as_mut().width=304; event.as_mut().height=259;
            let _=bar.event(&event);
            assert_eq!(count.get(),expected);
        }
        unsafe { popup.destroy(); bar.destroy(); }
    }
}

fn open_adws_config(tab: &str) {
    let candidates = application_tool_candidates("tools/adws-config.py");

    let Some(tool) = candidates.into_iter().find(|path| path.exists()) else {
        tracing::warn!("{}", crate::i18n::text("ADWS-Config 未找到（tools/adws-config.py 或 ~/.local/bin/adws-config）", "ADWS-Config not found (tools/adws-config.py or ~/.local/bin/adws-config)"));
        return;
    };

    let mut command = Command::new("python3");
    command.arg(&tool).env_remove("GDK_BACKEND");
    if !tab.is_empty() { command.arg("--tab").arg(tab); }
    let result = command.spawn();
    if let Err(e) = result {
        tracing::warn!(%e, "cannot launch ADWS-Config");
    }
}

pub fn launch_application(app_id: &str, administrator: bool) {
    application_action(app_id, if administrator {Some("--administrator")} else {None});
}

pub fn pin_application(app_id: &str, enabled: bool) {
    application_action(app_id, Some(if enabled {"--pin"} else {"--unpin"}));
}

fn application_action(app_id: &str, option: Option<&str>) {
    let candidates = application_tool_candidates("tools/adws_app_launch.py");
    let Some(tool) = candidates.into_iter().find(|path| path.is_file()) else {
        tracing::error!("ADWS application launch helper is missing");
        return;
    };
    tracing::info!(%app_id, ?option, "Application action from taskbar");
    let mut command = Command::new("python3");
    command.arg(tool);
    // Options precede -- so an application ID can never become a helper option.
    if let Some(option) = option {
        command.arg(option);
    }
    match command.arg("--").arg(app_id).env_remove("GDK_BACKEND").spawn() {
        Ok(mut child) => { std::thread::spawn(move || { let _ = child.wait(); }); }
        Err(error) => tracing::error!(%error, "Cannot start application launch helper"),
    }
}

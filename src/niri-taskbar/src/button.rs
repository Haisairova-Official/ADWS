use std::{cell::RefCell, fmt::Debug, path::PathBuf, rc::Rc};

use waybar_cffi::gtk::{
    self as gtk, Border, CssProvider, IconLookupFlags, IconSize, IconTheme, ReliefStyle,
    StateFlags,
    gdk_pixbuf::Pixbuf,
    prelude::*,

};

use crate::state::State;

/// A taskbar button.
pub struct Button {
    app_id: Option<String>,
    button: gtk::Button,
    badge: gtk::Label,
    icon: gtk::Overlay,
    state: State,
    members: Rc<RefCell<Vec<(u64, String)>>>,
}

impl Debug for Button {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Button")
            .field("app_id", &self.app_id)
            .finish()
    }
}

// These have to be declared as thread locals because Gtk objects are (generally) not Send.
// Practically, we're likely to be doing everything from the main thread anyway, but Glib can
// figure that out.
thread_local! {
    static BUTTON_CSS_PROVIDER: CssProvider = {
        let css = CssProvider::new();
        if let Err(e) = css.load_from_data(include_bytes!("style.css")) {
            tracing::error!(%e, "CSS parse error");
        }

        css
    };

    static ICON_THEME: IconTheme = {
        IconTheme::default().unwrap_or_default()
    };

    static ACTIVE_CONTEXT_MENU: RefCell<Option<gtk::Menu>> = RefCell::new(None);
}

impl Button {
    /// Instantiates a new button, including creating a new Gtk button internally.
    #[tracing::instrument(level = "TRACE", fields(app_id = &window.app_id))]
    pub fn new(state: &State, window: &niri_ipc::Window) -> Self {
        let state = state.clone();

        // Set up the basic image button.
        //
        // Note that we don't actually set the image here: we need to know the size before doing so
        // in order to load the most appropriate icon from the icon theme, and we won't know that
        // until we get an actual size allocation.
        let button = gtk::Button::new();
        button.set_always_show_image(true);
        button.set_relief(ReliefStyle::None);
        let icon = gtk::Overlay::new();
        icon.add(&gtk::Image::from_icon_name(Some("application-x-executable"),IconSize::Button));
        let badge = gtk::Label::new(None);
        badge.style_context().add_class("mnws-window-count");
        badge.set_halign(gtk::Align::End);
        badge.set_valign(gtk::Align::End);
        badge.set_no_show_all(true);
        icon.add_overlay(&badge);
        icon.set_overlay_pass_through(&badge,true);
        button.set_image(Some(&icon));

        // Provide the base CSS for each button that users can then extend.
        BUTTON_CSS_PROVIDER.with(|provider| {
            badge.style_context().add_provider(provider, gtk::STYLE_PROVIDER_PRIORITY_APPLICATION - 1);
            button
                .style_context()
                .add_provider(provider, gtk::STYLE_PROVIDER_PRIORITY_APPLICATION - 1);
        });

        let app_id = window.app_id.clone();
        let icon_path = app_id
            .as_deref()
            .and_then(|id| state.icon_cache().lookup(id));

        let button = Self {
            app_id,
            button,
            badge,
            icon,
            state,
            members: Rc::new(RefCell::new(vec![(window.id, window.title.clone().unwrap_or_default())])),
        };

        // Set up our event handlers. It's easier to do this with self already available.
        button.connect_click_handler(window.id);
        button.connect_context_menu(window.id);
        button.connect_size_allocate(icon_path);

        button
    }

    pub fn set_group(&self, members: Vec<(u64, String)>) {
        let count = members.len();
        let caption = if count > 1 { count.to_string() } else { String::new() };
        self.badge.set_text(&caption);
        self.badge.set_visible(count>1);
        self.button.set_tooltip_text(Some(&members.iter().map(|(_,title)|title.as_str()).collect::<Vec<_>>().join("\n")));
        *self.members.borrow_mut() = members;
    }

    /// Sets whether the window represented by this button is currently focused.
    #[tracing::instrument(level = "TRACE")]
    pub fn set_focus(&self, focus: bool) {
        let context = self.button.style_context();

        if focus {
            context.add_class("focused");
            context.remove_class("urgent");
        } else {
            context.remove_class("focused");
        }
    }

    /// Sets the window title.
    #[tracing::instrument(level = "TRACE")]
    pub fn set_title(&self, title: Option<&str>) {
        self.button.set_tooltip_text(title);

        // Apply any app styling rules.
        if let Some(app_id) = &self.app_id {
            if let Some(title) = title {
                let config = self.state.config();
                let context = self.button.style_context();

                // First, remove all the possible classes for this app.
                for class in config.app_classes(app_id) {
                    context.remove_class(class);
                }

                // Now add the classes that actually do match.
                for class in config.app_matches(app_id, title) {
                    context.add_class(class);
                }
            }
        }
    }

    /// Sets the window to urgent: that is, needing attention.
    ///
    /// This state is automatically cleared the next time the window is focused.
    #[tracing::instrument(level = "TRACE")]
    pub fn set_urgent(&self) {
        self.button.style_context().add_class("urgent");
    }

    /// Returns the actual [`gtk::Button`] widget.
    pub fn widget(&self) -> &gtk::Button {
        &self.button
    }

    fn connect_click_handler(&self, window_id: u64) {
        let state = self.state.clone();

        let members = self.members.clone();
        self.button.connect_clicked(move |button| {
            if members.borrow().len() > 1 {
                let menu = gtk::Menu::new();
                for (id,title) in members.borrow().iter() {
                    let item = gtk::MenuItem::with_label(title);
                    let state = state.clone();
                    let id = *id;
                    item.connect_activate(move |_| { let _ = state.niri().activate_window(id); });
                    menu.append(&item);
                }
                show_menu(menu, Some(button));
                return;
            }
            if let Err(e) = state.niri().activate_window(window_id) {
                tracing::warn!(%e, id = window_id, "error trying to activate window");
            }
        });
    }

    /// Opens a small context menu on right click (focus / minimize / close).
    fn connect_context_menu(&self, window_id: u64) {
        let state = self.state.clone();

        let members = self.members.clone();
        self.button.connect_button_press_event(move |_button, event| {
            if event.button() != 3 {
                return gtk::glib::Propagation::Proceed;
            }

            tracing::info!(id = window_id, "{}", crate::i18n::text("打开窗口右键菜单", "Open window context menu"));
            let menu = gtk::Menu::new();
            if members.borrow().len() > 1 {
                for (id,title) in members.borrow().iter() {
                    let item = gtk::MenuItem::with_label(title);
                    let submenu = gtk::Menu::new();
                    for (caption, action) in [(crate::i18n::text("聚焦窗口", "Focus window"),0),
                        (crate::i18n::text("最小化 / 还原", "Minimize / restore"),1),
                        (crate::i18n::text("关闭窗口", "Close window"),2)] {
                        let action_item = gtk::MenuItem::with_label(caption);
                        let state = state.clone(); let id = *id;
                        action_item.connect_activate(move |_| {
                            let result = match action {0 => state.niri().activate_window(id),1=>state.niri().toggle_window_minimized(id),_=>state.niri().close_window(id)};
                            if let Err(error) = result {tracing::warn!(%error,id,"group window action failed");}
                        });
                        submenu.append(&action_item);
                    }
                    item.set_submenu(Some(&submenu)); menu.append(&item);
                }
                show_menu(menu, None);
                return gtk::glib::Propagation::Stop;
            }
            let focus = gtk::MenuItem::with_label(crate::i18n::text("聚焦窗口", "Focus window"));
            let minimize = gtk::MenuItem::with_label(crate::i18n::text("最小化 / 还原", "Minimize / restore"));
            let close = gtk::MenuItem::with_label(crate::i18n::text("关闭窗口", "Close window"));

            let clicked_state = state.clone();
            focus.connect_activate(move |_| {
                if let Err(e) = clicked_state.niri().activate_window(window_id) {
                    tracing::warn!(%e, id = window_id, "error trying to activate window");
                }
            });

            let clicked_state = state.clone();
            minimize.connect_activate(move |_| {
                if let Err(e) = clicked_state.niri().toggle_window_minimized(window_id) {
                    tracing::warn!(%e, id = window_id, "error toggling window minimize state");
                }
            });

            let clicked_state = state.clone();
            close.connect_activate(move |_| {
                if let Err(e) = clicked_state.niri().close_window(window_id) {
                    tracing::warn!(%e, id = window_id, "error trying to close window");
                }
            });

            menu.append(&focus);
            menu.append(&minimize);
            menu.append(&close);
            crate::menu_style::apply(&menu);
            menu.show_all();
            menu.connect_deactivate(|_| {
                ACTIVE_CONTEXT_MENU.with(|slot| {
                    slot.borrow_mut().take();
                });
            });

            ACTIVE_CONTEXT_MENU.with(|slot| {
                let old = slot.borrow_mut().take();
                if let Some(old) = old {
                    old.popdown();
                }
                *slot.borrow_mut() = Some(menu.clone());
            });
            // 传入触发事件，让 GTK 在指针位置弹出菜单；不传时部分 Wayland 环境会定位失败。
            menu.popup_at_pointer(Some(event));

            gtk::glib::Propagation::Stop
        });
    }

    #[tracing::instrument(level = "TRACE")]
    fn connect_size_allocate(&self, icon_path: Option<PathBuf>) {
        let last_size = RefCell::new(None);
        let icon = self.icon.clone();
        let vertical = self.state.config().vertical();
        let lane = (self.state.config().thickness() / self.state.config().rows()) as i32;

        self.button
            .connect_size_allocate(move |button, allocation| {
                // Figure out if we actually need to redraw, since it's relatively expensive.
                //
                // The first condition is pretty easy: is there an image on the button? If not,
                // then it's the first draw, and we have no choice but to draw.
                let mut must_redraw = button.image().is_none();

                // Otherwise, let's check if the size allocation has changed since the last time
                // this was called.
                if !must_redraw {
                    if let Some(last_size) = last_size.take() {
                        if last_size != (allocation.width(), allocation.height()) {
                            must_redraw = true;
                        }
                    } else {
                        must_redraw = true;
                    }

                    last_size.replace(Some((allocation.width(), allocation.height())));
                }

                if must_redraw {
                    // Calculate the actual image size we need.
                    //
                    // Gtk3 doesn't provide a useful way to get the actual inner size of the
                    // element after applying style rules, so we have to do that here, otherwise we
                    // may draw the image too big and cause the container to grow. (Which will then
                    // result in another size allocate signal, which will result in another
                    // recalculation, which then results in your taskbar taking up your entire
                    // display within a few seconds.)
                    //
                    // Blindly using StateFlags::NORMAL probably isn't actually the right
                    // behaviour, but it's the best we've got for now.
                    //
                    // Note that we have to do this _after_ we figure out if we need to redraw:
                    // calculating the style information is apparently expensive enough that Gtk
                    // essentially busy-waits, which (a) burns CPU, and (b) means that :hover
                    // styles don't get applied. What that means in practice is that, if waybar's
                    // dynamically reloading CSS feature is enabled, sizing changes won't be
                    // applied after the button is first rendered.
                    //
                    // That seems to be the price we have to pay, though, so here we are.
                    let context = button.style_context();
                    let border = context.border(StateFlags::NORMAL);
                    let margin = context.margin(StateFlags::NORMAL);
                    let padding = context.padding(StateFlags::NORMAL);

                    let (available, decoration) = if vertical {
                        (allocation.width(), border.horizontal_size()+margin.horizontal_size()+padding.horizontal_size())
                    } else {
                        (allocation.height(), border.vertical_size()+margin.vertical_size()+padding.vertical_size())
                    };
                    let size = (available.min(lane) - decoration).max(1);

                    // Now we know the size, we can actually load the image.
                    let image =
                        Self::icon_image(icon_path.as_ref(), button, size).unwrap_or_else(|| {
                            // If we can't find an application icon, then we need to use a
                            // fallback.
                            static FALLBACK_ICON: &str = "application-x-executable";

                            // We'll try to look the icon up in the default icon theme, since then
                            // we can load up the actual image and control its scaling and display.
                            ICON_THEME
                                .with(|theme| {
                                    theme.lookup_icon_for_scale(
                                        FALLBACK_ICON,
                                        size,
                                        button.scale_factor(),
                                        IconLookupFlags::empty(),
                                    )
                                })
                                .and_then(|info| {
                                    Self::icon_image(info.filename().as_ref(), button, size)
                                })
                                .unwrap_or_else(|| {
                                    // But, if all else fails, we'll just use the default button
                                    // size and YOLO it.
                                    gtk::Image::from_icon_name(
                                        Some(FALLBACK_ICON),
                                        IconSize::Button,
                                    )
                                })
                        });

                    // Finally, we can set the button image. Doing this from the callback doesn't
                    // seem to work reliably for reasons I don't understand at all, but doing it
                    // from the main loop as soon as possible does. :shrug:
                    let icon = icon.clone();
                    gtk::glib::source::idle_add_local_once(move || {
                        if let Some(old) = icon.child() { icon.remove(&old); }
                        icon.add(&image);
                        image.show();
                    });
                }
            });
    }

    fn icon_image(
        icon_path: Option<&PathBuf>,
        button: &gtk::Button,
        size: i32,
    ) -> Option<gtk::Image> {
        let size = size * button.scale_factor();

        icon_path
            .and_then(
                |path| match Pixbuf::from_file_at_scale(path, size, size, true) {
                    Ok(pixbuf) => Some(pixbuf),
                    Err(e) => {
                        tracing::info!(%e, ?path, "cannot load icon");
                        None
                    }
                },
            )
            .and_then(|pixbuf| pixbuf.create_surface(0, button.window().as_ref()))
            .map(|surface| gtk::Image::from_surface(Some(&surface)))
    }
}

trait BorderExt {
    fn vertical_size(&self) -> i32;
    fn horizontal_size(&self) -> i32;
}

impl BorderExt for Border {
    fn horizontal_size(&self) -> i32 { (self.left + self.right).into() }
    fn vertical_size(&self) -> i32 {
        (self.top + self.bottom).into()
    }
}

fn show_menu(menu: gtk::Menu, anchor: Option<&gtk::Button>) {
    crate::menu_style::apply(&menu);
    menu.show_all();
    menu.connect_deactivate(|_| { ACTIVE_CONTEXT_MENU.with(|slot| {slot.borrow_mut().take();}); });
    ACTIVE_CONTEXT_MENU.with(|slot| {
        let old = slot.borrow_mut().take();
        if let Some(old) = old {old.popdown();}
        *slot.borrow_mut() = Some(menu.clone());
    });
    if let Some(button) = anchor {
        menu.popup_at_widget(button, gtk::gdk::Gravity::SouthWest, gtk::gdk::Gravity::NorthWest, None::<&gtk::gdk::Event>);
    } else {menu.popup_at_pointer(gtk::current_event().as_ref());}
}

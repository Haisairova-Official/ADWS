//! Run in an isolated display: xvfb-run cargo test --lib -- --ignored.
use super::*;
use gtk::prelude::*;
use serde_json::json;

fn snapshot() -> Snapshot {
    let mut stream = niri::WindowSet::new(false);
    stream.with_event(serde_json::from_value(json!({"WorkspacesChanged":{"workspaces":[{
        "id":10,"idx":1,"name":null,"output":"DP-1","is_urgent":false,
        "is_active":true,"is_focused":true,"active_window_id":2}]}})).unwrap());
    let windows: Vec<_> = ["foot","foot","firefox","code","unknown"].iter().enumerate().map(|(i,app)|json!({
        "id":i+1,"title":format!("Window {}",i+1),"app_id":app,"pid":null,
        "workspace_id":10,"is_focused":i==1,"is_floating":false,"is_urgent":false,
        "focus_timestamp":null,"layout":{"pos_in_scrolling_layout":[1,1],
        "tile_size":[800.0,600.0],"window_size":[800,600],
        "tile_pos_in_workspace_view":[0.0,0.0],"window_offset_in_tile":[0.0,0.0]}
    })).collect();
    stream.with_event(serde_json::from_value(json!({"WindowsChanged":{"windows":windows}})).unwrap()).unwrap()
}

fn settle() {
    for _ in 0..50 {
        while gtk::events_pending() { gtk::main_iteration(); }
        std::thread::sleep(std::time::Duration::from_millis(5));
    }
}

#[test]
#[ignore = "requires an isolated GTK display"]
fn panel_geometry_groups_and_colors() {
    gtk::init().unwrap();
    let base=gtk::CssProvider::new();
    base.load_from_path(concat!(env!("CARGO_MANIFEST_DIR"),"/../../config/waybar/style-bottom.css")).unwrap();
    gtk::StyleContext::add_provider_for_screen(&gtk::gdk::Screen::default().unwrap(),&base,gtk::STYLE_PROVIDER_PRIORITY_APPLICATION);
    let css=gtk::CssProvider::new();
    css.load_from_data(b".niri-taskbar button {min-width:0; min-height:0; transition:none;} .niri-taskbar button.focused {background:#123456;} .niri-taskbar button:hover:not(.focused) {background:#cc2244;}").unwrap();
    gtk::StyleContext::add_provider_for_screen(&gtk::gdk::Screen::default().unwrap(),&css,gtk::STYLE_PROVIDER_PRIORITY_APPLICATION);
    for vertical in [false,true] {
        for rows in [1,2] {
            for grouped in [false,true] {
                let config: Config=serde_json::from_value(json!({"vertical":vertical,"rows":rows,"thickness":64,"group_windows":grouped})).unwrap();
                let grid=gtk::Grid::new();
                grid.set_row_homogeneous(!vertical);
                grid.set_column_homogeneous(vertical);
                grid.style_context().add_class("niri-taskbar");
                let window=gtk::Window::new(gtk::WindowType::Toplevel);
                window.add(&grid);
                window.set_default_size(if vertical {64}else{320},if vertical {320}else{64});
                let mut instance=Instance::new(State::new(config),grid.clone());
                let filter=Arc::new(Mutex::new(output::Filter::ShowAll));
                MainContext::default().block_on(instance.process_window_snapshot(snapshot(),filter.clone()));
                window.show_all();settle();
                assert_eq!(grid.children().len(),if grouped{4}else{5});
                let first=instance.buttons[&1].widget();
                assert_eq!(first.style_context().has_class("focused"),grouped);
                if grouped {
                    assert!(!first.has_tooltip());
                    #[allow(deprecated)]
                    let color: gtk::gdk::RGBA=first.style_context().style_property_for_state("background-color",gtk::StateFlags::NORMAL).get().unwrap();
                    assert!((color.red()-18.0/255.0).abs()<0.01,"custom focus color was overridden: {color:?}");
                }
                first.set_state_flags(gtk::StateFlags::PRELIGHT,false);settle();
                let hover:gtk::gdk::RGBA=first.style_context().style_property_for_state("background-color",gtk::StateFlags::PRELIGHT).get().unwrap();
                assert!((hover.red()-if grouped {18.0/255.0}else{204.0/255.0}).abs()<0.01,"hover color was overridden");
                first.unset_state_flags(gtk::StateFlags::PRELIGHT);
                for (i,id) in instance.displayed.iter().enumerate() {
                    let (x,y)=grouping::cell(i,rows,vertical);
                    assert_eq!(grid.child_at(x,y).unwrap(),*instance.buttons[id].widget());
                }
                assert!(if vertical {window.allocated_width()<=64}else{window.allocated_height()<=64},"short axis expanded unexpectedly");
                // Closing a representative must promote the surviving window, with focus intact.
                let remaining=snapshot().into_iter().filter(|w|w.id!=1).collect();
                MainContext::default().block_on(instance.process_window_snapshot(remaining,filter));
                settle();
                assert!(instance.buttons[&2].widget().style_context().has_class("focused"));
                assert_eq!(grid.children().len(),4);
                unsafe {window.destroy();}
            }
        }
    }
}

//! GLib detaches a future when its JoinHandle is dropped. Own cancellation
//! explicitly so unloading a module/stream also releases its child listeners.
use waybar_cffi::gtk::glib;

#[derive(Default)]
pub(crate) struct Tasks(pub Vec<glib::JoinHandle<()>>);
impl Drop for Tasks {
    fn drop(&mut self) {
        for task in &self.0 { task.abort(); }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{cell::Cell, rc::Rc, time::Duration};
    #[test]
    #[ignore = "requires an isolated GLib context"]
    fn dropping_module_cancels_nested_listeners() {
        let context = glib::MainContext::default();
        let _owner = context.acquire().unwrap();
        let retained = Rc::new(Cell::new(0));
        let weak = Rc::downgrade(&retained);
        let child = retained.clone();
        let module = crate::TaskbarModule { _tasks: Tasks(vec![context.spawn_local(async move {
            let _children = Tasks(vec![glib::spawn_future_local(async move {
                let _retained = child;
                std::future::pending::<()>().await;
            })]);
            std::future::pending::<()>().await;
        })]) };
        drop(retained);
        context.block_on(glib::timeout_future(Duration::from_millis(10)));
        assert!(weak.upgrade().is_some());
        drop(module);
        context.block_on(glib::timeout_future(Duration::from_millis(10)));
        assert!(weak.upgrade().is_none(), "a detached child survived module unload");
    }
}

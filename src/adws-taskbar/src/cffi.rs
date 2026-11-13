//! Host ADWS's existing GTK modules. Both ABI versions use caller-owned config
//! entries during init and a stable callback context until deinit returns.
use gtk::{glib, prelude::*};
use serde_json::Value;
use std::{
    any::Any,
    cell::RefCell,
    collections::BTreeMap,
    ffi::{c_char, c_int, c_void, CStr, CString},
    ptr,
    sync::{
        atomic::{AtomicBool, AtomicPtr, Ordering},
        Arc,
    },
};

#[link(name = "gmodule-2.0")]
unsafe extern "C" {
    fn g_module_open(path: *const c_char, flags: c_int) -> *mut c_void;
    fn g_module_error() -> *const c_char;
    fn g_module_symbol(
        module: *mut c_void,
        name: *const c_char,
        address: *mut *mut c_void,
    ) -> c_int;
    fn g_module_make_resident(module: *mut c_void);
    fn g_module_close(module: *mut c_void) -> c_int;
}

struct Library(*mut c_void);
impl Library {
    fn open(path: &str) -> Result<Self, String> {
        let path = CString::new(path).map_err(|e| e.to_string())?;
        let handle = unsafe { g_module_open(path.as_ptr(), 2) }; // G_MODULE_BIND_LOCAL
        if handle.is_null() {
            let error = unsafe { CStr::from_ptr(g_module_error()) };
            return Err(error.to_string_lossy().into_owned());
        }
        Ok(Self(handle))
    }

    fn symbol(&self, name: &CStr) -> Result<*mut c_void, String> {
        let mut result = ptr::null_mut();
        if unsafe { g_module_symbol(self.0, name.as_ptr(), &mut result) } == 0 || result.is_null() {
            return Err(format!("missing symbol {}", name.to_string_lossy()));
        }
        Ok(result)
    }
}

impl Drop for Library {
    fn drop(&mut self) {
        unsafe { g_module_close(self.0) };
    }
}

#[repr(C)]
struct InitInfo {
    context: *const Context,
    version: *const c_char,
    root: unsafe extern "C" fn(*const Context) -> *mut gtk::ffi::GtkContainer,
    queue: unsafe extern "C" fn(*const Context),
}
#[repr(C)]
struct Entry {
    key: *const c_char,
    value: *const c_char,
}

type Init = unsafe extern "C" fn(*const InitInfo, *const Entry, usize) -> *mut c_void;
type InstanceFn = unsafe extern "C" fn(*mut c_void);

type Finish = unsafe extern "C" fn();
thread_local! {
    static FINISHERS: RefCell<BTreeMap<usize, Finish>> = const { RefCell::new(BTreeMap::new()) };
}

/// Called after every instance has been deinitialized, including partial mounts.
pub fn finish_shutdown() {
    for finish in FINISHERS.take().into_values() {
        unsafe { finish() };
    }
}

struct Pending {
    instance: AtomicPtr<c_void>,
    scheduled: AtomicBool,
    update: Option<InstanceFn>,
}

struct Context {
    root: gtk::EventBox,
    pending: Arc<Pending>,
}
unsafe extern "C" fn get_root(context: *const Context) -> *mut gtk::ffi::GtkContainer {
    unsafe { (*context).root.as_ptr().cast() }
}
unsafe extern "C" fn queue_update(context: *const Context) {
    // Called from any module thread. GTK and the instance itself are accessed
    // only on the main loop; clearing instance invalidates pending callbacks.
    let pending = unsafe { Arc::clone(&(*context).pending) };
    if pending.update.is_none() || pending.scheduled.swap(true, Ordering::AcqRel) {
        return;
    }
    glib::idle_add_once(move || {
        pending.scheduled.store(false, Ordering::Release);
        let instance = pending.instance.load(Ordering::Acquire);
        if !instance.is_null() {
            if let Some(update) = pending.update {
                unsafe { update(instance) };
            }
        }
    });
}

struct Mounted {
    context: Box<Context>,
    _info: Box<InitInfo>,
    _library: Library,
    deinit: InstanceFn,
}
impl Drop for Mounted {
    fn drop(&mut self) {
        let instance = self
            .context
            .pending
            .instance
            .swap(ptr::null_mut(), Ordering::AcqRel);
        if !instance.is_null() {
            unsafe { (self.deinit)(instance) };
        }
    }
}

pub fn mount(name: &str, config: &Value, root: &gtk::EventBox) -> Result<Box<dyn Any>, String> {
    let path = config["module_path"]
        .as_str()
        .ok_or_else(|| format!("{name}: missing module_path"))?;
    let library = Library::open(path)?;
    let version = unsafe { *library.symbol(c"wbcffi_version")?.cast::<usize>() };
    if !matches!(version, 1 | 2) {
        return Err(format!("{name}: unsupported CFFI ABI {version}"));
    }
    // The symbol signatures below are fixed by the validated CFFI ABI.
    let init: Init = unsafe { std::mem::transmute(library.symbol(c"wbcffi_init")?) };
    let deinit: InstanceFn = unsafe { std::mem::transmute(library.symbol(c"wbcffi_deinit")?) };
    let update = library
        .symbol(c"wbcffi_update")
        .ok()
        .map(|p| unsafe { std::mem::transmute::<*mut c_void, InstanceFn>(p) });
    let mut pairs = Vec::new();
    for (key, value) in config
        .as_object()
        .ok_or("module config must be an object")?
    {
        let value = match (version, value.as_str()) {
            (1, Some(s)) => s.to_owned(),
            _ => value.to_string(),
        };
        pairs.push((
            CString::new(key.as_str()).map_err(|e| e.to_string())?,
            CString::new(value).map_err(|e| e.to_string())?,
        ));
    }
    let entries: Vec<_> = pairs
        .iter()
        .map(|(k, v)| Entry {
            key: k.as_ptr(),
            value: v.as_ptr(),
        })
        .collect();
    let context = Box::new(Context {
        root: root.clone(),
        pending: Arc::new(Pending {
            instance: AtomicPtr::new(ptr::null_mut()),
            scheduled: AtomicBool::new(false),
            update,
        }),
    });
    let info = Box::new(InitInfo {
        context: &*context,
        version: c"ADWS native taskbar".as_ptr(),
        root: get_root,
        queue: queue_update,
    });
    // GTK types and closures registered by a plugin may survive its last widget.
    unsafe { g_module_make_resident(library.0) };
    if let Ok(address) = library.symbol(c"adws_panel_finish_shutdown") {
        let finish = unsafe { std::mem::transmute::<*mut c_void, Finish>(address) };
        FINISHERS.with_borrow_mut(|entries| entries.insert(address as usize, finish));
    }
    let instance = unsafe { init(&*info, entries.as_ptr(), entries.len()) };
    if instance.is_null() {
        return Err(format!("{name}: {path} failed to initialize"));
    }
    context.pending.instance.store(instance, Ordering::Release);
    if let Some(update) = update {
        unsafe { update(instance) };
    }
    Ok(Box::new(Mounted {
        context,
        _info: info,
        _library: library,
        deinit,
    }))
}

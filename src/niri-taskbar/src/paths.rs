use std::path::PathBuf;

// Resolve installed commands before the build-directory fallback: update packages
// are compiled in staging and then moved into the persistent installation path.
pub(crate) fn application_tool_candidates(relative: &str) -> Vec<PathBuf> {
    let mut entries = Vec::new();
    if let Some(entry) = waybar_cffi::gtk::glib::find_program_in_path("adws") { entries.push(entry); }
    if let Ok(home) = std::env::var("HOME") {
        entries.push(PathBuf::from(home).join(".local/bin/adws"));
    }
    let mut candidates: Vec<_> = entries.into_iter().filter_map(|entry| {
        std::fs::canonicalize(entry).ok().and_then(|entry| entry.parent().map(|root| root.join(relative)))
    }).collect();
    candidates.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..").join(relative));
    candidates
}

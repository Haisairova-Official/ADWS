use std::collections::HashMap;

use itertools::Itertools;
use regex::Regex;
use serde::{Deserialize, Deserializer};

/// The taskbar configuration.
#[derive(Debug, Deserialize)]
pub struct Config {
    #[serde(default)]
    apps: HashMap<String, Vec<AppConfig>>,
    #[serde(default)]
    vertical: bool,
    #[serde(default)]
    position: String,
    #[serde(default)]
    window_peek: bool,
    #[serde(default)]
    window_animations: bool,
    #[serde(default = "default_animation_duration")]
    animation_duration: u32,
    #[serde(default)]
    preview_helper: String,
    #[serde(default)]
    group_windows: bool,
    #[serde(default = "default_rows")]
    rows: u32,
    #[serde(default = "default_thickness")]
    thickness: u32,
    #[serde(default)]
    notifications: Notifications,
    #[serde(default)]
    show_all_outputs: bool,
    #[serde(default)]
    current_workspace_only: bool,
    /// 窗口图标栏的可选最大宽度；默认使用其他组件之外的全部可用空间。
    #[serde(default)]
    max_width: Option<u32>,
    /// 没有 max_width 时，图标栏可占底栏宽度的比例（0~1）。
    #[serde(default)]
    icon_zone_fraction: Option<f32>,
}

impl Default for Config {
    fn default() -> Self {
        Self { apps: Default::default(), vertical: false, position: String::new(), window_peek: false, window_animations: false, animation_duration: default_animation_duration(), preview_helper: String::new(), group_windows: false,
            rows: default_rows(), thickness: default_thickness(), notifications: Default::default(),
            show_all_outputs: false, current_workspace_only: false, max_width: None, icon_zone_fraction: None }
    }
}

#[derive(Debug, Deserialize)]
pub struct Notifications {
    #[serde(default = "default_true")]
    enabled: bool,
    #[serde(default)]
    map_app_ids: HashMap<String, String>,
    #[serde(default = "default_true")]
    use_desktop_entry: bool,
    #[serde(default)]
    use_fuzzy_matching: bool,
}

impl Default for Notifications {
    fn default() -> Self {
        Self {
            enabled: true,
            map_app_ids: Default::default(),
            use_desktop_entry: true,
            use_fuzzy_matching: Default::default(),
        }
    }
}

fn default_animation_duration() -> u32 { 280 }

fn default_rows() -> u32 { 1 }
fn default_thickness() -> u32 { 36 }

fn default_true() -> bool {
    true
}

impl Config {
    pub fn position(&self) -> &str { &self.position }
    pub fn preview_helper(&self) -> &str { &self.preview_helper }
    pub fn window_peek(&self) -> bool { self.window_peek }
    pub fn window_animations(&self) -> bool { self.window_animations }
    pub fn animation_duration(&self) -> u32 { self.animation_duration.clamp(80, 1000) }
    pub fn vertical(&self) -> bool { self.vertical }
    pub fn group_windows(&self) -> bool { self.group_windows }
    pub fn rows(&self) -> u32 { self.rows.clamp(1, 2) }
    pub fn thickness(&self) -> u32 { self.thickness.clamp(24, 160) }
    /// Returns all possible CSS classes that a particular application might have set.
    pub fn app_classes(&self, app_id: &str) -> Vec<&str> {
        self.apps
            .get(app_id)
            .map(|configs| {
                configs
                    .iter()
                    .map(|config| config.class.as_str())
                    .collect_vec()
            })
            .unwrap_or_default()
    }

    /// Returns the actual CSS classes that should be set for the given application and title.
    pub fn app_matches<'a>(
        &'a self,
        app_id: &str,
        title: &'a str,
    ) -> Box<dyn Iterator<Item = &'a str> + 'a> {
        match self.apps.get(app_id) {
            Some(configs) => Box::new(
                configs
                    .iter()
                    .filter(|config| config.re.is_match(title))
                    .map(|config| config.class.as_str()),
            ),
            None => Box::new(std::iter::empty()),
        }
    }

    /// Returns true if notification support is enabled.
    pub fn notifications_enabled(&self) -> bool {
        self.notifications.enabled
    }

    /// Returns any mapping that might exist for this app ID.
    pub fn notifications_app_map(&self, app_id: &str) -> Option<&'_ str> {
        self.notifications
            .map_app_ids
            .get(app_id)
            .map(String::as_str)
    }

    /// Returns true if notification support should use the desktop entry as a
    /// fallback.
    pub fn notifications_use_desktop_entry(&self) -> bool {
        self.notifications.use_desktop_entry
    }

    pub fn notifications_use_fuzzy_matching(&self) -> bool {
        self.notifications.use_fuzzy_matching
    }

    pub fn show_all_outputs(&self) -> bool {
        self.show_all_outputs
    }

    /// Returns true if only windows on the active workspace should be shown.
    pub fn current_workspace_only(&self) -> bool {
        self.current_workspace_only
    }

    pub fn max_width(&self) -> Option<u32> {
        self.max_width
    }

    pub fn icon_zone_fraction(&self) -> Option<f32> {
        self.icon_zone_fraction
    }
}

#[derive(Deserialize, Debug)]
struct AppConfig {
    #[serde(rename = "match", deserialize_with = "deserialise_regex")]
    re: Regex,
    class: String,
}

fn deserialise_regex<'de, D>(de: D) -> Result<Regex, D::Error>
where
    D: Deserializer<'de>,
{
    Regex::new(&String::deserialize(de)?).map_err(serde::de::Error::custom)
}

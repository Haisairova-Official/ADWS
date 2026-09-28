# Config.ad-yml

在“设置 → 关于”使用“导出全局配置”或“导入全局配置”。默认文件名为 `Config.ad-yml`，文件内容使用安全解析的 YAML，格式版本为 1。

包含桌面布局与偏好、任务栏布局、动效、时钟、固定应用、插件设置、Waybar 样式与配色，以及当前用户的 `mimeapps.list` 默认应用关联。仅导出本机存在的配置项目。

图片、插件程序、字体、录屏缓存和整个 Niri 配置不打包。跨机器使用时需要单独安装对应应用和插件，并调整图片、配色引用等本地路径；文件中的路径保持原样。配置可能包含自定义命令或插件 API 地址，请只导入可信文件，并在分享前检查内容。

导入会先验证格式并展示覆盖范围，确认后保存；原配置备份保存在 `$XDG_STATE_HOME/adws/config-backups/`（默认 `~/.local/state/adws/config-backups/`）。写入失败会恢复导入前的文件。完成后重新打开设置，并重启桌面和任务栏使其生效。

## English

Use **Settings → About → Export global configuration / Import global configuration**. The default filename is `Config.ad-yml`; it contains safely parsed YAML with format version 1.

The bundle includes existing desktop layout/preferences, taskbar layout, animations, clock, pinned apps, plugin settings, Waybar styling/palette and the user's `mimeapps.list` associations. Images, plugin programs, fonts, caches and the full Niri configuration are excluded. Install required applications/plugins separately and adjust local paths when moving between machines. Paths are preserved as written. Only import trusted files; review custom commands and plugin API settings before sharing.

Import validates the bundle and asks you to confirm the overwrite list. Backups live in `$XDG_STATE_HOME/adws/config-backups/` (normally `~/.local/state/adws/config-backups/`). A write failure restores previous files. Reopen Settings and restart the desktop/taskbar to apply the imported configuration.

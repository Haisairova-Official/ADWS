# ADWS 1.30 Pre-Release

构建日期 / Build date: 2026-09-21

## 最新更新

- MNWS 正式更名为 ADWS — Akizuki’s Desktop Workspace Solution。新的名字不再限定于 Niri，但当前版本仍以 Niri 为主要支持环境。命令统一改为 adws，安装时迁移旧配置，不保留 mnws 命令别名。
- 优化了 Peek，出现更早、切换更流畅，按桌面平铺顺序排列，并增加浮入淡出效果。
- 将设置入口统一为“桌面设置”和“任务栏设置”，任务栏样式、组件布局和插件配置终于放到一起了。
- 取消了滚轮对任务栏设置控件的误调整，滚动页面时不再顺手改掉配置。
- 任务栏项目卡右键新增“打开新窗口”和“以管理员权限运行”。
- 桌面图标支持原位重命名，非法名称和重名直接提示，不再另外弹出一个平铺窗口。
- 修复了部分输入法主题下，重命名切换中文导致桌面会话卡死的问题。
- 新建文件和文件夹也使用原位编辑，默认名称为 text.txt、markdown.md 和 folder；取消不会留下空文件。
- 新增固定应用：点击启动，本桌面打开后进入活动区，关闭后回到原来的固定位置。
- 同屏其他桌面运行的固定应用显示三点角标，点击回到最近操作的窗口，Peek 可继续按桌面和平铺顺序切换；其他物理屏幕按未开启处理。
- 固定区分隔线实时跟随聚焦背景色，没有活动窗口时也会保留。（C）
- 检查更新新增 Beta 渠道，支持 adws -u --preview 和 adws --update --preview；设置中也可选择，默认仍检查稳定版。（D）
- 修复了任务栏在开启窗口预览下偶发的卡顿bug。（1.28）
- 新增旧安装的一次性迁移与配置备份；旧插件单独保存，提供适配 ADWS 的 NCMLyricsBar。
- 提供 ADWS 1.30 Pre-Release 源码包与 Arch Linux x86_64 预构建包。
- 新增首次设置向导：没有本地配置时自动打开，也可从设置重新进入；支持动效、配色预览、默认应用和启动器，确认后统一保存。
- 新增全局配置导入和导出，使用 Config.ad-yml；导入前校验并确认覆盖范围，保留备份，写入失败时恢复原配置。
- 初始设置新增壁纸页：默认保留现有设置，选图预览后确认应用；高级选项支持 awww、swww 和 swaybg，缺少工具时可确认安装 awww。
- 设置中的技术路径收进默认折叠的“诊断信息”，支持一键复制。
- 补齐设置窗口的 Niri 浮动规则和 Wayland 标识；桌面设置、任务栏设置、时钟与初始向导不再挤进平铺布局，新安装自动生效。

### 从 MNWS 升级与已知限制

升级前先运行旧版 `mnws -S` 停止桌面和底栏，再运行新版安装程序；请勿先卸载旧版或删除配置。安装会迁移旧配置、更新路径并保留备份。旧插件单独保存，随包提供适配 ADWS 的 NCMLyricsBar；其他插件需要适配。安装后使用 `adws` 命令，不提供 `mnws` 别名。旧安装目录及普通文件形式的旧入口不会自动全部删除。

本次诊断发现旧 MNWS 底栏曾在静置时占满单核，重启后恢复；根因尚未确认，不能把本版本描述为已彻底修复所有卡顿。Arch 包已在构建主机及隔离测试中验证，完整的新设备登录、安装、卸载流程仍需要反馈。

## Latest updates

- MNWS is now ADWS — Akizuki’s Desktop Workspace Solution. The new name is no longer tied to Niri, but Niri remains the primary supported environment in this release. Commands now use adws; the installer migrates existing configuration without retaining mnws command aliases.
- Improve Peek responsiveness, order windows by workspace and tile position, and add float/fade transitions.
- Unify settings into Desktop Settings and Taskbar Settings, bringing taskbar appearance, component layout and plugin configuration together.
- Prevent accidental taskbar setting changes when scrolling; the wheel now scrolls the settings page.
- Add Open new window and Run as administrator to taskbar card context menus.
- Support inline desktop renaming, with inline invalid-name and collision errors instead of a separate tiled dialog.
- Fix desktop-session freezes when switching to Chinese input during renaming with certain input method themes.
- Use inline editing for new files and folders, defaulting to text.txt, markdown.md and folder; cancelling leaves no files behind.
- Add pinned apps: click to launch, move into the active area when opened on this workspace, and return to the saved pin position when closed.
- Show a three-dot badge for pinned apps running on another workspace of the same monitor. Click to focus the most recently used window; Peek lists it first, then the rest in workspace/tile order. Other physical monitors are treated as not running here.
- Keep the pinned-area separator in sync with the focused background color, including when no windows are active. (C)
- Add a Beta update channel via adws -u --preview or adws --update --preview and a Settings option; stable releases remain the default. (D)
- Fix intermittent taskbar stalls with window previews enabled. (1.28)
- Add one-way migration with configuration backups; retain old plugins separately and include NCMLyricsBar adapted for ADWS.
- Provide ADWS 1.30 Pre-Release source and Arch Linux x86_64 prebuilt packages.
- Add first-run setup when no local configuration exists, with a manual entry in Settings. Configure animations, preview colors, choose default apps and a launcher, then save on confirmation.
- Add global configuration import and export using Config.ad-yml, with validation, overwrite confirmation, backups and rollback on write failure.
- Added a wallpaper setup page: keep existing settings by default, preview images before applying, choose awww, swww or swaybg in advanced options, and optionally install awww when no tool is detected.
- Move technical paths in Settings into a collapsed Diagnostics section with a copy button.
- Install scoped Niri floating rules and consistent Wayland app IDs for desktop settings, taskbar settings, the clock and first-run setup, including fresh installations.

### Upgrading from MNWS and known limitations

Stop the old desktop and bottom bar with `mnws -S` before running the new installer. Do not uninstall MNWS or delete its configuration first. The installer migrates configuration, rewrites paths and preserves backups. Legacy plugins are kept separately; an ADWS-compatible NCMLyricsBar is included, while other plugins need porting. Use `adws` afterwards; no `mnws` aliases are provided. The old installation directory and regular-file command wrappers are not all removed automatically.

The old MNWS bar was observed consuming one CPU core while idle and recovered after restarting. Its root cause remains unconfirmed; this release does not claim to eliminate all stalls. The Arch package was checked on the build host and in isolated tests; fresh-device login, installation and removal still need broader validation.

## Downloads

- `ADWS1.30_Pre-Release_for_arch.zip`: Arch Linux x86_64 prebuilt package.
- `ADWS1.30_Pre-Release_source.zip`: source package, including vendored niri-ipc.
- Matching `.sha256` files are provided for both archives.

Extract to a permanent directory and run `./install.sh`. / 解压到固定目录后运行 `./install.sh`。

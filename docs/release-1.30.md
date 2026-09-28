# ADWS 1.30 Released

构建日期 / Build date: 2026-09-28

发布标签 / Release tag: `v1.30`.

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
- 提供 ADWS 1.30 稳定版源码包与 Arch Linux x86_64 预构建包。
- 新增首次设置向导：没有本地配置时自动打开，也可从设置重新进入；支持动效、配色预览、默认应用和启动器，确认后统一保存。
- 新增全局配置导入和导出，使用 Config.ad-yml；导入前校验并确认覆盖范围，保留备份，写入失败时恢复原配置。
- 初始设置新增壁纸页：默认保留现有设置，选图预览后确认应用；高级选项支持 awww、swww 和 swaybg，缺少工具时可确认安装 awww。
- 设置中的技术路径收进默认折叠的“诊断信息”，支持一键复制。
- 补齐设置窗口的 Niri 浮动规则和 Wayland 标识；桌面设置、任务栏设置、时钟与初始向导不再挤进平铺布局，新安装自动生效。
- 增加了可选的任务栏和设置选项卡动效，任务栏可以放在上下左右，高度、配色和窗口双排都能自己调整。
- 时钟支持上行大时间、下行小日期、自定义格式和秒数；NCMLyricsBar 1.1.0 保留动态占位、悬停切歌与竖排显示。
- 优化了安装和更新的恢复逻辑，取消、写入失败或组件启动失败时会尝试恢复原文件；恢复不完整会保留备份并明确提示。
- 安装、更新、卸载、配置导入和首次设置保存不会再同时抢着修改配置。
- 保留用户修改过的模板、配置软链接和文件权限，旧版本已经移除的默认模板不会再被带回来。
- 修复了首次设置保存失败后界面不能继续操作的问题，任务栏刷新失败时也会说明设置是否已经保存。
- 优化了旧版迁移：先检查安装记录，重复备份不会互相覆盖，替换随附歌词插件前也会保留旧包。
- 修复了配色刷新异常后不再跟随的问题，配色文件临时消失或写入异常时保留上一套有效颜色。
- 修复了插件断管后刷屏报错、关闭输出后一直等待，以及异常数值和损坏缓存记录导致启动失败的问题。
- 插件覆盖安装改为完整写入后再替换，中途失败不会把原来的插件包写坏。（1.30 稳定版）

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
- Provide ADWS 1.30 stable source and Arch Linux x86_64 prebuilt packages.
- Add first-run setup when no local configuration exists, with a manual entry in Settings. Configure animations, preview colors, choose default apps and a launcher, then save on confirmation.
- Add global configuration import and export using Config.ad-yml, with validation, overwrite confirmation, backups and rollback on write failure.
- Added a wallpaper setup page: keep existing settings by default, preview images before applying, choose awww, swww or swaybg in advanced options, and optionally install awww when no tool is detected.
- Move technical paths in Settings into a collapsed Diagnostics section with a copy button.
- Install scoped Niri floating rules and consistent Wayland app IDs for desktop settings, taskbar settings, the clock and first-run setup, including fresh installations.
- Add optional taskbar and settings-tab animations, all four panel edges, configurable thickness and colors, and two rows of application windows.
- The clock supports a larger time above a smaller date, custom formats and seconds. NCMLyricsBar 1.1.0 retains adaptive width, hover playback controls and vertical layout.
- Improve installation and update recovery: cancellation, write failures and component startup failures trigger restoration of previous files; incomplete recovery retains backups and reports the problem.
- Serialize installation, updates, removal, configuration imports and first-run setup saves to prevent conflicting changes.
- Preserve user-edited templates, configuration symlinks and file permissions; do not restore unchanged default templates removed by the new release.
- Restore an interactive wizard after save failures and distinguish saved settings from a failed taskbar refresh.
- Validate installation records before migration, prevent backup-name collisions and back up the bundled lyrics plugin before replacing it.
- Keep theme refresh active after callback failures and retain the last valid palette while stylesheet files are temporarily missing or invalid.
- Fix cascading plugin broken-pipe errors, unbounded waits after output closes, oversized numeric values and invalid cache records that prevent startup.
- Stage complete plugin packages before replacement so failed copies preserve the installed package. (1.30 stable)

## 安装包 / Downloads

- `ADWS1.30_for_arch.zip` — Arch Linux x86_64 预构建包。
- `ADWS1.30_source.zip` — 源码包，包含 vendor/niri-ipc。
- 每份 ZIP 均提供 SHA-256 文件 / SHA-256 sidecars accompany both archives.

解压到固定目录后运行 `./install.sh`。旧 MNWS 用户请先停止旧组件，再安装迁移，不要先卸载或删除配置。

Extract to a permanent directory and run `./install.sh`. Stop old MNWS components before migration; do not uninstall or delete configuration first.

## 验证范围 / Validation scope

发布检查记录见 [1.30 检查清单](release-1.30-checks.md)。用户已完成日常使用测试；自动化和隔离界面检查不能替代所有发行版、显卡与新设备的完整登录生命周期测试。此前静置卡顿的根因尚未完全确认，本版不声称消除了全部卡顿。

See the [release checklist](release-1.30-checks.md). The user has completed everyday-use testing; automated and isolated GUI checks do not cover every distribution, GPU or fresh-device login lifecycle. The earlier idle-stall root cause is not fully established; this release does not claim to eliminate every stall.

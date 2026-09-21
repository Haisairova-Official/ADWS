# Changelog / 更新记录

## 1.27-D — 2026-09-21

开发分支 / Development branch: `Pre-1.30`.

### 最新更新

Major 1.27    Minor：D    构建日期：2026-09-21

- 增加了大量可选动效，你的任务栏再也不无聊了。
- 增加了大量配色选项。
- 现在任务栏可以上下左右切换了。
- 任务栏高度也可以自行设置了。（1.26）
- 现在选项卡可以合并在一起节省空间了。
- 现在选项卡可以peek视图切换了，就像Windows的DWM那样（A）
- 修复了一些提示错位的bug。（1.27）
- 任务栏歌词插件升级至 NCMLyricsBar 1.1.0，支持 Chrome 等浏览器，并提供实验性的其他音乐平台兼容。歌词支持右键打开设置、点击暂停和悬停切歌，还能动态占位，淡入淡出和宽度过渡也安排上了。
- 完善了歌词的竖排显示与系统配色，原文、译文和分隔线各有各的颜色。
- 修复了应用配置后任务栏与窗口之间多出一块留白的问题。
- 修复了任务栏、菜单和设置窗口配色跟随不及时的问题，换配色终于不用手动重启了。
- 保留手动指定的颜色，配色文件临时写入异常时也不会丢掉上一套有效配色。（B）
- 优化了 Peek，出现更早、切换更流畅，按桌面平铺顺序排列，并增加浮入淡出效果。
- 将设置入口统一为“桌面设置”和“任务栏设置”，任务栏样式、组件布局和插件配置终于放到一起了。
- 取消了滚轮对任务栏设置控件的误调整，滚动页面时不再顺手改掉配置。
- 任务栏项目卡右键新增“打开新窗口”和“以管理员权限运行”。
- 桌面图标支持原位重命名，非法名称和重名直接提示，不再另外弹出一个平铺窗口。
- 新建文件和文件夹也使用原位编辑，默认名称为 text.txt、markdown.md 和 folder；取消不会留下空文件。
- 新增固定应用：点击启动，本桌面打开后进入活动区，关闭后回到原来的固定位置。
- 同屏其他桌面运行的固定应用显示三点角标，点击回到最近操作的窗口，Peek 可继续按桌面和平铺顺序切换；其他物理屏幕按未开启处理。（C）
- 检查更新新增 Beta 渠道，支持 mnws -u --preview 和 mnws --update --preview；设置中也可选择，默认仍检查稳定版。（D）

### Latest updates

Major 1.27    Minor: D    Build date: 2026-09-21

- Add plenty of optional animations—your taskbar will never be boring again.
- Add many more color options.
- The taskbar can now move to the top, bottom, left or right.
- Taskbar height is now customizable. (1.26)
- Window cards can now be grouped to save space.
- Window cards now support Peek-style switching, like Windows DWM. (A)
- Fix several misplaced-tooltip bugs. (1.27)
- Upgrade the taskbar lyrics plugin to NCMLyricsBar 1.1.0, supporting Chrome and other browsers, with optional experimental support for other music platforms. Lyrics now support right-click settings, click-to-pause and hover playback controls, with automatic sizing and optional fades and width transitions.
- Improve vertical lyrics and theme colors, with distinct colors for the original line, translation and separator.
- Fix the extra gap between the taskbar and windows after applying settings.
- Fix delayed theme updates in the taskbar, menus and settings windows; palette changes now apply without a manual restart.
- Preserve manually selected colors and retain the last valid palette if a palette file is temporarily invalid while being written. (B)
- Improve Peek responsiveness, order windows by workspace and tile position, and add float/fade transitions.
- Unify settings into Desktop Settings and Taskbar Settings, bringing taskbar appearance, component layout and plugin configuration together.
- Prevent accidental taskbar setting changes when scrolling; the wheel now scrolls the settings page.
- Add Open new window and Run as administrator to taskbar card context menus.
- Support inline desktop renaming, with inline invalid-name and collision errors instead of a separate tiled dialog.
- Use inline editing for new files and folders, defaulting to text.txt, markdown.md and folder; cancelling leaves no files behind.
- Add pinned apps: click to launch, move into the active area when opened on this workspace, and return to the saved pin position when closed.
- Show a three-dot badge for pinned apps running on another workspace of the same monitor. Click to focus the most recently used window; Peek lists it first, then the rest in workspace/tile order. Other physical monitors are treated as not running here. (C)
- Add a Beta update channel via mnws -u --preview or mnws --update --preview and a Settings option; stable releases remain the default. (D)

## 1.27-C — 2026-09-21

开发分支 / Development branch: `Pre-1.30`.

### 最新更新

Major 1.27    Minor：C    构建日期：2026-09-21

- 增加了大量可选动效，你的任务栏再也不无聊了。
- 增加了大量配色选项。
- 现在任务栏可以上下左右切换了。
- 任务栏高度也可以自行设置了。（1.26）
- 现在选项卡可以合并在一起节省空间了。
- 现在选项卡可以peek视图切换了，就像Windows的DWM那样（A）
- 修复了一些提示错位的bug。（1.27）
- 任务栏歌词插件升级至 NCMLyricsBar 1.1.0，支持 Chrome 等浏览器，并提供实验性的其他音乐平台兼容。歌词支持右键打开设置、点击暂停和悬停切歌，还能动态占位，淡入淡出和宽度过渡也安排上了。
- 完善了歌词的竖排显示与系统配色，原文、译文和分隔线各有各的颜色。
- 修复了应用配置后任务栏与窗口之间多出一块留白的问题。
- 修复了任务栏、菜单和设置窗口配色跟随不及时的问题，换配色终于不用手动重启了。
- 保留手动指定的颜色，配色文件临时写入异常时也不会丢掉上一套有效配色。（B）
- 优化了 Peek，出现更早、切换更流畅，按桌面平铺顺序排列，并增加浮入淡出效果。
- 将设置入口统一为“桌面设置”和“任务栏设置”，任务栏样式、组件布局和插件配置终于放到一起了。
- 取消了滚轮对任务栏设置控件的误调整，滚动页面时不再顺手改掉配置。
- 任务栏项目卡右键新增“打开新窗口”和“以管理员权限运行”。
- 桌面图标支持原位重命名，非法名称和重名直接提示，不再另外弹出一个平铺窗口。
- 新建文件和文件夹也使用原位编辑，默认名称为 text.txt、markdown.md 和 folder；取消不会留下空文件。
- 新增固定应用：点击启动，本桌面打开后进入活动区，关闭后回到原来的固定位置。
- 同屏其他桌面运行的固定应用显示三点角标，点击回到最近操作的窗口，Peek 可继续按桌面和平铺顺序切换；其他物理屏幕按未开启处理。（C）

### Latest updates

Major 1.27    Minor: C    Build date: 2026-09-21

- Add plenty of optional animations—your taskbar will never be boring again.
- Add many more color options.
- The taskbar can now move to the top, bottom, left or right.
- Taskbar height is now customizable. (1.26)
- Window cards can now be grouped to save space.
- Window cards now support Peek-style switching, like Windows DWM. (A)
- Fix several misplaced-tooltip bugs. (1.27)
- Upgrade the taskbar lyrics plugin to NCMLyricsBar 1.1.0, supporting Chrome and other browsers, with optional experimental support for other music platforms. Lyrics now support right-click settings, click-to-pause and hover playback controls, with automatic sizing and optional fades and width transitions.
- Improve vertical lyrics and theme colors, with distinct colors for the original line, translation and separator.
- Fix the extra gap between the taskbar and windows after applying settings.
- Fix delayed theme updates in the taskbar, menus and settings windows; palette changes now apply without a manual restart.
- Preserve manually selected colors and retain the last valid palette if a palette file is temporarily invalid while being written. (B)
- Improve Peek responsiveness, order windows by workspace and tile position, and add float/fade transitions.
- Unify settings into Desktop Settings and Taskbar Settings, bringing taskbar appearance, component layout and plugin configuration together.
- Prevent accidental taskbar setting changes when scrolling; the wheel now scrolls the settings page.
- Add Open new window and Run as administrator to taskbar card context menus.
- Support inline desktop renaming, with inline invalid-name and collision errors instead of a separate tiled dialog.
- Use inline editing for new files and folders, defaulting to text.txt, markdown.md and folder; cancelling leaves no files behind.
- Add pinned apps: click to launch, move into the active area when opened on this workspace, and return to the saved pin position when closed.
- Show a three-dot badge for pinned apps running on another workspace of the same monitor. Click to focus the most recently used window; Peek lists it first, then the rest in workspace/tile order. Other physical monitors are treated as not running here. (C)

## 1.27-B — 2026-09-21

开发分支 / Development branch: `Pre-1.30`.

### 最新更新

Major 1.27    Minor：B    构建日期：2026-09-21

- 增加了大量可选动效，你的任务栏再也不无聊了。
- 增加了大量配色选项。
- 现在任务栏可以上下左右切换了。
- 任务栏高度也可以自行设置了。（1.26）
- 现在选项卡可以合并在一起节省空间了。
- 现在选项卡可以peek视图切换了，就像Windows的DWM那样（A）
- 修复了一些提示错位的bug。（1.27）
- 任务栏歌词插件升级至 NCMLyricsBar 1.1.0，支持 Chrome 等浏览器，并提供实验性的其他音乐平台兼容。
- 歌词支持右键打开设置、点击暂停和悬停切歌，还能动态占位，淡入淡出和宽度过渡也可以安排上。
- 完善了歌词的竖排显示与系统配色，原文、译文和分隔线各有各的颜色。
- 修复了应用配置后任务栏与窗口之间多出一块留白的问题。
- 修复了任务栏、菜单和设置窗口配色跟随不及时的问题，换配色终于不用手动重启了。
- 保留手动指定的颜色，配色文件临时写入异常时也不会丢掉上一套有效配色。（B）

### Latest updates

Major 1.27    Minor: B    Build date: 2026-09-21

- Add plenty of optional animations—your taskbar will never be boring again.
- Add many more color options.
- The taskbar can now move to the top, bottom, left or right.
- Taskbar height is now customizable. (1.26)
- Window cards can now be grouped to save space.
- Window cards now support Peek-style switching, like Windows DWM. (A)
- Fix several misplaced-tooltip bugs. (1.27)
- Upgrade the taskbar lyrics plugin to NCMLyricsBar 1.1.0, supporting Chrome and other browsers, with optional experimental support for other music platforms.
- Lyrics now support right-click settings, click-to-pause and hover playback controls, with automatic sizing and optional fades and width transitions.
- Improve vertical lyrics and theme colors, with distinct colors for the original line, translation and separator.
- Fix the extra gap between the taskbar and windows after applying settings.
- Fix delayed theme updates in the taskbar, menus and settings windows; palette changes now apply without a manual restart.
- Preserve manually selected colors and retain the last valid palette if a palette file is temporarily invalid while being written. (B)

## 1.25 Released — 2026-09-18

### 最新更新

- 帮助新增版本、构建日期、更新摘要。（B）
- 防止隐藏图标后的右键失效；顺便新增终端入口与退出确认。我觉得是个好功能。（C）
- 统一组件启停、状态查询及六级日志。（D）
- 移除了Koha D
- 提升了超级牛力。（E）
- 优化了安装逻辑，修复了一箩筐的bug（1.21）
- 简化了install，并直接在程序中添加了uninstall选项。（F）
- 优化了安装逻辑，启动器我之前忘记配置了。我的错。（1.22）
- 优化了任务栏菜单。（G）
- 优化了命令行参数处理逻辑。（H）
- 添加了安装时默认自启询问。
- 语言支持完善，但是除了中文外其他系统语言默认使用英文。
- 新增检查更新，支持 --update / -u，国内优先使用 GitHub 代理。
- 您是最新的！
- 新增 Language.md，介绍语言文件与概率文案的制作方法。
- 修复了设置开关被拉成Super面筋开关的问题。
- 优化了部分发行版下的默认 include 配置兼容性。
- 定型 Plugin API v1.0，支持插件独立翻译、七类设置及运行错误隔离。
- 将网易云歌词Sample插件正式命名为 NCMLyricsBar，升级至 1.0.1，保留旧插件配置。
- 优化了歌词的系统配色，原文、译文和分隔线终于不用挤一个颜色了。
- 修复了上游 Niri 窗口数据兼容问题，补充事件容错和断线重连。
- 提供 Arch Linux x86_64 的预构建安装包，安装时不再需要现场编译 Rust 和 C。（Pre-release）
- 修改了开始按钮的默认文字，提供了自定义icon功能。
- 优化了任务栏稳定性，优化了MNWS系列命令稳定性。
- 修复了特殊情况下任务栏变为英文的bug。（Released）

### Latest updates

- Add version, build date and update summaries to help. (B)
- Fix the context menu when icons are hidden; add a terminal entry and exit confirmation. I think it is a nice feature. (C)
- Unify component controls, status queries and six logging levels. (D)
- Remove Koha D.
- Increase Super Cow Powers. (E)
- Improve installation logic and fix a basketful of bugs. (1.21)
- Simplify install and add an uninstall option directly to the program. (F)
- Improve installation logic: I forgot to configure the launcher earlier. My mistake. (1.22)
- Improve the taskbar menu. (G)
- Improve command-line argument handling. (H)
- Add a default-yes autostart prompt during installation.
- Improve language support; all system languages other than Chinese default to English.
- Add update checks via --update / -u, preferring a GitHub proxy in mainland China.
- You're up to date!
- Add Language.md explaining translation files and weighted messages.
- Fix settings switches stretching into Super gluten-strip switches.
- Improve default include configuration compatibility on some distributions.
- Finalize Plugin API v1.0 with package translations, seven setting types and plugin error isolation.
- Officially rename the NetEase lyrics Sample plugin to NCMLyricsBar, upgrade to 1.0.1 and preserve existing settings.
- Improve system-theme lyrics colors: the original, translation and separator no longer have to share one color.
- Fix upstream Niri window-data compatibility, with event tolerance and reconnection.
- Provide a prebuilt Arch Linux x86_64 archive so installation no longer compiles Rust and C on the spot. (Pre-release)
- Change the default Start-button text and add custom icon support.
- Improve taskbar stability and the reliability of the MNWS command suite.
- Fix the taskbar unexpectedly switching to English under special circumstances. (Released)

### 验证范围 / Validation scope

已完成 Arch Linux 与 Ubuntu 的 Niri 环境实机测试。
Tested in real Niri sessions on Arch Linux and Ubuntu.

## 1.23 H — 2026-09-09

### 中文

- 帮助新增版本、构建日期、更新摘要。（B）
- 防止隐藏图标后的右键失效；顺便新增终端入口与退出确认。我觉得是个好功能。（C）
- 统一组件启停、状态查询及六级日志。（D）
- 移除了Koha D
- 提升了超级牛力。（E）
- 优化了安装逻辑，修复了一箩筐的bug（1.21）
- 简化了install，并直接在程序中添加了uninstall选项。（F）
- 优化了安装逻辑，启动器我之前忘记配置了。我的错。（1.22）
- 优化了任务栏菜单。（G）
- 优化了命令行参数处理逻辑。（H）

### English

- Add version, build date and update summaries to help. (B)
- Fix the context menu when desktop icons are hidden; add a terminal entry and exit confirmation. I think it is a nice feature. (C)
- Unify component start/stop controls, status queries and six logging levels. (D)
- Remove Koha D.
- Increase Super Cow Powers. (E)
- Improve installation logic and fix a basketful of bugs. (1.21)
- Simplify install and add an uninstall option directly to the program. (F)
- Improve installation logic: I forgot to configure the launcher earlier. My mistake. (1.22)
- Improve the taskbar menu. (G)
- Improve command-line argument handling. (H)

### 本次改动 / Changes in this version

- 组件与短、长操作参数支持前后互换；省略组件时，启动、停止、强制结束、重启及状态查询作用于桌面和任务栏。调试仍需指定单个组件。
- Accept component names before or after short and long operation options. Without a component, start, stop, kill, restart and status target both desktop and taskbar. Debugging still requires a single component.

### 验证 / Validation

- 56 项测试通过，包含参数顺序、一键启动、无效参数拒绝及命令入口转发。
- 56 tests passed, including argument ordering, starting both components, invalid-argument rejection and command dispatch.

## 1.22 G — 2026-09-09

### 中文

- 帮助新增版本、构建日期、更新摘要。（B）
- 防止隐藏图标后的右键失效；顺便新增终端入口与退出确认。我觉得是个好功能。（C）
- 统一组件启停、状态查询及六级日志。（D）
- 移除了Koha D
- 提升了超级牛力。（E）
- 优化了安装逻辑，修复了一箩筐的bug（1.21）
- 简化了install，并直接在程序中添加了uninstall选项。（F）
- 优化了安装逻辑，启动器我之前忘记配置了。我的错。（1.22）
- 优化了任务栏菜单。（G）

### English

- Add version, build date and update summaries to help. (B)
- Fix the context menu when desktop icons are hidden; add a terminal entry and exit confirmation. I think it is a nice feature. (C)
- Unify component start/stop controls, status queries and six logging levels. (D)
- Remove Koha D.
- Increase Super Cow Powers. (E)
- Improve installation logic and fix a basketful of bugs. (1.21)
- Simplify install and add an uninstall option directly to the program. (F)
- Improve installation logic: I forgot to configure the launcher earlier. My mistake. (1.22)
- Improve the taskbar menu. (G)

### 本次改动 / Changes in this version

- 开始按钮支持自定义文字与字符图标、读取当前内容、预览及自动选择发行版 Logo（需要 Nerd Fonts / Font Logos 字体支持）。
- 命令优先链接到 PATH 中的 ~/.local/bin，否则询问安装到 /usr/local/bin；保护同名程序，卸载核对链接归属，不修改终端配置。
- Customize the start button text or glyph, load its current content, preview it, and select a distribution logo (requires Nerd Fonts / Font Logos).
- Link commands into ~/.local/bin when on PATH, otherwise offer /usr/local/bin; preserve unrelated commands and verify link ownership during uninstall without editing shell configuration.

### 验证 / Validation

- 52 项测试通过；发行版识别、回退图标与启动命令保留检查通过。未完成 GUI 视觉验证。
- 52 tests passed; distribution detection, fallback glyph and launcher-command preservation checks passed. GUI visual verification remains outstanding.

## 1.22 F — 2026-09-09

### 中文

- 帮助新增版本、构建日期、更新摘要。（B）
- 防止隐藏图标后的右键失效；顺便新增终端入口与退出确认。我觉得是个好功能。（C）
- 统一组件启停、状态查询及六级日志。（D）
- 移除了Koha D
- 提升了超级牛力。（E）
- 优化了安装逻辑，修复了一箩筐的bug（1.21）
- 简化了install，并直接在程序中添加了uninstall选项。（F）
- 优化了安装逻辑，启动器我之前忘记配置了。我的错。（1.22）

### English

- Add version, build date and update summaries to help. (B)
- Fix the context menu when desktop icons are hidden; add a terminal entry and exit confirmation. I think it is a nice feature. (C)
- Unify component start/stop controls, status queries and six logging levels. (D)
- Remove Koha D.
- Increase Super Cow Powers. (E)
- Improve installation logic and fix a basketful of bugs. (1.21)
- Simplify install and add an uninstall option directly to the program. (F)
- Improve installation logic: I forgot to configure the launcher earlier. My mistake. (1.22)

### 安装流程 / Installation flow

- 缺少运行依赖或组件时询问是否补齐或构建，完成后重新检查；自动补齐支持 apt、pacman、dnf，拒绝或取消时停止。
- Offer to install missing runtime dependencies or build components, then check again. Automatic dependency installation supports apt, pacman and dnf; declining or cancelling stops installation.

### 验证 / Validation

- 48 项测试通过，包括启动器优先级、自定义命令、取消、安装成功与失败、配置备份。包管理器使用模拟测试，未实际安装系统软件。
- 48 tests passed, covering launcher priority, custom commands, cancellation, installation success/failure and configuration backups. Package manager calls were mocked; no system packages were installed.

## 1.21 F — 2026-09-09

### 中文

- 帮助新增版本、构建日期、更新摘要。（B）
- 防止隐藏图标后的右键失效；顺便新增终端入口与退出确认。我觉得是个好功能。（C）
- 统一组件启停、状态查询及六级日志。（D）
- 移除了Koha D
- 提升了超级牛力。（E）
- 优化了安装逻辑，修复了一箩筐的bug（1.21）
- 简化了install，并直接在程序中添加了uninstall选项。（F）

### English

- Add version, build date and update summaries to help. (B)
- Fix the context menu when desktop icons are hidden; add a terminal entry and exit confirmation. I think it is a nice feature. (C)
- Unify component start/stop controls, status queries and six logging levels. (D)
- Remove Koha D.
- Increase Super Cow Powers. (E)
- Improve installation logic and fix a basketful of bugs. (1.21)
- Simplify install and add an uninstall option directly to the program. (F)

### 验证 / Validation

- 35 项安装、命令、歌词、彩蛋与卸载测试通过；卸载在临时目录中验证。
- 72 项桌面回归测试通过；Rust 任务栏编译通过。
- 未完成全新发行版虚拟机验证；安装仍需要手动准备依赖和构建组件，命令入口仍依赖源码目录。
- 35 installation, CLI, lyrics, easter-egg and uninstall tests passed, with uninstall tests isolated in temporary directories.
- 72 desktop regression tests and the Rust taskbar build passed.
- No fresh-distribution VM validation yet. Dependencies and component builds remain manual; launchers still require the source checkout.

## 1.2 — 2026-09-09

### 中文

- 修复隐藏桌面图标后右键失效：隐藏时保留简化菜单，可显示图标、打开终端或桌面文件夹。
- 普通菜单新增打开终端；退出项红色悬停，并增加确认弹窗与可复制的恢复命令。
- 桌面和任务栏统一支持 `--start/-s`、`--stop/-S`、`--kill/-k`、`--restart/-r`。
- 新增 `--debug/-d` 前台日志及 `-1` 到 `-6` 六级过滤，默认 `-4`；记录菜单、打开请求、弹窗响应及窗口操作。
- `mnws --status` 同时显示两个组件的状态；组件级 `--status` 可单独查询。
- 启动成功保持安静；帮助支持 `-h`、`--help`、`-?`，集中展示用法、命令、选项和示例。
- 保持 Niri 支持范围；MHWS 分支的 Hyprland 适配仍未开始。

### English

- Keep a minimal desktop context menu available while icons are hidden, with actions to show icons, open a terminal and open the desktop folder.
- Add a terminal action to the regular menu, a red exit hover state, and exit confirmation with a copyable recovery command.
- Unify desktop/taskbar controls: `--start/-s`, `--stop/-S`, `--kill/-k` and `--restart/-r`.
- Add foreground debugging with `--debug/-d` and six verbosity levels (`-1` through `-6`, default `-4`), covering menu actions, launch requests, dialog responses and window operations.
- Add global `mnws --status` alongside per-component status queries.
- Make successful starts silent; provide compact help through `-h`, `--help` and `-?`.
- This release targets Niri. Hyprland adaptation on MHWS has not started.

### Validation / 验证

- 19 command and lyrics tests passed / 19 项命令与歌词测试通过。
- 6 isolated GTK desktop regression tests passed / 6 项隔离 GTK 桌面回归测试通过。
- Rust taskbar release build passed / Rust 任务栏发布编译通过。
- Live global status and silent-start checks passed / 实机总览状态与静默启动检查通过。

This is a source release. Rebuild the taskbar module when updating to enable its new operation logs.
本次为源码发布；升级时需重新编译任务栏模块，才能使用新增的任务栏操作日志。

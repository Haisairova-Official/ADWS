# Changelog / 更新记录

## 1.35 — 2026-10-10

内部版本：Q。

- 新增原生开始菜单与 KDE、Vista Aero、Windows XP、AkiACG 主题，支持搜索、命令、会话操作和自定义 CSS。
- 新增独立系统设置，整合显示器、默认应用、网络、蓝牙、声音、账户与快捷键；补充应用独立缩放和桌面“用指定应用打开”。
- 任务栏支持分体、吸附／悬浮、四种材质和组件拖动布局；新增托盘、声音与亮度面板，完善 Peek 与 Shift＋右键结束进程。
- 新增可编辑侧边栏和时钟控制中心，提供日历、日程、通知、快捷开关、天气及免费潮汐预报；IP 定位需要单独同意。
- 剪贴板支持固定记录、图片与内容预览、搜索、删除，以及可拖动的置顶窗口。
- 新增 Waybar 配置页与四套预设，支持布局、字体、完整导入、备份恢复和自启；应用配置时重启所选栏。
- 新增 Kitty／Alacritty 预设、默认终端和壁纸自动配色；修复 Ubuntu 中文路径，增加 Waybar 兼容修复与可选 Nerd Fonts 安装。
- 更新器支持后台下载进度、校验和确认后安装；卸载保留已修改的系统配置。
- 优化开始菜单与侧边栏启动和动效，复用界面、按显示帧推进；原生 Rust 入口与 C 模糊控制减少延迟和退出残留。
- 修复任务栏悬停、聚焦样式累积及窗口切换积压造成的卡顿，完善吸附动画、字体回退和多屏显示配置。
- 插件增加语言标签、单例声明与独立 Watchdog；NCMLyricsBar 1.1.0 按钮配色跟随任务栏。
- 声音与亮度报错说明更清楚，点击和滚轮操作后刷新；无声音设备显示静音喇叭与右侧问号，其他异常使用角标。
- 修复微信等托盘服务漏注册后图标消失的问题，自动恢复已有图标服务并避免重复显示。

[正式版更新说明](docs/release-1.35.md)

## 1.35-N Pre-Release — 2026-10-05

- 修复 Ubuntu 下中文路径和设置组件兼容问题。（M）
- 更新器显示后台下载进度，确认后自动校验与安装。（M）
- 新增 Waybar 模块兼容性检查，可安装/升级或构建官方兼容版本。（N）
- 可选安装 Nerd Fonts 图标字体，帮助新增依赖修复命令。（N）

Fix Ubuntu paths/settings compatibility and add background update progress with installation after confirmation. Add Waybar compatibility repair and optional Nerd Fonts icon installation, with commands documented in help.

[更新说明 / Update notes](docs/update-notes-1.35-N-2026-10-05.md)

## 1.35-L Pre-Release — 2026-10-05

开发分支 / Development branch: `Pre-1.35`.

- 汇总 1.30 之后的开始菜单、系统设置、组件布局、授权与安装保护更新。
- 新增四套顶部 Waybar 预设，完善快捷组件、取色与配色、字体和折角。
- 新增整套配置导入、备份恢复与 Niri 自启选项；刷新与应用使用所选栏的正常重启。
- 修复隐藏托盘图标提示位置，窗口切换移至后台并限制积压，补充超时与卡顿警告。
- 修复悬停窗口图标时样式路径持续累积造成的任务栏卡顿，补充重复悬停和 Peek 回归验证。
- 插件新增独立 Watchdog，崩溃或无响应时通知并在设置中标黄；异常退出不再反复自动重启。
- NCMLyricsBar 1.1.0 配色修订：上一首、下一首按钮实时跟随任务栏主题。
- Extended daily-use verification remains ongoing.

J：顶部栏预设与布局；K：快捷组件与配色；L：导入、自启和刷新兼容；1.35：窗口切换可靠性。这些编号用于整理开发进度，未分别发布。

[完整累计更新 / Consolidated update notes](docs/update-notes-1.35-L-2026-10-05.md)

## 1.34-I — 2026-10-05

- 提供通用顶部 Waybar 默认配置，移除 Shorin 等专属脚本依赖；新安装保留已有顶部栏，支持独立临时预览。

- 新增独立 Waybar 配置页，支持尺寸、边距、组件排列及 JSONC 编辑；保存前备份，保留注释，只刷新匹配的顶部栏。

开发分支 / Development branch: `Pre-1.35`.

- 开始菜单短时复用，配置与应用变化自动刷新，闲置三分钟后释放。（1.34）
- Kitty／Alacritty 预设支持一键部署、备份与字体回退，补充默认终端。（H）
- 壁纸增加 Matugen 安装／卸载和可选自动配色，卸载保留配色。（I）
- Cache Start briefly with automatic refresh/expiry; add terminal presets/default selection and optional wallpaper colors.

[完整更新 / Update notes](docs/update-notes-1.34-I-2026-10-05.md)

## 1.33-G — 2026-10-05

- 修复管理员授权后崩溃、菜单动作丢失，使用紧凑授权与错误窗口。 / Fix authorization completion crashes and lost actions; use compact themed dialogs.

开发分支 / Development branch: `Pre-1.35`.

- 修复 Wayland 下 Shift＋右键无反应的问题；按住显示红色“结束进程”，松开恢复“关闭窗口”。（G）
- Fix unresponsive Shift + right-click on Wayland: hold Shift for red End process, and release it to restore Close window. (G)

验证：真实 Wayland 输入、菜单关闭后的焦点恢复，以及合并子菜单和终止动作回归通过。 / Verified real Wayland input, focus restoration, grouped-menu state and action regressions.

[累计更新 / Cumulative notes](docs/update-notes-1.33-G-2026-10-05.md) · [验证记录 / Verification](docs/shift-menu-verification-2026-10-05.md)

## 1.33-F — 2026-10-05

开发分支 / Development branch: `Pre-1.35`.

### 1.30 之后累计更新 / Changes since 1.30

- 开始 Rust 化，插件运行器优先使用 Rust，保留 Python 回退；插件新增语言标签，SSH／TTY 安装增加确认。（A）
- Prefer Rust plugin supervision with Python fallback, plugin language badges and SSH/TTY installation confirmation. (A)

- 新增原生开始菜单，提供 KDE、Vista Aero、Windows XP、AkiACG 主题，支持自定义 CSS、系统配色与动效。（B／D）
- Add a native Start menu with KDE, Vista Aero, Windows XP and AkiACG themes, custom CSS, system colors and animations. (B/D)

- 开始菜单支持搜索、回车执行命令、电源与会话操作；头像和昵称按登录缓存，按钮与快捷键定位统一。（B）
- Add Start search, Enter-to-run commands and power/session actions; cache account details per login and unify button/shortcut positioning. (B)

- 开始按钮独立设置，支持多个实例、自定义图标和图片、启动器及右键动作。（D）
- Give Start independent settings, multiple instances, custom icons/images, launchers and context actions. (D)

- 新增三套快捷键方案，并提供可选的标准 Niri 单修饰键兼容补丁。（B）
- Add three keyboard profiles and an optional modifier-tap patch for upstream Niri. (B)

- 新增分体任务栏、吸附与悬浮模式、四种材质；完善圆角、尖角和内容留白。（B／1.33）
- Add split taskbars, docking/floating modes and four materials; refine corners, pointed ends and content clearance. (B/1.33)

- Peek 增加关闭按钮；项目卡支持 Shift 切换“结束进程”，危险操作使用红色动效。（B／1.33）
- Add Peek close buttons and Shift-activated End process with red destructive transitions. (B/1.33)

- 新增独立系统设置，整合默认应用、网络、蓝牙、声音、电源、账户、地区、输入法与快捷键等功能，不依赖其他桌面的设置套件。（C）
- Add independent system settings for default apps, networking, Bluetooth, audio, power, accounts, regional settings and input, without other desktop control centers. (C)

- 显示设置适配 Niri／Hyprland，支持多屏拖动排布；壁纸平铺展示，添加时自动复制。（C）
- Provide Niri/Hyprland display arrangement and a wallpaper gallery with copied imports. (C)

- 重构组件布局，支持横向拖动、跨区排序和实时预览；可选组件可移除或重复添加，窗口图标栏始终保留。插件支持 isSingleOnly 单例声明。（D／E）
- Rebuild layout editing with horizontal drag ordering, movement across regions and live preview; retain mandatory window icons and support repeatable components with isSingleOnly plugin declarations. (D/E)

- 默认布局：左侧开始与窗口图标，中间留空，右侧声音、亮度、托盘与时钟；已有布局保留。（E）
- Default to Start and window icons at the front, an empty center, and sound, brightness, tray and clock at the back, preserving existing layouts. (E)

- 新增内置托盘，超过三个图标折叠；声音与亮度支持点击、滚轮和详细面板，外观跟随任务栏。（E）
- Add a tray with overflow after three icons, plus audio/brightness click, wheel and detailed controls following taskbar appearance. (E)

- 优化启动、事件队列、歌词渲染与资源清理，新增无响应诊断和自动恢复；修复托盘图标、重复菜单、下拉错位及开关拉伸等问题。（1.32／1.33）
- Improve startup, event queues, lyric rendering and resource cleanup; add stall diagnostics/recovery and fix tray icons, duplicate menus, misplaced selectors and stretched switches. (1.32/1.33)

- 卸载保留系统设置，个人布局不再覆盖默认配置；登录启动项支持右键删除并确认名称。（1.33／F）
- Preserve system settings on uninstall, keep personal layouts separate from shipped defaults, and confirm named login-entry deletions. (1.33/F)

### 开发阶段 / Development stages

以下中间编号按改动类别补记为开发阶段，未单独发布。已发布的 1.31 A／B 记录保留。
These intermediate numbers identify development stages, not separate published releases; published 1.31 A/B history is retained.

| 版本 / Version | 改动 / Changes |
| --- | --- |
| 1.32-B | 任务栏稳定性、队列与缓存优化、退出清理及无响应诊断。 / Taskbar reliability, queue/cache optimization, teardown and stall diagnostics. |
| 1.32-C | 独立系统设置、多屏排布、壁纸库及系统服务管理。 / Independent system settings, monitor arrangement, wallpaper library and service management. |
| 1.32-D | AkiACG 主题、开始按钮独立配置、组件实例与拖动布局。 / AkiACG theme, independent Start preferences, component instances and drag layout. |
| 1.32-E | 系统托盘、声音、亮度、插件单例声明与新默认布局。 / Tray, sound, brightness, singleton declarations and new defaults. |
| 1.33-E | 托盘与弹窗外观、Shift 终止、实际预览及配置保护等修复。 / Tray/popup appearance, Shift termination, live preview and configuration preservation fixes. |
| 1.33-F | 登录启动项右键删除、名称确认与本次累计更新整理。 / Confirmed login-entry removal and consolidated update notes. |

## 1.31 B — 2026-10-04

开发分支 / Development branch: `Pre-1.35`.

- 新增 Rust 开始菜单，提供 KDE、Vista Aero、Windows XP 风格，支持自定义 CSS 并跟随系统配色。
- Add a native Rust start menu with KDE, Vista Aero and Windows XP-inspired presets, custom CSS and system colors.

- 开始菜单绑定实际开始按钮位置；设置、初始向导和安装器可选择 ADWS 开始菜单、fuzzel 或 rofi。
- Anchor the menu to the actual Start button. Settings, OOBE and installation offer ADWS Start, fuzzel and rofi.

- 统一任务栏右键菜单、子菜单和 Peek 的圆角；Peek 右上角新增独立关闭按钮。
- Unify taskbar context-menu, submenu and Peek corners; add independent close controls to previews.

- 新增终止进程选项：Shift 激活、列于关闭下方、禁用；危险操作使用红色悬停并跟随动效开关。
- Configure process termination: Shift activation, a separate item below Close, or disabled. Red hover transitions follow animation settings.

- 新增分体任务栏，按前、中、后有内容的区域显示；新增常驻吸附、有平铺窗口时吸附和悬浮模式，支持四边布局。
- Add occupied-section split surfaces and docked, window-dependent docking and floating modes on all four edges.

- 新增纯色、云母、亚克力和糖果材质，保留手动背景色；透明材质的背景模糊由窗口管理器提供。
- Add Solid, Mica, Acrylic and Candy appearances, retaining manual base colors. Background blur depends on compositor support.

- 重做开始菜单的三套布局：KDE 分类网格、Vista 程序区与账户栏、XP 用户横幅与级联菜单。
- Rebuild the three start menu layouts: KDE navigation and grid, Vista program well and account rail, and XP user banner and cascading menus.

- 开始菜单后台加载应用并分批创建界面，浮入淡出与页面切换跟随动效选项。
- Load applications off the UI thread in bounded batches; menu fade/float and page transitions follow animation preferences.

- 开始菜单显示系统账户头像和昵称，未设置时回退到默认头像和用户名。
- Show the system account avatar and real name, falling back to a default avatar and login name.

- 修复吸附模式切换不刷新的问题，吸附时取消圆角并增加可反向衔接的浮动过渡；修复 Wayland 菜单延迟收到 Shift 状态时未切换终止动作的问题。
- Fix docking updates, use square docked corners and reversible float transitions; follow delayed Wayland Shift modifiers in termination menus.

- 开始菜单设置独立成页，关闭开始按钮后仍可配置和预览，保留按钮外观与菜单偏好。
- Give Start its own settings page; keep configuration and preview available with the taskbar button hidden, preserving appearance and menu preferences.

- 修复安装器连续读取管道输入时吞掉后续答案的问题。（B）
- Fix installation helpers reading ahead and consuming answers intended for later steps. (B)

- 开始菜单新增电源与会话入口，按系统能力提供锁屏、注销、挂起、休眠、重启和关机；注销、重启和关机需再次确认。
- Add Power and session to Start, offering available lock, logout, suspend, hibernate, restart and shutdown actions; confirm logout, restart and shutdown.

- 开始菜单支持搜索与命令输入，直接回车执行命令，选择搜索结果后回车启动应用。
- Search applications or enter a command in Start; direct Enter runs the command, while Enter on a selected result launches the application.

- 新增 Waylander、Traditional、Reversed 键位方案；检测 Niri 单修饰键支持，应用前校验并备份配置，不支持时保留原键位。
- Add Waylander, Traditional and Reversed keyboard profiles; detect modifier-tap support, validate and back up before applying, and preserve bindings on unsupported Niri builds.

- 提供可选的官方 Niri 26.04 单修饰键兼容补丁，锁定源码与校验值，独立构建和安装，保留原版与恢复入口。
- Provide an optional modifier-tap patch for upstream Niri 26.04 with pinned source and checksums, separate builds and installation, and an original-session recovery path.

- 开始菜单底部铭文显示 ADWS 与当前版本号，自动跟随构建信息。
- Show ADWS and the current version in the Start menu footer, following build metadata automatically.

- 开始按钮后台启动程序，首页快捷应用优先显示，并优化开始菜单浮入曲线。
- Launch Start commands off the taskbar UI thread, show home shortcuts before the full app list, and reveal the menu with an ease-out transition.

- 任务栏新增独立无响应检测：连续 10 秒未响应时记录诊断并自动恢复，10 分钟最多两次，短暂延迟仅记录。
- Add an independent taskbar heartbeat: log diagnostics and recover after 10 seconds without a response, with at most two attempts per 10 minutes; log shorter delays without restarting.

- 分体内容预留 5px 余量，可选圆角或 < > 尖角；吸附只拉直贴屏外缘，当前桌面平铺窗口触发自动吸附，浮窗不触发。（B）
- Reserve 5px around segment content; use rounded or pointed < > ends on every segment. Docking squares only the outside corners, retaining rounded inner ends. Only current-workspace tiled windows trigger auto-docking. (B)

- 优化任务栏启动：窗口数据连接与图标查找不再阻塞界面，首次吸附及时提交，不再等待组件刷新后才到位。
- Improve taskbar startup: keep window connections and icon lookup off the UI thread, and commit initial docking promptly without waiting for a component refresh.

- 统一快捷键与按钮的开始菜单定位；头像和昵称按登录会话缓存，后台获取，同一次登录不再重复查询。
- Use the live Start button position for both keyboard and button launches; cache the avatar and name per login session, with account lookup in the background.

- 限制窗口更新队列并合并过期快照，避免高频事件持续堆积、挤占任务栏界面线程。
- Bound window-update queues and coalesce stale snapshots to prevent high-frequency events from accumulating and starving the taskbar UI.

- 修复歌词宽度动画反复加载应用图标，以及配色和样式变化重复测量歌词字体的问题。
- Fix redundant application-icon loading during lyric width animations and repeated lyric font measurement after color or style changes.

- 补齐任务栏模块与后台监听的退出清理，卸载时主动取消任务并中断等待中的 Niri 读取。
- Cancel taskbar tasks and background listeners on unload, including interruption of idle Niri socket reads.

- 修复尖角模式在没有中间分体时退化为普通模式的问题：两侧朝向间隙的端头也显示尖角，保留 5px 内容余量。
- Fix pointed mode falling back to ordinary surfaces when the center segment is empty: gap-facing ends of the side segments are pointed too, with 5px of content clearance.

- 新增歌词长时间压力、窗口事件洪流、模块释放和图标缓存回归测试，并记录验证结果。
- Add lyric soak, window-event flood, teardown and icon-cache regression tests, with documented verification results.

## 1.31 A — 2026-09-28

开发分支 / Development branch: `Pre-1.35`.

- 开始 Rust 化：插件常驻运行器默认优先使用 Rust，源码安装和 Arch 预构建包都包含运行器；保留 Python 回退。
- Begin the Rust migration: prefer the Rust plugin supervisor by default and include it in source installation and Arch prebuilt packages; retain the Python fallback.

- 安装新增灵魂拷问：SSH 或非图形会话先确认是否继续，默认取消；普通桌面终端不受影响。
- Installation now asks for confirmation in SSH or non-graphical sessions, defaulting to cancel; normal desktop terminals are unaffected.

- 插件名称旁新增带代表色的圆角语言标签，长名称仍会省略，操作按钮保持可见。
- Add colored language badges beside plugin names while keeping long names ellipsized and action buttons visible.
- 修复了 Python 回退运行器收到退出信号后仍等待超时的问题。
- Fix the Python fallback supervisor waiting for a timeout after receiving a termination signal.

## 1.30 Released — 2026-09-28

发布标签 / Release tag: `v1.30`.

### 最新更新

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

### Latest updates

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

## 1.30 Pre-Release — 2026-09-21

开发分支 / Development branch: `Pre-1.30`.

### 最新更新

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

### Latest updates

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

## 1.28-D — 2026-09-21

开发分支 / Development branch: `Pre-1.30`.

### 最新更新

Major 1.28    Minor：D    构建日期：2026-09-21

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

### Latest updates

Major 1.28    Minor: D    Build date: 2026-09-21

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
- 检查更新新增 Beta 渠道，支持 adws -u --preview 和 adws --update --preview；设置中也可选择，默认仍检查稳定版。（D）

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
- Add a Beta update channel via adws -u --preview or adws --update --preview and a Settings option; stable releases remain the default. (D)

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
- 优化了任务栏稳定性，优化了ADWS系列命令稳定性。
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
- Improve taskbar stability and the reliability of the ADWS command suite.
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
- `adws --status` 同时显示两个组件的状态；组件级 `--status` 可单独查询。
- 启动成功保持安静；帮助支持 `-h`、`--help`、`-?`，集中展示用法、命令、选项和示例。
- 保持 Niri 支持范围；MHWS 分支的 Hyprland 适配仍未开始。

### English

- Keep a minimal desktop context menu available while icons are hidden, with actions to show icons, open a terminal and open the desktop folder.
- Add a terminal action to the regular menu, a red exit hover state, and exit confirmation with a copyable recovery command.
- Unify desktop/taskbar controls: `--start/-s`, `--stop/-S`, `--kill/-k` and `--restart/-r`.
- Add foreground debugging with `--debug/-d` and six verbosity levels (`-1` through `-6`, default `-4`), covering menu actions, launch requests, dialog responses and window operations.
- Add global `adws --status` alongside per-component status queries.
- Make successful starts silent; provide compact help through `-h`, `--help` and `-?`.
- This release targets Niri. Hyprland adaptation on MHWS has not started.

### Validation / 验证

- 19 command and lyrics tests passed / 19 项命令与歌词测试通过。
- 6 isolated GTK desktop regression tests passed / 6 项隔离 GTK 桌面回归测试通过。
- Rust taskbar release build passed / Rust 任务栏发布编译通过。
- Live global status and silent-start checks passed / 实机总览状态与静默启动检查通过。

This is a source release. Rebuild the taskbar module when updating to enable its new operation logs.
本次为源码发布；升级时需重新编译任务栏模块，才能使用新增的任务栏操作日志。


### 2026-10-05 字体与吸附修复

修复任务栏吸附动画在缺少绘制帧时停住；默认配置、生成和升级迁移加入 Nerd Symbols 字体回退，保留自定义文字字体。

# 顶部 Waybar / Top Waybar

ADWS 的通用顶部栏保留原设计的 Powerline 箭头、多段配色、居中启动器及图标布局，使用 Nerd Fonts。移除 Shorin／ML4W 专属脚本依赖，终端、截图、壁纸、更新、亮度、声音等入口改为通用或 ADWS 自有操作。没有电池时不显示电池；音频适配 PulseAudio、PipeWire Pulse 或 WirePlumber。

模板：`config/waybar/config-top.jsonc` 与 `config/waybar/style-top.css`。安装器为没有 `~/.config/waybar/config` 或 `config.jsonc` 的新用户创建配置，并询问是否随 Niri 自启。有现成顶部栏配置时保留原文件、软链接和主题；不会运行旧的 `launch.sh`，也不会杀掉其他 Waybar。卸载移除 ADWS 添加的顶部栏自启块，保留用户的原生 Waybar 配置。

“设置 → Waybar 配置”可调整布局和编辑 JSONC，也可预览默认顶部栏。预览使用临时目录，不修改本地配置、不抢占窗口空间，右侧“×”仅关闭预览；需要时也可用页面中的“关闭预览”。原有顶部栏和 ADWS 底栏继续运行。

默认 CSS 跟随 `colors.css`，不改动用户现有配色。模板中的设置入口在安装时生成准确路径，支持含空格的安装目录，中文环境显示中文，其他环境显示英文。

## English

The portable top bar preserves the original Powerline arrows, segmented colors, centered launcher and icon layout, using Nerd Fonts. Shorin/ML4W-specific scripts are replaced with generic tools or ADWS controls for terminal, screenshot, wallpaper, updates, brightness and sound. Audio adapts to PulseAudio, PipeWire Pulse or WirePlumber.

Templates are `config/waybar/config-top.jsonc` and `style-top.css`. Installation creates defaults only when no existing `config` or `config.jsonc` is present, then offers Niri startup. Existing configuration, links and themes are preserved. Uninstallation removes only the added startup block and keeps native Waybar configuration.

Use Settings → Waybar configuration to edit the bar or preview defaults. Preview uses temporary files, reserves no window space and leaves existing bars running. Its “×” button closes only the preview.

Styles follow `colors.css`. Generated settings commands handle installation paths with spaces; Chinese locales use Chinese text and other locales use English.

### 系统更新按钮 / System update button

顶部栏的更新按钮在默认终端中执行系统更新，不再打开 ADWS 版本检查页。默认优先使用 `yay -Syu`，没有 yay 时使用 `paru -Syu`。在 **Waybar 配置 → 系统更新按钮** 中可以固定选择 yay、paru，或填写自定义命令；右键更新按钮可进入此设置页。修改后点击应用。缺少所选程序时会提示，不会静默替换为其他系统的升级命令。终端保留执行结果，按回车关闭。

The top-bar update button runs system upgrades in the default terminal. It prefers `yay -Syu`, falling back to `paru -Syu`. Under **Waybar settings → System update button**, select yay, paru or a custom command, then apply. Right-click the button to open settings. Missing tools produce a notification; the terminal keeps the result visible until you press Enter.

音量与亮度入口使用 ADWS 自有调节面板，剪贴板窗口与任务栏显隐动作也已接入 ADWS。现有用户 Waybar 不会自动被覆盖。

Audio and brightness actions open ADWS panels; clipboard windows and taskbar visibility actions also use ADWS. Existing user Waybar configurations are never automatically overwritten.

### 可视化组件布局 / Visual module layout

组件按左、中、右区域显示为图标卡片。拖动可以排序或跨区域移动；点击卡片可前移、后移、换区或移除。上方选择组件和目标区域后点击加号即可添加。组件列表会读取当前配置及其 include 文件，保留已有自定义组件与分隔箭头；未点应用前不会修改正在运行的栏。原始 JSONC 仍可在高级编辑器中修改。

Modules appear as icon cards in left, center and right regions. Drag to reorder or move between regions, or click a card for move/remove actions. Select a module and destination above, then click + to add it. The catalog includes existing custom modules and separators from the configuration and its includes. Changes take effect only after applying; the advanced JSONC editor remains available.

更新方式的第三项为自定义命令，命令输入框仅在选择该项时显示。

Custom command is the third update option; its input is shown only while that option is selected.

### 颜色与样式 / Colors and style

分隔箭头使用小号卡片，不显示大图标和标题。鼠标悬停仍可查看模块名称，拖动与点击操作保持可用。

在 **颜色与样式** 中关闭“跟随系统配色”，即可设置组件背景、文字颜色、悬停背景以及三组强调色。保留原有分区和箭头设计，只在当前栏使用的样式文件末尾追加带标记的覆盖。再次开启跟随配色会移除 ADWS 的颜色覆盖；原有 CSS 与导入文件保留。点击应用时同时备份配置与样式；发现外部改动会要求重新加载。

Separator arrows use compact cards without a large icon or title. Their module names remain available in tooltips, and drag/click actions still work.

Under **Colors and style**, turn off **Follow system colors** to customize the module background, text, hover background and three accent colors. The original sections and arrow design are retained through a marked override at the end of the active stylesheet. Turning color following back on removes this override while retaining existing CSS and imports. Applying changes backs up both configuration and style files, and refuses to overwrite external edits.

### 展开组、剪贴板和频谱 / Drawers, clipboard and spectrum

默认布局补齐了音量展开滑条、亮度展开组、底栏显隐按钮和电源展开组。内屏有 backlight 设备时提供原生亮度滑条；外接屏使用 5% / 65% / 100% 快捷档位，以及 ADWS 的逐屏调节面板和夜间模式入口。音量展开滑条通过 PulseAudio / PipeWire-Pulse 控制；没有该接口时使用 WirePlumber 图标与 ADWS 调节面板。

剪贴板位于中间区域，使用 ADWS 原生历史窗口，支持搜索、选择复制和确认清空。后端需要 `cliphist` 与 `wl-clipboard`；沿用已有历史，检测已有记录服务，避免重复启动 `wl-paste --watch cliphist store`。记录服务在顶部栏启动后运行，历史由 cliphist 管理。清空历史必须在窗口中确认。

`custom/cava` 使用 CAVA 的 raw 输出显示十根频谱条，每秒最多 15 帧，只提交有变化的内容。静音五秒后 CAVA 自行休眠。ADWS 只管理自己启动的 CAVA 子进程，栏关闭时退出；缺少 `cava` 时显示静态底线。接口依据 [CAVA 官方配置](https://github.com/karlstav/cava/blob/master/example_files/config)。点击频谱通过 `playerctl` 暂停／继续播放。

底栏显隐只向当前用户的底部 Waybar 进程发送信号，不广播给顶部栏。电源展开组提供关机、重启、注销和锁屏；前三项由 ADWS 弹窗确认。

The default layout includes a volume slider drawer, a brightness drawer, a bottom-taskbar visibility button and a power drawer. Laptop backlight devices get a native brightness slider. External monitors get 5% / 65% / 100% shortcuts, ADWS per-monitor controls and night mode. The volume slider needs PulseAudio or PipeWire-Pulse; WirePlumber-only systems use the icon and ADWS panel.

The center clipboard module opens an ADWS history window with search, copying and confirmed clearing. It requires `cliphist` and `wl-clipboard`, reuses existing history and avoids starting a duplicate recording watcher. History is stored by cliphist.

`custom/cava` requires CAVA, shows ten spectrum bars at up to 15 frames per second, suppresses duplicate frames and lets CAVA sleep after five silent seconds. It manages only its own child process. A missing CAVA executable leaves a static baseline. Clicking uses `playerctl` to pause/resume playback.

Taskbar visibility signals only the current user's bottom Waybar processes. Shutdown, reboot and logout require confirmation; the drawer also offers locking.

展开组的展开／收起时长为 650 ms，宽度沿用 GTK 的三次缓出曲线，并叠加 `cubic-bezier(0.22, 0.61, 0.36, 1)` 淡入淡出。宽度缓动由 [GTK Revealer](https://github.com/GNOME/gtk/blob/gtk-3-24/gtk/gtkrevealer.c) 实现，CSS 曲线控制透明度。

Drawers expand/collapse over 650 ms using GTK's native ease-out-cubic width interpolation, with a matching cubic Bézier opacity transition.

### 亮度滚轮 / Brightness scrolling

滚轮事件交给单个后台调节器，合并连续滚动，复用设备与当前亮度数据。DDC 写入期间到达的事件合并处理，不逐格重复扫描和读回显示器。正反滚动保留 5% / 100% 上下限的行为；空闲约 1.2 秒后后台自动退出。硬件异常记录在 `~/.cache/adws/quick-controls/brightness-worker.log`（支持 XDG_CACHE_HOME）。

Wheel events use one background worker, coalescing rapid input and reusing the device/current-brightness snapshot. Events arriving during slow DDC writes are merged rather than queued as repeated hardware scans. Direction changes retain correct 5% / 100% boundary behavior. The worker exits after about 1.2 seconds of inactivity; hardware errors go to the quick-controls cache log.

### 保持唤醒与屏幕取色 / Keep awake and screen colors

顶部栏模板、样式及 ADWS 操作入口独立实现，不调用 Shorin / ML4W 脚本。Waybar、GTK、CAVA、grim、wl-clipboard 等系统依赖可以保留。

熄屏图标使用 Waybar 的 Wayland idle-inhibit 后端：睁眼表示保持唤醒，闭眼表示允许系统原有的空闲熄屏策略。默认允许系统策略，单击切换，右键打开 ADWS 电源与电池设置。这个开关本身不会创建熄屏定时器；请在电源设置配置空闲策略。若另一个栏或应用仍在保持唤醒，允许熄屏也不会解除它的抑制。

取色优先使用系统 hyprpicker 的放大镜、实时颜色预览和自动复制；成功后可播放系统提示音。没有 hyprpicker 时，使用 ADWS 自有全屏界面：`grim` 先捕获各显示器，再展示颜色提示；单击将 `#RRGGBB` 复制到剪贴板，Esc 或右键取消。支持多屏位置与缩放，截图只保存在内存中，结束即释放。缺少 grim / wl-clipboard 或屏幕协议不可用时明确报错，不跳转到壁纸设置。不会自动替换用户已有的 Waybar 配置。

Top-bar defaults, CSS and ADWS actions are independently implemented without Shorin / ML4W scripts. System dependencies remain supported.

The native Waybar idle-inhibit backend keeps the session awake while active. Inactive means allowing the existing idle policy, which is the default; click to toggle and right-click for ADWS power settings. It does not create an idle timer or release inhibitors owned by another bar/application.

ADWS prefers the system hyprpicker for its magnifier, live color preview and automatic copying, with optional system sound feedback. Without hyprpicker, its own UI uses grim to capture all monitors before displaying overlays. Click to copy `#RRGGBB`; Esc/right-click cancels. Monitor positions and scaling are accounted for. Captures stay in memory and are released on exit. Missing dependencies/protocols produce an error rather than redirecting to wallpaper settings. Existing user Waybar configuration is preserved.

取色按钮保留三种独立鼠标操作：左键打开 ADWS 屏幕取色，右键进入 ADWS 主题／壁纸选择页，中键打开 ADWS 系统配色方案窗口。中键使用 ADWS 自有菜单，跟随系统配色与圆角；分为快捷操作与配色方案，当前方案带勾选标记，支持搜索。顶部可切换深色／浅色、第一主色／轮换主色，或重新生成；下方列出九种 Matugen 策略。选中即可应用并保存方案，更换壁纸时自动提取也沿用该方案。可以读取旧 Waypaper 配置中的壁纸路径，但不运行其脚本或 Matugen 用户钩子。

The color button retains three actions: left-click for ADWS screen picking, right-click for theme/wallpaper selection, middle-click for the ADWS palette selector. The selector uses an ADWS menu with live colors, rounded rows, separate quick-action and scheme sections, a current-scheme indicator and search. It offers immediate light/dark and first/cycling source-color toggles, regeneration and nine palette strategies. Selection applies and saves the preferences for future wallpaper extraction. It can read a legacy wallpaper path without executing legacy scripts or user hooks.

### 预设与手动备份 / Presets and manual backups

设置 → Waybar 配置提供四种预设：**标准**（当前箭头分区）、**简洁**（紧凑圆角栏）、**状态**（系统监视）、**Gnome 风格**（新版工作区指示器、中间日期时间、右侧合并状态菜单）。选择后可以独立预览；“载入预设”只更新待应用内容，点击“应用”才替换所选栏与当前样式文件，并先备份旧配置和样式。配置中其他栏的定义保留；共享该样式文件的栏也会受到样式变更影响。

“备份当前配置”备份磁盘上的已保存版本，包括递归 include 文件、当前样式和本地 CSS import（例如 colors.css），保留源文件与软链接。备份位于 `~/.local/state/adws/waybar-backups/`（支持 XDG_STATE_HOME）。每份备份包含来源路径与 SHA-256 的 `manifest.json`，界面显示实际备份目录。未应用的编辑不进入备份；缺少引用文件时明确失败，不创建不完整备份。

Settings → Waybar provides **Standard**, **Simple**, **Status** and **Gnome style** presets. Preview runs separately. Load stages changes; Apply backs up and replaces the selected bar and current stylesheet. Other bar definitions remain intact, but bars sharing that stylesheet also receive the new style.

Back up current configuration snapshots saved files, recursive includes, the stylesheet and local CSS imports without changing source files or symlinks. Backups live under `~/.local/state/adws/waybar-backups/` (or XDG_STATE_HOME), with original paths and SHA-256 hashes in `manifest.json`. Unsaved edits are excluded; missing references prevent incomplete backups.

GNOME 风格预设采用细黑顶栏：当前工作区显示白色长条，其余为灰色圆点；不显示应用标题和托盘。点击日期时间打开日历，点击右侧状态区打开 ADWS 合并快捷设置，包含音量、亮度、Wi-Fi、蓝牙、夜间模式及电源操作。没有可用设备的控件禁用；设备查询和调节在后台执行。该预设是独立 Waybar 实现，不依赖 GNOME Shell，未实现 GNOME 通知中心。交互布局参考 [GNOME 官方介绍](https://help.gnome.org/gnome-help/shell-introduction.html)。

The GNOME preset uses a thin black bar with a white pill for the active workspace and grey dots for the others, without application titles or a tray. Click the centered date/time for the calendar, or the combined status area for ADWS quick settings: volume, brightness, Wi-Fi, Bluetooth, night mode and session/power actions. Unavailable controls are disabled; queries and writes run in background workers. This independent Waybar implementation does not require GNOME Shell or implement its notification center.

“读取配置”只读取磁盘上的设置；“刷新 Waybar”安全重启所选配置的栏，不发送 SIGUSR2 原地重载信号。未运行时请用“启动 / 重启 Waybar”：它只处理所选配置，保留其他栏；重启日志位于 `~/.local/state/adws/waybar-logs/`。读取时会还原配置中记录的预设选择。

Read configuration only reloads saved settings into the editor. Refresh Waybar safely restarts the selected profile instead of using in-process SIGUSR2 reload. Start / restart Waybar also works when no matching bar is running, preserves other profiles and records launch diagnostics in `~/.local/state/adws/waybar-logs/`. Reading a saved configuration restores its selected preset.

标准预设的窗口标题两侧增加留白。文字默认继承系统 GTK 字体；“颜色与样式”中可关闭“跟随系统字体”并选择字体与字号，只覆盖窗口标题、时钟和提示文字，保留图标字体。字体选择独立于配色并随样式备份；切回系统字体时读取当前系统字体。

The standard preset adds room around window titles. Text inherits the system GTK font by default. Under Colors and style, disable Use system font to choose a font and size for titles, the clock and tooltips; icon fonts remain unchanged. Font preferences are independent from colors and included in stylesheet backups. Switching back reads the current system font.

四种预设的默认高度统一为 30。标准预设使用 ADWS 自绘的 SVG 符号折角，按组件实际高度铺满；设置栏高时同步调整折角宽度，避免修改文字字体或栏高后折角错位。右侧展开组保留展开过程，取消内容淡入，始终显示正常颜色。

All four presets default to a height of 30. Standard uses original ADWS SVG symbolic junctions stretched to the allocated module height; changing bar height updates their width independently from text fonts. Right-side drawers slide with full-color content and no opacity fade.

应用 Waybar 更改会保存备份并直接安全重启所选栏；未运行时启动，不影响底部 ADWS 栏或其他配置实例。“随 Niri 登录自启”在应用时生效：检测主配置及 include 中匹配该 Waybar 配置的直接启动项，关闭时只移除匹配项，保留其他应用；修改 Niri 文件前备份并校验。

Applying Waybar changes backs up the files and safely starts/restarts the selected bar, leaving other profiles and the ADWS bottom panel alone. Start with Niri login is committed on Apply. It detects matching direct startup commands in the main configuration and includes; disabling removes those commands only. Niri changes are backed up and validated.


## 整套导入与恢复备份 / Full import and restore

点击“导入配置文件…”选择主配置。自动读取同目录的 `style.css`，没有时会让你选择配套 CSS。递归收集 include、CSS @import 和本地 CSS 图片，保留注释，先暂存到设置页。点击“应用更改”时才备份当前整套配置，将依赖复制到独立的 `adws-imports` 目录，更新引用并重启所选栏。导入源目录之后可以移走；配置内调用的外部程序和脚本仍是运行依赖，不会被自动安装或执行。

点击“恢复备份…”选择记录并确认。恢复前再次备份当前配置，校验快照后恢复主配置、样式和依赖；保留软链接。应用后启动失败会回滚文件并尝试重启旧配置。旧版主配置或配置＋样式备份标为“旧版部分备份”，只能恢复当时保存的文件，无法补回当时没有备份的资源。

Import selects a main configuration and companion CSS, stages recursive includes/CSS imports/local images, then copies dependencies into a managed directory when applying. External programs/scripts remain runtime dependencies. Restore validates snapshots and preserves symlinks, backing up the current bundle first. Failed restarts roll back file changes. Legacy partial backups restore only the files they originally saved.

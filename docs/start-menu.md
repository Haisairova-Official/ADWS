# ADWS 1.31 B — 开始菜单与任务栏 / Start menu and taskbar

在“任务栏设置 → 开始菜单”独立页面中，选择开始按钮启动器：ADWS 开始菜单、fuzzel、rofi 或自定义命令。安装器默认选 ADWS，也保留其他选项；外部启动器未安装时会先询问。OOBE 可以保留当前选择或切换启动器。

ADWS 开始菜单使用 Rust / GTK3，内置 KDE、Vista Aero、Windows XP 风格，跟随 Waybar 配色。文字和图片开始按钮都会传递位置与所在屏幕，菜单向屏幕内侧展开并限制在输出范围内。直接运行 `adws start-menu` 或设置中的预览没有按钮坐标时，使用当前任务栏边缘作为回退位置。输入框提示“请输入搜索内容或命令”。输入时过滤应用；直接 Enter 执行输入的 shell 命令。点击结果或按 Down 选择后 Enter 启动应用；空输入不执行，Esc 或点击外部关闭。

三种预设使用不同布局：KDE 为搜索横栏、分类导航和快捷应用网格；Vista Aero 为玻璃边框、内嵌程序区、底部搜索和右侧账户栏；XP 为用户横幅、双色分栏与级联“全部应用”。快捷应用优先使用任务栏固定的应用，其余补充常见应用，不伪装成使用历史。XP 可点击“搜索”，或直接输入以显示搜索框。

头像优先读取系统账户服务的 IconFile，兼容 `~/.face`、`~/.face.icon`；昵称读取系统账户 RealName，回退到系统用户全名及登录名。没有头像时显示默认图标。账户服务和应用目录读取不阻塞菜单显示；应用控件分批创建。

开始菜单浮入淡出与吸附/悬浮移动跟随“窗口动效”，页面切换跟随“选项卡动效”。吸附时四角变为直角，悬浮时恢复用户圆角；切换桌面直接更新占用状态，不依赖配色变化。

关闭“在任务栏显示开始按钮”只隐藏组件，保留全部偏好；统一设置的“开始菜单设置…”或 `adws config --tab start` 始终可以打开此页。组件列表的开始按钮设置入口也跳到同一页。隐藏按钮时不会加载其旧图片路径。

## 电源与键位

“电源与会话”按系统能力显示锁屏、注销、挂起、休眠、重启和关机。注销、重启和关机在菜单内确认，取消不会执行。操作前释放菜单的键盘占用，方便系统授权或锁屏；错误显示在菜单内。锁屏需要已安装的锁屏程序。

“开始菜单”设置页提供独立的“应用键位方案”按钮：

| 方案 | 单独轻按 Super | 单独轻按 Ctrl |
| --- | --- | --- |
| Waylander | 全览 | 无动作 |
| Traditional | ADWS 开始 | 全览 |
| Reversed | 全览 | ADWS 开始 |

只有检测到 Niri 支持单修饰键触发时才能应用。当前标准上游 Niri 不具备此能力，支持该功能的分支可以使用；ADWS 本身及普通组合键不受影响。不会把原始按下事件当成轻按，Ctrl+C 等组合键保持原样。Niri 的 `Mod` 单键绑定也随 Super 方案覆盖（通常两者是同一个键）；定制了其他 `Mod` 键的用户应注意该单键行为也会变化。

打开设置不会改键位。应用时追加受管理的 include，保留原 binds 文件，先校验再原子替换，备份为 `config.kdl.adws-keyboard-bak`。卸载移除 ADWS 管理块，原有绑定恢复。键位属于本机 Niri 配置，不随任务栏布局导入自动启用。即使隐藏开始按钮，键位仍可打开 ADWS 菜单。

## CSS

预设位于 `config/start-menu/`。建议在自己的配置目录创建 CSS，并在开始按钮设置里填入路径，避免更新覆盖。自定义样式在预设之后加载；文件和配色变更会自动重载，语法错误时保留上一次有效样式。`@import` 支持本地文件；图片 `url(...)` 请使用绝对路径。

```css
.adws-start-menu {
    border-radius: 18px;
    background: alpha(@adws_bg, 0.94);
}
.adws-start-menu row:hover {
    background: @adws_accent;
    color: @adws_on_accent;
}
```

配色别名：`@adws_bg`、`@adws_fg`、`@adws_accent`、`@adws_on_accent`、`@adws_border`。
常用类：`.menu-header`、`.menu-body`、`.menu-sidebar`、`.menu-search`、`.menu-footer`、`.active-category`、`.menu-programs`、`.menu-home`、`.shortcut`、`.menu-avatar`。XP 的级联菜单使用 `menu.xp-programs`。

## 任务栏外观与操作

- **分体**：关闭时为整体表面；开启时前、中、后三个有内容的区域分别显示，无内容的区域不绘制色块。组件继续按内容请求空间。
- **模式**：吸附屏幕边缘；当前任务栏有活动项目卡时吸附；悬浮。随任务栏上、下、左、右位置生效。固定但未开启的图标不算活动项目卡。
- **材质**：纯色；云母（带主题色的柔和表面）；亚克力（透明与细纹理）；糖果（玻璃高光渐变）。这四项是 GTK 材质外观，不是 Windows 专有合成器效果。背景模糊需要窗口管理器已支持并启用，普通 Niri 不会因选择材质而写入不兼容的模糊规则。
- **终止**：默认按住 Shift 右键时用“终止”替换“关闭”；也可始终列在关闭下方，或完全禁用。终止是强制结束所属进程，同一进程的其他窗口也会关闭。普通关闭与 Peek 叉号仍请求应用正常关闭。
- **圆角与动画**：右键菜单、子菜单与 Peek 跟随任务栏外观的圆角。终止项红色悬停和预览关闭按钮的过渡跟随窗口动效选项；系统关闭动画时也遵循系统设置。

## English

Choose ADWS Start, fuzzel, rofi or a custom command under **Taskbar settings → Start menu**. The installer defaults to ADWS and asks before installing a missing external launcher. OOBE can retain or change this selection.

The Rust/GTK3 menu has three original presets and follows the Waybar palette. Both text and image buttons pass their logical coordinates and monitor; the menu opens inward and clamps to the output. CLI/settings previews without an anchor fall back to the configured panel edge. Typing filters applications. Direct Enter runs the typed shell command; clicking a result or selecting it with Down then Enter launches an application. Empty input does nothing. Escape/outside-click dismisses the menu.

Select a custom CSS file to override the preset. Palette and stylesheet changes reload automatically; invalid edits retain the last valid style. Local imports are supported; use absolute image URLs. The example and class/color names above apply to every preset.

Split mode draws only occupied Front/Center/Back sections. Docking can be permanent, conditional on active window cards, or floating, on any edge. Inactive pinned icons do not trigger conditional docking. Solid, Mica, Acrylic and Candy are GTK surface appearances; actual background blur belongs to the compositor, and no unsupported blur configuration is injected into vanilla Niri.

Termination defaults to Shift+right-click, can appear below Close, or be disabled. It force-kills the owning process, potentially affecting its other windows. Normal Close and preview close controls remain graceful. Menu/Peek corners follow panel appearance; destructive hover transitions follow window-animation and system-animation preferences.

The presets now have distinct widget layouts: Kickoff-style navigation and shortcut grid; Vista's inset program well, bottom search and account rail; XP's user banner, two-tone columns and cascading All Programs. XP reveals search on typing or via its Search link. Shortcuts prioritize taskbar pins, then common applications; they do not claim to represent usage history.

The account service supplies the real name and avatar, with local `.face`/`.face.icon`, GECOS and login-name fallbacks. Catalog discovery runs off the GTK thread and rows are created in bounded batches. Window animations control menu fade/float and reversible docking motion; docked outer corners are square while split inner ends retain their radius. Tab animations control page crossfades. Shift mode follows modifiers received after the popup grab as well as while the menu is open.

The dedicated Start menu page stays available when the taskbar Start button is disabled. Open it from unified settings or `adws config --tab start`. Hiding the button preserves all preferences and skips loading unused image files.

Power and session offers only detected actions. Logout, restart and shutdown require confirmation inside the menu; cancellation executes nothing. The menu releases its keyboard grab before an action so a locker or authorization agent can receive input. Errors remain visible in the menu.

The Start settings page has an independent **Apply keyboard profile** control. Waylander maps Super to overview and Ctrl to no action; Traditional maps Super to ADWS Start and Ctrl to overview; Reversed maps Ctrl to ADWS Start and Super to overview. These are taps and releases, not modifier presses that interfere with combinations.

The current upstream Niri lacks modifier-tap support; compatible forks can enable these profiles. ADWS and regular shortcuts still work on upstream Niri. Capability detection disables unsupported profiles. Applying validates and backs up the config, adds a managed include, and preserves original binding files. Removing the managed block restores prior bindings. The compositor's standalone `Mod` binding follows Super too; users who remapped Mod should account for that. Profiles are local Niri settings and are not activated by importing a taskbar layout.

可选标准版兼容构建 / Optional upstream compatibility build: [Niri 补丁与恢复说明](../patches/niri/README.md).

底部铭文从 `build-info.json` 读取 `display_version`，例如 **ADWS 1.31 B**；缺失时回退为 ADWS。
The footer reads `display_version` from `build-info.json`, e.g. **ADWS 1.31 B**, falling back to ADWS when absent.

## Responsiveness and recovery / 响应与恢复

Start launches leave GTK's thread immediately; application discovery stays in the
background and home shortcuts populate before the entire application list.
The opening animation uses ease-out so it becomes visible promptly.

The taskbar's Rust window module observes GTK with an independent thread.
A continuous 10-second missing heartbeat records a diagnostic report and asks a
separate helper to recover only its original parent using a pidfd. Suspend-like
sampling gaps reset the counter. Shorter pauses stay in `taskbar.log`.
Recovery is limited to two attempts per ten minutes, persisted across restarts.
Reports rotate at 512 KiB (one previous log) under
`$XDG_STATE_HOME/adws/taskbar-recovery.log`, normally
`~/.local/state/adws/taskbar-recovery.log`. Reports contain process status and
wait location, not the process environment. Set `ADWS_TASKBAR_WATCHDOG=0` before
starting the bar to disable recovery during debugging. Removing the window
module also removes its heartbeat observer. Recovery is a fallback, not proof
that an underlying rendering stall is fixed.

无响应保护默认开启：连续 10 秒没有界面心跳才恢复，10 分钟最多两次。
休眠后的采样间隔会重置计数；短暂抖动只写任务栏日志。诊断与恢复结果保存在
`~/.local/state/adws/taskbar-recovery.log`，不会记录环境变量。

所有分体沿排列方向两端各留 5px 内容内边距，横栏为左右、竖栏为上下。
分体端头可选“同两侧一样”或“尖角（< >）”。尖端深度为任务栏厚度的一半，
额外加在 5px 缓冲以外，不占用插件内容。跟随设置时，吸附只取消整条任务栏最外侧四个角的圆角；内侧端头与中间段保留设置的圆角。
自动吸附只由当前屏幕、当前桌面的非最小化平铺窗口触发；浮窗不触发。
Pointed ends are clipped polygons with separate tip space and 5px content padding;
matching ends retain the configured radius on inner ends and the center; docking squares only the outer corners. Pointed mode also applies to front/back segments, including when the center slot is empty.
Only active-workspace tiled windows on this output trigger automatic docking.
Empty center segments receive no padding or surface.

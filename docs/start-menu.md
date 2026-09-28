# ADWS 1.31 B — 开始菜单与任务栏 / Start menu and taskbar

在“任务栏设置 → 组件与插件”中，选择开始按钮启动器：ADWS 开始菜单、fuzzel、rofi 或自定义命令。安装器默认选 ADWS，也保留其他选项；外部启动器未安装时会先询问。OOBE 可以保留当前选择或切换启动器。

ADWS 开始菜单使用 Rust / GTK3，内置 KDE、Vista Aero、Windows XP 风格，跟随 Waybar 配色。文字和图片开始按钮都会传递位置与所在屏幕，菜单向屏幕内侧展开并限制在输出范围内。直接运行 `adws start-menu` 或设置中的预览没有按钮坐标时，使用当前任务栏边缘作为回退位置。输入搜索，Enter 启动首个匹配应用，Esc 或点击外部关闭。

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
常用类：`.menu-header`、`.menu-body`、`.menu-sidebar`、`.menu-search`、`.menu-footer`、`.active-category`。

## 任务栏外观与操作

- **分体**：关闭时为整体表面；开启时前、中、后三个有内容的区域分别显示，无内容的区域不绘制色块。组件继续按内容请求空间。
- **模式**：吸附屏幕边缘；当前任务栏有活动项目卡时吸附；悬浮。随任务栏上、下、左、右位置生效。固定但未开启的图标不算活动项目卡。
- **材质**：纯色；云母（带主题色的柔和表面）；亚克力（透明与细纹理）；糖果（玻璃高光渐变）。这四项是 GTK 材质外观，不是 Windows 专有合成器效果。背景模糊需要窗口管理器已支持并启用，普通 Niri 不会因选择材质而写入不兼容的模糊规则。
- **终止**：默认按住 Shift 右键时用“终止”替换“关闭”；也可始终列在关闭下方，或完全禁用。终止是强制结束所属进程，同一进程的其他窗口也会关闭。普通关闭与 Peek 叉号仍请求应用正常关闭。
- **圆角与动画**：右键菜单、子菜单与 Peek 跟随任务栏外观的圆角。终止项红色悬停和预览关闭按钮的过渡跟随窗口动效选项；系统关闭动画时也遵循系统设置。

## English

Choose ADWS Start, fuzzel, rofi or a custom command under **Taskbar settings → Components & plugins**. The installer defaults to ADWS and asks before installing a missing external launcher. OOBE can retain or change this selection.

The Rust/GTK3 menu has three original presets and follows the Waybar palette. Both text and image buttons pass their logical coordinates and monitor; the menu opens inward and clamps to the output. CLI/settings previews without an anchor fall back to the configured panel edge. Search, Enter to launch and Escape/outside-click to dismiss are supported.

Select a custom CSS file to override the preset. Palette and stylesheet changes reload automatically; invalid edits retain the last valid style. Local imports are supported; use absolute image URLs. The example and class/color names above apply to every preset.

Split mode draws only occupied Front/Center/Back sections. Docking can be permanent, conditional on active window cards, or floating, on any edge. Inactive pinned icons do not trigger conditional docking. Solid, Mica, Acrylic and Candy are GTK surface appearances; actual background blur belongs to the compositor, and no unsupported blur configuration is injected into vanilla Niri.

Termination defaults to Shift+right-click, can appear below Close, or be disabled. It force-kills the owning process, potentially affecting its other windows. Normal Close and preview close controls remain graceful. Menu/Peek corners follow panel appearance; destructive hover transitions follow window-animation and system-animation preferences.

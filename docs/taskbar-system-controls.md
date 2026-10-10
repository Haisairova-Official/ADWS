# Taskbar system controls / 任务栏系统组件

在 **设置 → 组件与插件 → 添加组件** 中添加“系统托盘”“亮度”或“声音”。三者可以移除，每类只能添加一个；四个屏幕边缘均可使用。已有布局不会被自动改写。

- **系统托盘**：前三个活动图标直接显示；其余放入向屏幕内侧展开的图标面板。应用退出后自动补位。支持 StatusNotifierItem、原生应用菜单、左键激活和中键辅助动作；不收纳 XEmbed 老式托盘。
- **亮度**：左键快速调节，滚轮每格 5%；右键显示各屏亮度、色温和夜间开关。硬件背光通过 brightnessctl，外接屏通过 ddcutil/DDC-CI；有 wl-gammarelay-rs 时可按输出调节软件亮度、色温。不支持的功能禁用，不显示虚假的可用滑块。
- **色温**：优先接入已运行的 wl-gammarelay-rs，亦可使用已安装的 wlsunset 按输出调节。ADWS 只停止自己启动并记录过的 wlsunset，不终止其他调色程序。wlsunset 后端的开关开启设为 4500 K，关闭恢复正常色温；手动滑块立即设置色温。
- **声音**：左键调默认输出，滚轮每格 5%，右键打开带设备和应用独立音量、静音的合成器。使用 pactl 与 PulseAudio 或 PipeWire 的 Pulse 服务；忽略 null 虚拟占位设备，没有真实可用输出时显示“无可用配置”。

DDC 操作需要设备开启 DDC-CI，并允许当前用户访问 I²C。组件不自动提升权限或安装软件。检测、调节和刷新不阻塞任务栏主线程；滑块连续拖动时合并写入。关闭弹窗会停止刷新，并保留最后一次调节。

Add **System tray**, **Brightness** and **Sound** from **Settings → Components & plugins → Add component**. Each is optional and limited to one instance. Existing layouts are preserved.

The tray shows three active StatusNotifierItem icons and an inward overflow popup. Brightness supports hardware backlight (brightnessctl), DDC-CI displays (ddcutil), and per-output color controls with wl-gammarelay-rs or wlsunset. Sound uses pactl with PulseAudio or PipeWire Pulse and provides separate master/application volume and mute controls. Left-click opens quick controls, the wheel adjusts by 5%, and right-click opens the detailed panel. Unavailable hardware/services disable the relevant controls. No automatic privileged operation or package installation occurs.

图标支持主题名称、应用提供的 IconThemePath、绝对文件路径与 ARGB 像素图；保持原始配色和长宽比，按屏幕缩放清晰显示，缺失图标可回退到应用提供的像素图。未变化的图标复用渲染结果。

声音与亮度弹窗实时跟随任务栏配置的圆角、背景色及纯色／云母／亚克力／糖果材质；透明背景模糊依赖窗口管理器。弹窗使用 Waybar 图层命名以沿用已有的背景模糊规则。

Tray icons support themed names, application IconThemePath, absolute file paths and ARGB pixmaps, retaining color and aspect ratio at the output scale. Unchanged icons reuse their render. Audio and brightness popups follow taskbar colors, configured radius and Solid/Mica/Acrylic/Candy materials live. Background blur depends on the compositor; their Waybar layer namespace reuses existing blur rules.

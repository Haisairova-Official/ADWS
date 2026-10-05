# 1.35-N Pre-Release

构建日期 / Build date: 2026-10-05 · 分支 / Branch: `Pre-1.35`

- 修复 Ubuntu 下中文路径和设置组件兼容问题。（M）
- 更新器显示后台下载进度，确认后自动校验与安装。（M）
- 新增 Waybar 模块兼容性检查，可安装/升级或构建官方兼容版本。（N）
- 可选安装 Nerd Fonts 图标字体，帮助新增依赖修复命令。（N）

Fix Ubuntu paths/settings compatibility and add background update progress with installation after confirmation. Add Waybar compatibility repair and optional Nerd Fonts icon installation, with commands documented in help.



依赖修复 / Dependency repair:

```sh
adws check --repair-waybar
adws check --install-fonts
```

安装前询问；Waybar 源码版使用专用用户目录，图标字体保留原来的正文字体。
Ubuntu 必须在目标系统构建，不能使用 Arch 预构建组件。

Repair asks before installation. Built Waybar uses a private user directory;
icon installation preserves existing text fonts. Ubuntu needs native target-system
builds, not Arch prebuilt components.

[Ubuntu 安装说明 / Installation guide](ubuntu-install.md) · [此前累计更新 / Previous cumulative notes](update-notes-1.35-L-2026-10-05.md)

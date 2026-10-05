# Terminal appearance presets / 终端外观预设

在「设置 → 默认应用 → 终端外观预设」选择部署 Kitty 或 Alacritty。
配置源自 Akizuki 2026-10-05 的 Kitty：JetBrains Maple Mono、13.5 pt、5 px 内边距、80% 不透明度、无标题栏、块状光标及当前 16 色配色。Kitty 包含原配置与所需主题文件；Alacritty 提供同款外观，不包含 Kitty 独有的光标拖尾。

部署前将原配置备份到 `$XDG_STATE_HOME/adws/terminal-presets/`（默认 `~/.local/state/adws/terminal-presets/`），保持配置软链接；失败会回滚。缺少字体时回退为 monospace，缺少 zsh 时使用当前 shell。预设不安装终端或字体，也不改变默认终端；默认终端可在同一页面单独选择。

Deploy from Settings → Default applications → Terminal appearance presets.
The presets capture Akizuki's Kitty appearance on 2026-10-05: JetBrains Maple Mono, 13.5 pt, 5 px padding, 80% opacity, no title bar, block cursor and the current 16-color palette. Kitty includes its theme files. Alacritty matches the appearance but has no Kitty cursor-trail equivalent.

Existing files are backed up under `$XDG_STATE_HOME/adws/terminal-presets/`; symlinks are preserved and failed writes roll back. Missing fonts fall back to monospace; missing zsh falls back to the current shell. Deployment neither installs a terminal/font nor changes the default terminal.

Reference: [Alacritty configuration](https://alacritty.org/config-alacritty.html).

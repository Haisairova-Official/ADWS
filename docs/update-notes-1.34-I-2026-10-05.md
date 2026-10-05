# Major 1.34 · Minor I · 2026-10-05

开发分支 / Development branch: `Pre-1.35`.

- 修复管理员授权后崩溃和菜单动作失效，授权与错误窗口改为紧凑布局并跟随 ADWS 配色。（G）
- 优化开始菜单重复打开速度，短时保留已加载的界面；配置和应用列表变化后自动刷新，闲置后释放缓存。（1.34）
- 保存当前 Kitty 配置为预设，并提供 Alacritty 同款；支持一键部署、自动备份和字体回退，补充默认终端选择。（H）
- 壁纸新增 Matugen 安装／卸载入口，可选自动提取主体色；更换壁纸后实时更新任务栏和设置，卸载保留配色。（I）

- 新增独立 Waybar 配置页，支持尺寸、边距、组件排列及 JSONC 编辑；保存前备份，保留注释，只刷新匹配的顶部栏。

- 提供通用顶部 Waybar 默认配置，移除 Shorin 等专属脚本依赖；新安装保留已有顶部栏，支持独立临时预览。

## English

- Add standalone Waybar settings for size, margins, modules and JSONC editing, with backups and targeted reload.
- Add portable top Waybar defaults and a temporary preview; preserve existing local bars.
- Fix crashes after administrator authentication and lost menu actions; use compact authorization/error dialogs matching ADWS colors. (G)
- Speed up repeated Start opens by retaining the loaded UI briefly; refresh on configuration/application changes and release it after idle time. (1.34)
- Bundle the current Kitty configuration and a matching Alacritty preset with one-click deployment, backups and font fallback; add default terminal selection. (H)
- Add Matugen install/uninstall controls and optional wallpaper color extraction; update taskbar/settings live and preserve colors when uninstalling. (I)

验证：管理员授权回归；四套菜单主题的键盘操作、界面复用和配置刷新；终端预设备份与失败回滚；Matugen 实际提色与旧配色保护。复用后六次菜单打开约 15–29 ms（隔离 X11 测试，不代表所有设备）。

Verified authorization regressions, keyboard behavior across four themes, menu reuse/configuration refresh, terminal backup/rollback and real Matugen extraction. Six cached menu opens took about 15–29 ms in isolated X11 tests; timings depend on the device.

[终端预设 / Terminal presets](../samples/terminal-presets/README.md)

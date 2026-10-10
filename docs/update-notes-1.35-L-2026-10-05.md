# 1.35-L Pre-Release　构建日期：2026-10-05

最新更新：

- 开始 Rust 化，插件运行器优先使用 Rust，插件增加语言标签；SSH／TTY 安装会先问你是不是认真的。（A）
- 新增原生开始菜单，提供 KDE、Vista Aero、Windows XP 和 AkiACG 主题，支持搜索、命令、电源操作、自定义 CSS 与动效。（B）
- 开始按钮支持独立设置、重复添加、自定义图片和右键动作；新增三套快捷键方案与可选 Niri 兼容补丁。（B／D）
- 新增分体任务栏、吸附／悬浮模式和四种材质；Peek 支持关闭窗口，完善圆角、尖角和内容留白。（B／1.33）
- 新增独立 ADWS 系统设置，整合默认应用、网络、蓝牙、声音、电源、账户、地区、输入法与快捷键，不再依赖其他桌面的设置套件。（C）
- 显示设置支持 Niri／Hyprland 和多屏拖动排布；壁纸平铺展示，手动添加会自动复制到壁纸目录。（C）
- 组件布局支持横向拖动、跨区排序、重复添加与实时预览；窗口图标栏始终保留，插件支持单例声明。（D／E）
- 新增内置托盘，超过三个图标折叠；声音与亮度支持点击、滚轮及详细面板，外观跟随任务栏。（E）
- 卸载保留系统配置，已有个人布局不会被默认配置覆盖；登录启动项支持右键删除并再次确认。（F）
- 修复 Shift＋右键切换“结束进程”和管理员授权后崩溃的问题，授权与错误窗口更紧凑。（G）
- 优化开始菜单重复打开速度，头像与昵称按登录缓存，按钮和快捷键定位统一；闲置后释放界面缓存。（1.34）
- 新增 Kitty 与同款 Alacritty 预设，一键部署前自动备份；默认应用补充默认终端。（H）
- 壁纸新增 Matugen 安装／卸载与自动提取主体色，换壁纸时实时更新配色，卸载保留已有颜色。（I）
- 新增 Waybar 配置页与标准、简洁、状态、GNOME 风格四套预设，支持模块布局、独立预览和配置备份。（J）
- 顶部栏补齐剪贴板、音频频谱、取色与配色菜单、保持唤醒、任务栏显隐、音量／亮度及电源展开；系统更新支持 yay／paru 或自定义命令。（K）
- Waybar 支持整套配置导入、备份恢复与 Niri 自启；应用与刷新改为重启所选栏，避免原地重载导致崩溃。（L）
- 优化顶部栏折角随高度缩放、默认 30px 高度、标题间距和系统字体跟随；修复隐藏托盘图标的提示位置。（L）
- 窗口项目卡与 Peek 的点击切换改为后台请求，连续点击不再无限积压；补充请求超时与默认卡顿警告日志。（1.35）

- 修复悬停窗口图标时样式路径持续累积造成的任务栏卡顿，补充重复悬停和 Peek 回归验证。
- 插件新增独立 Watchdog，崩溃或无响应时通知并在设置中标黄；异常退出不再反复自动重启。
- NCMLyricsBar 1.1.0 配色修订：上一首、下一首按钮实时跟随任务栏主题。

已确认并修复 GTK 样式路径累积导致的卡顿，实机短时回归正常；更长时间的使用仍需持续验证。

Development branch: `Pre-1.35`. This pre-release includes Rust plugin supervision, native Start themes, independent system settings, draggable layouts, tray/audio/brightness controls, authorization fixes, cached Start menus, terminal presets, wallpaper colors and four configurable Waybar presets. Top-bar controls are implemented independently of Shorin/ML4W scripts. Waybar configuration bundles (includes, CSS and local images) are staged before applying, with a backup restore action; refresh/application restarts only the selected profile. Window focus requests now run in a bounded background worker with timeouts. The confirmed GTK widget-path accumulation causing icon-hover stalls is fixed. Independent plugin watchdogs report failures and mark affected instances in settings; abnormal exits no longer trigger repeated automatic retries. NCMLyricsBar 1.1.0 controls now track the panel palette. Extended daily-use verification remains ongoing.

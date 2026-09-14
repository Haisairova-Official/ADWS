# 上游 Niri 窗口项目卡缺失

用户报告 Arch 与 Ubuntu 的原生 Niri + Waybar 环境均出现窗口卡片不显示。
未收到具体版本号，尚未进行这两套实际环境的复测。

已确认代码缺陷：vendored Window 强制反序列化 Shorin 的 is_minimized 字段，
而 [上游 Window 定义](https://raw.githubusercontent.com/YaLTeR/niri/main/niri-ipc/src/lib.rs)
没有该字段。首次 WindowsChanged 解析失败后，旧代码退出监听线程，无法显示窗口卡片。

修复：缺失扩展字段默认 false；未知/不兼容事件记录后跳过；断线明确识别 EOF 并延迟重连。
原生 Niri 不支持 ToggleWindowMinimized 时回退 FocusWindow。

验证：上游形状的窗口/工作区事件（两种初始化顺序）能产生窗口卡片；
Shorin minimized=true 保留；本地 socket 上未知事件后仍能读取下一事件，EOF 能明确识别。
需要真实 Arch/Ubuntu + 支持 CFFI v2 的 Waybar 复测后，才可宣称这两套环境已通过发布验收。

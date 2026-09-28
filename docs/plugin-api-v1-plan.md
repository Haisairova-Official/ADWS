# Plugin API v1.0 接入记录

已纳入 ADWS 1.25，实现与公开约定见 [正式规范](mplg-spec.md)。
用户提供的 [原始草案](plugin-api-v1-proposal.md) 保留作设计参考。

- 简化清单、API/最低版本校验、text/rows 适配和旧包兼容。
- install/add、按 ID 删除、最高版本选择、缓存校验及解包锁。
- 七类设置、插件独立中英文词典、默认值合并。
- 统一 JSON-lines 执行器、错误占位、带 ID 的日志及静默超时。
- HelloWorld sample 与 NCMLyricsBar 1.0.1 参考插件。
- 旧歌词 ID 在加载时映射，保存时使用新 ID，保留布局与设置。

协议补充：只支持 Python 新入口；缺 adws 按 API 1 / ADWS 1.25；
30 秒静默上限、1 MiB 行上限；choice 使用 value/label 对；
text 支持 Waybar 标记，rows 使用纯文本。

原生 Niri 兼容性修复和真实环境复测仍属于 1.25 发布验收，
不可因 API 文档已完成而跳过。发布前需审核最终更新摘要。

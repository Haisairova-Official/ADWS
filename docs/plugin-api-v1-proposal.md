> 状态：用户提供的 Plugin API v1.0 设计参考，尚未全部实现。
> 当前代码差异及待明确事项见 [接入清单](plugin-api-v1-plan.md)。
> 本文不是当前已发布插件格式的兼容性承诺。

# MNWS Plugin API v1.0

## 1. 目标

v1.0 只解决四件事：

1. `.mplg` 可以被 MNWS 安装和识别
2. 插件可以向任务栏输出内容
3. 插件可以声明设置项
4. MNWS 可以统一管理插件启用、禁用、配置和运行

不追求“大而全”。

---

# 2. `.mplg` 定位

`.mplg` 是 MNWS 插件包。

v1.0 暂时只支持：

```text
Panel Plugin
```

即任务栏插件。

未来再扩展：

```text
Desktop Widget
Service
Menu Provider
KDE Plasmoid Adapter
```

但这些不进入 v1.0。

---

# 3. 插件目录

最简单结构：

```text
MyPlugin/
├── plugin.json
├── main.py
└── README.md
```

带设置和语言：

```text
MyPlugin/
├── plugin.json
├── main.py
├── locale/
│   ├── zh.json
│   └── en.json
└── README.md
```

`.mplg` 本质上可以继续使用 ZIP。

---

# 4. Plugin ID

统一使用 reverse-domain 格式。

例如：

```text
org.AkiACG_Community.NCMLyricsBar
```

要求：

- 全局唯一
- 安装后不可修改
- 用作配置和运行时标识

v1.0 不强制全小写。

---

# 5. `plugin.json`

建议 v1.0 保持简单：

```json
{
  "id": "org.AkiACG_Community.NCMLyricsBar",
  "name": "NCMLyricsBar",
  "version": "1.0.0",
  "description": "NetEase Cloud Music lyrics for MNWS",

  "mnws": {
    "api": 1,
    "minVersion": "1.25"
  },

  "entry": "main.py",

  "renderer": "panel.rows-v1",

  "defaults": {
    "width": 420,
    "align": 0.5
  },

  "settingsSchema": []
}
```

v1.0 必需字段：

```text
id
name
version
entry
renderer
```

可选：

```text
description
mnws
defaults
settingsSchema
```

---

# 6. API 版本

只需要：

```json
"mnws": {
  "api": 1,
  "minVersion": "1.25"
}
```

MNWS 加载时检查：

```text
api != 1
→ 拒绝加载

MNWS version < minVersion
→ 拒绝加载
```

暂时不做复杂版本协商。

---

# 7. Renderer

v1.0 只保留两个 renderer。

## `panel.text-v1`

最简单插件：

```json
{
  "text": "Hello MNWS",
  "tooltip": "Example plugin"
}
```

适合：

- CPU
- 温度
- 网络
- 简单状态

---

## `panel.rows-v1`

双行内容：

```json
{
  "primary": "僕らが見た光",
  "secondary": "我们曾看见的光",
  "tooltip": "NCMLyricsBar"
}
```

由 MNWS 原生 renderer 负责：

- 字体
- 对齐
- 高度
- ellipsis
- 分隔线
- 主题颜色

插件只输出数据。

---

# 8. 插件输出协议

v1.0 采用最简单的模型：

```text
MNWS
  ↓ execute
main.py
  ↓ stdout
JSON
```

要求：

```text
stdout
→ 只能输出插件数据 JSON

stderr
→ 日志

exit 0
→ 成功

exit != 0
→ 插件运行失败
```

例如：

```python
import json

print(json.dumps({
    "text": "Hello MNWS",
    "tooltip": "Hello World plugin"
}))
```

暂时不做 socket、D-Bus 或复杂 IPC。

---

# 9. Settings

继续保留当前设计：

```text
--settings-json
```

例如 MNWS 执行：

```bash
python main.py --settings-json '{"offset":200,"color":"#fff"}'
```

v1.0 不重构这一部分。

以后再换 stdin / file / socket。

---

# 10. `settingsSchema`

v1.0 支持：

```text
string
number
boolean
choice
color
font
url
```

例如：

```json
{
  "settingsSchema": [
    {
      "key": "offset",
      "label": "同步偏移",
      "type": "number",
      "default": 0
    },
    {
      "key": "font",
      "label": "字体",
      "type": "font",
      "default": ""
    }
  ]
}
```

MNWS 自动根据 schema 生成设置界面。

配置保存在：

```text
taskbar-layout.json
```

而不是写回 `.mplg`。

---

# 11. i18n

v1.0 可以顺手支持，但保持非常简单。

```text
locale/
├── zh.json
└── en.json
```

例如：

`zh.json`

```json
{
  "plugin.name": "网易云歌词",
  "settings.offset": "同步偏移",
  "settings.font": "字体"
}
```

`en.json`

```json
{
  "plugin.name": "NetEase Lyrics",
  "settings.offset": "Sync offset",
  "settings.font": "Font"
}
```

manifest：

```json
{
  "name": "plugin.name"
}
```

设置：

```json
{
  "key": "offset",
  "label": "settings.offset"
}
```

规则：

```text
zh*
→ zh.json

其他
→ en.json
```

如果 key 不存在：

```text
→ 直接显示 key
```

这样实现最简单。

---

# 12. 安装位置

统一：

```text
~/.local/share/mnws/plugins/
```

例如：

```text
~/.local/share/mnws/plugins/
└── org.AkiACG_Community.NCMLyricsBar_1.0.0.mplg
```

MNWS 扫描此目录。

---

# 13. 插件缓存

解压后的插件不要直接散落在安装目录。

建议：

```text
$XDG_CACHE_HOME/mnws/plugins/
```

例如：

```text
~/.cache/mnws/plugins/
└── org.AkiACG_Community.NCMLyricsBar/
```

流程：

```text
.mplg
 ↓
validate
 ↓
materialize
 ↓
cache directory
 ↓
execute
```

---

# 14. 插件生命周期

v1.0 不需要搞复杂状态机。

只定义：

```text
discover
validate
enable
run
disable
remove
```

即可。

---

# 15. 插件管理命令

建议 v1.0 提供：

```bash
mnws mplg list
mnws mplg build <directory>
mnws mplg install <file.mplg>
mnws mplg remove <id>
mnws mplg validate <file.mplg>
mnws mplg run <id>
```

已有功能能复用就直接复用。

---

# 16. `build`

```bash
mnws mplg build plugins/NCMLyricsBar
```

执行：

1. 检查 `plugin.json`
2. 检查必要字段
3. 检查入口文件
4. 检查 Plugin ID
5. 检查 renderer
6. 检查 settingsSchema
7. 打包为 `.mplg`

输出：

```text
org.AkiACG_Community.NCMLyricsBar_1.0.0.mplg
```

---

# 17. 安全检查

v1.0 至少必须检查：

```text
../
绝对路径
ZIP path traversal
缺失 plugin.json
重复 plugin.json
不存在的 entry
不支持的 renderer
不支持的 API version
```

暂时不做：

```text
signature
publisher verification
sandbox
permission enforcement
```

---

# 18. 错误处理

插件运行失败时：

```text
任务栏不要崩
```

MNWS 应：

```text
记录 stderr
显示 fallback
继续运行其他插件
```

例如：

```text
Plugin failed
```

或者直接隐藏该组件。

---

# 19. 日志

插件：

```text
stdout → protocol
stderr → logs
```

MNWS 可以给 stderr 自动加前缀：

```text
[plugin:org.AkiACG_Community.NCMLyricsBar]
```

暂时不用设计复杂日志 API。

---

# 20. NCMLyricsBar

建议把现有网易云歌词插件正式改名为：

```text
org.AkiACG_Community.NCMLyricsBar
```

并作为：

> MNWS Plugin API v1.0 Reference Plugin

它用于验证：

- `.mplg`
- settingsSchema
- i18n
- `panel.rows-v1`
- 网络请求
- MPRIS
- 自定义 API
- 原生 renderer

但它不应该再叫 sample。

---

# 21. Sample

真正的 sample 只需要一个：

```text
plugins/sample/
```

大约几十行。

例如：

```text
org.mnws.sample.HelloWorld
```

输出：

```json
{
  "text": "Hello MNWS"
}
```

第三方作者应该能在 5 分钟内看懂。

---

# 22. v1.0 明确不做

以下全部推迟：

```text
desktop.widget-v1
service-v1
KDE Plasmoid compatibility
capability permission enforcement
sandbox
bubblewrap
plugin signature
publisher verification
automatic update
plugin repository
complex IPC
Unix socket
D-Bus plugin runtime
migration framework
menu provider
MUI-specific API
```

这些都不要阻塞 Plugin API v1.0。

---

# 23. v1.0 最终结构

```text
                   MNWS
                     │
               Plugin Manager
                     │
                   .mplg
                     │
              ┌──────┴──────┐
              │             │
       panel.text-v1   panel.rows-v1
              │             │
              └──────┬──────┘
                     │
               MNWS Renderer
                     │
                  Waybar
```

---

# 24. v1.0 实现优先级

## P0

```text
plugin.json schema
API version
panel.text-v1
panel.rows-v1
build
validate
install
remove
```

## P1

```text
settingsSchema
i18n
plugin cache/materialize
错误隔离
```

## P2

```text
inspect
更好的日志
开发者模式
文档
HelloWorld sample
NCMLyricsBar reference plugin
```

---

# 25. v1.0 完成定义

满足以下条件即可宣布：

> MNWS Plugin API v1.0

```text
✓ 第三方可以自己写 plugin.json
✓ 可以 build 成 .mplg
✓ MNWS 可以安装并扫描
✓ 可以放入任务栏
✓ 支持 text/rows 两种 renderer
✓ 可以声明设置
✓ 中文/英文可正常显示
✓ 插件出错不会拖垮 MNWS
✓ 不需要修改 MNWS Core 才能添加新插件
```

最后一条最重要：

> **一个新插件如果只使用公开 v1.0 API，就不应该需要修改 MNWS Core。**

只要这一点成立，v1.0 就成功了。

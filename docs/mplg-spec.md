# ADWS Plugin API v1.0

ADWS 1.25 的任务栏插件接口。公开格式只支持 Python 任务栏插件；
桌面 Widget、Service、Plasmoid、签名、沙箱、插件市场及自动更新不属于 v1.0。
`.mplg` 是 ZIP，第三方使用下列接口即可接入，无需修改 ADWS Core。

## 包结构与清单

```text
MyPlugin/
├── plugin.json
├── main.py
├── locale/          # 可选；插件自己的词典
│   ├── zh.json
│   └── en.json
└── README.md
```

```json
{
  "id": "org.example.HelloWorld",
  "name": "plugin.name",
  "version": "1.0.0",
  "entry": "main.py",
  "renderer": "panel.text-v1",
  "adws": {"api": 1, "minVersion": "1.25"},
  "defaults": {"slot": "right", "width": 0, "interval": 5, "align": 0.5},
  "settingsSchema": [
    {"key": "greeting", "label": "settings.greeting", "type": "string", "default": "Hello ADWS"},
    {"key": "enabled", "label": "settings.enabled", "type": "boolean", "default": true}
  ]
}
```

必需：`id`、`name`、`version`、`entry`、`renderer`。可选：`description`、`adws`、
`defaults`、`settingsSchema` 及作者/许可证等说明。

- ID 至少两个以点分隔的非空段，允许 ASCII 字母、数字、下划线，区分大小写。
  安装后以 ID 标识配置，不随显示名变化。
- 插件版本采用 `主.次.修订`，可有预发布/构建后缀；多个已安装版本选择最高版本。
- `entry` 为包内文件，禁止绝对路径、反斜杠、冒号、`.`、`..` 路径段与符号链接。
- 不带阶段后缀的 minVersion（如 1.25）表示最低兼容版本系列，包括该系列预发布；显式 Release 则要求正式阶段。
- 省略 `adws` 等价于 `{"api":1,"minVersion":"1.25"}`；不支持的 API 或宿主版本过低会拒绝加载。
- `slot` 为 left/center/right；width 为非负宽度，0 表示自动（rows 默认 420）；
  align 为 0–1；interval 为非负秒数。text 的正间隔由 Waybar 定期执行，最小 0.5 秒。
  interval=0 可用于长驻逐行输出；rows 使用长驻流，结束后宿主重试。

## 输出与生命周期

新格式入口接收 `--settings-json '<JSON>'`，不会被追加旧的 `--output-json` 参数。
工作目录为解包根目录。程序应使用 UTF-8，并将每条 JSON 独占一行、及时 flush。
stdout 只能输出协议数据，stderr 用于日志；0 代表成功，非零代表失败。

`panel.text-v1`：

```json
{"text":"Hello ADWS","tooltip":"Example"}
```

`panel.rows-v1`：

```json
{"primary":"僕らが見た光","secondary":"我们曾看见的光","tooltip":"Lyrics"}
```

text 必须有字符串 `text`；rows 必须有字符串 `primary`，`secondary` 可省略。
可选 tooltip、alt 为字符串。rows 使用纯文本；text 继承 Waybar 的 Pango 标记支持，
显示不可信文字前应转义。`class` 遵循 Waybar 的类名约定。

长驻插件至少每 30 秒输出一条有效记录，即使数据未变化也应发送心跳。
单行输出最多 1 MiB。无效 JSON、无输出、超时和异常退出会记录带插件 ID 前缀的错误，
输出失败占位；不会把异常传播到其他插件。禁用并应用布局会停止对应运行组件。
插件以当前用户权限运行；v1.0 不提供沙箱或权限隔离。

## 设置

支持 string、number、boolean、choice、color、font、url。
设置键唯一，label/hint 可使用翻译键，default 是对应类型的 JSON 值。
number 支持 min/max/step，默认范围 0–100、步长 1，保留小数；boolean 使用真正的 JSON 布尔值。
choice 的 `choices` 为 `[["stored-value","label.key"], ...]`，值唯一，default 必须在列表内。
缺失 default 时，字符串为空、boolean 为 false、number 为 min、choice 为首选项。

宿主合并 schema 默认值与用户 settings，再传给插件。用户设置保存在
`taskbar-layout.json`，不会写回 `.mplg`；未知私有设置键会保留。
rows 的 font_family、primary_color、secondary_color、separator_color 为宿主渲染设置，
空值使用系统主题；原文与译文大小保持 3:2，颜色分别使用前景与强调色，分隔线使用主题混色。

## 插件语言文件

`locale/zh.json` / `locale/en.json` 是字符串字典，例如：

```json
{"plugin.name":"HelloWorld 示例","settings.greeting":"问候语","settings.enabled":"显示问候"}
```

中文环境读取 zh，其他读取 en；缺文件或缺键直接显示原键。
宿主翻译 name、description、设置 label/hint 和 choice 标签，不翻译设置值。
插件输出文本由插件自行本地化。包内语言文件与 ADWS 根目录 `language/` 相互独立；
宿主的加权 `_messages` 不是此版本插件词典的格式。

## 命令与路径

```sh
adws mplg init MyPlugin --id org.example.HelloWorld
adws mplg build MyPlugin
adws mplg validate org.example.HelloWorld_1.0.0.mplg
adws mplg install org.example.HelloWorld_1.0.0.mplg
adws mplg list
adws mplg inspect org.example.HelloWorld_1.0.0.mplg
adws mplg run org.example.HelloWorld --settings-json '{"enabled":true}'
adws mplg remove org.example.HelloWorld
```

安装目录：`$XDG_DATA_HOME/adws/plugins/`（默认 `~/.local/share/adws/plugins/`）；
缓存目录：`$XDG_CACHE_HOME/adws/plugins/<id>/<version>/`。
可通过 ADWS_PLUGIN_DIR / ADWS_CACHE_DIR 覆盖。包先校验后解包，
重复 ZIP 成员、越界路径、缺入口、非法语言文件、无效 schema 等会被拒绝。
缓存使用包 SHA-256 和解包锁；删除缓存不影响安装包与设置。

`remove <id>` 删除该 ID 的所有已安装版本；兼容旧的文件名删除方式，
但不接受任意目录路径。正在显示的组件应在布局设置中禁用并应用，
删除包后再次应用布局以卸载当前显示；布局里的设置保留便于重装。

## 旧包与参考插件

旧清单的 api/apiVersion/kind/language/interfaces 继续校验并兼容，
`panel.json-v1` 对应新版文本 renderer；旧 Python 入口仍收到 `--output-json`。旧协议只要求首条数据在超时前到达；
收到有效数据后允许长期静默，不强制旧插件实现新协议的心跳。
新插件应使用本文的简化格式，避免混用两种声明。

参考插件：`org.AkiACG_Community.NCMLyricsBar`，版本 1.0.2。
旧 ID `org.adws.neteaselyrics` 在加载布局和扫描包时映射为新 ID，
保留启用状态、分区、顺序和 settings；同时存在时只选一个版本，不重复显示。
[HelloWorld](../plugins/sample/) 是最小示例，歌词插件是完整参考实现。

## English quick reference

Plugin API 1 supports Python panel plugins packaged as ZIP `.mplg` archives.
Required manifest fields are id, name, version, entry and renderer. Renderers are
`panel.text-v1` (text) and `panel.rows-v1` (primary/secondary). Omitted `adws`
means API 1 and minimum ADWS 1.25. IDs are case-sensitive dotted ASCII segments
with letters, digits and underscores.

The host passes `--settings-json`, starts the entry in the extracted package root,
and validates UTF-8 JSON lines on stdout. Logs go to stderr. Emit at least once
per 30 seconds while streaming; each line is limited to 1 MiB. Settings and user
layout remain outside the archive. Plugins run with the user's permissions.

Package dictionaries in `locale/zh.json` and `locale/en.json` translate manifest
and schema labels; missing keys remain literal. The application `language/`
catalogue is separate. Use `plugins/sample` as the minimal runnable example.
Old manifests remain supported through a compatibility adapter.

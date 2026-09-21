# ADWS 语言文件制作指南 / Translation guide

语言文件放在项目根目录的 `language/` 文件夹中。使用 **UTF-8 编码的 JSON**，
不要添加注释或尾随逗号。修改后重新打开程序，已经打开的窗口不会自动刷新翻译。

## 1.25 支持范围

- 中文显示环境使用中文，其他显示语言统一使用英文。
- `language/en.json` 保存 Python 桌面、设置和命令行的普通英文翻译及命名文案。
- `language/zh.json` 保存中文命名文案；普通中文直接使用代码中的原文。
- 目前**不会自动发现或加载其他语言文件**。例如添加 `ja.json` 可以提交日语翻译，
  但不会直接使整个程序变成日语；还需要开发者接入对应语言。
- Shell 安装提示、Rust/C 原生组件及独立歌词插件目前有各自的中英文实现，
  尚未全部由 JSON 文件控制。修改 JSON 不会改变这些部分。

## 制作文件

维护英文时直接编辑 `language/en.json`。制作其他语言时，以它作为完整模板：

```sh
cp language/en.json language/ja.json
```

建议用语言代码命名，如 `ja.json`、`de.json`；需要地区区分时可使用
`pt_BR.json`。这些是贡献文件的命名约定，当前不代表自动加载支持。
翻译时保留所有键名，只修改对应的字符串值。

### 普通文本

键是程序传入的中文原文，值是目标语言翻译。例如英文文件：

```json
{
  "检查更新": "Check for updates",
  "发现新版本：%s": "New version available: %s"
}
```

不要翻译键名，也不要修改 `%s`、`%d`、`{id}`、`{title}` 等占位符的拼写或数量。
保留命令选项、路径、配置标记和 URL；不要翻译用户的文件名、歌曲名或自定义标签。
字符串中的换行写作 `\n`，引号写作 `\"`。
如果原文是一个片段，应保留拼接所需的空格和标点。

普通翻译由 `tr(原文)` 使用。当前英文缺项会回退到中文原文，
因此提交完整翻译时应检查是否漏项。不要在 `zh.json` 增加普通键并期待它覆盖原文。

### 命名文案与概率彩蛋

可复用文案放在特殊键 `_messages` 下。普通命名文案是字符串，
概率文案是包含 `weight` 和 `text` 的数组。例如中文文件：

```json
{
  "_messages": {
    "example.saved": "保存完成。",
    "updates.none": [
      {"weight": 80, "text": "未检测到更新。"},
      {"weight": 20, "text": "您是最新的！"}
    ]
  }
}
```

`example.saved` 仅为示例，新键需要在界面代码中调用才会显示。
同一命名键应在中英文文件中同时提供；当前缺失命名键会报错，不会自动回退。

- 每条记录必须包含字符串 `text` 和有限、严格大于零的数字 `weight`。
- 概率为该条权重除以所有权重之和；80/20 和 4/1 都表示 80%/20%。
- 权重不必合计为 100，但数组不能为空，也不能使用零、负数、布尔值或无穷大。
- 每种语言可以使用不同的措辞与权重，程序中不需要写死百分比。
- 每次调用独立抽取；不保证连续十次恰好出现八次和两次。

工具和设置代码调用：

```python
from adws_i18n import message

text = message("updates.none")
```

桌面代码则从 `desktop_layer.i18n` 导入同名函数。需要稳定显示的提示应只抽取一次，
保存返回值；不要在每帧绘制时重新抽取。

## 检查与预览

在项目根目录运行：

```sh
python3 -m json.tool language/en.json >/dev/null
python3 -m json.tool language/zh.json >/dev/null
python3 -m unittest discover -s tests -p 'test_i18n.py'
python3 -m unittest discover -s tests -p 'test_update.py'
```

对新增文件也运行 `json.tool`。JSON 语法通过不代表占位符、翻译完整度和排版全部正确；
还需要检查长文本、按钮、弹窗及概率文案。

```sh
LC_ALL=zh_CN.UTF-8 LANGUAGE=zh_CN ./adws -h
LC_ALL=en_US.UTF-8 LANGUAGE=en ./adws -h
LC_ALL=en_US.UTF-8 LANGUAGE=en ./adws config
```

系统需有对应 locale。显示语言取 `LC_ALL`、`LC_MESSAGES`、`LANG` 中第一个非空值；
除 C/POSIX 环境外，`LANGUAGE` 的第一项可覆盖消息语言。当前非中文仍回退英文。

## 新语言接入清单

插件作者请阅读 [Plugin API v1.0](docs/mplg-spec.md)。插件语言文件位于包内
`locale/`，与宿主的 `language/` 分开；支持中英文名称与设置标签的命名键翻译。

1. 将翻译文件放入 `language/`，保留原有键及占位符，翻译 `_messages`。
2. 扩展 `src/niri-desktop-layer/desktop_layer/i18n.py` 的语言选择与文件加载，
   定义缺项的英文回退，并调整 `prepare_gtk_language()`，避免 GTK 强制使用英文。
3. 同步处理 `scripts/adws-i18n.sh`、`src/niri-taskbar/src/i18n.rs`、
   `src/adws-i18n.h` 和独立插件中的语言选择及文本。
4. 增加该语言的回归测试，检查安装、CLI、桌面、设置和原生菜单的实际显示。

## English

Store UTF-8 JSON translation files in the root `language/` directory.
Copy `language/en.json` as a template, keep the Chinese source keys unchanged,
and translate their values. Preserve placeholders, commands, paths and URLs.
Restart the application after editing; open windows do not reload translations.

ADWS 1.25 currently selects Chinese for Chinese locales and English for everything
else. **Adding another JSON file does not enable that language automatically.**
Other languages require loader, GTK language selection and native/shell/plugin
integration changes. Ordinary Chinese text comes directly from source code;
`zh.json` currently supplies named messages only.

Under `_messages`, use either a string or an array of `{ "weight": 80, "text": "…" }`
objects. Weights must be finite positive numbers. Each probability is its weight
divided by the total; languages can define different weights. Call `message(key)`
from `adws_i18n` or `desktop_layer.i18n` once per displayed message. Define each
named key in both supported languages: missing named keys currently raise an error.

Run the JSON syntax checks and language/update tests above. Validate placeholders,
translation coverage and actual layouts separately. Shell prompts, Rust/C menus
and the standalone lyrics plugin are not yet fully controlled by these JSON files.

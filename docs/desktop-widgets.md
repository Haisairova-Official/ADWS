# 桌面小组件（开发版）

桌面右键选择“桌面小组件…”，或进入 **设置 → 桌面插件配置**。可添加时钟、日历、便签，以及模组包明确提供的桌面组件。拖动标题移动，拖动右下角调整大小；组件菜单支持锁定、设置、重新启动和移除。

桌面和任务栏是独立宿主，拥有不同组件声明、布局和实例设置；共享模组包的安装目录和更新版本。旧任务栏插件不会自动出现在桌面组件列表。桌面布局保存在 `~/.config/adws/desktop-widgets.json`，支持全局配置导入／导出；位置通过拖动调整，内部保存两个 −100%～+100% 的相对参数；(0%, 0%) 为组件居中，负值向左／上，正值向右／下，端点表示贴边。界面不提供坐标输入框。尺寸仍使用逻辑像素，屏幕尺寸变化时自动换算位置。旧像素坐标在对应屏幕尺寸稳定后自动转换，并保留 `desktop-widgets.json.pixels-backup`。临时移除显示器或缩小分辨率不会覆盖原有坐标。隐藏桌面或进入全览会隐藏组件并暂停其计时器／插件进程。

插件在独立进程中运行，使用现有 Rust 运行器和 Watchdog，故障不会在桌面进程中执行；组件显示错误状态，设置中标黄。移除或退出时会停止运行器并回收资源。右键组件标题旁的菜单可重新启动。便签在输入停顿后自动保存，并在失焦、隐藏或正常退出时保存；每张便签最多 20000 字符。

## 网易云歌词测试包

NCMLyricsBar **1.2.0** 在同一 `.mplg` 中保留原任务栏歌词，并新增独立桌面歌词。桌面端支持双语显示、播放／暂停、上一首／下一首，以及独立的歌词来源和同步偏移设置。两类实例不会互相覆盖设置，共用原有歌词缓存和获取锁。

```sh
adws mplg install ./org.AkiACG_Community.NCMLyricsBar_1.2.0.mplg
adws config --tab desktop-widgets
```

桌面宿主功能需要本次开发版 ADWS；旧版可继续使用包内原任务栏组件。

## 同一包提供两类组件

保留原有 `entry` / `renderer` 即保留旧任务栏组件；新增 `components` 可声明独立组件。也可以不提供顶层入口，全部在数组中声明。

```json
{
  "id": "org.example.DualLyrics",
  "name": "Dual Lyrics",
  "version": "1.0.0",
  "components": [
    {"id": "bar", "target": "taskbar", "name": "任务栏歌词", "entry": "bar.py", "renderer": "panel.rows-v1"},
    {"id": "desktop", "target": "desktop", "name": "桌面歌词", "entry": "desktop.py", "renderer": "panel.rows-v1", "isSingleOnly": true}
  ]
}
```

每个局部 `id` 在包内唯一，仅包含字母、数字和下划线，以字母开头。设置、控制接口等字段可从包级继承，组件级声明覆盖它们。包 ID 和版本保持统一。`isSingleOnly` 作用于该组件，不会因桌面实例而禁用另一个任务栏组件。两个入口可以共享实现文件，但声明和实例独立。

文本类桌面插件渲染器支持现有 JSON 文本／双行协议，使用纯文本显示，字体和空白颜色跟随桌面主题；媒体控制支持现有 `previous`、`play-pause`、`next`。不在桌面进程中加载第三方 GTK/Python UI 代码。包中每一个入口均参与路径、存在性与设置格式校验。

```sh
adws mplg run ./dual.mplg --component desktop
```

## 设置入口、重复实例与 CSS

- **插件管理**：安装／更新本地 `.mplg` 包、查看版本及支持的宿主、确认后卸载。卸载保留两类组件的布局与设置。
- **任务栏插件配置**：只负责任务栏实例、排列与组件设置。
- **桌面插件配置**：只负责桌面实例、位置、尺寸、显示器、组件设置和 CSS。

时钟、日历、便签和网易云桌面歌词均支持重复添加，也可点击“复制组件”复制现有实例。副本有独立 ID、位置、设置和 CSS；修改一个副本不会影响其他实例。明确声明 `isSingleOnly: true` 的其他插件仍遵守单例约束。

在桌面组件菜单或桌面插件配置中选择“自定义 CSS”。使用 GTK 3 CSS，保存前校验语法；清空即恢复默认主题。CSS 随实例保存并包含在配置备份中，只作用于当前卡片，不能修改其他卡片或任务栏。支持卡片 `.adws-desktop-card`、主文字 `.desktop-primary`、副文字 `.desktop-secondary`、时钟 `.desktop-clock` 以及卡片内部的 `button` 等选择器。例如：

```css
.adws-desktop-card { background-color: rgba(35, 38, 52, 0.9); border-radius: 20px; }
.desktop-primary { color: #ffffff; font-size: 26px; }
.desktop-secondary { color: #c0c8ef; }
```

网易云桌面歌词使用透明歌词与悬停工具栏，可单独开关翻译、罗马音、上下句，并设置字号、对齐。新增 CSS 类：`.desktop-lyrics`、`.desktop-context`、`.desktop-romanization`、`.desktop-toolbar`。

网易云桌面歌词可开启「日语汉字注音」：假名显示在对应汉字词组上方，依据歌曲源罗马音进行唯一对齐；不确定时保留原文。注音样式使用 `.desktop-furigana`，不影响独立的整行罗马音和翻译开关。


## desktopBasicPack 与交互协议（开发版）

新增 `org.AkiACG-Community.desktopBasicPack` **1.0.0**，包含六个可重复部署的桌面组件：时钟、计时器、2048、16 格图片拼图、图片展示框、便签贴。见[使用说明](../plugins/desktop-basic-pack/README.md)。安装只把组件加入可用列表，不自动占用桌面。

新渲染器 `desktop.widgets-v1` 仅允许桌面目标，继续经独立运行器与 Watchdog 校验、转发 JSON。包 ID 支持点分段内连字符，保留大小写和旧下划线 ID。可选 `desktopSize: [宽, 高]` 决定新实例默认尺寸；最终由桌面模型限制尺寸范围。

输出保留字符串 `text`，新增 `view` 声明式树：每个节点有唯一 `id` 和 `type`，支持 `column`、`row`、`grid`、`label`、`button`、`text`、`file`、`image`、`progress`、`clockface`。嵌套最多 8 层、160 节点，显示文字最多 4096 字符，便签输入最多 20000 字符。`classes` 只接受 CSS 类名，文本不解析 HTML/Pango 标记；节点不能执行任意命令或导入 Python。

按钮/输入节点携带 `action`，控件通过宿主提供的 `ADWS_DESKTOP_EVENT_SOCKET` 接收 UTF-8 JSON 数据报 `{"action":"...","value":...}`。该路径位于每次运行独立的 0700 临时目录，事件限长 128 KiB，发送不阻塞 GTK，停止后回收目录。包负责在独立进程监听 Unix 数据报套接字、保存状态、输出新界面，并按原接口维持心跳。`file` 节点由宿主弹出本地图片选择器，将用户选定路径作为事件值。

`key_actions` 可绑定方向键等按键，仅在当前卡片聚焦时响应。`alert: {"id":"...","text":"..."}` 可发出一次桌面通知；宿主回送 `alert_seen`，包应持久记录，避免重启重复提醒。不可见或移除组件仍遵守原有停止/恢复生命周期。图片在后台加载并有界缓存；CSS 和用户输入控件沿用 ADWS 原生 GTK 组件。

`clockface` 节点必须指定 `face`（`retro`／`minimal`／`railway`／`orbit`）、布尔 `seconds` 和整数 `utc_offset`（−86400 至 86400 秒）。宿主使用系统时钟并应用偏移，后台更新时区／夏令时；不通过插件进程发送逐帧画面。钟面由宿主缓存绘制，并在隐藏或停止组件时释放动画回调。

`clockface` 可选 `path` 指定本地图片，使用同一后台图片缓存；可选布尔 `markers`（默认 `true`）控制刻度与数字。自定义图片替代内置底色，圆形裁切时保留 Alpha；读取失败回退内置钟面。

显示范围可选择“仅限本屏幕”“仅限主屏幕”“所有屏幕的相同位置”。非主屏幕的组件菜单中“仅限主屏幕”置灰。所有屏幕共享同一个组件实例和相对坐标，插件仅启动一份，各屏幕独立显示最新状态；隐藏或移除最后一个视图时才停止进程。

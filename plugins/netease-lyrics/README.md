# NCMLyricsBar 1.2.0

ADWS 任务栏／桌面同步歌词模组 · Plugin API v1.0

**声明：本插件存在使用 vibe coding 的内容。本项目仍处于早期状态。**

## 最新更新

**1.2.0　2026-10-23（配合 ADWS 桌面组件开发版）**

- 一个模组包分别提供原任务栏歌词和新的桌面歌词，两者独立添加、设置和运行。
- 桌面歌词支持自由拖动、缩放、锁定，双语显示与上一首／暂停／下一首控制，沿用原歌词缓存和 Watchdog。
- 旧版任务栏入口及设置保持兼容，不会自动把任务栏实例搬到桌面。
- 添加入口：设置 → 桌面小组件。完整宿主说明见 `docs/desktop-widgets.md`。

**1.1.0　构建日期：2026-09-20**

· 支持 Google Chrome、Chromium、Brave、Microsoft Edge 等公开标准 MPRIS 媒体信息的浏览器，不再只识别 Firefox。
· 新增“实验性：兼容其他音乐平台”，默认关闭。读取其他音乐平台的曲目信息，再通过当前歌词源匹配歌词；不对 QQ 系平台做特殊优化。
· 右键歌词直接打开插件设置，移除了歌词本体的悬浮说明。
· 左键点击歌词暂停或继续播放，鼠标移入时在两侧显示上一首、下一首符号按钮。
· 宽度设置为 0 时开启动态占位，随歌词长度与两侧按钮占位变化。
· 增加可选的按钮淡入淡出与贝塞尔宽度过渡，默认关闭。
· 修复了按钮出现时任务栏卡死、右侧多余空档及移出后按钮不消失的问题。
· 优化系统配色刷新，原文、译文与分隔线使用有区分度的颜色。
· 支持竖向任务栏：中文竖排保持正向，英文旋转 90 度。
· 保留 1.0.2 的暂停心跳与静默重连，后台重连时保留歌词，不显示重连提示。

**1.1.0 配色修订　2026-10-05**

· 上一首、下一首按钮默认透明，文字与任务栏前景色一致；悬停和按下背景跟随任务栏系统配色，换配色即时更新。
· 此修订需要更新 ADWS 的原生歌词渲染组件，单独替换插件包不会更新宿主按钮样式。

## 安装

建议配合 **ADWS 1.27-A / Pre-1.30** 使用，获得本页全部交互、配色、竖排和动效。插件 API 最低声明为 ADWS 1.25，但仅升级插件包不会升级宿主的原生渲染组件。

下载 `org.AkiACG_Community.NCMLyricsBar_1.2.0.mplg` 后执行：

```sh
adws mplg install ./org.AkiACG_Community.NCMLyricsBar_1.2.0.mplg
```

在“组件与插件”中启用 NCMLyricsBar。插件 ID 保持为 `org.AkiACG_Community.NCMLyricsBar`，升级时保留已有设置。

依赖 Python 3、PyGObject/Gio，以及向 Linux 会话公开标准 MPRIS 曲目信息和播放位置的播放器。打开浏览器中的网易云音乐并播放即可；默认模式要求媒体 URL 来自 `music.163.com`。不同浏览器、平台是否提供完整信息会影响可用性。

## 设置与使用

- 双语歌词居中显示，原文与译文字号比为 3:2，中间为细分隔线，按任务栏实时高度计算字号。
- 默认宽度为 420；设置为 0 开启自适应占位。固定宽度下过长歌词截断。
- 右键歌词进入设置，可修改字体、三种颜色、同步偏移及歌词来源。字体和颜色可以跟随主题。
- 在宿主设置中开启“启用动画（淡入淡出与宽度过渡）”后，自适应宽度使用约 280 毫秒的过渡；系统关闭动画时直接切换。
- 上一首、下一首及暂停操作依赖播放器提供对应 MPRIS 控制能力。
- 歌词按曲目信息匹配，未匹配时显示歌名，没有时间轴时不伪造同步。

“实验性：兼容其他音乐平台”扩展曲目信息来源，包括 Spotify、YouTube Music、Apple Music、QQ 音乐、酷狗、酷我和 SoundCloud 等已识别平台；不保证每个平台都能匹配歌词。歌词仍由网易云或自定义 API 提供，不读取账号、Cookie 或浏览器登录信息。

自定义 API 使用 GET 地址模板，支持 `{id}`、`{title}`、`{artist}`、`{album}`、`{duration}`，参数自动 URL 编码。只有模板使用 `{id}` 时才先匹配网易云歌曲编号。接口可返回 UTF-8 LRC 文本或 JSON；JSON 字段路径支持点分路径和数组索引，例如 `lrc.lyric`、`tlyric.lyric`、`syncedLyrics`。无翻译时可留空译文字段。

缓存位于 `$XDG_CACHE_HOME/adws/netease-lyrics-v2`，未设置 XDG_CACHE_HOME 时使用 `~/.cache`。不同歌词来源分别缓存，双屏共用缓存和请求锁。

## 多实例（ADWS 1.31 B）

本插件未声明 `isSingleOnly`，因此允许在任务栏重复添加。每份歌词组件单独保存位置、宽度、颜色、歌词来源及动效设置，右键进入相应实例的设置；歌曲缓存和请求锁继续共享。移除某一份不会影响其他歌词组件。

插件开发者可在 `plugin.json` 顶层声明 `"isSingleOnly": true` 限制单例，`false` 或省略则允许重复；只接受 JSON 布尔值。详情见 [Plugin API](../../docs/mplg-spec.md)。

## 构建与排查

在 ADWS 源码根目录执行：

```sh
./adws mplg build plugins/netease-lyrics
python3 -m unittest discover -s tests -p 'test_netease_lyrics.py'
python3 plugins/netease-lyrics/main.py --diagnose
```

插件使用持续运行模式（`interval: 0`），不要改为周期启动。公开歌词接口发生变化时可能需要更新适配。

---

# English

**Notice: This plugin contains work created with vibe coding. The project is still in its early stages.**

## What's new

**1.1.0 · Build date: 2026-09-20**

- Discover standard MPRIS sessions from Chrome, Chromium, Brave, Edge and other browsers, alongside Firefox.
- Add opt-in experimental support for metadata from other music platforms. Lyrics still come from the selected source; there are no QQ-specific workarounds.
- Right-click lyrics to open settings; remove the lyrics body's hover description.
- Click lyrics to pause/resume; hover to reveal previous/next symbols on either side.
- Set width to 0 for automatic sizing based on lyrics and playback controls.
- Add optional control fades and Bézier width transitions, disabled by default.
- Fix freezes when controls appear, excess trailing space and controls remaining visible after pointer exit.
- Refresh theme colors and distinguish original lyrics, translation and separator.
- Support vertical bars with upright CJK text and Latin text rotated 90 degrees.
- Retain 1.0.2 pause heartbeats and silent reconnection without replacing existing lyrics with a reconnect message.

## Installation and compatibility

Use **ADWS 1.27-A / Pre-1.30** for all documented rendering and interaction features. The manifest declares ADWS 1.25 as its API minimum; installing the plugin alone does not update the host's native renderer.

```sh
adws mplg install ./org.AkiACG_Community.NCMLyricsBar_1.1.0.mplg
```

Enable NCMLyricsBar in Components & Plugins. Its ID remains `org.AkiACG_Community.NCMLyricsBar`, preserving existing settings when upgrading.

Requires Python 3, PyGObject/Gio and a player exposing track metadata and playback position through MPRIS. Play NetEase Music in a supported browser; default mode requires a `music.163.com` media URL. Browser integration and available metadata determine compatibility.

## Settings

Bilingual lyrics use a 3:2 font-size ratio, centered lines and a separator, sized from the actual taskbar height. Default width is 420; use 0 for automatic sizing. Right-click to configure fonts, original/translation/separator colors, timing offset and lyrics source. Fonts and colors can follow the theme.

Enable the host's fade and width animation option for approximately 280 ms automatic-width transitions. System animation settings are respected. Playback buttons require the corresponding MPRIS capabilities.

Experimental platform support recognizes metadata from services including Spotify, YouTube Music, Apple Music, QQ Music, Kugou, Kuwo and SoundCloud. This does not guarantee lyric matches or change the lyrics source. Account credentials, cookies and browser login data are not accessed. Unmatched tracks show their title; unsynchronized lyrics are not given a fabricated timeline.

Custom GET API templates accept `{id}`, `{title}`, `{artist}`, `{album}` and `{duration}` with URL-encoded values. NetEase ID matching is required only when `{id}` is used. Responses may be UTF-8 LRC or JSON. Configure dotted JSON paths with optional array indices, such as `lrc.lyric`, `tlyric.lyric` or `syncedLyrics`; leave translation empty when unavailable.

Cache: `$XDG_CACHE_HOME/adws/netease-lyrics-v2` (normally under `~/.cache`). Sources have separate cache keys; multiple displays share cache and request locks.

Build, test and diagnose using the commands above from the ADWS source root. Keep `interval: 0` for continuous operation. Public lyrics APIs may require future compatibility updates.

## Multiple instances (ADWS 1.31 B)

This plugin omits `isSingleOnly`, allowing multiple taskbar instances. Placement, width, colors, lyric source and animations are configured separately; right-click opens the matching instance. Shared song caches and request locks remain shared. Removing one instance does not remove the others.

Plugin authors can set top-level `"isSingleOnly": true` for one active instance, or use `false`/omit it to allow repeated instances. Only JSON Booleans are accepted. See [Plugin API](../../docs/mplg-spec.md).

### 1.1.0 palette revision — 2026-10-05

Previous/Next controls use transparent idle backgrounds and follow the taskbar's foreground, hover and pressed palette, including live color changes. This revision requires the updated ADWS native rows renderer; replacing only the plugin archive does not update host button styling.

桌面歌词支持重复添加，每个实例的尺寸、位置、设置和自定义 GTK 3 CSS 独立保存。在“插件管理”安装包，在“桌面插件配置”添加或复制实例。

### 桌面歌词显示

默认以透明歌词显示，悬停显示拖动标题、上一首、播放／暂停、下一首、锁定与菜单；当前句突出，上下句弱化。菜单和组件设置都提供“显示翻译”“显示罗马音”“显示上下句”独立开关，按实例保存；默认开启翻译和上下句。可调当前句字号、左／中／右对齐，也可用实例 CSS 覆盖。

罗马音读取歌词源的 `rlyric.lyric`，自定义接口可设置字段路径；没有对应数据时隐藏，不自动生成音译。翻译和罗马音匹配当前句时间戳，避免缺行时残留上一句译文。开启罗马音时会补充更新旧缓存，但不会反复请求没有罗马音的歌曲。

媒体按钮绑定当前歌词对应的 MPRIS 播放器；播放／暂停图标随状态更新，不支持的操作灰显，调用失败或超时显示提示。

### 日语汉字注音

桌面歌词提供独立的「日语汉字注音」开关（默认关闭），将歌曲源提供的罗马音对齐到原歌词，用假名显示在汉字或连续汉字词组上方。不依赖在线翻译服务或额外词典；没有罗马音、存在多种对齐方式或不支持的拼写时保留原文。整行罗马音开关保持独立。只在含日语假名的歌曲歌词中启用匹配；连续汉字按词组注音，不推测逐字读法。计算结果使用有界缓存，同一句歌词不会随播放进度重复构建界面。

译文紧贴当前歌词下方，不加标识；上下句以更淡、更小的文字和较大的间距区分。CSS 可使用 `.desktop-ruby .desktop-primary` 调整原文、`.desktop-furigana` 调整注音、`.desktop-secondary` 调整译文。

### 备用罗马音来源

桌面歌词的「自动查找备用罗马音」默认开启；仅在用户启用整行罗马音或日语汉字注音、主源没有罗马音且歌词含日语时使用。后台通过 [LRCLIB 公共 API](https://lrclib.net/docs) 查询歌曲名、歌手和时长，不需要账户或付费密钥。原歌词与译文先显示，备用查找使用独立后台线程，不阻塞切歌后的主源请求。可以在组件设置中关闭在线补全。

只接受歌名、歌手、时长一致且多句读音能与原歌词对应的同步版本；不替换原歌词和译文，也不把无时间戳文本直接拼接到歌词中。成功结果共享原歌词缓存，查无结果缓存 6 小时，网络错误缓存 10 分钟；悬停注音或罗马音可以看到来源。备用库也可能缺少罗马音，此时保留原文，不保证每首歌都能补齐。

长原文会先缩小字号（通常不低于设定字号的 72%，且不低于 18px；原字号已更小时保持原值），到达下限后分成两行居中。注音与对应汉字词组一起缩放、换行。极端长句两行仍放不下时省略末尾，不无限缩小。兼容网易云的 `romalrc` 和 `rlyric` 两种罗马音字段，旧的空读音缓存会自动重新读取一次。

### 播放进度与条状频谱

桌面歌词新增「显示播放进度」与「显示条状频谱」独立开关，默认开启，也可在组件菜单快速切换。进度条显示当前时间与总时长，直接使用播放器进度，不叠加歌词偏移；播放器不提供进度时灰显。支持拖动进度条跳转；松手时仅发送一次定位请求，拖动期间不会被播放状态刷新拉回。播放器不支持跳转时灰显；拖动期间切歌会取消旧定位，防止误跳新歌曲。

频谱固定放在歌词下方的独立区域，组件高度不足时自动预留歌词空间，不覆盖上下句。频谱使用 CAVA 的真实系统播放输出，32 个柱条、最高约 30fps、平滑回落，颜色跟随 ADWS 主题；需要可选依赖 `cava`、`pactl` 与 PulseAudio / PipeWire-Pulse。只连接默认输出的 monitor，不采集麦克风，也不保存音频。多个桌面组件共享一个采样进程，暂停、隐藏或移除最后一个活动实例时停止采样；缺少依赖或音频输出不可用时显示静止基线并在悬停时提示。CSS 可使用 `.desktop-spectrum`、`.desktop-progress` 和 `.desktop-media`。

注音支持空格分隔的连续汉字词组：罗马音没有给出逐字边界时，以合并词组注音，不猜单字读法。

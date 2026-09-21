# NCMLyricsBar 1.1.0

ADWS 任务栏同步歌词插件 · Plugin API v1.0

**声明：本插件存在使用 vibe coding 的内容。本项目仍处于早期状态。**

## 最新更新

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

## 安装

建议配合 **ADWS 1.27-A / Pre-1.30** 使用，获得本页全部交互、配色、竖排和动效。插件 API 最低声明为 ADWS 1.25，但仅升级插件包不会升级宿主的原生渲染组件。

下载 `org.AkiACG_Community.NCMLyricsBar_1.1.0.mplg` 后执行：

```sh
adws mplg install ./org.AkiACG_Community.NCMLyricsBar_1.1.0.mplg
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

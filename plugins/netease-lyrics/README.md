# NCMLyricsBar 1.0.2 — Plugin API v1.0 Reference Plugin

ID: `org.AkiACG_Community.NCMLyricsBar`

1.0.2：暂停时持续发送心跳；配合新版宿主，兼容旧插件的静默暂停。
后台重连保留原歌词，不显示重连提示。该修复需要同步更新宿主执行器及原生 renderer。

1.0.2: keep sending heartbeats while paused. The updated host tolerates silent legacy
streams and preserves lyrics during background reconnection without a reconnect label.

跟随系统配色时，原文使用主题前景、译文使用有区分度的强调色，
分隔线使用主题混色。取消旧的所有文字直接继承同色的方法；
手动指定颜色仍然生效。此行为由 MNWS 1.25 的原生 rows renderer 提供，
仅更新插件包而不更新宿主动态库不会改变颜色。

Theme mode uses foreground for the original line, a distinct accent for the
translation, and a theme-derived separator. Manual colors remain supported.
This requires the updated MNWS 1.25 native renderer, not just the plugin archive.

# 网易云歌词

MNWS 任务栏插件，从 Firefox 的 MPRIS 媒体会话读取网易云音乐当前曲目和播放位置。
不读取浏览器登录信息，不修改播放队列，不需要 API Key 或浏览器扩展。

- 当前句随播放位置更新，暂停时保留该句，拖动进度后重新定位。
- 双语时上下两行居中，原文/译文字号比 3:2，按任务栏实时高度与所选字体度量计算，中间细线随高度缩放。
- 悬浮查看歌曲、歌手和对应翻译。
- 默认右侧预留 420px，过长歌词截断，完整文本保留在提示中。
- 歌词按歌名、歌手、专辑和时长匹配，避免误选伴奏、短版、翻唱；匹配失败时显示歌名。
- 只请求网易云公开搜索与歌词接口；没有时间轴时不伪造同步。
- 本地缓存位于 `$XDG_CACHE_HOME/mnws/netease-lyrics-v2`，双屏共用缓存和请求锁。

依赖：Python 3、PyGObject/Gio、支持 MPRIS 播放进度的 Firefox。
在 Firefox 的 `music.163.com` 播放歌曲后会自动连接。

## 构建及使用

在 MNWS 根目录运行 `./mnws mplg build plugins/netease-lyrics`，将 `.mplg` 放进
`~/.local/share/mnws/plugins/`，在“组件与插件”里启用“网易云歌词”。
双语渲染依赖 `src/panel-rows` 构建的 `libmnws_panel.so`，安装到 `~/.local/lib/waybar/`。
`interval: 0` 表示持续运行并只在内容变化时输出；不要设置为定时单次执行。

排查连接：`python3 main.py --diagnose`。
单次输出：`python3 main.py --once`。

测试：在 MNWS 根目录执行 `python3 -m unittest discover -s tests -p 'test_netease_lyrics.py'`。
使用了本机当前可用的网易云网页接口，接口变更时可能需要适配。

## 插件设置

在布局窗口中点击“网易云歌词”旁的“设置…”，可配置字体、原文/译文/分隔线颜色、同步偏移和歌词来源。
字体与颜色可分别选择“跟随主题”。保存并应用会保存设置并重启底部任务栏。

自定义 API 使用 GET 地址模板，支持 `{id}`、`{title}`、`{artist}`、`{album}`、`{duration}`，参数自动 URL 编码。
只有使用 `{id}` 时才先在网易云匹配歌曲编号；否则可以直接使用其他歌词服务。
接口可返回 UTF-8 LRC 文本，也可返回 JSON：在设置中指定原文、译文的点分字段路径（支持数组索引）。
例如 `lrc.lyric` / `tlyric.lyric` 或 `syncedLyrics`。无翻译时留空译文字段。
不同来源和字段配置使用不同缓存，切换来源不会误用旧缓存。

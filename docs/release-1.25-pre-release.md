# 1.25 Pre-release — 2026-09-14

## 最新更新

- 帮助新增版本、构建日期、更新摘要。（B）
- 防止隐藏图标后的右键失效；顺便新增终端入口与退出确认。我觉得是个好功能。（C）
- 统一组件启停、状态查询及六级日志。（D）
- 移除了Koha D
- 提升了超级牛力。（E）
- 优化了安装逻辑，修复了一箩筐的bug（1.21）
- 简化了install，并直接在程序中添加了uninstall选项。（F）
- 优化了安装逻辑，启动器我之前忘记配置了。我的错。（1.22）
- 优化了任务栏菜单。（G）
- 优化了命令行参数处理逻辑。（H）
- 添加了安装时默认自启询问。
- 语言支持完善，但是除了中文外其他系统语言默认使用英文。
- 新增检查更新，支持 --update / -u，国内优先使用 GitHub 代理。
- 您是最新的！
- 新增 Language.md，介绍语言文件与概率文案的制作方法。
- 修复了设置开关被拉成Super面筋开关的问题。
- 优化了部分发行版下的默认 include 配置兼容性。
- 定型 Plugin API v1.0，支持插件独立翻译、七类设置及运行错误隔离。
- 将网易云歌词Sample插件正式命名为 NCMLyricsBar，升级至 1.0.1，保留旧插件配置。
- 优化了歌词的系统配色，原文、译文和分隔线终于不用挤一个颜色了。
- 修复了上游 Niri 窗口数据兼容问题，补充事件容错和断线重连。
- 提供 Arch Linux x86_64 的预构建安装包，安装时不再需要现场编译 Rust 和 C。（1.25 Pre-release）

## Latest updates

- Add version, build date and update summaries to help. (B)
- Fix the context menu when icons are hidden; add a terminal entry and exit confirmation. I think it is a nice feature. (C)
- Unify component controls, status queries and six logging levels. (D)
- Remove Koha D.
- Increase Super Cow Powers. (E)
- Improve installation logic and fix a basketful of bugs. (1.21)
- Simplify install and add an uninstall option directly to the program. (F)
- Improve installation logic: I forgot to configure the launcher earlier. My mistake. (1.22)
- Improve the taskbar menu. (G)
- Improve command-line argument handling. (H)
- Add a default-yes autostart prompt during installation.
- Improve language support; all system languages other than Chinese default to English.
- Add update checks via --update / -u, preferring a GitHub proxy in mainland China.
- You're up to date!
- Add Language.md explaining translation files and weighted messages.
- Fix settings switches stretching into Super gluten-strip switches.
- Improve default include configuration compatibility on some distributions.
- Finalize Plugin API v1.0 with package translations, seven setting types and plugin error isolation.
- Officially rename the NetEase lyrics Sample plugin to NCMLyricsBar, upgrade to 1.0.1 and preserve existing settings.
- Improve system-theme lyrics colors: the original, translation and separator no longer have to share one color.
- Fix upstream Niri window-data compatibility, with event tolerance and reconnection.
- Provide a prebuilt Arch Linux x86_64 archive so installation no longer compiles Rust and C on the spot. (1.25 Pre-release)

## 验证范围 / Validation scope

预发布版本；Arch、Ubuntu 裸 Niri 环境仍待实机复测。
Pre-release: real-world verification on stock Niri under Arch and Ubuntu remains pending.

## NCMLyricsBar 1.0.2 补丁 / Patch

- 修复旧歌词插件暂停后被误判超时；后台重连保留歌词、译文与分隔线，不显示重连提示。
- Fix false timeouts in paused legacy plugins. Background reconnection preserves the displayed lyrics without a reconnect label.
- 需要同时更新宿主执行器、原生 renderer 和插件。/ Update the host runner, native renderer and plugin together.
- 新附件：`ADWS1.25_for_arch_lyrics1.0.2.zip`、对应 SHA-256 文件、`org.AkiACG_Community.NCMLyricsBar_1.0.2.mplg`。
- 原发布标签及其自动生成的 Source code 归档仍对应初版；补丁源码包含在新 Arch ZIP 内，也可从 main 获取。旧附件保留。
- The original release tag and automatic Source code archives remain the initial snapshot. Patch sources are included in the new Arch ZIP and available on main. Original assets are retained.

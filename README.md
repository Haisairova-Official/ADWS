> **声明：本 Repo 使用大量 vibe coding，可能不适合所有人。**
>
> **Notice: This repository makes extensive use of vibe coding and may not be suitable for everyone.**

# MNWS — My Niri Workspace Solution

**A simpler desktop solution for Niri.**

当前开发版本 / Current development version: **1.25 Pre-release** · [更新记录 / Changelog](CHANGELOG.md)

[中文](#中文) · [English](#english)

## 中文

MNWS 为 Niri 整合桌面图标、底部任务栏、统一设置与插件，让日常桌面操作更简单。
它仍在持续开发，当前主要在 Niri/Shorin 26.04 环境验证；尚未完成不同发行版与上游 Niri 的兼容性验证。

### 预发布补丁：NCMLyricsBar 1.0.2

修复暂停较久后歌词周期性断开的问题：旧插件只在内容变化时输出数据，
新版宿主不再把这种正常静默当作超时。后台重连时保留上一条歌词，
不显示“正在重新连接”，也不清空译文和分隔线。

**本补丁需要同时更新宿主与插件，单独替换 `.mplg` 不够。**
源码用户更新仓库后重新运行 `./install.sh`，并重新构建安装原生面板组件；
Arch 用户可使用预发布附件 `MNWS1.25_for_arch_lyrics1.0.2.zip`。
安装 `org.AkiACG_Community.NCMLyricsBar_1.0.2.mplg` 后，应用任务栏布局并重启任务栏。
已有设置保留；无需修改 Firefox 或歌词 API。

源码版在更新后的仓库目录执行（任务栏会短暂关闭）：

```sh
./mnws taskbar -S
make -C src/panel-rows
install -Dm644 src/panel-rows/libmnws_panel.so "$HOME/.local/lib/waybar/libmnws_panel.so"
./install.sh
./mnws mplg build plugins/netease-lyrics
./mnws mplg install plugins/org.AkiACG_Community.NCMLyricsBar_1.0.2.mplg
./mnws layout apply --restart
```

下载入口：[1.25 Pre-release 附件](https://github.com/Haisairova-Official/MNWS/releases/tag/v1.25-pre-release)。
原始 1.0.1 与初版 Arch 包保留供追溯，请选择带 1.0.2 标识的补丁包。

### 功能

- **桌面图标层**：桌面文件展示、选择、拖动排序、文件操作及外观设置。
- **底部任务栏**：窗口图标随内容增长，空间不足时滚动；支持右键菜单，桌面与任务栏可独立显示或隐藏。
- **布局设置**：内置组件与用户插件可混合排序、放入左/中/右分区；中间分区对齐整条任务栏中心。设置窗口以浮动形式打开。
- **插件系统**：Plugin API v1.0 通过 `.mplg` 包分发插件，支持插件自带设置；长名称自动省略，操作按钮保持可见。
- **网易云歌词**：读取 Firefox 的 MPRIS 媒体会话，同步当前歌词。双语上下居中，原文与译文字号比为 3:2，中间以细线分隔，字号根据任务栏实时高度计算。支持字体、颜色、同步偏移和自定义歌词 API。

### 环境要求

- Linux、Niri，以及支持 CFFI v2 的 Waybar。
- Python 3.11+、PyGObject（GTK 3/Gio）、PyCairo、Pillow、gtk-layer-shell；文件管理集成使用 Thunar。
- 仅源码构建需要：Rust 1.87+ / Cargo、C 编译器、Make、pkg-config，以及 GTK 3、gtk-layer-shell、json-glib 开发文件。
- 桌面启动器使用 systemd 用户服务；应用菜单优先使用 fuzzel，其次 rofi，也可自定义启动命令。
- 歌词插件需要 Firefox 启用 MPRIS 并正在播放 `music.163.com` 的音乐。

任务栏使用随仓库提供的 `vendor/niri-ipc`，兼容上游窗口数据与 Shorin 最小化扩展。
缺少最小化接口时回退到聚焦窗口。仍需支持 CFFI v2 的 Waybar；具体发行版的实机兼容性需要验证。

### 构建与安装

安装完成后会询问是否让桌面和任务栏随 Niri 自启（默认 Y）；选择 n 或 Ctrl+C 保留安装结果和原有自启设置。

源码安装：

```sh
git clone https://github.com/Haisairova-Official/MNWS.git
cd MNWS
./install.sh
mnws -s
```

按提示补齐依赖、构建组件和选择启动器即可。Arch x86_64 用户也可使用预构建包，
省去 Rust/Cargo 和 C 编译步骤，见 [Arch 安装说明](docs/arch-install.md)。

用 `./mnws config` 打开设置，`./mnws check` 排查安装问题。
安装保留已有配置，并更新应用菜单启动命令（原文件备份为 `.mnws-launcher.bak`）。优先使用 fuzzel，其次 rofi；都没有时按提示选择安装 fuzzel（默认 Y）、输入自定义启动命令（n），或 Ctrl+C 取消。缺少运行依赖或组件时，安装程序会询问是否补齐或构建（默认 Y，n/Ctrl+C 取消），完成后重新检查。自动补齐支持 apt、pacman、dnf；软件源缺包或版本不够时会提示手动处理。
保留仓库目录。安装程序优先在已有 PATH 的 `~/.local/bin` 建立命令链接，否则询问是否安装到 `/usr/local/bin`（可能需要 sudo）。不会修改终端配置或覆盖其他程序；卸载只移除属于 MNWS 的链接。

为兼容部分 Ubuntu 构建环境，安装和应用布局时会把单个默认 `modules.jsonc` 引用写为实际配置目录下的绝对路径字符串。已有配置转换前备份为 `.mnws-include-bak`；自定义引用和多文件 include 保留。

浮动窗口规则、登录自启及已有 Waybar 配置的接入方式见 [安装详情](docs/installation.md)。

### 语言与检查更新

中文显示环境使用中文，其他语言统一使用英文。执行 `mnws --update` / `mnws -u`，
或在设置的“关于”页点击“检查更新”。中国大陆出口 IP 优先使用 GitHub 代理，失败回退直连。
只检查正式 Release，不自动安装。概率文案和翻译维护见 [语言文件制作指南](Language.md)。

### 卸载

```sh
mnws --uninstall
```

默认取消卸载；确认后可选择保留配置（默认保留）。会停止组件并移除 MNWS 启动入口、可确认归属的动态库及自动生成的桌面自启项。
选择清理配置时，仅清理 MNWS 自有配置；共享 Waybar 配置、桌面文件、插件包和源码保留。手动添加的任务栏自启命令需自行移除。

### 使用与插件

```sh
./mnws check
./mnws config
./mnws layout show
./mnws layout render
./mnws layout apply --restart
./mnws mplg build plugins/netease-lyrics
./mnws mplg list
```

将打包命令生成的 `.mplg` 放到 `~/.local/share/mnws/plugins/`，在“组件与插件”中启用、调整位置并应用。
布局优先读取 `~/.config/mnws/taskbar-layout.json`，否则使用仓库默认配置。

网易云歌词默认不需要 API Key，也不读取浏览器登录信息。公开接口可能变化；匹配失败或没有同步歌词时，插件无法显示同步文本。
可在插件设置中指定自定义 GET API、LRC 文本或 JSON 字段路径。

详见 [歌词插件说明](plugins/netease-lyrics/README.md)、[插件规范](docs/mplg-spec.md) 与 [桌面图标层说明](src/niri-desktop-layer/README.md)。部分组件文档保留开发阶段说明，以本页的安装流程为准。

### 许可证

MNWS 原创代码采用 **GNU GPL v3.0 或更新版本（GPL-3.0-or-later）**。
第三方及独立许可组件保留原许可证与版权声明；请参阅 [LICENSE](LICENSE) 和 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## English

MNWS brings desktop icons, a bottom taskbar, unified settings and plugins to Niri, making everyday desktop interaction simpler.
It is under active development and has mainly been tested with Niri/Shorin 26.04. Compatibility across distributions and upstream Niri has not yet been verified.

### Pre-release patch: NCMLyricsBar 1.0.2

Fix periodic lyric interruptions after a long pause. Legacy plugins emit only
changed data; the host no longer treats their normal silence as a timeout.
Background reconnection preserves the last lyrics, translation and separator,
without displaying a reconnect message.

**Update both the host and the plugin; replacing only the `.mplg` is insufficient.**
Source users must update the checkout, rerun `./install.sh`, and rebuild/install
the native panel component. Arch users can use `MNWS1.25_for_arch_lyrics1.0.2.zip`.
Install `org.AkiACG_Community.NCMLyricsBar_1.0.2.mplg`, apply the layout and restart
the taskbar. Existing settings are preserved.
The source-upgrade commands in the Chinese patch section above perform these
steps explicitly, including rebuilding the native panel library.

Get the files from [1.25 Pre-release](https://github.com/Haisairova-Official/MNWS/releases/tag/v1.25-pre-release).
Original 1.0.1 assets remain available; choose the patch archive marked 1.0.2.

### Features

- **Desktop icons:** display desktop files, select items, rearrange icons, perform file actions and customize appearance.
- **Bottom taskbar:** window icons grow with their content and scroll when space runs out. Context menus and independent desktop/taskbar visibility are supported.
- **Layout settings:** mix built-in components and user plugins in a persistent order across left, center and right sections. The center section aligns with the whole taskbar. Settings open as floating windows.
- **Plugins:** distribute plugins as `.mplg` packages with their own settings. Long names are ellipsized while action buttons remain visible.
- **NetEase lyrics:** follow Firefox's MPRIS session and display synchronized lyrics. Bilingual lines are centered with a 3:2 original/translation font-size ratio and a thin separator. Font sizes follow the actual taskbar height. Font, colors, timing offset and a custom lyrics API are configurable.

### Requirements

- Linux, Niri and Waybar with CFFI v2 support.
- Python 3.11+, PyGObject (GTK 3/Gio), PyCairo, Pillow and gtk-layer-shell. File-manager integration uses Thunar.
- Source builds only: Rust 1.87+ / Cargo, a C compiler, Make, pkg-config and development files for GTK 3, gtk-layer-shell and json-glib.
- The desktop launcher uses a systemd user service. The application menu prefers fuzzel, then rofi, and supports a custom command.
- Lyrics require Firefox with MPRIS enabled and music playing on `music.163.com`.

The bundled IPC client accepts upstream window data and Shorin minimization extensions.
When minimization is unsupported, the action falls back to focusing the window.
Waybar still needs CFFI v2 support; real distribution compatibility requires verification.

### Build and install

```sh
git clone https://github.com/Haisairova-Official/MNWS.git
cd MNWS
./install.sh
mnws -s
```

Follow the prompts to install missing dependencies, build components and choose a launcher.
At the end, the installer offers Niri autostart for both components (default Y).
Arch x86_64 users can skip Rust/Cargo and C compilation with the prebuilt archive;
see the [Arch installation guide](docs/arch-install.md).

Use `./mnws config` for settings and `./mnws check` to diagnose installation problems.
The installer preserves existing settings and updates the app launcher command, backing up the original file as `.mnws-launcher.bak`. It prefers fuzzel, then rofi. If neither is available, choose to install fuzzel (default Y), enter a custom command (n), or cancel with Ctrl+C. Missing runtime dependencies and components trigger an offer to install or build them (default Y; n/Ctrl+C cancels), followed by another check. Automatic dependency installation supports apt, pacman and dnf; unavailable packages or outdated versions need manual attention.
Keep the checkout. The installer uses `~/.local/bin` if already on PATH, otherwise offering `/usr/local/bin` (sudo may be required). Shell configuration and unrelated commands are preserved; uninstall removes only MNWS-owned links.

For compatibility with reported Ubuntu builds, installation and layout generation write the single default `modules.jsonc` include as an absolute-path string in the configuration directory. Existing files are backed up as `.mnws-include-bak` before migration; custom references and multiple includes are preserved.

See [installation details](docs/installation.md#build-and-install) for floating-window rules, autostart and integration with an existing Waybar configuration.

### Language and updates

Chinese display locales use Chinese; all other locales use English. Run `mnws --update` /
`mnws -u`, or select **About → Check for updates** in settings. Mainland-China outbound
IPs prefer a GitHub proxy, with direct access as fallback. Checks report stable Releases
without installing them. See [translation and weighted-message guide](Language.md).

### Uninstall

Run `mnws --uninstall`. Uninstallation defaults to **No**; keeping configuration defaults to **Yes**.
It stops the components and removes MNWS launchers, identifiable libraries and its generated desktop autostart entry.
Choosing to discard configuration removes only MNWS-owned configuration. Shared Waybar files, desktop documents, plugin packages and source files remain. Remove manually configured taskbar autostart commands separately.

### Usage and plugins

Use `./mnws config` for settings, `./mnws check` for status and `./mnws layout apply --restart` to apply the layout.
Build the lyrics plugin with `./mnws mplg build plugins/netease-lyrics`.
Place the resulting `.mplg` file in `~/.local/share/mnws/plugins/`, then enable and position it in the components/plugins window and apply.
The layout is read from `~/.config/mnws/taskbar-layout.json` when present, otherwise from the repository default.

The default lyrics service needs no API key and does not read browser credentials.
Public endpoints can change, and synchronized text is unavailable when matching fails or timed lyrics are missing.
Plugin settings support a custom GET API returning LRC text or configurable JSON fields.

See the [lyrics plugin guide](plugins/netease-lyrics/README.md), [plugin specification](docs/mplg-spec.md) and [desktop icon guide](src/niri-desktop-layer/README.md).
These component guides are currently primarily in Chinese and may contain development-era notes; use this README for installation.

### License

Original MNWS code is licensed under **GNU GPL version 3 or any later version (GPL-3.0-or-later)**.
Third-party and separately licensed components retain their own licenses and copyright notices.
See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Development checks / 开发检查

```sh
python3 -m unittest discover -s tests -p 'test_netease_lyrics.py'
xvfb-run -a env GDK_BACKEND=x11 python3 tests/check_plugin_settings_gui.py
xvfb-run -a env GDK_BACKEND=x11 python3 tests/check_layout_order_gui.py
make -C src/panel-rows check
```

GUI checks require Xvfb. These checks do not replace testing in a real Niri session.

### Component commands / 组件命令

| Command / 命令 | Action / 操作 |
| --- | --- |
| `mnws desktop --start` / `mnws desktop -s` | Start desktop / 启动桌面 |
| `mnws desktop --stop` / `mnws desktop -S` | Stop desktop / 正常停止桌面 |
| `mnws desktop --kill` / `mnws desktop -k` | Force quit desktop / 强制结束桌面 |
| `mnws taskbar --start` / `mnws taskbar -s` | Start taskbar / 启动任务栏 |
| `mnws taskbar --stop` / `mnws taskbar -S` | Stop taskbar / 正常停止任务栏 |
| `mnws taskbar --kill` / `mnws taskbar -k` | Force quit taskbar / 强制结束任务栏 |

Stopping the desktop also disables its context menu. Start it again with `mnws desktop -s`.
停止桌面后，桌面右键菜单也会失效；可用 `mnws desktop -s` 恢复。

Debug either component in the current terminal with `mnws desktop -d` or `mnws taskbar -d` (`--debug`).
This gracefully stops the existing instance first. Ctrl+C stops the foreground instance; use `-s` to start it in the background again.
使用 `mnws desktop -d` 或 `mnws taskbar -d`（`--debug`）在当前终端启动并输出日志；已有实例会先正常停止。
按 Ctrl+C 结束调试后，可用 `-s` 恢复后台运行。

Use `mnws desktop --status` / `mnws taskbar --status` for status (exit code 0: running, 1: stopped),
and `mnws desktop -r` / `mnws taskbar -r` (`--restart`) to restart.
`--status` 查询状态（运行返回 0，未运行返回 1），`--restart/-r` 重启组件。`--help/-h` 查看命令帮助。

### Log levels / 日志级别

`mnws desktop --debug -4` / `mnws taskbar -d -6`

| Level / 级别 | Output / 输出 |
| --- | --- |
| `-1` | Critical / 致命错误 |
| `-2` | Error / 错误及以上 |
| `-3` | Warning / 警告及以上 |
| `-4` (default / 默认) | Info / 操作请求、菜单选择、弹窗响应与结果 |
| `-5` | Debug / 调试细节 |
| `-6` | Trace / 高频事件跟踪 |

The level flag requires `--debug/-d`. Lower numbers filter out routine operations.
日志数字参数必须与 `--debug/-d` 一起使用；较低级别会过滤普通操作日志。
A submitted launch request does not prove that the external application opened successfully.
日志中的“启动请求已提交”表示请求已发出，不代表外部应用已成功打开。

`mnws --status` shows both desktop and taskbar status. / 同时显示桌面和任务栏状态。

Configuration, visibility markers, plugin data and caches follow `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, `XDG_DATA_HOME` and `XDG_CACHE_HOME`, respectively. Existing `MNWS_PLUGIN_DIR` / `MNWS_CACHE_DIR` overrides take precedence.
配置、显隐标记、插件数据和缓存分别遵循上述 XDG 路径；已有 `MNWS_PLUGIN_DIR` / `MNWS_CACHE_DIR` 覆盖设置优先。

> **声明：本 Repo 使用大量 vibe coding，可能不适合所有人。**
>
> **Notice: This repository makes extensive use of vibe coding and may not be suitable for everyone.**

# MNWS — My Niri Workspace Solution

**A simpler desktop experience for Niri.**

当前版本 / Current version: **1.25 Released** · [更新记录 / Changelog](CHANGELOG.md)

[中文](#中文) · [English](#english)

## 中文

MNWS 为 Niri 提供桌面图标、底部任务栏、统一设置和插件系统，让日常桌面操作更接近一套完整而轻量的桌面体验。

1.25 已在 Arch Linux 与 Ubuntu 的 Niri 环境完成测试。MNWS 仍依赖 Niri、Waybar 和发行版提供的系统组件，不打算取代窗口管理器或 Linux 用户空间。

### 1.25 Released 最新更新

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
- 新增检查更新，支持 `--update` / `-u`，国内优先使用 GitHub 代理。
- 您是最新的！
- 新增 Language.md，介绍语言文件与概率文案的制作方法。
- 修复了设置开关被拉成Super面筋开关的问题。
- 优化了部分发行版下的默认 include 配置兼容性。
- 定型 Plugin API v1.0，支持插件独立翻译、七类设置及运行错误隔离。
- 将网易云歌词Sample插件正式命名为 NCMLyricsBar，升级至 1.0.1，保留旧插件配置。
- 优化了歌词的系统配色，原文、译文和分隔线终于不用挤一个颜色了。
- 修复了上游 Niri 窗口数据兼容问题，补充事件容错和断线重连。
- 提供 Arch Linux x86_64 的预构建安装包，安装时不再需要现场编译 Rust 和 C。（Pre-release）
- 修改了开始按钮的默认文字，提供了自定义icon功能。
- 优化了任务栏稳定性，优化了MNWS系列命令稳定性。
- 修复了特殊情况下任务栏变为英文的bug。（Released）

### 主要功能

- **桌面图标层**：显示、选择和排列桌面文件，提供文件操作、终端入口、简化菜单与安全退出确认。
- **底部任务栏**：显示 Niri 窗口、工作区、时钟和插件；窗口较多时自动滚动，支持任务栏右键菜单。
- **统一设置**：调整桌面、任务栏、组件顺序、左中右分区和插件设置；中间分区按整条任务栏真正居中。
- **开始按钮**：支持文字、发行版图标或自定义图片；默认图和悬停图可分别设置，并保留原有左键、右键和悬停提示逻辑。
- **启动器**：内置 fuzzel 与 rofi 预设，也可以填写自定义命令。rofi 预设沿用当前配色与毛玻璃效果。
- **Plugin API v1.0**：通过 `.mplg` 安装插件，支持插件翻译、七类设置、错误隔离和稳定的混合排序。
- **NCMLyricsBar 1.0.2**：读取 Firefox 的网易云音乐 MPRIS 会话；支持双语歌词、3:2 字号、分隔线、同步偏移、字体、颜色与自定义歌词 API。暂停和后台重连时保留当前显示。
- **中英文界面**：中文环境显示中文，其他系统语言统一使用英文；语言包和概率文案可以扩展。
- **命令行管理**：统一启停、状态、更新、卸载和六级日志；短参数与长参数都可使用。

### 环境要求

- Linux、Niri，以及支持 CFFI v2 的 Waybar。
- Python 3.11+、PyGObject（GTK 3/Gio）、PyCairo、Pillow、gtk-layer-shell；文件管理集成使用 Thunar。
- 源码构建需要 Rust 1.87+ / Cargo、C 编译器、Make、pkg-config，以及 GTK 3、gtk-layer-shell、json-glib 开发文件。
- 歌词插件需要 Firefox 启用 MPRIS，并正在播放 `music.163.com` 的音乐。

任务栏使用仓库内的 `vendor/niri-ipc`，兼容上游 Niri 窗口数据与 Shorin 最小化扩展；上游不提供最小化接口时会回退到聚焦窗口。

### 安装

源码安装适用于大多数发行版：

```sh
git clone https://github.com/Haisairova-Official/MNWS.git
cd MNWS
./install.sh
mnws -s
```

安装程序会检查依赖、构建缺失组件、选择启动器、安装 `mnws` 命令，并询问是否让桌面和任务栏随 Niri 自启。补齐依赖或修改现有配置前都会先询问；已有文件会保留或备份。

Arch Linux x86_64 用户可以使用 GitHub Release 中的 `MNWS1.25_for_arch.zip`。该包包含预构建原生组件，安装时无需 Rust、Cargo 或 C 编译器。详见 [Arch 安装说明](docs/arch-install.md)。

安装目录需要保留，因为命令入口会链接到其中的程序文件。若 `~/.local/bin` 尚未进入 PATH，安装程序会提供 `/usr/local/bin` 入口。

部分 Ubuntu 环境不接受数组形式的默认 Waybar `include`。MNWS 会把单个默认 `modules.jsonc` 引用转换为配置目录中的绝对路径字符串；转换前保存 `.mnws-include-bak`，自定义引用和多文件 include 不受影响。

更多细节见 [安装说明](docs/installation.md)。

### 使用

```sh
mnws -s                         # 启动桌面与任务栏
mnws --status                   # 查看两者状态
mnws config                     # 打开统一设置
mnws layout apply --restart     # 应用任务栏布局
mnws -u                         # 检查正式 Release 更新
mnws --uninstall                # 卸载
```

`desktop` 和 `taskbar` 可以单独管理，例如 `mnws taskbar -s`、`mnws desktop -S`。使用 `--debug/-d` 在当前终端运行并输出日志，`-1` 至 `-6` 控制日志级别，默认为 `-4`。

检查更新不会自动安装。中国大陆出口 IP 会优先尝试 GitHub 代理，失败后回退直连。

### 插件与 Sample

```sh
mnws mplg build plugins/netease-lyrics
mnws mplg install plugins/org.AkiACG_Community.NCMLyricsBar_1.0.2.mplg
mnws mplg list
```

插件安装后可在“组件与插件”中启用、排序并设置。布局保存在 `~/.config/mnws/taskbar-layout.json`，插件保存在 `~/.local/share/mnws/plugins/`。

仓库的 [samples](samples/) 包含可直接试用的示例资源，其中 [Popcat 开始按钮](samples/start-buttons/popcat/README.md) 默认闭嘴，鼠标移入时张嘴。两张图片尺寸一致，MNWS 会按任务栏高度等比显示。

详见 [歌词插件说明](plugins/netease-lyrics/README.md)、[Plugin API v1.0](docs/mplg-spec.md)、[语言文件指南](Language.md) 与 [桌面图标层说明](src/niri-desktop-layer/README.md)。

### 卸载

```sh
mnws --uninstall
```

卸载默认为取消，确认后可以选择保留配置（默认保留）。MNWS 只移除属于自己的命令入口、原生组件和自动生成的自启项；共享 Waybar 配置、桌面文件和源码目录不会被直接删除。

### 许可证

MNWS 原创代码采用 **GNU GPL v3.0 或更新版本（GPL-3.0-or-later）**。第三方组件与 Sample 保留各自的许可证、来源和版权声明，详见 [LICENSE](LICENSE) 与 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## English

MNWS adds desktop icons, a bottom taskbar, unified settings and a plugin system to Niri, providing a lightweight but complete everyday desktop experience.

Version 1.25 has been tested with Niri on Arch Linux and Ubuntu. MNWS still relies on Niri, Waybar and distribution-provided system components; it does not aim to replace the window manager or the Linux user space.

### 1.25 Released — latest updates

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
- Add update checks via `--update` / `-u`, preferring a GitHub proxy in mainland China.
- You're up to date!
- Add Language.md explaining translation files and weighted messages.
- Fix settings switches stretching into Super gluten-strip switches.
- Improve default include configuration compatibility on some distributions.
- Finalize Plugin API v1.0 with package translations, seven setting types and plugin error isolation.
- Officially rename the NetEase lyrics Sample plugin to NCMLyricsBar, upgrade to 1.0.1 and preserve existing settings.
- Improve system-theme lyrics colors: the original, translation and separator no longer have to share one color.
- Fix upstream Niri window-data compatibility, with event tolerance and reconnection.
- Provide a prebuilt Arch Linux x86_64 archive so installation no longer compiles Rust and C on the spot. (Pre-release)
- Change the default Start-button text and add custom icon support.
- Improve taskbar stability and the reliability of the MNWS command suite.
- Fix the taskbar unexpectedly switching to English under special circumstances. (Released)

### Highlights

- **Desktop icons:** display, select and arrange desktop files, with file operations, a terminal entry, a simplified hidden-icon menu and safe exit confirmation.
- **Bottom taskbar:** show Niri windows, workspaces, the clock and plugins. Window items scroll when space runs out, and the taskbar has a context menu.
- **Unified settings:** configure the desktop, taskbar, component order, left/center/right sections and plugin settings. The center section aligns with the geometric center of the whole bar.
- **Start button:** use text, a distribution logo or custom images. Separate default and hover images preserve the normal left-click, right-click and tooltip behavior.
- **Launchers:** built-in fuzzel and rofi presets, plus custom commands. The rofi preset keeps the current color scheme and blur styling.
- **Plugin API v1.0:** install `.mplg` packages with plugin translations, seven setting types, runtime error isolation and stable mixed ordering.
- **NCMLyricsBar 1.0.2:** follow Firefox's NetEase Music MPRIS session, with bilingual lyrics, a 3:2 font ratio, separator, timing offset, fonts, colors and custom API support. Pausing and background reconnection preserve the current display.
- **Chinese and English UI:** Chinese locales use Chinese; all other locales use English. Translation files and weighted UI messages are extensible.
- **Command-line management:** unified start, stop, status, update and uninstall commands, plus six logging levels.

### Requirements

- Linux, Niri and Waybar with CFFI v2 support.
- Python 3.11+, PyGObject (GTK 3/Gio), PyCairo, Pillow and gtk-layer-shell. File-manager integration uses Thunar.
- Source builds require Rust 1.87+ / Cargo, a C compiler, Make, pkg-config and development files for GTK 3, gtk-layer-shell and json-glib.
- Lyrics require Firefox with MPRIS enabled and music playing on `music.163.com`.

The bundled `vendor/niri-ipc` supports upstream Niri window data and Shorin minimization extensions. When minimization is unavailable, MNWS falls back to focusing the window.

### Install

Source installation works on most distributions:

```sh
git clone https://github.com/Haisairova-Official/MNWS.git
cd MNWS
./install.sh
mnws -s
```

The installer checks dependencies, builds missing components, selects a launcher, installs the `mnws` command and offers to start the desktop and taskbar with Niri. It asks before installing dependencies or changing existing configuration, and preserves or backs up existing files.

Arch Linux x86_64 users can download `MNWS1.25_for_arch.zip` from the GitHub Release. It includes prebuilt native components, so Rust, Cargo and a C compiler are not required during installation. See the [Arch installation guide](docs/arch-install.md).

Keep the installation directory: command entries link to its program files. If `~/.local/bin` is not already on PATH, the installer can place entries in `/usr/local/bin`.

Some Ubuntu environments reject the default Waybar `include` in array form. MNWS converts a single default `modules.jsonc` include to an absolute string path in the configuration directory. It saves `.mnws-include-bak` first and preserves custom or multi-file includes.

See [installation details](docs/installation.md) for more information.

### Usage

```sh
mnws -s                         # Start desktop and taskbar
mnws --status                   # Show both states
mnws config                     # Open unified settings
mnws layout apply --restart     # Apply the taskbar layout
mnws -u                         # Check stable Releases
mnws --uninstall                # Uninstall
```

Manage `desktop` and `taskbar` separately with commands such as `mnws taskbar -s` and `mnws desktop -S`. Run either component in the current terminal with `--debug/-d`; `-1` through `-6` select the log level, with `-4` as the default.

Update checks do not install anything. Mainland-China outbound IPs try a GitHub proxy first and fall back to a direct connection.

### Plugins and samples

```sh
mnws mplg build plugins/netease-lyrics
mnws mplg install plugins/org.AkiACG_Community.NCMLyricsBar_1.0.2.mplg
mnws mplg list
```

Enable, order and configure installed plugins in **Components and plugins**. Layout is stored in `~/.config/mnws/taskbar-layout.json`; plugin packages are stored in `~/.local/share/mnws/plugins/`.

The [samples](samples/) directory contains ready-to-use example resources. The [Popcat Start button](samples/start-buttons/popcat/README.md) keeps its mouth closed normally and opens it on hover. Both images have identical dimensions and scale proportionally with the taskbar height.

See the [lyrics plugin guide](plugins/netease-lyrics/README.md), [Plugin API v1.0](docs/mplg-spec.md), [language-file guide](Language.md) and [desktop icon guide](src/niri-desktop-layer/README.md).

### Uninstall

```sh
mnws --uninstall
```

Uninstall defaults to cancellation. After confirmation, keeping configuration defaults to Yes. MNWS removes only its own command entries, native components and generated autostart entries; shared Waybar configuration, desktop files and the source directory are not deleted directly.

### License

Original MNWS code is licensed under **GNU GPL version 3 or any later version (GPL-3.0-or-later)**. Third-party components and samples retain their own licenses, sources and copyright notices. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Development checks / 开发检查

```sh
python3 -m unittest discover -s tests
xvfb-run -a env GDK_BACKEND=x11 python3 tests/check_plugin_settings_gui.py
xvfb-run -a env GDK_BACKEND=x11 python3 tests/check_layout_order_gui.py
make -C src/panel-rows check
```

GUI checks require Xvfb and complement testing in a real Niri session.

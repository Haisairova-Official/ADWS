# Ubuntu / Linux Mint: Waybar compatibility

ADWS requires a native Waybar build containing `cffi/` and `niri/workspaces`.
Ubuntu 24.04 / Mint 22's 0.9.24 package lacks these modules. Checking only the
version or the existence of `waybar` cannot detect this problem.

The source installer now checks the compiled module names. If Waybar is missing
or incompatible, it asks before installing/upgrading the distribution package.
It checks again afterward; when repositories still provide an incompatible
build, it offers to build official Waybar 0.14.0 on the target machine.

For an existing installation:

```sh
adws check --repair-waybar
adws taskbar -s
```

Alternatively, rerun `install.sh`. Build dependencies are shown and require
confirmation. Downloads prefer the configured GitHub proxy when mainland China
is detected, with direct GitHub as fallback. The source revision is pinned to
`41de8964f1e3278edf07902ad68ca5e01e7abeeb`; the GTK Layer Shell fallback archive
is verified against upstream's SHA-256. The build uses two compile jobs.

The source build goes into `$XDG_DATA_HOME/adws-dependencies/waybar` (normally
`~/.local/share/adws-dependencies/waybar`). It does not overwrite system Waybar.
ADWS prefers a compatible system package, otherwise its private build, for the
bottom taskbar and managed top-bar launch/restart/preview. Other applications
invoking plain `waybar` still use their existing PATH configuration.

Before activation, the new binary must pass module checks and `--version`.
Failed activation restores the previous private build; successful replacements
retain the previous directory as `waybar-backup-*`. Build logs are retained under
`$XDG_STATE_HOME/adws-waybar` (normally `~/.local/state/adws-waybar`). Concurrent
builds are rejected. Cancelling repair leaves existing Waybar configuration intact.

Run this on the Ubuntu device, not from an Arch chroot into its mounted disk.
Arch prebuilt ADWS binaries cannot be used on Ubuntu: use the source installer.
The automatic source build is tested in an isolated directory on the development
machine; a complete build on the reported Ubuntu device remains to be verified.

Official sources:
- https://github.com/Alexays/Waybar/tree/0.14.0
- https://github.com/Alexays/Waybar/wiki/Module:-CFFI

## 中文

安装脚本会检查 Waybar 是否包含 CFFI 和 Niri 工作区模块。不兼容时先询问是否
通过系统软件源安装/升级；仍不合适时，可选择在目标系统编译固定版本的官方源码。
现有安装可运行 `adws check --repair-waybar`，完成后重新启动任务栏。

编译版安装在用户专用目录，不覆盖系统 Waybar；ADWS 自动选择兼容版本。
构建前会询问依赖安装，失败保留日志，替换失败恢复旧版，成功替换也保留旧版备份。
国内优先 GitHub 代理，源码提交和依赖下载均校验。卸载 ADWS 不会删除该外部依赖。

另外已修复 Ubuntu PyGObject 的拖动按键类型错误，以及中文目录 CSS 路径被写成
JSON Unicode 转义的问题。完整 Ubuntu 原生构建仍需要在该设备启动后验证。

## Optional Nerd Fonts icons / 可选图标字体

The installer detects existing Nerd Fonts through Fontconfig. When none are
installed, it offers the official Nerd Fonts 3.5.1 Symbols Only package (about
3 MB), verified against the release's SHA-256. The two symbol fonts and their
license are installed under `$XDG_DATA_HOME/fonts/ADWS-NerdSymbols`, and the font
cache is refreshed. Existing text fonts and system font settings are preserved.
Download/install failures warn and allow ADWS installation to continue; declining
does not download anything. ADWS uninstall leaves these shared fonts installed.

To install later, run `adws check --install-fonts`. Restart an existing bar if it
still displays missing glyphs. Official release:
https://github.com/ryanoasis/nerd-fonts/releases/tag/v3.5.1

安装时会检测 Nerd Fonts，缺少时询问是否下载官方轻量符号字体包。安装仅补齐图标，
不替换原来的中英文正文字体。之后也可运行 `adws check --install-fonts`；正在运行的
栏若仍显示方框，可重新启动。下载失败不会阻止 ADWS 安装，卸载 ADWS 不删除字体。

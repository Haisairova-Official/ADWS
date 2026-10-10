# ADWS System Settings

ADWS has one searchable settings window, with grouped navigation, theme-aware cards and compact searchable selection menus. Reopening settings reuses the existing window and can navigate to the requested page without losing pending edits. Pages are created when opened and retain pending changes when navigating. Ctrl+F searches; Ctrl+S applies pending changes. Closing with unsaved appearance, wallpaper, display or account changes asks before discarding them. Refreshing the account page also asks before discarding edits. Page scrollbars occupy the outer edge rather than overlaying their cards.

The visual design uses ADWS's live palette. Manually chosen panel colors stay unchanged. Transitions follow the taskbar's animation preference. The navigation and functional grouping reference [KDE System Settings](https://docs.kde.org/trunk_kf6/en/systemsettings/systemsettings/configuring.html) and [DankMaterialShell's settings modules](https://github.com/AvengeMedia/DankMaterialShell/tree/master/quickshell/Modules/Settings); the implementation uses ADWS's existing GTK stack and configuration formats.

## Account header

The upper-left corner shows a circular avatar, nickname, smaller login name and account type: administrator, standard account or root. Clicking it opens Account & region. Account data is loaded in a worker and cached for the graphical login session; a matching start-menu cache can supply the avatar and nickname. AccountsService supplies account type when available, with local account/group information as fallback. UID 0 is always shown as root. An unavailable account lookup is shown as unknown rather than assuming administrator privileges.

Changing the current user's nickname in Account & region refreshes the header immediately. Interface language is selected from installed system locales and takes effect after signing in again. These actions use AccountsService and any authorization required by that service. Per-account regional formats appear when AccountsService supports them; the native system-default language/date/number controls use locale1 and remain available independently.

## Pages and service integration

| Page | Controls |
| --- | --- |
| Overview | Distribution logo/name, Linux kernel version, current WM/DE and ADWS version, and frequently used settings |
| Desktop and text | Desktop icons, fonts and grid |
| Taskbar appearance | Position, dimensions, split sections, material, colors and animations |
| Components and plugins | Layout, plugin settings and clock |
| Start menu | Launcher, button artwork, menu theme and supported modifier-key profiles |
| Wallpaper | Image library and wallpaper manager |
| Default applications | Browser, file manager, text, image, music, video and PDF handlers |
| Displays | Monitor arrangement, resolution, refresh rate, scale and rotation |
| Input and shortcuts | Keyboard repeat, current Niri layout, modifier-key profiles; native Fcitx 5 groups, addon/schema settings, themes, dictionaries and phrases; native IBus engine order and installed GSettings schemas |
| Network and connections | Devices, Wi-Fi scan/hidden networks, WPA2/WPA3/WEP and enterprise PEAP/TTLS/TLS, Ethernet profiles, IPv4/IPv6/DNS/PAC, VPN import and profile editing |
| Bluetooth | Adapter selection/power, bounded discovery, pairing/PIN confirmation, connection, trust and removal |
| Sound | Input/output selection, per-application volume/mute/routing, card profiles, device ports and per-channel volume |
| Power and battery | Batteries, supported power profiles, per-session AC/battery display/suspend timers, system power-button/lid actions |
| Account and region | Account creation/deletion, name/avatar/password/role/lock, per-account language, system-default language/formats, timezone, NTP and manual time |
| Session and components | ADWS components, Niri startup and per-user XDG login applications |
| Updates and configuration | Updates, configuration import/export and setup wizard |

Service discovery runs off the UI thread with bounded command timeouts. Unavailable services show an explanation in their page. Opening a page does not change the system. Service actions are explicitly applied within their page; disconnecting a network or disabling radios asks for confirmation. ADWS provides these controls itself. It never launches nm-connection-editor, Blueman, pavucontrol, GNOME/KDE control centers, fcitx5-configtool or ibus-setup. The backends remain NetworkManager, BlueZ, PulseAudio/PipeWire, AccountsService, systemd and the chosen input-method framework. Missing backends offer an explicit package-install action for Arch, Debian/Ubuntu or Fedora; no packages are installed merely by visiting a page. Sound client installation preserves the existing audio server; installing PipeWire is a separate explicit action. VPN provider plugins also have a dedicated install action.

Wi-Fi, Bluetooth power and audio mute use compact switches. The switch reflects the last confirmed service state while an operation is pending. Cancelling confirmation or encountering an error preserves that state; successful operations reload it from the service.

Niri keyboard-repeat changes use a validated managed include and preserve existing mouse, touchpad and XKB settings. Hyprland keyboard-repeat changes currently affect only the running session. XDG login-app changes create per-user overrides; system desktop files are not edited. The desktop session must support XDG autostart for those applications to launch.

Native dialogs are transient to the settings window. Administrative actions use a temporary ADWS Polkit agent when the session has no existing agent; an existing session agent stays in charge. Passwords never appear in process arguments or settings exports. Password hashes use the system libcrypt; service secrets are transmitted through D-Bus.

Network edits compare the original profile before writing, preserve withheld Wi-Fi/VPN/WireGuard credentials and remove conflicting legacy IP representations. An activation failure retains a saved profile for correction. VPN import supports provider configuration files for WireGuard/OpenVPN/OpenConnect/vpnc; provider-specific secrets beyond the common password are preserved. New account creation attempts rollback if setting the password fails. Account edits validate all fields before writes, protect root/system/current accounts, attempt restoration of reversible changes on failure and set passwords last.

Bluetooth discovery releases its scan lease after twelve seconds or when its page closes. Pairing uses an ADWS-owned temporary BlueZ agent, accepts requests only from BlueZ for the selected device, asks the user to confirm/input pairing codes, and cleans up cancelled requests and registration.

Power idle policy is off by default and stored in `~/.config/adws/power-policy.json`, included in global config exports. It uses swayidle's Wayland idle events, compositor monitor-power actions and logind suspend; one worker runs per Wayland session only when enabled. Disabling it or uninstalling stops that worker. System button/lid changes are written to an ADWS-managed logind drop-in and apply after reboot; ADWS does not restart logind during the desktop session. Existing system overrides or compositor inhibitors may still affect lid behavior.

Fcitx forms use the configuration schema supplied by the running framework. Schema-less subconfigurations have an internal JSON editor. Theme ZIP imports reject traversal, symlinks and oversized archives; dictionary imports validate their native format. Custom phrases use the framework's XDG data directory. IBus uses its installed GSettings schemas; components that publish no schema cannot expose their private settings through this page. No input-method environment variables are rewritten.

**Uninstall boundary:** even when deleting ADWS configuration, uninstall removes only ADWS components/integration and app-owned configuration. It preserves user-selected network, audio, Bluetooth, account, language, system power policies, input-method resources and shared default-application configuration. It removes ADWS-specific startup/bindings/window rules, preserving unrelated Niri configuration. System changes are not rolled back as a side effect of uninstalling.

Default applications use ADWS's own searchable dropdowns rather than a desktop control center or GTK's grouped application chooser. Compatible handlers are listed first, followed by other visible installed applications. Each application identity appears once, including the current default. Aliases with identical names and launch commands are merged, while separate native and Flatpak launch commands remain distinct. Hidden launchers are excluded unless they are the current default. Selection is staged until Apply; a missing default is not silently replaced when opening the page.

## Displays

Displays appears only in an identified Niri or Hyprland session. Installing the compositor alone does not expose its controls. Available modes come from the running compositor. The arrangement canvas represents logical size after scaling and rotation. Select a monitor and drag it to arrange the desktop; edges snap for alignment, and arrow keys provide fine adjustment. Each monitor retains its own pending mode and position.

Refresh rate and scale each use one editable input with a preset dropdown. Refresh presets are restricted to the selected resolution; manually entered refresh values must match an advertised mode. Scale accepts custom percentages from 50% to 400%. Invalid drafts remain visible for correction and prevent display application, including when switching between monitors.

The test action requests confirmation for 15 seconds and restores original values on cancellation or timeout. All changed outputs are validated before application; partial failures attempt restoration. Concurrent external display changes are detected before overwriting them.

Display changes apply **to the running session only**. Output disabling, HDR, VRR, color profiles and persistent display profiles are not yet provided. Hyprland uses `hyprctl keyword monitor`; unsupported commands report an error instead of silently modifying compositor files.

## Wallpaper library

The default library is `~/Pictures/Wallpapers/`. Images appear as paged thumbnail tiles, loaded in a background worker. “Add wallpapers” accepts multiple images and copies them to the current library. Existing files are never overwritten: duplicates receive a numbered filename. Choosing a different library folder saves that location in `~/.config/adws/wallpaper-library.json`, which is included in configuration exports. The images themselves are not embedded in a configuration export.

Selecting an image previews the selection; wallpaper changes take effect only after Apply. Importing a file does not itself change the desktop wallpaper. Invalid or oversized images report an error. Thumbnail work is bounded and cancelled when obsolete or when the page is destroyed. The gallery currently supports still-image formats, not video wallpapers. Installing a missing wallpaper manager still requires an explicit action and confirmation.

## Verification — 2026-10-04

Backend and isolated GTK checks cover display arrangement and rollback, service adapters, account changes, input persistence, startup overrides, wallpaper imports and asynchronous cleanup. Chinese and English GUI checks cover every page, search, preserved pending changes, editable/searchable selectors and compact-window layout. GUI service mutations use fixtures, so tests do not change real monitor modes, account settings, network connections or wallpaper.

Actual Niri display discovery and installed desktop-service reads were also checked. A live Hyprland session remains unverified; its normalization, commands and rollback are tested with fixtures.

Run `python3 -m unittest discover -s tests` for backend tests. Run `tests/check_system_settings_gui.py` and `tests/check_choice_widgets_gui.py` under a virtual display with isolated `XDG_CONFIG_HOME`, `XDG_STATE_HOME` and `XDG_CACHE_HOME`. Run `xvfb-run -a dbus-run-session -- python3 tests/check_settings_instance_gui.py` to verify repeated launches without contacting an existing desktop settings process. Display, wallpaper and account tests additionally exercise their GTK paths when a virtual display is available. Switch tests intercept system commands in addition to using service fixtures.

Native regression checks: `python3 -m unittest discover -s tests -p test_native_settings.py` and `xvfb-run -a dbus-run-session -- python3 tests/check_native_settings_gui.py`. Native GUI checks intercept every service write and exercise cancellation, error recovery, addon field order, stale discovery and authentication cleanup. Actual destructive network/account/power changes are not part of automated verification.

Protocol references: [NetworkManager settings](https://networkmanager.dev/docs/api/latest/settings-ipv4.html), [BlueZ Agent API](https://bluez.readthedocs.io/en/latest/agent-api/), [Fcitx controller implementation](https://github.com/fcitx/fcitx5/blob/master/src/modules/dbus/dbusmodule.cpp), [IBus GSettings schema](https://github.com/ibus/ibus/blob/master/data/dconf/org.freedesktop.ibus.gschema.xml), and [Polkit authentication agents](https://polkit.pages.freedesktop.org/polkit/polkit-agents.html).

## Input, sound and compact controls — 2026-10-04

输入与快捷键分为键盘、快捷键和输入法；输入法再按输入方式、候选框与词库、附加组件分组，切换分组保留未应用的键盘修改。键盘页增加测试输入框。声音页统一为输出、输入、应用音量和高级设置，不重复扫描/展示同一组设备；音量滑块即时生效，连续调整合并并在工作线程串行提交，控件不会因每次音量变化重建。设备、声道、配置模式和应用路由仍可设置。刷新或关闭会取消尚未提交的音量调整，失败后重新读取实际状态。

设置中的开关按自然尺寸在两轴对齐，包含蓝牙设备信任开关及输入法附加组件，避免被相邻按钮撑大。账户管理在每个用户最左侧显示头像；头像在后台限量读取并裁切，没有有效头像时使用默认图标。

Input settings now group keyboard, shortcuts and input methods. Fcitx separates methods, appearance/dictionaries and add-ons. Switching groups preserves pending keyboard edits. Audio uses Output, Input, Applications and Advanced views without duplicate device controls. Slider updates are coalesced and serialized outside GTK; moving a slider does not rebuild it. Refresh/close cancels pending edits, and failures reload actual service state. Toggles retain their natural size beside tall controls. Account management places a bounded, asynchronously decoded avatar at the far left of each user row.

Regression checks: `tests/test_settings_redesign.py` and `tests/check_settings_redesign_gui.py`. Use an isolated virtual display, session bus and temporary XDG directories. The GUI check uses service fixtures and checks Chinese/English layout, compact switch allocations, preserved tab state, user avatars and the AkiACG theme selector without changing system settings.

## 登录启动项删除 / Removing login applications

右键登录启动项可选择“删除”。确认框的标题和正文再次显示启动项名称，并询问“确定要删除该启动项吗？”，默认取消。只移除自启入口，不卸载应用；系统自启项仅以当前用户的隐藏覆盖配置屏蔽，不修改系统文件，启动项软链接的目标也会保留。重新添加应用可恢复自启。

Right-click a login application and choose Delete. The confirmation repeats its name in the title and message and defaults to Cancel. Deletion removes the login entry, not the application. System entries are suppressed with a private hidden override; system files and symlink targets remain intact. Adding the application again restores its login entry.

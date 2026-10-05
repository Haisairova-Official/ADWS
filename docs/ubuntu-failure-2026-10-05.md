# Ubuntu-family failure diagnosis — 2026-10-05

Mounted report system: Linux Mint 22.3, Ubuntu noble base. Package database shows
Waybar 0.9.24-1build3. Taskbar logs repeatedly report unknown `cffi/*` and
`niri/workspaces` modules. The bars start but cannot instantiate ADWS components.
Read-only ELF inspection confirms the required factory module names are absent.
This is a runtime dependency incompatibility, not a Niri IPC or lyrics failure.

Two independent ADWS bugs were reproduced and fixed:

1. CSS asset paths generated through `json.dumps` turned the Chinese install
   directory `桌面` into literal `\u684c\u9762`. CSS does not use JSON Unicode
   escape syntax. Corrected topbar rendering, preview color imports, height corner
   styling and imported CSS paths to use a CSS string encoder. Legacy escaped
   references resolve to their existing decoded file only when the literal file
   does not exist, allowing backup/import of affected configurations.
2. `LayoutWindow` passed `1 << 8` to `drag_source_set`. With the report system's
   Python 3.12/PyGObject, construction raises `TypeError: Expected a
   Gdk.ModifierType, but got int`. All three shared taskbar settings pages fail.
   Use `Gdk.ModifierType.BUTTON1_MASK`.

Validation loaded the report system's own Python and GTK shared libraries using
its dynamic loader, against isolated copies of the mounted home configuration.
Before the fix, the exact drag-source TypeError reproduced. Afterwards taskbar,
layout and start pages all opened successfully. Chinese-path render, bundle,
import and legacy-reference tests passed. System font/resource warnings in this
mixed-root test are environmental; no real desktop session was changed.

Installation and taskbar startup now validate compiled Waybar module support and
refuse an empty-bar startup. This does not upgrade Waybar automatically. The
mounted device still needs a compatible Waybar, then a source installation and a
real graphical login test. See [Ubuntu installation](ubuntu-install.md).

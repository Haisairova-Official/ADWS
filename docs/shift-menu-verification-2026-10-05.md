# Shift context-menu verification — 2026-10-05

The Wayland taskbar layer normally has keyboard interactivity disabled. With
Shift held in another application, both the pointer event mask and GDK keymap
reported zero. An X11 event fixture did not reproduce this condition.

Window context menus now temporarily enable on-demand keyboard interactivity
on their owning layer window. Deactivate, unmap and destruction restore its
previous mode. Non-layer windows and already-interactive layers retain their
mode. Modifier handlers remain event driven; no polling timer was added.

## Verification

- Nested Niri with actual Wayland GTK clients and a separate focused entry:
  hold left Shift before right-click → End process with destructive styling;
  release → Close window; press right Shift → End process; Escape → the
  menu is destroyed and the layer returns to keyboard mode NONE.
- GTK regression: Shift/below/disabled modes, grouped submenus, both Shift
  keys, destructive styling, and agreement between the displayed action and
  the action sent to a disposable test process.
- Native unit tests: 15 passed; display/stress tests remain opt-in.
- Release build and Python driver syntax passed.

Run the Wayland check after building native tests:

```sh
cargo test --locked --offline --manifest-path src/niri-taskbar/Cargo.toml --lib --no-run
dbus-run-session -- python3 tests/check_shift_wayland.py
```

Requires Niri, Xvfb, xdotool, libXtst, PyGObject and gtk-layer-shell. The driver
creates a private display and runtime directory and never sends input to the
current desktop. The Wayland fixture isolates hover previews; grouped-menu
state and actions are covered by the separate GTK regression. Combined Peek
interactions need a manual desktop check.

The rebuilt module was backed up, atomically installed and loaded by the local
taskbar. Backup: `/tmp/adws-shift-focus-backup-20261005-012836`.

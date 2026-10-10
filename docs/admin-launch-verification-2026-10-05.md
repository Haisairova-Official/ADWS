# Administrator launch repair — 2026-10-05

Three separate failures were found:

- The current context menu destroyed its children during `deactivate`. GTK's
  normal click/Enter path deactivates the shell before activating the item, so
  its action handlers had already been disconnected. Deferred cleanup restores
  action delivery and still releases dismissed menus.
- A recorded Firefox launch reached pkexec but inherited the user's
  `XDG_RUNTIME_DIR`, which Firefox rejected as belonging to another UID.
  Administrator launches now resolve the Wayland display socket to an absolute
  path and retain pkexec's administrative HOME/runtime environment.

- The initial Python `PolkitAgent.Listener` implementation crashed after password
  submission. Core dumps showed the native Polkit completion callback receiving
  an invalid context (`0x1`). A C callback probe reproduced loss of the original
  opaque callback context; Python-only virtual-method fixtures missed it.
  The replacement exports the documented authentication-agent D-Bus protocol
  through GIO and retains each real method invocation until completion. PAM and
  privilege decisions remain entirely in the system Polkit libraries.

The launch helper runs its GTK loop while authorization is pending and provides
an ADWS Polkit agent scoped to its own process. It does not replace the session
agent or alter authorization policy. If native agent support is unavailable,
an installed session agent can still service pkexec. Cancellation closes the
temporary agent; errors show the app name and bounded diagnostic output in a
compact ADWS dialog with the live settings palette. The authorization dialog
shows the application, account, one password field and Cancel/Authorize actions;
operation details are expandable. Launch diagnostics are also expandable and
bounded, with plain labels rather than HTML. Apps that explicitly refuse root execution keep that behavior;
no sandbox-disabling flags are added.

## Verification

- Actual GTK menu-shell activation: root and opened grouped submenu actions
  fire once and dismissed menus are released.
- Real Wayland Shift regression passed after deferred cleanup.
- Launch unit tests: 10 passed; translations: 4 passed.
- GUI fixtures cover success, cancellation, refusal, execution errors, missing
  native auth support, bounded diagnostic reads, UI dispatch and agent cleanup.
- Existing native-settings GUI fixtures passed, including auth cancellation.
- A real process-scoped agent registered against local Polkit, received an
  actual PAM authentication challenge, automatically cancelled it and completed
  CheckAuthorization with `authorized=False`. No password was submitted and no
  root application was started.
- Isolated real D-Bus conversations cover successful completion, password
  submission/clearing, failure/retry, cancellation, late signals, untrusted
  senders and cleanup. PAM is simulated in these tests. Both Chinese and English
  dialogs passed size checks and were visually inspected.
- Native units: 15 passed; release build passed.

Actual privileged application startup still requires a manual password/launch
check. Fixture tests do not bypass Polkit or start the user's apps as root.

```sh
python3 -m unittest discover -s tests -p test_app_launch.py
GDK_BACKEND=x11 xvfb-run -a python3 tests/check_app_launch_gui.py
GDK_BACKEND=x11 GIO_USE_VFS=local dbus-run-session -- xvfb-run -a python3 tests/check_auth_bus_gui.py
```

References: [GTK menu-shell activation](https://github.com/GNOME/gtk/blob/gtk-3-24/gtk/gtkmenushell.c),
[pkexec environment and authorization](https://polkit.pages.freedesktop.org/polkit/pkexec.1.html),
[pkexec caller subject](https://github.com/polkit-org/polkit/blob/master/src/programs/pkexec.c),
[Firefox UID mismatch checks](https://github.com/mozilla/gecko-dev/blob/master/toolkit/xre/nsAppRunner.cpp).

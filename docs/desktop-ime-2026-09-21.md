# Desktop inline rename: Wayland IME regression

The 2026-09-21 desktop freeze was reproduced in a separate Niri compositor running
inside Xvfb with a private D-Bus session and copies of the affected GTK/Fcitx theme
configuration. The default theme did not reproduce it. The blocked application's
main-thread stack was:

```
im-fcitx5.so → gdk_pixbuf_new_from_file
             → gly_image_get_specific_frame → futex wait
```

This occurs when the GTK Fcitx module loads the themed client-side candidate UI.
It is distinct from the independently fixed resize feedback and focus-out commit
issues. Simulated preedit events under X11 were insufficient to catch it.

The native desktop rename entry now explicitly selects GTK's `wayland` IM module.
Candidate UI is handled by the compositor/input method instead of decoding the
Fcitx candidate images in the desktop process. This is a per-entry setting; global
input-method variables, dictionaries and themes are unchanged. X11 preview mode
continues to use its normal input method.

Validation: private Xvfb keyboard events through nested Niri, Fcitx Pinyin and the
affected theme produced `中文`, successfully renamed a temporary file, and exited
normally. The 10 isolated desktop GUI regressions also passed. All compositor,
input-method and debugger test processes used private sessions and temporary data.

Inline creation now shares the same editor and native Wayland input path. It uses
text.txt, markdown.md and folder defaults, holds drafts only in memory until
confirmation, and rejects existing targets with exclusive filesystem creation.
Validation: 12 desktop GUI tests passed, including full-page/cancel/collision
cases; a private nested Niri/Fcitx run created a file named 中文 through actual
keyboard input while preserving the existing fixture file.

# Licensing and third-party notices

ADWS original code is licensed under GNU GPL version 3 or, at your option,
any later version (`GPL-3.0-or-later`). See [LICENSE](LICENSE).
Separately licensed components retain their existing terms and notices.

- `src/niri-taskbar`: derived from Adam Harvey's
  [niri-taskbar](https://github.com/LawnGnome/niri-taskbar), MIT.
  See its retained `LICENSE`. ADWS modifications include scrolling, menus,
  layout sizing and compatibility with the Niri/Shorin IPC used here.
- `src/niri-desktop-layer`: Akizuki, MIT; see its retained `LICENSE`.
- `vendor/niri-ipc`: snapshot from the local Niri/Shorin 26.04 source tree,
  package version 26.4.0, GPL-3.0-or-later. Source and license are included.
  The upstream metadata points to https://github.com/niri-wm/niri;
  an exact fork revision was not recorded. Only the manifest was adapted
  to remove workspace inheritance; Rust source is unchanged.
- `src/adws-runtime`: ADWS native plugin supervisor, GPL-3.0-or-later.
- `src/adws-start-menu`: ADWS GTK3 start menu, GPL-3.0-or-later. Theme presets are original CSS inspired by desktop layouts; no proprietary theme assets are bundled.
- Other Rust dependencies retain their respective licenses. Versions are
  recorded in `src/niri-taskbar/Cargo.lock`, `src/adws-runtime/Cargo.lock` and `src/adws-start-menu/Cargo.lock`.

This source release does not include compiled binaries, fonts, music,
lyrics, or browser credentials. External lyrics services supply their own content.

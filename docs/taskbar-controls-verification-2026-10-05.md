# 2026-10-05 verification

- Python backend suite: 429 tests, successful; 22 conditional skips.
- Native taskbar: 15 ordinary tests passed; isolated tray icon, tray overflow/unload, Shift single/group menu, and real close/terminate action regressions passed separately.
- Native plugin supervisor: two unit tests and ten subprocess integration tests passed, including both supervisors sharing bounded display snapshots, ignoring stale producer processes and avoiding repeated heartbeat writes.
- Isolated GTK checks passed: actual mouse drag across regions and preview, four-direction bilingual preview, all four popup materials with configured radius, and startup deletion confirmation/cancel/removal. Temporary entries and fixture devices only.
- Chinese/English help and translation checks passed. Python syntax, shell syntax and Git whitespace checks passed. Release builds of taskbar and plugin supervisor succeeded offline.
- Installed Wayland audio/brightness test panels passed overlay, namespace, keyboard and exclusive-zone checks with all hardware writes replaced by fixtures.
- Development, publishing checkout and installed ADWS files were synchronized. Personal runtime layout was preserved. Native components were replaced atomically after backup to `/tmp/adws-layout-tray-startup-backup-20261005-010035`.
- Restarted taskbar PID 491709 was alive, with one running lyric preview instance and no critical errors or main-loop delays in the sampled new log. RSS at that point was 168272 kB, with 22 threads. This short check does not establish long-term memory or stall behavior.

No Git commit, push or release was performed. The update record remains pending user review.

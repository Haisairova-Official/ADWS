# Taskbar / NCMLyricsBar verification — 2026-10-03

## Scope and limitations

Investigated intermittent, progressively worsening main-loop latency and possible
memory growth. The original real-session stall has **not** been reproduced in the
controlled tests below. These results do not certify hours of browser playback or
Wayland/compositor behaviour. No release or plugin version bump is implied.

Installed NCMLyricsBar 1.1.0 source and native supervisor match the development
copies (SHA-256 checked). The zbus `read_socket: close` messages end tracing spans
for individual reads; they do not establish disconnections/reconnection storms.

## Changes under test

Window updates previously traversed two unbounded queues. The IPC reader now
retains one latest complete window snapshot, while preserving pending output
changes. The UI handoff is bounded and yields to GLib between events. All IPC
events still update the model; obsolete visual snapshots are coalesced.
Snapshot rendering taking more than 50 ms now logs a diagnostic.

## Results

- 100,000 snapshots while the UI is idle: one pending notification and latest
  state retained, including an earlier output-change flag.
- Concurrent 100,000-update producer: final notification delivered, receiver
  shutdown detected.
- 30-second real IPC-to-GTK synthetic flood: 149,100 events; 1,446 heartbeat
  samples after warmup; maximum and p99 heartbeat gaps 20 ms. RSS after warmup
  186,400 KiB, final 186,120 KiB.
- 500 created/removed window cards: zero surviving GTK button or popover weak
  references after each of ten batches.
- Rust supervisor → real NCMLyricsBar render payloads → C GTK rows renderer:
  90 seconds, 1,102 label changes, maximum heartbeat gap 20.53 ms; RSS stable at
  204,040 KiB after warmup; zero supervisor restarts.
- Python supervisor with the same workload: 90 seconds, 1,111 label changes,
  maximum gap 20.67 ms; RSS stable at 204,060 KiB; zero restarts.
- Both lyric runs include dynamic width, mixed CJK/Latin text, bilingual and
  single-line output, repeated hover controls, a 35-second pause with 15-second
  heartbeats, and playback resumption. Playback metadata is synthetic; browser
  IPC and network requests are not included.
- 18-second C AddressSanitizer/UndefinedBehaviorSanitizer run: no reported access
  or undefined-behaviour errors. LeakSanitizer was disabled because GTK caches
  require separate interpretation; this is not a global leak-freedom claim.
- GTK regressions: card geometry/grouping, pinned applications, Peek fade and
  cancellation of an unfinished preview all passed with isolated configuration.
- Native supervisor subprocess tests: 9 passed (contracts, slow consumers,
  disconnects, cancellation and child cleanup). Lyric logic tests: 14 passed.

## Test installation

Queue fix built in release mode and installed into `/home/akizuki/ADWS` and
`~/.local/lib/waybar/libniri_taskbar.so`; prior files are in
`/home/akizuki/ADWS/backups/queue-verification-20261003-120851`.
The restarted real bottom bar was observed for 44 seconds: RSS 159,828 →
159,788 KiB, no new main-loop or snapshot-rendering delay warnings. This short
observation is not a long-playback regression test. The lyrics supervisor and
plugin were not changed. No Git push was performed.

## Reproduction

From the repository root:

```sh
python3 tests/check_lyrics_soak.py --seconds 90
python3 tests/check_lyrics_soak.py --backend rust --seconds 90 --sanitize
```

The tests use Xvfb and do not alter the desktop configuration. They require GTK3,
JSON-GLib, gtk-layer-shell development packages and the built Rust supervisor.

For the IPC stress test, from `src/niri-taskbar`:

```sh
xvfb-run -a env GDK_BACKEND=x11 ADWS_STRESS_SECONDS=60 cargo test --offline --lib sustained_ipc_flood_keeps_gtk_responsive_and_memory_bounded -- --ignored --nocapture
```

Current evidence does not identify a Rust-supervisor/NCMLyricsBar protocol
incompatibility as the cause. The extended playback results follow below.

## Extended verification and icon allocation fix

A reproducible hot-path defect was found in application card allocation: the
redraw test checked GtkButton.image(), but the icon is a child in a separate
container. It also invalidated on long-axis changes even though image size
only depends on thickness and scale. Lyrics width animation could consequently
trigger redundant synchronous icon loading on the GTK thread.

The cache now checks the actual icon child and keys on cross-axis thickness and
scale factor; asynchronous icon-path discovery still invalidates it. The new
horizontal/vertical regression produced 12 redundant loads before the fix and
zero afterward; changing thickness still redraws correctly. All 12 non-GUI Rust
tests and four isolated GTK regression cases passed, and the release build
completed. The icon fix was not installed during the initial real playback
observation, to avoid changing its conditions mid-run.

Two 720-second real-render-payload / Rust-supervisor / GTK tests cover >13,600
text changes each, repeated hover controls and pause/resume. The second also
loads the user's installed Waybar CSS. These are synthetic media tests, not
browser playback. Optional ADWS_PANEL_PROFILE=1 now logs per-30-second rows
update and font-fit counters/timing; disabled by default.

- Default theme 720 s: 13,662 changes, max heartbeat gap 22.77 ms,
  RSS warm/final both 203,956 KiB, no supervisor restarts.
- Installed theme 720 s: 13,678 changes, max gap 22.27 ms,
  RSS warm/final both 207,908 KiB, no supervisor restarts.

## Real desktop observation (before the icon/font/lifetime fixes)

The queue fix and optional rows diagnostics were active. Firefox music was
confirmed Playing during and at the end of a 730-second observation. A parent
GDB sampled the main thread every 10 seconds and detached at completion; this
briefly pauses execution and is not an entirely uninstrumented run. No
main-loop-delay warnings occurred. Samples were in the GLib poll loop.
RSS at the first sample was 159,692 KiB and the final sample 170,624 KiB;
it held around 169,992 KiB late in the run. This is not proof of leak freedom.
Initial font fit took 445,739 us; later sampled text updates were under 104 us
and did not refit. The reported original progressive stall was not reproduced.

## Follow-up source audit

- Font fit used to binary-search sizes after every style invalidation, even
  when only colors/classes changed. One retained metrics key now includes
  height, font description, font map and serial, language, DPI and Cairo font
  options. A regression first failed with 20 redundant fits, then passed with
  zero; font changes and the existing height/vertical/palette tests still pass.
- GLib JoinHandle drop detaches tasks. TaskbarModule previously held no handle,
  so unloading it did not cancel its Instance. The event stream and notification
  stream likewise detached child listeners. Explicit cancellation owners now
  propagate module/stream teardown to their child tasks. Notification buffering
  is bounded. Closed UI receivers stop forwarders.
- An owned duplicate of the Niri transport permits shutdown on stream drop,
  interrupting even an idle blocking read. Its regression verifies termination
  without sending any further event. Cancellation never joins a worker on GTK.
- Module cancellation regression verifies nested listener resources are released.
  These lifecycle defects concern module replacement/unload; they do not prove
  that uninterrupted music playback caused repeated module replacement.

The fixes do not change plugin settings, visual design, or release versions.

## Final build and handoff

- Final Rust units: 13 passed; nested cancellation GLib test passed separately.
- Final IPC flood: 15 s / 74,550 events, max and p99 heartbeat 20 ms;
  RSS after warmup 186,148 -> 185,904 KiB.
- Four GTK card/Peek regression cases passed; C panel/motion/vertical suite passed.
- Post-cache ASAN/UBSAN: 18 s / 362 lyric changes, max heartbeat 20.50 ms,
  no reported memory access or UB failures (LeakSanitizer remains disabled).
- Release libraries built, sources synchronized to the development/publishing/test
  copies. Test installation backup:
  /home/akizuki/ADWS/backups/lyrics-icon-fix-20261003-123800
- Bottom bar restarted and both new libraries verified loaded without deleted
  mappings. The user's configuration was preserved; no Git push was performed.
- Long real-session sampling ended at the user's request. The final icon/font/
  lifetime changes have regression and startup validation, not another long
  playback run. The original progressive stall remains unproven as to cause.

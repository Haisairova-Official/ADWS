# Taskbar hover stall: 2026-10-05

## Confirmed defect

The pinned-app separator used `parent.path()` to probe the focused-card color, then appended a synthetic button to that path. gtk-rs exposes `GtkWidgetPath` as a shared, ref-counted boxed value: `Widget::path()` and ordinary clones do not deep-copy the cached widget path. Every separator redraw therefore extended the live parent path. Icon hover animations caused redraws and expensive GTK selector matching on the increasingly long ancestor chain.

The regression test fails on the old implementation after the first lookup: parent path length changes from 2 to 3. The fix uses `WidgetPath::copy()` before appending the synthetic selector. It retains custom focused colors and live palette changes.

## Evidence and validation

- Three stalled main-thread stacks were inside GTK CSS matching/style validation. The background focus worker was idle.
- Symbolized sample: `_gtk_css_matcher_has_id` → descendant selector matching → `gtk_style_cascade_lookup` → `gtk_css_node_validate_internal`.
- Live main-loop delays reached roughly 1.6–2.5 seconds. Old taskbar RSS grew from roughly 171 MiB to over 500 MiB during the observed session. This is corroborating evidence of accumulated state, not a complete heap leak analysis.
- Added isolated GTK regression: 100 focused-color lookups preserve the parent path's length and selector text.
- Added 200-cycle Peek render/dismiss regression under the installed adw-gtk3-dark theme: old child widgets release; first/last 20 cycles remain approximately 0.65/0.63 seconds total (including deliberate test waits). This separately checks that preview content is not retained.
- Standard Rust unit tests: 15 passed. Local-socket tests require execution outside the restricted sandbox.
- Fixed the existing pin click fixture to wait for the already asynchronous focus worker before asserting its response.
- Source synchronized to the publishing checkout; rebuilt library and relevant source deployed with a backup. Only the bottom ADWS taskbar restarted; live configuration and the top bar were preserved.
- User's post-deployment hover/Peek/window-switch test: currently normal. After roughly nine minutes the bottom bar remained around 180 MiB RSS with no new matching delay warnings. Long-session memory stability remains a separate observation requirement.

No GitHub release artifact or Git push was performed for this fix.

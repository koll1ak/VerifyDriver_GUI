# Auto-scan on app open

## Problem

Today the GUI opens idle ("Ready") and requires the user to click "Scan"
before seeing anything. Since scanning is almost always the first thing a
user wants after opening the app, that click is pure friction.

## Design

In `App.__init__` (`gui/app.py`), after `_build_widgets()`, schedule the
existing `_start_scan()` via `self.root.after(100, self._start_scan)`
instead of leaving the app idle. This:

- Lets the window paint and become visible before the scan starts, rather
  than blocking/racing construction.
- Reuses `_start_scan()` exactly as-is — same worker thread, same queue
  polling, same result rendering, same error handling.
- Triggers on every launch (no persistence between runs exists today, so
  there's nothing to conditionally skip).

The manual "Scan" button is unchanged: it stays enabled/disabled by the
same logic as today, and can be used to re-scan after the automatic scan
(or any scan) completes.

## Out of scope

- No settings/toggle to disable auto-scan.
- No persistence of previous results between launches.

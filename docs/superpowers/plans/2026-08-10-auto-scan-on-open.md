# Auto-scan on app open Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the GUI start scanning automatically as soon as it opens, instead of sitting idle until the user clicks "Scan".

**Architecture:** `App.__init__` (`gui/app.py`) builds the widgets, then schedules the existing `_start_scan()` method via `self.root.after(100, self._start_scan)` so the window paints before the scan kicks off. `_start_scan()` itself is untouched — same worker thread, same queue polling, same rendering, same "Scan" button enable/disable behavior for later manual re-scans.

**Tech Stack:** Python, Tkinter/ttk (existing GUI stack — no new dependencies).

## Global Constraints

- No settings/toggle to disable auto-scan (per approved design doc `docs/superpowers/specs/2026-08-10-auto-scan-on-open-design.md`).
- No persistence of previous results between launches — auto-scan runs on every launch, unconditionally.
- This codebase has no automated test suite (no pytest, nothing in `requirements.txt`, no `test_*.py` files anywhere). Per project convention (see project memory: iterate GUI changes against the interpreter, not a rebuild), verification for this task is manual: run the app with the Python interpreter and observe behavior — do not introduce a new test framework for this one change.

---

### Task 1: Auto-start the scan when the window opens

**Files:**
- Modify: `gui/app.py:65-77` (the `App.__init__` method)

**Interfaces:**
- Consumes: `App._start_scan` (existing method, `gui/app.py:169`) — no signature change, called with no arguments exactly as the "Scan" button's `command=self._start_scan` already does.
- Produces: nothing new consumed by other tasks — this is the only task in the plan.

- [ ] **Step 1: Make the code change**

In `gui/app.py`, the current `__init__` ends with:

```python
        self._build_widgets()
```

Change it to:

```python
        self._build_widgets()

        # kick off a scan automatically once the window is up, rather
        # than sitting idle until the user clicks "Scan" — scheduled via
        # after() instead of a direct call so the window finishes
        # painting first
        self.root.after(100, self._start_scan)
```

- [ ] **Step 2: Run the app from source and verify manually**

Run: `python gui_main.py` (from the project root, using the project's existing venv/interpreter — do not build with Nuitka for this check).

Expected, in order:
1. The window appears already in the "Scanning" state (status label reads "Scanning", progress bar is animating, "Scan" button is disabled) — no click needed.
2. The scan completes normally and results render exactly as they do today after a manual scan (status label reads "Done", table populated, drivers link shown if applicable).
3. Click "Scan" again — it re-scans normally (button disables, progress restarts, table clears and repopulates on completion), confirming the manual path still works unchanged.

- [ ] **Step 3: Commit**

```bash
git add gui/app.py
git commit -m "Auto-start a scan when the GUI opens"
```

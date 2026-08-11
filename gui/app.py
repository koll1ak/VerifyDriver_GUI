import ctypes
import queue
import sys
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from tkinter import ttk
from typing import NamedTuple

from checks.common import overall_drivers_page_url
from checks.registry import CATEGORY_ORDER
from orchestrator import group_pairs_by_category
from gui import worker

WINDOW_TITLE = "VerifyDriver"
# base size at 100% Windows scaling (96 DPI) -- actually applied through
# App._init_dpi_scaling()'s multiplier, not used as a literal geometry
# string, so the window (and everything else sized off self._scale) comes
# out physically the same size on a 4K/150%+ display instead of shrinking
# to a corner of the screen
BASE_WINDOW_WIDTH = 1000
BASE_WINDOW_HEIGHT = 600

# same idea for the Treeview's column widths (see _build_widgets)
BASE_COLUMN_WIDTHS = {"#0": 280, "current": 170, "available": 170, "status": 220}


def _enable_windows_dpi_awareness():
    """
    Without this, Windows treats the process as DPI-unaware and bitmap-
    scales the whole rendered window to match the display's actual scale
    factor -- the classic blurry/oversized-then-shrunk look old apps get
    on a 4K screen. Must run before the first Tk window is created (the
    Win32 API rejects a second call, and it's a no-op once a window
    already exists) -- called at the very top of App.__init__, before
    tk.Tk().
    """
    if sys.platform != "win32":
        return
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE -- Windows 8.1+; re-queries DPI if
        # the window is dragged to a monitor with a different scale factor
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            # Vista/7 fallback -- system-DPI-aware only, but still sharp
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


class _RowInfo(NamedTuple):
    """Per-row Treeview state that's always looked up together (tags for
    restoring after a hover, url for opening on click)."""
    tags: tuple
    url: str | None

# "Scanning" is the longest of the three normal-flow status texts
# (Ready/Scanning/Done) — reserve that much width so the layout doesn't
# shift as the text changes between them
STATUS_LABEL_WIDTH = len("Scanning")


def _fit_text(text, max_width, measure):
    """
    Shrinks text to fit max_width (in whatever unit `measure` returns,
    normally pixels), appending "..." once it doesn't already fit. The
    first cut removes 2 characters; every cut after that removes 1 --
    matches the ellipsis behavior of Driver Store Explorer (RAPR), which
    this app's column resizing is modeled on.
    """
    if measure(text) <= max_width:
        return text
    candidate = text[:-2]
    while candidate:
        fitted = candidate + "..."
        if measure(fitted) <= max_width:
            return fitted
        candidate = candidate[:-1]
    return "..."


class App:
    def __init__(self):
        _enable_windows_dpi_awareness()
        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self._scale = self._init_dpi_scaling()
        self.root.geometry(f"{round(BASE_WINDOW_WIDTH * self._scale)}x{round(BASE_WINDOW_HEIGHT * self._scale)}")

        self.result_queue: queue.Queue | None = None
        self._rows: dict[str, _RowInfo] = {}
        self._row_counter = 0
        self._hovered_row = None

        self._build_widgets()

        # kick off a scan automatically once the window is up, rather
        # than sitting idle until the user clicks "Scan" — scheduled via
        # after() instead of a direct call so the window finishes
        # painting first
        self.root.after(100, self._start_scan)

    def run(self):
        self.root.mainloop()

    def _init_dpi_scaling(self) -> float:
        """
        Tk's own unit system assumes 72 DPI internally, so without this a
        DPI-aware process (see _enable_windows_dpi_awareness) still draws
        fonts/widgets at the wrong physical size even though the window
        itself is no longer bitmap-blurred. Setting "tk scaling" to the
        display's real DPI/72 fixes point-sized fonts; the returned
        DPI/96 factor (96 = Windows' 100% baseline) is used separately to
        scale pixel-literal layout constants (window size, column widths)
        that were tuned by eye at 100%.
        """
        dpi = self.root.winfo_fpixels("1i")
        self.root.tk.call("tk", "scaling", dpi / 72.0)
        return dpi / 96.0

    # --- widget construction ------------------------------------------

    def _build_widgets(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")

        self.scan_button = ttk.Button(top, text="Scan", command=self._start_scan)
        self.scan_button.pack(side="left")

        self.status_label = ttk.Label(top, text="Ready", width=STATUS_LABEL_WIDTH, anchor="w")
        self.status_label.pack(side="left", padx=10)

        self.progress = ttk.Progressbar(top, mode="indeterminate")
        self.progress.pack(side="left", fill="x", expand=True, padx=10)

        tree_frame = ttk.Frame(self.root)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        columns = ("current", "available", "status")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings")
        self.tree.heading("#0", text="Device")
        self.tree.heading("current", text="Current Driver version")
        self.tree.heading("available", text="Available Driver version")
        self.tree.heading("status", text="Status")
        for col, base_width in BASE_COLUMN_WIDTHS.items():
            self.tree.column(col, width=round(base_width * self._scale), anchor="w")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # "TkDefaultFont" as a font *family* string doesn't exist — passing
        # it in a (family, size, style) tuple silently falls back to some
        # generic font instead of matching the rest of the UI. Derive the
        # real family/size from the actual named font instead.
        default_font = tkfont.nametofont("TkDefaultFont")
        family, size = default_font.actual("family"), default_font.actual("size")
        # the "Treeview" style's row height is a fixed pixel count baked in
        # by the theme at startup, based on whatever font metrics were
        # current at that point — recompute it from the actual (now
        # DPI-scaled) font so rows don't end up too short to fit their own
        # text on a high-DPI display
        style = ttk.Style()
        style.configure("Treeview", rowheight=round(default_font.metrics("linespace") * 1.4))
        self.tree.tag_configure("category", font=(family, size, "bold"))
        self.tree.tag_configure("update", foreground="#c0392b", font=(family, size, "underline"))
        self.tree.tag_configure("linked", foreground="#1a73e8")
        self.tree.tag_configure("error", foreground="#c0392b")
        # hover highlight for any row with a link — only sets background,
        # so it layers on top of the "update"/"linked"/"error" foreground
        # color instead of replacing it
        self.tree.tag_configure("hover", background="#dbe9fd")

        self.tree.bind("<Double-1>", self._on_row_double_click)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", self._on_tree_leave)

        # a Text widget (not a Label) specifically so only the URL portion
        # of the line is a click/hover zone, not the whole sentence
        self.drivers_link = tk.Text(
            self.root, height=1, wrap="none", relief="flat", state="disabled",
            cursor="arrow", padx=8, pady=4, background=self.root.cget("background"),
            font="TkDefaultFont",
        )
        self.drivers_link.pack(fill="x")
        self.drivers_link.tag_configure("link", foreground="#1a73e8", underline=True)
        self.drivers_link.tag_configure("hover", background="#dbe9fd")
        self._drivers_link_range = None

    # --- scan lifecycle -------------------------------------------------

    def _start_scan(self):
        self.scan_button.config(state="disabled")
        self.status_label.config(text="Scanning")
        self.progress.start(10)
        self._clear_tree()
        self._set_drivers_link(None)

        # nothing is rendered until the scan is fully done (see
        # _finish_scan) — same "collect everything, then show it once,
        # already in order" model the CLI has always used
        self._pending_errors = []

        self.result_queue = queue.Queue()
        worker.start_scan(self.result_queue)
        self.root.after(100, self._poll_queue)

    def _poll_queue(self):
        try:
            while True:
                msg = self.result_queue.get_nowait()
                tag = msg[0]
                if tag == worker.ERROR:
                    _, category, message = msg
                    self._pending_errors.append((category, message))
                elif tag == worker.DONE:
                    _, results, board, laptop = msg
                    self._finish_scan(results, board, laptop)
                    return
                elif tag == worker.NO_INTERNET:
                    self._finish_scan_no_internet()
                    return
                elif tag == worker.FATAL:
                    _, message = msg
                    self._finish_scan_fatal(message)
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _reset_scan_controls(self):
        self.progress.stop()
        self.scan_button.config(state="normal")

    def _finish_scan(self, results, board, laptop):
        self._reset_scan_controls()
        self._render_results(results)
        self.status_label.config(text="Done")
        self._set_drivers_link(overall_drivers_page_url(board, laptop))

    def _finish_scan_no_internet(self):
        self._reset_scan_controls()
        self._clear_tree()
        self.status_label.config(text="No internet connection — check your network and try again.")

    def _finish_scan_fatal(self, message):
        self._reset_scan_controls()
        self.status_label.config(text=f"Unexpected error: {message}")

    # --- row insertion -----------------------------------------------------

    def _category_iid(self, category):
        return f"cat:{category}"

    def _next_row_iid(self):
        self._row_counter += 1
        return f"row:{self._row_counter}"

    def _render_results(self, results):
        """
        Builds the whole table in one pass, grouped by CATEGORY_ORDER —
        called only once, after the scan is fully done, so there's no
        lazy-category-creation/reordering dance to do.
        """
        by_category = group_pairs_by_category(results, CATEGORY_ORDER)
        errors_by_category = group_pairs_by_category(self._pending_errors, CATEGORY_ORDER)

        for category in CATEGORY_ORDER:
            category_results = by_category[category]
            category_errors = errors_by_category[category]
            if not category_results and not category_errors:
                continue
            category_iid = self._category_iid(category)
            self.tree.insert("", "end", iid=category_iid, text=category, open=True, tags=("category",))
            for result in category_results:
                self._insert_result_row(category_iid, result)
            for message in category_errors:
                self._insert_error_row(category_iid, message)

    def _insert_result_row(self, category_iid, result):
        # update_line is the single source of truth for "this row has an
        # available update" (same field the CLI's "Updates available"
        # section keys off of) — checking it directly, rather than
        # matching a hardcoded set of status strings, means any future
        # check that sets update_line gets highlighted automatically
        if result.update_line:
            tags = ("update",)
        elif result.url:
            # any row with a link (not just updates) — e.g. an "Up to
            # date" BIOS row still linking to the vendor's support page
            tags = ("linked",)
        else:
            tags = ()

        iid = self._next_row_iid()
        self.tree.insert(
            category_iid, "end", iid=iid, text=result.device,
            values=(result.current, result.available, result.status), tags=tags,
        )
        self._rows[iid] = _RowInfo(tags, result.url)

    def _insert_error_row(self, category_iid, message):
        iid = self._next_row_iid()
        tags = ("error",)
        self.tree.insert(
            category_iid, "end", iid=iid, text="(error)",
            values=("—", "—", f"Error: {message}"), tags=tags,
        )
        self._rows[iid] = _RowInfo(tags, None)

    def _clear_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        self._row_counter = 0
        self._hovered_row = None

    # --- links -----------------------------------------------------------

    def _on_row_double_click(self, _event):
        selected = self.tree.selection()
        if not selected:
            return
        info = self._rows.get(selected[0])
        if info and info.url:
            webbrowser.open(info.url)

    def _on_tree_motion(self, event):
        row = self.tree.identify_row(event.y)
        if row == self._hovered_row:
            return
        self._clear_hover()
        # hover feedback only for actual "Download update" rows — a
        # "linked" row (e.g. an up-to-date BIOS with a reference link)
        # stays double-click-able, just without the hover highlight
        info = self._rows.get(row)
        if info and "update" in info.tags:
            self.tree.item(row, tags=info.tags + ("hover",))
            self.tree.config(cursor="hand2")
            self._hovered_row = row

    def _on_tree_leave(self, _event):
        self._clear_hover()

    def _clear_hover(self):
        if self._hovered_row and self.tree.exists(self._hovered_row):
            info = self._rows.get(self._hovered_row)
            self.tree.item(self._hovered_row, tags=info.tags if info else ())
        self.tree.config(cursor="")
        self._hovered_row = None

    def _set_drivers_link(self, url):
        self.drivers_link.config(state="normal")
        self.drivers_link.delete("1.0", "end")
        self._drivers_link_range = None
        if url:
            self.drivers_link.insert("end", "Page with all available drivers for this device: ")
            link_start = self.drivers_link.index("end-1c")
            self.drivers_link.insert("end", url, "link")
            link_end = self.drivers_link.index("end-1c")
            self._drivers_link_range = (link_start, link_end)
            self.drivers_link.tag_bind("link", "<Enter>", lambda e: self._on_drivers_link_enter())
            self.drivers_link.tag_bind("link", "<Leave>", lambda e: self._on_drivers_link_leave())
            self.drivers_link.tag_bind("link", "<Button-1>", lambda e: webbrowser.open(url))
        self.drivers_link.config(state="disabled")

    def _on_drivers_link_enter(self):
        if self._drivers_link_range:
            self.drivers_link.tag_add("hover", *self._drivers_link_range)
            self.drivers_link.config(cursor="hand2")

    def _on_drivers_link_leave(self):
        if self._drivers_link_range:
            self.drivers_link.tag_remove("hover", *self._drivers_link_range)
        self.drivers_link.config(cursor="arrow")

import queue
import re
import tkinter as tk
import webbrowser
from tkinter import ttk

from checks.common import overall_drivers_page_url
from checks.registry import CATEGORY_ORDER
from orchestrator import group_by_category
from gui import worker

_URL_RE = re.compile(r"https?://[^\s)]+")

WINDOW_TITLE = "VerifyDriver"
WINDOW_SIZE = "900x600"


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.geometry(WINDOW_SIZE)

        self.result_queue: queue.Queue | None = None
        self._link_counter = 0

        self._build_widgets()

    def run(self):
        self.root.mainloop()

    # --- widget construction ------------------------------------------

    def _build_widgets(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")

        self.scan_button = ttk.Button(top, text="Scan", command=self._start_scan)
        self.scan_button.pack(side="left")

        self.status_label = ttk.Label(top, text="Ready")
        self.status_label.pack(side="left", padx=10)

        self.progress = ttk.Progressbar(top, mode="indeterminate")
        self.progress.pack(side="left", fill="x", expand=True, padx=10)

        text_frame = ttk.Frame(self.root)
        text_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.text = tk.Text(text_frame, wrap="word", state="disabled", cursor="arrow")
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.tag_config("heading", font=("TkDefaultFont", 10, "bold"), spacing1=6, spacing3=2)
        self.text.tag_config("link", foreground="#1a73e8", underline=True)
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # --- scan lifecycle -------------------------------------------------

    def _start_scan(self):
        self.scan_button.config(state="disabled")
        self.status_label.config(text="Scanning...")
        self._clear_text()
        self._results_received = 0
        self.progress.start(10)

        self.result_queue = queue.Queue()
        worker.start_scan(self.result_queue)
        self.root.after(100, self._poll_queue)

    def _poll_queue(self):
        try:
            while True:
                msg = self.result_queue.get_nowait()
                tag = msg[0]
                if tag == worker.RESULT:
                    _, _category, display_line, _update_line = msg
                    self._results_received += 1
                    self._insert_line(display_line)
                    self.status_label.config(text=f"Scanning... ({self._results_received} results so far)")
                elif tag == worker.ERROR:
                    _, category, message = msg
                    self._insert_line(f"[{category}] error: {message}")
                elif tag == worker.DONE:
                    _, results, board, laptop = msg
                    self._finish_scan()
                    self._render_final_report(results, board, laptop)
                    return
                elif tag == worker.NO_INTERNET:
                    self._finish_scan()
                    self._clear_text()
                    self._insert_line(
                        "No internet connection — cannot check for updates. "
                        "Check your network and try again."
                    )
                    return
                elif tag == worker.FATAL:
                    _, message = msg
                    self._finish_scan()
                    self._insert_line(f"Unexpected error: {message}")
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _finish_scan(self):
        self.progress.stop()
        self.scan_button.config(state="normal")
        self.status_label.config(text="Done")

    # --- rendering --------------------------------------------------------

    def _render_final_report(self, results, board, laptop):
        display_by_category, updates_by_category = group_by_category(results, CATEGORY_ORDER)

        self._clear_text()
        for category in CATEGORY_ORDER:
            lines = display_by_category[category]
            if not lines:
                continue
            self._insert_heading(category)
            for line in lines:
                self._insert_line(line)

        any_updates = any(updates_by_category[category] for category in CATEGORY_ORDER)
        if any_updates:
            self._insert_heading("Updates available")
            for category in CATEGORY_ORDER:
                for line in updates_by_category[category]:
                    self._insert_line(line)
        else:
            self._insert_line("Everything is up to date (where a comparison was possible).")

        drivers_url = overall_drivers_page_url(board, laptop)
        if drivers_url:
            self._insert_line(f"Page with all available drivers for this device: {drivers_url}")

    # --- Text widget helpers -----------------------------------------------

    def _clear_text(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")

    def _insert_heading(self, title):
        self.text.config(state="normal")
        self.text.insert("end", title + "\n", "heading")
        self.text.config(state="disabled")

    def _insert_line(self, line):
        """Appends one line, turning any http(s) URL in it into a clickable link."""
        self.text.config(state="normal")
        pos = 0
        for match in _URL_RE.finditer(line):
            self.text.insert("end", line[pos:match.start()])
            self._insert_link(match.group(0))
            pos = match.end()
        self.text.insert("end", line[pos:] + "\n")
        self.text.config(state="disabled")
        self.text.see("end")

    def _insert_link(self, url):
        tag = f"link_{self._link_counter}"
        self._link_counter += 1
        self.text.insert("end", url, ("link", tag))
        self.text.tag_bind(tag, "<Enter>", lambda e: self.text.config(cursor="hand2"))
        self.text.tag_bind(tag, "<Leave>", lambda e: self.text.config(cursor="arrow"))
        self.text.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))

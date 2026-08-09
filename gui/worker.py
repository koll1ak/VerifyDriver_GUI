import queue
import threading

from net_utils import has_internet_connection
from scanner import get_installed_devices
from board_detect import detect_board
from laptop_detect import detect_laptop
from orchestrator import run_checks

# message tags put on the queue: (tag, *payload)
NO_INTERNET = "no_internet"
ERROR = "error"          # (category, message)
DONE = "done"             # (results, board, laptop)
FATAL = "fatal"            # (message,)


def start_scan(result_queue: queue.Queue) -> threading.Thread:
    """
    Runs a full scan on a background thread — Tkinter widgets aren't
    thread-safe, so the scan (network-bound, ~35 checks) must never run
    on the Tk main thread. Progress is reported by pushing tagged
    messages onto result_queue; the caller polls it from the main thread
    (e.g. via root.after()).
    """
    def _run():
        try:
            if not has_internet_connection():
                result_queue.put((NO_INTERNET,))
                return

            devices = get_installed_devices()
            board = detect_board()
            laptop = detect_laptop()
            results = run_checks(
                devices, board, laptop,
                on_error=lambda cat, msg: result_queue.put((ERROR, cat, msg)),
            )
            result_queue.put((DONE, results, board, laptop))
        except Exception as e:
            result_queue.put((FATAL, str(e)))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread

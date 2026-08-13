"""
Downloads, unpacks, and installs a driver .cab from a direct URL (as
resolved by providers/ms_catalog.py's _resolve_download_url) via
Windows' built-in expand.exe and pnputil.exe.

Mirrors gui/worker.py's background-thread-plus-queue pattern so the GUI
polls install progress the same way it already polls scan progress.
"""

import os
import shutil
import subprocess
import tempfile
import threading
import queue

import requests

# message tags put on the queue: (tag, *payload)
DOWNLOADING = "downloading"
INSTALLING = "installing"
DONE = "done"
DONE_REBOOT_REQUIRED = "done_reboot_required"
ERROR = "error"          # (message,)

# pnputil's documented exit code for "succeeded, but a reboot is needed
# to finish applying the driver"
_PNPUTIL_REBOOT_REQUIRED_EXIT_CODE = 3010

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _download(url: str, dest_dir: str) -> str:
    cab_path = os.path.join(dest_dir, "driver.cab")
    resp = requests.get(url, stream=True, timeout=60)
    resp.raise_for_status()
    with open(cab_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
    return cab_path


def _unpack(cab_path: str, dest_dir: str) -> None:
    result = subprocess.run(
        ["expand.exe", "-F:*", cab_path, dest_dir],
        capture_output=True, text=True, creationflags=_NO_WINDOW,
    )
    if result.returncode != 0:
        reason = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"unpacking the driver package failed: {reason}")


def _install(dest_dir: str) -> int:
    """Runs pnputil against every .inf unpacked into dest_dir. Returns
    pnputil's exit code (0 = installed, 3010 = installed, reboot needed)."""
    inf_pattern = os.path.join(dest_dir, "*.inf")
    result = subprocess.run(
        ["pnputil.exe", "/add-driver", inf_pattern, "/subdirs", "/install"],
        capture_output=True, text=True, creationflags=_NO_WINDOW,
    )
    if result.returncode not in (0, _PNPUTIL_REBOOT_REQUIRED_EXIT_CODE):
        reason = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"pnputil failed: {reason}")
    return result.returncode


def _run_pipeline(url: str, result_queue: queue.Queue) -> None:
    """The actual download->unpack->install sequence, synchronous — a
    separate function from start_install so tests can call it directly
    without a real background thread."""
    dest_dir = tempfile.mkdtemp(prefix="verifydriver_install_")
    try:
        result_queue.put((DOWNLOADING,))
        cab_path = _download(url, dest_dir)

        result_queue.put((INSTALLING,))
        _unpack(cab_path, dest_dir)
        exit_code = _install(dest_dir)

        if exit_code == _PNPUTIL_REBOOT_REQUIRED_EXIT_CODE:
            result_queue.put((DONE_REBOOT_REQUIRED,))
        else:
            result_queue.put((DONE,))
    except Exception as e:
        result_queue.put((ERROR, str(e)))
    finally:
        shutil.rmtree(dest_dir, ignore_errors=True)


def start_install(url: str, result_queue: queue.Queue) -> threading.Thread:
    """Runs _run_pipeline on a background thread — Tkinter widgets
    aren't thread-safe, and downloading+installing a driver can take
    several seconds, so this must never run on the Tk main thread."""
    thread = threading.Thread(target=_run_pipeline, args=(url, result_queue), daemon=True)
    thread.start()
    return thread

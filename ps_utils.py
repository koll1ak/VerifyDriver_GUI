import subprocess


def run_powershell(command: str) -> subprocess.CompletedProcess:
    """
    Shared helper for every "powershell -Command <...>" call in this
    project. creationflags=CREATE_NO_WINDOW matters once this runs inside
    a windowed (no-console) build: capture_output alone only redirects
    the pipes, it doesn't stop Windows from popping up a console for the
    child process when the parent has none.
    """
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        # CREATE_NO_WINDOW only exists on Windows -- getattr'd with a 0
        # (no-op) fallback so callers that catch OSError for "not on
        # Windows" (e.g. laptop_detect.py) still see that, not an
        # unrelated AttributeError from this flag itself
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

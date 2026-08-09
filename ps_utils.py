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
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

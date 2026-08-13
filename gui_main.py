import sys
import os
import ctypes

# In a windowed build (no console attached — how the packaged .exe runs),
# sys.stdout/sys.stderr are None, same as under pythonw.exe. Several
# checks/providers modules print diagnostics to stderr on error; without
# this guard, print(..., file=None) raises AttributeError from inside
# their own except blocks, which can kill a scan on the first vendor
# error instead of just skipping that one check. Must run before any
# other import, since those modules read sys.stderr at call time.
if sys.stdout is None or sys.stderr is None:
    log_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.getcwd()), "VerifyDriver")
    os.makedirs(log_dir, exist_ok=True)
    log_file = open(os.path.join(log_dir, "verifydriver.log"), "a", encoding="utf-8", errors="replace")
    sys.stdout = sys.stderr = log_file

from gui.app import App


def _is_elevated() -> bool:
    """Whether this process already holds admin rights. Installing a
    driver via pnputil requires them, so the whole app runs elevated
    rather than prompting again at install time."""
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def _relaunch_elevated() -> bool:
    """Re-launches this same process with a UAC prompt. Works both as
    `python gui_main.py` (dev, see the no-rebuild-every-change
    convention) and as the packaged Nuitka onefile exe -- Nuitka injects
    __compiled__ as a module global at compile time, which is how the
    two cases are told apart.

    Returns True if the relaunch succeeded, False if the user declined
    the UAC prompt or another error occurred."""
    if "__compiled__" in globals():
        executable = sys.executable
        args = sys.argv[1:]
    else:
        executable = sys.executable
        args = [os.path.abspath(__file__)] + sys.argv[1:]
    params = " ".join(f'"{a}"' for a in args)
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, params, None, 1)
    return result > 32


def main():
    if not _is_elevated():
        if not _relaunch_elevated():
            ctypes.windll.user32.MessageBoxW(None, "VerifyDriver needs administrator rights to install drivers. Please run it again and accept the UAC prompt.", "Administrator rights required", 0x10)
        return
    App().run()


if __name__ == "__main__":
    main()

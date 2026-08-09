import sys
import os

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


def main():
    App().run()


if __name__ == "__main__":
    main()

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gui_main


class IsElevatedTests(unittest.TestCase):
    @patch("gui_main.ctypes.windll.shell32.IsUserAnAdmin", return_value=1, create=True)
    def test_true_when_windows_reports_admin(self, _mock_is_admin):
        self.assertTrue(gui_main._is_elevated())

    @patch("gui_main.ctypes.windll.shell32.IsUserAnAdmin", return_value=0, create=True)
    def test_false_when_windows_reports_not_admin(self, _mock_is_admin):
        self.assertFalse(gui_main._is_elevated())


class RelaunchElevatedTests(unittest.TestCase):
    @patch("gui_main.ctypes.windll.shell32.ShellExecuteW", create=True)
    @patch("gui_main.sys")
    def test_dev_run_relaunches_python_with_script_path(self, mock_sys, mock_shell_execute):
        # not compiled by Nuitka -- __compiled__ isn't in gui_main's globals
        gui_main.__dict__.pop("__compiled__", None)
        mock_sys.executable = "C:\\Python312\\python.exe"
        mock_sys.argv = ["gui_main.py", "--flag"]
        mock_shell_execute.return_value = 42  # Success: > 32

        result = gui_main._relaunch_elevated()

        args, _kwargs = mock_shell_execute.call_args
        self.assertEqual(args[1], "runas")
        self.assertEqual(args[2], "C:\\Python312\\python.exe")
        self.assertIn(os.path.abspath(gui_main.__file__), args[3])
        self.assertIn("--flag", args[3])
        self.assertTrue(result)

    @patch("gui_main.ctypes.windll.shell32.ShellExecuteW", create=True)
    def test_compiled_exe_relaunches_itself_directly(self, mock_shell_execute):
        # simulates a Nuitka onefile build, which injects __compiled__
        # as a module global at compile time
        gui_main.__dict__["__compiled__"] = True
        try:
            with patch("gui_main.sys") as mock_sys:
                mock_sys.executable = "C:\\VerifyDriver\\gui_main.exe"
                mock_sys.argv = ["gui_main.exe"]
                mock_shell_execute.return_value = 42  # Success: > 32

                result = gui_main._relaunch_elevated()

            args, _kwargs = mock_shell_execute.call_args
            self.assertEqual(args[2], "C:\\VerifyDriver\\gui_main.exe")
            self.assertEqual(args[3], "")  # no extra argv beyond argv[0]
            self.assertTrue(result)
        finally:
            del gui_main.__dict__["__compiled__"]

    @patch("gui_main.ctypes.windll.shell32.ShellExecuteW", return_value=5, create=True)
    @patch("gui_main.sys")
    def test_returns_false_when_relaunch_fails(self, mock_sys, mock_shell_execute):
        # ShellExecuteW returns 5 (access denied), which is <= 32
        gui_main.__dict__.pop("__compiled__", None)
        mock_sys.executable = "C:\\Python312\\python.exe"
        mock_sys.argv = ["gui_main.py"]

        result = gui_main._relaunch_elevated()

        self.assertFalse(result)


class MainTests(unittest.TestCase):
    @patch("gui_main.App")
    @patch("gui_main._relaunch_elevated", return_value=True)
    @patch("gui_main._is_elevated", return_value=False)
    def test_relaunches_and_does_not_build_app_when_not_elevated(
        self, _mock_is_elevated, mock_relaunch, mock_app_cls,
    ):
        gui_main.main()

        mock_relaunch.assert_called_once()
        mock_app_cls.assert_not_called()

    @patch("gui_main.ctypes.windll.user32.MessageBoxW", create=True)
    @patch("gui_main.App")
    @patch("gui_main._relaunch_elevated", return_value=False)
    @patch("gui_main._is_elevated", return_value=False)
    def test_shows_error_and_does_not_build_app_when_relaunch_fails(
        self, _mock_is_elevated, mock_relaunch, mock_app_cls, mock_msgbox,
    ):
        gui_main.main()

        mock_relaunch.assert_called_once()
        mock_msgbox.assert_called_once()
        mock_app_cls.assert_not_called()

    @patch("gui_main.App")
    @patch("gui_main._relaunch_elevated")
    @patch("gui_main._is_elevated", return_value=True)
    def test_builds_and_runs_app_when_already_elevated(
        self, _mock_is_elevated, mock_relaunch, mock_app_cls,
    ):
        gui_main.main()

        mock_relaunch.assert_not_called()
        mock_app_cls.return_value.run.assert_called_once()


if __name__ == "__main__":
    unittest.main()

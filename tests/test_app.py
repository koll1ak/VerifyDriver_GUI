import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gui.app import _fit_text, _open_in_browser


class FitTextTests(unittest.TestCase):
    def test_text_that_already_fits_is_returned_unchanged(self):
        self.assertEqual(_fit_text("Status", 10, len), "Status")

    def test_first_cut_removes_two_characters(self):
        # "Driver Class" (12 chars) doesn't fit in 10: the algorithm cuts
        # 2 chars first ("Driver Cla" + "..." = 13, still too wide), then
        # 1 at a time until "Driver " + "..." (10 chars) fits exactly.
        self.assertEqual(_fit_text("Driver Class", 10, len), "Driver ...")

    def test_always_cuts_two_first_even_if_one_would_have_fit(self):
        # "Status" (6 chars) doesn't fit in 5. Cutting only 1 char would
        # give "Statu..." (8 chars, still too wide) -- 2 chars first,
        # then 1 more, lands on "Sta..." (6 chars > 5)... continue to
        # "St..." (5 chars), which fits.
        self.assertEqual(_fit_text("Status", 5, len), "St...")

    def test_impossible_width_collapses_to_bare_ellipsis(self):
        self.assertEqual(_fit_text("Hello", 0, len), "...")

    def test_first_cut_removes_two_characters_not_one(self):
        # A real font makes "..." far narrower than three letters, which is
        # the only regime where "cut 2 first" differs from "cut 1 at a
        # time" -- len-based measures can't distinguish the two algorithms
        # (a period costs the same as a letter under len), so this uses a
        # measure where "." is cheap and letters are expensive.
        proportional = lambda s: sum(1 if c == "." else 10 for c in s)
        # "Statu..." (53) would fit under a naive 1-char-at-a-time cut, but
        # the first cut always removes 2, landing on "Stat..." instead.
        self.assertEqual(_fit_text("Status", 53, proportional), "Stat...")


class OpenInBrowserTests(unittest.TestCase):
    """
    The whole app runs elevated (see gui_main.main()) so that pnputil
    never needs its own UAC prompt -- but a direct webbrowser.open() (or
    ShellExecuteW) call would then launch a not-yet-running browser at
    admin integrity too. _open_in_browser instead routes through
    explorer.exe's own running COM server (ShellWindows -> Document
    .Application.ShellExecute), which re-launches the browser at normal
    (non-elevated) integrity even though this process is elevated. This
    is an OS shell launch, not meaningfully unit-testable beyond
    asserting the right COM call gets made -- actually launching a
    browser isn't attempted here.

    A prior version shelled out to "explorer.exe <url>" directly --
    confirmed live on Windows 11 build 10.0.26200 that this no longer
    launches anything, it just opens a new File Explorer window at the
    default library location instead (reported as "Download update"
    redirecting to the home folder).
    """

    @patch("gui.app.win32com.client.Dispatch")
    def test_shell_executes_url_through_desktops_com_server(self, mock_dispatch):
        mock_app = Mock()
        mock_dispatch.return_value.Item.return_value.Document.Application = mock_app

        _open_in_browser("https://example.com/some/page")

        mock_dispatch.assert_called_once_with("{9BA05972-F6A8-11CF-A442-00A0C90A8F39}")
        mock_app.ShellExecute.assert_called_once_with("https://example.com/some/page", "", "", "open", 1)


if __name__ == "__main__":
    unittest.main()

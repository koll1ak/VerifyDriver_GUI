import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gui.app import _fit_text


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


if __name__ == "__main__":
    unittest.main()

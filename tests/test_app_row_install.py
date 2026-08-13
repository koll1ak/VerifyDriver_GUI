import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checks.common import CheckResult, report, no_downgrade_match
from gui.app import _is_cab_installable, _display_status_text


def _result(status, url):
    return CheckResult(
        device="Test Device", current="1.0", available="2.0", status=status,
        url=url, display_line="", update_line=None,
    )


class IsCabInstallableTests(unittest.TestCase):
    def test_true_for_download_update_status_with_cab_url(self):
        result = _result("Download update", "https://catalog.s.download.windowsupdate.com/x/y/driver.cab")
        self.assertTrue(_is_cab_installable(result))

    def test_false_for_up_to_date_even_with_cab_url(self):
        # up-to-date rows link to the same .cab for reference only, not for action
        result = _result("Up to date", "https://catalog.s.download.windowsupdate.com/x/y/driver.cab")
        self.assertFalse(_is_cab_installable(result))

    def test_false_for_non_cab_url(self):
        result = _result("Download update", "https://www.realtek.com/Download/ToDownload?type=direct&downloadid=1")
        self.assertFalse(_is_cab_installable(result))

    def test_false_for_ms_catalog_search_page_fallback_url(self):
        # when _resolve_download_url fails, ms_catalog.py falls back to
        # the search page -- not a direct .cab, must not offer install
        result = _result("Download update", "https://www.catalog.update.microsoft.com/Search.aspx?q=Qualcomm")
        self.assertFalse(_is_cab_installable(result))

    def test_false_for_no_url(self):
        result = _result("Download update", None)
        self.assertFalse(_is_cab_installable(result))

    def test_case_insensitive_extension_match(self):
        result = _result("Download update", "https://example.com/driver.CAB")
        self.assertTrue(_is_cab_installable(result))


class RealMsCatalogReportIntegrationTests(unittest.TestCase):
    """
    Pins the real end-to-end binding _is_cab_installable relies on: it
    only works because report()'s "Download update" status text matches
    gui/app.py's DOWNLOAD_UPDATE_STATUS constant, and because
    providers/ms_catalog.py's result dict has no "page_url" key so
    report() falls through to "url" (the resolved .cab link). Goes
    through the real checks.common.report() producer instead of
    hand-building a CheckResult, so a rename of the status string or a
    future "page_url" addition to the MS Catalog provider's result dict
    would fail this test instead of silently breaking every row.
    """

    def test_ms_catalog_style_result_is_cab_installable(self):
        # shaped exactly like providers/ms_catalog.py's
        # MsCatalogProvider.get_latest() return value: "version" and
        # "url" keys, url ending in ".cab", deliberately no "page_url"
        latest = {
            "version": "22.130.0.1",
            "url": "https://catalog.s.download.windowsupdate.com/c/msdownload/update/driver/drvs/x/y.cab",
            "date": "07/30/2026",
            "title": "Qualcomm Atheros Communications - Bluetooth - 22.130.0.1",
        }
        result = report(
            "Qualcomm Bluetooth", latest, current="21.0.0.1", comparator=no_downgrade_match,
        )

        self.assertEqual(result.status, "Download update")
        self.assertEqual(result.url, latest["url"])
        self.assertTrue(_is_cab_installable(result))


class DisplayStatusTextTests(unittest.TestCase):
    def test_installable_row_gets_relabeled(self):
        result = _result("Download update", "https://example.com/driver.cab")
        self.assertEqual(_display_status_text(result, True), "Download and install update")

    def test_non_installable_row_keeps_original_status(self):
        result = _result("Up to date", "https://example.com/page")
        self.assertEqual(_display_status_text(result, False), "Up to date")


if __name__ == "__main__":
    unittest.main()

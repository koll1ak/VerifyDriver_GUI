import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from providers.ms_catalog import CatalogPageUnexpected, MsCatalogProvider


def _catalog_html(rows: str) -> str:
    return f'<table id="ctl00_catalogBody_updateMatches">{rows}</table>'


def _no_results_html(query: str) -> str:
    return (
        f'<span id="ctl00_catalogBody_noResultText">We did not find any results for </span>'
        f'<span id="ctl00_catalogBody_searchString">"{query}"</span>'
    )


def _row(row_id: str, title: str, date: str, version: str) -> str:
    cells = "".join(f"<td>{c}</td>" for c in ("", title, "", "", date, version, "", ""))
    return f'<tr id="{row_id}">{cells}</tr>'


class VersionFromTitleTests(unittest.TestCase):
    def test_extracts_trailing_dotted_version(self):
        self.assertEqual(
            MsCatalogProvider._version_from_title("Qualcomm Atheros Communications - Bluetooth - 10.0.0.1272"),
            "10.0.0.1272",
        )

    def test_extracts_trailing_dotted_version_from_wifi_title(self):
        # real case: Killer/Qualcomm WiFi adapters (e.g. Killer 1535)
        self.assertEqual(
            MsCatalogProvider._version_from_title("Qualcomm Atheros Communications Inc. - Net - 12.0.0.1272"),
            "12.0.0.1272",
        )

    def test_no_trailing_version_returns_none(self):
        # real case: legacy Realtek catalog entries with no version anywhere
        self.assertIsNone(
            MsCatalogProvider._version_from_title(
                "Realtek Semiconductor Corp. driver update for Realtek High Definition Audio"
            )
        )


class GetLatestVersionColumnFallbackTests(unittest.TestCase):
    # Some catalog entries (confirmed live: Qualcomm Atheros Bluetooth) show
    # the literal placeholder "n/a" in the dedicated version column even
    # though they have a real version -- embedded in the title instead.
    # get_latest must recover it there rather than discarding the row.

    def _mock_response(self, html: str):
        resp = Mock()
        resp.text = html
        resp.raise_for_status = Mock()
        return resp

    @patch("providers.ms_catalog._resolve_download_url", return_value=None)
    @patch("providers.ms_catalog.requests.get")
    def test_recovers_version_from_title_when_column_is_na(self, mock_get, _mock_resolve):
        html = _catalog_html(
            _row("guid1_R0", "Qualcomm Atheros Communications - Bluetooth - 10.0.0.1272", "3/4/2023", "n/a")
        )
        mock_get.return_value = self._mock_response(html)

        result = MsCatalogProvider(query="Qualcomm Atheros QCA61x4 Bluetooth").get_latest()

        self.assertIsNotNone(result)
        self.assertEqual(result["version"], "10.0.0.1272")

    @patch("providers.ms_catalog._resolve_download_url", return_value=None)
    @patch("providers.ms_catalog.requests.get")
    def test_still_skips_rows_with_no_recoverable_version(self, mock_get, _mock_resolve):
        html = _catalog_html(
            _row(
                "guid2_R0",
                "Realtek Semiconductor Corp. driver update for Realtek High Definition Audio",
                "11/7/2016",
                "n/a",
            )
        )
        mock_get.return_value = self._mock_response(html)

        result = MsCatalogProvider(query="Realtek High Definition Audio").get_latest()

        self.assertIsNone(result)


class TitleContainsTupleFilterTests(unittest.TestCase):
    # a vendor-only resolved device name (see checks/network.py's
    # check_bluetooth_via_windows_update/check_wifi_via_windows_update)
    # can match unrelated catalog rows from the same vendor's other
    # product categories -- title_contains narrows the free-text search
    # result down to the right category. Different vendors use different
    # category words for the same kind of device (confirmed live: WiFi
    # entries say "Net" for most vendors but "WLAN" for Ralink), so
    # title_contains must accept multiple alternative substrings.

    def _mock_response(self, html: str):
        resp = Mock()
        resp.text = html
        resp.raise_for_status = Mock()
        return resp

    @patch("providers.ms_catalog._resolve_download_url", return_value=None)
    @patch("providers.ms_catalog.requests.get")
    def test_tuple_matches_row_containing_any_substring(self, mock_get, _mock_resolve):
        html = _catalog_html(
            _row("guid1_R0", "Ralink Technology, Corp. - WLAN - Ralink 802.11n Wireless LAN Card", "3/4/2023", "1.2.3.4")
        )
        mock_get.return_value = self._mock_response(html)

        result = MsCatalogProvider(query="Ralink Wireless", title_contains=("Net", "WLAN")).get_latest()

        self.assertIsNotNone(result)
        self.assertEqual(result["version"], "1.2.3.4")

    @patch("providers.ms_catalog._resolve_download_url", return_value=None)
    @patch("providers.ms_catalog.requests.get")
    def test_tuple_excludes_row_containing_none_of_the_substrings(self, mock_get, _mock_resolve):
        html = _catalog_html(
            _row(
                "guid2_R0",
                "Qualcomm Atheros Communications Inc. - System - 1.0.0.1769",
                "3/4/2023",
                "1.0.0.1769",
            )
        )
        mock_get.return_value = self._mock_response(html)

        result = MsCatalogProvider(query="Qualcomm Atheros Communications", title_contains=("Net", "WLAN")).get_latest()

        self.assertIsNone(result)

    @patch("providers.ms_catalog._resolve_download_url", return_value=None)
    @patch("providers.ms_catalog.requests.get")
    def test_tuple_filter_is_case_insensitive(self, mock_get, _mock_resolve):
        html = _catalog_html(
            _row("guid3_R0", "Qualcomm Atheros Communications - bluetooth - 10.0.0.1272", "3/4/2023", "10.0.0.1272")
        )
        mock_get.return_value = self._mock_response(html)

        result = MsCatalogProvider(query="Qualcomm Atheros Bluetooth", title_contains="Bluetooth").get_latest()

        self.assertIsNotNone(result)


class UnexpectedPageTests(unittest.TestCase):
    # A response can come back 200 OK with neither a results table NOR
    # the site's own "no results" confirmation -- e.g. a maintenance page
    # or bot-check interstitial. That must NOT be treated the same as a
    # confirmed empty result (see CatalogPageUnexpected's docstring).

    def _mock_response(self, html: str):
        resp = Mock()
        resp.text = html
        resp.raise_for_status = Mock()
        return resp

    @patch("providers.ms_catalog.requests.get")
    def test_confirmed_no_results_returns_none(self, mock_get):
        mock_get.return_value = self._mock_response(_no_results_html("Qualcomm QCA6174"))

        result = MsCatalogProvider(query="Qualcomm QCA6174").get_latest()

        self.assertIsNone(result)

    @patch("providers.ms_catalog.requests.get")
    def test_missing_table_and_no_confirmation_raises(self, mock_get):
        mock_get.return_value = self._mock_response("<html><body>Site Maintenance</body></html>")

        with self.assertRaises(CatalogPageUnexpected):
            MsCatalogProvider(query="Realtek High Definition Audio").get_latest()


class RetryOnTimeoutTests(unittest.TestCase):
    # catalog.update.microsoft.com is confirmed live to be intermittently
    # slow enough to time out even while otherwise up -- a lone timeout
    # must not be reported as a failed check when a retry would succeed.

    def _mock_response(self, html: str):
        resp = Mock()
        resp.text = html
        resp.raise_for_status = Mock()
        return resp

    @patch("providers.ms_catalog.time.sleep")
    @patch("providers.ms_catalog._resolve_download_url", return_value=None)
    @patch("providers.ms_catalog.requests.get")
    def test_recovers_after_one_timeout(self, mock_get, _mock_resolve, _mock_sleep):
        html = _catalog_html(_row("guid1_R0", "Qualcomm Atheros Communications - Bluetooth - 10.0.0.1272", "3/4/2023", "n/a"))
        mock_get.side_effect = [requests.Timeout("timed out"), self._mock_response(html)]

        result = MsCatalogProvider(query="Qualcomm Atheros QCA61x4 Bluetooth").get_latest()

        self.assertIsNotNone(result)
        self.assertEqual(result["version"], "10.0.0.1272")
        self.assertEqual(mock_get.call_count, 2)

    @patch("providers.ms_catalog.time.sleep")
    @patch("providers.ms_catalog.requests.get")
    def test_gives_up_after_exhausting_retries(self, mock_get, _mock_sleep):
        mock_get.side_effect = requests.Timeout("timed out")

        with self.assertRaises(requests.Timeout):
            MsCatalogProvider(query="Qualcomm QCA6174").get_latest()

        self.assertEqual(mock_get.call_count, 3)


if __name__ == "__main__":
    unittest.main()

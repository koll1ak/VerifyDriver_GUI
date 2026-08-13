import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from providers.ms_catalog import MsCatalogProvider


def _catalog_html(rows: str) -> str:
    return f'<table id="ctl00_catalogBody_updateMatches">{rows}</table>'


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


if __name__ == "__main__":
    unittest.main()

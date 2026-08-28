import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from providers.intel_download import IntelDownloadCenterProvider


def _page_html(download_version: str, date: str = "08/25/2026 00:00:00") -> str:
    return (
        "<html><head>"
        f'<meta name="DownloadVersion" content="{download_version}">'
        f'<meta name="lastModifieddate" content="{date}">'
        "</head><body></body></html>"
    )


class IntelDownloadCenterVersionParsingTests(unittest.TestCase):
    def _mock_session(self, html: str):
        resp = Mock()
        resp.text = html
        resp.raise_for_status = Mock()
        session = Mock()
        session.get.return_value = resp
        return session

    @patch("providers.intel_download.requests.Session")
    def test_strips_whql_certified_suffix_from_arc_gpu_page(self, mock_session_cls):
        # confirmed live on download ID 785597 (Intel Arc & Iris Xe Graphics):
        # DownloadVersion now reads "32.0.101.8991 WHQL Certified" instead of
        # a bare version -- comparing this raw string against the installed
        # "32.0.101.8991" always looks like an update, even when identical.
        mock_session_cls.return_value = self._mock_session(_page_html("32.0.101.8991 WHQL Certified"))

        result = IntelDownloadCenterProvider(download_id="785597", slug="intel-arc-graphics-windows").get_latest()

        self.assertEqual(result["version"], "32.0.101.8991")

    @patch("providers.intel_download.requests.Session")
    def test_bare_version_unaffected(self, mock_session_cls):
        # other Intel download-center pages (chipset, LAN, WiFi, NPU) still
        # serve a bare version -- must not be altered by the fix
        mock_session_cls.return_value = self._mock_session(_page_html("10.1.20658.8883"))

        result = IntelDownloadCenterProvider(download_id="19347", slug="chipset-inf-utility").get_latest()

        self.assertEqual(result["version"], "10.1.20658.8883")


if __name__ == "__main__":
    unittest.main()

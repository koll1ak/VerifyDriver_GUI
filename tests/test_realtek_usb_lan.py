import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checks.network import check_realtek_usb_lan

DEVICE_NAME = "Realtek USB GbE Family Controller"


def _device(driver_version, driver_date=None):
    return {
        "VendorID": "0BDA",
        "DeviceID": r"USB\VID_0BDA&PID_8153\0133000001",
        "DeviceName": DEVICE_NAME,
        "DriverVersion": driver_version,
        "DriverDate": driver_date,
    }


class RealtekUsbLanVariantDetectionTests(unittest.TestCase):
    # confirmed live on a real device: installed "1156.10.20.1104" is the
    # NetAdapterCx family, matching the site's "115X.22.20" entry (site
    # uses "X" as a literal placeholder for the chip-specific digit) --
    # NOT the PCIe product-code+year format detect_realtek_lan_variant
    # expects, which would misclassify this as "unknown".

    @patch("checks.network.RealtekUsbLanProvider.get_latest")
    def test_netadaptercx_style_version_shows_current_and_finds_update(self, mock_get_latest):
        mock_get_latest.return_value = {
            "version": "115X.22.20", "date": "2026/06/23", "url": "https://example.com/netadaptercx.zip",
        }
        result = check_realtek_usb_lan([_device("1156.10.20.1104")], board=None, laptop=None)

        self.assertEqual(result.current, "1156.10.20.1104")
        self.assertEqual(result.status, "Download update")
        self.assertEqual(result.available, "115X.22.20 (2026-06-23)")

    @patch("checks.network.RealtekUsbLanProvider.get_latest")
    def test_netadaptercx_style_up_to_date(self, mock_get_latest):
        mock_get_latest.return_value = {
            "version": "115X.10.20", "date": "2022/11/05", "url": "https://example.com/netadaptercx.zip",
        }
        result = check_realtek_usb_lan([_device("1156.10.20.1104")], board=None, laptop=None)

        # same version on both sides -- report() borrows the site's date
        # for "current" too, since no current_date was supplied here
        self.assertEqual(result.current, "1156.10.20.1104 (2022-11-05)")
        self.assertEqual(result.status, "Up to date")

    @patch("checks.network.RealtekUsbLanProvider.get_latest")
    def test_ndis_style_version_still_compares(self, mock_get_latest):
        mock_get_latest.return_value = {
            "version": "10.67.20", "date": "2026/06/23", "url": "https://example.com/ndis.zip",
        }
        result = check_realtek_usb_lan([_device("10.67.20.407")], board=None, laptop=None)

        self.assertEqual(result.current, "10.67.20.407 (2026-06-23)")
        self.assertEqual(result.status, "Up to date")
        self.assertEqual(result.available, "10.67.20 (2026-06-23)")

    @patch("checks.network.RealtekUsbLanProvider.get_latest")
    def test_unrecognized_format_falls_back_to_no_comparison(self, mock_get_latest):
        # e.g. a legacy 3-segment version -- can't be confidently classified
        # as either variant, must not risk a false "update available"
        mock_get_latest.return_value = {
            "version": "2.0.8.3", "date": "2026/07/16", "url": "https://example.com/diagnostic.zip",
        }
        result = check_realtek_usb_lan([_device("5.23.0")], board=None, laptop=None)

        self.assertEqual(result.current, "—")  # no automatic comparison, unlike current=None being wired up wrong
        self.assertEqual(result.status, "Found (no comparison)")

    def test_no_matching_device_returns_none(self):
        result = check_realtek_usb_lan([{"VendorID": "8086", "DeviceName": "Intel WiFi"}], board=None, laptop=None)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

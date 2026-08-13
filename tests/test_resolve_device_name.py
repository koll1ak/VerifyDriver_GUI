import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checks.common import resolve_device_name

# the exact placeholder date Windows' generic/inbox drivers hardcode,
# in WMI's raw CIM_DATETIME format
GENERIC_DATE = "20060621000000.000000-000"
REAL_DATE = "20230305000000.000000-000"


def _device(device_id, device_name, driver_date, vendor_id=None, product_id=None):
    return {
        "DeviceID": device_id,
        "DeviceName": device_name,
        "DriverDate": driver_date,
        "VendorID": vendor_id,
        "DeviceID_PCI": product_id,
    }


class ResolveDeviceNameTests(unittest.TestCase):
    def test_non_generic_date_returns_original_name_unchanged(self):
        device = _device("USB\\VID_0489&PID_E10A", "Qualcomm FastConnect 7800", REAL_DATE, "0489", "E10A")
        self.assertEqual(resolve_device_name(device), "Qualcomm FastConnect 7800")

    @patch("checks.common.hardware_ids.lookup", return_value=("Foxconn / Hon Hai", "FastConnect 7800 Bluetooth"))
    def test_generic_date_with_full_match_returns_product_name(self, mock_lookup):
        device = _device("USB\\VID_0489&PID_E10A", "Generic Bluetooth Adapter", GENERIC_DATE, "0489", "E10A")
        self.assertEqual(resolve_device_name(device), "FastConnect 7800 Bluetooth")
        mock_lookup.assert_called_once_with("usb", "0489", "E10A")

    @patch("checks.common.hardware_ids.lookup", return_value=("Foxconn / Hon Hai", None))
    def test_generic_date_vendor_only_match_returns_vendor_name(self, _mock_lookup):
        device = _device("USB\\VID_0489&PID_E10A", "Generic Bluetooth Adapter", GENERIC_DATE, "0489", "E10A")
        self.assertEqual(resolve_device_name(device), "Foxconn / Hon Hai")

    @patch("checks.common.hardware_ids.lookup", return_value=(None, None))
    def test_generic_date_no_match_returns_original_name_unchanged(self, _mock_lookup):
        device = _device("USB\\VID_FFFF&PID_FFFF", "Generic Bluetooth Adapter", GENERIC_DATE, "FFFF", "FFFF")
        self.assertEqual(resolve_device_name(device), "Generic Bluetooth Adapter")

    @patch("checks.common.hardware_ids.lookup", return_value=("Realtek Semiconductor Co., Ltd.", "RTL-8139"))
    def test_pci_device_id_uses_pci_namespace(self, mock_lookup):
        device = _device("PCI\\VEN_10EC&DEV_8139", "Generic Network Adapter", GENERIC_DATE, "10EC", "8139")
        resolve_device_name(device)
        mock_lookup.assert_called_once_with("pci", "10EC", "8139")

    @patch("checks.common.hardware_ids.lookup", return_value=("Realtek Semiconductor Co., Ltd.", None))
    def test_hdaudio_device_id_uses_pci_namespace(self, mock_lookup):
        # HD Audio codec vendor IDs are drawn from the PCI-SIG vendor ID
        # space, not USB's
        device = _device("HDAUDIO\\FUNC_01&VEN_10EC&DEV_0899", "Generic Audio Device", GENERIC_DATE, "10EC", "0899")
        resolve_device_name(device)
        mock_lookup.assert_called_once_with("pci", "10EC", "0899")

    @patch("checks.common.hardware_ids.lookup", return_value=("Foxconn / Hon Hai", "FastConnect 7800 Bluetooth"))
    def test_usb_device_id_uses_usb_namespace(self, mock_lookup):
        device = _device("USB\\VID_0489&PID_E10A", "Generic Bluetooth Adapter", GENERIC_DATE, "0489", "E10A")
        resolve_device_name(device)
        mock_lookup.assert_called_once_with("usb", "0489", "E10A")

    def test_missing_device_name_does_not_crash(self):
        device = _device("USB\\VID_FFFF&PID_FFFF", None, REAL_DATE, "FFFF", "FFFF")
        self.assertEqual(resolve_device_name(device), "")


if __name__ == "__main__":
    unittest.main()

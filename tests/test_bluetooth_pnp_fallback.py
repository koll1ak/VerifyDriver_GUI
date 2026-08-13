import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checks.network import check_intel_bluetooth, check_bluetooth_via_windows_update

REAL_DATE = "20250101000000.000000-000"


class BluetoothGetPnpDeviceFallbackTests(unittest.TestCase):
    # A composite USB Bluetooth adapter's Bluetooth sub-function can be
    # invisible to Win32_PnPSignedDriver the same way composite USB audio
    # codecs are (see checks/audio.py's _find_audio_device) -- but
    # Bluetooth chips come from many vendors (Qualcomm, MediaTek,
    # Broadcom, ...), so there's no single fixed VID to search for the
    # way Realtek's audio fallback does. The fallback here is keyed on
    # PNP class "Bluetooth" instead (scanner.get_devices_by_class).

    @patch("checks.network.get_devices_by_class")
    @patch("checks.network.safe_get_latest", return_value=(True, None))
    def test_bluetooth_via_windows_update_uses_fallback_when_missing_from_primary_list(
        self, _mock_latest, mock_get_by_class,
    ):
        mock_get_by_class.return_value = [{
            "DeviceID": "USB\\VID_0489&PID_E10A&MI_03", "DeviceName": "Qualcomm Bluetooth",
            "DriverVersion": "1.0.0.0", "DriverDate": REAL_DATE,
            "VendorID": "0489", "DeviceID_PCI": "E10A",
        }]

        result = check_bluetooth_via_windows_update([], board={}, laptop={})

        mock_get_by_class.assert_called_once_with("Bluetooth")
        self.assertEqual(result.device, "Qualcomm Bluetooth")

    @patch("checks.network.get_devices_by_class")
    @patch("checks.network.safe_get_latest", return_value=(True, None))
    def test_bluetooth_via_windows_update_skips_fallback_when_found_in_primary_list(
        self, _mock_latest, mock_get_by_class,
    ):
        devices = [{
            "DeviceID": "USB\\VID_0489&PID_E10A", "DeviceName": "Qualcomm Bluetooth",
            "DriverVersion": "1.0.0.0", "DriverDate": REAL_DATE,
            "VendorID": "0489", "DeviceID_PCI": "E10A",
        }]

        check_bluetooth_via_windows_update(devices, board={}, laptop={})

        mock_get_by_class.assert_not_called()

    @patch("checks.network.get_devices_by_class")
    @patch("checks.network.safe_get_latest", return_value=(True, None))
    def test_intel_bluetooth_uses_fallback_when_missing_from_primary_list(self, _mock_latest, mock_get_by_class):
        mock_get_by_class.return_value = [{
            "DeviceID": "USB\\VID_8087&PID_0026&MI_03", "DeviceName": "Intel(R) Wireless Bluetooth(R)",
            "DriverVersion": "1.0.0.0", "DriverDate": REAL_DATE,
            "VendorID": "8087", "DeviceID_PCI": "0026",
        }]

        result = check_intel_bluetooth([], board={}, laptop={})

        mock_get_by_class.assert_called_once_with("Bluetooth")
        self.assertEqual(result.device, "Intel(R) Wireless Bluetooth(R)")


if __name__ == "__main__":
    unittest.main()

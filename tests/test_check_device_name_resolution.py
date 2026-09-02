import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checks.network import check_intel_lan, check_bluetooth_via_windows_update, check_wifi_via_windows_update
from checks.npu import check_intel_npu

GENERIC_DATE = "20060621000000.000000-000"


class CheckDeviceNameResolutionTests(unittest.TestCase):
    # confirms the wiring, not resolve_device_name itself (already
    # covered by tests/test_resolve_device_name.py) -- one representative
    # check per file is enough to prove the call sites were actually
    # updated, not every single check in checks/network.py

    # patch target is checks.common.hardware_ids.lookup, not
    # checks.network.hardware_ids.lookup / checks.npu.hardware_ids.lookup
    # -- checks/network.py and checks/npu.py never import hardware_ids
    # themselves, only checks/common.py's resolve_device_name does
    @patch("checks.common.hardware_ids.lookup", return_value=("Intel Corporation", "I219 Ethernet"))
    @patch("checks.network.safe_get_latest", return_value=(True, None))
    def test_intel_lan_uses_resolved_name_when_generic(self, _mock_latest, _mock_lookup):
        devices = [{
            "DeviceID": "PCI\\VEN_8086&DEV_15F2", "DeviceName": "Ethernet Controller",
            "DriverVersion": "1.0.0.0", "DriverDate": GENERIC_DATE,
            "VendorID": "8086", "DeviceID_PCI": "15F2", "DeviceClass": "NET",
        }]
        result = check_intel_lan(devices, board={}, laptop={})
        self.assertEqual(result.device, "I219 Ethernet")

    @patch("checks.common.hardware_ids.lookup", return_value=("Intel Corporation", None))
    @patch("checks.npu.safe_get_latest", return_value=(True, None))
    def test_intel_npu_falls_back_to_vendor_name_when_generic(self, _mock_latest, _mock_lookup):
        devices = [{
            "DeviceID": "PCI\\VEN_8086&DEV_7D1D", "DeviceName": "AI Boost NPU Device",
            "DriverVersion": "1.0.0.0", "DriverDate": GENERIC_DATE,
            "VendorID": "8086", "DeviceID_PCI": "7D1D",
        }]
        result = check_intel_npu(devices, board={}, laptop={})
        self.assertEqual(result.device, "Intel Corporation")

    @patch("checks.network.MsCatalogProvider")
    @patch("checks.common.hardware_ids.lookup", return_value=("Qualcomm Atheros Communications", None))
    def test_bluetooth_via_windows_update_searches_by_resolved_name(self, _mock_lookup, mock_provider_cls):
        mock_provider_cls.return_value.get_latest.return_value = None
        devices = [{
            "DeviceID": "USB\\VID_0489&PID_E10A", "DeviceName": "Generic Bluetooth Adapter",
            "DriverVersion": "10.0.26100.8972", "DriverDate": GENERIC_DATE,
            "VendorID": "0489", "DeviceID_PCI": "E10A", "DeviceClass": "BLUETOOTH",
        }]
        result = check_bluetooth_via_windows_update(devices, board={}, laptop={})

        # the resolved name, not "Generic Bluetooth Adapter", was used
        # as the search query -- this is the actual fix for the incident
        # that motivated this feature. title_contains="Bluetooth" is the
        # fix for the follow-up finding: a bare vendor-only resolved name
        # (no product match) must not be free-searched across ALL of that
        # vendor's catalog entries -- see providers/ms_catalog.py.
        mock_provider_cls.assert_called_once_with(
            query="Qualcomm Atheros Communications", title_contains="Bluetooth", name="bluetooth_windows_update",
        )
        self.assertEqual(result.device, "Qualcomm Atheros Communications")
        self.assertIn("Qualcomm Atheros Communications", result.display_line)

    @patch("checks.network.MsCatalogProvider")
    @patch("checks.common.hardware_ids.lookup", return_value=("Qualcomm Atheros Communications", None))
    def test_wifi_via_windows_update_searches_by_resolved_name(self, _mock_lookup, mock_provider_cls):
        mock_provider_cls.return_value.get_latest.return_value = None
        devices = [{
            "DeviceID": "PCI\\VEN_168C&DEV_003E", "DeviceName": "Generic Wireless Network Adapter",
            "DriverVersion": "12.0.0.1000", "DriverDate": GENERIC_DATE,
            "VendorID": "168C", "DeviceID_PCI": "003E", "DeviceClass": "NET",
        }]
        result = check_wifi_via_windows_update(devices, board={}, laptop={})

        # same category-safety fix as Bluetooth above, but WiFi/networking
        # catalog entries use "Net" or "WLAN" as the category word instead
        # of "Bluetooth" -- confirmed live (see providers/ms_catalog.py).
        mock_provider_cls.assert_called_once_with(
            query="Qualcomm Atheros Communications", title_contains=("Net", "WLAN"), name="wifi_windows_update",
        )
        self.assertEqual(result.device, "Qualcomm Atheros Communications")
        self.assertIn("Qualcomm Atheros Communications", result.display_line)

    @patch("checks.network.MsCatalogProvider")
    @patch("checks.common.hardware_ids.lookup", return_value=("Qualcomm Atheros Communications", None))
    def test_wifi_via_windows_update_ignores_non_net_wireless_dongle(self, _mock_lookup, mock_provider_cls):
        # regression test: a Razer HyperPolling wireless mouse/keyboard USB
        # dongle names itself "Razer HyperPolling Wireless Dongle" (matching
        # the WIRELESS keyword) but its DeviceClass is HIDCLASS, not NET --
        # confirmed live, this shadowed the real WiFi adapter (which sorted
        # later in the device list) and the app reported the dongle instead
        # of ever finding the WiFi card.
        mock_provider_cls.return_value.get_latest.return_value = None
        devices = [
            {
                "DeviceID": "USB\\VID_1532&PID_00B3&MI_02", "DeviceName": "Razer HyperPolling Wireless Dongle",
                "DriverVersion": "1.0.0.0", "DriverDate": GENERIC_DATE,
                "VendorID": "1532", "DeviceID_PCI": "00B3", "DeviceClass": "HIDCLASS",
            },
            {
                "DeviceID": "PCI\\VEN_17CB&DEV_1107", "DeviceName": "Qualcomm FastConnect 7800 Wi-Fi 7 Network Adapter",
                "DriverVersion": "3.1.0.1647", "DriverDate": GENERIC_DATE,
                "VendorID": "17CB", "DeviceID_PCI": "1107", "DeviceClass": "NET",
            },
        ]
        result = check_wifi_via_windows_update(devices, board={}, laptop={})

        self.assertEqual(result.device, "Qualcomm Atheros Communications")


if __name__ == "__main__":
    unittest.main()

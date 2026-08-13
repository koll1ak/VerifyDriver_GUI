import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checks.network import check_intel_lan, check_bluetooth_via_windows_update
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
            "VendorID": "8086", "DeviceID_PCI": "15F2",
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
            "VendorID": "0489", "DeviceID_PCI": "E10A",
        }]
        result = check_bluetooth_via_windows_update(devices, board={}, laptop={})

        # the resolved name, not "Generic Bluetooth Adapter", was used
        # as the search query -- this is the actual fix for the incident
        # that motivated this feature
        mock_provider_cls.assert_called_once_with(
            query="Qualcomm Atheros Communications", name="bluetooth_windows_update",
        )
        self.assertEqual(result.device, "Qualcomm Atheros Communications")
        self.assertIn("Qualcomm Atheros Communications", result.display_line)


if __name__ == "__main__":
    unittest.main()

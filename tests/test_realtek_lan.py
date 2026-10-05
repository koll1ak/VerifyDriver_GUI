import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from providers.realtek_lan import RealtekLanProvider


def _device(name, device_class="NET", vendor_id="10EC"):
    return {
        "VendorID": vendor_id,
        "DeviceID": r"PCI\VEN_10EC&DEV_8126&SUBSYS_7E511462&REV_01\01000000684CE00000",
        "DeviceName": name,
        "DeviceClass": device_class,
    }


class RealtekLanMatchesTests(unittest.TestCase):
    def test_matches_realtek_driver_family_controller_name(self):
        self.assertTrue(RealtekLanProvider().matches(_device("Realtek Gaming 5GbE Family Controller")))

    def test_matches_windows_inbox_driver_ethernet_controller_name(self):
        # confirmed live: an RTL8126 on Windows' inbox driver (9.1.412.2015)
        self.assertTrue(RealtekLanProvider().matches(_device("Realtek(R) PCI(e) Ethernet Controller")))

    def test_rejects_non_net_class(self):
        self.assertFalse(RealtekLanProvider().matches(_device("Realtek(R) PCI(e) Ethernet Controller", "MEDIA")))

    def test_rejects_wifi(self):
        self.assertFalse(RealtekLanProvider().matches(_device("Realtek RTL8852BE WiFi 6 802.11ax PCIe Adapter")))


if __name__ == "__main__":
    unittest.main()

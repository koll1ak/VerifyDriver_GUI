import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hardware_ids

_SAMPLE_IDS = (
    "# comment line, ignored\n"
    "\n"
    "0489  Foxconn / Hon Hai\n"
    "\t0502  SmartMedia Card Reader Firmware Loader\n"
    "\td00c  Rollei Compactline (Storage Mode)\n"
    "\t\t00  some interface, should be ignored\n"
    "10ec  Realtek Semiconductor Co., Ltd.\n"
    "\t0139  RTL-8139/8139C/8139C+ Ethernet Controller\n"
    "0000  Vendor With No Devices\n"
)


def _write_fixture(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class ParseIdsFileTests(unittest.TestCase):
    def test_parses_vendors_and_devices(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sample.ids")
            _write_fixture(path, _SAMPLE_IDS)
            result = hardware_ids._parse_ids_file(path)

        self.assertEqual(result["0489"][0], "Foxconn / Hon Hai")
        self.assertEqual(result["0489"][1]["d00c"], "Rollei Compactline (Storage Mode)")
        self.assertEqual(result["10ec"][0], "Realtek Semiconductor Co., Ltd.")
        self.assertEqual(result["10ec"][1]["0139"], "RTL-8139/8139C/8139C+ Ethernet Controller")

    def test_ignores_interface_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sample.ids")
            _write_fixture(path, _SAMPLE_IDS)
            result = hardware_ids._parse_ids_file(path)

        # the "00  some interface" line is double-tab-indented -- must not
        # show up as a device of 0489, and must not corrupt parsing of
        # the vendor that follows it
        self.assertNotIn("00", result["0489"][1])
        self.assertIn("10ec", result)

    def test_vendor_with_no_devices(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sample.ids")
            _write_fixture(path, _SAMPLE_IDS)
            result = hardware_ids._parse_ids_file(path)

        self.assertEqual(result["0000"], ("Vendor With No Devices", {}))

    def test_missing_file_returns_empty_dict(self):
        result = hardware_ids._parse_ids_file("/nonexistent/path/does-not-exist.ids")
        self.assertEqual(result, {})


class LookupTests(unittest.TestCase):
    def setUp(self):
        hardware_ids._usb_vendors = None
        hardware_ids._pci_vendors = None

    def tearDown(self):
        hardware_ids._usb_vendors = None
        hardware_ids._pci_vendors = None

    def test_usb_namespace_finds_vendor_and_product(self):
        fixture = {"0489": ("Foxconn / Hon Hai", {"e10a": "FastConnect 7800 Bluetooth"})}
        with patch("hardware_ids._usb_db", return_value=fixture):
            vendor, product = hardware_ids.lookup("usb", "0489", "E10A")
        self.assertEqual(vendor, "Foxconn / Hon Hai")
        self.assertEqual(product, "FastConnect 7800 Bluetooth")

    def test_usb_namespace_vendor_only_when_product_unknown(self):
        fixture = {"0489": ("Foxconn / Hon Hai", {})}
        with patch("hardware_ids._usb_db", return_value=fixture):
            vendor, product = hardware_ids.lookup("usb", "0489", "ZZZZ")
        self.assertEqual(vendor, "Foxconn / Hon Hai")
        self.assertIsNone(product)

    def test_pci_namespace_uses_separate_registry(self):
        usb_fixture = {"10ec": ("Wrong Registry", {})}
        pci_fixture = {"10ec": ("Realtek Semiconductor Co., Ltd.", {"0139": "RTL-8139"})}
        with patch("hardware_ids._usb_db", return_value=usb_fixture), \
                patch("hardware_ids._pci_db", return_value=pci_fixture):
            vendor, product = hardware_ids.lookup("pci", "10EC", "0139")
        self.assertEqual(vendor, "Realtek Semiconductor Co., Ltd.")
        self.assertEqual(product, "RTL-8139")

    def test_unknown_vendor_returns_none_none(self):
        with patch("hardware_ids._usb_db", return_value={}):
            vendor, product = hardware_ids.lookup("usb", "FFFF", "FFFF")
        self.assertIsNone(vendor)
        self.assertIsNone(product)

    def test_no_vendor_hex_returns_none_none(self):
        vendor, product = hardware_ids.lookup("usb", None, "E10A")
        self.assertIsNone(vendor)
        self.assertIsNone(product)

    def test_case_insensitive_lookup(self):
        fixture = {"0489": ("Foxconn / Hon Hai", {"e10a": "FastConnect 7800"})}
        with patch("hardware_ids._usb_db", return_value=fixture):
            vendor, product = hardware_ids.lookup("usb", "0489", "e10a")
        self.assertEqual(product, "FastConnect 7800")


class RealBundledDataSmokeTests(unittest.TestCase):
    """Confirms the actual bundled data/usb.ids and data/pci.ids files are
    present and parse to something sane -- guards against forgetting to
    bundle them, or a corrupt/empty download."""

    def setUp(self):
        hardware_ids._usb_vendors = None
        hardware_ids._pci_vendors = None

    def tearDown(self):
        hardware_ids._usb_vendors = None
        hardware_ids._pci_vendors = None

    def test_real_pci_ids_resolves_nvidia(self):
        vendor, _product = hardware_ids.lookup("pci", "10DE", None)
        self.assertEqual(vendor, "NVIDIA Corporation")

    def test_real_usb_ids_resolves_foxconn(self):
        vendor, _product = hardware_ids.lookup("usb", "0489", None)
        self.assertIn("Foxconn", vendor)


if __name__ == "__main__":
    unittest.main()

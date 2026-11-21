import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checks import gpu
from checks.common import DOWNLOAD_UPDATE_STATUS

NVIDIA_DEVICE = {
    "VendorID": "10DE",
    "DeviceName": "NVIDIA GeForce RTX 5080",
    "DeviceClass": "DISPLAY",
    "DriverVersion": "32.0.15.6213",
    "DriverDate": "20261101000000.000000-000",
}

INTEL_DEVICE = {
    "VendorID": "8086",
    "DeviceName": "Intel(R) Arc(TM) Graphics",
    "DeviceClass": "DISPLAY",
    "DriverVersion": "32.0.101.6000",
    "DriverDate": "20261101000000.000000-000",
}


def _run_nvidia(installed, site):
    latest = {"version": site, "date": "2026-10-01", "url": "https://example.com/nv.exe"}
    with patch.object(gpu.NvidiaProvider, "get_latest", return_value=latest), \
            patch.object(gpu, "get_current_nvidia_version", return_value=installed):
        return gpu.check_nvidia([NVIDIA_DEVICE], {}, {})


def _run_intel(site):
    latest = {"version": site, "url": "https://example.com/intel.exe"}
    with patch.object(gpu.IntelDownloadCenterProvider, "get_latest", return_value=latest):
        return gpu.check_intel_gpu([INTEL_DEVICE], {}, {})


class NvidiaVersionCompareTests(unittest.TestCase):
    def test_installed_newer_than_site_is_up_to_date(self):
        # seen in practice: 621.35 installed, NVIDIA's lookup API listing 621.24
        result = _run_nvidia("621.35", "621.24")
        self.assertEqual(result.status, "Up to date")

    def test_newer_installed_keeps_separate_dates(self):
        result = _run_nvidia("621.35", "621.24")
        self.assertEqual(result.current, "621.35 (2026-11-01)")
        self.assertEqual(result.available, "621.24 (2026-10-01)")

    def test_site_newer_offers_update(self):
        result = _run_nvidia("621.24", "621.35")
        self.assertEqual(result.status, DOWNLOAD_UPDATE_STATUS)

    def test_minor_part_compared_numerically_not_as_string(self):
        # "621.9" < "621.10" numerically, though "9" > "1" as strings
        self.assertEqual(_run_nvidia("621.9", "621.10").status, DOWNLOAD_UPDATE_STATUS)
        self.assertEqual(_run_nvidia("621.10", "621.9").status, "Up to date")

    def test_same_version_is_up_to_date(self):
        self.assertEqual(_run_nvidia("621.35", "621.35").status, "Up to date")


class IntelGpuVersionCompareTests(unittest.TestCase):
    def test_installed_newer_than_site_is_up_to_date(self):
        self.assertEqual(_run_intel("32.0.101.5999").status, "Up to date")

    def test_site_newer_offers_update(self):
        self.assertEqual(_run_intel("32.0.101.6100").status, DOWNLOAD_UPDATE_STATUS)


if __name__ == "__main__":
    unittest.main()

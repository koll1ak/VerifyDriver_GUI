import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checks.laptop import check_dell_bios, check_huawei_bios


class ManualCheckBiosCurrentVersionTests(unittest.TestCase):
    # manual_check_unavailable used to always report current=None, so
    # laptops whose vendor site is blocked (Dell, Huawei) never showed
    # the installed BIOS version at all, even though it's readable
    # locally via Win32_BIOS regardless of whether the site is reachable.

    @patch("checks.laptop.get_current_bios_info", return_value=("1.22.0", "2023-05-10"))
    def test_dell_bios_shows_installed_version(self, _mock_bios_info):
        laptop = {"is_laptop": True, "manufacturer": "Dell Inc.", "dell_service_tag": "ABC1234"}
        result = check_dell_bios([], board={}, laptop=laptop)

        self.assertEqual(result.current, "1.22.0 (2023-05-10)")
        self.assertEqual(result.status, "Manual check")

    @patch("checks.laptop.get_current_bios_info", return_value=("1.14", None))
    def test_huawei_bios_shows_installed_version(self, _mock_bios_info):
        laptop = {"is_laptop": True, "manufacturer": "HUAWEI", "model": "MateBook X Pro"}
        result = check_huawei_bios([], board={}, laptop=laptop)

        self.assertEqual(result.current, "1.14")
        self.assertEqual(result.status, "Manual check")


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checks.laptop import check_dell_audio

LAPTOP = {"is_laptop": True, "manufacturer": "Dell Inc.", "dell_service_tag": "ABC1234"}


class DellAudioCurrentVersionTests(unittest.TestCase):
    # check_dell_audio never looked at the `devices` list at all, so the
    # installed audio driver version was always missing -- same root
    # cause as the Dell BIOS bug, but the current version here comes
    # from the PnP device list (Realtek codec) instead of Win32_BIOS.

    def test_shows_installed_version_from_realtek_codec(self):
        devices = [{
            "VendorID": "10EC",
            "DeviceName": "Realtek High Definition Audio",
            "DriverVersion": "6.0.9564.1",
            "DriverDate": "20230815000000.000000-000",
        }]
        result = check_dell_audio(devices, board={}, laptop=LAPTOP)

        self.assertEqual(result.device, "Realtek High Definition Audio")
        self.assertEqual(result.current, "6.0.9564.1 (2023-08-15)")
        self.assertEqual(result.status, "Manual check")

    def test_falls_back_to_usb_codec_vendor_id(self):
        devices = [{
            "VendorID": "0BDA",
            "DeviceName": "Realtek USB2.0 Audio",
            "DriverVersion": "6.0.9500.1",
            "DriverDate": None,
        }]
        result = check_dell_audio(devices, board={}, laptop=LAPTOP)

        self.assertEqual(result.current, "6.0.9500.1")

    def test_no_audio_device_found_still_returns_manual_check(self):
        result = check_dell_audio([], board={}, laptop=LAPTOP)

        self.assertEqual(result.device, "Dell Audio")
        self.assertEqual(result.current, "—")
        self.assertEqual(result.status, "Manual check")

    def test_non_dell_laptop_returns_none(self):
        laptop = {"is_laptop": True, "manufacturer": "HP Inc."}
        self.assertIsNone(check_dell_audio([], board={}, laptop=laptop))


if __name__ == "__main__":
    unittest.main()

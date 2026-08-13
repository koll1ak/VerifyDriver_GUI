import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner import get_devices_by_id_pattern, get_devices_by_class, PS_COMMAND_PNP_FALLBACK, PS_COMMAND_PNP_BY_CLASS


def _completed(stdout, returncode=0):
    return Mock(returncode=returncode, stdout=stdout, stderr="")


class GetDevicesByIdPatternDriverDateTests(unittest.TestCase):
    # resolve_device_name's placeholder-date gate (checks/common.py) only
    # fires when a DriverDate is present -- the Get-PnpDevice fallback
    # path used to omit it entirely (only DriverVersion was fetched via
    # Get-PnpDeviceProperty), which made hardware-ID name resolution a
    # guaranteed silent no-op for every device found through this path
    # (documented in checks/audio.py's _audio_display_name docstring).
    # DriverDate must now come back the same way DriverVersion already
    # does, via DEVPKEY_Device_DriverDate.

    @patch("scanner.run_powershell")
    def test_includes_driver_date_from_devpkey(self, mock_run):
        mock_run.return_value = _completed(json.dumps({
            "DeviceName": "Realtek USB2.0 Audio",
            "DeviceID": "USB\\VID_0BDA&PID_4080&MI_00\\6&2E28A24&0&0000",
            "DriverVersion": "6.0.9200.1",
            "DriverDate": "/Date(1749081600000)/",
            "Status": "OK",
        }))

        devices = get_devices_by_id_pattern("VID_0BDA")

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["DriverDate"], "/Date(1749081600000)/")

    def test_ps_command_fetches_driver_date_devpkey(self):
        self.assertIn("DEVPKEY_Device_DriverDate", PS_COMMAND_PNP_FALLBACK)


class GetDevicesByClassTests(unittest.TestCase):
    # Bluetooth's Get-PnpDevice fallback (checks/network.py) can't key on
    # one fixed vendor ID the way audio's fallback does (VID_0BDA) --
    # Bluetooth chips come from many makers (Qualcomm, MediaTek,
    # Broadcom, ...) -- so it filters by PNP device class instead.

    @patch("scanner.run_powershell")
    def test_includes_driver_date_from_devpkey(self, mock_run):
        mock_run.return_value = _completed(json.dumps({
            "DeviceName": "Qualcomm FastConnect 7800 Bluetooth",
            "DeviceID": "USB\\VID_0489&PID_E10A&MI_03\\6&2E28A24&0&0003",
            "DriverVersion": "10.0.26100.8972",
            "DriverDate": "/Date(1749081600000)/",
            "Status": "OK",
        }))

        devices = get_devices_by_class("Bluetooth")

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["DeviceName"], "Qualcomm FastConnect 7800 Bluetooth")
        self.assertEqual(devices[0]["VendorID"], "0489")
        self.assertEqual(devices[0]["DriverDate"], "/Date(1749081600000)/")
        mock_run.assert_called_once_with(PS_COMMAND_PNP_BY_CLASS.format(class_name="Bluetooth"))

    def test_ps_command_filters_by_class_not_instance_id(self):
        self.assertIn("-Class '{class_name}'", PS_COMMAND_PNP_BY_CLASS)
        self.assertIn("DEVPKEY_Device_DriverDate", PS_COMMAND_PNP_BY_CLASS)

    def test_ps_command_excludes_non_hardware_and_nameless_devices(self):
        # Get-PnpDevice -Class 'Bluetooth' also returns non-hardware PnP
        # entries (e.g. "Microsoft Bluetooth Enumerator", RFCOMM/PAN
        # virtual sub-devices) that have no VEN_/VID_ in their InstanceId
        # (so VendorID ends up None, which slips past a "not Intel"
        # vendor check) and sometimes no FriendlyName at all (which would
        # crash a caller's `d.get("DeviceName", "").upper()`, since a
        # present-but-null key isn't caught by dict.get's default). The
        # primary Win32_PnPSignedDriver query already guards against both
        # (scanner.py's PS_COMMAND: `-match '^(PCI|USB|HDAUDIO)' -and
        # $_.DeviceName`) -- this fallback needs the same two guards.
        self.assertIn("-match '^(PCI|USB|HDAUDIO)'", PS_COMMAND_PNP_BY_CLASS)
        self.assertIn("$_.FriendlyName", PS_COMMAND_PNP_BY_CLASS)


if __name__ == "__main__":
    unittest.main()

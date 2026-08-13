import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner import get_devices_by_id_pattern, PS_COMMAND_PNP_FALLBACK


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


if __name__ == "__main__":
    unittest.main()

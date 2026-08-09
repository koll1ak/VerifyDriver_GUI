"""
Collects the list of installed devices and driver versions via WMI.
Works only on Windows (uses powershell.exe).
"""

import json
import re

from ps_utils import run_powershell


PS_COMMAND = (
    "Get-CimInstance Win32_PnPSignedDriver | "
    "Where-Object { $_.DeviceID -match '^(PCI|USB|HDAUDIO)' -and $_.DeviceName } | "
    "Select-Object DeviceName, DeviceID, DriverVersion, DriverDate, Manufacturer | "
    "ConvertTo-Json -Depth 3"
)

# Get-PnpDevice sees devices that Win32_PnPSignedDriver sometimes misses —
# in particular individual "sub-functions" of composite USB devices.
# Without -PresentOnly (or with -PresentOnly but iterating disabled
# statuses too), so we can catch a device even if it's currently disabled
# in Windows.
PS_COMMAND_PNP_FALLBACK = (
    "Get-PnpDevice | "
    "Where-Object {{ $_.InstanceId -match '{pattern}' }} | "
    "ForEach-Object {{ "
    "  $ver = (Get-PnpDeviceProperty -InstanceId $_.InstanceId "
    "          -KeyName 'DEVPKEY_Device_DriverVersion' -ErrorAction SilentlyContinue).Data; "
    "  [PSCustomObject]@{{ "
    "    DeviceName = $_.FriendlyName; DeviceID = $_.InstanceId; "
    "    DriverVersion = $ver; Status = $_.Status "
    "  }} "
    "}} | ConvertTo-Json -Depth 3"
)

VEN_DEV_RE = re.compile(
    r"(?:VEN_|VID_)([0-9A-F]{4})(?:&(?:DEV_|PID_)([0-9A-F]{4}))?",
    re.IGNORECASE,
)


def get_installed_devices() -> list[dict]:
    """
    Returns a list of devices shaped like:
    {
        "DeviceName": "NVIDIA GeForce RTX 5080",
        "DeviceID": "PCI\\VEN_10DE&DEV_2704&...",
        "DriverVersion": "32.0.15.7283",
        "DriverDate": "...",
        "Manufacturer": "NVIDIA",
        "VendorID": "10DE",
        "DeviceID_PCI": "2704",
    }
    """
    result = run_powershell(PS_COMMAND)

    if result.returncode != 0:
        raise RuntimeError(f"PowerShell error: {result.stderr}")

    raw = result.stdout.strip()
    if not raw:
        return []

    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]

    devices = []
    for item in data:
        m = VEN_DEV_RE.search(item.get("DeviceID", ""))
        item["VendorID"] = m.group(1).upper() if m else None
        item["DeviceID_PCI"] = m.group(2).upper() if m else None
        devices.append(item)

    return devices


def get_devices_by_id_pattern(instance_id_regex: str) -> list[dict]:
    """
    Fallback lookup via Get-PnpDevice for devices that
    Win32_PnPSignedDriver doesn't show (composite USB sub-functions, etc.).
    Searches ALL devices matching this pattern, including disabled ones
    (no -PresentOnly) — the Status field shows whether the device is enabled.
    instance_id_regex — a regex pattern used to filter InstanceId on the
    PowerShell side (e.g. "VID_0BDA").
    """
    ps_command = PS_COMMAND_PNP_FALLBACK.format(pattern=instance_id_regex)
    result = run_powershell(ps_command)

    if result.returncode != 0:
        raise RuntimeError(f"PowerShell error: {result.stderr}")

    raw = result.stdout.strip()
    if not raw:
        return []

    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]

    devices = []
    for item in data:
        m = VEN_DEV_RE.search(item.get("DeviceID", ""))
        item["VendorID"] = m.group(1).upper() if m else None
        item["DeviceID_PCI"] = m.group(2).upper() if m else None
        devices.append(item)

    return devices


if __name__ == "__main__":
    import sys

    # on some systems (non-UTF8 console locale) output may contain
    # characters not present in the console encoding — switch stdout to
    # UTF-8 with replacement of unreadable characters instead of crashing
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) > 1:
        # python scanner.py VID_0BDA — targeted lookup by pattern,
        # including disabled devices (useful for debugging)
        pattern = sys.argv[1]
        for d in get_devices_by_id_pattern(pattern):
            print(f"{d['DeviceName']} | VEN_{d['VendorID']} | ver={d['DriverVersion']} | status={d.get('Status')}")
    else:
        for d in get_installed_devices():
            print(f"{d['DeviceName']} | VEN_{d['VendorID']} | ver={d['DriverVersion']}")

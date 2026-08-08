"""
Сбор списка установленных устройств и версий драйверов через WMI.
Работает только на Windows (использует powershell.exe).
"""

import json
import re
import subprocess


PS_COMMAND = (
    "Get-CimInstance Win32_PnPSignedDriver | "
    "Where-Object { $_.DeviceID -match '^(PCI|USB|HDAUDIO)' -and $_.DeviceName } | "
    "Select-Object DeviceName, DeviceID, DriverVersion, DriverDate, Manufacturer | "
    "ConvertTo-Json -Depth 3"
)

# Get-PnpDevice видит устройства, которые Win32_PnPSignedDriver иногда
# пропускает — в частности отдельные "под-функции" составных USB-устройств.
# Без -PresentOnly (или с -PresentOnly, но перебирая и отключённые статусы),
# чтобы поймать устройство, даже если оно сейчас отключено в Windows.
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
    Возвращает список устройств вида:
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
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", PS_COMMAND],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

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
    Резервный поиск через Get-PnpDevice для устройств, которые
    Win32_PnPSignedDriver не показывает (составные USB под-функции и т.п.).
    Ищет ВСЕ устройства с этим паттерном, включая отключённые (без
    -PresentOnly) — поле Status покажет, включено ли устройство.
    instance_id_regex — regex-паттерн для фильтрации InstanceId на стороне
    PowerShell (например "VID_0BDA").
    """
    ps_command = PS_COMMAND_PNP_FALLBACK.format(pattern=instance_id_regex)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

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

    # на некоторых системах (не-UTF8 локаль консоли) вывод может содержать
    # символы, которых нет в кодировке консоли — переключаем stdout на
    # UTF-8 с заменой нечитаемых символов вместо падения
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) > 1:
        # python scanner.py VID_0BDA — точечный поиск по паттерну,
        # включая отключённые устройства (полезно для отладки)
        pattern = sys.argv[1]
        for d in get_devices_by_id_pattern(pattern):
            print(f"{d['DeviceName']} | VEN_{d['VendorID']} | ver={d['DriverVersion']} | status={d.get('Status')}")
    else:
        for d in get_installed_devices():
            print(f"{d['DeviceName']} | VEN_{d['VendorID']} | ver={d['DriverVersion']}")

import sys
import re
from datetime import datetime

from net_utils import classify_error


def find_device(devices, predicate):
    """
    Returns the first device from the list matching predicate.
    predicate is either an object with a matches(device) method (a
    Provider) or a plain device -> bool function. A shared helper
    instead of repeating "for device in devices: if ...matches(device):
    ..." in every check.
    """
    match_fn = predicate.matches if hasattr(predicate, "matches") else predicate
    for device in devices:
        if match_fn(device):
            return device
    return None


def safe_get_latest(label: str, provider, device=None):
    """
    Wraps provider.get_latest() — replaces the repeated try/except in
    every check_* function. If the provider raises, prints to stderr and
    returns (False, None) (a signal to silently skip the check). If it
    ran without errors (including the case where the provider itself
    genuinely found nothing and returned None) — returns (True, latest);
    True here means exactly "ran without failing", not "found
    something" — latest can be None, and that's handled normally
    downstream by report().
    """
    try:
        latest = provider.get_latest(device) if device is not None else provider.get_latest()
    except Exception as e:
        print(f"[{label}] error: {classify_error(e)}", file=sys.stderr)
        return False, None
    return True, latest


def find_device_driver_version(devices, vendor_id: str, name_keywords):
    """Looks among devices for a match on VendorID and a name substring, returns DriverVersion."""
    device = find_device(
        devices,
        lambda d: d.get("VendorID") == vendor_id and any(
            kw in d.get("DeviceName", "").upper() for kw in name_keywords
        ),
    )
    return device.get("DriverVersion") if device else None


def laptop_model_if_vendor(laptop: dict, vendor_keyword: str, model_field: str):
    """
    Shared pattern for vendor-specific laptop checks: if this is a
    laptop from the given vendor and the model was determined — returns
    the model, otherwise None (a signal to silently skip the check).
    """
    if not laptop.get("is_laptop"):
        return None
    manufacturer = laptop.get("manufacturer") or ""
    if vendor_keyword not in manufacturer.upper():
        return None
    return laptop.get(model_field)


def overall_drivers_page_url(board: dict, laptop: dict) -> str | None:
    """
    The overall page with all drivers for the device as a whole — a
    known-vendor laptop (Acer/Dell) or a motherboard (MSI/Gigabyte/
    ASRock/ASUS) on desktop. Useful as a single link for a manual check
    at the end of the run, separate from the specific per-component checks.
    """
    if laptop.get("is_laptop"):
        manufacturer = (laptop.get("manufacturer") or "").upper()

        if "ACER" in manufacturer and laptop.get("acer_model_name") and laptop.get("acer_part_number"):
            model = laptop["acer_model_name"]
            part_number = laptop["acer_part_number"]
            serial = laptop.get("acer_serial", "")
            return f"https://www.acer.com/us-en/support/product-support/{model}/{part_number}/downloads?sn={serial}"

        if "DELL" in manufacturer and laptop.get("dell_service_tag"):
            return f"https://www.dell.com/support/home/en-us/product-support/servicetag/{laptop['dell_service_tag']}/drivers"

        if "ASUS" in manufacturer and laptop.get("asus_laptop_model"):
            model = laptop["asus_laptop_model"].lower()
            return f"https://www.asus.com/us/supportonly/{model}/helpdesk_download/"

        return None

    # desktop — the motherboard page at the corresponding vendor
    vendor = board.get("vendor")

    if vendor == "msi" and board.get("msi_slug"):
        return f"https://www.msi.com/Motherboard/{board['msi_slug']}/support"

    if vendor == "gigabyte" and board.get("gigabyte_slug"):
        return f"https://www.gigabyte.com/Motherboard/{board['gigabyte_slug']}/support"

    if vendor == "asrock" and board.get("asrock_model"):
        family = board.get("chipset_family", "amd")
        return f"https://www.asrock.com/mb/{family}/{board['asrock_model']}/"

    if vendor == "asus" and board.get("asus_model"):
        from urllib.parse import quote
        return f"https://www.asus.com/us/supportonly/{quote(board['asus_model'].lower())}/helpdesk_download/"

    return None


def _parse_version_tuple(v: str):
    """Version as a tuple of numbers for numeric comparison (not string comparison)."""
    try:
        return tuple(int(p) for p in v.split("."))
    except (ValueError, AttributeError):
        return None


def no_downgrade_match(current: str, latest: str) -> bool:
    """
    Considers the versions "matching" (don't suggest an update) if the
    installed version is NUMERICALLY not older than the version on the
    site — i.e. if the site lags behind what's actually already
    installed (a common situation: an OEM page updates less often than
    Windows Update/the chip maker itself), we never recommend
    "downgrading" to an older version.
    """
    if not current or not latest:
        return False
    current_t = _parse_version_tuple(current)
    latest_t = _parse_version_tuple(latest)
    if current_t is None or latest_t is None:
        return current == latest  # couldn't parse as numbers — compare as strings
    return current_t >= latest_t


def parse_flexible_date(raw: str):
    """
    Tries to parse a date in the various formats that come up:
    - Realtek's site: "2026/07/30"
    - WMI DriverDate (raw CIM format): "20220516000000.000000-000"
    - WMI DriverDate (if PowerShell already converted it to ISO): "2022-05-16T00:00:00"
    - WMI DriverDate via ConvertTo-Json (ASP.NET style, confirmed on a
      real device): "/Date(1783123200000)/" — Unix time in ms
    """
    if not raw:
        return None

    aspnet_match = re.match(r"/Date\((\d+)\)/", raw)
    if aspnet_match:
        try:
            from datetime import timezone
            return datetime.fromtimestamp(int(aspnet_match.group(1)) / 1000, tz=timezone.utc).replace(tzinfo=None)
        except (ValueError, OSError):
            return None

    for fmt in ("%Y/%m/%d", "%Y%m%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            # for the raw WMI format take only the first 8 characters (YYYYMMDD)
            candidate = raw[:8] if fmt == "%Y%m%d" else raw
            return datetime.strptime(candidate, fmt)
        except (ValueError, TypeError):
            continue
    return None


def report(label, latest, current, comparator=None):
    """
    Shared comparison logic. Returns (display_line, update_line):
    display_line — a status line for the overall report (always
    present), update_line — a line for the "Updates available" section
    (or None if no update was found/comparison wasn't possible). Doesn't
    print by itself — printing happens in main() after all the parallel
    checks finish, in a fixed order by category.
    """
    if latest is None:
        return f"[{label}] could not find the current version on the site", None

    if current is None:
        return f"[{label}] on the site: {latest['version']} (couldn't compare against the installed version)", None

    is_match = comparator(current, latest["version"]) if comparator else (current == latest["version"])

    if is_match:
        return f"[{label}] up to date ({latest['version']})", None

    display_url = latest.get("page_url") or latest.get("url") or ""
    update_line = f"{label}: installed {current} -> available {latest['version']} ({display_url})"
    return f"[{label}] UPDATE AVAILABLE: {current} -> {latest['version']}", update_line

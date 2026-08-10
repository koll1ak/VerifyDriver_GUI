import sys
import re
from datetime import datetime
from typing import NamedTuple

from net_utils import classify_error


class CheckResult(NamedTuple):
    """
    What a check_* function returns. display_line/update_line are the
    exact text the CLI has always printed (main.py doesn't need to
    change at all); the other fields are the same information broken out
    for the GUI's table view (Device/Current/Available/Status columns).
    """
    device: str
    current: str             # "Current" column text, "—" if unknown
    available: str            # "Available" column text, "—" if unknown/not applicable
    status: str                 # short status text, e.g. "Up to date", "Update available"
    url: str | None              # manual-check page or update download link, if any
    display_line: str             # unchanged CLI per-category line
    update_line: str | None        # unchanged CLI "Updates available" line


# Windows' built-in "null" class drivers (e.g. the generic Bluetooth
# radio driver, bthusb.inf/bth.inf, used when no vendor-specific driver
# is installed) hardcode this exact DriverVer date regardless of the
# actual Windows version — it's not when anything was installed, just a
# fixed placeholder baked into the inbox INF (widely reported across
# Windows 7 through 11). Showing "(2006-06-21)" next to a driver version
# like "10.0.19041.5848" falsely implies the driver itself is 20 years
# old, so it's treated the same as "no date" rather than displayed.
_NULL_DRIVER_PLACEHOLDER_DATE = datetime(2006, 6, 21)

# Some Intel chipset "platform" devices (SMBus/LPC Controller/Host Bridge,
# confirmed live via Win32_PnPSignedDriver.DriverDate) report a DriverDate
# of 1968-07-18 -- another garbage/uninitialized placeholder, like the
# 2006-06-21 one above but not a single fixed constant we've seen (no
# confirmed alternate value yet). No real Windows driver predates 1990,
# so any date parsed before this cutoff is treated as "no date" the same
# way -- showing a fabricated decades-old date is worse than showing none.
_IMPLAUSIBLY_OLD_DATE_CUTOFF = datetime(1990, 1, 1)


def _parse_valid_date(raw_date):
    """
    Parses raw_date (any format parse_flexible_date handles) and filters
    out known-garbage placeholder dates, returning a real datetime or
    None either way — used both to render a date and to decide, when two
    sources disagree, which one is actually worth showing.
    """
    date = parse_flexible_date(raw_date) if raw_date else None
    if date == _NULL_DRIVER_PLACEHOLDER_DATE or (date and date < _IMPLAUSIBLY_OLD_DATE_CUTOFF):
        return None
    return date


def _with_date(version, raw_date):
    """
    "6.4.0.2443" + "20220516000000.000000-000"/"2026/07/30"/etc. (any
    format parse_flexible_date already handles) -> "6.4.0.2443
    (2026-07-30)". Falls back to just the version if there's no date, it
    doesn't parse, or it's a known-garbage placeholder date — never
    fails, since a missing/unparseable date is common and shouldn't hide
    the version itself.
    """
    if not version:
        return "—"
    date = _parse_valid_date(raw_date)
    return f"{version} ({date.date()})" if date else version


def build_result(
    label, display_line, update_line=None, current=None, available=None, status="", url=None, device_name=None,
    current_date=None, available_date=None,
):
    """
    device_name: the actual hardware name reported by Windows (e.g.
    "NVIDIA GeForce RTX 5080"), when a check has one — shown in the GUI
    table's Device column instead of the generic check label ("NVIDIA").
    label is still used as-is for display_line, so CLI text never
    changes; device_name/current_date/available_date only affect the
    structured fields.

    current_date/available_date: the driver's release date (installed
    one from WMI's DriverDate, available one from whatever date field
    the provider scraped), shown as "version (date)" in the GUI table.
    """
    return CheckResult(
        device=device_name or label,
        current=_with_date(current, current_date),
        available=_with_date(available, available_date),
        status=status,
        url=url,
        display_line=display_line,
        update_line=update_line,
    )


def manual_result(label, display_line, url=None, current=None, device_name=None, current_date=None):
    """
    Shared shape for the "no automatic check possible" checks (Dell,
    Huawei, Samsung, LG, Microsoft Surface, ASRock, ...) — each vendor's
    exact display_line wording differs (it reflects something specific
    confirmed about that vendor's site), but they all end up as the same
    "manual check" row in the GUI's table.
    """
    return build_result(
        label, display_line, current=current, status="Manual check", url=url, device_name=device_name,
        current_date=current_date,
    )


def manual_check_unavailable(label, url, device_name=None):
    """
    Shared shape specifically for the "site confirmed blocked/unreachable
    — visit it yourself" checks (ASRock, Dell, Huawei, and the desktop
    vendor_configs' blocked-page fallback in checks/audio.py) — same
    exact wording every time, just the label/url differ.
    """
    display_line = f"[{label}] automatic check unavailable — visit the site manually: {url}"
    return manual_result(label, display_line, url=url, device_name=device_name)


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


def find_device_by_vendor_and_keywords(devices, vendor_id: str, name_keywords):
    """
    Looks among devices for a match on VendorID and a name substring,
    returns the device dict itself (or None) — use this instead of
    find_device_driver_version when the caller also needs DeviceName/
    DriverDate/etc., not just the version.
    """
    return find_device(
        devices,
        lambda d: d.get("VendorID") == vendor_id and any(
            kw in d.get("DeviceName", "").upper() for kw in name_keywords
        ),
    )


def find_device_driver_version(devices, vendor_id: str, name_keywords):
    """Looks among devices for a match on VendorID and a name substring, returns DriverVersion."""
    device = find_device_by_vendor_and_keywords(devices, vendor_id, name_keywords)
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
    - NVIDIA's AjaxDriverService ReleaseDateTime (confirmed live):
      "Tue Jul 28, 2026"
    - Intel Download Center's lastModifieddate meta tag (confirmed live):
      "08/04/2026 08:00:00"
    - pnputil /enum-drivers' "Driver Version:" line (confirmed live):
      "04/16/2026"
    - ASUS's GetPDDrivers API INFDate field (confirmed live, ASUS B650
      board): "07-30-2026" — dash-separated, unlike everything else here
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

    for fmt in (
        "%Y/%m/%d", "%Y%m%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%a %b %d, %Y", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y",
        "%m-%d-%Y",
    ):
        try:
            # for the raw WMI format take only the first 8 characters (YYYYMMDD)
            candidate = raw[:8] if fmt == "%Y%m%d" else raw
            return datetime.strptime(candidate, fmt)
        except (ValueError, TypeError):
            continue
    return None


def report(label, latest, current, comparator=None, page_url=None, device_name=None, current_date=None):
    """
    Shared comparison logic. Returns a CheckResult; display_line/
    update_line are the exact text that's always been printed (doesn't
    print by itself — printing happens in main() after all the parallel
    checks finish, in a fixed order by category).

    page_url — when the site was reachable but no version could be
    extracted from it (e.g. a bot-protection challenge page served
    instead of the real content), a known fixed URL for the download
    page lets us point the user at it for a manual check instead of
    just saying "couldn't find a version".

    device_name — the actual hardware name (see build_result), when the
    caller has one; doesn't affect display_line/update_line text.

    current_date — the installed driver's release date (e.g. from WMI's
    DriverDate), when the caller has one. The available driver's date is
    picked up automatically from latest["date"] if the provider scraped
    one — the caller doesn't need to pass that part.
    """
    available_date = latest.get("date") if latest else None

    if latest is None:
        if page_url:
            suffix = f" (installed {current})" if current is not None else ""
            display_line = f"[{label}] automatic check unavailable{suffix} — visit the site manually: {page_url}"
            return build_result(
                label, display_line, current=current, status="Manual check", url=page_url, device_name=device_name,
                current_date=current_date,
            )
        if current is not None:
            display_line = f"[{label}] installed {current} (couldn't find a version to compare against on the site)"
            return build_result(
                label, display_line, current=current, status="Not found", device_name=device_name,
                current_date=current_date,
            )
        display_line = f"[{label}] could not find a version on the site to compare against"
        return build_result(label, display_line, status="Not found", device_name=device_name)

    if current is None:
        display_line = f"[{label}] on the site: {latest['version']} (couldn't compare against the installed version)"
        return build_result(
            label, display_line, available=latest["version"], status="Found (no comparison)",
            url=latest.get("page_url") or latest.get("url"), device_name=device_name, available_date=available_date,
        )

    is_match = comparator(current, latest["version"]) if comparator else (current == latest["version"])

    if is_match:
        display_line = f"[{label}] up to date ({latest['version']})"
        # same version on both sides means it's the same release — if only
        # one side's source happened to give us a (valid) date, show that
        # date on both instead of leaving the other side bare. Prefer
        # current_date only when it actually holds a real date — a
        # garbage/placeholder current_date shouldn't win over a genuinely
        # parseable available_date just because it's non-empty.
        shared_date = current_date if _parse_valid_date(current_date) else available_date
        return build_result(
            label, display_line, current=current, available=latest["version"], status="Up to date",
            # even when up to date, link to the source page if we have one —
            # lets the GUI table offer a "check it yourself" link on every
            # row, not just when an update was found
            url=latest.get("page_url") or latest.get("url"), device_name=device_name,
            current_date=shared_date, available_date=shared_date,
        )

    display_url = latest.get("page_url") or latest.get("url") or ""
    update_line = f"{label}: installed {current} -> available {latest['version']} ({display_url})"
    display_line = f"[{label}] UPDATE AVAILABLE: {current} -> {latest['version']}"
    return build_result(
        label, display_line, update_line, current=current, available=latest["version"],
        status="Download update", url=display_url or None, device_name=device_name,
        current_date=current_date, available_date=available_date,
    )

from checks.common import find_device, find_device_driver_version, safe_get_latest, report, parse_flexible_date, no_downgrade_match
from providers.realtek_lan import (
    RealtekLanProvider, realtek_versions_match, realtek_ndis_versions_match, detect_realtek_lan_variant,
)
from providers.realtek_wifi import RealtekWifiProvider
from providers.realtek_usb_lan import RealtekUsbLanProvider
from providers.intel_download import IntelDownloadCenterProvider
from providers.ms_catalog import MsCatalogProvider

INTEL_LAN_DOWNLOAD_ID = "15084"
INTEL_LAN_SLUG = "intel-ethernet-adapter-complete-driver-pack"

INTEL_WIFI_DOWNLOAD_ID = "19351"
INTEL_WIFI_SLUG = "intel-wireless-wi-fi-drivers-for-windows-10-and-windows-11"

INTEL_BLUETOOTH_DOWNLOAD_ID = "18649"
INTEL_BLUETOOTH_SLUG = "intel-wireless-bluetooth-drivers-for-windows-10-and-windows-11"


def check_realtek_lan(devices, board, laptop):
    provider_finder = RealtekLanProvider()  # only for matches(), not for get_latest()
    device = find_device(devices, provider_finder)
    if device is None:
        return None  # no Realtek network card in the system — silently skip, don't hit the site

    current = device.get("DriverVersion")
    variant = detect_realtek_lan_variant(current)

    # pick the SAME driver variant on the site (NDIS/NetAdapterCx) as
    # what's actually installed — this used to always take the
    # NetAdapterCx version, even if the machine had NDIS installed (or
    # vice versa), which made the comparison fundamentally meaningless
    # (comparing two different driver frameworks with different
    # numbering). Both variants are confirmed on real devices.
    if variant == "ndis":
        match_substrings = ("NDIS", "Not Support Power Saving")
        comparator = realtek_ndis_versions_match
    else:  # netadaptercx or unknown — use NetAdapterCx as before
        match_substrings = ("NetAdapterCx", "Not Support Power Saving")
        comparator = realtek_versions_match

    provider = RealtekLanProvider(match_substrings=match_substrings)
    ok, latest = safe_get_latest("Realtek LAN", provider)
    if not ok:
        return None

    if variant == "unknown":
        # unrecognized format (e.g. older 1GbE chips, where the version
        # ends with a year instead of a build number) — comparing
        # version numbers directly isn't safe; the fallback is by DATE,
        # which exists on both sides and doesn't depend on the specific
        # numbering quirks of a given chip generation.
        # IMPORTANT: the download link in this case is taken from the
        # NetAdapterCx variant (used as a reference point for the date)
        # — but for older chips with legacy version numbering this
        # specific file MAY TURN OUT TO BE INCOMPATIBLE (confirmed in
        # practice: installing it didn't change the version even after
        # a clean reinstall and reboot) — it's not guaranteed to be the
        # right package for that chip.
        installed_date = parse_flexible_date(device.get("DriverDate", ""))
        site_date = parse_flexible_date(latest.get("date", "")) if latest else None
        if installed_date and site_date:
            if (site_date - installed_date).days > 60:  # threshold to avoid noise on small discrepancies
                display = (
                    f"[Realtek LAN] possibly outdated (by date, not by version — comparison isn't reliable for "
                    f"this chip): installed driver from {installed_date.date()}, site has one from {site_date.date()}"
                )
                update_line = (
                    f"Realtek LAN: possibly outdated — installed driver from {installed_date.date()}, "
                    f"the whole LAN category on the site: https://www.realtek.com/Download/List?cate_id=584 "
                    f"(the auto-picked file may not be right for this specific chip — pick manually)"
                )
                return display, update_line
            return f"[Realtek LAN] up to date by date (installed driver from {installed_date.date()})", None
        current = None  # couldn't compare by either version or date

    return report("Realtek LAN", latest, current, comparator=comparator)


def check_realtek_wifi(devices, board, laptop):
    """
    Realtek WLAN chips (RTL8723/RTL8821/RTL8822, etc.) — a separate
    category on Realtek's site (cate_id=673). We don't do an automatic
    version comparison yet (current=None) — it hasn't been confirmed on
    real data that the Windows version format is comparable to the
    site's format (the way it was worked out for LAN on a specific chip).
    """
    provider = RealtekWifiProvider()
    device = find_device(devices, provider)
    if device is None:
        return None

    ok, latest = safe_get_latest("Realtek WiFi", provider)
    if not ok:
        return None
    return report("Realtek WiFi", latest, current=None)


def check_realtek_usb_lan(devices, board, laptop):
    """
    External USB Ethernet adapters/dongles from Realtek — a separate
    category (cate_id=585) from built-in PCIe chips. Also without an
    automatic version comparison (see check_realtek_wifi).
    """
    provider = RealtekUsbLanProvider()
    device = find_device(devices, provider)
    if device is None:
        return None

    ok, latest = safe_get_latest("Realtek USB LAN", provider)
    if not ok:
        return None
    return report("Realtek USB LAN", latest, current=None)


def check_intel_lan(devices, board, laptop):
    current = find_device_driver_version(
        devices, "8086", ("ETHERNET", "I219", "I225", "I226", "I210", "I350")
    )
    if current is None:
        return None  # no Intel network card in the system — silently skip

    provider = IntelDownloadCenterProvider(
        download_id=INTEL_LAN_DOWNLOAD_ID, slug=INTEL_LAN_SLUG, name="intel_lan"
    )
    ok, latest = safe_get_latest("Intel LAN", provider)
    if not ok:
        return None
    # the "Complete Driver Pack" is a single package for all models, its
    # version doesn't always match 1:1 with the version of the specific
    # installed driver
    return report("Intel LAN", latest, current=None)


def check_intel_wifi(devices, board, laptop):
    current = find_device_driver_version(devices, "8086", ("WI-FI", "WIRELESS"))
    if current is None:
        return None  # no Intel WiFi card in the system — silently skip

    provider = IntelDownloadCenterProvider(
        download_id=INTEL_WIFI_DOWNLOAD_ID, slug=INTEL_WIFI_SLUG, name="intel_wifi"
    )
    ok, latest = safe_get_latest("Intel WiFi", provider)
    if not ok:
        return None
    # the official Intel page is more reliable than a laptop vendor's
    # repackaged version — but we still don't suggest a "downgrade" if
    # the installed version is already newer than what the site shows
    # (happens when the site just hasn't caught up yet)
    return report("Intel WiFi", latest, current, comparator=no_downgrade_match)


def check_intel_bluetooth(devices, board, laptop):
    # IMPORTANT: Intel Bluetooth devices in Windows are listed under a
    # DIFFERENT PCI/USB Vendor ID — 8087, not 8086 (which is used for
    # WiFi/chipset/GPU) — confirmed on a real device.
    current = find_device_driver_version(devices, "8087", ("BLUETOOTH",))
    if current is None:
        return None  # no Intel Bluetooth module in the system — silently skip

    provider = IntelDownloadCenterProvider(
        download_id=INTEL_BLUETOOTH_DOWNLOAD_ID, slug=INTEL_BLUETOOTH_SLUG, name="intel_bluetooth"
    )
    ok, latest = safe_get_latest("Intel Bluetooth", provider)
    if not ok:
        return None
    return report("Intel Bluetooth", latest, current, comparator=no_downgrade_match)


def check_bluetooth_via_windows_update(devices, board, laptop):
    """
    For non-Intel Bluetooth modules (Qualcomm, MediaTek, etc.) — the
    same logic as for WiFi (check_wifi_via_windows_update): most such
    vendors don't have a separate official downloads page, so the only
    official source is the Microsoft Update Catalog.
    """
    bt_device = find_device(
        devices,
        lambda d: d.get("VendorID") not in ("8086", "8087") and "BLUETOOTH" in d.get("DeviceName", "").upper(),
    )
    if bt_device is None:
        return None  # Intel is already covered by check_intel_bluetooth, no other Bluetooth modules

    device_name = bt_device.get("DeviceName", "")
    current = bt_device.get("DriverVersion")

    provider = MsCatalogProvider(query=device_name, name="bluetooth_windows_update")
    ok, latest = safe_get_latest(f"Bluetooth ({device_name})", provider)
    if not ok:
        return None

    # searching by the device name string doesn't guarantee an exact
    # match to the right variant (see the MediaTek WiFi story above) —
    # we don't suggest a "downgrade"
    return report(f"Bluetooth ({device_name})", latest, current, comparator=no_downgrade_match)


def check_wifi_via_windows_update(devices, board, laptop):
    """
    For non-Intel WiFi chips (Qualcomm, some MediaTek, etc.) that don't
    have a separate official downloads page from the maker — drivers are
    only distributed via Windows Update. The only official source in
    this case is the Microsoft Update Catalog; we search by the exact
    device name reported by Windows.
    """
    wifi_device = find_device(
        devices,
        lambda d: d.get("VendorID") not in ("8086", "8087", "10EC")
        and "BLUETOOTH" not in d.get("DeviceName", "").upper()  # "Wireless" also matches Bluetooth devices
        and any(kw in d.get("DeviceName", "").upper() for kw in ("WI-FI", "WIRELESS", "WLAN")),
    )
    if wifi_device is None:
        return None  # Intel is already covered by check_intel_wifi, no other WiFi chips

    device_name = wifi_device.get("DeviceName", "")
    current = wifi_device.get("DriverVersion")

    provider = MsCatalogProvider(query=device_name, name="wifi_windows_update")
    ok, latest = safe_get_latest(f"WiFi ({device_name})", provider)
    if not ok:
        return None

    # searching by the device name string doesn't guarantee an exact
    # match to the right variant — same as with OEM pages, we don't
    # suggest a "downgrade"
    return report(f"WiFi ({device_name})", latest, current, comparator=no_downgrade_match)

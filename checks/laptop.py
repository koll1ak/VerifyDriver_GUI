import sys

from net_utils import classify_error
from scanner import get_devices_by_id_pattern
from checks.common import (
    find_device, find_device_driver_version, laptop_model_if_vendor, safe_get_latest, report, no_downgrade_match,
)
from providers.dell_support import dell_drivers_url
from providers.acer_support import AcerSupportProvider
from providers.huawei_support import huawei_search_url
from providers.lenovo_support import LenovoSupportProvider
from providers.hp_support import HpSupportProvider
from providers.msi_bios import get_current_bios_version
from providers.msi_laptop import MsiLaptopBiosProvider, MsiLaptopDriverProvider
from providers.gigabyte_laptop import GigabyteLaptopProvider
from providers.lg_support import LgSupportProvider
from providers.asus_bios import AsusBiosProvider
from providers.asus_laptop_driver import AsusLaptopDriverProvider


def _asus_laptop_bios_versions_match(current: str, latest: str) -> bool:
    """
    Windows reports the ASUS laptop BIOS version with a model-code
    prefix (e.g. "S5606CA.312"), while the site only shows the build
    number ("313" or "312"). We take the tail after the last dot of the
    installed version and compare it against the site's version directly.
    """
    if not current or not latest:
        return False
    current_tail = current.split(".")[-1].strip()
    return current_tail == latest.strip()


def _acer_bios_versions_match(current: str, latest: str) -> bool:
    """
    Windows reports the Acer BIOS version with a "V" prefix (e.g.
    "V2.06"), the site shows it without one ("2.06") — strip the prefix
    from both sides before comparing.
    """
    if not current or not latest:
        return False
    strip_v = lambda s: s.upper().lstrip("V")
    return strip_v(current) == strip_v(latest)


def _acer_lan_versions_match(current: str, latest: str) -> bool:
    """
    The site gives the version with a leading zero in one of the
    segments (e.g. "10.038.1118.2019"), Windows shows it without one
    ("10.38.1118.2019") — strip leading zeros from every segment before
    comparing.
    """
    if not current or not latest:
        return False

    def _norm(v: str) -> str:
        try:
            return ".".join(str(int(p)) for p in v.split("."))
        except ValueError:
            return v

    return _norm(current) == _norm(latest)


def check_dell_bios(devices, board, laptop):
    """
    Dell laptops only (detected independently of board_detect.py, which
    is built for desktop boards) — by the device's Service Tag.
    Automatic checking isn't possible: Dell's site is confirmed blocked
    by Akamai (403 with or without curl_cffi's Chrome impersonation, see
    providers/dell_support.py) — same situation as Huawei BIOS, so we
    just link to the drivers page for a manual check instead.
    """
    tag = laptop_model_if_vendor(laptop, "DELL", "dell_service_tag")
    if tag is None:
        return None

    url = dell_drivers_url(tag)
    if url is None:
        return None
    return f"[Dell BIOS] automatic check unavailable — visit the site manually: {url}", None


def check_dell_audio(devices, board, laptop):
    """Same as check_dell_bios, but for the Audio category — Dell has no
    other source for laptop audio (unlike WiFi/Bluetooth, which still
    get the Windows Update Catalog fallback)."""
    tag = laptop_model_if_vendor(laptop, "DELL", "dell_service_tag")
    if tag is None:
        return None

    url = dell_drivers_url(tag)
    if url is None:
        return None
    return f"[Dell Audio] automatic check unavailable — visit the site manually: {url}", None


def check_acer_bios(devices, board, laptop):
    """
    Acer laptops only — by ModelName (Win32_ComputerSystem.Model without
    the product-line prefix). API structure confirmed on real data
    (Acer Nitro AN515-55) — as reliable as the desktop providers.
    """
    model_name = laptop_model_if_vendor(laptop, "ACER", "acer_model_name")
    if model_name is None:
        return None

    provider = AcerSupportProvider(
        model_name=model_name, category="BIOS",
        part_number=laptop.get("acer_part_number"), serial=laptop.get("acer_serial"),
        name="acer_bios",
    )
    ok, latest = safe_get_latest("Acer BIOS", provider)
    if not ok:
        return None
    # Acer's BIOS version is in a plain format ("2.06"), not tied to the
    # board model (unlike MSI) — but Windows adds a "V" prefix (V2.06)
    # that isn't on the site, so we compare via a separate comparator
    return report("Acer BIOS", latest, get_current_bios_version(), comparator=_acer_bios_versions_match)


def check_acer_audio(devices, board, laptop):
    """Same as check_acer_bios, but for the Audio category (with an OS filter)."""
    model_name = laptop_model_if_vendor(laptop, "ACER", "acer_model_name")
    if model_name is None:
        return None

    provider = AcerSupportProvider(
        model_name=model_name, category="Audio",
        part_number=laptop.get("acer_part_number"), serial=laptop.get("acer_serial"),
        name="acer_audio",
    )
    ok, latest = safe_get_latest("Acer Audio", provider)
    if not ok:
        return None
    # try to compare against the installed version — if a proper Realtek
    # branded driver is actually installed (not the generic Windows
    # driver), the versions might match directly (a format like
    # "6.0.9180.1" looks like what Windows shows for an installed
    # Realtek package)
    current = find_device_driver_version(devices, "10EC", ("AUDIO",)) or \
        find_device_driver_version(devices, "0BDA", ("AUDIO",))

    if current is None:
        # Win32_PnPSignedDriver sometimes doesn't see the audio device
        # (same as on desktop with a USB codec) — fallback lookup via
        # Get-PnpDevice
        try:
            fallback_devices = get_devices_by_id_pattern("VEN_10EC")
        except Exception as e:
            print(f"[Acer Audio] fallback lookup error: {classify_error(e)}", file=sys.stderr)
            fallback_devices = []
        audio_device = find_device(fallback_devices, lambda d: "AUDIO" in d.get("DeviceName", "").upper())
        current = audio_device.get("DriverVersion") if audio_device else None

    if latest and latest.get("os_mismatch"):
        # Acer's catalog has no separate entry for the installed OS — we
        # show what we found, but don't claim "update available" since
        # we're not sure the version is actually meant for this OS
        return f"[Acer Audio] on the site (different OS in the catalog): {latest['version']} — comparison isn't reliable", None

    return report("Acer Audio", latest, current)


def check_acer_lan(devices, board, laptop):
    """Same as check_acer_audio, but for the Lan category."""
    model_name = laptop_model_if_vendor(laptop, "ACER", "acer_model_name")
    if model_name is None:
        return None

    # if the network chip is Realtek or Intel, those are already covered
    # by the official checks (check_realtek_lan / check_intel_lan) — we
    # don't duplicate them, and we don't substitute a version from
    # Acer's repackaged page instead of the chip vendor's official source
    has_realtek_lan = find_device(
        devices, lambda d: d.get("VendorID") == "10EC" and "FAMILY CONTROLLER" in d.get("DeviceName", "").upper()
    ) is not None
    has_intel_lan = find_device_driver_version(
        devices, "8086", ("ETHERNET", "I219", "I225", "I226", "I210", "I350")
    ) is not None
    if has_realtek_lan or has_intel_lan:
        return None

    provider = AcerSupportProvider(
        model_name=model_name, category="Lan",
        part_number=laptop.get("acer_part_number"), serial=laptop.get("acer_serial"),
        name="acer_lan",
    )
    ok, latest = safe_get_latest("Acer LAN", provider)
    if not ok:
        return None

    # look for a network adapter — Killer/Realtek/Intel, on Acer it's
    # most often Killer (sometimes actually a rebranded Realtek chip
    # under their brand)
    current = find_device_driver_version(devices, "10EC", ("ETHERNET", "GIGABIT", "KILLER")) or \
        find_device_driver_version(devices, "8086", ("ETHERNET", "I219", "I225", "I226"))

    if current is None:
        # the same fallback path as for audio, in case
        # Win32_PnPSignedDriver doesn't see the device directly
        try:
            fallback_devices = get_devices_by_id_pattern("VEN_10EC")
        except Exception as e:
            print(f"[Acer LAN] fallback lookup error: {classify_error(e)}", file=sys.stderr)
            fallback_devices = []
        lan_device = find_device(
            fallback_devices,
            lambda d: any(kw in d.get("DeviceName", "").upper() for kw in ("ETHERNET", "GIGABIT", "KILLER")),
        )
        current = lan_device.get("DriverVersion") if lan_device else None

    if latest and latest.get("os_mismatch"):
        return f"[Acer LAN] on the site (different OS in the catalog): {latest['version']} — comparison isn't reliable", None

    return report("Acer LAN", latest, current, comparator=_acer_lan_versions_match)


def check_asus_laptop_bios(devices, board, laptop):
    """
    ASUS laptop — reuses the same AsusBiosProvider as desktop ASUS
    boards (same site/page structure), just the model comes from
    Win32_ComputerSystem.Model instead of Win32_BaseBoard.
    """
    model = laptop_model_if_vendor(laptop, "ASUS", "asus_laptop_model")
    if model is None:
        return None

    ok, latest = safe_get_latest("ASUS BIOS", AsusBiosProvider(model=model))
    if not ok:
        return None
    # try comparing directly — the ASUS format hasn't been verified; if
    # it doesn't match, we'll sort it out from real data (as with
    # Acer/MSI earlier)
    return report("ASUS BIOS", latest, get_current_bios_version(), comparator=_asus_laptop_bios_versions_match)


def check_asus_laptop_audio(devices, board, laptop):
    """Same as check_asus_laptop_bios, but for the Audio (Realtek)
    category — via the official JSON API (providers/asus_laptop_driver.py),
    since the laptop page loads the driver list via JS instead of
    returning it directly in the HTML (unlike the BIOS page)."""
    model = laptop_model_if_vendor(laptop, "ASUS", "asus_laptop_model")
    if model is None:
        return None

    provider = AsusLaptopDriverProvider(model=model, category="Audio", match_substrings=("Realtek",), name="asus_laptop_audio")
    ok, latest = safe_get_latest("ASUS Audio", provider)
    if not ok:
        return None
    if latest is None:
        return None

    current = find_device_driver_version(devices, "10EC", ("AUDIO",)) or \
        find_device_driver_version(devices, "0BDA", ("AUDIO",))

    if current is None:
        try:
            fallback_devices = get_devices_by_id_pattern("VEN_10EC")
        except Exception as e:
            print(f"[ASUS Audio] fallback lookup error: {classify_error(e)}", file=sys.stderr)
            fallback_devices = []
        audio_device = find_device(fallback_devices, lambda d: "AUDIO" in d.get("DeviceName", "").upper())
        current = audio_device.get("DriverVersion") if audio_device else None

    return report("ASUS Audio", latest, current)


def check_asus_laptop_networking(devices, board, laptop):
    """
    ASUS's "Networking" category lumps WiFi/Bluetooth/LAN together.
    If the WiFi chip is Intel, we skip this check entirely: the
    official Intel page is more reliable and accurate than ASUS's
    repackaged version (confirmed in practice — the ASUS page lagged
    behind Intel), and check_intel_wifi already covers it. We check via
    ASUS only when the WiFi chip is NOT Intel (MediaTek/Realtek/Killer,
    etc.), for which we don't have a separate direct source.
    """
    model = laptop_model_if_vendor(laptop, "ASUS", "asus_laptop_model")
    if model is None:
        return None

    has_any_wifi = find_device(
        devices, lambda d: any(kw in d.get("DeviceName", "").upper() for kw in ("WI-FI", "WIRELESS", "WLAN"))
    ) is not None
    has_realtek_lan = find_device(
        devices, lambda d: d.get("VendorID") == "10EC" and "FAMILY CONTROLLER" in d.get("DeviceName", "").upper()
    ) is not None
    if has_any_wifi or has_realtek_lan:
        return None  # already covered by check_intel_wifi/check_wifi_via_windows_update/check_realtek_lan

    provider = AsusLaptopDriverProvider(
        model=model, category="Networking", match_substrings=(), name="asus_laptop_networking"
    )
    ok, latest = safe_get_latest("ASUS Networking", provider)
    if not ok:
        return None
    if latest is None:
        return None

    current = find_device_driver_version(devices, "8086", ("WI-FI",))
    return report("ASUS Networking", latest, current, comparator=no_downgrade_match)


def check_huawei_bios(devices, board, laptop):
    """
    There's no official chip-maker source for Huawei laptop BIOS (unlike
    components such as WiFi/Chipset — BIOS is always written by the
    laptop vendor, not Intel/Realtek) — we just give a link to search
    Huawei's site manually, without an automatic comparison.
    """
    if not laptop.get("is_laptop") or "HUAWEI" not in (laptop.get("manufacturer") or "").upper():
        return None

    url = huawei_search_url(laptop.get("model"))
    if url is None:
        return None
    return f"[Huawei BIOS] automatic check unavailable — visit the site manually: {url}", None


def check_lenovo_bios(devices, board, laptop):
    """
    Lenovo laptops only — a two-step resolution via the
    pcsupport.lenovo.com API (serial -> product slug -> driver list, see
    providers/lenovo_support.py). NOT VERIFIED on a real device.
    """
    serial = laptop_model_if_vendor(laptop, "LENOVO", "lenovo_serial")
    if serial is None:
        return None

    provider = LenovoSupportProvider(serial=serial, category="BIOS", name="lenovo_bios")
    ok, latest = safe_get_latest("Lenovo BIOS", provider)
    if not ok:
        return None
    # no comparison against the installed version — it hasn't been
    # verified what format Windows actually reports for Lenovo BIOS
    # compared to the site
    return report("Lenovo BIOS", latest, current=None)


def check_lenovo_audio(devices, board, laptop):
    """Same as check_lenovo_bios, but for the Audio category."""
    serial = laptop_model_if_vendor(laptop, "LENOVO", "lenovo_serial")
    if serial is None:
        return None

    provider = LenovoSupportProvider(serial=serial, category="Audio", name="lenovo_audio")
    ok, latest = safe_get_latest("Lenovo Audio", provider)
    if not ok:
        return None
    return report("Lenovo Audio", latest, current=None)


def check_hp_bios(devices, board, laptop):
    """
    HP laptops only — resolved by searching support.hp.com's own
    product search with the machine's marketing model name (no simpler
    ID confirmed without a real serial, see providers/hp_support.py).
    NOT VERIFIED on a real device, though every API step was confirmed
    live against a real current HP product.

    Doesn't use laptop_model_if_vendor(laptop, "HP", ...): that helper
    re-checks the vendor keyword against Manufacturer, but "HP" isn't a
    substring of "Hewlett-Packard" (the Manufacturer string on older
    devices) — hp_model is already correctly gated by both spellings in
    laptop_detect.py, so re-checking here would wrongly skip those.
    """
    if not laptop.get("is_laptop"):
        return None
    model = laptop.get("hp_model")
    if model is None:
        return None

    provider = HpSupportProvider(model_name=model, category="BIOS", name="hp_bios")
    ok, latest = safe_get_latest("HP BIOS", provider)
    if not ok:
        return None
    # no comparison against the installed version — HP's version is an
    # alphanumeric build code (e.g. "F.17 Rev.A"), not a dotted number,
    # same situation as Dell/Gigabyte/ASRock/Lenovo BIOS
    return report("HP BIOS", latest, current=None)


def check_hp_audio(devices, board, laptop):
    """Same as check_hp_bios, but for the Audio category (see its
    docstring for why laptop_model_if_vendor isn't used here)."""
    if not laptop.get("is_laptop"):
        return None
    model = laptop.get("hp_model")
    if model is None:
        return None

    provider = HpSupportProvider(model_name=model, category="Driver-Audio", name="hp_audio")
    ok, latest = safe_get_latest("HP Audio", provider)
    if not ok:
        return None
    # confirmed live the version has a dotted-number prefix (e.g.
    # "6.0.9712.1 Rev.C") that COULD be comparable to WMI's
    # DriverVersion format, but this hasn't been confirmed against a
    # real installed driver, so no comparison is attempted yet
    return report("HP Audio", latest, current=None)


def check_msi_laptop_bios(devices, board, laptop):
    """
    MSI laptops only — Win32_BaseBoard is unreliable on laptops (same
    reason check_bios in checks/bios.py is desktop-only), so this uses
    the machine's marketing model name via providers/msi_laptop.py
    instead of the board slug the desktop MSI check uses.
    NOT VERIFIED on a real device — the confirmed-live API calls are
    the same ones used successfully for desktop boards, but WMI's exact
    Model string format on a real MSI laptop isn't confirmed (see
    providers/msi_laptop.py risk #1).

    Doesn't use laptop_model_if_vendor(laptop, "MSI", ...): same reason
    as check_hp_bios — "MSI" isn't necessarily a substring of the full
    Manufacturer string ("Micro-Star International Co., Ltd."), while
    msi_laptop_model is already correctly gated in laptop_detect.py.
    """
    if not laptop.get("is_laptop"):
        return None
    model = laptop.get("msi_laptop_model")
    if model is None:
        return None

    provider = MsiLaptopBiosProvider(model_slug=model)
    ok, latest = safe_get_latest("MSI Laptop BIOS", provider)
    if not ok:
        return None
    # no comparison against the installed version — MSI laptop BIOS
    # versions (e.g. "E1585IMS.11C") don't match the desktop
    # comparator's "tail after 'v'" format, and no real device is
    # available to confirm what Windows actually reports here
    return report("MSI Laptop BIOS", latest, current=None)


def check_msi_laptop_audio(devices, board, laptop):
    """Same as check_msi_laptop_bios, but for the Audio category."""
    if not laptop.get("is_laptop"):
        return None
    model = laptop.get("msi_laptop_model")
    if model is None:
        return None

    provider = MsiLaptopDriverProvider(model_slug=model, category_keyword="AUDIO", name="msi_laptop_audio")
    ok, latest = safe_get_latest("MSI Laptop Audio", provider)
    if not ok:
        return None

    current = find_device_driver_version(devices, "10EC", ("AUDIO",)) or \
        find_device_driver_version(devices, "0BDA", ("AUDIO",))

    # confirmed live the version (e.g. "6.0.9597.1") is in the same
    # dotted format WMI reports, so a direct comparison is meaningful
    return report("MSI Laptop Audio", latest, current)


def check_gigabyte_laptop_bios(devices, board, laptop):
    """
    GIGABYTE/AORUS laptops only — resolved by searching GIGABYTE's own
    site search with the machine's marketing model name (no simpler ID
    confirmed without a real serial, see providers/gigabyte_laptop.py).
    NOT VERIFIED on a real device, though every API step was confirmed
    live against a real current GIGABYTE laptop.
    """
    model = laptop_model_if_vendor(laptop, "GIGABYTE", "gigabyte_laptop_model")
    if model is None:
        return None

    provider = GigabyteLaptopProvider(model_name=model, category="bios", name="gigabyte_laptop_bios")
    ok, latest = safe_get_latest("GIGABYTE Laptop BIOS", provider)
    if not ok:
        return None
    # no comparison against the installed version — GIGABYTE laptop
    # BIOS versions (e.g. "FB13") are a short alphanumeric build code,
    # not a dotted number, same situation as Dell/ASRock/Lenovo/HP/MSI
    return report("GIGABYTE Laptop BIOS", latest, current=None)


def check_gigabyte_laptop_audio(devices, board, laptop):
    """Same as check_gigabyte_laptop_bios, but for the Audio category."""
    model = laptop_model_if_vendor(laptop, "GIGABYTE", "gigabyte_laptop_model")
    if model is None:
        return None

    provider = GigabyteLaptopProvider(
        model_name=model, category="driver", match_substrings=("Audio",), name="gigabyte_laptop_audio",
    )
    ok, latest = safe_get_latest("GIGABYTE Laptop Audio", provider)
    if not ok:
        return None

    current = find_device_driver_version(devices, "10EC", ("AUDIO",)) or \
        find_device_driver_version(devices, "0BDA", ("AUDIO",))

    # confirmed live the version (e.g. "6.0.9679.1") is in the same
    # dotted format WMI reports, so a direct comparison is meaningful
    return report("GIGABYTE Laptop Audio", latest, current)


def check_samsung_bios(devices, board, laptop):
    """
    Samsung laptops only. Samsung distributes driver/firmware updates
    through its official "Samsung Download Center" desktop application
    rather than a straightforward web download page — confirmed live
    that the web support portal's download modal (support.samsung.com,
    reached via /us/support/computing/windows-laptops/?modelCode=...)
    doesn't render any usable content in an automated browser session,
    even after using its own internal search box. Given that, and that
    there's no simpler API found, we just point at the official app
    instead of attempting a check that doesn't work.
    """
    if not laptop.get("is_laptop") or "SAMSUNG" not in (laptop.get("manufacturer") or "").upper():
        return None
    return '[Samsung BIOS] automatic check unavailable — download and visit the "Samsung Download Center" application', None


def check_samsung_audio(devices, board, laptop):
    """Same as check_samsung_bios, but for the Audio category."""
    if not laptop.get("is_laptop") or "SAMSUNG" not in (laptop.get("manufacturer") or "").upper():
        return None
    return '[Samsung Audio] automatic check unavailable — download and visit the "Samsung Download Center" application', None


def check_lg_bios(devices, board, laptop):
    """
    LG (gram) laptops only. Confirmed live (see providers/lg_support.py)
    that gram laptops don't offer a standalone downloadable BIOS file
    through the support site at all — BIOS updates are folded into the
    "LG Update" auto-updater tool instead. Rather than attempt a check
    that's confirmed to never find anything, we just point at that tool.
    """
    if not laptop.get("is_laptop") or "LG" not in (laptop.get("manufacturer") or "").upper():
        return None
    return '[LG BIOS] latest BIOS can be checked in the "LG Update" application', None


def check_lg_audio(devices, board, laptop):
    """Same as check_lg_bios, but for the Audio category."""
    model = laptop_model_if_vendor(laptop, "LG", "lg_model")
    if model is None:
        return None

    provider = LgSupportProvider(base_model=model, category="Audio", name="lg_audio")
    ok, latest = safe_get_latest("LG Audio", provider)
    if not ok:
        return None

    current = find_device_driver_version(devices, "10EC", ("AUDIO",)) or \
        find_device_driver_version(devices, "0BDA", ("AUDIO",))

    # comparison attempted since the version format (e.g. "24.10.0.4",
    # extracted from the title's "Ver.X" suffix) looks WMI-comparable
    # for other categories, but this hasn't been confirmed for an
    # actual Audio entry specifically (none was found in live testing)
    return report("LG Audio", latest, current)

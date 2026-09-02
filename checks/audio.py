import sys

from net_utils import classify_error
from scanner import get_devices_by_id_pattern
from checks.common import (
    find_device, find_device_driver_version, find_device_by_vendor_and_keywords, safe_get_latest, report,
    no_downgrade_match, overall_drivers_page_url, manual_check_unavailable, resolve_device_name,
    parse_flexible_date, build_result,
)
from providers.msi_driver import MsiDriverProvider, get_installed_inf_version, get_installed_inf_date
from providers.gigabyte_driver import GigabyteDriverProvider
from providers.asus_driver import AsusDriverProvider
from providers.senary_audio import SenaryAudioProvider, PAGE_URL as SENARY_PAGE_URL, resolve_chip_code
from providers.ms_catalog import MsCatalogProvider, catalog_search_url


def _find_audio_device(devices):
    """
    Looks for an audio codec (usually Realtek, VendorID 10EC — the
    classic PCI/HDAUDIO one, 0BDA — newer codecs like the ALC4080 via a
    built-in USB interface).
    """
    audio_device = find_device(
        devices,
        lambda d: d.get("VendorID") in ("10EC", "0BDA") and "AUDIO" in d.get("DeviceName", "").upper()
        and (d.get("DeviceClass") or "").upper() == "MEDIA",
    )
    if audio_device is None:
        # Win32_PnPSignedDriver sometimes doesn't see the audio function
        # of a composite USB device (as with the Realtek USB2.0 Audio,
        # ALC4080) — try a fallback lookup via Get-PnpDevice by Realtek's
        # Vendor ID
        try:
            fallback_devices = get_devices_by_id_pattern("VID_0BDA")
        except Exception as e:
            print(f"[Audio] fallback lookup error: {classify_error(e)}", file=sys.stderr)
            fallback_devices = []
        audio_device = find_device(
            fallback_devices,
            lambda d: "AUDIO" in d.get("DeviceName", "").upper() and (d.get("DeviceClass") or "").upper() == "MEDIA",
        )
    return audio_device


_AUDIO_CHIP_VENDOR_NAMES = {"10EC": "Realtek", "0BDA": "Realtek"}


def _audio_display_name(device):
    """
    Windows' generic inbox USB Audio class driver reports a bare class
    name like "USB Audio 2.0" (confirmed live: Manufacturer field shows
    "Microsoft", not the actual chip vendor) instead of a vendor-branded
    one. Display only — callers that also use the device name as a
    search query (e.g. the Windows Update Catalog lookup) must keep
    using the raw, unprefixed name for that.

    Tries the shared hardware-ID-database resolution first (see
    checks.common.resolve_device_name), for devices truly stuck on
    Windows' generic/inbox driver (the exact placeholder DriverDate) —
    if that finds something, it's used as-is. Otherwise falls back to
    the original vendor-prefix heuristic below, unchanged: prefix the
    known chip vendor (from VendorID) when the name doesn't already
    mention it, so the table still shows which vendor's chip this is,
    even for names resolve_device_name's placeholder-date gate doesn't
    catch.

    Devices found via _find_audio_device's Get-PnpDevice fallback
    (composite USB audio devices Win32_PnPSignedDriver misses — see
    scanner.get_devices_by_id_pattern) get a DriverDate the same way as
    everything else, via DEVPKEY_Device_DriverDate, so resolve_device_name
    applies to them too.
    """
    if not device:
        return None
    name = device.get("DeviceName", "")
    resolved = resolve_device_name(device)
    if resolved != name:
        return resolved
    vendor = _AUDIO_CHIP_VENDOR_NAMES.get(device.get("VendorID"))
    if vendor and name and vendor.upper() not in name.upper():
        return f"{vendor} {name}"
    return name


def _check_audio_via_windows_update(audio_device):
    """
    Fallback path for when the board isn't from one of the known vendors
    (MSI/Gigabyte/ASRock/ASUS) or its page has no Audio category.
    This used to be Realtek's site — removed: the last update there was
    back in 2022, not a viable source for an up-to-date check. Instead
    we use the Microsoft Update Catalog: the WHQL builds Realtek itself
    submits to Windows Update actually do get updated.

    Takes the already-resolved audio device (see check_audio) rather
    than re-discovering it — _find_audio_device() can shell out to
    PowerShell on its fallback path, not worth paying for twice.
    """
    if audio_device is None:
        return None  # no audio codec in the system — silently skip

    # the raw, unprefixed name — used for the label, the catalog search
    # query, and the manual-search link, all of which need to match what
    # Windows/the catalog actually call this device
    device_name = audio_device.get("DeviceName", "")
    current = audio_device.get("DriverVersion")

    provider = MsCatalogProvider(query=device_name, name="audio_windows_update")
    ok, latest = safe_get_latest(f"Audio ({device_name})", provider)
    if not ok:
        latest = None

    # searching by the device name string doesn't guarantee an exact
    # match to the right variant — same as with WiFi/Bluetooth via
    # Windows Update, we don't suggest a "downgrade"
    return report(
        f"Audio ({device_name})", latest, current, comparator=no_downgrade_match,
        page_url=catalog_search_url(device_name), device_name=_audio_display_name(audio_device),
        current_date=audio_device.get("DriverDate"),
    )


def _check_vendor_audio_driver(
    board, vendor, slug_field, provider_factory, label, current_version_getter=None, current_date_getter=None,
    device_name=None,
):
    """
    Shared pattern for vendor-specific desktop-board audio drivers
    (MSI/Gigabyte/ASRock/ASUS) — they only differ in the provider class,
    the slug/model field in board, and (only for MSI) how the installed
    version is obtained for comparison.

    Returns (found, result, blocked):
      found — True if the check applies at all and found something on
              the site (regardless of whether there's an update or
              everything is current) — used to decide whether the
              generic Windows Update fallback is still needed;
      result — a (display, update) tuple from report(), or None.
      blocked — True specifically when the vendor's own page couldn't be
                reached/parsed at all (network error, blocked, 5xx, ...)
                — distinct from the page loading fine but simply having
                no "Audio" category, which isn't a reachability problem
                and should still fall through to the generic fallback.
    """
    if board.get("vendor") != vendor:
        return False, None, False

    slug = board.get(slug_field)
    if slug is None:
        return False, None, False

    provider = provider_factory(slug)
    ok, latest = safe_get_latest(label, provider)
    if not ok:
        return False, None, True
    if latest is None:
        return False, None, False  # this board's page has no "Audio" category

    current = current_version_getter() if current_version_getter else None
    current_date = current_date_getter() if current_date_getter else None
    return True, report(label, latest, current, device_name=device_name, current_date=current_date), False


def check_audio(devices, board, laptop):
    """
    A driver customized for the specific board vendor (MSI/Gigabyte/
    ASUS) takes priority — it more accurately reflects what should
    actually be installed on that specific board. ASRock is handled
    separately below (always a manual link, see the ASRock branch) —
    its site is confirmed unreachable, not just imprecise.

    If the board IS from MSI/Gigabyte/ASUS but its page couldn't be
    reached at all (blocked/network error), we don't fall back to the
    Windows Update Catalog search — confirmed live that it's not a
    reliable source for Realtek audio specifically, since virtually
    every Realtek codec reports the same generic Windows device name
    ("Realtek High Definition Audio"), which only ever turns up old
    versionless catalog entries (see providers/ms_catalog.py). Instead
    we point at the vendor's overall drivers page for a manual check.

    Windows Update is still tried when no vendor-specific path applies
    at all (the board isn't from one of these vendors) or the vendor's
    site loads fine but simply has nothing under the audio category —
    neither of those is a reachability problem.

    This function should never run on a laptop: Win32_BaseBoard (which
    desktop board vendor detection relies on) often returns garbage on
    laptops — and for some vendors (e.g. ASUS) the Manufacturer field
    matches both desktop boards and laptops, which could accidentally
    match the wrong model or duplicate output with
    check_acer_audio/check_asus_laptop_audio/check_dell_audio. The real
    vendor-specific checks for laptops are separate functions.
    """
    if laptop.get("is_laptop"):
        return None

    audio_device = _find_audio_device(devices)
    device_name = _audio_display_name(audio_device)

    if board.get("vendor") == "asrock" and board.get("asrock_model"):
        # automatic checking isn't possible: confirmed live that ASRock's
        # site is blocked by Incapsula (a JS-challenge bot-protection
        # system that even curl_cffi's Chrome TLS impersonation can't
        # get past — same limitation this project already hit for
        # Huawei) and, worse, the block returns HTTP 200 with a fake
        # page instead of a clean error, so the old scraping-based
        # AsrockDriverProvider would silently look like "board not
        # found" instead of "blocked". Same fix as checks/bios.py's
        # ASRock branch and Dell: a manual link instead of a check that
        # can never actually succeed.
        url = overall_drivers_page_url(board, laptop)
        return manual_check_unavailable("ASRock Audio Driver", url, device_name=device_name)

    vendor_configs = [
        dict(
            vendor="msi", slug_field="msi_slug", label="MSI Audio Driver",
            provider_factory=lambda slug: MsiDriverProvider(
                product_slug=slug, category_keyword="AUDIO", name="msi_audio"
            ),
            # the driver version of the specific device (via the scanner)
            # is the version of the active Windows class driver, not the
            # version of the package in the Driver Store. We get the
            # actual installed MSI/Realtek package version separately —
            # "rtdusbad" is the stable part of the INF name for Realtek
            # USB Audio on MSI boards specifically — it won't match the
            # far more common PCI/HDA "Realtek High Definition Audio"
            # codec (confirmed live: pnputil finds no "rtdusbad" INF at
            # all in that case, silently leaving current blank even
            # though a driver is installed and the site's version was
            # found fine). Fall back to the same WMI-based lookup
            # Gigabyte/ASUS already use below when the USB-specific INF
            # isn't present.
            current_version_getter=lambda: get_installed_inf_version("rtdusbad")
            or find_device_driver_version(devices, "10EC", ("AUDIO",), device_class="MEDIA")
            or find_device_driver_version(devices, "0BDA", ("AUDIO",), device_class="MEDIA"),
            current_date_getter=lambda: get_installed_inf_date("rtdusbad") or (
                find_device_by_vendor_and_keywords(devices, "10EC", ("AUDIO",), device_class="MEDIA")
                or find_device_by_vendor_and_keywords(devices, "0BDA", ("AUDIO",), device_class="MEDIA")
                or {}
            ).get("DriverDate"),
        ),
        dict(
            vendor="gigabyte", slug_field="gigabyte_slug", label="Gigabyte Audio Driver",
            provider_factory=lambda slug: GigabyteDriverProvider(
                product_slug=slug, category="Audio", match_substrings=("Realtek",), name="gigabyte_audio"
            ),
            # confirmed live: the site's version column (e.g. "6.0.9927.1")
            # is in the same dotted format WMI reports for the installed
            # driver, so a direct comparison is meaningful
            current_version_getter=lambda: find_device_driver_version(devices, "10EC", ("AUDIO",), device_class="MEDIA")
            or find_device_driver_version(devices, "0BDA", ("AUDIO",), device_class="MEDIA"),
            current_date_getter=lambda: (
                find_device_by_vendor_and_keywords(devices, "10EC", ("AUDIO",), device_class="MEDIA")
                or find_device_by_vendor_and_keywords(devices, "0BDA", ("AUDIO",), device_class="MEDIA")
                or {}
            ).get("DriverDate"),
        ),
        dict(
            vendor="asus", slug_field="asus_model", label="ASUS Audio Driver",
            provider_factory=lambda model: AsusDriverProvider(
                model=model, match_substrings=("Realtek",), category="Audio", name="asus_audio"
            ),
            # confirmed live: the API's version field (e.g. "6.0.8702.1")
            # is in the same format WMI reports for the installed
            # driver, unlike the old HTML scraper's page which had no
            # reliable version-comparable source at all
            current_version_getter=lambda: find_device_driver_version(devices, "10EC", ("AUDIO",), device_class="MEDIA")
            or find_device_driver_version(devices, "0BDA", ("AUDIO",), device_class="MEDIA"),
            current_date_getter=lambda: (
                find_device_by_vendor_and_keywords(devices, "10EC", ("AUDIO",), device_class="MEDIA")
                or find_device_by_vendor_and_keywords(devices, "0BDA", ("AUDIO",), device_class="MEDIA")
                or {}
            ).get("DriverDate"),
        ),
    ]

    for cfg in vendor_configs:
        found, result, blocked = _check_vendor_audio_driver(board, device_name=device_name, **cfg)
        if found:
            return result
        if blocked:
            url = overall_drivers_page_url(board, laptop)
            if url:
                return manual_check_unavailable(cfg["label"], url, device_name=device_name)
            break  # no fallback link available either — fall through below
    return _check_audio_via_windows_update(audio_device)


def check_senary_audio(devices, board, laptop):
    """
    SenaryTech (a Chinese audio codec maker, an alternative to Realtek)
    — found on some ultra-thin laptops, including certain Huawei models.
    Vendor ID 14F1 is confirmed on a real device. Works regardless of
    system type — based purely on whether the device is present, same
    as Intel/Realtek.
    """
    device = find_device(devices, lambda d: d.get("VendorID") == "14F1")
    if device is None:
        # Win32_PnPSignedDriver sometimes doesn't see this device
        # directly (the same situation as with Realtek USB Audio) —
        # fallback path
        try:
            fallback_devices = get_devices_by_id_pattern("VEN_14F1")
        except Exception as e:
            print(f"[Senary Audio] fallback lookup error: {classify_error(e)}", file=sys.stderr)
            fallback_devices = []
        device = find_device(fallback_devices, lambda d: True)  # any device with this VEN_
    if device is None:
        return None

    current = device.get("DriverVersion")
    current_date_raw = device.get("DriverDate")
    device_name = resolve_device_name(device)

    # resolve_chip_code only confirms a chip via the bundled pci.ids
    # database (currently just CX11880) -- None means "couldn't tell",
    # not "no chip", so unidentified chips fall through to the same
    # no-comparison display as before, further down
    chip_code = resolve_chip_code(device)
    provider = SenaryAudioProvider(chip_code=chip_code)
    ok, latest = safe_get_latest("Senary Audio", provider)
    if not ok:
        latest = None

    if chip_code and latest is not None:
        # the OEM (e.g. Huawei) still repackages the driver under its own
        # version number (see the module docstring), so a version
        # comparison isn't possible even for a confirmed chip -- but the
        # site's filename date is a real, comparable signal, same
        # date-based fallback check_realtek_lan uses for its own
        # incompatible-version-format case
        installed_date = parse_flexible_date(current_date_raw)
        site_date = parse_flexible_date(latest.get("date")) if latest.get("date") else None
        if installed_date and site_date:
            if (site_date - installed_date).days > 60:  # threshold to avoid noise on small discrepancies
                display_line = (
                    f"[Senary Audio] possibly outdated (by date, not by version — OEM repackages with its own "
                    f"version numbers): installed driver from {installed_date.date()}, site has one from {site_date.date()}"
                )
                update_line = (
                    f"Senary Audio: possibly outdated — installed driver from {installed_date.date()}, "
                    f"site: {SENARY_PAGE_URL}"
                )
                return build_result(
                    "Senary Audio", display_line, update_line,
                    current=current, available=latest["version"], current_date=current_date_raw,
                    available_date=latest.get("date"), status="Possibly outdated (by date)",
                    url=SENARY_PAGE_URL, device_name=device_name,
                )
            display_line = f"[Senary Audio] up to date by date (installed driver from {installed_date.date()})"
            return build_result(
                "Senary Audio", display_line,
                current=current, available=latest["version"], current_date=current_date_raw,
                available_date=latest.get("date"), status="Up to date (by date)",
                url=SENARY_PAGE_URL, device_name=device_name,
            )
        # chip confirmed but no usable date on one/both sides -- fall
        # through to the generic no-comparison display below, same as an
        # unidentified chip

    # chip not identified via pci.ids, or date comparison wasn't possible
    # — the installed version is still known and worth showing
    # (display_current), just not compared against
    return report(
        "Senary Audio", latest, current=None, page_url=SENARY_PAGE_URL, device_name=device_name,
        display_current=current, display_current_date=current_date_raw,
    )

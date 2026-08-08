import sys

from net_utils import classify_error
from scanner import get_devices_by_id_pattern
from checks.common import find_device, safe_get_latest, report, no_downgrade_match
from providers.msi_driver import MsiDriverProvider, get_installed_inf_version
from providers.gigabyte_driver import GigabyteDriverProvider
from providers.asrock_driver import AsrockDriverProvider
from providers.asus_driver import AsusDriverProvider
from providers.senary_audio import SenaryAudioProvider
from providers.ms_catalog import MsCatalogProvider


def _find_audio_device(devices):
    """
    Looks for an audio codec (usually Realtek, VendorID 10EC — the
    classic PCI/HDAUDIO one, 0BDA — newer codecs like the ALC4080 via a
    built-in USB interface).
    """
    audio_device = find_device(
        devices,
        lambda d: d.get("VendorID") in ("10EC", "0BDA") and "AUDIO" in d.get("DeviceName", "").upper(),
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
        audio_device = find_device(fallback_devices, lambda d: "AUDIO" in d.get("DeviceName", "").upper())
    return audio_device


def _check_audio_via_windows_update(devices):
    """
    Fallback path for when the board isn't from one of the known vendors
    (MSI/Gigabyte/ASRock/ASUS) or its page has no Audio category.
    This used to be Realtek's site — removed: the last update there was
    back in 2022, not a viable source for an up-to-date check. Instead
    we use the Microsoft Update Catalog: the WHQL builds Realtek itself
    submits to Windows Update actually do get updated.
    """
    audio_device = _find_audio_device(devices)
    if audio_device is None:
        return None  # no audio codec in the system — silently skip

    device_name = audio_device.get("DeviceName", "")
    current = audio_device.get("DriverVersion")

    provider = MsCatalogProvider(query=device_name, name="audio_windows_update")
    ok, latest = safe_get_latest(f"Audio ({device_name})", provider)
    if not ok:
        return None
    if latest is None:
        return None

    # searching by the device name string doesn't guarantee an exact
    # match to the right variant — same as with WiFi/Bluetooth via
    # Windows Update, we don't suggest a "downgrade"
    return report(f"Audio ({device_name})", latest, current, comparator=no_downgrade_match)


def _check_vendor_audio_driver(board, vendor, slug_field, provider_factory, label, current_version_getter=None):
    """
    Shared pattern for vendor-specific desktop-board audio drivers
    (MSI/Gigabyte/ASRock/ASUS) — they only differ in the provider class,
    the slug/model field in board, and (only for MSI) how the installed
    version is obtained for comparison.

    Returns (found, result):
      found — True if the check applies at all and found something on
              the site (regardless of whether there's an update or
              everything is current) — used to decide whether the
              generic Windows Update fallback is still needed;
      result — a (display, update) tuple from report(), or None.
    """
    if board.get("vendor") != vendor:
        return False, None

    slug = board.get(slug_field)
    if slug is None:
        return False, None

    provider = provider_factory(slug)
    ok, latest = safe_get_latest(label, provider)
    if not ok:
        return False, None
    if latest is None:
        return False, None  # this board's page has no "Audio" category

    current = current_version_getter() if current_version_getter else None
    return True, report(label, latest, current)


def check_audio(devices, board, laptop):
    """
    A driver customized for the specific board vendor (MSI/Gigabyte/
    ASRock/ASUS) takes priority — it more accurately reflects what
    should actually be installed on that specific board. We only check
    Windows Update as a fallback when no vendor-specific path applies
    (the board isn't from one of these four vendors) or the vendor's
    site has nothing under the audio category.

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
            # USB Audio on MSI boards
            current_version_getter=lambda: get_installed_inf_version("rtdusbad"),
        ),
        dict(
            vendor="gigabyte", slug_field="gigabyte_slug", label="Gigabyte Audio Driver",
            provider_factory=lambda slug: GigabyteDriverProvider(
                product_slug=slug, match_substrings=("Realtek", "Audio"), name="gigabyte_audio"
            ),
            current_version_getter=None,  # no reliable way to compare, not verified on real data
        ),
        dict(
            vendor="asrock", slug_field="asrock_model", label="ASRock Audio Driver",
            provider_factory=lambda model: AsrockDriverProvider(
                model=model, match_substrings=("Realtek", "Audio"),
                family=board.get("chipset_family", "amd"), name="asrock_audio",
            ),
            current_version_getter=None,
        ),
        dict(
            vendor="asus", slug_field="asus_model", label="ASUS Audio Driver",
            provider_factory=lambda model: AsusDriverProvider(
                model=model, match_substrings=("Realtek", "Audio"), name="asus_audio"
            ),
            current_version_getter=None,
        ),
    ]

    for cfg in vendor_configs:
        found, result = _check_vendor_audio_driver(board, **cfg)
        if found:
            return result
    return _check_audio_via_windows_update(devices)


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

    provider = SenaryAudioProvider()
    ok, latest = safe_get_latest("Senary Audio", provider)
    if not ok:
        return None
    # the OEM (e.g. Huawei) repackages the driver under its own version
    # number, different from what's on the SenaryTech site — comparison
    # isn't reliable
    return report("Senary Audio", latest, current=None)

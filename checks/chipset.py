import sys

from net_utils import classify_error
from checks.common import find_device, safe_get_latest, report, no_downgrade_match
from providers.amd_chipset import AmdChipsetProvider, get_current_amd_chipset_version, get_current_amd_chipset_date
from providers.intel_download import IntelDownloadCenterProvider, get_current_intel_chipset_version, intel_download_url
from providers.intel_chipset_inf_db import IntelChipsetInfDbProvider

INTEL_CHIPSET_DOWNLOAD_ID = "19347"
INTEL_CHIPSET_SLUG = "chipset-inf-utility"


def check_amd_chipset(devices, board, laptop):
    # first check whether there's an AMD platform in the system at all —
    # if not (e.g. an Intel laptop), silently skip instead of scaring the
    # user with a false "couldn't detect chipset" warning
    has_amd_platform = find_device(
        devices,
        lambda d: d.get("VendorID") == "1022" and any(
            kw in d.get("DeviceName", "").upper()
            for kw in ("SMBUS", "CHIPSET", "PCIE ROOT", "PCI ROOT")
        ),
    ) is not None
    if not has_amd_platform:
        return None  # not an AMD platform — silently skip

    page_url = board.get("amd_chipset_url")
    if page_url is None:
        print(
            "[AMD Chipset] AMD platform found, but couldn't determine "
            "the board chipset automatically (board_detect.py didn't recognize the model)",
            file=sys.stderr,
        )
        return None

    provider = AmdChipsetProvider(page_url=page_url)
    device = find_device(devices, provider)
    if device is None:
        return None  # device not found in the system — silently skip

    ok, latest = safe_get_latest("AMD Chipset", provider, device)
    if not ok:
        latest = None
    return report(
        "AMD Chipset", latest, get_current_amd_chipset_version(), page_url=page_url,
        current_date=get_current_amd_chipset_date(),
    )


def check_intel_chipset(devices, board, laptop):
    # check whether there's an Intel platform in the system at all (by
    # PCI Vendor ID) before hitting the site — on an AMD system Intel
    # Chipset Software will never be installed, and a comparison
    # wouldn't make sense
    intel_platform_device = find_device(
        devices,
        lambda d: d.get("VendorID") == "8086" and any(
            kw in d.get("DeviceName", "").upper()
            for kw in ("SMBUS", "LPC", "ISA BRIDGE", "PCI BRIDGE", "HOST BRIDGE")
        ),
    )
    if intel_platform_device is None:
        return None  # not an Intel platform — silently skip

    # PRIMARY path: a community database (not an official Intel source,
    # but public and actively maintained) gives a version specifically
    # FOR THIS platform (by Hardware ID) — the same numbering scheme seen
    # on the installed system, so the comparison ends up meaningful
    # (unlike the version of the package as a whole from Intel's site —
    # see the comment below for why we had to move away from that).
    hwid = intel_platform_device.get("DeviceID_PCI")
    current = intel_platform_device.get("DriverVersion")

    if hwid:
        try:
            db_latest = IntelChipsetInfDbProvider(hwid=hwid).get_latest()
        except Exception as e:
            print(f"[Intel Chipset] error (community database): {classify_error(e)}", file=sys.stderr)
            db_latest = None
        if db_latest is not None:
            # the version used for comparison comes from the community
            # database (accurate, by HWID), but the link shown to the
            # person should point to the official Intel page where the
            # installer can actually be downloaded — not to the raw .md
            # file of the database, which was only needed for comparison
            db_latest["url"] = (
                f"https://www.intel.com/content/www/us/en/download/"
                f"{INTEL_CHIPSET_DOWNLOAD_ID}/{INTEL_CHIPSET_SLUG}.html"
            )
            return report("Intel Chipset", db_latest, current, comparator=no_downgrade_match)

    # FALLBACK path: the official Intel page, but only the version of the
    # package as a whole — comparing against the installed version is
    # fundamentally impossible here (the package version lives in a
    # different numbering scheme than the version of a specific
    # component for a specific CPU generation).
    provider = IntelDownloadCenterProvider(
        download_id=INTEL_CHIPSET_DOWNLOAD_ID, slug=INTEL_CHIPSET_SLUG, name="intel_chipset"
    )
    ok, latest = safe_get_latest("Intel Chipset", provider)
    if not ok:
        latest = None

    # IMPORTANT: there was originally an attempt here to fall back to the
    # PnP driver version of the SMBus controller when the registry was
    # empty — turned out that's wrong: the version of a specific PnP
    # component (SMBus) doesn't have to match the version of the whole
    # "Chipset Device Software" package (confirmed in practice: after
    # actually installing the package, the SMBus driver version didn't
    # change, and the comparison kept falsely showing "update
    # available"). So we only use the registry — if it's empty, we
    # honestly show "couldn't compare" instead of guessing.
    current = get_current_intel_chipset_version()
    return report(
        "Intel Chipset", latest, current,
        page_url=intel_download_url(INTEL_CHIPSET_DOWNLOAD_ID, INTEL_CHIPSET_SLUG),
    )

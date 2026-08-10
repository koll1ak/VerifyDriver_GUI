from checks.common import find_device_by_vendor_and_keywords, safe_get_latest, report, no_downgrade_match
from providers.intel_download import IntelDownloadCenterProvider, intel_download_url

INTEL_NPU_DOWNLOAD_ID = "794734"
INTEL_NPU_SLUG = "intel-npu-driver-windows"


def check_intel_npu(devices, board, laptop):
    # Windows reports the NPU as "Intel(R) AI Boost" under Device
    # Manager's "Neural processors" category, confirmed across every
    # generation (Meteor Lake, Lunar Lake, Arrow Lake, Panther Lake) —
    # the underlying PCI device ID differs per generation, but the
    # friendly name and category are consistent, so we match on name
    # like every other Intel device check here, not a hardcoded DEV_ list.
    device = find_device_by_vendor_and_keywords(devices, "8086", ("AI BOOST", "NPU"))
    if device is None:
        return None  # no Intel NPU in the system — silently skip
    current = device.get("DriverVersion")

    provider = IntelDownloadCenterProvider(
        download_id=INTEL_NPU_DOWNLOAD_ID, slug=INTEL_NPU_SLUG, name="intel_npu"
    )
    ok, latest = safe_get_latest("Intel NPU", provider)
    if not ok:
        latest = None
    # confirmed live: unlike Intel Bluetooth, this download page has no
    # per-chip-generation version split — one package covers every NPU
    # generation, so a direct comparison is correct
    return report(
        "Intel NPU", latest, current, comparator=no_downgrade_match,
        page_url=intel_download_url(INTEL_NPU_DOWNLOAD_ID, INTEL_NPU_SLUG),
        device_name=device.get("DeviceName"), current_date=device.get("DriverDate"),
    )

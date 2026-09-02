from checks.common import find_device, find_device_by_vendor_and_keywords, safe_get_latest, report, resolve_device_name
from providers.nvidia import NvidiaProvider, get_current_nvidia_version
from providers.amd_gpu import AmdGpuProvider
from providers.intel_download import IntelDownloadCenterProvider, intel_download_url

# NVIDIA has no per-GPU static page usable as a provider source (see
# providers/nvidia.py — it goes through an AJAX API instead), but its
# generic driver-search landing page is a long-stable, well-known public
# URL — fine to use as a manual-check link when the API call fails.
NVIDIA_DRIVERS_PAGE_URL = "https://www.nvidia.com/Download/index.aspx"

# AMD Software: Adrenalin Edition — the exact same driver version is
# shown on ANY AMD product page (discrete cards and CPU-integrated APU
# graphics use a shared universal package, confirmed in practice: the
# same version number appears both on the graphics card page and on the
# processor-with-APU page) — so any valid AMD product page works, even
# if the actual integrated graphics is a different model. This one is
# specifically the Ryzen 7 9800X3D page (integrated RDNA2 graphics,
# 2 CU); the page structure has been verified: the driver version and
# the Release Notes link (RN-RAD-WIN) parse the way AmdGpuProvider expects.
AMD_GPU_PAGE_URL = "https://www.amd.com/en/support/downloads/drivers.html/processors/ryzen/ryzen-9000-series/amd-ryzen-7-9800x3d.html"

INTEL_GPU_DOWNLOAD_ID = "785597"
INTEL_GPU_SLUG = "intel-arc-graphics-windows"


def _is_integrated_amd_gpu(device_name: str) -> bool:
    """
    AMD's naming convention reliably distinguishes the two: every Ryzen
    CPU's integrated graphics reports as a bare "AMD Radeon(TM) Graphics"
    or "AMD Radeon(TM) Vega 8 Graphics" — always ending in the plain word
    "Graphics" — while every discrete Radeon card has a specific model
    suffix instead ("... RX 7900 XTX", "... Pro W7900", "... VII"), never
    ending in just "Graphics".
    """
    return device_name.strip().upper().endswith("GRAPHICS")


def check_nvidia(devices, board, laptop):
    provider = NvidiaProvider()
    device = find_device(devices, provider)
    if device is None:
        return None  # device not found in the system — silently skip

    ok, latest = safe_get_latest("NVIDIA", provider, device)
    if not ok:
        latest = None
    return report(
        "NVIDIA", latest, get_current_nvidia_version(), page_url=NVIDIA_DRIVERS_PAGE_URL,
        device_name=resolve_device_name(device), current_date=device.get("DriverDate"),
    )


def check_amd_gpu(devices, board, laptop):
    # look for an AMD graphics card among the devices even if the URL
    # isn't configured yet — so we can hint at the exact card name to
    # search for on amd.com.
    # IMPORTANT: AMD graphics cards have Vendor ID "1002" (inherited from
    # ATI), not "1022" (used for chipset/CPU devices) — confirmed on a
    # real device, there was originally a bug with the IDs swapped.
    amd_gpu_device = find_device_by_vendor_and_keywords(devices, "1002", ("RADEON", "AMD GRAPHICS"), device_class="DISPLAY")
    if amd_gpu_device is None:
        return None  # device not found in the system — silently skip

    provider = AmdGpuProvider(page_url=AMD_GPU_PAGE_URL)
    ok, latest = safe_get_latest("AMD GPU", provider, amd_gpu_device)
    if not ok:
        latest = None
    # AmdGpuProvider explicitly sets a comparable_with_windows_version
    # flag telling us whether the comparison can be trusted (see
    # providers/amd_gpu.py) — if the site's version could be converted
    # to the "Windows Driver Store Version" format (the same one Windows
    # sees), we compare directly; if not, the version stayed the
    # marketing one ("26.7.1"), and comparing against it isn't safe
    current = amd_gpu_device.get("DriverVersion") if latest and latest.get("comparable_with_windows_version") else None
    amd_device_name = resolve_device_name(amd_gpu_device)
    if _is_integrated_amd_gpu(amd_device_name):
        amd_device_name += " (Integrated)"
    return report(
        "AMD GPU", latest, current, page_url=AMD_GPU_PAGE_URL,
        device_name=amd_device_name, current_date=amd_gpu_device.get("DriverDate") if current else None,
    )


def check_intel_gpu(devices, board, laptop):
    # IMPORTANT: the driver package (ID 785597) is specifically "Intel
    # Arc & Iris Xe Graphics" — it does NOT work for older integrated
    # GPUs (e.g. "Intel UHD Graphics" on pre-Xe platforms like Comet
    # Lake) — installing on unsupported hardware gives a "No supported
    # devices" error. So we search strictly for "ARC" or "IRIS XE", not
    # the generic "GRAPHICS"/bare "IRIS" (the latter also matches the
    # older Iris Plus/Pro).
    device = find_device_by_vendor_and_keywords(devices, "8086", ("ARC", "IRIS XE"), device_class="DISPLAY")
    if device is None:
        return None  # device not found in the system (or not Xe-generation) — silently skip
    current = device.get("DriverVersion")

    provider = IntelDownloadCenterProvider(
        download_id=INTEL_GPU_DOWNLOAD_ID, slug=INTEL_GPU_SLUG, name="intel_gpu"
    )
    ok, latest = safe_get_latest("Intel GPU", provider)
    if not ok:
        latest = None
    # for Intel, the Windows version usually matches the marketing version directly
    return report(
        "Intel GPU", latest, current,
        page_url=intel_download_url(INTEL_GPU_DOWNLOAD_ID, INTEL_GPU_SLUG),
        device_name=resolve_device_name(device), current_date=device.get("DriverDate"),
    )

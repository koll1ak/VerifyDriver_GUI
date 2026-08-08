"""
NVIDIA provider.

Logic:
1. Look up pfid (Product Family ID, NVIDIA's internal identifier) by the
   device name from the scanner, using the open ZenitH-AT/nvidia-data
   reference.
2. Hit the official AjaxDriverService (the same backend the manual
   driver-search page on nvidia.com uses) — get the current version,
   date, and link.

osID is picked automatically based on the installed Windows version (10
or 11) — for NVIDIA these are different IDs in the reference (57 and 135
respectively), though for modern cards the driver package is usually the
same for both versions.

Sources:
- https://github.com/ZenitH-AT/nvidia-data  (gpu-data.json, os-data.json files in the repo root)
- https://github.com/ZenitH-AT/nvidia-update (example of a real API request)
"""

import re
import subprocess
import sys

import requests

from providers.base import DriverProvider

GPU_DATA_URL = "https://raw.githubusercontent.com/ZenitH-AT/nvidia-data/main/gpu-data.json"
AJAX_URL = "https://gfwsl.geforce.com/services_toolkit/services/com/nvidia/services/AjaxDriverService.php"

# osID from os-data.json: 57 = "Windows 10 64-bit", 135 = "Windows 11"
OS_ID_WINDOWS_10 = "57"
OS_ID_WINDOWS_11 = "135"
WINDOWS_11_MIN_BUILD = 22000  # the first build Microsoft calls "Windows 11"


def detect_windows_os_id() -> str:
    """
    Determines the right osID for the installed Windows version.
    sys.getwindowsversion() is more reliable than platform.release() —
    the latter sometimes still returns "10" on Windows 11 because of the
    shared code base.
    If not Windows (or it couldn't be determined) — defaults to the Win10
    ID, which is also historically the most compatible option in
    NVIDIA's API.
    """
    try:
        build = sys.getwindowsversion().build
    except AttributeError:
        return OS_ID_WINDOWS_10  # not Windows — use the default

    return OS_ID_WINDOWS_11 if build >= WINDOWS_11_MIN_BUILD else OS_ID_WINDOWS_10


def get_current_nvidia_version() -> str | None:
    """
    The actual installed driver version via nvidia-smi — it's already in
    the marketing format (e.g. "610.88"), avoiding the hassle of
    Windows's internal version format (Win32_PnPSignedDriver gives
    something like "32.0.15.6108", from which the marketing version
    isn't easy to reconstruct).
    """
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        return None
    version = result.stdout.strip()
    return version or None


class NvidiaProvider(DriverProvider):
    name = "nvidia"

    def __init__(self, os_id: str | None = None):
        # if os_id isn't passed explicitly — auto-detect from the system
        self.os_id = os_id or detect_windows_os_id()
        self._gpu_data = None

    def matches(self, device: dict) -> bool:
        # VendorID 10DE (NVIDIA) is used not just by the graphics card
        # but also by its HDMI audio device ("NVIDIA High Definition
        # Audio") — filtering only on "NVIDIA" in the name is too broad
        # and could accidentally match the audio device instead of the
        # GPU. Require a word characteristic of a graphics card.
        if device.get("VendorID") != "10DE":
            return False
        name_upper = device.get("DeviceName", "").upper()
        return any(kw in name_upper for kw in ("GEFORCE", "RTX", "GTX", "QUADRO", "NVS", "TESLA"))

    def _load_gpu_data(self) -> dict:
        if self._gpu_data is None:
            resp = requests.get(GPU_DATA_URL, timeout=15)
            resp.raise_for_status()
            self._gpu_data = resp.json()
        return self._gpu_data

    @staticmethod
    def _clean_name(name: str) -> str:
        # "NVIDIA GeForce RTX 5080" -> "GeForce RTX 5080"
        return name.replace("NVIDIA ", "").strip()

    @staticmethod
    def _normalize_variant_name(name: str) -> str:
        """
        Per the ZenitH-AT/nvidia-data reference's own documentation: some
        of the name variants reported by Windows don't match the
        database key-for-key — need to normalize "Super" to "SUPER" and
        strip typical suffixes (memory size, laptop-vendor abbreviations
        in parentheses, "with Max-Q Design", "Laptop GPU" — Windows adds
        this suffix for mobile cards starting with the 30-series, it
        wasn't in the reference's original list).
        """
        name = name.replace("Super", "SUPER")
        for pattern in (
            r"\s+\(Laptop GPU\)$",
            r"\s+Laptop GPU$",
            r"\s+\([^)]*\)$",                # any parenthesized suffix
            r"\s+\d+GB$",                     # "8GB"
            r"\s+COLLECTORS EDITION$",
            r"\s+with Max-Q Design$",
        ):
            name = re.sub(pattern, "", name, flags=re.IGNORECASE)
        return name.strip()

    def _lookup_pfid(self, gpu_data: dict, name: str) -> str | None:
        for section in ("desktop", "notebook"):
            section_data = gpu_data.get(section, {})
            if name in section_data:
                return section_data[name]
        return gpu_data.get(name)  # in case of a flat structure (no desktop/notebook)

    def get_latest(self, device: dict) -> dict | None:
        gpu_data = self._load_gpu_data()
        clean_name = self._clean_name(device["DeviceName"])

        pfid = self._lookup_pfid(gpu_data, clean_name)

        if pfid is None:
            normalized_name = self._normalize_variant_name(clean_name)
            if normalized_name != clean_name:
                pfid = self._lookup_pfid(gpu_data, normalized_name)

        if pfid is None:
            print(
                f"[nvidia] card not found in the reference by name "
                f"\"{clean_name}\" (nor after normalization) — you may "
                f"need to check gpu-data.json manually",
                file=sys.stderr,
            )
            return None

        params = {
            "func": "DriverManualLookup",
            "pfid": pfid,
            "osID": self.os_id,
            "dch": 1,
        }

        resp = requests.get(AJAX_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        ids = data.get("IDS") or []
        if not ids:
            return None

        info = ids[0]["downloadInfo"]
        url = info.get("DownloadURL", "")
        if url.startswith("//"):
            url = "https:" + url

        return {
            "version": info.get("Version"),
            "date": info.get("ReleaseDateTime"),
            "url": url,
        }

"""
AMD Radeon GPU provider (AMD Software: Adrenalin Edition).

Reuses AmdChipsetProvider — the page structure on amd.com is the same
for chipsets and graphics cards, only the URL and the version format
differ ("Adrenalin 26.5.2 (WHQL Recommended)" instead of a plain number).

IMPORTANT: the marketing version ("26.7.1") is not the same as the
version Windows sees ("32.0.21043.1005") — these are different numbering
schemes, same as with NVIDIA. But unlike NVIDIA, AMD doesn't have an API
with a direct mapping — however, every release's Release Notes page
publishes the exact "Windows Driver Store Version" value in the SAME
format Windows sees (confirmed on real AMD release notes). AMD runs TWO
parallel numbering tracks at once (for different GPU generations) — we
pick the right one by comparing the first 2 digits of the third segment
of the installed version (e.g. "21" in "32.0.21043.1005").

IMPORTANT: page_url needs to be set manually for the specific graphics
card model — take it from the address bar of that model's support page
on amd.com (Support -> Drivers & Support -> find your model).
Example for the Radeon RX 580:
"https://www.amd.com/en/support/downloads/drivers.html/graphics/radeon-600-500-400/radeon-rx-500-series/radeon-rx-580.html"
"""

import re

import requests
from bs4 import BeautifulSoup

from providers.amd_chipset import AmdChipsetProvider
from providers.http_utils import DEFAULT_HEADERS

DRIVER_NAME = "AMD Software: Adrenalin Edition"
VERSION_REGEX = r"Adrenalin\s+([\d.]+)"

_STORE_VERSION_RE = re.compile(r"Windows Driver Store Version\s+([\d.]+)")


def _segment3_prefix(version: str) -> str | None:
    """The first 2 digits of the third segment — determines AMD's numbering "track"."""
    parts = version.split(".")
    if len(parts) < 3 or len(parts[2]) < 2:
        return None
    return parts[2][:2]


class AmdGpuProvider(AmdChipsetProvider):
    name = "amd_gpu"

    def __init__(self, page_url: str, driver_name: str = DRIVER_NAME):
        super().__init__(
            page_url=page_url,
            driver_name=driver_name,
            version_regex=VERSION_REGEX,
            vendor_match_keywords=("RADEON", "AMD GRAPHICS"),
        )

    def matches(self, device: dict) -> bool:
        # AMD graphics cards have Vendor ID "1002" (inherited from ATI),
        # not "1022" (the parent AmdChipsetProvider.matches() uses that
        # one, which is correct for chipset/CPU devices, but not for
        # GPUs) — confirmed on a real device
        return (
            device.get("VendorID") == "1002"
            and any(kw in device.get("DeviceName", "").upper() for kw in self.vendor_match_keywords)
        )

    def get_latest(self, device: dict = None) -> dict | None:
        latest = super().get_latest(device)
        if latest is None:
            return None

        # an explicit flag instead of implicitly inferring from the
        # presence/absence of a key — main.py reads exactly this to
        # decide whether to trust the comparison
        latest["comparable_with_windows_version"] = False

        current_version = device.get("DriverVersion") if device else None
        if not current_version:
            return latest  # nothing to compare against — return the marketing version as-is

        try:
            store_version = self._find_matching_store_version(current_version)
        except Exception:
            return latest  # Release Notes unavailable/structure changed — don't risk it, return as-is

        if store_version:
            latest["marketing_version"] = latest.get("raw_revision")
            latest["version"] = store_version
            latest["comparable_with_windows_version"] = True

        return latest

    def _find_matching_store_version(self, current_version: str) -> str | None:
        target_prefix = _segment3_prefix(current_version)
        if target_prefix is None:
            return None

        resp = requests.get(self.page_url, headers=DEFAULT_HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        release_notes_link = soup.find("a", href=re.compile(r"release-notes.*RN-RAD-WIN", re.IGNORECASE))
        if release_notes_link is None:
            return None

        rn_url = release_notes_link["href"]
        if rn_url.startswith("/"):
            rn_url = "https://www.amd.com" + rn_url

        rn_resp = requests.get(rn_url, headers=DEFAULT_HEADERS, timeout=20)
        rn_resp.raise_for_status()
        rn_text = BeautifulSoup(rn_resp.text, "html.parser").get_text(" ", strip=True)

        candidates = _STORE_VERSION_RE.findall(rn_text)
        for candidate in candidates:
            if _segment3_prefix(candidate) == target_prefix:
                return candidate
        return None

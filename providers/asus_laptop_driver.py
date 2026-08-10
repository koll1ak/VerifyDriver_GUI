"""
Provider for ASUS laptops — uses the support page's official JSON API
(not a text heuristic like providers/asus_driver.py, which was written
for desktop boards and doesn't fit laptop pages — there the driver list
loads via this separate endpoint).

    GET https://www.asus.com/support/webapi/ProductV2/GetPDDrivers
        ?website=us&model=<model>&pdhashedid=&cpu=&osid=<osid>&pdid=99999&siteID=www&sitelang=

Response structure:
{
  "Result": {
    "Obj": [
      {"Name": "Audio", "Files": [several of these
        {"Id": "...Realtek Codec Console Application", "Version": "latest version at the MS store", ...},
        {"Id": "...Audio_DriverOnly_Dolby_DCH_Realtek_J_V6.0.9768.1_41645_1.exe", "INFDate": "12-03-2024", ...},
      ]},
      ...
    ]
  }
}

The version of the actual installable package is baked into the file
name ("_V6.0.9768.1_"), not into a separate Version field (which is
sometimes occupied by boilerplate text like "latest version at the MS
store" — an MS Store app, not an installer; such entries are skipped).
The date is INFDate in MM-DD-YYYY format.
"""

import re
import sys

import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

API_URL = "https://www.asus.com/support/webapi/ProductV2/GetPDDrivers"

# 52 — Windows 11 64-bit in ASUS's system (confirmed on a real request).
# 45 — Windows 10 64-bit: not documented anywhere, inferred by sweeping
# osid values across many real ASUS laptop models — 45 consistently
# returns real data (with filenames literally containing "Win10_64")
# for pre-2022/pre-Windows-11-era models, while several 2022+ models
# return nothing for 45 but do for 52. Same confidence level as the
# NVIDIA/Acer OS-code detection this mirrors, but ASUS gives no
# official documentation to cross-check against, unlike those two.
OS_ID_WINDOWS_10 = "45"
OS_ID_WINDOWS_11 = "52"
WINDOWS_11_MIN_BUILD = 22000  # the first build Microsoft calls "Windows 11"


def detect_asus_os_id() -> str:
    """
    Determines the right osid for the installed Windows version, the
    same way providers/nvidia.py and providers/acer_support.py do (via
    sys.getwindowsversion().build). Previously this provider always
    defaulted to Windows 11's code regardless of the actual installed
    OS — a real laptop running Windows 10 would silently get Windows 11
    driver data.
    """
    try:
        build = sys.getwindowsversion().build
    except AttributeError:
        return OS_ID_WINDOWS_10  # not Windows — use the default
    return OS_ID_WINDOWS_11 if build >= WINDOWS_11_MIN_BUILD else OS_ID_WINDOWS_10


_VERSION_IN_FILENAME_RE = re.compile(r"_V([\d.]+)_")


def _parse_version_tuple(v: str):
    """
    "6.0.9050.1" -> (6, 0, 9050, 1), for choosing the "best" candidate by
    version number. Ranking used to be by INFDate instead — dropped
    after confirming live (ASUS PRIME H310M-R R2.0) that INFDate is
    unreliable: two candidate files for the same board had an empty
    INFDate each, and the one non-empty INFDate present ("05/13/2018")
    belonged to a numerically OLDER version than the others, contradicting
    both the version number and the date baked into that same file's own
    name (2019) — INFDate looks like it can be the driver's original
    authoring date, not this OEM release's date, so it isn't a trustworthy
    "latest" signal here.
    """
    try:
        return tuple(int(p) for p in v.split("."))
    except (ValueError, AttributeError):
        return None


class AsusLaptopDriverProvider(DriverProvider):
    """
    category: the exact category name in the API response — "Audio",
    "Networking", "Chipset", etc. (visible in the response itself; for
    ASUS it doesn't always match what you'd logically expect — e.g.
    their LAN category is called "Networking", not "Lan").
    match_substrings: substrings required in the file's Id/ExeModule
    (e.g. ("Realtek",) so we don't confuse it with another vendor in the
    same category).
    """

    def __init__(self, model: str, category: str, match_substrings: tuple[str, ...], os_id: str | None = None, name: str = "asus_laptop_driver"):
        self.model = model
        self.category = category
        self.match_substrings = match_substrings
        # if os_id isn't passed explicitly — auto-detect from the system
        self.os_id = os_id or detect_asus_os_id()
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        resp = requests.get(
            API_URL,
            params={
                "website": "us",
                "model": self.model,
                "pdhashedid": "",
                "cpu": "",
                "osid": self.os_id,
                "pdid": "99999",
                "siteID": "www",
                "sitelang": "",
            },
            headers=DEFAULT_HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        categories = data.get("Result", {}).get("Obj", []) or []
        category_data = next(
            (c for c in categories if c.get("Name", "").upper() == self.category.upper()),
            None,
        )
        if category_data is None:
            return None

        candidates = []
        for f in category_data.get("Files", []) or []:
            identifier = f.get("Id", "") or f.get("ExeModule", "")
            if not all(s.upper() in identifier.upper() for s in self.match_substrings):
                continue
            version_match = _VERSION_IN_FILENAME_RE.search(identifier)
            if version_match is None:
                continue  # e.g. a boilerplate entry with no version in the name
            candidates.append((f, version_match.group(1)))

        if not candidates:
            return None

        best_file, best_version = max(
            candidates, key=lambda pair: _parse_version_tuple(pair[1]) or ()
        )

        # DownloadUrl is either an absolute link (e.g. an MS Store page)
        # or a path relative to ASUS's CDN (confirmed against a real
        # response) — same relative-path shape as providers/asus_bios.py
        download_url = (best_file.get("DownloadUrl") or {}).get("Global")
        if download_url and download_url.startswith("/"):
            download_url = "https://dlcdnets.asus.com" + download_url

        return {
            "version": best_version,
            "date": best_file.get("INFDate"),
            "size": best_file.get("FileSize"),
            "description": best_file.get("Description"),
            "url": download_url,
        }

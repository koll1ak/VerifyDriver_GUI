"""
Provider for (non-BIOS) drivers from ASUS DESKTOP BOARDS.

Originally a blind text heuristic over the "helpdesk_driver" HTML page
(look for a leaf element whose text contains both match_substrings) —
replaced after live testing on a real board (PRIME Z370-P II) found the
actual root cause of it turning up nothing: that page's content is
OS-gated by the exact same mechanism as ASUS LAPTOPS
(providers/asus_laptop_driver.py, GetPDDrivers?osid=...), and the old
scraper never sent any OS parameter at all — so it silently saw
whatever the page defaults to server-side, which for this real board
turned out to be Windows 11's driver list (2 categories, no Audio at
all), while the actually-installed OS was Windows 10 (7 categories,
including Audio — confirmed live, and the top file's version,
6.0.8702.1, is the EXACT version already installed on that machine).

Same GET https://www.asus.com/support/webapi/ProductV2/GetPDDrivers
endpoint as the laptop provider (confirmed live: works identically for
a desktop board's model name) — kept in its own file/class rather than
merged into asus_laptop_driver.py, matching this codebase's existing
per-page-type convention (desktop asus_bios.py/asus_driver.py vs
laptop asus_laptop_driver.py are already separate despite overlap).

Match against Id + Title together, not just Id: confirmed live that
ASUS's own naming is inconsistent — one real file's Id abbreviates the
vendor to "RTK" (no "Realtek" substring at all), while its Title says
"Realtek Audio Driver" plainly; another file's Id says "Realtek_Audio_
Driver..." but its Title is just "Audio". Neither field alone catches
both cases.
"""

import re
from datetime import datetime

import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS
from providers.asus_laptop_driver import detect_asus_os_id

API_URL = "https://www.asus.com/support/webapi/ProductV2/GetPDDrivers"

_VERSION_IN_FILENAME_RE = re.compile(r"_V([\d.]+)_")


def _parse_inf_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%m-%d-%Y")
    except (ValueError, TypeError):
        return None


class AsusDriverProvider(DriverProvider):
    """
    model: the board's model name (e.g. "PRIME Z370-P II"), same format
    used for the BIOS page URL elsewhere.
    match_substrings: substrings required (combined across Id + Title)
    to identify the right vendor's driver within the category — e.g.
    ("Realtek",) for audio.
    category: the exact category name in the API response (confirmed
    live for desktop boards: "Audio", "LAN", "Chipset", "VGA", "SATA",
    "Utilities", "BIOS-Utilities" — no plain "BIOS", firmware isn't
    OS-gated the same way and is handled separately by asus_bios.py).
    """

    def __init__(self, model: str, match_substrings: tuple[str, ...], category: str = "Audio", os_id: str | None = None, name: str = "asus_driver"):
        self.model = model
        self.match_substrings = match_substrings
        self.category = category
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
            identifier = f"{f.get('Id', '')} {f.get('Title', '')}"
            if not all(s.upper() in identifier.upper() for s in self.match_substrings):
                continue

            version = f.get("Version")
            if not version:
                continue
            candidates.append((f, version))

        if not candidates:
            return None

        best_file, best_version = max(
            candidates, key=lambda pair: _parse_inf_date(pair[0].get("INFDate", "")) or datetime.min
        )

        # DownloadUrl is either an absolute link or a path relative to
        # ASUS's CDN (same shape as providers/asus_laptop_driver.py)
        download_url = (best_file.get("DownloadUrl") or {}).get("Global")
        if download_url and download_url.startswith("/"):
            download_url = "https://dlcdnets.asus.com" + download_url

        return {
            "version": best_version,
            "date": best_file.get("INFDate"),
            "size": best_file.get("FileSize"),
            "url": download_url,
        }

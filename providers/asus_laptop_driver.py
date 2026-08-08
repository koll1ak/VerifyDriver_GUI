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
from datetime import datetime

import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

API_URL = "https://www.asus.com/support/webapi/ProductV2/GetPDDrivers"

# 52 — the code for Windows 11 64-bit in ASUS's system (confirmed on a real request)
DEFAULT_OS_ID = "52"

_VERSION_IN_FILENAME_RE = re.compile(r"_V([\d.]+)_")


def _parse_inf_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%m-%d-%Y")
    except (ValueError, TypeError):
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

    def __init__(self, model: str, category: str, match_substrings: tuple[str, ...], os_id: str = DEFAULT_OS_ID, name: str = "asus_laptop_driver"):
        self.model = model
        self.category = category
        self.match_substrings = match_substrings
        self.os_id = os_id
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
            candidates, key=lambda pair: _parse_inf_date(pair[0].get("INFDate", "")) or datetime.min
        )

        return {
            "version": best_version,
            "date": best_file.get("INFDate"),
            "size": best_file.get("FileSize"),
            "description": best_file.get("Description"),
        }

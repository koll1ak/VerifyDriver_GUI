"""
Provider for GIGABYTE/AORUS LAPTOPS — BIOS and (non-BIOS) drivers.

Confirmed live this is a genuinely different site architecture from
GIGABYTE's DESKTOP boards (providers/gigabyte_bios.py,
providers/gigabyte_driver.py): the laptop support page is entirely
client-side rendered (a Nuxt/Vue app — the server response has ZERO
mentions of "BIOS" or "Realtek" anywhere, confirmed by direct fetch),
unlike desktop boards' server-rendered pages. Reverse-engineered via
Claude in Chrome capturing the page's actual network requests (the
Performance API's resource-timing buffer, specifically, since a
regular network-request read raced ahead of the page's very first
requests every time) — three real endpoints, in order:

1. GET https://www.gigabyte.com/iisApplicationNuxt/api/proxy/api/v1.0/Search/global
       ?keyword=<model name>&type=0
   Confirmed live: this is GIGABYTE's own site search (type=0 is
   "Products" — type=1 returned zero results for a real query, "All"
   from the URL bar is REJECTED by the API itself with a validation
   error, both confirmed live). Each Products result's
   document.linkUrl gives the SERIES page slug (e.g.
   "/Laptop/AORUS-15X--2023") — a laptop series can cover multiple
   specific models (e.g. "AORUS 15X ASF" and "AORUS 15X AKF"), and the
   series slug alone isn't enough to fetch driver data; step 2 resolves
   which specific model.

2. GET https://www.gigabyte.com{series slug}/support
   Confirmed live: this page IS server-rendered enough to contain each
   specific model's numeric ID directly as plain HTML attributes —
   `product-num="8768" product-name="AORUS 15X ASF"` — even though the
   actual driver/BIOS DATA on this same page is not (loaded by a
   further client-side call, step 3). Regex out (product-num,
   product-name) pairs and match product-name against the exact model
   name from step 1's search result.

3. GET https://www.gigabyte.com/iisApplicationNuxt/api/proxy/api/v1.0/Consumer/global/GetProductTabDataAsync/Support/{productId}
   Confirmed live, no auth needed: data[].child[] has "bios" and
   "driver" keys (among others: "utility", "manual", "faq"). "driver"
   lumps every non-BIOS category into one list, disambiguated by each
   item's info[] array (e.g. [{"infoName": "Audio"}, {"infoName":
   "Windows 11 64bit"}]) — filtered by category name via that field,
   same way as "bios", which needs no such filtering (confirmed live:
   both its entries were genuinely BIOS versions, no contamination like
   MSI/Lenovo's laptop BIOS lists had). Neither list is reliably
   sorted newest-first (confirmed live: BIOS came oldest-first) — pick
   by fileReleaseDate instead of index.

Not verified on real GIGABYTE laptop hardware — the author doesn't
have one. WMI's exact Win32_ComputerSystem.Model string format on a
real device isn't confirmed; this assumes it's close enough to the
specific model name ("AORUS 15X ASF") for the search step to resolve
correctly, the same assumption already made for the other search-based
providers (HP, Dell before it was dropped).
"""

import re
import sys
from datetime import datetime, timezone

from curl_cffi import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

BASE_URL = "https://www.gigabyte.com"
SEARCH_URL = f"{BASE_URL}/iisApplicationNuxt/api/proxy/api/v1.0/Search/global"
TAB_DATA_URL = f"{BASE_URL}/iisApplicationNuxt/api/proxy/api/v1.0/Consumer/global/GetProductTabDataAsync/Support/{{product_id}}"

_PRODUCT_NUM_RE = re.compile(r'product-num="(\d+)" product-name="([^"]+)"')

WINDOWS_11_MIN_BUILD = 22000


def _detect_windows_name() -> str:
    """"Windows 11 64bit" / "Windows 10 64bit" — matches the info[] OS tag format."""
    try:
        build = sys.getwindowsversion().build
    except AttributeError:
        return "Windows 10 64bit"
    return "Windows 11 64bit" if build >= WINDOWS_11_MIN_BUILD else "Windows 10 64bit"


def _parse_release_date(raw: str):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


class GigabyteLaptopProvider(DriverProvider):
    """
    model_name: the specific model name (e.g. "AORUS 15X ASF") — used
    both as the search query and to match against the series page's
    product-name attributes (see module docstring step 1-2).
    category: "bios" or "driver" (the GetProductTabDataAsync child key).
    match_substrings: for category="driver", substrings matched
    case-insensitively against each item's info[].infoName (e.g.
    ("Audio",)) to isolate the right component within the shared list.
    Ignored for category="bios" (no such filtering needed there).
    """

    def __init__(self, model_name: str, category: str, match_substrings: tuple[str, ...] = (), name: str = "gigabyte_laptop"):
        self.model_name = model_name
        self.category = category
        self.match_substrings = match_substrings
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def _resolve_product_id(self) -> str | None:
        resp = requests.get(
            SEARCH_URL, params={"keyword": self.model_name, "type": "0"},
            headers={**DEFAULT_HEADERS, "Accept": "application/json"}, timeout=20, impersonate="chrome",
        )
        resp.raise_for_status()
        results = ((resp.json().get("data") or {}).get("data")) or []
        products = [r for r in results if r.get("searchTypeName") == "Products"]
        if not products:
            return None
        series_slug = (products[0].get("document") or {}).get("linkUrl")
        if not series_slug:
            return None

        page_resp = requests.get(f"{BASE_URL}{series_slug}/support", headers=DEFAULT_HEADERS, timeout=20, impersonate="chrome")
        page_resp.raise_for_status()
        pairs = _PRODUCT_NUM_RE.findall(page_resp.text)

        exact = next((pid for pid, name in pairs if name == self.model_name), None)
        if exact:
            return exact
        # fall back to a case-insensitive/substring match in case the
        # WMI-derived name doesn't match the site's exact casing/spacing
        return next((pid for pid, name in pairs if self.model_name.upper() in name.upper() or name.upper() in self.model_name.upper()), None)

    def get_latest(self, device: dict = None) -> dict | None:
        product_id = self._resolve_product_id()
        if product_id is None:
            return None

        resp = requests.get(
            TAB_DATA_URL.format(product_id=product_id),
            headers={**DEFAULT_HEADERS, "Accept": "application/json"}, timeout=20, impersonate="chrome",
        )
        resp.raise_for_status()
        tabs = resp.json().get("data") or []

        items = []
        for tab in tabs:
            for child in tab.get("child") or []:
                if child.get("key") == self.category:
                    items = child.get("data") or []
                    break

        if self.category == "driver" and self.match_substrings:
            items = [
                it for it in items
                if any(
                    s.upper() in (i.get("infoName") or "").upper()
                    for i in it.get("info", [])
                    for s in self.match_substrings
                )
            ]

        if not items:
            return None

        target_os = _detect_windows_name()
        os_matched = [
            it for it in items
            if any((i.get("infoName") or "") == target_os for i in it.get("info", []))
        ]
        if os_matched:
            items = os_matched

        best = max(items, key=lambda it: _parse_release_date(it.get("fileReleaseDate")) or datetime.min.replace(tzinfo=timezone.utc))

        return {
            "version": best.get("fileVersion"),
            "date": best.get("fileReleaseDate"),
            "url": best.get("filePath"),
            "size": best.get("fileSize"),
            "description": best.get("fileDescription"),
        }

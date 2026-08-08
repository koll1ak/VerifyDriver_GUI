"""
Provider for BIOS/Audio drivers from the Lenovo site (pcsupport.lenovo.com).

NOT VERIFIED with a real serial number (step 1, getproducts) — the
author doesn't have a Lenovo laptop on hand. Step 2 (downloads, by
product slug) HAS been confirmed live against several real public
product slugs across different eras (Legion Y540-15IRH-PG0/81sy,
ThinkPad X1 Carbon Gen 9/20xw, Legion 5 Pro 16ACH6H/82jq, and others)
— those runs are what surfaced the fixes below, so unlike Dell this
half of the pipeline is now verified against actual current site
behavior across multiple real models, not just documentation.

Two steps, the way the site itself does it (the page is a heavy JS app
(Angular), there's no content in the source HTML, everything loads via
the API after rendering — confirmed: a plain request returns only the
page skeleton with not a single driver in it):

1. GET https://pcsupport.lenovo.com/{country}/{lang}/api/v4/mse/getproducts?productId=<serial>
   The serial is Win32_BIOS.SerialNumber (on Lenovo hardware this is
   the device's serial number, used as-is). The same pattern is used by
   the third-party Get-LenovoWarranty.ps1 (KelvinTegelaar) to look up
   warranty info by serial: `$req.id` from the response is used as the
   ready-made path to the product page — we take that same field as the
   slug for the second request.

2. GET https://pcsupport.lenovo.com/{country}/{lang}/api/v4/downloads/drivers?productId=<slug from step 1>
   The URL format and response structure are confirmed by a working
   public script (lenovoDriverDownloader.py, Gictorbit, gist.github.com)
   — a real example: ...productId=laptops-and-netbooks/legion-series/legion-y540-15irh-pg0/81sy
   Response: body.DownloadItems — a list of packages, each with
   Category.Name (the category, e.g. "BIOS/UEFI"/"Audio" — confirmed
   real values) and Files — a list of files, each with its own
   Name/URL/Version/Date.Unix fields (confirmed live, see risks below).

Risks — confirmed or still open:
1. CONFIRMED: Lenovo is behind Akamai Bot Manager — curl_cffi with
   impersonate="chrome" alone still got a 403 in a live test; a Referer
   header pointing at the corresponding pcsupport.lenovo.com page was
   also required to get a 200. Both requests below now send one.
   Still open: step 1 (getproducts) itself hasn't been exercised live
   (no real serial on hand) — its Referer is a best-effort guess by
   analogy with step 2's confirmed fix, not independently confirmed.
2. The field carrying the slug in the getproducts response might not be
   named "Id"/"id" for some models — we check both spellings, but if
   it's empty, it's worth checking via DevTools on a real device.
3. The category in Category.Name might be named differently than just
   "BIOS"/"Audio" (e.g. "Audio Driver", "System BIOS Update") — the
   comparison is done as "the search string is a substring of the
   category name", case-insensitive. CONFIRMED against real data: Lenovo
   actually names it "BIOS/UEFI" and "Audio" — both matched correctly.
4. CONFIRMED (and fixed) a real parsing bug: the version is NOT in
   Files[0].Name (that's a plain title like "Realtek Audio Driver", no
   digits) — it's in the separate Files[0].Version field (confirmed
   real values: "6.0.8921.1_WHQL" for Audio, "BHCN45WW" for BIOS). BIOS
   version there is Lenovo's own alphanumeric build code, not a dotted
   number — no numeric comparison is possible for it, same situation as
   Dell/Gigabyte/ASRock, so current=None is intentional/correct for BIOS.
5. The date isn't embedded in the file name either — it's the item's
   own Date.Unix field (epoch milliseconds), used directly now instead
   of a regex search that could never have matched anything.
6. CONFIRMED (and fixed) a real bug: the "BIOS/UEFI" category can also
   contain unrelated utility tools, not just the actual firmware
   (confirmed live: ThinkPad X1 Carbon Gen 9 lists a "Setup Settings
   Capture/Playback Utility" there too) — blindly taking the category's
   first item could return a tool's version instead of the real BIOS
   version. Now filtered to items whose Title says "BIOS Update".
7. CONFIRMED (and fixed) a real bug: some models split a category into
   separate per-OS packages rather than one package covering both
   (confirmed live: Legion 5 Pro 16ACH6H has DISTINCT Windows 10 and
   Windows 11 Realtek Audio entries with different versions — 6.0.9088.1
   vs 6.0.9363.1). Not universal — many models bundle both OSes into one
   package instead — but real often enough that picking blindly risked
   the wrong package. Now prefers the item matching the actual installed
   OS (detect_lenovo_os_name(), same sys.getwindowsversion() pattern as
   nvidia.py/acer_support.py/asus_laptop_driver.py), falling back to the
   unfiltered set when nothing matches (e.g. an "OS Independent" entry).

Install: pip install curl_cffi (already required for MSI).
"""

import re
import sys
from datetime import datetime, timezone

from curl_cffi import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

GETPRODUCTS_URL = "https://pcsupport.lenovo.com/{country}/{lang}/api/v4/mse/getproducts"
DOWNLOADS_URL = "https://pcsupport.lenovo.com/{country}/{lang}/api/v4/downloads/drivers"

# fallback only — used if a file is ever missing its own Version field
_VERSION_RE = re.compile(r"\b\d+(?:\.\d+){1,4}\b")

WINDOWS_11_MIN_BUILD = 22000  # the first build Microsoft calls "Windows 11"


def detect_lenovo_os_name() -> str:
    """
    The exact OperatingSystemKeys string Lenovo uses for the installed
    Windows version — same sys.getwindowsversion().build pattern as
    providers/nvidia.py and providers/acer_support.py. Confirmed live
    (real model: Legion 5 Pro 16ACH6H) that some categories genuinely
    split into separate per-OS packages (distinct Windows 10 and
    Windows 11 Realtek Audio entries) — not universal (many models
    bundle both OSes into one package instead), but real often enough
    that picking blindly risks the wrong package.
    """
    try:
        build = sys.getwindowsversion().build
    except AttributeError:
        return "Windows 10 (64-bit)"  # not Windows — use the default
    return "Windows 11 (64-bit)" if build >= WINDOWS_11_MIN_BUILD else "Windows 10 (64-bit)"


def _format_unix_ms(unix_ms) -> str | None:
    if not unix_ms:
        return None
    try:
        return datetime.fromtimestamp(int(unix_ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OSError, TypeError):
        return None


class LenovoSupportProvider(DriverProvider):
    """
    category: a substring to search for in Category.Name ("BIOS" or
    "Audio"), case-insensitive.
    """

    def __init__(self, serial: str, category: str, country: str = "us", lang: str = "en", name: str = "lenovo_support"):
        self.serial = serial
        self.category = category
        self.country = country
        self.lang = lang
        self.name = name

    def matches(self, device: dict) -> bool:
        # doesn't participate in the PnP device scan — like Dell/Acer,
        # it's called directly from checks/laptop.py based on the
        # laptop's vendor
        return False

    def _resolve_product_slug(self) -> str | None:
        url = GETPRODUCTS_URL.format(country=self.country, lang=self.lang)
        # Referer required to get past Akamai — confirmed live for the
        # downloads endpoint below; here it's the same fix applied by
        # analogy (best-effort generic page, not independently tested —
        # no real serial number on hand, see module docstring risk #1)
        headers = {**DEFAULT_HEADERS, "Referer": f"https://pcsupport.lenovo.com/{self.country}/{self.lang}/"}
        resp = requests.get(
            url, params={"productId": self.serial}, headers=headers,
            timeout=20, impersonate="chrome",
        )
        resp.raise_for_status()
        data = resp.json()
        # this field appears in third-party tools' responses as both
        # "Id" and "id" depending on the endpoint — check both
        return data.get("Id") or data.get("id") or None

    def get_latest(self, device: dict = None) -> dict | None:
        slug = self._resolve_product_slug()
        if slug is None:
            return None  # couldn't find the product by serial number

        page_url = f"https://pcsupport.lenovo.com/{self.country}/{self.lang}/products/{slug}/downloads"

        url = DOWNLOADS_URL.format(country=self.country, lang=self.lang)
        # Referer required to get past Akamai — confirmed live: the same
        # request without it gets a 403, with it a 200 (see docstring)
        headers = {**DEFAULT_HEADERS, "Referer": page_url}
        resp = requests.get(
            url, params={"productId": slug}, headers=headers,
            timeout=20, impersonate="chrome",
        )
        resp.raise_for_status()
        data = resp.json()

        items = (data.get("body") or {}).get("DownloadItems") or []
        category_items = [
            it for it in items
            if self.category.upper() in (((it.get("Category") or {}).get("Name")) or "").upper()
        ]
        if not category_items:
            return None  # category not found among this model's packages

        if self.category.upper() == "BIOS":
            # BIOS/UEFI sometimes also lists unrelated utility tools in
            # the same category (confirmed live: ThinkPad X1 Carbon Gen
            # 9 lists a "Setup Settings Capture/Playback Utility" there
            # alongside the real firmware) — the actual firmware entry's
            # title always says "BIOS Update". Only narrow down when
            # that filter actually finds something, so a model with
            # different wording still falls back to the old behavior
            # instead of returning nothing.
            bios_only = [it for it in category_items if "BIOS UPDATE" in (it.get("Title") or "").upper()]
            if bios_only:
                category_items = bios_only

        # some models split a category into separate per-OS packages
        # (confirmed live, see detect_lenovo_os_name) — prefer the one
        # matching the actually installed OS when that happens; same
        # "only narrow down if it actually matches something" guard
        target_os = detect_lenovo_os_name()
        os_matched = [it for it in category_items if target_os in (it.get("OperatingSystemKeys") or [])]
        if os_matched:
            category_items = os_matched

        for item in category_items:
            files = item.get("Files") or []
            if not files:
                continue

            best_file = files[0]
            # the real version lives in Files[0].Version, not in the
            # human-readable Name (confirmed live — see docstring risk
            # #4); fall back to scanning Name only if Version is ever
            # absent for some model/category
            version = best_file.get("Version") or None
            if not version:
                version_match = _VERSION_RE.search(best_file.get("Name") or "")
                version = version_match.group(0) if version_match else None
            if not version:
                continue

            date = _format_unix_ms((best_file.get("Date") or {}).get("Unix")) \
                or _format_unix_ms((item.get("Date") or {}).get("Unix"))

            return {
                "version": version,
                "date": date,
                "url": best_file.get("URL") or page_url,
                "page_url": page_url,
            }

        return None  # no usable Files entry in any matched item

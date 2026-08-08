"""
Provider for BIOS/Audio drivers from the Lenovo site (pcsupport.lenovo.com).

NOT VERIFIED with a real serial number (step 1, getproducts) — the
author doesn't have a Lenovo laptop on hand. Step 2 (downloads, by
product slug) HAS been confirmed live against a real public product
slug (Legion Y540-15IRH-PG0 / 81sy) — that run is what surfaced the two
fixes below, so unlike Dell this half of the pipeline is now verified
against actual current site behavior, not just documentation.

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

Install: pip install curl_cffi (already required for MSI).
"""

import re
from datetime import datetime, timezone

from curl_cffi import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

GETPRODUCTS_URL = "https://pcsupport.lenovo.com/{country}/{lang}/api/v4/mse/getproducts"
DOWNLOADS_URL = "https://pcsupport.lenovo.com/{country}/{lang}/api/v4/downloads/drivers"

# fallback only — used if a file is ever missing its own Version field
_VERSION_RE = re.compile(r"\b\d+(?:\.\d+){1,4}\b")


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
        for item in items:
            category_name = ((item.get("Category") or {}).get("Name")) or ""
            if self.category.upper() not in category_name.upper():
                continue

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

        return None  # category not found among this model's packages

"""
Provider for BIOS/Audio drivers from the Lenovo site (pcsupport.lenovo.com).

NOT VERIFIED ON A REAL DEVICE (same as providers/dell_support.py) — the
author doesn't have a Lenovo laptop on hand. Unlike Dell, here at least
the real format of both API endpoints and the response structure are
confirmed — from published working tools built by third-party
developers (not just a guess based on documentation).

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
   Category.Name (the category, e.g. "BIOS"/"Audio Driver") and Files —
   a list of files with Name/URL/TypeString fields. There was no
   explicit version field in the confirmed example — we extract it from
   Name with a regex (the same trick used in providers/dell_support.py
   and providers/asrock_driver.py).

Risks worth double-checking on the first real run:
1. Lenovo is behind Akamai Bot Manager (confirmed by a third-party
   bypass service, Piloterr, which describes this directly on its page)
   — so curl_cffi with impersonate="chrome" is used from the start here,
   not as a fallback plan (unlike Dell, where it's only a risk).
2. The field carrying the slug in the getproducts response might not be
   named "Id"/"id" for some models — we check both spellings, but if
   it's empty, it's worth checking via DevTools on a real device.
3. The category in Category.Name might be named differently than just
   "BIOS"/"Audio" (e.g. "Audio Driver", "System BIOS Update") — the
   comparison is done as "the search string is a substring of the
   category name", case-insensitive, to survive that.
4. We don't compare against the installed version (current=None) — same
   as with Dell/Gigabyte/ASRock, it's unknown what format Windows would
   show the BIOS/Audio version in, for comparing against what the
   Lenovo site returns.

Install: pip install curl_cffi (already required for MSI).
"""

import re

from curl_cffi import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

GETPRODUCTS_URL = "https://pcsupport.lenovo.com/{country}/{lang}/api/v4/mse/getproducts"
DOWNLOADS_URL = "https://pcsupport.lenovo.com/{country}/{lang}/api/v4/downloads/drivers"

_VERSION_RE = re.compile(r"\b\d+(?:\.\d+){1,4}\b")
_DATE_RE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{4}")


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
        resp = requests.get(
            url, params={"productId": self.serial}, headers=DEFAULT_HEADERS,
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

        url = DOWNLOADS_URL.format(country=self.country, lang=self.lang)
        resp = requests.get(
            url, params={"productId": slug}, headers=DEFAULT_HEADERS,
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

            name_text = files[0].get("Name") or ""
            version_match = _VERSION_RE.search(name_text)
            if version_match is None:
                continue

            date_match = _DATE_RE.search(name_text)
            page_url = f"https://pcsupport.lenovo.com/{self.country}/{self.lang}/products/{slug}/downloads"

            return {
                "version": version_match.group(0),
                "date": date_match.group(0) if date_match else None,
                "url": files[0].get("URL") or page_url,
                "page_url": page_url,
            }

        return None  # category not found among this model's packages

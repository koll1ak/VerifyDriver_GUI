"""
BIOS provider for Gigabyte / AORUS boards (it's the same site — AORUS is
a Gigabyte sub-brand, there's no separate domain/API).

The support page is fully server-rendered, a plain HTML table under a
"BIOS" heading:

    https://www.gigabyte.com/Motherboard/<MODEL-SLUG>/support

<MODEL-SLUG> is the board name with spaces replaced by hyphens, e.g.
"X870-AORUS-STEALTH" for "X870 AORUS STEALTH".

CONFIRMED LIVE: contrary to what this docstring used to claim, the site
now DOES have bot protection — a plain requests.get() gets a flat 403,
while curl_cffi with impersonate="chrome" gets a normal 200 with no
extra steps needed (no session/cookie dance like MSI needs). Before
this fix, EVERY Gigabyte board's BIOS check was silently failing
(exception caught in checks/bios.py, nothing printed to the report at
all) — this wasn't a subtle bug, the check was completely broken.

The list of versions in the table is sorted newest to oldest — we take
the first row.
"""

import re

from curl_cffi import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider

SUPPORT_PAGE_URL = "https://www.gigabyte.com/Motherboard/{slug}/support"

from providers.http_utils import DEFAULT_HEADERS

HEADERS = DEFAULT_HEADERS


def normalize_gigabyte_slug(product: str) -> str:
    """"X870 AORUS STEALTH" -> "X870-AORUS-STEALTH" """
    return re.sub(r"\s+", "-", product.strip()).upper()


class GigabyteBiosProvider(DriverProvider):
    name = "gigabyte_bios"

    def __init__(self, product_slug: str):
        self.product_slug = product_slug

    def matches(self, device: dict) -> bool:
        # doesn't participate in the PnP device scan — BIOS isn't visible as a regular device
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        url = SUPPORT_PAGE_URL.format(slug=self.product_slug)
        resp = requests.get(url, headers=HEADERS, timeout=20, impersonate="chrome")
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        bios_heading = None
        for heading in soup.find_all(re.compile(r"^h[1-6]$")):
            if heading.get_text(strip=True) == "BIOS":
                bios_heading = heading
                break

        if bios_heading is None:
            return None

        table = bios_heading.find_next("table")
        if table is None:
            return None

        first_row = table.find("tbody").find("tr") if table.find("tbody") else table.find_all("tr")[1]
        cells = first_row.find_all("td")
        if len(cells) < 4:
            return None

        description_cell, version_cell, size_cell, date_cell = cells[0], cells[1], cells[2], cells[3]
        download_link = first_row.find("a", href=True)

        return {
            "version": version_cell.get_text(strip=True),
            "date": date_cell.get_text(strip=True),
            "url": download_link["href"] if download_link else None,
            "size": size_cell.get_text(strip=True),
            "description": re.sub(r"\s+", " ", description_cell.get_text(" ", strip=True)),
        }

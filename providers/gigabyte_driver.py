"""
Provider for (non-BIOS) drivers from the Gigabyte site.

    https://www.gigabyte.com/Motherboard/<MODEL-SLUG>/support

CONFIRMED LIVE, two real findings:

1. Same bot-protection fix as providers/gigabyte_bios.py — plain
   requests.get() gets a flat 403 now, curl_cffi with
   impersonate="chrome" gets a normal 200. Before this fix EVERY
   Gigabyte audio check was silently failing.

2. The site has been restructured since this file was originally
   written: there is no longer one big "Driver" heading with every
   driver type dumped into a single table. Each category now has its
   OWN heading directly — "Audio", "Chipset", "LAN", "WLAN+BT", etc. —
   the exact same layout providers/gigabyte_bios.py already uses for
   "BIOS". The old code searched for a heading literally named
   "Driver", which doesn't exist anymore, so it always returned None
   regardless of the bot-protection issue above.

   Checked live whether the table's OS column (e.g. "Windows 10
   64bit\\nWindows 11 64bit") means a real board can have TWO
   concurrent packages for the same version split by OS, the way ASUS/
   Lenovo do — it does NOT, at least across 5 real boards checked
   (old and new): the newest row is always either OS-unified (current
   packages support both) or the only option for its time (older rows
   predate Windows 11 and just list Windows 10, which is expected, not
   a conflict). So no OS-matching logic is needed here — "take the
   first (newest) row" is correct as originally written.
"""

import re

from curl_cffi import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

SUPPORT_PAGE_URL = "https://www.gigabyte.com/Motherboard/{slug}/support"
HEADERS = DEFAULT_HEADERS


class GigabyteDriverProvider(DriverProvider):
    """
    category: the exact heading text for this driver type on the page
    (e.g. "Audio", "LAN", "Chipset", "WLAN+BT" — confirmed real values).
    match_substrings: optional extra filter on the row's Description,
    in case a category ever lists more than one distinct driver (not
    observed live so far, kept as a safety net).
    """

    def __init__(self, product_slug: str, category: str, match_substrings: tuple[str, ...] = (), name: str = "gigabyte_driver"):
        self.product_slug = product_slug
        self.category = category
        self.match_substrings = match_substrings
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        url = SUPPORT_PAGE_URL.format(slug=self.product_slug)
        resp = requests.get(url, headers=HEADERS, timeout=20, impersonate="chrome")
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        heading = None
        for tag in soup.find_all(re.compile(r"^h[1-6]$")):
            if tag.get_text(strip=True) == self.category:
                heading = tag
                break

        if heading is None:
            return None

        table = heading.find_next("table")
        if table is None:
            return None

        rows = (table.find("tbody") or table).find_all("tr")

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 5:
                continue  # skip the header row and any other non-data rows

            # confirmed live column order: Description | Version | OS | Size | Date | Download
            description_cell, version_cell, size_cell, date_cell = cells[0], cells[1], cells[3], cells[4]
            description = re.sub(r"\s+", " ", description_cell.get_text(" ", strip=True))

            if not all(s.upper() in description.upper() for s in self.match_substrings):
                continue

            download_link = row.find("a", href=True)
            return {
                "version": version_cell.get_text(strip=True),
                "date": date_cell.get_text(strip=True),
                "url": download_link["href"] if download_link else None,
                "size": size_cell.get_text(strip=True),
                "description": description,
            }

        return None

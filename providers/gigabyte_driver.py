"""
Provider for (non-BIOS) drivers from the Gigabyte site — the same page
and the same table structure as BIOS (providers/gigabyte_bios.py), but
data is looked up under a "Driver" heading instead of "BIOS", and inside
that section every driver type (Audio/Chipset/APU/RAID etc.) is dumped
into a single table — we find the right row by a substring in
Description, not by a separate section heading.

    https://www.gigabyte.com/Motherboard/<MODEL-SLUG>/support
"""

import re

import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

SUPPORT_PAGE_URL = "https://www.gigabyte.com/Motherboard/{slug}/support"
HEADERS = DEFAULT_HEADERS


class GigabyteDriverProvider(DriverProvider):
    """
    match_substrings: substrings that must appear in the Description of
    a table row (e.g. ("Realtek", "Audio") for the audio driver).
    """

    def __init__(self, product_slug: str, match_substrings: tuple[str, ...], name: str = "gigabyte_driver"):
        self.product_slug = product_slug
        self.match_substrings = match_substrings
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        url = SUPPORT_PAGE_URL.format(slug=self.product_slug)
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        driver_heading = None
        for heading in soup.find_all(re.compile(r"^h[1-6]$")):
            if heading.get_text(strip=True) == "Driver":
                driver_heading = heading
                break

        if driver_heading is None:
            return None

        table = driver_heading.find_next("table")
        if table is None:
            return None

        rows = (table.find("tbody") or table).find_all("tr")

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            # the "Driver" table (unlike "BIOS") has an OS column between
            # Version and Size: Description | Version | OS | Size | Date | Download
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

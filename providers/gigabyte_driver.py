"""
Провайдер для драйверов с сайта Gigabyte (не BIOS) — та же страница и та
же табличная структура, что и у BIOS (providers/gigabyte_bios.py), но
данные ищутся под заголовком "Driver" вместо "BIOS", и внутри этой секции
все типы драйверов (Audio/Chipset/APU/RAID и т.д.) свалены в одну таблицу —
нужную строку находим по подстроке в Description, а не по отдельному
заголовку раздела.

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
    match_substrings: подстроки, которые должны встретиться в Description
    строки таблицы (например ("Realtek", "Audio") для аудио-драйвера).
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

            # у таблицы "Driver" (в отличие от "BIOS") есть колонка OS между
            # Version и Size: Description | Version | OS | Size | Date | Download
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

"""
Провайдер BIOS для плат Gigabyte / AORUS (это один и тот же сайт —
AORUS — суббренд Gigabyte, отдельного домена/API нет).

Страница поддержки полностью server-rendered, обычная HTML-таблица
под заголовком "BIOS", без JS/API и без защиты от ботов:

    https://www.gigabyte.com/Motherboard/<MODEL-SLUG>/support

<MODEL-SLUG> — имя платы с пробелами, заменёнными на дефисы, например
"X870-AORUS-STEALTH" для "X870 AORUS STEALTH".

Список версий в таблице отсортирован от новой к старой — берём первую
строку.
"""

import re

import requests
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
        # не участвует в обходе PnP-устройств — BIOS не виден как обычное устройство
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        url = SUPPORT_PAGE_URL.format(slug=self.product_slug)
        resp = requests.get(url, headers=HEADERS, timeout=20)
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

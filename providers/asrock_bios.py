"""
Провайдер BIOS для плат ASRock.

Страница полностью server-rendered, обычная HTML-таблица, без JS/API:

    https://www.asrock.com/mb/<family>/<MODEL NAME>/bios.html

<family> — "amd" или "intel" (сегмент пути на сайте ASRock, зависит от
платформы чипсета).
<MODEL NAME> — имя платы как есть, с пробелами (URL-кодируются автоматически
библиотекой requests) — в отличие от MSI/Gigabyte, дефисы тут не нужны.

Список версий отсортирован от новой к старой — берём первую строку.
"""

import re

import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider

BIOS_PAGE_URL = "https://www.asrock.com/mb/{family}/{model}/bios.html"

from providers.http_utils import DEFAULT_HEADERS

HEADERS = DEFAULT_HEADERS


class AsrockBiosProvider(DriverProvider):
    name = "asrock_bios"

    def __init__(self, model: str, family: str = "amd"):
        self.model = model
        self.family = family

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        url = BIOS_PAGE_URL.format(family=self.family, model=self.model)
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        table = soup.find("table")
        if table is None:
            return None

        body = table.find("tbody") or table
        rows = body.find_all("tr")
        # первая строка может быть заголовком — пропускаем строки без <td>
        data_rows = [r for r in rows if r.find("td")]
        if not data_rows:
            return None

        first_row = data_rows[0]
        cells = first_row.find_all("td")
        if len(cells) < 3:
            return None

        version_cell, date_cell, size_cell = cells[0], cells[1], cells[2]

        # ссылка на Global-загрузку (не China/FTP) — ищем первую <a href> на download.asrock.com
        download_link = None
        for a in first_row.find_all("a", href=True):
            if "download.asrock.com" in a["href"]:
                download_link = a["href"]
                break

        return {
            "version": re.sub(r"\s+", " ", version_cell.get_text(strip=True)),
            "date": date_cell.get_text(strip=True),
            "url": download_link,
            "size": size_cell.get_text(strip=True),
        }

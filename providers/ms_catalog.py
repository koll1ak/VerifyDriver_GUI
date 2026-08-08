"""
Провайдер для драйверов, которые распространяются ТОЛЬКО через Windows
Update, без отдельной страницы загрузок у производителя чипа (типичный
случай для Qualcomm/некоторых MediaTek WiFi-модулей — в отличие от Intel,
у которого есть отдельная официальная страница, см. providers/intel_download.py).

    GET https://www.catalog.update.microsoft.com/Search.aspx?q=<query>

Страница server-rendered (обычная HTML-таблица), JS не нужен.
"""

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

SEARCH_URL = "https://www.catalog.update.microsoft.com/Search.aspx"


class MsCatalogProvider(DriverProvider):
    """
    query: поисковый запрос — обычно точное имя устройства из Windows
           (например "Qualcomm QCA6174" или "MediaTek Wi-Fi 6")
    title_contains: доп. фильтр по названию записи в каталоге, если нужно
                     сузить (например "Driver"), можно оставить пустым
    """

    def __init__(self, query: str, title_contains: str = "", name: str = "ms_catalog"):
        self.query = query
        self.title_contains = title_contains
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        resp = requests.get(
            SEARCH_URL,
            params={"q": self.query},
            headers=DEFAULT_HEADERS,
            timeout=20,
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", id="ctl00_catalogBody_updateMatches")
        if table is None:
            return None

        best = None
        best_date = None

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 6:
                continue  # пропускаем заголовок и служебные строки

            title = cells[1].get_text(strip=True)
            if self.title_contains and self.title_contains.upper() not in title.upper():
                continue

            date_str = cells[4].get_text(strip=True)
            version = cells[5].get_text(strip=True)

            date = self._parse_date(date_str)
            if date is None:
                continue

            if best_date is None or date > best_date:
                best_date = date
                best = {
                    "version": version,
                    "date": date_str,
                    "title": title,
                    "url": SEARCH_URL + f"?q={self.query}",
                }

        return best

    @staticmethod
    def _parse_date(date_str: str):
        # формат вида "1/20/2026"
        try:
            return datetime.strptime(date_str, "%m/%d/%Y")
        except ValueError:
            return None

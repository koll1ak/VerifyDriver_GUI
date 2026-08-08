"""
Провайдер для драйверов с сайта ASRock (не BIOS) — та же схема сайта,
что и у BIOS (providers/asrock_bios.py):

    https://www.asrock.com/mb/<family>/<MODEL NAME>/driver.html

ВАЖНО: точная структура таблицы на странице driver.html НЕ была
проверена напрямую (в отличие от bios.html, которую разбирали по
реальному HTML) — колонки могут идти в другом порядке или их может
быть больше (например добавлена колонка OS, как оказалось на Gigabyte).
Поэтому здесь версия/дата/размер ищутся по паттерну содержимого ячейки,
а не по фиксированному индексу — устойчивее к неизвестной раскладке
колонок, но при первом реальном запуске стоит свериться с выводом.
"""

import re

import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

DRIVER_PAGE_URL = "https://www.asrock.com/mb/{family}/{model}/driver.html"
HEADERS = DEFAULT_HEADERS

_DATE_RE = re.compile(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{4}")
_SIZE_RE = re.compile(r"\d+(\.\d+)?\s*(MB|KB|GB)", re.IGNORECASE)
_VERSION_RE = re.compile(r"^[\dvV][\d.]*$")


class AsrockDriverProvider(DriverProvider):
    """match_substrings: подстроки, обязательные в тексте строки (например ("Realtek", "Audio"))."""

    def __init__(self, model: str, match_substrings: tuple[str, ...], family: str = "amd", name: str = "asrock_driver"):
        self.model = model
        self.family = family
        self.match_substrings = match_substrings
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        url = DRIVER_PAGE_URL.format(family=self.family, model=self.model)
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        for table in soup.find_all("table"):
            body = table.find("tbody") or table
            rows = [r for r in body.find_all("tr") if r.find("td")]

            for row in rows:
                row_text = row.get_text(" ", strip=True)
                if not all(s.upper() in row_text.upper() for s in self.match_substrings):
                    continue

                cells = [c.get_text(strip=True) for c in row.find_all("td")]

                date = next((c for c in cells if _DATE_RE.search(c)), None)
                size = next((c for c in cells if _SIZE_RE.search(c)), None)
                version = next(
                    (c for c in cells if _VERSION_RE.match(c) and c != date and c != size),
                    None,
                )

                download_link = None
                for a in row.find_all("a", href=True):
                    if "download.asrock.com" in a["href"]:
                        download_link = a["href"]
                        break

                return {
                    "version": version,
                    "date": date,
                    "size": size,
                    "url": download_link,
                    "raw_row_text": row_text,  # на случай если авто-разбор не сработал — видно, что реально в строке
                }

        return None

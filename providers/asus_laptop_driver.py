"""
Провайдер для ноутбуков ASUS — использует официальный JSON API страницы
поддержки (не текстовую эвристику, как providers/asus_driver.py, которая
писалась под десктопные платы и не подходит для ноутбучных страниц —
там список драйверов подгружается через этот отдельный эндпоинт).

    GET https://www.asus.com/support/webapi/ProductV2/GetPDDrivers
        ?website=us&model=<model>&pdhashedid=&cpu=&osid=<osid>&pdid=99999&siteID=www&sitelang=

Структура ответа:
{
  "Result": {
    "Obj": [
      {"Name": "Audio", "Files": [
several по типу
        {"Id": "...Realtek Codec Console Application", "Version": "latest version at the MS store", ...},
        {"Id": "...Audio_DriverOnly_Dolby_DCH_Realtek_J_V6.0.9768.1_41645_1.exe", "INFDate": "12-03-2024", ...},
      ]},
      ...
    ]
  }
}

Версия реального установочного пакета зашита в имя файла ("_V6.0.9768.1_"),
а не в отдельном поле Version (то иногда занято служебным текстом вроде
"latest version at the MS store" — MS Store приложение, не установщик,
такие записи пропускаем). Дата — INFDate в формате MM-DD-YYYY.
"""

import re
from datetime import datetime

import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

API_URL = "https://www.asus.com/support/webapi/ProductV2/GetPDDrivers"

# 52 — код Windows 11 64-bit в системе ASUS (подтверждено на реальном запросе)
DEFAULT_OS_ID = "52"

_VERSION_IN_FILENAME_RE = re.compile(r"_V([\d.]+)_")


def _parse_inf_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%m-%d-%Y")
    except (ValueError, TypeError):
        return None


class AsusLaptopDriverProvider(DriverProvider):
    """
    category: точное имя категории в ответе API — "Audio", "Networking",
    "Chipset" и т.п. (видно в самом ответе, у ASUS не всегда совпадает
    с тем, что было бы логично предположить — например LAN у них
    "Networking", не "Lan").
    match_substrings: подстроки, обязательные в Id/ExeModule файла
    (например ("Realtek",) чтобы не спутать с другим вендором в той же
    категории).
    """

    def __init__(self, model: str, category: str, match_substrings: tuple[str, ...], os_id: str = DEFAULT_OS_ID, name: str = "asus_laptop_driver"):
        self.model = model
        self.category = category
        self.match_substrings = match_substrings
        self.os_id = os_id
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        resp = requests.get(
            API_URL,
            params={
                "website": "us",
                "model": self.model,
                "pdhashedid": "",
                "cpu": "",
                "osid": self.os_id,
                "pdid": "99999",
                "siteID": "www",
                "sitelang": "",
            },
            headers=DEFAULT_HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        categories = data.get("Result", {}).get("Obj", []) or []
        category_data = next(
            (c for c in categories if c.get("Name", "").upper() == self.category.upper()),
            None,
        )
        if category_data is None:
            return None

        candidates = []
        for f in category_data.get("Files", []) or []:
            identifier = f.get("Id", "") or f.get("ExeModule", "")
            if not all(s.upper() in identifier.upper() for s in self.match_substrings):
                continue
            version_match = _VERSION_IN_FILENAME_RE.search(identifier)
            if version_match is None:
                continue  # например служебная запись без версии в имени
            candidates.append((f, version_match.group(1)))

        if not candidates:
            return None

        best_file, best_version = max(
            candidates, key=lambda pair: _parse_inf_date(pair[0].get("INFDate", "")) or datetime.min
        )

        return {
            "version": best_version,
            "date": best_file.get("INFDate"),
            "size": best_file.get("FileSize"),
            "description": best_file.get("Description"),
        }

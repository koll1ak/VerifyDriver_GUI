"""
Общая логика для провайдеров категорий на realtek.com — LAN и Audio
используют один и тот же JSON API, отличаются только cate_id и способом
выбора нужной записи в списке (LAN фильтрует по подстроке в Description,
Audio просто берёт самую свежую).

    GET https://www.realtek.com/Download/ListAllDownloadItem?cate_id=<CATE_ID>
"""

import time

import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS, DEFAULT_TIMEOUT

API_URL = "https://www.realtek.com/Download/ListAllDownloadItem"
BASE_URL = "https://www.realtek.com"

HEADERS = {**DEFAULT_HEADERS, "Accept": "application/json"}


class RealtekCategoryProvider(DriverProvider):
    """
    Базовый класс для любой категории на realtek.com/Download/ListAllDownloadItem.
    Наследники обязаны реализовать matches() под свой Vendor ID/тип устройства,
    и могут передать match_substrings для фильтрации конкретного варианта
    драйвера внутри категории (если в ней несколько вариантов).
    """

    def __init__(self, cate_id: str, match_substrings: tuple[str, ...] | None = None):
        self.cate_id = cate_id
        self.match_substrings = match_substrings

    def matches(self, device: dict) -> bool:
        raise NotImplementedError

    def _select_item(self, windows_items: list[dict]) -> dict | None:
        if not windows_items:
            return None
        if self.match_substrings:
            return next(
                (i for i in windows_items if all(s in i.get("Description", "") for s in self.match_substrings)),
                None,
            )
        return windows_items[0]  # список отсортирован: новые сверху

    def get_latest(self, device: dict = None) -> dict | None:
        resp = requests.get(
            API_URL,
            params={"cate_id": self.cate_id, "_": int(time.time() * 1000)},
            headers=HEADERS,
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        windows_items = data.get("Data", {}).get("DownloadItems", {}).get("Windows", [])
        item = self._select_item(windows_items)
        if item is None:
            return None

        download_url = item.get("DownloadUrl", "")
        if download_url.startswith("/"):
            download_url = BASE_URL + download_url

        return {
            "version": item.get("Version"),
            "date": item.get("UpdateTime"),
            "url": download_url,
            "size": item.get("FileSize"),
            "name": item.get("Name"),
            "description": item.get("Description"),
        }

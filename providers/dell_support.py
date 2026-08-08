"""
Провайдер для BIOS/Audio-драйверов с сайта Dell по Service Tag.

    https://www.dell.com/support/home/en-us/product-support/servicetag/<TAG>/drivers

НЕ ПРОВЕРЕНО НА РЕАЛЬНОМ УСТРОЙСТВЕ (в отличие от MSI/AMD/Gigabyte/ASRock/
ASUS, где структуру разбирали по реальным скриншотам с конкретной машины) —
у автора нет ни одного Dell-ноутбука под рукой. Написано по документированному
паттерну (Service Tag → страница драйверов, категории включая "BIOS" и
"Audio", версия+дата+размер видны в интерфейсе) и по аналогии с уже
проверенными провайдерами.

Риски, которые стоит проверить при первом реальном запуске:
1. Страница может оказаться тяжёлым JS-приложением (Dell.com в целом
   использует сложные Angular/React-компоненты) — тогда нужного контента
   в простом requests.get() просто не будет, придётся искать реальный
   API-эндпоинт через DevTools, как делали для MSI/AMD chipset.
2. Возможна защита от ботов (Akamai или похожая) — тогда потребуется
   curl_cffi с impersonate="chrome", как в providers/msi_bios.py.
3. Категории на сайте называются "BIOS" и "Audio" по документации Dell,
   но точный текст категории на странице может отличаться регистром/
   формулировкой — сравнение сделано без учёта регистра, чтобы это
   пережить, но сам факт совпадения не гарантирован.

Парсинг — по текстовым паттернам (год-месяц-день для даты, "MB"/"KB" для
размера, версия — первая последовательность цифр с точками рядом с меткой
категории), а не по конкретным CSS-классам/индексам столбцов — так же, как
в providers/asrock_driver.py и providers/asus_driver.py, по той же причине
(меньше риск сломаться на неизвестной вёрстке).
"""

import re

import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

DRIVERS_PAGE_URL = "https://www.dell.com/support/home/en-us/product-support/servicetag/{service_tag}/drivers"
HEADERS = DEFAULT_HEADERS

_VERSION_RE = re.compile(r"\b\d+(?:\.\d+){1,4}\b")
_DATE_RE = re.compile(r"\d{1,2}\s+\w+\s+\d{4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{4}")
_SIZE_RE = re.compile(r"\d+(\.\d+)?\s*(MB|KB|GB)", re.IGNORECASE)


class DellSupportProvider(DriverProvider):
    """
    category: "BIOS" или "Audio" (ищется как отдельное слово в тексте
    страницы, без учёта регистра).
    """

    def __init__(self, service_tag: str, category: str, name: str = "dell_support"):
        self.service_tag = service_tag
        self.category = category
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        url = DRIVERS_PAGE_URL.format(service_tag=self.service_tag)
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()

        text = resp.text

        # ищем позицию упоминания нужной категории на странице, затем
        # версию/дату/размер в окне текста сразу после неё — так же, как
        # это выглядит на странице для пользователя (категория, затем
        # детали конкретного пакета)
        category_match = re.search(re.escape(self.category), text, re.IGNORECASE)
        if category_match is None:
            return None

        window = text[category_match.end():category_match.end() + 2000]

        # убираем HTML-теги из окна, чтобы регексы искали по видимому тексту,
        # а не по разметке
        window_text = re.sub(r"<[^>]+>", " ", window)
        window_text = re.sub(r"\s+", " ", window_text)

        version_match = _VERSION_RE.search(window_text)
        date_match = _DATE_RE.search(window_text)
        size_match = _SIZE_RE.search(window_text)

        if version_match is None:
            return None

        return {
            "version": version_match.group(0),
            "date": date_match.group(0) if date_match else None,
            "size": size_match.group(0) if size_match else None,
            "url": url,  # прямой ссылки на файл эвристика не даёт — ведём на страницу
            "page_url": url,
        }

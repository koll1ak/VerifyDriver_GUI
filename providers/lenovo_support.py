"""
Провайдер для BIOS/Audio-драйверов с сайта Lenovo (pcsupport.lenovo.com).

НЕ ПРОВЕРЕНО НА РЕАЛЬНОМ УСТРОЙСТВЕ (как и providers/dell_support.py) —
у автора нет Lenovo-ноутбука под рукой. В отличие от Dell, здесь хотя бы
подтверждён реальный формат обоих API-эндпоинтов и структура ответа — по
опубликованным рабочим инструментам сторонних разработчиков (не просто
предположение по документации).

Два шага, как это делает сам сайт (страница — тяжёлое JS-приложение
(Angular), содержимого нет в исходном HTML, всё подгружается через API
уже после рендера — подтверждено: обычный запрос отдаёт только каркас
страницы без единого драйвера):

1. GET https://pcsupport.lenovo.com/{country}/{lang}/api/v4/mse/getproducts?productId=<серийник>
   Серийник — Win32_BIOS.SerialNumber (на технике Lenovo это и есть
   серийный номер устройства, используется как есть). Этот же паттерн
   использует сторонний Get-LenovoWarranty.ps1 (KelvinTegelaar) для
   поиска гарантии по серийнику: `$req.id` из ответа используется как
   готовый путь к странице продукта — берём это же поле как slug для
   второго запроса.

2. GET https://pcsupport.lenovo.com/{country}/{lang}/api/v4/downloads/drivers?productId=<slug из шага 1>
   Формат URL и структура ответа подтверждены рабочим публичным скриптом
   (lenovoDriverDownloader.py, Gictorbit, gist.github.com) — реальный
   пример: ...productId=laptops-and-netbooks/legion-series/legion-y540-15irh-pg0/81sy
   Ответ: body.DownloadItems — список пакетов, у каждого Category.Name
   (категория, например "BIOS"/"Audio Driver") и Files — список файлов
   с полями Name/URL/TypeString. Явного поля версии в подтверждённом
   примере не было — извлекаем её из Name регэкспом (тот же приём, что
   в providers/dell_support.py и providers/asrock_driver.py).

Риски, которые стоит перепроверить при первом реальном запуске:
1. Lenovo прикрыт Akamai Bot Manager (подтверждено сторонним сервисом
   обхода Piloterr, который прямо описывает это на своей странице) —
   поэтому здесь сразу используется curl_cffi с impersonate="chrome",
   а не как запасной план (в отличие от Dell, где это только риск).
2. Поле со slug в ответе getproducts может называться не "Id"/"id" для
   каких-то моделей — проверяем оба варианта написания, но если пусто —
   стоит свериться через DevTools на реальном устройстве.
3. Категория в Category.Name может называться иначе, чем просто "BIOS"/
   "Audio" (например "Audio Driver", "System BIOS Update") — сравнение
   сделано как "искомая строка — подстрока названия категории" без учёта
   регистра, чтобы это пережить.
4. Сравнение с установленной версией не делаем (current=None) — как и у
   Dell/Gigabyte/ASRock, неизвестно, в каком формате Windows покажет
   версию BIOS/Audio для сравнения именно с тем, что отдаёт сайт Lenovo.

Установка: pip install curl_cffi (уже требуется для MSI).
"""

import re

from curl_cffi import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

GETPRODUCTS_URL = "https://pcsupport.lenovo.com/{country}/{lang}/api/v4/mse/getproducts"
DOWNLOADS_URL = "https://pcsupport.lenovo.com/{country}/{lang}/api/v4/downloads/drivers"

_VERSION_RE = re.compile(r"\b\d+(?:\.\d+){1,4}\b")
_DATE_RE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{4}")


class LenovoSupportProvider(DriverProvider):
    """
    category: подстрока для поиска в Category.Name ("BIOS" или "Audio"),
    без учёта регистра.
    """

    def __init__(self, serial: str, category: str, country: str = "us", lang: str = "en", name: str = "lenovo_support"):
        self.serial = serial
        self.category = category
        self.country = country
        self.lang = lang
        self.name = name

    def matches(self, device: dict) -> bool:
        # не участвует в обходе PnP-устройств — как Dell/Acer, вызывается
        # напрямую из checks/laptop.py по факту вендора ноутбука
        return False

    def _resolve_product_slug(self) -> str | None:
        url = GETPRODUCTS_URL.format(country=self.country, lang=self.lang)
        resp = requests.get(
            url, params={"productId": self.serial}, headers=DEFAULT_HEADERS,
            timeout=20, impersonate="chrome",
        )
        resp.raise_for_status()
        data = resp.json()
        # поле встречается в ответах сторонних инструментов и как "Id",
        # и как "id" в зависимости от эндпоинта — проверяем оба
        return data.get("Id") or data.get("id") or None

    def get_latest(self, device: dict = None) -> dict | None:
        slug = self._resolve_product_slug()
        if slug is None:
            return None  # не удалось найти продукт по серийнику

        url = DOWNLOADS_URL.format(country=self.country, lang=self.lang)
        resp = requests.get(
            url, params={"productId": slug}, headers=DEFAULT_HEADERS,
            timeout=20, impersonate="chrome",
        )
        resp.raise_for_status()
        data = resp.json()

        items = (data.get("body") or {}).get("DownloadItems") or []
        for item in items:
            category_name = ((item.get("Category") or {}).get("Name")) or ""
            if self.category.upper() not in category_name.upper():
                continue

            files = item.get("Files") or []
            if not files:
                continue

            name_text = files[0].get("Name") or ""
            version_match = _VERSION_RE.search(name_text)
            if version_match is None:
                continue

            date_match = _DATE_RE.search(name_text)
            page_url = f"https://pcsupport.lenovo.com/{self.country}/{self.lang}/products/{slug}/downloads"

            return {
                "version": version_match.group(0),
                "date": date_match.group(0) if date_match else None,
                "url": files[0].get("URL") or page_url,
                "page_url": page_url,
            }

        return None  # категория не найдена среди пакетов этой модели

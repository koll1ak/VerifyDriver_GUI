"""
Провайдер BIOS/Audio-драйверов с сайта Acer.

    POST https://www.acer.com/us-en/DynamicContent/GetDriversAndManuals
    Body (JSON): {"ModelName": "<MODEL>", "Local": "en-us"}

Структура разобрана на реальных данных (Acer Nitro AN515-55). Ответ —
JSON, где нужное содержимое лежит ДВАЖДЫ закодированным: в
hits[0]._source.global_download_details лежит СТРОКА, которую нужно
ещё раз распарсить как JSON — внутри неё уже категории driver/bios/
userguide/application со списками файлов.

BIOS: секция "bios" -> "files", фильтруем по category == "BIOS" (не
"Firmware" — это отдельно VBIOS видеокарты, не системный BIOS), версии
без разделения по ОС.

Audio: секция "driver" -> "files", фильтруем по category == "Audio" И
по полю "oss" (значения вида "11M1"/"10M1" — Windows 11/10) — важно не
перепутать: без этого фильтра можно получить версию под чужую ОС.

<MODEL> — Win32_ComputerSystem.Model без префикса линейки продукта
(например "Nitro AN515-55" -> "AN515-55").
"""

import json
import re
import sys

from curl_cffi import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

API_URL = "https://www.acer.com/us-en/DynamicContent/GetDriversAndManuals"
HEADERS = {**DEFAULT_HEADERS, "Content-Type": "application/json", "Accept": "application/json"}

_DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")


def _date_sort_key(date_str: str):
    m = _DATE_RE.match(date_str or "")
    if not m:
        return (0, 0, 0)
    return tuple(int(g) for g in m.groups())


def detect_acer_os_code() -> str:
    """
    "11M1"/"10M1" — коды ОС, которые использует Acer в поле "oss".
    Определяется так же, как в providers/nvidia.py (через билд системы).
    """
    try:
        build = sys.getwindowsversion().build
    except AttributeError:
        return "10M1"  # не Windows — дефолт
    return "11M1" if build >= 22000 else "10M1"


class AcerSupportProvider(DriverProvider):
    """
    category: "BIOS" или "Audio".
    os_code: нужен только для category="Audio" (у BIOS разделения по ОС нет);
             если не передан — определяется автоматически по текущей системе.
    """

    def __init__(
        self,
        model_name: str,
        category: str,
        os_code: str | None = None,
        part_number: str | None = None,
        serial: str | None = None,
        name: str = "acer_support",
    ):
        self.model_name = model_name
        self.category = category
        self.os_code = os_code or detect_acer_os_code()
        self.part_number = part_number
        self.serial = serial
        self.name = name

    def _build_page_url(self) -> str:
        # полный URL требует ещё номер детали и серийник (иначе страница не
        # существует) — если их не передали, отдаём укороченный вариант
        # как максимально близкое приближение
        if self.part_number and self.serial:
            return (
                f"https://www.acer.com/us-en/support/product-support/"
                f"{self.model_name}/{self.part_number}/downloads?sn={self.serial}"
            )
        return f"https://www.acer.com/us-en/support/product-support/{self.model_name}"

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        # так же, как у MSI: сначала посещаем саму страницу товара (чтобы
        # получить cookies сессии), затем делаем API-запрос в её рамках.
        # curl_cffi с impersonate="chrome" — сайт похож на MSI/Intel: держит
        # соединение до таймаута вместо явного отказа для "небраузерных"
        # клиентов (похоже на защиту вроде Akamai).
        session = requests.Session(impersonate="chrome")
        session.headers.update(HEADERS)

        product_page_url = self._build_page_url()
        try:
            session.get(product_page_url, timeout=20)
        except Exception:
            pass  # не критично, даже если страница не отдалась — пробуем API всё равно

        resp = session.post(
            API_URL,
            json={"ModelName": self.model_name, "Local": "en-us"},
            headers={**HEADERS, "Referer": product_page_url},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        hits = data.get("hits", [])
        if not hits:
            return None

        raw_details = hits[0].get("_source", {}).get("global_download_details")
        if not raw_details:
            return None

        try:
            details = json.loads(raw_details)
        except json.JSONDecodeError:
            return None

        if self.category.upper() == "BIOS":
            files = details.get("bios", {}).get("files") or []
            candidates = [f for f in files if f.get("category", "").upper() == "BIOS"]
        else:
            files = details.get("driver", {}).get("files") or []
            candidates = [
                f for f in files
                if f.get("category", "").upper() == self.category.upper() and f.get("oss") == self.os_code
            ]
            if not candidates:
                # для этой модели в каталоге Acer может не быть отдельного
                # пакета под твою версию Windows (например только "11M1",
                # хотя у тебя Win10) — тогда берём самую свежую запись под
                # ЛЮБУЮ ОС как справочную информацию, без уверенности, что
                # она точно подходит именно твоей системе
                candidates = [
                    f for f in files if f.get("category", "").upper() == self.category.upper()
                ]
                if candidates:
                    latest = max(candidates, key=lambda f: _date_sort_key(f.get("date", "")))
                    file_link = latest.get("link")
                    download_url = f"https://www.acer.com/{file_link}" if file_link else None
                    return {
                        "version": latest.get("version"),
                        "date": latest.get("date"),
                        "size": latest.get("size"),
                        "description": latest.get("description"),
                        "url": download_url,
                        "page_url": self._build_page_url(),
                        "os_mismatch": True,  # для этой ОС отдельной записи нет — сверку лучше не доверять
                    }

        if not candidates:
            return None

        latest = max(candidates, key=lambda f: _date_sort_key(f.get("date", "")))

        # "link" в ответе — относительный путь к файлу (без домена),
        # достраиваем до полного рабочего URL; "page_url" — страница
        # продукта целиком, полезна как запасной вариант для ручной проверки
        file_link = latest.get("link")
        download_url = f"https://www.acer.com/{file_link}" if file_link else None
        page_url = self._build_page_url()

        return {
            "version": latest.get("version"),
            "date": latest.get("date"),
            "url": download_url,
            "page_url": page_url,
            "size": latest.get("size"),
            "description": latest.get("description"),
        }

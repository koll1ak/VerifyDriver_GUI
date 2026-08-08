"""
Провайдер для драйверов с сайта ASUS (не BIOS).

    https://www.asus.com/us/supportonly/<MODEL>/helpdesk_driver/

ВАЖНО: в отличие от providers/asus_bios.py (структуру которого разобрали
по реальному HTML со страницы), точные CSS-классы для вкладки "Driver"
не проверялись — судя по коду сайта, это отдельный компонент
(DriverPanel.js, не BIOSPanel.js), поэтому имена классов могут отличаться
от "ProductSupportDriverBIOS__...". Чтобы не зависеть от угаданных
классов, здесь используется текстовый эвристический разбор: ищем
элемент, в тексте которого одновременно есть "Realtek"+"Audio" и рядом
паттерн "Version X.X.X" — независимо от конкретной разметки/классов.
Менее точно, чем classname-based парсер, но не сломается при
косметическом редизайне сайта.
"""

import re
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

SUPPORT_PAGE_URL = "https://www.asus.com/us/supportonly/{model}/helpdesk_driver/"
HEADERS = DEFAULT_HEADERS

_VERSION_RE = re.compile(r"Version\s+V?([\d.]+)")
_DATE_RE = re.compile(r"\d{4}/\d{1,2}/\d{1,2}")
_SIZE_RE = re.compile(r"\d+(\.\d+)?\s*(MB|KB|GB)", re.IGNORECASE)


class AsusDriverProvider(DriverProvider):
    """match_substrings: подстроки, обязательные в тексте карточки (например ("Realtek", "Audio"))."""

    def __init__(self, model: str, match_substrings: tuple[str, ...], name: str = "asus_driver"):
        self.model = model
        self.match_substrings = match_substrings
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        url = SUPPORT_PAGE_URL.format(model=quote(self.model.lower()))
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Ищем от НАЗВАНИЯ драйвера (уникальная фраза вроде "Realtek Audio
        # Driver"), а не от версии — так надёжнее: климб вверх от версии
        # рискует "перепрыгнуть" границу карточки и попасть в общий
        # контейнер, где искомые слова тоже встретятся, но уже от другой
        # записи на странице. Ищем "листовые" элементы (без вложенных
        # div/p/span), чей ТЕКСТ САМ ПО СЕБЕ содержит обе подстроки —
        # это и есть заголовок нужной карточки.
        title_tag = None
        for tag in soup.find_all(["div", "p", "span"]):
            if tag.find(["div", "p", "span"]):
                continue  # не листовой элемент — пропускаем
            text = tag.get_text(strip=True)
            if all(s.upper() in text.upper() for s in self.match_substrings):
                title_tag = tag
                break

        if title_tag is None:
            return None

        # поднимаемся на несколько уровней вверх до "карточки" — целой
        # записи об этом драйвере, где рядом должны быть версия/дата/размер
        card = title_tag
        for _ in range(4):
            if card is None:
                break
            card_text = card.get_text(" ", strip=True)
            version_match = _VERSION_RE.search(card_text)
            if version_match:
                date_match = _DATE_RE.search(card_text)
                size_match = _SIZE_RE.search(card_text)
                download_link = card.find("a", href=True)
                return {
                    "version": version_match.group(1),
                    "date": date_match.group(0) if date_match else None,
                    "size": size_match.group(0) if size_match else None,
                    "url": download_link["href"] if download_link else None,
                }
            card = card.parent

        return None

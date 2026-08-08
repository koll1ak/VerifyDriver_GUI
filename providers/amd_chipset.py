"""
Провайдер AMD Chipset Software.

Страница поддержки чипсета (support.amd.com) отдаёт список драйверов
прямо в серверном HTML — никакого скрытого API/JS не нужно. Каждый
драйвер — это <article class="driver-download-details"> с <h4>-названием
и парой блоков col-6 col-lg (Revision Number / File Size / Release Date)
плюс кнопкой Download.

Страница разбита на аккордеоны по ОС (Windows 11 / Windows 10) — данные
внутри обычно идентичны, берём первое совпадение.
"""

import re
import subprocess

import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider

CHIPSET_PAGE_URL = "https://www.amd.com/en/support/downloads/drivers.html/chipsets/am5/x870.html"
DRIVER_NAME = "AMD Chipset Drivers"

# PowerShell: ищем версию установленного пакета "AMD Chipset Software"
# в записях Uninstall реестра (там же, где его видит "Установка и удаление программ")
_GET_INSTALLED_VERSION_PS = (
    "Get-ItemProperty "
    "'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*', "
    "'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*' "
    "-ErrorAction SilentlyContinue | "
    "Where-Object { $_.DisplayName -like '*AMD Chipset*' } | "
    "Select-Object -First 1 -ExpandProperty DisplayVersion"
)


def get_current_amd_chipset_version() -> str | None:
    """Версия установленного пакета AMD Chipset Software (из реестра Uninstall)."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", _GET_INSTALLED_VERSION_PS],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    version = result.stdout.strip()
    return version or None

from providers.http_utils import DEFAULT_HEADERS, DEFAULT_TIMEOUT

# без UA страница иногда отдаёт урезанный ответ через Akamai
HEADERS = DEFAULT_HEADERS


class AmdChipsetProvider(DriverProvider):
    """
    Универсальный провайдер для страниц amd.com/en/support/downloads/drivers.html/...
    Работает и для chipset-страниц, и для страниц видеокарт (Radeon) —
    структура HTML одна и та же на всём сайте, отличаются только page_url,
    driver_name и формат самого номера версии.

    version_regex: если версия дана не в чистом виде (например
    "Adrenalin 26.5.2 (WHQL Recommended)" у видеокарт вместо "8.07.16.1035"
    у чипсета), передаётся regex для извлечения номера из текста.
    """

    name = "amd_chipset"

    def __init__(
        self,
        page_url: str = CHIPSET_PAGE_URL,
        driver_name: str = DRIVER_NAME,
        version_regex: str | None = None,
        vendor_match_keywords=("SMBUS", "CHIPSET", "PCIE ROOT", "PCI ROOT"),
    ):
        self.page_url = page_url
        self.driver_name = driver_name
        self.version_regex = re.compile(version_regex) if version_regex else None
        self.vendor_match_keywords = vendor_match_keywords

    def matches(self, device: dict) -> bool:
        return (
            device.get("VendorID") == "1022"  # AMD PCI Vendor ID
            and any(
                kw in device.get("DeviceName", "").upper()
                for kw in self.vendor_match_keywords
            )
        )

    def get_latest(self, device: dict = None) -> dict | None:
        resp = requests.get(self.page_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        for article in soup.select("article.driver-download-details"):
            h4 = article.find("h4")
            if not h4 or h4.get_text(strip=True) != self.driver_name:
                continue

            revision = self._extract_field(article, "Revision Number")
            release_date = self._extract_field(article, "Release Date")
            download_link = article.select_one("a[href*='drivers.amd.com']")

            if revision is None:
                continue

            version = revision
            if self.version_regex:
                m = self.version_regex.search(revision)
                if m:
                    version = m.group(1)

            return {
                "version": version,
                "raw_revision": revision,
                "date": release_date,
                "url": download_link["href"] if download_link else None,
            }

        # запасной путь: некоторые разделы сайта (например страницы
        # процессоров/APU, в отличие от chipset-страниц) используют другую
        # структуру DOM без <article class="driver-download-details"> —
        # ищем по тексту страницы вместо конкретных тегов/классов
        return self._extract_via_text_fallback(soup)

    def _extract_via_text_fallback(self, soup) -> dict | None:
        text = soup.get_text("\n", strip=True)
        lines = [l for l in text.split("\n") if l]

        try:
            name_idx = lines.index(self.driver_name)
        except ValueError:
            return None

        window = lines[name_idx : name_idx + 20]  # несколько строк после названия драйвера
        window_text = " ".join(window)

        revision = None
        if "Revision Number" in window:
            idx = window.index("Revision Number")
            if idx + 1 < len(window):
                revision = window[idx + 1]

        if revision is None:
            return None

        version = revision
        if self.version_regex:
            m = self.version_regex.search(revision)
            if m:
                version = m.group(1)

        date_match = re.search(r"\d{4}-\d{2}-\d{2}", window_text)
        url_match = re.search(r"https://drivers\.amd\.com/\S+\.exe", window_text)

        return {
            "version": version,
            "raw_revision": revision,
            "date": date_match.group(0) if date_match else None,
            "url": url_match.group(0) if url_match else None,
        }

    @staticmethod
    def _extract_field(article, label: str) -> str | None:
        for col in article.select(".col-6.col-lg"):
            strong = col.find("strong")
            if strong and strong.get_text(strip=True) == label:
                p = col.find("p")
                if p:
                    return re.sub(r"\s+", " ", p.get_text(strip=True))
        return None

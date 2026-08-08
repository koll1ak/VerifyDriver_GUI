"""
Провайдер AMD Radeon GPU (AMD Software: Adrenalin Edition).

Переиспользует AmdChipsetProvider — структура страниц amd.com одна и та же
для чипсетов и видеокарт, отличается только URL и формат версии
("Adrenalin 26.5.2 (WHQL Recommended)" вместо чистого номера).

ВАЖНО: маркетинговая версия ("26.7.1") — не то же самое, что версия,
которую видит Windows ("32.0.21043.1005"), это разные системы счёта, как
и у NVIDIA. Но, в отличие от NVIDIA, у AMD нет API с прямым
сопоставлением — зато на странице Release Notes каждого релиза
публикуется точное значение "Windows Driver Store Version" в ТОМ ЖЕ
формате, что видит Windows (подтверждено на реальных release notes AMD).
У AMD ДВА параллельных трека нумерации одновременно (для разных
поколений GPU) — выбираем нужный, сравнивая первые 2 цифры третьего
сегмента установленной версии (например "21" в "32.0.21043.1005").

ВАЖНО: page_url нужно указать вручную под конкретную модель видеокарты —
взять из адресной строки страницы поддержки этой модели на amd.com
(Support -> Drivers & Support -> найти свою модель).
Пример для Radeon RX 580:
"https://www.amd.com/en/support/downloads/drivers.html/graphics/radeon-600-500-400/radeon-rx-500-series/radeon-rx-580.html"
"""

import re

import requests
from bs4 import BeautifulSoup

from providers.amd_chipset import AmdChipsetProvider
from providers.http_utils import DEFAULT_HEADERS

DRIVER_NAME = "AMD Software: Adrenalin Edition"
VERSION_REGEX = r"Adrenalin\s+([\d.]+)"

_STORE_VERSION_RE = re.compile(r"Windows Driver Store Version\s+([\d.]+)")


def _segment3_prefix(version: str) -> str | None:
    """Первые 2 цифры третьего сегмента — определяет "трек" нумерации AMD."""
    parts = version.split(".")
    if len(parts) < 3 or len(parts[2]) < 2:
        return None
    return parts[2][:2]


class AmdGpuProvider(AmdChipsetProvider):
    name = "amd_gpu"

    def __init__(self, page_url: str, driver_name: str = DRIVER_NAME):
        super().__init__(
            page_url=page_url,
            driver_name=driver_name,
            version_regex=VERSION_REGEX,
            vendor_match_keywords=("RADEON", "AMD GRAPHICS"),
        )

    def matches(self, device: dict) -> bool:
        # у видеокарт AMD Vendor ID "1002" (унаследовано от ATI), а не
        # "1022" (родительский AmdChipsetProvider.matches() использует
        # именно его, он верен для чипсета/CPU-устройств, но не для GPU) —
        # подтверждено на реальном устройстве
        return (
            device.get("VendorID") == "1002"
            and any(kw in device.get("DeviceName", "").upper() for kw in self.vendor_match_keywords)
        )

    def get_latest(self, device: dict = None) -> dict | None:
        latest = super().get_latest(device)
        if latest is None:
            return None

        # явный флаг вместо неявного вывода по наличию/отсутствию ключа —
        # main.py читает именно его, чтобы решить, доверять ли сравнению
        latest["comparable_with_windows_version"] = False

        current_version = device.get("DriverVersion") if device else None
        if not current_version:
            return latest  # нечего сопоставлять — отдаём маркетинговую версию как есть

        try:
            store_version = self._find_matching_store_version(current_version)
        except Exception:
            return latest  # Release Notes недоступны/структура изменилась — не рискуем, отдаём как было

        if store_version:
            latest["marketing_version"] = latest.get("raw_revision")
            latest["version"] = store_version
            latest["comparable_with_windows_version"] = True

        return latest

    def _find_matching_store_version(self, current_version: str) -> str | None:
        target_prefix = _segment3_prefix(current_version)
        if target_prefix is None:
            return None

        resp = requests.get(self.page_url, headers=DEFAULT_HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        release_notes_link = soup.find("a", href=re.compile(r"release-notes.*RN-RAD-WIN", re.IGNORECASE))
        if release_notes_link is None:
            return None

        rn_url = release_notes_link["href"]
        if rn_url.startswith("/"):
            rn_url = "https://www.amd.com" + rn_url

        rn_resp = requests.get(rn_url, headers=DEFAULT_HEADERS, timeout=20)
        rn_resp.raise_for_status()
        rn_text = BeautifulSoup(rn_resp.text, "html.parser").get_text(" ", strip=True)

        candidates = _STORE_VERSION_RE.findall(rn_text)
        for candidate in candidates:
            if _segment3_prefix(candidate) == target_prefix:
                return candidate
        return None

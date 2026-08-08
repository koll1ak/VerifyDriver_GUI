"""
Провайдер для драйверов с сайта MSI (не BIOS) — использует тот же API,
что и providers/msi_bios.py, но с параметром type=driver вместо type=bios.

    GET https://www.msi.com/api/v1/product/support/panel?product=<MODEL>&type=driver

Актуально в первую очередь для аудио-драйвера: у Realtek-кодеков на платах
MSI часто стоит кастомизированный под MSI пакет (INF вида "..._msi.inf"),
который распространяется именно через сайт MSI, а не через общую страницу
Realtek — с другой (обычно более свежей/точной) версией под конкретную плату.

Название категории в JSON-ответе заранее неизвестно (в отличие от BIOS,
где ключ "AMI BIOS" был явно виден) — ищем по подстроке "AUDIO" среди
всех категорий в result.downloads, а не по жёстко зашитому названию.
"""

import requests

from providers.base import DriverProvider

API_URL = "https://www.msi.com/api/v1/product/support/panel"

from providers.http_utils import DEFAULT_USER_AGENT

HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}


class MsiDriverProvider(DriverProvider):
    """
    category_keyword: подстрока для поиска нужной категории в downloads
    (например "AUDIO" для аудио-драйвера).
    """

    def __init__(self, product_slug: str, category_keyword: str, name: str = "msi_driver"):
        self.product_slug = product_slug
        self.category_keyword = category_keyword.upper()
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        # так же, как в msi_bios.py — сначала страница поддержки (для cookies
        # от Akamai), потом сам API-запрос с Referer в рамках той же сессии
        support_url = f"https://www.msi.com/Motherboard/{self.product_slug}/support"

        from curl_cffi import requests as curl_requests
        session = curl_requests.Session(impersonate="chrome")

        page_resp = session.get(support_url, timeout=20)
        page_resp.raise_for_status()

        resp = session.get(
            API_URL,
            params={"product": self.product_slug, "type": "driver"},
            headers={**HEADERS, "Referer": support_url},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        downloads = data.get("result", {}).get("downloads", {})

        matched_category = None
        for category_name in downloads:
            if self.category_keyword in category_name.upper():
                matched_category = category_name
                break

        if matched_category is None:
            return None

        items = downloads[matched_category]
        if not items:
            return None

        latest = items[0]  # список отсортирован: новые сверху
        return {
            "version": latest.get("download_version"),
            "date": latest.get("download_release"),
            "url": latest.get("download_url"),
            "size": latest.get("download_size"),
            "category": matched_category,
            "title": latest.get("type_title"),
        }


def get_installed_inf_version(inf_name_hint: str) -> str | None:
    """
    Версия установленного стороннего драйвера из Driver Store (pnputil),
    например "rtdusbad_msi.inf" -> "6.4.0.2443". Это НЕ версия драйвера,
    привязанного к конкретному устройству (Get-CimInstance...DriverVersion
    может показывать другое — версию активного класс-драйвера Windows,
    а не установленного в системе стороннего пакета).
    """
    import subprocess

    ps_command = (
        "pnputil /enum-drivers | "
        f"Select-String -Pattern '{inf_name_hint}' -Context 0,4"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        return None

    import re
    match = re.search(r"Driver version:\s*[\d/]+\s*,?\s*([\d.]+)", result.stdout, re.IGNORECASE)
    return match.group(1) if match else None

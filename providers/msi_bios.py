"""
Провайдер BIOS для материнской платы MSI.

Использует официальный (хоть и не документированный публично) JSON API,
который использует сама страница поддержки MSI:

    GET https://www.msi.com/api/v1/product/support/panel?product=<MODEL>&type=bios

<MODEL> — это slug платы из URL страницы поддержки, например
"MAG-X870-TOMAHAWK-WIFI" для https://www.msi.com/Motherboard/MAG-X870-TOMAHAWK-WIFI/support

Ответ содержит result.downloads["AMI BIOS"] — список версий BIOS,
отсортированный от новой к старой (индекс 0 = последняя версия).

ВАЖНО: сайт прикрыт Akamai с TLS-фингерпринтингом (JA3) — обычный
`requests`/`urllib3` блокируется на уровне TLS-рукопожатия ещё ДО того,
как сервер увидит HTTP-заголовки (даже правильный User-Agent/Referer
не помогает). Поэтому здесь используется curl_cffi, который умеет
имитировать TLS-отпечаток настоящего браузера (impersonate="chrome").

Установка: pip install curl_cffi

Важное отличие от NVIDIA/AMD-провайдеров: BIOS не виден в
Win32_PnPSignedDriver — текущую версию нужно брать отдельно через:
    Get-CimInstance Win32_BIOS | Select SMBIOSBIOSVersion
"""

import subprocess

from curl_cffi import requests

from providers.base import DriverProvider

SUPPORT_PAGE_URL = "https://www.msi.com/Motherboard/{slug}/support"
API_URL = "https://www.msi.com/api/v1/product/support/panel"
BIOS_CATEGORY_KEY = "AMI BIOS"


def get_current_bios_version() -> str | None:
    """Текущая версия BIOS, установленная в системе (Windows only)."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_BIOS).SMBIOSBIOSVersion"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    version = result.stdout.strip()
    return version or None


class MsiBiosProvider(DriverProvider):
    name = "msi_bios"

    def __init__(self, product_slug: str):
        # например: "MAG-X870-TOMAHAWK-WIFI"
        self.product_slug = product_slug

    def matches(self, device: dict) -> bool:
        # не участвует в обходе PnP-устройств — вызывается отдельно из main.py,
        # т.к. BIOS не виден как обычное PnP-устройство
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        support_url = SUPPORT_PAGE_URL.format(slug=self.product_slug)

        session = requests.Session(impersonate="chrome")

        # 1. Открываем страницу поддержки — получаем cookies (в т.ч. Akamai)
        page_resp = session.get(support_url, timeout=20)
        page_resp.raise_for_status()

        # 2. Дёргаем API уже с Referer и cookies от шага 1
        resp = session.get(
            API_URL,
            params={"product": self.product_slug, "type": "bios"},
            headers={
                "Referer": support_url,
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        downloads = data.get("result", {}).get("downloads", {})
        bios_list = downloads.get(BIOS_CATEGORY_KEY, [])

        if not bios_list:
            return None

        latest = bios_list[0]  # список отсортирован: новые сверху
        return {
            "version": latest.get("download_version"),
            "date": latest.get("download_release"),
            "url": latest.get("download_url"),
            "size": latest.get("download_size"),
            "sha256": latest.get("download_sha256"),
            "description": latest.get("download_description"),
        }

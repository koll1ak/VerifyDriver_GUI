"""
Универсальный провайдер для страниц Intel Download Center
(intel.com/content/www/us/en/download/<ID>/<slug>.html).

Такие страницы рендерятся на сервере, и версия/дата лежат прямо в
мета-тегах — JS/API не нужен. Но intel.com, как и msi.com, прикрыт
Akamai с TLS-фингерпринтингом — обычный requests/urllib3 получает 403
ещё до того, как сервер посмотрит на заголовки. Поэтому используется
curl_cffi (impersonate="chrome"), как и в providers/msi_bios.py.

Известные ID:
- 19347   — Intel Chipset Device Software (Chipset INF Utility)
- 785597  — Intel Arc & Iris Xe Graphics Driver (Windows)
"""

import subprocess

from curl_cffi import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider

DOWNLOAD_URL_TEMPLATE = "https://www.intel.com/content/www/us/en/download/{download_id}/{slug}.html"


def _find_meta(soup, name: str) -> str | None:
    tag = soup.find("meta", attrs={"name": name})
    if tag is None:
        for m in soup.find_all("meta"):
            if m.get("name", "").lower() == name.lower():
                tag = m
                break
    return tag.get("content", "").strip() if tag and tag.get("content") else None


class IntelDownloadCenterProvider(DriverProvider):
    def __init__(self, download_id: str, slug: str, name: str = "intel_download"):
        self.download_id = download_id
        self.slug = slug
        self.name = name

    def matches(self, device: dict) -> bool:
        # вызывается отдельно из main.py, не через обход PnP-устройств
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        url = DOWNLOAD_URL_TEMPLATE.format(download_id=self.download_id, slug=self.slug)

        session = requests.Session(impersonate="chrome")
        resp = session.get(url, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        version = _find_meta(soup, "DownloadVersion")
        date = _find_meta(soup, "lastModifieddate")

        if version is None:
            return None

        return {"version": version, "date": date, "url": url}


def get_current_intel_chipset_version() -> str | None:
    """Версия установленного Intel Chipset Device Software (из реестра Uninstall)."""
    ps_command = (
        "Get-ItemProperty "
        "'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*', "
        "'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*' "
        "-ErrorAction SilentlyContinue | "
        "Where-Object { $_.DisplayName -like '*Intel*Chipset*' } | "
        "Select-Object -First 1 -ExpandProperty DisplayVersion"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    version = result.stdout.strip()
    return version or None

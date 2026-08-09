"""
General-purpose provider for Intel Download Center pages
(intel.com/content/www/us/en/download/<ID>/<slug>.html).

These pages are server-rendered, and the version/date are right there
in meta tags — no JS/API needed. But intel.com, like msi.com, is behind
Akamai with TLS fingerprinting — plain requests/urllib3 gets a 403
before the server even looks at the headers. So curl_cffi is used
(impersonate="chrome"), same as in providers/msi_bios.py.

Known IDs:
- 19347   — Intel Chipset Device Software (Chipset INF Utility)
- 785597  — Intel Arc & Iris Xe Graphics Driver (Windows)
"""

import subprocess

from curl_cffi import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider

DOWNLOAD_URL_TEMPLATE = "https://www.intel.com/content/www/us/en/download/{download_id}/{slug}.html"


def intel_download_url(download_id: str, slug: str) -> str:
    return DOWNLOAD_URL_TEMPLATE.format(download_id=download_id, slug=slug)


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
        # called separately from main.py, not via the PnP device scan
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
    """The version of the installed Intel Chipset Device Software (from the Uninstall registry key)."""
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

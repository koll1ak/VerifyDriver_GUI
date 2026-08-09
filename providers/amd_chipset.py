"""
AMD Chipset Software provider.

The chipset support page (support.amd.com) returns the driver list
directly in server-rendered HTML — no hidden API/JS needed. Each driver
is an <article class="driver-download-details"> with an <h4> title and a
pair of col-6 col-lg blocks (Revision Number / File Size / Release Date)
plus a Download button.

The page is split into accordions by OS (Windows 11 / Windows 10) — the
data inside is usually identical, we take the first match.
"""

import re

import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider
from ps_utils import run_powershell

CHIPSET_PAGE_URL = "https://www.amd.com/en/support/downloads/drivers.html/chipsets/am5/x870.html"
DRIVER_NAME = "AMD Chipset Drivers"

# PowerShell: look for the installed "AMD Chipset Software" package
# version in the registry's Uninstall entries (the same place "Add or
# remove programs" reads it from)
_GET_INSTALLED_VERSION_PS = (
    "Get-ItemProperty "
    "'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*', "
    "'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*' "
    "-ErrorAction SilentlyContinue | "
    "Where-Object { $_.DisplayName -like '*AMD Chipset*' } | "
    "Select-Object -First 1 -ExpandProperty DisplayVersion"
)


def get_current_amd_chipset_version() -> str | None:
    """The version of the installed AMD Chipset Software package (from the Uninstall registry key)."""
    result = run_powershell(_GET_INSTALLED_VERSION_PS)
    version = result.stdout.strip()
    return version or None

from providers.http_utils import DEFAULT_HEADERS, DEFAULT_TIMEOUT

# without a UA the page sometimes returns a stripped-down response via Akamai
HEADERS = DEFAULT_HEADERS


class AmdChipsetProvider(DriverProvider):
    """
    A general-purpose provider for amd.com/en/support/downloads/drivers.html/...
    pages. Works for both chipset pages and graphics card (Radeon) pages
    — the HTML structure is the same across the site, only page_url,
    driver_name, and the format of the version number itself differ.

    version_regex: if the version isn't given in a plain form (e.g.
    "Adrenalin 26.5.2 (WHQL Recommended)" for graphics cards instead of
    "8.07.16.1035" for chipsets), a regex is passed to extract the
    number from the text.
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
                # AMD's CDN rejects direct/hotlinked navigation to the raw
                # .exe URL with no referrer (confirmed live: it redirects
                # to a "Download Not Complete" page) — link to the support
                # page instead, where AMD's own Download button sets the
                # right referrer. report()/build_result() already prefer
                # page_url over url for exactly this kind of case.
                "page_url": self.page_url,
            }

        # fallback path: some sections of the site (e.g. processor/APU
        # pages, unlike chipset pages) use a different DOM structure
        # without <article class="driver-download-details"> — search by
        # the page text instead of specific tags/classes
        return self._extract_via_text_fallback(soup)

    def _extract_via_text_fallback(self, soup) -> dict | None:
        text = soup.get_text("\n", strip=True)
        lines = [l for l in text.split("\n") if l]

        try:
            name_idx = lines.index(self.driver_name)
        except ValueError:
            return None

        window = lines[name_idx : name_idx + 20]  # a few lines after the driver name
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
            "page_url": self.page_url,
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

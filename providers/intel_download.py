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

import re

from curl_cffi import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider
from ps_utils import run_powershell

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


_PURPOSE_LI_RE = re.compile(r"^Driver version\s+([\d.]+)\s*:\s*For\s+(.+)$", re.IGNORECASE)


def _parse_purpose_chip_versions(soup: BeautifulSoup) -> list[dict]:
    """
    Extracts the "Purpose" section's chip -> driver version mapping from
    an Intel download page's Detailed Description block (confirmed live
    on the Bluetooth driver page, download ID 18649), e.g.:
        "Driver version 24.60.0.4 : For BE213, BE211, ... AX211"
        "Driver version 24.40.11.1 : For AX411, AX211, ... 9260"
    -> [{"version": "24.60.0.4", "chips": {"BE213", "BE211", ..., "AX211"}}, ...]

    A single chip can legitimately appear in more than one entry (the
    same silicon paired with different platforms, e.g. AX211 on Panther
    Lake vs. Wildcat Lake) -- callers decide how to handle that.

    Starts searching from the "Detailed Description" <h2> heading (via
    find_next("div")) as a best-effort scope narrowing -- this is NOT a
    strict guarantee that only that section's <div> is scanned, just
    "the next div in document order after the heading", which happens
    to be the right container on the real page today. The actual
    protection against picking up unrelated "Driver version ... : For
    ..." strings elsewhere on the page is the _PURPOSE_LI_RE regex match
    on each <li>'s text below. Returns [] if the page doesn't have this
    section at all -- callers already treat an empty list as "no
    chip-specific data available" and fall back to the package-level
    version.
    """
    heading = soup.find(lambda tag: tag.name == "h2" and tag.get_text(strip=True) == "Detailed Description")
    if heading is None:
        return []
    container = heading.find_next("div")
    if container is None:
        return []

    entries = []
    for li in container.find_all("li"):
        text = li.get_text(" ", strip=True)
        m = _PURPOSE_LI_RE.match(text)
        if not m:
            continue
        version, chip_list = m.groups()
        chips = {c.strip().upper() for c in chip_list.split(",") if c.strip()}
        if chips:
            entries.append({"version": version, "chips": chips})
    return entries


def find_chip_versions_for_device(chip_versions: list[dict], *device_names) -> list[str] | None:
    """
    Given _parse_purpose_chip_versions's output and one or more device
    name strings to check (in priority order -- e.g. the Bluetooth
    device's own name, then a fallback like the WiFi adapter's name on
    the same combo card, since Bluetooth's own Windows name is
    typically generic -- confirmed live: "Intel(R) Wireless
    Bluetooth(R)", no chip code), returns every driver version Intel
    lists for whichever known chip code is found first, or None if none
    of the given names contain a chip code from chip_versions at all.
    """
    all_chips = {chip for entry in chip_versions for chip in entry["chips"]}
    for name in device_names:
        if not name:
            continue
        name_upper = name.upper()
        matched_chips = {chip for chip in all_chips if re.search(rf"\b{re.escape(chip)}\b", name_upper)}
        if matched_chips:
            return [entry["version"] for entry in chip_versions if entry["chips"] & matched_chips]
    return None


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


class IntelBluetoothProvider(DriverProvider):
    """
    Like IntelDownloadCenterProvider, but also extracts the per-chip
    driver version list from the page's "Purpose" section (see
    _parse_purpose_chip_versions), so check_intel_bluetooth can match
    against the exact installed chip instead of just the overall
    package version -- those differ (e.g. package 24.60.0 ships both
    driver 24.60.0.4 and 24.40.11.1, for different chips).
    """
    name = "intel_bluetooth"

    def __init__(self, download_id: str, slug: str):
        self.download_id = download_id
        self.slug = slug

    def matches(self, device: dict) -> bool:
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

        return {
            "version": version, "date": date, "url": url,
            "chip_versions": _parse_purpose_chip_versions(soup),
        }


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
    result = run_powershell(ps_command)
    version = result.stdout.strip()
    return version or None

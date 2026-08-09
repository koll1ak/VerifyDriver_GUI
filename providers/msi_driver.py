"""
Provider for (non-BIOS) drivers from the MSI site — uses the same API as
providers/msi_bios.py, but with the type=driver parameter instead of
type=bios.

    GET https://www.msi.com/api/v1/product/support/panel?product=<MODEL>&type=driver

Mainly relevant for the audio driver: Realtek codecs on MSI boards
often ship a package customized for MSI (an INF like "..._msi.inf"),
distributed via MSI's own site rather than Realtek's generic page — with
a different (usually newer/more accurate) version for that specific board.

The category name in the JSON response isn't known ahead of time
(unlike BIOS, where the "AMI BIOS" key was visible up front) — we search
for a substring like "AUDIO" among all the categories in
result.downloads, rather than a hardcoded name.
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
    category_keyword: a substring used to find the right category in
    downloads (e.g. "AUDIO" for the audio driver).
    """

    def __init__(self, product_slug: str, category_keyword: str, name: str = "msi_driver"):
        self.product_slug = product_slug
        self.category_keyword = category_keyword.upper()
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        # same as in msi_bios.py — first the support page (for Akamai
        # cookies), then the actual API request with a Referer, within
        # the same session
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

        latest = items[0]  # the list is sorted: newest first
        return {
            "version": latest.get("download_version"),
            "date": latest.get("download_release"),
            "url": latest.get("download_url"),
            "size": latest.get("download_size"),
            "category": matched_category,
            "title": latest.get("type_title"),
        }


def _get_installed_inf_line(inf_name_hint: str) -> str | None:
    from ps_utils import run_powershell

    ps_command = (
        "pnputil /enum-drivers | "
        f"Select-String -Pattern '{inf_name_hint}' -Context 0,4"
    )
    result = run_powershell(ps_command)
    if result.returncode != 0:
        return None
    return result.stdout


def get_installed_inf_version(inf_name_hint: str) -> str | None:
    """
    The version of the installed third-party driver from the Driver
    Store (pnputil), e.g. "rtdusbad_msi.inf" -> "6.4.0.2443". This is
    NOT the driver version tied to a specific device
    (Get-CimInstance...DriverVersion may show something different — the
    version of Windows's active class driver, not the third-party
    package installed on the system).
    """
    import re

    stdout = _get_installed_inf_line(inf_name_hint)
    if stdout is None:
        return None
    match = re.search(r"Driver version:\s*[\d/]+\s*,?\s*([\d.]+)", stdout, re.IGNORECASE)
    return match.group(1) if match else None


def get_installed_inf_date(inf_name_hint: str) -> str | None:
    """
    The date of the installed third-party driver from the Driver Store
    (pnputil) — the same "Driver Version:" line as get_installed_inf_version,
    which pnputil actually formats as "MM/DD/YYYY version" (confirmed
    live, e.g. "04/16/2026 6.4.0.2443"), so both live in the same match.
    """
    import re

    stdout = _get_installed_inf_line(inf_name_hint)
    if stdout is None:
        return None
    match = re.search(r"Driver version:\s*([\d/]+)\s*,?\s*[\d.]+", stdout, re.IGNORECASE)
    return match.group(1) if match else None

"""
BIOS provider for MSI motherboards.

Uses the official (though not publicly documented) JSON API that the
MSI support page itself uses:

    GET https://www.msi.com/api/v1/product/support/panel?product=<MODEL>&type=bios

<MODEL> is the board slug from the support page URL, e.g.
"MAG-X870-TOMAHAWK-WIFI" for https://www.msi.com/Motherboard/MAG-X870-TOMAHAWK-WIFI/support

The response contains result.downloads["AMI BIOS"] — a list of BIOS
versions sorted newest to oldest (index 0 = latest version).

IMPORTANT: the site is behind Akamai with TLS fingerprinting (JA3) —
plain `requests`/`urllib3` gets blocked at the TLS handshake level
BEFORE the server even sees the HTTP headers (even the right
User-Agent/Referer doesn't help). That's why curl_cffi is used here —
it can mimic a real browser's TLS fingerprint (impersonate="chrome").

Install: pip install curl_cffi

An important difference from the NVIDIA/AMD providers: BIOS isn't
visible in Win32_PnPSignedDriver — the current version has to be
obtained separately via:
    Get-CimInstance Win32_BIOS | Select SMBIOSBIOSVersion
"""

from curl_cffi import requests

from providers.base import DriverProvider
from ps_utils import run_powershell

SUPPORT_PAGE_URL = "https://www.msi.com/Motherboard/{slug}/support"
API_URL = "https://www.msi.com/api/v1/product/support/panel"
BIOS_CATEGORY_KEY = "AMI BIOS"


def get_current_bios_version() -> str | None:
    """The BIOS version currently installed on the system (Windows only)."""
    result = run_powershell("(Get-CimInstance Win32_BIOS).SMBIOSBIOSVersion")
    version = result.stdout.strip()
    return version or None


class MsiBiosProvider(DriverProvider):
    name = "msi_bios"

    def __init__(self, product_slug: str):
        # e.g.: "MAG-X870-TOMAHAWK-WIFI"
        self.product_slug = product_slug

    def matches(self, device: dict) -> bool:
        # doesn't participate in the PnP device scan — called separately
        # from main.py, since BIOS isn't visible as a regular PnP device
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        support_url = SUPPORT_PAGE_URL.format(slug=self.product_slug)

        session = requests.Session(impersonate="chrome")

        # 1. Open the support page — get cookies (including Akamai's)
        page_resp = session.get(support_url, timeout=20)
        page_resp.raise_for_status()

        # 2. Hit the API using the Referer and cookies from step 1
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

        latest = bios_list[0]  # the list is sorted: newest first
        return {
            "version": latest.get("download_version"),
            "date": latest.get("download_release"),
            "url": latest.get("download_url"),
            "size": latest.get("download_size"),
            "sha256": latest.get("download_sha256"),
            "description": latest.get("download_description"),
        }

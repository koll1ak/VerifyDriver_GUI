"""
Providers for MSI LAPTOPS (Katana/Raider/Stealth/etc.) — BIOS and
(non-BIOS) drivers.

Confirmed live: the exact same API as desktop boards
(providers/msi_bios.py, providers/msi_driver.py) —

    GET https://www.msi.com/api/v1/product/support/panel?product=<slug>&type=<bios|driver>

— with real, confirmed differences from the desktop case that make
reusing those classes unchanged unsafe:

1. CONFIRMED a real laptop model page
   (https://www.msi.com/Laptop/Katana-15-B13VX/support) is a PARENT
   page with a "Select Model" dropdown for its specific SKUs
   (Katana-15-B13VFK, Katana-15-B13VEK, Katana-15-B13VGK, ...) — the
   specific SKU slug has NO page of its own
   (https://www.msi.com/Laptop/Katana-15-B13VFK/support is a genuine
   404), yet the API's "product" param needs exactly that specific SKU
   slug, not the parent's. Since Win32_ComputerSystem.Model on a real
   laptop would report the specific SKU (matching desktop board
   behavior), there's no reliable way to derive the parent page slug
   from it alone without another lookup (e.g. a site search) — so
   rather than depend on that, this CONFIRMED LIVE that the initial
   page visit (for Akamai cookies) doesn't need to be the matching
   product page at all: visiting MSI's generic
   https://www.msi.com/support/download landing page first, then
   calling the API directly with the specific SKU slug as "product",
   works identically (same BIOS/driver data returned) — this sidesteps
   the parent/child slug problem entirely instead of trying to solve it.

2. CONFIRMED the BIOS category key is literally "BIOS" for laptops,
   not "AMI BIOS" (the desktop key, hardcoded in msi_bios.py).

3. CONFIRMED the BIOS category can contain more than one entry, and
   the first isn't reliably the actual firmware — a real laptop
   (Katana 15 B13VFK) lists an "Intel ME FW Update Tool" BEFORE the
   entry titled plainly "BIOS". Filtered to the entry whose
   download_title is exactly "BIOS", falling back to the first entry
   if no such title exists (defensive, in case another laptop's
   wording differs).

Still NOT verified: whether Win32_ComputerSystem.Model on a real MSI
laptop, after the same hyphenation used for desktop boards
(laptop_detect.py's extract_msi_laptop_slug), produces exactly the
specific-SKU-level slug the API expects — no MSI laptop was available
to confirm this end of the chain.
"""

from curl_cffi import requests

from providers.base import DriverProvider

GENERIC_SUPPORT_PAGE_URL = "https://www.msi.com/support/download"
API_URL = "https://www.msi.com/api/v1/product/support/panel"
LAPTOP_BIOS_CATEGORY_KEY = "BIOS"


def _fetch_downloads(product_slug: str, download_type: str) -> dict:
    session = requests.Session(impersonate="chrome")

    page_resp = session.get(GENERIC_SUPPORT_PAGE_URL, timeout=20)
    page_resp.raise_for_status()

    resp = session.get(
        API_URL,
        params={"product": product_slug, "type": download_type},
        headers={
            "Referer": GENERIC_SUPPORT_PAGE_URL,
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("result", {}).get("downloads", {})


class MsiLaptopBiosProvider(DriverProvider):
    name = "msi_laptop_bios"

    def __init__(self, model_slug: str):
        self.model_slug = model_slug

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        downloads = _fetch_downloads(self.model_slug, "bios")
        bios_list = downloads.get(LAPTOP_BIOS_CATEGORY_KEY, [])
        if not bios_list:
            return None

        real_bios = next((b for b in bios_list if b.get("download_title") == "BIOS"), bios_list[0])

        return {
            "version": real_bios.get("download_version"),
            "date": real_bios.get("download_release"),
            "url": real_bios.get("download_url"),
            "size": real_bios.get("download_size"),
            "sha256": real_bios.get("download_sha256"),
            "description": real_bios.get("download_description"),
        }


class MsiLaptopDriverProvider(DriverProvider):
    """
    category_keyword: a substring used to find the right category in
    downloads (e.g. "AUDIO" — confirmed live real laptop category keys
    include "Audio", "LAN", "Wireless LAN", "Bluetooth", "Chipset",
    "Graphics", "TouchPad", "Intel Rapid Storage Technology",
    "Intel Management Engine", "Dynamic Tuning").
    """

    def __init__(self, model_slug: str, category_keyword: str, name: str = "msi_laptop_driver"):
        self.model_slug = model_slug
        self.category_keyword = category_keyword.upper()
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        downloads = _fetch_downloads(self.model_slug, "driver")

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

        latest = items[0]  # the list is sorted: newest first (confirmed for driver categories; BIOS needed a title filter, drivers didn't show the same contamination in the one laptop checked)
        return {
            "version": latest.get("download_version"),
            "date": latest.get("download_release"),
            "url": latest.get("download_url"),
            "size": latest.get("download_size"),
            "category": matched_category,
            "title": latest.get("download_title"),
        }

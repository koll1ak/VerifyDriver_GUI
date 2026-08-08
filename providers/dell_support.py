"""
Provider for BIOS/Audio drivers from the Dell site by Service Tag.

    https://www.dell.com/support/home/en-us/product-support/servicetag/<TAG>/drivers

NOT VERIFIED ON A REAL DEVICE (unlike MSI/AMD/Gigabyte/ASRock/ASUS,
whose structure was worked out from real screenshots off an actual
machine) — the author doesn't have a single Dell laptop on hand. Written
based on the documented pattern (Service Tag → drivers page, categories
including "BIOS" and "Audio", version+date+size visible in the UI) and
by analogy with already-verified providers.

Risks worth checking on the first real run:
1. The page might turn out to be a heavy JS app (Dell.com generally
   uses complex Angular/React components) — in which case the needed
   content just won't be in a plain requests.get() response, and a real
   API endpoint would need to be found via DevTools, the way it was done
   for MSI/AMD chipset.
2. There might be bot protection (Akamai or similar) — in which case
   curl_cffi with impersonate="chrome" would be needed, as in
   providers/msi_bios.py.
3. The categories on the site are called "BIOS" and "Audio" per Dell's
   documentation, but the exact category text on the page may differ in
   case/wording — the comparison is case-insensitive to survive that,
   but a match isn't guaranteed.

Parsing is done via text patterns (year-month-day for the date, "MB"/"KB"
for size, version as the first dotted number sequence near the category
label) rather than specific CSS classes/column indices — same as in
providers/asrock_driver.py and providers/asus_driver.py, for the same
reason (less risk of breaking on unknown markup).
"""

import re

import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

DRIVERS_PAGE_URL = "https://www.dell.com/support/home/en-us/product-support/servicetag/{service_tag}/drivers"
HEADERS = DEFAULT_HEADERS

_VERSION_RE = re.compile(r"\b\d+(?:\.\d+){1,4}\b")
_DATE_RE = re.compile(r"\d{1,2}\s+\w+\s+\d{4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{4}")
_SIZE_RE = re.compile(r"\d+(\.\d+)?\s*(MB|KB|GB)", re.IGNORECASE)


class DellSupportProvider(DriverProvider):
    """
    category: "BIOS" or "Audio" (looked up as a standalone word in the
    page text, case-insensitive).
    """

    def __init__(self, service_tag: str, category: str, name: str = "dell_support"):
        self.service_tag = service_tag
        self.category = category
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        url = DRIVERS_PAGE_URL.format(service_tag=self.service_tag)
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()

        text = resp.text

        # find where the desired category is mentioned on the page, then
        # look for version/date/size in a window of text right after it
        # — the same way it appears to the person on the page (category,
        # then the specific package's details)
        category_match = re.search(re.escape(self.category), text, re.IGNORECASE)
        if category_match is None:
            return None

        window = text[category_match.end():category_match.end() + 2000]

        # strip HTML tags from the window so the regexes search visible
        # text, not markup
        window_text = re.sub(r"<[^>]+>", " ", window)
        window_text = re.sub(r"\s+", " ", window_text)

        version_match = _VERSION_RE.search(window_text)
        date_match = _DATE_RE.search(window_text)
        size_match = _SIZE_RE.search(window_text)

        if version_match is None:
            return None

        return {
            "version": version_match.group(0),
            "date": date_match.group(0) if date_match else None,
            "size": size_match.group(0) if size_match else None,
            "url": url,  # the heuristic doesn't give a direct file link — point to the page
            "page_url": url,
        }

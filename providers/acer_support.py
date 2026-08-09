"""
Provider for BIOS/Audio drivers from the Acer site.

    POST https://www.acer.com/us-en/DynamicContent/GetDriversAndManuals
    Body (JSON): {"ModelName": "<MODEL>", "Local": "en-us"}

Structure worked out from real data (Acer Nitro AN515-55). The response
is JSON where the content we need is DOUBLE-encoded: hits[0]._source.
global_download_details is a STRING that needs to be parsed as JSON
again — inside it there are already driver/bios/userguide/application
categories with file lists.

BIOS: the "bios" section -> "files", filtered by category == "BIOS" (not
"Firmware" — that's the graphics card's VBIOS, a separate thing, not the
system BIOS), versions aren't split by OS.

Audio: the "driver" section -> "files", filtered by category == "Audio"
AND by the "oss" field (values like "11M1"/"10M1" — Windows 11/10) — it's
important not to mix this up: without this filter you can end up with a
version meant for a different OS.

<MODEL> — Win32_ComputerSystem.Model without the product-line prefix
(e.g. "Nitro AN515-55" -> "AN515-55").
"""

import json
import re
import sys

from curl_cffi import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

API_URL = "https://www.acer.com/us-en/DynamicContent/GetDriversAndManuals"
HEADERS = {**DEFAULT_HEADERS, "Content-Type": "application/json", "Accept": "application/json"}

_DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")


def _date_sort_key(date_str: str):
    m = _DATE_RE.match(date_str or "")
    if not m:
        return (0, 0, 0)
    return tuple(int(g) for g in m.groups())


def detect_acer_os_code() -> str:
    """
    "11M1"/"10M1" — the OS codes Acer uses in the "oss" field.
    Determined the same way as in providers/nvidia.py (via the system's build number).
    """
    try:
        build = sys.getwindowsversion().build
    except AttributeError:
        return "10M1"  # not Windows — default
    return "11M1" if build >= 22000 else "10M1"


class AcerSupportProvider(DriverProvider):
    """
    category: "BIOS" or "Audio".
    os_code: only needed for category="Audio" (BIOS has no OS split);
             if not passed, auto-detected from the current system.
    """

    def __init__(
        self,
        model_name: str,
        category: str,
        os_code: str | None = None,
        part_number: str | None = None,
        serial: str | None = None,
        name: str = "acer_support",
    ):
        self.model_name = model_name
        self.category = category
        self.os_code = os_code or detect_acer_os_code()
        self.part_number = part_number
        self.serial = serial
        self.name = name

    def build_page_url(self) -> str:
        # the full URL also needs a part number and serial number
        # (otherwise the page doesn't exist) — if they weren't passed,
        # we return a shortened version as the closest approximation
        if self.part_number and self.serial:
            return (
                f"https://www.acer.com/us-en/support/product-support/"
                f"{self.model_name}/{self.part_number}/downloads?sn={self.serial}"
            )
        return f"https://www.acer.com/us-en/support/product-support/{self.model_name}"

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        # same as with MSI: first visit the product page itself (to get
        # the session cookies), then make the API request within that
        # session. curl_cffi with impersonate="chrome" — the site is
        # similar to MSI/Intel: it holds the connection until it times
        # out instead of an explicit rejection for "non-browser" clients
        # (looks like Akamai-style protection).
        session = requests.Session(impersonate="chrome")
        session.headers.update(HEADERS)

        product_page_url = self.build_page_url()
        try:
            session.get(product_page_url, timeout=20)
        except Exception:
            pass  # not critical, even if the page fails to load — try the API anyway

        resp = session.post(
            API_URL,
            json={"ModelName": self.model_name, "Local": "en-us"},
            headers={**HEADERS, "Referer": product_page_url},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        hits = data.get("hits", [])
        if not hits:
            return None

        raw_details = hits[0].get("_source", {}).get("global_download_details")
        if not raw_details:
            return None

        try:
            details = json.loads(raw_details)
        except json.JSONDecodeError:
            return None

        if self.category.upper() == "BIOS":
            files = details.get("bios", {}).get("files") or []
            candidates = [f for f in files if f.get("category", "").upper() == "BIOS"]
        else:
            files = details.get("driver", {}).get("files") or []
            candidates = [
                f for f in files
                if f.get("category", "").upper() == self.category.upper() and f.get("oss") == self.os_code
            ]
            if not candidates:
                # Acer's catalog for this model might not have a
                # separate package for your specific Windows version
                # (e.g. only "11M1", even though you have Win10) — in
                # that case take the newest entry for ANY OS as
                # informational data, without being sure it's actually
                # right for your system
                candidates = [
                    f for f in files if f.get("category", "").upper() == self.category.upper()
                ]
                if candidates:
                    latest = max(candidates, key=lambda f: _date_sort_key(f.get("date", "")))
                    file_link = latest.get("link")
                    download_url = f"https://www.acer.com/{file_link}" if file_link else None
                    return {
                        "version": latest.get("version"),
                        "date": latest.get("date"),
                        "size": latest.get("size"),
                        "description": latest.get("description"),
                        "url": download_url,
                        "page_url": self.build_page_url(),
                        "os_mismatch": True,  # no separate entry for this OS — the comparison isn't trustworthy
                    }

        if not candidates:
            return None

        latest = max(candidates, key=lambda f: _date_sort_key(f.get("date", "")))

        # "link" in the response is a relative path to the file (no
        # domain), we build it into a full working URL; "page_url" is
        # the product page as a whole, useful as a fallback for a manual check
        file_link = latest.get("link")
        download_url = f"https://www.acer.com/{file_link}" if file_link else None
        page_url = self.build_page_url()

        return {
            "version": latest.get("version"),
            "date": latest.get("date"),
            "url": download_url,
            "page_url": page_url,
            "size": latest.get("size"),
            "description": latest.get("description"),
        }

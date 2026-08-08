"""
BIOS provider for ASUS boards.

The support page is a React app with CSS Modules, but server-rendered
(all the content is in the source HTML, including entries hidden under
"Show More" — they're just visually collapsed via CSS, not lazy-loaded).

    https://www.asus.com/us/supportonly/<MODEL>/helpdesk_bios/

<MODEL> — the exact board name with spaces (e.g.
"rog strix x870-i gaming wifi"), case doesn't matter in the URL.

IMPORTANT: classes like "ProductSupportDriverBIOS__title__3yZVA" contain
a CSS-module hash that may change on the next ASUS site deploy. So here
we search by a regex matching the stable part of the class name (up to
the second "__"), not the class in full — that makes the parser less
likely to break on a cosmetic redesign.
"""

import re
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider

SUPPORT_PAGE_URL = "https://www.asus.com/us/supportonly/{model}/helpdesk_bios/"

from providers.http_utils import DEFAULT_HEADERS

HEADERS = DEFAULT_HEADERS


def _class_matches(tag, stable_prefix: str) -> bool:
    classes = tag.get("class") or []
    return any(re.match(re.escape(stable_prefix) + r"__", c) for c in classes)


class AsusBiosProvider(DriverProvider):
    name = "asus_bios"

    def __init__(self, model: str):
        self.model = model

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        # the URL is case-insensitive, but spaces need to be encoded explicitly
        url = SUPPORT_PAGE_URL.format(model=quote(self.model.lower()))
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # find the "BIOS" section heading (not "Driver", not "Utility")
        title_div = None
        for div in soup.find_all("div"):
            if _class_matches(div, "ProductSupportDriverBIOS__title") and div.get_text(strip=True) == "BIOS":
                title_div = div
                break

        if title_div is None:
            return self._extract_via_filename_pattern(resp.text)

        section = title_div.find_parent(
            lambda tag: tag.name == "section" and _class_matches(tag, "ProductSupportDriverBIOS__productSupportDriverBIOSSection")
        )
        if section is None:
            return self._extract_via_filename_pattern(resp.text)

        first_box = section.find(
            lambda tag: tag.name == "div" and any(
                c.startswith("ProductSupportDriverBIOS__productSupportDriverBIOSBox")
                for c in (tag.get("class") or [])
            )
        )
        if first_box is None:
            return self._extract_via_filename_pattern(resp.text)

        version_text = None
        date_text = None
        size_text = None

        for div in first_box.find_all("div"):
            classes = div.get("class") or []
            if any(c.startswith("ProductSupportDriverBIOS__releaseDate") for c in classes):
                date_text = div.get_text(strip=True)
            elif any(c.startswith("ProductSupportDriverBIOS__fileSize") for c in classes):
                size_text = div.get_text(strip=True)
            elif (
                version_text is None
                and div.find("div") is None  # only a "leaf" div, no nested ones
                and re.match(r"^Version\s+\S+", div.get_text(strip=True))
            ):
                version_text = div.get_text(strip=True)

        if version_text is None:
            # Fallback path: on some pages (not every model has the same
            # internal structure) the expected DOM block might be
            # missing — but the version is usually baked right into the
            # installer's file name ("ASUS_FX506LH_310_BIOS_Update_3.exe"
            # -> "310"), which is present in the raw HTML regardless of
            # how the page was rendered.
            return self._extract_via_filename_pattern(resp.text)

        version = re.sub(r"^Version\s+", "", version_text)

        download_link = first_box.find("a", href=True)

        return {
            "version": version,
            "date": date_text,
            "size": size_text,
            "url": download_link["href"] if download_link else None,
        }

    @staticmethod
    def _extract_via_filename_pattern(raw_text: str) -> dict | None:
        match = re.search(r"([A-Z0-9]+)_(\d+)_BIOS_Update", raw_text, re.IGNORECASE)
        if match is None:
            return None

        version = match.group(2)

        # look for a nearby download link (the Global path to
        # .exe/.zip) — slashes in the raw HTML can appear either as
        # regular "/" or as an unescaped JS escape "\u002F" — handle
        # both cases
        url_match = re.search(
            r'"?Global"?\s*:\s*"((?:/|\\u002[Ff])pub(?:/|\\u002[Ff])[^"]+\.(?:exe|zip))"',
            raw_text,
            re.IGNORECASE,
        )
        url = None
        if url_match:
            path = url_match.group(1).replace("\\u002F", "/").replace("\\u002f", "/").replace("\\/", "/")
            url = "https://dlcdnets.asus.com" + path

        return {"version": version, "date": None, "size": None, "url": url}

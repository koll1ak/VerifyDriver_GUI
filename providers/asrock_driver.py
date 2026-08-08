"""
Provider for (non-BIOS) drivers from the ASRock site — the same site
layout as BIOS (providers/asrock_bios.py):

    https://www.asrock.com/mb/<family>/<MODEL NAME>/driver.html

IMPORTANT: the exact table structure on the driver.html page was NOT
verified directly (unlike bios.html, which was inspected against real
HTML) — the columns might be in a different order or there might be
more of them (e.g. an added OS column, as turned out to be the case for
Gigabyte). So version/date/size are found here by matching the content
pattern of a cell rather than by a fixed index — more resilient to an
unknown column layout, but the output is worth checking against the
real page on first run.
"""

import re

import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

DRIVER_PAGE_URL = "https://www.asrock.com/mb/{family}/{model}/driver.html"
HEADERS = DEFAULT_HEADERS

_DATE_RE = re.compile(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{4}")
_SIZE_RE = re.compile(r"\d+(\.\d+)?\s*(MB|KB|GB)", re.IGNORECASE)
_VERSION_RE = re.compile(r"^[\dvV][\d.]*$")


class AsrockDriverProvider(DriverProvider):
    """match_substrings: substrings required in the row's text (e.g. ("Realtek", "Audio"))."""

    def __init__(self, model: str, match_substrings: tuple[str, ...], family: str = "amd", name: str = "asrock_driver"):
        self.model = model
        self.family = family
        self.match_substrings = match_substrings
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        url = DRIVER_PAGE_URL.format(family=self.family, model=self.model)
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        for table in soup.find_all("table"):
            body = table.find("tbody") or table
            rows = [r for r in body.find_all("tr") if r.find("td")]

            for row in rows:
                row_text = row.get_text(" ", strip=True)
                if not all(s.upper() in row_text.upper() for s in self.match_substrings):
                    continue

                cells = [c.get_text(strip=True) for c in row.find_all("td")]

                date = next((c for c in cells if _DATE_RE.search(c)), None)
                size = next((c for c in cells if _SIZE_RE.search(c)), None)
                version = next(
                    (c for c in cells if _VERSION_RE.match(c) and c != date and c != size),
                    None,
                )

                download_link = None
                for a in row.find_all("a", href=True):
                    if "download.asrock.com" in a["href"]:
                        download_link = a["href"]
                        break

                return {
                    "version": version,
                    "date": date,
                    "size": size,
                    "url": download_link,
                    "raw_row_text": row_text,  # in case auto-parsing didn't work — shows what's actually in the row
                }

        return None

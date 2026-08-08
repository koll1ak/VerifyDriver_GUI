"""
Provider for drivers distributed ONLY via Windows Update, with no
separate downloads page from the chip maker (typical for
Qualcomm/some MediaTek WiFi modules — unlike Intel, which has a
separate official page, see providers/intel_download.py).

    GET https://www.catalog.update.microsoft.com/Search.aspx?q=<query>

The page is server-rendered (a plain HTML table), no JS needed.
"""

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

SEARCH_URL = "https://www.catalog.update.microsoft.com/Search.aspx"


class MsCatalogProvider(DriverProvider):
    """
    query: the search query — usually the exact device name from Windows
           (e.g. "Qualcomm QCA6174" or "MediaTek Wi-Fi 6")
    title_contains: an extra filter on the catalog entry's title, if you
                     need to narrow it down (e.g. "Driver"), can be left empty
    """

    def __init__(self, query: str, title_contains: str = "", name: str = "ms_catalog"):
        self.query = query
        self.title_contains = title_contains
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        resp = requests.get(
            SEARCH_URL,
            params={"q": self.query},
            headers=DEFAULT_HEADERS,
            timeout=20,
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", id="ctl00_catalogBody_updateMatches")
        if table is None:
            return None

        best = None
        best_date = None

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 6:
                continue  # skip the header and other non-data rows

            title = cells[1].get_text(strip=True)
            if self.title_contains and self.title_contains.upper() not in title.upper():
                continue

            date_str = cells[4].get_text(strip=True)
            version = cells[5].get_text(strip=True)

            date = self._parse_date(date_str)
            if date is None:
                continue

            if best_date is None or date > best_date:
                best_date = date
                # each row's id is "<update GUID>_R0" — strip the suffix to
                # get the GUID and link straight to that update's detail
                # page (ScopedViewInline.aspx), confirmed against the
                # catalog's own goToDetails() JS. Falls back to the generic
                # search page if the row has no id (markup change).
                row_id = row.get("id", "")
                update_id = row_id.split("_")[0] if row_id else None
                detail_url = (
                    f"https://www.catalog.update.microsoft.com/ScopedViewInline.aspx?updateid={update_id}"
                    if update_id else SEARCH_URL + f"?q={self.query}"
                )
                best = {
                    "version": version,
                    "date": date_str,
                    "title": title,
                    "url": detail_url,
                }

        return best

    @staticmethod
    def _parse_date(date_str: str):
        # format like "1/20/2026"
        try:
            return datetime.strptime(date_str, "%m/%d/%Y")
        except ValueError:
            return None

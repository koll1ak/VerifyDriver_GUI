"""
Provider for drivers distributed ONLY via Windows Update, with no
separate downloads page from the chip maker (typical for
Qualcomm/some MediaTek WiFi modules — unlike Intel, which has a
separate official page, see providers/intel_download.py).

    GET https://www.catalog.update.microsoft.com/Search.aspx?q=<query>

The search page is server-rendered (a plain HTML table), no JS needed.
The direct CDN download link is resolved with a second request — see
_resolve_download_url — mirroring what the site's own Download button
does under the hood.
"""

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

SEARCH_URL = "https://www.catalog.update.microsoft.com/Search.aspx"
DOWNLOAD_DIALOG_URL = "https://www.catalog.update.microsoft.com/DownloadDialog.aspx"


def catalog_search_url(query: str) -> str:
    from urllib.parse import quote
    return f"{SEARCH_URL}?q={quote(query)}"


def _resolve_download_url(update_id: str) -> str | None:
    """
    The catalog site itself gets the real .cab/.msu CDN link by POSTing
    the update's GUID here (this is what its "Download" button does under
    the hood) — the response is a JS snippet assigning
    downloadInformation[0].files[N].url, not a JSON API. Confirmed live;
    no auth/session needed, the CDN links are public.
    """
    body = f'updateIDs=[{{"size":0,"languages":"","uidInfo":"{update_id}","updateID":"{update_id}"}}]'
    resp = requests.post(
        DOWNLOAD_DIALOG_URL,
        data=body,
        headers={**DEFAULT_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
        timeout=20,
    )
    resp.raise_for_status()
    urls = re.findall(r"downloadInformation\[0\]\.files\[\d+\]\.url = '([^']+)'", resp.text)
    return urls[0] if urls else None


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

            # a lot of older/generic catalog entries (confirmed live:
            # every "Realtek High Definition Audio" result from
            # 2016-2017) have no real version at all, just the literal
            # placeholder text "n/a" in that column — picking one of
            # these as "best" produced a nonsensical "update to n/a".
            # Skip them; a versionless entry can never be a valid update.
            if not version or version.strip().lower() in ("n/a", "-"):
                continue

            date = self._parse_date(date_str)
            if date is None:
                continue

            if best_date is None or date > best_date:
                best_date = date
                # row id is "<update GUID>_R0" — strip the suffix to get
                # the GUID for the DownloadDialog.aspx lookup below.
                row_id = row.get("id", "")
                update_id = row_id.split("_")[0] if row_id else None
                best = {
                    "version": version,
                    "date": date_str,
                    "title": title,
                    "update_id": update_id,
                }

        if best is None:
            return None

        # Resolve straight to the CDN file link so opening it starts the
        # download immediately, same as the NVIDIA provider's DownloadURL —
        # falls back to the search results page (still has a working
        # Download button, just not a one-click one) if that lookup fails.
        download_url = None
        if best["update_id"]:
            try:
                download_url = _resolve_download_url(best["update_id"])
            except requests.RequestException:
                download_url = None
        best["url"] = download_url or catalog_search_url(self.query)
        del best["update_id"]

        return best

    @staticmethod
    def _parse_date(date_str: str):
        # format like "1/20/2026"
        try:
            return datetime.strptime(date_str, "%m/%d/%Y")
        except ValueError:
            return None

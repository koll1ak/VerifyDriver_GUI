"""
SenaryTech audio driver provider (a Chinese audio codec maker — an
alternative to Realtek, found on some Huawei models and others).

    https://www.senarytech.com/en/DriverDownload/index.aspx

The page is tiny and fully server-rendered (no JS) — at the time this
was written it only had 2 entries, each covering several chip codes at
once (e.g. "CX11880 | CX11970 | SN6140"). The version is baked into the
file name (e.g. "HDART_2.26.0.9_..." -> "2.26.0.9").

IMPORTANT: Huawei's driver package version differs from the version on
this page (e.g. "SenaryAudio_3.40.0.40" on Huawei vs "3.46.0.9" here) —
the same phenomenon we saw with MSI/Realtek Audio: the OEM repackages
the chip's driver under its own version number. So we don't do an
automatic version comparison — just show what's available.
"""

import re

import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

PAGE_URL = "https://www.senarytech.com/en/DriverDownload/index.aspx"

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+(?:\.\d+)?)_")


class SenaryAudioProvider(DriverProvider):
    """
    chip_code: the chip code to filter by (e.g. "SN6140" or "CX11880") —
    if not passed, the first (newest by list order) entry is returned.
    """

    def __init__(self, chip_code: str | None = None, name: str = "senary_audio"):
        self.chip_code = chip_code.upper() if chip_code else None
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        resp = requests.get(PAGE_URL, headers=DEFAULT_HEADERS, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        entries = []
        for link in soup.find_all("a", href=True):
            if "Download.aspx?Guid=" not in link["href"]:
                continue
            title = link.get_text(strip=True)
            version_match = _VERSION_RE.search(title)
            if version_match is None:
                continue  # this is most likely a duplicate "File Down" link with no version in its text
            url = link["href"]
            if url.startswith("/"):
                url = "https://www.senarytech.com" + url
            entries.append({"title": title, "url": url, "version": version_match.group(1)})

        if not entries:
            return None

        if self.chip_code:
            entries = [e for e in entries if self.chip_code in e["title"].upper()] or entries
            latest = entries[0]
            return {"version": latest["version"], "url": latest["url"], "description": latest["title"]}

        # without an exact chip code (DEV_) we don't know which entry is
        # really yours — show ALL of them at once instead of guessing one
        combined_version = " / ".join(f"{e['version']} ({e['title'].split('|')[0].strip()})" for e in entries)
        return {
            "version": combined_version,
            "url": entries[0]["url"],
            "description": "; ".join(e["title"] for e in entries),
        }

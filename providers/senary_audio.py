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

import hardware_ids
from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

PAGE_URL = "https://www.senarytech.com/en/DriverDownload/index.aspx"

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+(?:\.\d+)?)_")

# the release date is also baked into the file name, right before the
# extension (e.g. "..._DCH_10-21-22WHQL_Common_20231206.zip" -> "20231206")
_DATE_RE = re.compile(r"_(\d{8})\.zip", re.IGNORECASE)

# every chip code the site's two catalog entries list at the time this
# was written (see the module docstring's live-confirmed titles) --
# checked against the bundled pci.ids database in resolve_chip_code()
# below, NOT assumed to all be present there (only CX11880 confirmed so far)
_KNOWN_CHIP_CODES = ("CX20632", "CX11880", "CX11970", "SN6140")


def resolve_chip_code(device: dict) -> str | None:
    """
    Determines which SenaryTech-listed chip is installed, using the
    bundled pci.ids database (see hardware_ids.py) resolved via the
    device's PCI Vendor/Device ID. Confirmed live: pci.ids has
    chip-specific entries for CX11880 under Conexant's vendor ID (14F1,
    the same one SenaryTech-branded chips report) --
    "1f86  DBH CX11880 Codec" / "1f87  SMIC CX11880 Codec" -- but NOT for
    CX20632/CX11970/SN6140, which aren't in pci.ids at all.

    Returns None whenever the chip can't be confirmed this way (includes
    the CX20632/CX11970/SN6140 case above) -- callers MUST treat that as
    "chip unknown", not "no update available"; a wrong guess here would
    silently compare against the wrong catalog entry.
    """
    vendor_name, product_name = hardware_ids.lookup("pci", device.get("VendorID"), device.get("DeviceID_PCI"))
    if not product_name:
        return None
    product_upper = product_name.upper()
    for code in _KNOWN_CHIP_CODES:
        if code in product_upper:
            return code
    return None


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
            date_match = _DATE_RE.search(latest["title"])
            date = date_match.group(1) if date_match else None
            return {"version": latest["version"], "url": latest["url"], "description": latest["title"], "date": date}

        # without an exact chip code (DEV_) we don't know which entry is
        # really yours — show ALL of them at once instead of guessing one
        combined_version = " / ".join(f"{e['version']} ({e['title'].split('|')[0].strip()})" for e in entries)
        return {
            "version": combined_version,
            "url": entries[0]["url"],
            "description": "; ".join(e["title"] for e in entries),
        }

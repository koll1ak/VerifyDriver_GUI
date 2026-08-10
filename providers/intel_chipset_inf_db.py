"""
Provider for an accurate Intel Chipset version comparison — uses an open
community database (not an official Intel source, but public and
regularly updated) that tracks the INF file version separately for
EACH platform (by Hardware ID), rather than just the package version as
a whole.

    https://raw.githubusercontent.com/FirstEverTech/Universal-Intel-Chipset-Updater/main/data/intel-chipset-infs-latest.md

Why this solves the problem we struggled with earlier: the Intel
Chipset Device Software package version (e.g. "10.1.20658.8883") has no
relationship to the version of a specific installed component (e.g.
"10.1.31.3" for CometLake PCH-H) — these are different numbering
schemes, and the package can get updated without ever touching the
version for your specific CPU generation. This database gives the
component's own version — the same numbering scheme visible on the
installed system — so the comparison ends up meaningful.

Source: https://github.com/FirstEverTech/Universal-Intel-Chipset-Updater
Author: Marcin Grygiel
"""

import re

import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

DB_URL = "https://raw.githubusercontent.com/FirstEverTech/Universal-Intel-Chipset-Updater/main/data/intel-chipset-infs-latest.md"

_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")


def _clean_cell(cell: str) -> str:
    # strip markdown escaping ("\_" -> "_") and stray whitespace/asterisks
    return cell.replace("\\_", "_").replace("\\*", "").strip()


_DATE_CELL_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})\*?$")


def _normalize_date_cell(cell: str) -> str:
    """
    The database's date column is day/month/year with a trailing "*"
    footnote marker (confirmed live, e.g. "18/03/2026*") -- a format
    parse_flexible_date (checks/common.py) doesn't recognize (it only
    knows month/day/year for slash-separated dates, used by other
    sources like pnputil), so every date from here silently failed to
    parse and got dropped. Converting to ISO (YYYY-MM-DD) here, specific
    to this one source, avoids making the shared parser guess between
    day/month/year and month/day/year for ambiguous cells from other
    providers.
    """
    cleaned = _clean_cell(cell)
    m = _DATE_CELL_RE.match(cleaned)
    if not m:
        return cleaned
    day, month, year = m.groups()
    return f"{year}-{month.zfill(2)}-{day.zfill(2)}"


def _parse_database(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        m = _TABLE_ROW_RE.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) != 5:
            continue
        inf_cell, package_cell, version_cell, date_cell, hwids_cell = cells

        if not set(package_cell) <= set("-: "):  # skip the table's separator row
            if ".inf" not in inf_cell.lower():
                continue  # not a data row (e.g. a header)
            hwids = [
                _clean_cell(h).upper()
                for h in hwids_cell.split(",")
                if _clean_cell(h)
            ]
            rows.append({
                "inf": _clean_cell(inf_cell),
                "package": _clean_cell(package_cell),
                "version": _clean_cell(version_cell),
                "date": _normalize_date_cell(date_cell),
                "hwids": hwids,
            })
    return rows


class IntelChipsetInfDbProvider(DriverProvider):
    """
    hwid: the device's specific Hardware ID (DEV_XXXX without the
    prefix) — taken from the scanned chipset device, we look up which
    platform in the database this specific HWID belongs to.
    """

    name = "intel_chipset_inf_db"

    def __init__(self, hwid: str):
        self.hwid = hwid.upper()

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        resp = requests.get(DB_URL, headers=DEFAULT_HEADERS, timeout=20)
        resp.raise_for_status()

        rows = _parse_database(resp.text)

        for row in rows:
            if self.hwid in row["hwids"]:
                return {
                    "version": row["version"],
                    "date": row["date"],
                    "url": DB_URL,
                    "inf": row["inf"],
                    "package": row["package"],
                }

        return None

"""
Provider for BIOS/Audio drivers from the LG site (lg.com) — LG gram
laptops.

NOT VERIFIED on a real device — the author doesn't have an LG laptop
on hand. Every step below WAS independently confirmed live (via Claude
in Chrome capturing the site's real network requests) against two real
current products (LG gram Pro 17 "17Z90U-G.AU89U1" and LG gram Pro 16
"16Z90U-K.AUB7U1").

Two steps:

1. GET https://www.lg.com/us/support/api/products/model-number
       ?searchModel=<base model, e.g. "17Z90U-G">
   Confirmed live: this is the API behind the support site's own
   "Search by model number" box. Returns every specific SKU variant
   (differing by RAM/storage/color) under that base model, each with
   its own "model"/"salesCode" (e.g. "17Z90U-G.AU75U1") — filtered to
   category == "Laptops". Confirmed live: driver data is identical
   across variants of the same base model, so any one of them works;
   we take the first.

2. GET https://www.lg.com/us/support/product/lg-<resolved model>?tab=1
   Confirmed live: server-rendered (reachable via curl_cffi with
   impersonate="chrome" — plain requests gets a 403, same Akamai-style
   block as several other vendors here). The download list ISN'T in
   plain HTML text as clickable links (confirmed: zero <a href> in
   that section) — it's a Next.js page, and the real structured data
   lives in the embedded <script id="__NEXT_DATA__"> JSON, at
   props.pageProps.softwareData.swList: a clean list of {title,
   releaseDate (MM/DD/YYYY string), fileSize, downloadLink (a real,
   direct gscs-b2c.lge.com URL), originalFileName}. title embeds the
   version (e.g. "Ver.24.10.0.4") and a bracketed category tag (e.g.
   "[Wireless/Win11_64bit]", "[LAN/Win11_64bit]").

IMPORTANT — confirmed live, not just theorized: neither of the two
real current-generation gram models checked had a BIOS or Audio entry
in swList at all (only "LG Update" + WLAN + 2x LAN). This may mean gram
laptops fold BIOS updates into the "LG Update" auto-updater tool rather
than offering a standalone download, and/or rely on Windows Update for
audio — or it may just be these two specific (2024+, Copilot+ PC era)
models; older/other gram lines weren't checked. Either way, the
category-matching logic below is written generically and will surface
BIOS/Audio entries correctly if/when they exist for a given model —
this isn't a case of guessing at an unconfirmed category name.
"""

import re
import json
from datetime import datetime

from bs4 import BeautifulSoup
from curl_cffi import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_USER_AGENT

MODEL_SEARCH_URL = "https://www.lg.com/us/support/api/products/model-number"
PRODUCT_PAGE_URL = "https://www.lg.com/us/support/product/lg-{model}"

HEADERS = {"User-Agent": DEFAULT_USER_AGENT}

_VERSION_RE = re.compile(r"Ver\.?\s*([\d.]+)", re.IGNORECASE)


def _parse_release_date(raw: str):
    try:
        return datetime.strptime(raw, "%m/%d/%Y")
    except (ValueError, TypeError):
        return None


class LgSupportProvider(DriverProvider):
    """
    base_model: the machine's base model code (e.g. "17Z90U-G") — used
    as a search query to resolve the specific SKU variant needed for
    the actual driver page (see module docstring step 1). NOT verified
    against a real LG laptop's Win32_ComputerSystem.Model format.
    category: substring matched case-insensitively against each
    swList item's title (e.g. "BIOS" or "Audio").
    """

    def __init__(self, base_model: str, category: str, name: str = "lg_support"):
        self.base_model = base_model
        self.category = category
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def _resolve_model(self) -> str | None:
        resp = requests.get(
            MODEL_SEARCH_URL, params={"searchModel": self.base_model},
            headers={**HEADERS, "Accept": "application/json"}, timeout=20, impersonate="chrome",
        )
        resp.raise_for_status()
        results = [r for r in (resp.json() or []) if r.get("category") == "Laptops"]
        if not results:
            return None
        return results[0].get("model")

    def get_latest(self, device: dict = None) -> dict | None:
        model = self._resolve_model()
        if model is None:
            return None

        resp = requests.get(
            PRODUCT_PAGE_URL.format(model=model), params={"tab": "1"},
            headers=HEADERS, timeout=20, impersonate="chrome",
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if script is None or not script.string:
            return None
        data = json.loads(script.string)
        sw_list = (((data.get("props") or {}).get("pageProps") or {}).get("softwareData") or {}).get("swList") or []

        candidates = [it for it in sw_list if self.category.upper() in (it.get("title") or "").upper()]
        if not candidates:
            return None

        best = max(candidates, key=lambda it: _parse_release_date(it.get("releaseDate")) or datetime.min)

        version_match = _VERSION_RE.search(best.get("title") or "")
        version = version_match.group(1) if version_match else best.get("title")

        return {
            "version": version,
            "date": best.get("releaseDate"),
            "url": best.get("downloadLink"),
            "size": best.get("fileSize"),
            "title": best.get("title"),
        }

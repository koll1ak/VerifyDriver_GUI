"""
Provider for BIOS/Audio drivers from the HP site (support.hp.com).

NOT VERIFIED on a real device — the author doesn't have an HP laptop
on hand. Every step below WAS independently confirmed live, though,
using Claude in Chrome to drive the real site and capture its actual
network requests (the same DevTools-network-tab technique used to
build the other providers) against a real, currently-shipping product
(HP Spectre x360 14 inch 2-in-1 Laptop PC 14-eu0000) — this is a
stronger starting point than a pure documentation guess, but a real
device is still needed to confirm WMI's exact Model string format and
the BIOS version format comparison.

Three steps, none needing a serial number (no HP hardware to test a
real serial-based lookup with — see risk #1):

1. GET https://support.hp.com/typeahead?q=<model name>&resultLimit=10
       &store=tmsstore&languageCode=en
       &filters=class:(pm_series_value^1.1 OR pm_name_value OR pm_number_value)
                AND (hiddenproduct:no OR (!_exists_:hiddenproduct))
       &printFields=tmspmseriesvalue,tmspmnamevalue,tmspmnumbervalue,class,
                    productid,title,tmsnodedepth,seofriendlyname,
                    navigationpath,shortestnavigationpath,childnodes,
                    activewebsupportflag,historicalwebsupportflag,body,
                    btoflag,description
   Confirmed live: this is the same typeahead search HP's own "enter
   your serial number, product number or product name" box uses.
   matches[] entries have a "pmClass" of "pm_series_value" (a product
   line/name grouping, e.g. "...14-eu0000") or "pm_name_value"/
   "pm_number_value" (more specific configurations within it) — take
   the best-scoring pm_series_value match's "productId" as
   productSeriesOid, and the FIRST entry in its pipe-separated
   "childnodes" string as productNumberOid. Confirmed live that the
   driverDetails endpoint below doesn't care which child you use here —
   tested two different direct children of the same series and both
   returned the identical 12-category driver list, so exact SKU
   precision isn't needed for driver data (BIOS/Audio/Chipset etc. are
   shared across configurations of the same series).

2. GET https://support.hp.com/wcc-services/swd-v2/osVersionData
       ?cc=<cc>&lc=<lc>&productOid=<productSeriesOid>
   Confirmed live, no auth needed. Returns data.osAvailablePlatformsAnsOS
   .osPlatforms — a list with one entry per OS family (e.g. "Windows"),
   each with its own "id" (-> platformId) and an "osVersions" list of
   specific versions (each with its own "id" -> osTMSId). We use the
   platform's generic top-level entry (name == "Windows 10"/"Windows 11"
   exactly, not a dated sub-version like "...version 24H2 (64-bit)") —
   confirmed live this is what HP's own OS dropdown defaults to.

3. POST https://support.hp.com/wcc-services/swd-v2/driverDetails
   Body: {"productLineCode": "", "lc": <lc>, "cc": <cc>,
          "osTMSId": <from step 2>, "osName": "Windows",
          "productNumberOid": <from step 1>,
          "productSeriesOid": <from step 1>,
          "platformId": <from step 2>}
   Confirmed live (found via the page's own compiled Angular component,
   src_app_.../swd-download-page_component, function
   getProductDriversList) — productLineCode can be sent empty and the
   call still succeeds; productNumberOid is REQUIRED (an empty string
   makes data come back null). Response: data.softwareTypes[], each
   with "accordionName" (confirmed real category names: "BIOS",
   "Driver-Audio", "Driver-Chipset", "Driver-Network", ...) and
   "softwareDriversList[]" — each item's "latestVersionDriver" has
   "version" (e.g. "F.17 Rev.A" for BIOS — HP's own alphanumeric build
   code, NOT a dotted number, so no numeric comparison is possible for
   it, same situation as Dell/Gigabyte/ASRock/Lenovo BIOS), "title",
   "releaseDateString", and "fileUrl" pointing directly at a real
   ftp.hp.com SoftPaq download (confirmed live, e.g.
   https://ftp.hp.com/pub/softpaq/sp172501-173000/sp172870.exe).

Risks worth checking on the first real run:
1. No real serial number was available to test — WMI's exact
   Win32_ComputerSystem.Model string format on real HP hardware isn't
   confirmed, only that a full marketing name (as tested via the site's
   own search suggestions) resolves correctly. If auto-detection
   doesn't find a match, check the raw Model string via
   `python laptop_detect.py` and compare against what support.hp.com's
   search box accepts.
2. Audio version format ("614.6" style Realtek numbers, TBD from a real
   response) — comparison against the installed version isn't attempted
   (current=None), same as Dell/Gigabyte/ASRock, until confirmed.
"""

import sys

import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

TYPEAHEAD_URL = "https://support.hp.com/typeahead"
OS_VERSION_URL = "https://support.hp.com/wcc-services/swd-v2/osVersionData"
DRIVER_DETAILS_URL = "https://support.hp.com/wcc-services/swd-v2/driverDetails"

TYPEAHEAD_FILTERS = (
    "class:(pm_series_value^1.1 OR pm_name_value OR pm_number_value) "
    "AND (hiddenproduct:no OR (!_exists_:hiddenproduct))"
)
TYPEAHEAD_PRINT_FIELDS = (
    "tmspmseriesvalue,tmspmnamevalue,tmspmnumbervalue,class,productid,title,"
    "tmsnodedepth,seofriendlyname,navigationpath,shortestnavigationpath,"
    "childnodes,activewebsupportflag,historicalwebsupportflag,body,btoflag,"
    "description"
)

WINDOWS_11_MIN_BUILD = 22000


def detect_windows_name() -> str:
    """"Windows 11" / "Windows 10" — matches HP's own osVersions[].name for the generic (non-dated) entry."""
    try:
        build = sys.getwindowsversion().build
    except AttributeError:
        return "Windows 10"
    return "Windows 11" if build >= WINDOWS_11_MIN_BUILD else "Windows 10"


class HpSupportProvider(DriverProvider):
    """
    model_name: the machine's marketing product name (Win32_ComputerSystem
    .Model, e.g. "HP Spectre x360 14-eu0000") — used as a search query,
    not an exact ID lookup (HP has no simpler single-field ID we could
    confirm without a real serial number, see module docstring risk #1).
    category: the exact accordionName from HP's response ("BIOS" or
    "Driver-Audio" — confirmed real values).
    """

    def __init__(self, model_name: str, category: str, country: str = "us", lang: str = "en", name: str = "hp_support"):
        self.model_name = model_name
        self.category = category
        self.country = country
        self.lang = lang
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def _resolve_product(self) -> tuple[str, str] | None:
        """Returns (productSeriesOid, productNumberOid), or None if no match."""
        resp = requests.get(
            TYPEAHEAD_URL,
            params={
                "q": self.model_name,
                "resultLimit": 10,
                "store": "tmsstore",
                "languageCode": self.lang,
                "filters": TYPEAHEAD_FILTERS,
                "printFields": TYPEAHEAD_PRINT_FIELDS,
            },
            headers=DEFAULT_HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        series_matches = [m for m in (data.get("matches") or []) if m.get("pmClass") == "pm_series_value"]
        if not series_matches:
            return None

        best = max(series_matches, key=lambda m: m.get("matchScore", 0))
        series_oid = best.get("productId")
        childnodes = (best.get("childnodes") or "").strip("|").split("|")
        if series_oid is None or not childnodes or not childnodes[0]:
            return None

        return str(series_oid), childnodes[0]

    def _resolve_os(self, series_oid: str) -> tuple[str, str] | None:
        """Returns (osTMSId, platformId) for the installed Windows version, or None."""
        resp = requests.get(
            OS_VERSION_URL,
            params={"cc": self.country, "lc": self.lang, "productOid": series_oid},
            headers=DEFAULT_HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        platforms = ((data.get("data") or {}).get("osAvailablePlatformsAnsOS") or {}).get("osPlatforms") or []
        windows_platform = next((p for p in platforms if p.get("name") == "Windows"), None)
        if windows_platform is None:
            return None

        target_name = detect_windows_name()
        versions = windows_platform.get("osVersions") or []
        version = next((v for v in versions if v.get("name") == target_name), None)
        if version is None:
            return None

        return version.get("id"), windows_platform.get("id")

    def get_latest(self, device: dict = None) -> dict | None:
        product = self._resolve_product()
        if product is None:
            return None
        series_oid, number_oid = product

        os_ids = self._resolve_os(series_oid)
        if os_ids is None:
            return None
        os_tms_id, platform_id = os_ids

        body = {
            "productLineCode": "",
            "lc": self.lang,
            "cc": self.country,
            "osTMSId": os_tms_id,
            "osName": "Windows",
            "productNumberOid": number_oid,
            "productSeriesOid": series_oid,
            "platformId": platform_id,
        }
        resp = requests.post(
            DRIVER_DETAILS_URL,
            params={"authState": "anonymous"},
            headers={**DEFAULT_HEADERS, "Content-Type": "application/json"},
            json=body,
            timeout=20,
        )
        resp.raise_for_status()
        data = (resp.json() or {}).get("data") or {}

        software_types = data.get("softwareTypes") or []
        category_data = next((s for s in software_types if s.get("accordionName") == self.category), None)
        if category_data is None:
            return None

        items = category_data.get("softwareDriversList") or []
        if not items:
            return None

        driver = items[0].get("latestVersionDriver") or {}
        version = driver.get("version")
        if not version:
            return None

        return {
            "version": version,
            "date": driver.get("releaseDateString") or driver.get("releaseDate"),
            "url": driver.get("fileUrl"),
            "size": driver.get("fileSize"),
            "title": driver.get("title"),
        }

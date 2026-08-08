"""
Realtek LAN provider — a thin wrapper over RealtekCategoryProvider.

cate_id=584 — the general PCIe FE/GbE/2.5G/5G/10G category, covers the
whole RTL8111/8125/8126/8127 chip lineup with a single installer (the
installer itself detects the specific chip). The category contains
several driver variants at once (NDIS/NetAdapterCx, with and without
power-saving support) — we select by a substring in Description rather
than by index (the order can change on an update).
"""

from providers.realtek_base import RealtekCategoryProvider

DEFAULT_CATE_ID = "584"
DEFAULT_MATCH_SUBSTRINGS = ("NetAdapterCx", "Not Support Power Saving")


def realtek_versions_match(current: str, latest: str) -> bool:
    """
    The site gives a version like "11.030.20", Windows gives one like
    "1126.30.20.508". The middle two segments of the Windows version
    correspond to the last two segments of the site's version (with
    leading zeros stripped) — e.g. "30.20" in both cases. The first
    segment of the Windows version is a combination of a product code
    and release year, the last one is an internal build number, neither
    is used in the comparison.

    This rule has ONLY been confirmed empirically for 2.5G/5G chips
    (e.g. the RTL8126, where the real version was "1126.30.20.508"). For
    older 1GbE chips (RTL8111, etc.) the Windows version format looks
    different — e.g. "1168.8.515.2022", where the last segment looks like
    a year, not a build — this rule doesn't apply there.
    is_recognized_format() below helps tell the two cases apart before
    trusting the comparison.
    """
    if not current or not latest:
        return False

    def _norm(parts):
        try:
            return ".".join(str(int(p)) for p in parts)
        except ValueError:
            return None

    site_parts = latest.split(".")
    installed_parts = current.split(".")

    if len(site_parts) < 2 or len(installed_parts) < 3:
        return False

    site_norm = _norm(site_parts[-2:])
    installed_norm = _norm(installed_parts[1:3])

    return site_norm is not None and site_norm == installed_norm


def is_recognized_realtek_version_format(current: str) -> bool:
    """
    True if the Windows version looks like the confirmed format for
    2.5G/5G chips ("PPYY.mid.mid.build", e.g. "1126.30.20.508" — first
    segment 4 digits, where the last 2 are plausible as a 20XX year).
    Older 1GbE chips have a different format (e.g. "1168.8.515.2022") —
    not empirically confirmed, comparing against the site isn't safe.
    """
    parts = current.split(".")
    if len(parts) != 4:
        return False
    first = parts[0]
    if len(first) != 4 or not first.isdigit():
        return False
    year_part = int(first[2:4])
    return 20 <= year_part <= 39  # a plausible release year (2020s-2030s)


def realtek_ndis_versions_match(current: str, latest: str) -> bool:
    """
    For the NDIS driver variant (not NetAdapterCx), the Windows version
    and the site's version match directly — the site gives "10.80.20",
    Windows gives "10.80.20.407" (just with an extra build segment
    appended). Confirmed on a real device.
    """
    if not current or not latest:
        return False
    installed_parts = current.split(".")
    if len(installed_parts) < 3:
        return False
    try:
        installed_prefix = ".".join(str(int(p)) for p in installed_parts[:3])
        site_norm = ".".join(str(int(p)) for p in latest.split("."))
    except ValueError:
        return False
    return installed_prefix == site_norm


def detect_realtek_lan_variant(current: str) -> str:
    """
    "ndis" / "netadaptercx" / "unknown" — which driver framework is
    installed, based on the version format. NDIS gives a short first
    segment ("10"/"11"), NetAdapterCx gives a product-code-plus-year
    combo ("1126" etc., see is_recognized_realtek_version_format). Both
    are confirmed on real devices — either one may be installed on a
    given machine, Realtek's page publishes both variants separately.

    IMPORTANT: on some legacy chips the last version segment is also a
    year (e.g. "10.31.828.2018"), and the first segment can coincidentally
    match "10"/"11" — this is NOT the real NDIS format (confirmed in
    practice: such a version doesn't match any entry on the site). We
    check for this BEFORE detecting NDIS, to avoid comparing incorrectly.
    """
    if not current:
        return "unknown"
    parts = current.split(".")
    if len(parts) != 4:
        return "unknown"

    last = parts[-1]
    if len(last) == 4 and last.isdigit() and 2000 <= int(last) <= 2039:
        return "unknown"  # looks like the legacy format with a year at the end

    if parts[0] in ("10", "11"):
        return "ndis"
    if is_recognized_realtek_version_format(current):
        return "netadaptercx"
    return "unknown"


class RealtekLanProvider(RealtekCategoryProvider):
    name = "realtek_lan"

    def __init__(self, cate_id: str = DEFAULT_CATE_ID, match_substrings=DEFAULT_MATCH_SUBSTRINGS):
        super().__init__(cate_id=cate_id, match_substrings=match_substrings)

    def matches(self, device: dict) -> bool:
        # Realtek's VEN_10EC is used for both audio and LAN — we exclude
        # audio devices by checking for "FAMILY CONTROLLER" in the name
        # (that's what Windows calls this lineup's network chips)
        return (
            device.get("VendorID") == "10EC"
            and "FAMILY CONTROLLER" in device.get("DeviceName", "").upper()
        )

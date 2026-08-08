"""
Auto-detection of the motherboard: vendor, model, chipset.

Source — Win32_BaseBoard via WMI. Works reliably on DIY builds (a PC
assembled from a "bare" board). On laptops and pre-built systems
(Dell/HP/Lenovo) Win32_BaseBoard often returns garbage like
"Type1ProductConfigId" — a different source is needed there
(Win32_ComputerSystem.Manufacturer/Model), which isn't covered here.

IMPORTANT: the logic for ASUS/Gigabyte/ASRock was only verified against
the structure of their websites (real server-rendered pages, inspected
via web_fetch), but NOT verified against a real Win32_BaseBoard.Product
value for these vendors — unlike MSI, where the format is confirmed on
an actual machine. The format may differ (suffixes, case) — if
auto-detection doesn't work, check the extracted values manually via
`python board_detect.py` and adjust the normalize_* functions if needed.
"""

import re
import subprocess

# --- Board vendor detection -------------------------------------------

# substring in Win32_BaseBoard.Manufacturer -> internal vendor code
VENDOR_SIGNATURES = {
    "MICRO-STAR": "msi",
    "MSI": "msi",
    "ASUSTEK": "asus",
    "GIGABYTE": "gigabyte",
    "ASROCK": "asrock",
}

# --- Known AMD/Intel chipsets and their socket (for amd.com and ASRock URLs) -

AMD_CHIPSET_SOCKETS = {
    # AM5
    "X870E": "am5", "X870": "am5",
    "X670E": "am5", "X670": "am5",
    "B850": "am5", "B650E": "am5", "B650": "am5",
    "A620": "am5",
    # AM4 (legacy, just in case)
    "X570": "am4", "X470": "am4", "X370": "am4",
    "B550": "am4", "B450": "am4", "B350": "am4",
    "A520": "am4", "A320": "am4",
}

# Intel — only used to detect family="intel" for ASRock, no amd.com-specific
# URL building here (Intel has its own logic via Download Center)
INTEL_CHIPSET_CODENAMES = {
    "Z890", "B860", "H810",
    "Z790", "B760", "H770", "Q670", "H610",
}

ALL_CHIPSET_CODENAMES = set(AMD_CHIPSET_SOCKETS) | INTEL_CHIPSET_CODENAMES

CHIPSET_CODENAME_REGEX = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in ALL_CHIPSET_CODENAMES) + r")\b"
)


def get_motherboard_info() -> dict | None:
    """
    Returns {"manufacturer": ..., "product": ...} from Win32_BaseBoard,
    or None if it couldn't be obtained (e.g. not Windows).
    """
    ps_command = (
        "Get-CimInstance Win32_BaseBoard | "
        "Select-Object Manufacturer, Product | ConvertTo-Json"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None

    import json
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    manufacturer = (data.get("Manufacturer") or "").strip()
    product = (data.get("Product") or "").strip()
    if not manufacturer or not product:
        return None

    return {"manufacturer": manufacturer, "product": product}


def detect_vendor(manufacturer: str) -> str | None:
    """MSI/ASUS/Gigabyte/ASRock -> internal vendor code, otherwise None."""
    manufacturer_upper = manufacturer.upper()
    for signature, vendor_code in VENDOR_SIGNATURES.items():
        if signature in manufacturer_upper:
            return vendor_code
    return None


def _hyphenate_product_name(product: str) -> str:
    """
    Shared logic for MSI and Gigabyte — both use an uppercase
    "BOARD-NAME-WITH-HYPHENS" slug, without the board-code suffix in
    parentheses (e.g. "(MS-7E51)").
    "MAG X870 TOMAHAWK WIFI (MS-7E51)" -> "MAG-X870-TOMAHAWK-WIFI"
    """
    without_suffix = re.sub(r"\s*\([^)]*\)\s*$", "", product).strip()
    return re.sub(r"\s+", "-", without_suffix).upper()


def extract_msi_product_slug(product: str) -> str:
    return _hyphenate_product_name(product)


def extract_gigabyte_slug(product: str) -> str:
    return _hyphenate_product_name(product)


def _strip_suffix(product: str) -> str:
    """
    Shared logic for ASUS and ASRock — both use the model with spaces
    as-is in the URL, we only strip the parenthesized suffix if present.
    """
    return re.sub(r"\s*\([^)]*\)\s*$", "", product).strip()


def extract_asus_model(product: str) -> str:
    return _strip_suffix(product)


def extract_asrock_model(product: str) -> str:
    return _strip_suffix(product)


def extract_chipset_codename(product: str) -> str | None:
    """Looks for a known chipset name (X870, B650, ...) in the board name."""
    match = CHIPSET_CODENAME_REGEX.search(product.upper())
    return match.group(1) if match else None


def detect_chipset_family(chipset_codename: str | None) -> str:
    """AMD/Intel — needed by ASRock for the /mb/<family>/... path segment on the site."""
    if chipset_codename in AMD_CHIPSET_SOCKETS:
        return "amd"
    if chipset_codename in INTEL_CHIPSET_CODENAMES:
        return "intel"
    return "amd"  # default — the most common case


def build_amd_chipset_page_url(chipset_codename: str) -> str | None:
    socket = AMD_CHIPSET_SOCKETS.get(chipset_codename)
    if socket is None:
        return None
    return (
        f"https://www.amd.com/en/support/downloads/drivers.html/"
        f"chipsets/{socket}/{chipset_codename.lower()}.html"
    )


def detect_board() -> dict:
    """
    Main function: returns everything that could be determined.
    {
        "vendor": "msi" | "asus" | "gigabyte" | "asrock" | None,
        "manufacturer_raw": str | None,
        "product_raw": str | None,
        "msi_slug": str | None,
        "gigabyte_slug": str | None,
        "asus_model": str | None,
        "asrock_model": str | None,
        "chipset_codename": str | None,   # e.g. "X870"
        "chipset_family": str,            # "amd" | "intel"
        "amd_chipset_url": str | None,    # ready-made URL for AmdChipsetProvider
    }
    """
    info = get_motherboard_info()
    if info is None:
        return {
            "vendor": None, "manufacturer_raw": None, "product_raw": None,
            "msi_slug": None, "gigabyte_slug": None,
            "asus_model": None, "asrock_model": None,
            "chipset_codename": None, "chipset_family": "amd",
            "amd_chipset_url": None,
        }

    vendor = detect_vendor(info["manufacturer"])
    product = info["product"]
    chipset = extract_chipset_codename(product)

    return {
        "vendor": vendor,
        "manufacturer_raw": info["manufacturer"],
        "product_raw": product,
        "msi_slug": extract_msi_product_slug(product) if vendor == "msi" else None,
        "gigabyte_slug": extract_gigabyte_slug(product) if vendor == "gigabyte" else None,
        "asus_model": extract_asus_model(product) if vendor == "asus" else None,
        "asrock_model": extract_asrock_model(product) if vendor == "asrock" else None,
        "chipset_codename": chipset,
        "chipset_family": detect_chipset_family(chipset),
        "amd_chipset_url": build_amd_chipset_page_url(chipset) if chipset else None,
    }


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(detect_board(), indent=2, ensure_ascii=False))

"""
Laptop detection: chassis type, vendor/model, Service Tag (for Dell),
serial number (for Lenovo — used as productId in the pcsupport.lenovo.com API).

Sources — WMI:
- Win32_SystemEnclosure.ChassisTypes — codes 8-14, 30-32 correspond to
  portable chassis types (laptop, convertible tablet, etc.)
- Win32_ComputerSystem.Manufacturer/Model — vendor/model of the system as
  a whole (not the board — on laptops Win32_BaseBoard often returns garbage)
- Win32_BIOS.SerialNumber — on Dell hardware this is the Service Tag,
  a unique 7-character identifier for the specific device
"""

import subprocess
import json
import re

# chassis codes that Windows/DMI considers portable
LAPTOP_CHASSIS_TYPES = {"8", "9", "10", "11", "12", "14", "30", "31", "32"}


def is_laptop() -> bool | None:
    """True/False, or None if it couldn't be determined."""
    ps_command = (
        "(Get-CimInstance Win32_SystemEnclosure).ChassisTypes | ConvertTo-Json"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_command],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        return None  # powershell unavailable (not Windows, restrictions, etc.)

    if result.returncode != 0 or not result.stdout.strip():
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    codes = data if isinstance(data, list) else [data]
    return any(str(c) in LAPTOP_CHASSIS_TYPES for c in codes)


def get_laptop_info() -> dict:
    """
    {"manufacturer": ..., "model": ..., "dell_service_tag": ..., "acer_model_name": ...,
     "lenovo_serial": ...}
    """
    ps_command = (
        "$cs = Get-CimInstance Win32_ComputerSystem; "
        "$bios = Get-CimInstance Win32_BIOS; "
        "[PSCustomObject]@{ "
        "Manufacturer = $cs.Manufacturer; Model = $cs.Model; "
        "SerialNumber = $bios.SerialNumber "
        "} | ConvertTo-Json"
    )
    empty = {
        "manufacturer": None, "model": None, "dell_service_tag": None,
        "acer_model_name": None, "acer_part_number": None, "acer_serial": None,
        "asus_laptop_model": None, "lenovo_serial": None, "hp_model": None,
        "msi_laptop_model": None,
    }
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_command],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        return empty

    if result.returncode != 0 or not result.stdout.strip():
        return empty

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return empty

    manufacturer = (data.get("Manufacturer") or "").strip()
    model = (data.get("Model") or "").strip()
    serial = (data.get("SerialNumber") or "").strip()

    is_dell = "DELL" in manufacturer.upper()
    is_acer = "ACER" in manufacturer.upper()
    is_asus = "ASUS" in manufacturer.upper()
    is_lenovo = "LENOVO" in manufacturer.upper()
    # "HP" on newer devices, "Hewlett-Packard" on older ones (both confirmed
    # real WMI Manufacturer values used across HP's product history)
    is_hp = "HP" in manufacturer.upper() or "HEWLETT" in manufacturer.upper()
    is_msi = "MICRO-STAR" in manufacturer.upper() or "MSI" in manufacturer.upper()

    return {
        "manufacturer": manufacturer or None,
        "model": model or None,
        "dell_service_tag": serial if (is_dell and serial) else None,
        "acer_model_name": extract_acer_model_name(model) if (is_acer and model) else None,
        "acer_part_number": extract_acer_part_number(serial) if (is_acer and serial) else None,
        "acer_serial": serial if (is_acer and serial) else None,
        "asus_laptop_model": extract_asus_laptop_model(model) if (is_asus and model) else None,
        "lenovo_serial": serial if (is_lenovo and serial) else None,
        # HP has no simpler single-field ID confirmed without a real
        # serial number (see providers/hp_support.py risk #1) — the raw
        # marketing model name is used as a search query instead
        "hp_model": model if (is_hp and model) else None,
        "msi_laptop_model": extract_msi_laptop_slug(model) if (is_msi and model) else None,
    }


# known Acer product lines — stripped from the prefix to get the exact
# part that acer.com uses as ModelName
# (e.g. "Nitro AN515-55" -> "AN515-55")
ACER_PRODUCT_LINES = (
    "Predator", "Nitro", "Aspire", "Swift", "TravelMate",
    "Extensa", "ConceptD", "Spin", "Enduro", "Iconia", "Chromebook",
)
_ACER_PREFIX_RE = re.compile(
    r"^(?:" + "|".join(ACER_PRODUCT_LINES) + r")\s+", re.IGNORECASE
)


def extract_acer_model_name(model: str) -> str:
    """"Nitro AN515-55" -> "AN515-55" (strips the product line prefix)."""
    return _ACER_PREFIX_RE.sub("", model).strip()


def extract_acer_part_number(serial: str) -> str | None:
    """
    The Acer part number is derived directly from the first 10 characters
    of the serial number:
    "NHQ7JEU00G0400B98F3400" -> "NH.Q7JEU.00G"
    (2+5+3 character segments separated by dots) — confirmed on a real
    device (Acer Nitro AN515-55).
    """
    if not serial or len(serial) < 10:
        return None
    return f"{serial[0:2]}.{serial[2:7]}.{serial[7:10]}"


def extract_asus_laptop_model(model: str) -> str:
    """
    On ASUS laptops, Win32_ComputerSystem.Model usually duplicates the
    model code with an underscore:
    "ASUS Vivobook S 16 S5606CA_S5606CA" -> "S5606CA"
    (confirmed on a real device) — take the last segment after "_";
    if there's no underscore, use the string as-is.
    """
    if "_" in model:
        return model.rsplit("_", 1)[-1].strip()
    return model.strip()


def extract_msi_laptop_slug(model: str) -> str:
    """
    Same hyphenation pattern confirmed for MSI desktop boards
    (board_detect.py's _hyphenate_product_name) — "Katana 15 B13VFK
    (MS-16WK)" -> "KATANA-15-B13VFK". Confirmed live that MSI's laptop
    API is case-insensitive on this slug, so the casing mismatch
    against the site's own display casing ("Katana-15-B13VFK") doesn't
    matter. NOT verified against a real MSI laptop's actual
    Win32_ComputerSystem.Model string — see providers/msi_laptop.py
    risk #1: this assumes Model already reports the specific-SKU-level
    slug the API's "product" param expects (matching how desktop board
    slugs work), not a family/parent name.
    """
    without_suffix = re.sub(r"\s*\([^)]*\)\s*$", "", model).strip()
    return re.sub(r"\s+", "-", without_suffix).upper()


def detect_laptop() -> dict:
    """
    Main function.
    {
        "is_laptop": True/False/None,
        "manufacturer": str | None,
        "model": str | None,
        "dell_service_tag": str | None,
    }
    """
    laptop = is_laptop()
    info = get_laptop_info()
    return {"is_laptop": laptop, **info}


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(detect_laptop(), indent=2, ensure_ascii=False))

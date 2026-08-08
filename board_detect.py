"""
Автоопределение материнской платы: вендор, модель, чипсет.

Источник — Win32_BaseBoard через WMI. Надёжно работает на DIY-сборках
(самостоятельно собранный ПК на "голой" плате). На ноутбуках и
готовых системах (Dell/HP/Lenovo) Win32_BaseBoard часто возвращает
мусор вроде "Type1ProductConfigId" — там нужен другой источник
(Win32_ComputerSystem.Manufacturer/Model), это не покрыто.

ВАЖНО: логика для ASUS/Gigabyte/ASRock проверена только на структуре
их сайтов (реальные страницы server-rendered, разобраны через web_fetch),
но НЕ проверена на реальном Win32_BaseBoard.Product для этих вендоров —
в отличие от MSI, где формат подтверждён на реальной машине. Формат
может отличаться (суффиксы, регистр) — если автоопределение не
сработает, извлечённые значения стоит проверить вручную через
`python board_detect.py` и подправить функции normalize_* при необходимости.
"""

import re
import subprocess

# --- Определение вендора платы -------------------------------------------

# подстрока в Win32_BaseBoard.Manufacturer -> внутренний код вендора
VENDOR_SIGNATURES = {
    "MICRO-STAR": "msi",
    "MSI": "msi",
    "ASUSTEK": "asus",
    "GIGABYTE": "gigabyte",
    "ASROCK": "asrock",
}

# --- Известные чипсеты AMD/Intel и их сокет (для URL на amd.com и ASRock) -

AMD_CHIPSET_SOCKETS = {
    # AM5
    "X870E": "am5", "X870": "am5",
    "X670E": "am5", "X670": "am5",
    "B850": "am5", "B650E": "am5", "B650": "am5",
    "A620": "am5",
    # AM4 (легаси, на всякий случай)
    "X570": "am4", "X470": "am4", "X370": "am4",
    "B550": "am4", "B450": "am4", "B350": "am4",
    "A520": "am4", "A320": "am4",
}

# Intel — только для определения family="intel" у ASRock, без построения
# amd.com-специфичных URL (у Intel своя логика через Download Center)
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
    Возвращает {"manufacturer": ..., "product": ...} из Win32_BaseBoard,
    либо None, если не удалось получить (например, не Windows).
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
    """MSI/ASUS/Gigabyte/ASRock -> внутренний код вендора, иначе None."""
    manufacturer_upper = manufacturer.upper()
    for signature, vendor_code in VENDOR_SIGNATURES.items():
        if signature in manufacturer_upper:
            return vendor_code
    return None


def _hyphenate_product_name(product: str) -> str:
    """
    Общая логика для MSI и Gigabyte — оба используют slug вида
    "ИМЯ-ПЛАТЫ-ЧЕРЕЗ-ДЕФИСЫ" в верхнем регистре, без суффикса с кодом
    платы в скобках (например "(MS-7E51)").
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
    Общая логика для ASUS и ASRock — оба используют модель с пробелами
    как есть в URL, убираем только суффикс в скобках, если он есть.
    """
    return re.sub(r"\s*\([^)]*\)\s*$", "", product).strip()


def extract_asus_model(product: str) -> str:
    return _strip_suffix(product)


def extract_asrock_model(product: str) -> str:
    return _strip_suffix(product)


def extract_chipset_codename(product: str) -> str | None:
    """Ищет в имени платы известное название чипсета (X870, B650, ...)."""
    match = CHIPSET_CODENAME_REGEX.search(product.upper())
    return match.group(1) if match else None


def detect_chipset_family(chipset_codename: str | None) -> str:
    """AMD/Intel — нужно ASRock для сегмента пути /mb/<family>/... на сайте."""
    if chipset_codename in AMD_CHIPSET_SOCKETS:
        return "amd"
    if chipset_codename in INTEL_CHIPSET_CODENAMES:
        return "intel"
    return "amd"  # по умолчанию — самый частый случай


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
    Главная функция: возвращает всё, что удалось определить.
    {
        "vendor": "msi" | "asus" | "gigabyte" | "asrock" | None,
        "manufacturer_raw": str | None,
        "product_raw": str | None,
        "msi_slug": str | None,
        "gigabyte_slug": str | None,
        "asus_model": str | None,
        "asrock_model": str | None,
        "chipset_codename": str | None,   # например "X870"
        "chipset_family": str,            # "amd" | "intel"
        "amd_chipset_url": str | None,    # готовый URL для AmdChipsetProvider
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

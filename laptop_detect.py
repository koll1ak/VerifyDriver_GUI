"""
Определение ноутбука: тип корпуса, вендор/модель, Service Tag (для Dell),
серийник (для Lenovo — используется как productId в API pcsupport.lenovo.com).

Источники — WMI:
- Win32_SystemEnclosure.ChassisTypes — коды 8-14, 30-32 соответствуют
  портативным корпусам (ноутбук, планшет-трансформер и т.д.)
- Win32_ComputerSystem.Manufacturer/Model — вендор/модель системы в целом
  (не платы — на ноутбуках Win32_BaseBoard часто даёт мусор)
- Win32_BIOS.SerialNumber — на технике Dell это и есть Service Tag,
  уникальный 7-значный идентификатор конкретного устройства
"""

import subprocess
import json
import re

# коды корпусов, которые Windows/DMI считает портативными
LAPTOP_CHASSIS_TYPES = {"8", "9", "10", "11", "12", "14", "30", "31", "32"}


def is_laptop() -> bool | None:
    """True/False, либо None если не удалось определить."""
    ps_command = (
        "(Get-CimInstance Win32_SystemEnclosure).ChassisTypes | ConvertTo-Json"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_command],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        return None  # powershell недоступен (не Windows, ограничения и т.п.)

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
        "asus_laptop_model": None, "lenovo_serial": None,
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

    return {
        "manufacturer": manufacturer or None,
        "model": model or None,
        "dell_service_tag": serial if (is_dell and serial) else None,
        "acer_model_name": extract_acer_model_name(model) if (is_acer and model) else None,
        "acer_part_number": extract_acer_part_number(serial) if (is_acer and serial) else None,
        "acer_serial": serial if (is_acer and serial) else None,
        "asus_laptop_model": extract_asus_laptop_model(model) if (is_asus and model) else None,
        "lenovo_serial": serial if (is_lenovo and serial) else None,
    }


# известные линейки продуктов Acer — убираем префикс, чтобы получить
# именно ту часть, которую сайт acer.com использует как ModelName
# (например "Nitro AN515-55" -> "AN515-55")
ACER_PRODUCT_LINES = (
    "Predator", "Nitro", "Aspire", "Swift", "TravelMate",
    "Extensa", "ConceptD", "Spin", "Enduro", "Iconia", "Chromebook",
)
_ACER_PREFIX_RE = re.compile(
    r"^(?:" + "|".join(ACER_PRODUCT_LINES) + r")\s+", re.IGNORECASE
)


def extract_acer_model_name(model: str) -> str:
    """"Nitro AN515-55" -> "AN515-55" (убираем префикс линейки продукта)."""
    return _ACER_PREFIX_RE.sub("", model).strip()


def extract_acer_part_number(serial: str) -> str | None:
    """
    Номер детали Acer выводится прямо из первых 10 символов серийника:
    "NHQ7JEU00G0400B98F3400" -> "NH.Q7JEU.00G"
    (сегменты 2+5+3 символа, разделённые точками) — подтверждено на
    реальном устройстве (Acer Nitro AN515-55).
    """
    if not serial or len(serial) < 10:
        return None
    return f"{serial[0:2]}.{serial[2:7]}.{serial[7:10]}"


def extract_asus_laptop_model(model: str) -> str:
    """
    Win32_ComputerSystem.Model на ноутбуках ASUS обычно дублирует код
    модели через подчёркивание:
    "ASUS Vivobook S 16 S5606CA_S5606CA" -> "S5606CA"
    (подтверждено на реальном устройстве) — берём последний сегмент
    после "_"; если подчёркивания нет — используем строку как есть.
    """
    if "_" in model:
        return model.rsplit("_", 1)[-1].strip()
    return model.strip()


def detect_laptop() -> dict:
    """
    Главная функция.
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

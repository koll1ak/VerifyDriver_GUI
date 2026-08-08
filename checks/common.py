import sys
import re
from datetime import datetime

from net_utils import classify_error


def find_device(devices, predicate):
    """
    Возвращает первое устройство из списка, подходящее под predicate.
    predicate — либо объект с методом matches(device) (Provider), либо
    обычная функция device -> bool. Общий хелпер вместо повторяющегося
    "for device in devices: if ...matches(device): ..." в каждой проверке.
    """
    match_fn = predicate.matches if hasattr(predicate, "matches") else predicate
    for device in devices:
        if match_fn(device):
            return device
    return None


def safe_get_latest(label: str, provider, device=None):
    """
    Оборачивает provider.get_latest() — заменяет повторяющийся try/except
    в каждой check_*-функции. Если провайдер бросает исключение — пишет
    в stderr и возвращает (False, None) (сигнал молча пропустить проверку).
    Если отработал без ошибок (в том числе если сам провайдер честно не
    нашёл ничего и вернул None) — возвращает (True, latest); True здесь
    означает именно "выполнилось без сбоя", а не "что-то нашлось" — latest
    может быть None, и это нормально обрабатывается дальше через report().
    """
    try:
        latest = provider.get_latest(device) if device is not None else provider.get_latest()
    except Exception as e:
        print(f"[{label}] ошибка: {classify_error(e)}", file=sys.stderr)
        return False, None
    return True, latest


def find_device_driver_version(devices, vendor_id: str, name_keywords):
    """Ищет среди устройств совпадение по VendorID и подстроке в имени, возвращает DriverVersion."""
    device = find_device(
        devices,
        lambda d: d.get("VendorID") == vendor_id and any(
            kw in d.get("DeviceName", "").upper() for kw in name_keywords
        ),
    )
    return device.get("DriverVersion") if device else None


def laptop_model_if_vendor(laptop: dict, vendor_keyword: str, model_field: str):
    """
    Общий шаблон для vendor-специфичных проверок ноутбуков: если это
    ноутбук нужного вендора и модель определена — возвращает модель,
    иначе None (сигнал молча пропустить проверку).
    """
    if not laptop.get("is_laptop"):
        return None
    manufacturer = laptop.get("manufacturer") or ""
    if vendor_keyword not in manufacturer.upper():
        return None
    return laptop.get(model_field)


def overall_drivers_page_url(board: dict, laptop: dict) -> str | None:
    """
    Общая страница со всеми драйверами устройства целиком — ноутбука
    известного вендора (Acer/Dell) или материнской платы (MSI/Gigabyte/
    ASRock/ASUS) на десктопе. Полезно как единая ссылка для ручной
    проверки в конце прогона, отдельно от конкретных проверок по
    компонентам.
    """
    if laptop.get("is_laptop"):
        manufacturer = (laptop.get("manufacturer") or "").upper()

        if "ACER" in manufacturer and laptop.get("acer_model_name") and laptop.get("acer_part_number"):
            model = laptop["acer_model_name"]
            part_number = laptop["acer_part_number"]
            serial = laptop.get("acer_serial", "")
            return f"https://www.acer.com/us-en/support/product-support/{model}/{part_number}/downloads?sn={serial}"

        if "DELL" in manufacturer and laptop.get("dell_service_tag"):
            return f"https://www.dell.com/support/home/en-us/product-support/servicetag/{laptop['dell_service_tag']}/drivers"

        if "ASUS" in manufacturer and laptop.get("asus_laptop_model"):
            model = laptop["asus_laptop_model"].lower()
            return f"https://www.asus.com/us/supportonly/{model}/helpdesk_download/"

        return None

    # десктоп — страница материнской платы у соответствующего вендора
    vendor = board.get("vendor")

    if vendor == "msi" and board.get("msi_slug"):
        return f"https://www.msi.com/Motherboard/{board['msi_slug']}/support"

    if vendor == "gigabyte" and board.get("gigabyte_slug"):
        return f"https://www.gigabyte.com/Motherboard/{board['gigabyte_slug']}/support"

    if vendor == "asrock" and board.get("asrock_model"):
        family = board.get("chipset_family", "amd")
        return f"https://www.asrock.com/mb/{family}/{board['asrock_model']}/"

    if vendor == "asus" and board.get("asus_model"):
        from urllib.parse import quote
        return f"https://www.asus.com/us/supportonly/{quote(board['asus_model'].lower())}/helpdesk_download/"

    return None


def _parse_version_tuple(v: str):
    """Версия как тюпл чисел для численного сравнения (не строкового)."""
    try:
        return tuple(int(p) for p in v.split("."))
    except (ValueError, AttributeError):
        return None


def no_downgrade_match(current: str, latest: str) -> bool:
    """
    Считает версии "совпадающими" (не предлагать обновление), если
    установленная версия ЧИСЛЕННО не старше версии на сайте — то есть
    если сайт отстаёт от того, что уже реально стоит (типичная ситуация:
    OEM-страница обновляется реже, чем Windows Update/сам производитель
    чипа), мы никогда не порекомендуем "откатиться" на более старую версию.
    """
    if not current or not latest:
        return False
    current_t = _parse_version_tuple(current)
    latest_t = _parse_version_tuple(latest)
    if current_t is None or latest_t is None:
        return current == latest  # не смогли распарсить как числа — сравниваем как строки
    return current_t >= latest_t


def parse_flexible_date(raw: str):
    """
    Пытается распарсить дату в разных форматах, которые встречаются:
    - сайт Realtek: "2026/07/30"
    - WMI DriverDate (сырой CIM-формат): "20220516000000.000000-000"
    - WMI DriverDate (если PowerShell уже сконвертировал в ISO): "2022-05-16T00:00:00"
    - WMI DriverDate через ConvertTo-Json (ASP.NET-стиль, подтверждено на
      реальном устройстве): "/Date(1783123200000)/" — Unix-время в мс
    """
    if not raw:
        return None

    aspnet_match = re.match(r"/Date\((\d+)\)/", raw)
    if aspnet_match:
        try:
            from datetime import timezone
            return datetime.fromtimestamp(int(aspnet_match.group(1)) / 1000, tz=timezone.utc).replace(tzinfo=None)
        except (ValueError, OSError):
            return None

    for fmt in ("%Y/%m/%d", "%Y%m%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            # для WMI сырого формата берём только первые 8 символов (YYYYMMDD)
            candidate = raw[:8] if fmt == "%Y%m%d" else raw
            return datetime.strptime(candidate, fmt)
        except (ValueError, TypeError):
            continue
    return None


def report(label, latest, current, comparator=None):
    """
    Общая логика сравнения. Возвращает (display_line, update_line):
    display_line — строка статуса для показа в общем отчёте (всегда есть),
    update_line — строка для секции "Найдены обновления" (или None, если
    обновление не найдено/сверка невозможна). Не печатает сама — печать
    делает main() после того, как все параллельные проверки завершатся,
    в фиксированном порядке по категориям.
    """
    if latest is None:
        return f"[{label}] не удалось найти актуальную версию на сайте", None

    if current is None:
        return f"[{label}] на сайте: {latest['version']} (установленную версию сверить не удалось)", None

    is_match = comparator(current, latest["version"]) if comparator else (current == latest["version"])

    if is_match:
        return f"[{label}] актуально ({latest['version']})", None

    display_url = latest.get("page_url") or latest.get("url", "")
    update_line = f"{label}: установлено {current} -> доступно {latest['version']} ({display_url})"
    return f"[{label}] ОБНОВЛЕНИЕ ДОСТУПНО: {current} -> {latest['version']}", update_line

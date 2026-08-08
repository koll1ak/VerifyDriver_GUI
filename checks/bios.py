import sys

from net_utils import classify_error
from checks.common import report
from providers.msi_bios import MsiBiosProvider, get_current_bios_version
from providers.gigabyte_bios import GigabyteBiosProvider
from providers.asrock_bios import AsrockBiosProvider
from providers.asus_bios import AsusBiosProvider


def _asus_desktop_bios_versions_match(current: str, latest: str) -> bool:
    """
    Для десктопных плат ASUS версия и на сайте, и в Windows — простое
    число без префиксов (например "2403" установлено, "3004" на сайте),
    в отличие от ноутбуков ASUS (там версия с префиксом модели платы).
    Подтверждено на реальном устройстве.
    """
    if not current or not latest:
        return False
    try:
        return int(current.strip()) == int(latest.strip())
    except ValueError:
        return current.strip() == latest.strip()


def _bios_versions_match(current: str, latest: str) -> bool:
    """
    Windows возвращает версию BIOS в укороченном виде (например "1.A92"),
    а сайт MSI — полный код с моделью платы (например "7E51v1A92").
    Сравниваем "хвост" после 'v' у сайта с версией из Windows без точек.
    """
    if not current or not latest:
        return False
    tail = latest.split("v")[-1] if "v" in latest else latest
    return current.replace(".", "").upper() == tail.replace(".", "").upper()


def check_bios(devices, board, laptop):
    # на ноутбуках Win32_BaseBoard часто даёт мусор вместо реального вендора
    # платы (например кодовое имя референсной платформы) — реальный BIOS
    # для ноутбуков покрывают отдельные vendor-специфичные проверки
    # (check_dell_bios, check_acer_bios и т.д.), эта функция для десктопов
    if laptop.get("is_laptop"):
        return None

    vendor = board.get("vendor")

    if vendor == "msi":
        slug = board.get("msi_slug")
        if slug is None:
            print("[BIOS] MSI: не удалось определить модель платы", file=sys.stderr)
            return None
        try:
            latest = MsiBiosProvider(product_slug=slug).get_latest()
        except Exception as e:
            print(f"[BIOS] ошибка (MSI): {classify_error(e)}", file=sys.stderr)
            return None
        return report("BIOS", latest, get_current_bios_version(), comparator=_bios_versions_match)

    if vendor == "gigabyte":
        slug = board.get("gigabyte_slug")
        if slug is None:
            print("[BIOS] Gigabyte: не удалось определить модель платы", file=sys.stderr)
            return None
        try:
            latest = GigabyteBiosProvider(product_slug=slug).get_latest()
        except Exception as e:
            print(f"[BIOS] ошибка (Gigabyte): {classify_error(e)}", file=sys.stderr)
            return None
        # надёжного способа сверить с установленной версией пока нет
        # (Windows не даёт единый BIOS-код в предсказуемом формате для Gigabyte)
        return report("BIOS", latest, current=None)

    if vendor == "asrock":
        model = board.get("asrock_model")
        if model is None:
            print("[BIOS] ASRock: не удалось определить модель платы", file=sys.stderr)
            return None
        try:
            latest = AsrockBiosProvider(model=model, family=board.get("chipset_family", "amd")).get_latest()
        except Exception as e:
            print(f"[BIOS] ошибка (ASRock): {classify_error(e)}", file=sys.stderr)
            return None
        return report("BIOS", latest, current=None)

    if vendor == "asus":
        model = board.get("asus_model")
        if model is None:
            print("[BIOS] ASUS: не удалось определить модель платы", file=sys.stderr)
            return None
        try:
            latest = AsusBiosProvider(model=model).get_latest()
        except Exception as e:
            print(f"[BIOS] ошибка (ASUS): {classify_error(e)}", file=sys.stderr)
            return None
        return report("BIOS", latest, get_current_bios_version(), comparator=_asus_desktop_bios_versions_match)

    print(f"[BIOS] вендор платы не распознан (manufacturer: {board.get('manufacturer_raw')})", file=sys.stderr)
    return None

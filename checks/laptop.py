import sys

from net_utils import classify_error
from scanner import get_devices_by_id_pattern
from checks.common import (
    find_device, find_device_driver_version, laptop_model_if_vendor, safe_get_latest, report, no_downgrade_match,
)
from providers.dell_support import DellSupportProvider
from providers.acer_support import AcerSupportProvider
from providers.huawei_support import huawei_search_url
from providers.lenovo_support import LenovoSupportProvider
from providers.msi_bios import get_current_bios_version
from providers.asus_bios import AsusBiosProvider
from providers.asus_laptop_driver import AsusLaptopDriverProvider


def _asus_laptop_bios_versions_match(current: str, latest: str) -> bool:
    """
    Windows отдаёт версию BIOS ASUS-ноутбука с префиксом кода модели
    (например "S5606CA.312"), сайт — только номер сборки ("313" или "312").
    Берём хвост после последней точки у установленной версии и сравниваем
    с версией сайта напрямую.
    """
    if not current or not latest:
        return False
    current_tail = current.split(".")[-1].strip()
    return current_tail == latest.strip()


def _acer_bios_versions_match(current: str, latest: str) -> bool:
    """
    Windows отдаёт версию BIOS Acer с префиксом "V" (например "V2.06"),
    сайт — без него ("2.06") — убираем префикс с обеих сторон перед сравнением.
    """
    if not current or not latest:
        return False
    strip_v = lambda s: s.upper().lstrip("V")
    return strip_v(current) == strip_v(latest)


def _acer_lan_versions_match(current: str, latest: str) -> bool:
    """
    Сайт даёт версию с ведущим нулём в одном из сегментов (например
    "10.038.1118.2019"), Windows — без него ("10.38.1118.2019") — убираем
    ведущие нули в каждом сегменте перед сравнением.
    """
    if not current or not latest:
        return False

    def _norm(v: str) -> str:
        try:
            return ".".join(str(int(p)) for p in v.split("."))
        except ValueError:
            return v

    return _norm(current) == _norm(latest)


def check_dell_bios(devices, board, laptop):
    """
    Только для Dell-ноутбуков (определяется независимо от board_detect.py,
    который заточен под десктопные платы) — по Service Tag устройства.
    НЕ ПРОВЕРЕНО на реальном устройстве, см. providers/dell_support.py.
    """
    tag = laptop_model_if_vendor(laptop, "DELL", "dell_service_tag")
    if tag is None:
        return None

    provider = DellSupportProvider(service_tag=tag, category="BIOS", name="dell_bios")
    ok, latest = safe_get_latest("Dell BIOS", provider)
    if not ok:
        return None
    # сверки с установленной версией нет — не проверено, какой формат
    # версии реально отдаёт Windows для Dell BIOS в сравнении с сайтом
    return report("Dell BIOS", latest, current=None)


def check_dell_audio(devices, board, laptop):
    """Аналогично check_dell_bios, но категория Audio."""
    tag = laptop_model_if_vendor(laptop, "DELL", "dell_service_tag")
    if tag is None:
        return None

    provider = DellSupportProvider(service_tag=tag, category="Audio", name="dell_audio")
    ok, latest = safe_get_latest("Dell Audio", provider)
    if not ok:
        return None
    return report("Dell Audio", latest, current=None)


def check_acer_bios(devices, board, laptop):
    """
    Только для Acer-ноутбуков — по ModelName (Win32_ComputerSystem.Model
    без префикса линейки продукта). Структура API проверена на реальных
    данных (Acer Nitro AN515-55) — надёжность как у десктопных провайдеров.
    """
    model_name = laptop_model_if_vendor(laptop, "ACER", "acer_model_name")
    if model_name is None:
        return None

    provider = AcerSupportProvider(
        model_name=model_name, category="BIOS",
        part_number=laptop.get("acer_part_number"), serial=laptop.get("acer_serial"),
        name="acer_bios",
    )
    ok, latest = safe_get_latest("Acer BIOS", provider)
    if not ok:
        return None
    # версия BIOS у Acer в простом формате ("2.06"), без привязки к модели
    # платы (в отличие от MSI) — но Windows добавляет префикс "V" (V2.06),
    # которого нет на сайте, поэтому сравниваем через отдельный компаратор
    return report("Acer BIOS", latest, get_current_bios_version(), comparator=_acer_bios_versions_match)


def check_acer_audio(devices, board, laptop):
    """Аналогично check_acer_bios, но категория Audio (с фильтром по ОС)."""
    model_name = laptop_model_if_vendor(laptop, "ACER", "acer_model_name")
    if model_name is None:
        return None

    provider = AcerSupportProvider(
        model_name=model_name, category="Audio",
        part_number=laptop.get("acer_part_number"), serial=laptop.get("acer_serial"),
        name="acer_audio",
    )
    ok, latest = safe_get_latest("Acer Audio", provider)
    if not ok:
        return None
    # пробуем сверить с установленной версией — если реально стоит
    # фирменный Realtek-драйвер (не общий Windows-драйвер), версии могут
    # совпасть напрямую (формат вида "6.0.9180.1" похож на то, что
    # показывает Windows для установленного Realtek-пакета)
    current = find_device_driver_version(devices, "10EC", ("AUDIO",)) or \
        find_device_driver_version(devices, "0BDA", ("AUDIO",))

    if current is None:
        # Win32_PnPSignedDriver иногда не видит аудио-устройство (как и на
        # десктопе с USB-кодеком) — резервный поиск через Get-PnpDevice
        try:
            fallback_devices = get_devices_by_id_pattern("VEN_10EC")
        except Exception as e:
            print(f"[Acer Audio] ошибка резервного поиска: {classify_error(e)}", file=sys.stderr)
            fallback_devices = []
        audio_device = find_device(fallback_devices, lambda d: "AUDIO" in d.get("DeviceName", "").upper())
        current = audio_device.get("DriverVersion") if audio_device else None

    if latest and latest.get("os_mismatch"):
        # для установленной ОС в каталоге Acer нет отдельной записи —
        # показываем найденное, но не утверждаем "обновление доступно",
        # раз не уверены, что версия реально предназначена для этой ОС
        return f"[Acer Audio] на сайте (другая ОС в каталоге): {latest['version']} — сверка ненадёжна", None

    return report("Acer Audio", latest, current)


def check_acer_lan(devices, board, laptop):
    """Аналогично check_acer_audio, но категория Lan."""
    model_name = laptop_model_if_vendor(laptop, "ACER", "acer_model_name")
    if model_name is None:
        return None

    # если сетевой чип — Realtek или Intel, эти уже покрыты официальными
    # проверками (check_realtek_lan / check_intel_lan) — не дублируем и
    # не подсовываем версию с переупакованной страницы Acer вместо
    # официального источника вендора чипа
    has_realtek_lan = find_device(
        devices, lambda d: d.get("VendorID") == "10EC" and "FAMILY CONTROLLER" in d.get("DeviceName", "").upper()
    ) is not None
    has_intel_lan = find_device_driver_version(
        devices, "8086", ("ETHERNET", "I219", "I225", "I226", "I210", "I350")
    ) is not None
    if has_realtek_lan or has_intel_lan:
        return None

    provider = AcerSupportProvider(
        model_name=model_name, category="Lan",
        part_number=laptop.get("acer_part_number"), serial=laptop.get("acer_serial"),
        name="acer_lan",
    )
    ok, latest = safe_get_latest("Acer LAN", provider)
    if not ok:
        return None

    # ищем сетевой адаптер — Killer/Realtek/Intel, у Acer это чаще всего
    # Killer (иногда на деле переброшенный Realtek-чип под их брендом)
    current = find_device_driver_version(devices, "10EC", ("ETHERNET", "GIGABIT", "KILLER")) or \
        find_device_driver_version(devices, "8086", ("ETHERNET", "I219", "I225", "I226"))

    if current is None:
        # тот же резервный путь, что и для аудио — на случай, если
        # Win32_PnPSignedDriver не видит устройство напрямую
        try:
            fallback_devices = get_devices_by_id_pattern("VEN_10EC")
        except Exception as e:
            print(f"[Acer LAN] ошибка резервного поиска: {classify_error(e)}", file=sys.stderr)
            fallback_devices = []
        lan_device = find_device(
            fallback_devices,
            lambda d: any(kw in d.get("DeviceName", "").upper() for kw in ("ETHERNET", "GIGABIT", "KILLER")),
        )
        current = lan_device.get("DriverVersion") if lan_device else None

    if latest and latest.get("os_mismatch"):
        return f"[Acer LAN] на сайте (другая ОС в каталоге): {latest['version']} — сверка ненадёжна", None

    return report("Acer LAN", latest, current, comparator=_acer_lan_versions_match)


def check_asus_laptop_bios(devices, board, laptop):
    """
    ASUS-ноутбук — переиспользует тот же AsusBiosProvider, что и для
    десктопных плат ASUS (одна и та же структура сайта/страницы), только
    модель берётся из Win32_ComputerSystem.Model, а не Win32_BaseBoard.
    """
    model = laptop_model_if_vendor(laptop, "ASUS", "asus_laptop_model")
    if model is None:
        return None

    ok, latest = safe_get_latest("ASUS BIOS", AsusBiosProvider(model=model))
    if not ok:
        return None
    # пробуем сверить напрямую — формат для ASUS не проверен, если не
    # совпадёт, разберёмся по реальным данным (как с Acer/MSI ранее)
    return report("ASUS BIOS", latest, get_current_bios_version(), comparator=_asus_laptop_bios_versions_match)


def check_asus_laptop_audio(devices, board, laptop):
    """Аналогично check_asus_laptop_bios, но категория Audio (Realtek) —
    через официальный JSON API (providers/asus_laptop_driver.py), т.к.
    страница ноутбука подгружает список драйверов через JS, а не отдаёт
    его сразу в HTML (в отличие от страницы BIOS)."""
    model = laptop_model_if_vendor(laptop, "ASUS", "asus_laptop_model")
    if model is None:
        return None

    provider = AsusLaptopDriverProvider(model=model, category="Audio", match_substrings=("Realtek",), name="asus_laptop_audio")
    ok, latest = safe_get_latest("ASUS Audio", provider)
    if not ok:
        return None
    if latest is None:
        return None

    current = find_device_driver_version(devices, "10EC", ("AUDIO",)) or \
        find_device_driver_version(devices, "0BDA", ("AUDIO",))

    if current is None:
        try:
            fallback_devices = get_devices_by_id_pattern("VEN_10EC")
        except Exception as e:
            print(f"[ASUS Audio] ошибка резервного поиска: {classify_error(e)}", file=sys.stderr)
            fallback_devices = []
        audio_device = find_device(fallback_devices, lambda d: "AUDIO" in d.get("DeviceName", "").upper())
        current = audio_device.get("DriverVersion") if audio_device else None

    return report("ASUS Audio", latest, current)


def check_asus_laptop_networking(devices, board, laptop):
    """
    Категория "Networking" у ASUS объединяет WiFi/Bluetooth/LAN вместе.
    Если WiFi-чип — Intel, эту проверку пропускаем целиком: официальная
    страница Intel надёжнее и точнее переупакованной версии от ASUS
    (проверено на практике — ASUS-страница отставала от Intel), и
    check_intel_wifi уже её покрывает. Проверяем через ASUS только когда
    WiFi-чип НЕ Intel (MediaTek/Realtek/Killer и т.п.), для которых у нас
    нет отдельного прямого источника.
    """
    model = laptop_model_if_vendor(laptop, "ASUS", "asus_laptop_model")
    if model is None:
        return None

    has_any_wifi = find_device(
        devices, lambda d: any(kw in d.get("DeviceName", "").upper() for kw in ("WI-FI", "WIRELESS", "WLAN"))
    ) is not None
    has_realtek_lan = find_device(
        devices, lambda d: d.get("VendorID") == "10EC" and "FAMILY CONTROLLER" in d.get("DeviceName", "").upper()
    ) is not None
    if has_any_wifi or has_realtek_lan:
        return None  # уже покрыто check_intel_wifi/check_wifi_via_windows_update/check_realtek_lan

    provider = AsusLaptopDriverProvider(
        model=model, category="Networking", match_substrings=(), name="asus_laptop_networking"
    )
    ok, latest = safe_get_latest("ASUS Networking", provider)
    if not ok:
        return None
    if latest is None:
        return None

    current = find_device_driver_version(devices, "8086", ("WI-FI",))
    return report("ASUS Networking", latest, current, comparator=no_downgrade_match)


def check_huawei_bios(devices, board, laptop):
    """
    Для BIOS ноутбуков Huawei нет официального источника по производителю
    чипа (в отличие от компонентов вроде WiFi/Chipset — BIOS всегда пишет
    именно вендор ноутбука, а не Intel/Realtek) — просто даём ссылку на
    поиск по сайту Huawei для ручной проверки, без автоматической сверки.
    """
    if not laptop.get("is_laptop") or "HUAWEI" not in (laptop.get("manufacturer") or "").upper():
        return None

    url = huawei_search_url(laptop.get("model"))
    if url is None:
        return None
    return f"[Huawei BIOS] автоматическая проверка недоступна — посети сайт вручную: {url}", None


def check_lenovo_bios(devices, board, laptop):
    """
    Только для ноутбуков Lenovo — двухшаговое разрешение через API
    pcsupport.lenovo.com (серийник -> slug продукта -> список драйверов,
    см. providers/lenovo_support.py). НЕ ПРОВЕРЕНО на реальном устройстве.
    """
    serial = laptop_model_if_vendor(laptop, "LENOVO", "lenovo_serial")
    if serial is None:
        return None

    provider = LenovoSupportProvider(serial=serial, category="BIOS", name="lenovo_bios")
    ok, latest = safe_get_latest("Lenovo BIOS", provider)
    if not ok:
        return None
    # сверки с установленной версией нет — не проверено, какой формат
    # версии реально отдаёт Windows для Lenovo BIOS в сравнении с сайтом
    return report("Lenovo BIOS", latest, current=None)


def check_lenovo_audio(devices, board, laptop):
    """Аналогично check_lenovo_bios, но категория Audio."""
    serial = laptop_model_if_vendor(laptop, "LENOVO", "lenovo_serial")
    if serial is None:
        return None

    provider = LenovoSupportProvider(serial=serial, category="Audio", name="lenovo_audio")
    ok, latest = safe_get_latest("Lenovo Audio", provider)
    if not ok:
        return None
    return report("Lenovo Audio", latest, current=None)

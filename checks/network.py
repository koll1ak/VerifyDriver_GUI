from checks.common import find_device, find_device_driver_version, safe_get_latest, report, parse_flexible_date, no_downgrade_match
from providers.realtek_lan import (
    RealtekLanProvider, realtek_versions_match, realtek_ndis_versions_match, detect_realtek_lan_variant,
)
from providers.realtek_wifi import RealtekWifiProvider
from providers.realtek_usb_lan import RealtekUsbLanProvider
from providers.intel_download import IntelDownloadCenterProvider
from providers.ms_catalog import MsCatalogProvider

INTEL_LAN_DOWNLOAD_ID = "15084"
INTEL_LAN_SLUG = "intel-ethernet-adapter-complete-driver-pack"

INTEL_WIFI_DOWNLOAD_ID = "19351"
INTEL_WIFI_SLUG = "intel-wireless-wi-fi-drivers-for-windows-10-and-windows-11"

INTEL_BLUETOOTH_DOWNLOAD_ID = "18649"
INTEL_BLUETOOTH_SLUG = "intel-wireless-bluetooth-drivers-for-windows-10-and-windows-11"


def check_realtek_lan(devices, board, laptop):
    provider_finder = RealtekLanProvider()  # только для matches(), не для get_latest()
    device = find_device(devices, provider_finder)
    if device is None:
        return None  # Realtek-сетевой карты нет в системе — молча пропускаем, на сайт не идём

    current = device.get("DriverVersion")
    variant = detect_realtek_lan_variant(current)

    # выбираем ТОТ ЖЕ вариант драйвера на сайте (NDIS/NetAdapterCx), что
    # реально установлен — раньше здесь всегда бралась только версия
    # NetAdapterCx, даже если на машине стоит NDIS (или наоборот), из-за
    # чего сравнение было в принципе бессмысленным (сравнивали два разных
    # драйверных фреймворка с разной нумерацией). Оба варианта
    # подтверждены на реальных устройствах.
    if variant == "ndis":
        match_substrings = ("NDIS", "Not Support Power Saving")
        comparator = realtek_ndis_versions_match
    else:  # netadaptercx или unknown — используем NetAdapterCx как и раньше
        match_substrings = ("NetAdapterCx", "Not Support Power Saving")
        comparator = realtek_versions_match

    provider = RealtekLanProvider(match_substrings=match_substrings)
    ok, latest = safe_get_latest("Realtek LAN", provider)
    if not ok:
        return None

    if variant == "unknown":
        # неопознанный формат (например старые 1GbE-чипы, где версия
        # оканчивается на год, а не build-номер) — сравнивать номера
        # версий напрямую небезопасно; запасной путь — по ДАТЕ, она есть
        # в обеих системах и не зависит от особенностей нумерации
        # конкретного поколения чипа.
        # ВАЖНО: ссылка на скачивание в этом случае берётся из варианта
        # NetAdapterCx (используем как справочную точку для даты) — но
        # для старых чипов с легаси-нумерацией версии этот конкретный
        # файл МОЖЕТ ОКАЗАТЬСЯ НЕСОВМЕСТИМЫМ (подтверждено на практике:
        # установка не поменяла версию даже после чистой переустановки
        # и перезагрузки) — не факт, что это правильный пакет для чипа.
        installed_date = parse_flexible_date(device.get("DriverDate", ""))
        site_date = parse_flexible_date(latest.get("date", "")) if latest else None
        if installed_date and site_date:
            if (site_date - installed_date).days > 60:  # порог, чтобы не шуметь на мелких расхождениях
                display = (
                    f"[Realtek LAN] возможно устарел (по дате, не по версии — сверка ненадёжна для "
                    f"этого чипа): драйвер от {installed_date.date()}, на сайте есть от {site_date.date()}"
                )
                update_line = (
                    f"Realtek LAN: возможно устарел — драйвер от {installed_date.date()}, "
                    f"на сайте LAN-категория целиком: https://www.realtek.com/Download/List?cate_id=584 "
                    f"(автовыбранный файл может не подойти именно этому чипу — выбери вариант вручную)"
                )
                return display, update_line
            return f"[Realtek LAN] актуально по дате (драйвер от {installed_date.date()})", None
        current = None  # не удалось сверить ни по версии, ни по дате

    return report("Realtek LAN", latest, current, comparator=comparator)


def check_realtek_wifi(devices, board, laptop):
    """
    Realtek WLAN-чипы (RTL8723/RTL8821/RTL8822 и т.п.) — отдельная
    категория на сайте Realtek (cate_id=673). Автоматическую сверку версий
    пока не делаем (current=None) — не подтверждено реальными данными, что
    формат версии Windows сопоставим с версией сайта (как это было
    выведено для LAN на конкретном чипе).
    """
    provider = RealtekWifiProvider()
    device = find_device(devices, provider)
    if device is None:
        return None

    ok, latest = safe_get_latest("Realtek WiFi", provider)
    if not ok:
        return None
    return report("Realtek WiFi", latest, current=None)


def check_realtek_usb_lan(devices, board, laptop):
    """
    Внешние USB-адаптеры/докстанции Ethernet от Realtek — отдельная
    категория (cate_id=585) от встроенных PCIe-чипов. Тоже без
    автоматической сверки версий (см. check_realtek_wifi).
    """
    provider = RealtekUsbLanProvider()
    device = find_device(devices, provider)
    if device is None:
        return None

    ok, latest = safe_get_latest("Realtek USB LAN", provider)
    if not ok:
        return None
    return report("Realtek USB LAN", latest, current=None)


def check_intel_lan(devices, board, laptop):
    current = find_device_driver_version(
        devices, "8086", ("ETHERNET", "I219", "I225", "I226", "I210", "I350")
    )
    if current is None:
        return None  # Intel-сетевой карты нет в системе — молча пропускаем

    provider = IntelDownloadCenterProvider(
        download_id=INTEL_LAN_DOWNLOAD_ID, slug=INTEL_LAN_SLUG, name="intel_lan"
    )
    ok, latest = safe_get_latest("Intel LAN", provider)
    if not ok:
        return None
    # "Complete Driver Pack" — общий пакет под все модели, версия пакета
    # не всегда 1:1 совпадает с версией конкретного установленного драйвера
    return report("Intel LAN", latest, current=None)


def check_intel_wifi(devices, board, laptop):
    current = find_device_driver_version(devices, "8086", ("WI-FI", "WIRELESS"))
    if current is None:
        return None  # Intel-WiFi карты нет в системе — молча пропускаем

    provider = IntelDownloadCenterProvider(
        download_id=INTEL_WIFI_DOWNLOAD_ID, slug=INTEL_WIFI_SLUG, name="intel_wifi"
    )
    ok, latest = safe_get_latest("Intel WiFi", provider)
    if not ok:
        return None
    # официальная страница Intel надёжнее переупакованной версии от вендора
    # ноутбука — но всё равно не предлагаем "откат", если уже стоит версия
    # новее той, что показывает сайт (бывает, что сайт просто не успел
    # обновиться)
    return report("Intel WiFi", latest, current, comparator=no_downgrade_match)


def check_intel_bluetooth(devices, board, laptop):
    # ВАЖНО: Intel Bluetooth-устройства в Windows числятся под ДРУГИМ
    # PCI/USB Vendor ID — 8087, а не 8086 (тот используется для WiFi/
    # чипсета/GPU) — подтверждено на реальном устройстве.
    current = find_device_driver_version(devices, "8087", ("BLUETOOTH",))
    if current is None:
        return None  # Intel Bluetooth-модуля нет в системе — молча пропускаем

    provider = IntelDownloadCenterProvider(
        download_id=INTEL_BLUETOOTH_DOWNLOAD_ID, slug=INTEL_BLUETOOTH_SLUG, name="intel_bluetooth"
    )
    ok, latest = safe_get_latest("Intel Bluetooth", provider)
    if not ok:
        return None
    return report("Intel Bluetooth", latest, current, comparator=no_downgrade_match)


def check_bluetooth_via_windows_update(devices, board, laptop):
    """
    Для Bluetooth-модулей НЕ Intel (Qualcomm, MediaTek и т.п.) — та же
    логика, что и для WiFi (check_wifi_via_windows_update): у большинства
    таких вендоров нет отдельной официальной страницы загрузок, поэтому
    единственный официальный источник — Microsoft Update Catalog.
    """
    bt_device = find_device(
        devices,
        lambda d: d.get("VendorID") not in ("8086", "8087") and "BLUETOOTH" in d.get("DeviceName", "").upper(),
    )
    if bt_device is None:
        return None  # Intel уже покрыт check_intel_bluetooth, других Bluetooth-модулей нет

    device_name = bt_device.get("DeviceName", "")
    current = bt_device.get("DriverVersion")

    provider = MsCatalogProvider(query=device_name, name="bluetooth_windows_update")
    ok, latest = safe_get_latest("Bluetooth ({device_name})", provider)
    if not ok:
        return None
    if latest is None:
        return None

    # поиск по строке названия устройства не гарантирует идеальное
    # совпадение варианта (см. историю с MediaTek WiFi выше) — не
    # предлагаем "откат"
    return report(f"Bluetooth ({device_name})", latest, current, comparator=no_downgrade_match)


def check_wifi_via_windows_update(devices, board, laptop):
    """
    Для WiFi-чипов НЕ Intel (Qualcomm, некоторые MediaTek и т.д.), у которых
    нет отдельной официальной страницы загрузок производителя — драйверы
    распространяются только через Windows Update. Единственный официальный
    источник в этом случае — Microsoft Update Catalog, ищем по точному
    имени устройства из Windows.
    """
    wifi_device = find_device(
        devices,
        lambda d: d.get("VendorID") not in ("8086", "8087", "10EC")
        and "BLUETOOTH" not in d.get("DeviceName", "").upper()  # "Wireless" совпадает и с Bluetooth-устройствами
        and any(kw in d.get("DeviceName", "").upper() for kw in ("WI-FI", "WIRELESS", "WLAN")),
    )
    if wifi_device is None:
        return None  # Intel уже покрыт check_intel_wifi, других WiFi-чипов нет

    device_name = wifi_device.get("DeviceName", "")
    current = wifi_device.get("DriverVersion")

    provider = MsCatalogProvider(query=device_name, name="wifi_windows_update")
    ok, latest = safe_get_latest("WiFi (Windows Update)", provider)
    if not ok:
        return None
    if latest is None:
        return None

    # поиск по строке названия устройства не гарантирует идеальное
    # совпадение варианта — как и с OEM-страницами, не предлагаем "откат"
    return report(f"WiFi ({device_name})", latest, current, comparator=no_downgrade_match)

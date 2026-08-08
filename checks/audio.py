import sys

from net_utils import classify_error
from scanner import get_devices_by_id_pattern
from checks.common import find_device, safe_get_latest, report, no_downgrade_match
from providers.msi_driver import MsiDriverProvider, get_installed_inf_version
from providers.gigabyte_driver import GigabyteDriverProvider
from providers.asrock_driver import AsrockDriverProvider
from providers.asus_driver import AsusDriverProvider
from providers.senary_audio import SenaryAudioProvider
from providers.ms_catalog import MsCatalogProvider


def _find_audio_device(devices):
    """
    Ищет аудио-кодек (обычно Realtek, VendorID 10EC — классика PCI/HDAUDIO,
    0BDA — новые кодеки вроде ALC4080 через встроенный USB-интерфейс).
    """
    audio_device = find_device(
        devices,
        lambda d: d.get("VendorID") in ("10EC", "0BDA") and "AUDIO" in d.get("DeviceName", "").upper(),
    )
    if audio_device is None:
        # Win32_PnPSignedDriver иногда не видит аудио-функцию составного
        # USB-устройства (как в случае Realtek USB2.0 Audio, ALC4080) —
        # пробуем резервный поиск через Get-PnpDevice по Vendor ID Realtek
        try:
            fallback_devices = get_devices_by_id_pattern("VID_0BDA")
        except Exception as e:
            print(f"[Audio] ошибка резервного поиска: {classify_error(e)}", file=sys.stderr)
            fallback_devices = []
        audio_device = find_device(fallback_devices, lambda d: "AUDIO" in d.get("DeviceName", "").upper())
    return audio_device


def _check_audio_via_windows_update(devices):
    """
    Запасной путь, когда плата не от одного из известных вендоров
    (MSI/Gigabyte/ASRock/ASUS) или на её странице нет категории Audio.
    Раньше здесь был сайт Realtek — убрали: последнее обновление там было
    ещё в 2022 году, источник не годится для актуальной проверки. Вместо
    него — Microsoft Update Catalog: WHQL-сборки, которые Realtek сама
    сдаёт в Windows Update, реально обновляются.
    """
    audio_device = _find_audio_device(devices)
    if audio_device is None:
        return None  # аудио-кодека нет в системе — молча пропускаем

    device_name = audio_device.get("DeviceName", "")
    current = audio_device.get("DriverVersion")

    provider = MsCatalogProvider(query=device_name, name="audio_windows_update")
    ok, latest = safe_get_latest(f"Audio ({device_name})", provider)
    if not ok:
        return None
    if latest is None:
        return None

    # поиск по строке названия устройства не гарантирует идеальное
    # совпадение варианта — как и с WiFi/Bluetooth через Windows Update,
    # не предлагаем "откат"
    return report(f"Audio ({device_name})", latest, current, comparator=no_downgrade_match)


def _check_vendor_audio_driver(board, vendor, slug_field, provider_factory, label, current_version_getter=None):
    """
    Общий шаблон для vendor-специфичных аудио-драйверов десктопных плат
    (MSI/Gigabyte/ASRock/ASUS) — отличаются только классом провайдера,
    полем со slug/model в board и (только у MSI) способом получить
    установленную версию для сравнения.

    Возвращает (found, result):
      found — True, если проверка вообще применима и что-то нашла на сайте
              (независимо от того, есть обновление или всё актуально) —
              используется, чтобы решить, нужен ли ещё и generic-Realtek;
      result — (display, update) кортеж от report(), либо None.
    """
    if board.get("vendor") != vendor:
        return False, None

    slug = board.get(slug_field)
    if slug is None:
        return False, None

    provider = provider_factory(slug)
    ok, latest = safe_get_latest(label, provider)
    if not ok:
        return False, None
    if latest is None:
        return False, None  # категория "Audio" не найдена на странице этой платы

    current = current_version_getter() if current_version_getter else None
    return True, report(label, latest, current)


def check_audio(devices, board, laptop):
    """
    Драйвер, кастомизированный под конкретного вендора платы (MSI/Gigabyte/
    ASRock/ASUS), приоритетнее — он точнее отражает то, что реально должно
    быть установлено на конкретной плате. Windows Update как запасной путь
    проверяем только если ни один vendor-специфичный путь не применим
    (плата не от одного из этих четырёх вендоров) или на сайте вендора не
    нашлось ничего под категорией аудио.

    На ноутбуке эта функция не должна запускаться вообще: Win32_BaseBoard
    (на который завязано определение вендора десктопной платы) на
    ноутбуках часто даёт мусор — а у некоторых вендоров (например ASUS)
    Manufacturer совпадает что у десктопных плат, что у ноутбуков, из-за
    чего можно случайно попасть по неправильной модели или задублировать
    вывод с check_acer_audio/check_asus_laptop_audio/check_dell_audio.
    Реальные vendor-специфичные проверки для ноутбуков — отдельные функции.
    """
    if laptop.get("is_laptop"):
        return None

    vendor_configs = [
        dict(
            vendor="msi", slug_field="msi_slug", label="MSI Audio Driver",
            provider_factory=lambda slug: MsiDriverProvider(
                product_slug=slug, category_keyword="AUDIO", name="msi_audio"
            ),
            # версия драйвера конкретного устройства (через сканер) — версия
            # активного класс-драйвера Windows, не версия пакета в Driver Store.
            # Реальную версию установленного пакета MSI/Realtek берём отдельно —
            # "rtdusbad" — стабильная часть имени INF для Realtek USB Audio на MSI платах
            current_version_getter=lambda: get_installed_inf_version("rtdusbad"),
        ),
        dict(
            vendor="gigabyte", slug_field="gigabyte_slug", label="Gigabyte Audio Driver",
            provider_factory=lambda slug: GigabyteDriverProvider(
                product_slug=slug, match_substrings=("Realtek", "Audio"), name="gigabyte_audio"
            ),
            current_version_getter=None,  # надёжного способа сверить нет, не проверено на реальных данных
        ),
        dict(
            vendor="asrock", slug_field="asrock_model", label="ASRock Audio Driver",
            provider_factory=lambda model: AsrockDriverProvider(
                model=model, match_substrings=("Realtek", "Audio"),
                family=board.get("chipset_family", "amd"), name="asrock_audio",
            ),
            current_version_getter=None,
        ),
        dict(
            vendor="asus", slug_field="asus_model", label="ASUS Audio Driver",
            provider_factory=lambda model: AsusDriverProvider(
                model=model, match_substrings=("Realtek", "Audio"), name="asus_audio"
            ),
            current_version_getter=None,
        ),
    ]

    for cfg in vendor_configs:
        found, result = _check_vendor_audio_driver(board, **cfg)
        if found:
            return result
    return _check_audio_via_windows_update(devices)


def check_senary_audio(devices, board, laptop):
    """
    SenaryTech (китайский производитель аудио-кодеков, альтернатива
    Realtek) — встречается на некоторых ультратонких ноутбуках, включая
    отдельные модели Huawei. Vendor ID 14F1 подтверждён на реальном
    устройстве. Работает независимо от типа системы — по факту наличия
    устройства, как Intel/Realtek.
    """
    device = find_device(devices, lambda d: d.get("VendorID") == "14F1")
    if device is None:
        # Win32_PnPSignedDriver иногда не видит это устройство напрямую
        # (та же ситуация, что была с Realtek USB Audio) — резервный путь
        try:
            fallback_devices = get_devices_by_id_pattern("VEN_14F1")
        except Exception as e:
            print(f"[Senary Audio] ошибка резервного поиска: {classify_error(e)}", file=sys.stderr)
            fallback_devices = []
        device = find_device(fallback_devices, lambda d: True)  # любое устройство с этим VEN_
    if device is None:
        return None

    provider = SenaryAudioProvider()
    ok, latest = safe_get_latest("Senary Audio", provider)
    if not ok:
        return None
    # OEM (например Huawei) переупаковывает драйвер под своим номером
    # версии, отличным от того, что на сайте SenaryTech — сверка ненадёжна
    return report("Senary Audio", latest, current=None)

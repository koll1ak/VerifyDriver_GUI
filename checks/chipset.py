import sys

from net_utils import classify_error
from checks.common import find_device, safe_get_latest, report, no_downgrade_match
from providers.amd_chipset import AmdChipsetProvider, get_current_amd_chipset_version
from providers.intel_download import IntelDownloadCenterProvider, get_current_intel_chipset_version
from providers.intel_chipset_inf_db import IntelChipsetInfDbProvider

INTEL_CHIPSET_DOWNLOAD_ID = "19347"
INTEL_CHIPSET_SLUG = "chipset-inf-utility"


def check_amd_chipset(devices, board, laptop):
    # сначала проверяем, есть ли вообще AMD-платформа в системе — если нет
    # (например Intel-ноутбук), молча пропускаем, не пугая ложным
    # предупреждением про "не удалось определить чипсет"
    has_amd_platform = find_device(
        devices,
        lambda d: d.get("VendorID") == "1022" and any(
            kw in d.get("DeviceName", "").upper()
            for kw in ("SMBUS", "CHIPSET", "PCIE ROOT", "PCI ROOT")
        ),
    ) is not None
    if not has_amd_platform:
        return None  # платформа не AMD — молча пропускаем

    page_url = board.get("amd_chipset_url")
    if page_url is None:
        print(
            "[AMD Chipset] AMD-платформа найдена, но не удалось определить "
            "чипсет платы автоматически (board_detect.py не распознал модель)",
            file=sys.stderr,
        )
        return None

    provider = AmdChipsetProvider(page_url=page_url)
    device = find_device(devices, provider)
    if device is None:
        return None  # устройство не найдено в системе — молча пропускаем

    ok, latest = safe_get_latest("AMD Chipset", provider, device)
    if not ok:
        return None
    return report("AMD Chipset", latest, get_current_amd_chipset_version())


def check_intel_chipset(devices, board, laptop):
    # проверяем, есть ли вообще Intel-платформа в системе (по PCI Vendor ID),
    # прежде чем идти на сайт — на AMD-системе Intel Chipset Software
    # никогда не будет установлен, и сверка не имеет смысла
    intel_platform_device = find_device(
        devices,
        lambda d: d.get("VendorID") == "8086" and any(
            kw in d.get("DeviceName", "").upper()
            for kw in ("SMBUS", "LPC", "ISA BRIDGE", "PCI BRIDGE", "HOST BRIDGE")
        ),
    )
    if intel_platform_device is None:
        return None  # платформа не Intel — молча пропускаем

    # ОСНОВНОЙ путь: community-база (не официальный источник Intel, но
    # общедоступная и активно поддерживаемая) даёт версию конкретно ДЛЯ
    # ЭТОЙ платформы (по Hardware ID) — та же система счёта, что видна
    # в установленной системе, поэтому сравнение получается осмысленным
    # (в отличие от версии пакета целиком с сайта Intel — см. историю
    # в комментариях ниже, почему от неё пришлось отказаться).
    hwid = intel_platform_device.get("DeviceID_PCI")
    current = intel_platform_device.get("DriverVersion")

    if hwid:
        try:
            db_latest = IntelChipsetInfDbProvider(hwid=hwid).get_latest()
        except Exception as e:
            print(f"[Intel Chipset] ошибка (community-база): {classify_error(e)}", file=sys.stderr)
            db_latest = None
        if db_latest is not None:
            # версия для сравнения — из community-базы (точная, по HWID),
            # но ссылка для человека должна вести на официальную страницу
            # Intel, откуда реально качать установщик — не на сырой .md
            # файл базы данных, который нужен был только для сравнения
            db_latest["url"] = (
                f"https://www.intel.com/content/www/us/en/download/"
                f"{INTEL_CHIPSET_DOWNLOAD_ID}/{INTEL_CHIPSET_SLUG}.html"
            )
            return report("Intel Chipset", db_latest, current, comparator=no_downgrade_match)

    # ЗАПАСНОЙ путь: официальная страница Intel, но только версия пакета
    # целиком — сверка с установленной версией здесь принципиально
    # невозможна (версия пакета живёт в другой системе счёта, чем версия
    # конкретного компонента для конкретного поколения процессора).
    provider = IntelDownloadCenterProvider(
        download_id=INTEL_CHIPSET_DOWNLOAD_ID, slug=INTEL_CHIPSET_SLUG, name="intel_chipset"
    )
    ok, latest = safe_get_latest("Intel Chipset", provider)
    if not ok:
        return None

    # ВАЖНО: изначально тут была попытка брать версию PnP-драйвера SMBus-
    # контроллера как fallback, если реестр пуст — оказалось, что это
    # неверно: версия конкретного PnP-компонента (SMBus) не обязана
    # совпадать с версией всего пакета "Chipset Device Software" целиком
    # (подтверждено на практике: после реальной установки пакета версия
    # SMBus-драйвера не изменилась, сравнение продолжало ложно показывать
    # "обновление доступно"). Поэтому используем только реестр — если он
    # пуст, честно показываем "сверить не удалось", а не гадаем.
    current = get_current_intel_chipset_version()
    return report("Intel Chipset", latest, current)

from checks.common import find_device, find_device_driver_version, safe_get_latest, report
from providers.nvidia import NvidiaProvider, get_current_nvidia_version
from providers.amd_gpu import AmdGpuProvider
from providers.intel_download import IntelDownloadCenterProvider

# AMD Software: Adrenalin Edition — одна и та же версия драйвера указана
# на ЛЮБОЙ странице продукта AMD (дискретные карты и APU-графика в
# процессорах используют общий универсальный пакет, подтверждено на
# практике: одинаковый номер версии виден и на странице видеокарты, и
# на странице процессора с APU) — поэтому подходит любая валидная
# страница продукта AMD, даже если сама встроенная графика — другой
# модели. Здесь — страница конкретно Ryzen 7 9800X3D (встроенная
# RDNA2-графика, 2 CU), структура страницы проверена: версия драйвера
# и ссылка на Release Notes (RN-RAD-WIN) парсятся так, как ожидает
# AmdGpuProvider.
AMD_GPU_PAGE_URL = "https://www.amd.com/en/support/downloads/drivers.html/processors/ryzen/ryzen-9000-series/amd-ryzen-7-9800x3d.html"

INTEL_GPU_DOWNLOAD_ID = "785597"
INTEL_GPU_SLUG = "intel-arc-graphics-windows"


def check_nvidia(devices, board, laptop):
    provider = NvidiaProvider()
    device = find_device(devices, provider)
    if device is None:
        return None  # устройство не найдено в системе — молча пропускаем

    ok, latest = safe_get_latest("NVIDIA", provider, device)
    if not ok:
        return None
    return report("NVIDIA", latest, get_current_nvidia_version())


def check_amd_gpu(devices, board, laptop):
    # ищем AMD-видеокарту среди устройств, даже если URL ещё не настроен —
    # чтобы подсказать точное имя карты для поиска на amd.com.
    # ВАЖНО: у видеокарт AMD Vendor ID "1002" (унаследовано от ATI), а не
    # "1022" (тот используется для чипсета/CPU-устройств) — подтверждено
    # на реальном устройстве, изначально был баг с перепутанными ID.
    amd_gpu_device = find_device(
        devices,
        lambda d: d.get("VendorID") == "1002" and any(
            kw in d.get("DeviceName", "").upper() for kw in ("RADEON", "AMD GRAPHICS")
        ),
    )
    if amd_gpu_device is None:
        return None  # устройство не найдено в системе — молча пропускаем

    provider = AmdGpuProvider(page_url=AMD_GPU_PAGE_URL)
    ok, latest = safe_get_latest("AMD GPU", provider, amd_gpu_device)
    if not ok:
        return None
    # AmdGpuProvider явно указывает флагом comparable_with_windows_version,
    # можно ли доверять сравнению (см. providers/amd_gpu.py) — если версию
    # с сайта удалось перевести в формат "Windows Driver Store Version"
    # (тот же, что видит Windows), сравниваем напрямую; если нет — версия
    # осталась маркетинговой ("26.7.1"), сравнивать с ней небезопасно
    current = amd_gpu_device.get("DriverVersion") if latest and latest.get("comparable_with_windows_version") else None
    return report("AMD GPU", latest, current)


def check_intel_gpu(devices, board, laptop):
    # ВАЖНО: пакет драйвера (ID 785597) — это конкретно "Intel Arc & Iris Xe
    # Graphics", он НЕ подходит для более старых встроенных GPU (например
    # "Intel UHD Graphics" на платформах до Xe-поколения, вроде Comet Lake) —
    # установка на несовместимом железе даёт ошибку "No supported devices".
    # Поэтому ищем строго по словам "ARC" или "IRIS XE", а не по общему
    # "GRAPHICS"/голому "IRIS" (последнее ловит и старый Iris Plus/Pro).
    current = find_device_driver_version(devices, "8086", ("ARC", "IRIS XE"))
    if current is None:
        return None  # устройство не найдено в системе (или не Xe-поколения) — молча пропускаем

    provider = IntelDownloadCenterProvider(
        download_id=INTEL_GPU_DOWNLOAD_ID, slug=INTEL_GPU_SLUG, name="intel_gpu"
    )
    ok, latest = safe_get_latest("Intel GPU", provider)
    if not ok:
        return None
    # у Intel версия в Windows обычно совпадает с маркетинговой напрямую
    return report("Intel GPU", latest, current)

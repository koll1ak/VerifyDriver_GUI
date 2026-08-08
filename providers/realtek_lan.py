"""
Провайдер Realtek LAN — тонкая обёртка над RealtekCategoryProvider.

cate_id=584 — общая категория PCIe FE/GbE/2.5G/5G/10G, покрывает весь
модельный ряд чипов RTL8111/8125/8126/8127 одним установщиком (инсталлятор
сам определяет конкретный чип). В категории одновременно лежат разные
варианты драйвера (NDIS/NetAdapterCx, с поддержкой энергосбережения и без) —
выбираем по подстроке в Description, а не по индексу (порядок может
смениться при обновлении).
"""

from providers.realtek_base import RealtekCategoryProvider

DEFAULT_CATE_ID = "584"
DEFAULT_MATCH_SUBSTRINGS = ("NetAdapterCx", "Not Support Power Saving")


def realtek_versions_match(current: str, latest: str) -> bool:
    """
    Сайт даёт версию вида "11.030.20", Windows — вида "1126.30.20.508".
    Средние два сегмента версии Windows соответствуют последним двум
    сегментам версии с сайта (без ведущих нулей) — например "30.20" в обоих
    случаях. Первый сегмент Windows-версии — это склейка кода продукта и
    года релиза, последний — внутренний build, оба не участвуют в сравнении.

    Правило подтверждено эмпирически ТОЛЬКО для 2.5G/5G-чипов (например
    RTL8126, где реальная версия была "1126.30.20.508"). Для старых
    1GbE-чипов (RTL8111 и т.п.) формат версии Windows выглядит иначе —
    например "1168.8.515.2022", где последний сегмент похож на год, а не
    build — правило тут неприменимо. is_recognized_format() ниже помогает
    отличить один случай от другого перед тем, как доверять сравнению.
    """
    if not current or not latest:
        return False

    def _norm(parts):
        try:
            return ".".join(str(int(p)) for p in parts)
        except ValueError:
            return None

    site_parts = latest.split(".")
    installed_parts = current.split(".")

    if len(site_parts) < 2 or len(installed_parts) < 3:
        return False

    site_norm = _norm(site_parts[-2:])
    installed_norm = _norm(installed_parts[1:3])

    return site_norm is not None and site_norm == installed_norm


def is_recognized_realtek_version_format(current: str) -> bool:
    """
    True, если версия Windows похожа на подтверждённый формат для 2.5G/5G
    чипов ("PPYY.mid.mid.build", например "1126.30.20.508" — первый
    сегмент 4 цифры, где последние 2 правдоподобны как год 20XX).
    Для старых 1GbE-чипов формат другой (например "1168.8.515.2022") —
    не подтверждён эмпирически, сравнивать с сайтом небезопасно.
    """
    parts = current.split(".")
    if len(parts) != 4:
        return False
    first = parts[0]
    if len(first) != 4 or not first.isdigit():
        return False
    year_part = int(first[2:4])
    return 20 <= year_part <= 39  # правдоподобный год релиза (2020-е-2030-е)


def realtek_ndis_versions_match(current: str, latest: str) -> bool:
    """
    Для NDIS-варианта драйвера (не NetAdapterCx) версия Windows и версия
    сайта совпадают напрямую — сайт даёт "10.80.20", Windows —
    "10.80.20.407" (просто с дополнительным build-сегментом на конце).
    Подтверждено на реальном устройстве.
    """
    if not current or not latest:
        return False
    installed_parts = current.split(".")
    if len(installed_parts) < 3:
        return False
    try:
        installed_prefix = ".".join(str(int(p)) for p in installed_parts[:3])
        site_norm = ".".join(str(int(p)) for p in latest.split("."))
    except ValueError:
        return False
    return installed_prefix == site_norm


def detect_realtek_lan_variant(current: str) -> str:
    """
    "ndis" / "netadaptercx" / "unknown" — какой драйверный фреймворк
    установлен, по формату версии. NDIS даёт короткий первый сегмент
    ("10"/"11"), NetAdapterCx — склейку кода продукта с годом ("1126" и
    т.п., см. is_recognized_realtek_version_format). Оба подтверждены на
    реальных устройствах — на разных машинах может быть установлен любой
    из двух, страница Realtek публикует оба варианта отдельно.

    ВАЖНО: у некоторых легаси-чипов последний сегмент версии — тоже год
    (например "10.31.828.2018"), и первый сегмент при этом может случайно
    совпасть с "10"/"11" — это НЕ настоящий NDIS-формат (подтверждено на
    практике: такая версия не совпадает ни с одной записью на сайте).
    Проверяем это ДО определения NDIS, чтобы не сравнивать по ошибке.
    """
    if not current:
        return "unknown"
    parts = current.split(".")
    if len(parts) != 4:
        return "unknown"

    last = parts[-1]
    if len(last) == 4 and last.isdigit() and 2000 <= int(last) <= 2039:
        return "unknown"  # похоже на легаси-формат с годом на конце

    if parts[0] in ("10", "11"):
        return "ndis"
    if is_recognized_realtek_version_format(current):
        return "netadaptercx"
    return "unknown"


class RealtekLanProvider(RealtekCategoryProvider):
    name = "realtek_lan"

    def __init__(self, cate_id: str = DEFAULT_CATE_ID, match_substrings=DEFAULT_MATCH_SUBSTRINGS):
        super().__init__(cate_id=cate_id, match_substrings=match_substrings)

    def matches(self, device: dict) -> bool:
        # Realtek VEN_10EC используется и для аудио, и для LAN — отсекаем
        # аудио-устройства по наличию "FAMILY CONTROLLER" в имени (так
        # называются в Windows именно сетевые чипы этой линейки)
        return (
            device.get("VendorID") == "10EC"
            and "FAMILY CONTROLLER" in device.get("DeviceName", "").upper()
        )

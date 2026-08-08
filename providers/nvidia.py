"""
Провайдер NVIDIA.

Логика:
1. По имени устройства из сканера находим pfid (Product Family ID, внутренний
   идентификатор NVIDIA) в открытом справочнике ZenitH-AT/nvidia-data.
2. Дергаем официальный AjaxDriverService (тот же backend, которым пользуется
   страница ручного поиска драйверов на nvidia.com) — получаем актуальную
   версию, дату и ссылку.

osID подбирается автоматически под установленную Windows (10 или 11) —
у NVIDIA это разные ID в справочнике (57 и 135 соответственно), хотя
для современных карт пакет драйвера обычно один и тот же на обе версии.

Источники:
- https://github.com/ZenitH-AT/nvidia-data  (файлы gpu-data.json, os-data.json в корне репо)
- https://github.com/ZenitH-AT/nvidia-update (пример реального запроса к API)
"""

import re
import subprocess
import sys

import requests

from providers.base import DriverProvider

GPU_DATA_URL = "https://raw.githubusercontent.com/ZenitH-AT/nvidia-data/main/gpu-data.json"
AJAX_URL = "https://gfwsl.geforce.com/services_toolkit/services/com/nvidia/services/AjaxDriverService.php"

# osID из os-data.json: 57 = "Windows 10 64-bit", 135 = "Windows 11"
OS_ID_WINDOWS_10 = "57"
OS_ID_WINDOWS_11 = "135"
WINDOWS_11_MIN_BUILD = 22000  # первый билд, который Microsoft называет "Windows 11"


def detect_windows_os_id() -> str:
    """
    Определяет правильный osID под установленную Windows.
    sys.getwindowsversion() надёжнее, чем platform.release() — последний
    на Windows 11 иногда всё ещё возвращает "10" из-за общей кодовой базы.
    Если не Windows (или определить не удалось) — по умолчанию Win10 ID,
    он же исторически самый совместимый вариант в API NVIDIA.
    """
    try:
        build = sys.getwindowsversion().build
    except AttributeError:
        return OS_ID_WINDOWS_10  # не Windows — используем дефолт

    return OS_ID_WINDOWS_11 if build >= WINDOWS_11_MIN_BUILD else OS_ID_WINDOWS_10


def get_current_nvidia_version() -> str | None:
    """
    Реальная установленная версия драйвера через nvidia-smi — она сразу
    в маркетинговом формате (например "610.88"), без возни с внутренним
    форматом версии Windows (Win32_PnPSignedDriver даёт что-то вроде
    "32.0.15.6108", откуда маркетинговую версию не так просто восстановить).
    """
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        return None
    version = result.stdout.strip()
    return version or None


class NvidiaProvider(DriverProvider):
    name = "nvidia"

    def __init__(self, os_id: str | None = None):
        # если os_id не передан явно — определяем автоматически по системе
        self.os_id = os_id or detect_windows_os_id()
        self._gpu_data = None

    def matches(self, device: dict) -> bool:
        # VendorID 10DE (NVIDIA) используется не только видеокартой, но и её
        # HDMI-аудио устройством ("NVIDIA High Definition Audio") — фильтр
        # только по "NVIDIA" в имени слишком широкий и может случайно
        # поймать аудио вместо GPU. Требуем характерное для видеокарты слово.
        if device.get("VendorID") != "10DE":
            return False
        name_upper = device.get("DeviceName", "").upper()
        return any(kw in name_upper for kw in ("GEFORCE", "RTX", "GTX", "QUADRO", "NVS", "TESLA"))

    def _load_gpu_data(self) -> dict:
        if self._gpu_data is None:
            resp = requests.get(GPU_DATA_URL, timeout=15)
            resp.raise_for_status()
            self._gpu_data = resp.json()
        return self._gpu_data

    @staticmethod
    def _clean_name(name: str) -> str:
        # "NVIDIA GeForce RTX 5080" -> "GeForce RTX 5080"
        return name.replace("NVIDIA ", "").strip()

    @staticmethod
    def _normalize_variant_name(name: str) -> str:
        """
        По документации самого справочника ZenitH-AT/nvidia-data: некоторые
        варианты имени от Windows не совпадают ключ-в-ключ с базой — нужно
        привести "Super" к "SUPER" и убрать типичные суффиксы (объём памяти,
        аббревиатуры производителя ноутбука в скобках, "with Max-Q Design",
        "Laptop GPU" — этот суффикс Windows добавляет для мобильных карт
        начиная с 30-й серии, в оригинальном списке справочника его не было).
        """
        name = name.replace("Super", "SUPER")
        for pattern in (
            r"\s+\(Laptop GPU\)$",
            r"\s+Laptop GPU$",
            r"\s+\([^)]*\)$",                # любой суффикс в скобках
            r"\s+\d+GB$",                     # "8GB"
            r"\s+COLLECTORS EDITION$",
            r"\s+with Max-Q Design$",
        ):
            name = re.sub(pattern, "", name, flags=re.IGNORECASE)
        return name.strip()

    def _lookup_pfid(self, gpu_data: dict, name: str) -> str | None:
        for section in ("desktop", "notebook"):
            section_data = gpu_data.get(section, {})
            if name in section_data:
                return section_data[name]
        return gpu_data.get(name)  # на случай плоской структуры (без desktop/notebook)

    def get_latest(self, device: dict) -> dict | None:
        gpu_data = self._load_gpu_data()
        clean_name = self._clean_name(device["DeviceName"])

        pfid = self._lookup_pfid(gpu_data, clean_name)

        if pfid is None:
            normalized_name = self._normalize_variant_name(clean_name)
            if normalized_name != clean_name:
                pfid = self._lookup_pfid(gpu_data, normalized_name)

        if pfid is None:
            print(
                f"[nvidia] карта не найдена в справочнике по имени "
                f"\"{clean_name}\" (и после нормализации тоже) — возможно, "
                f"нужно вручную свериться с gpu-data.json",
                file=sys.stderr,
            )
            return None

        params = {
            "func": "DriverManualLookup",
            "pfid": pfid,
            "osID": self.os_id,
            "dch": 1,
        }

        resp = requests.get(AJAX_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        ids = data.get("IDS") or []
        if not ids:
            return None

        info = ids[0]["downloadInfo"]
        url = info.get("DownloadURL", "")
        if url.startswith("//"):
            url = "https:" + url

        return {
            "version": info.get("Version"),
            "date": info.get("ReleaseDateTime"),
            "url": url,
        }

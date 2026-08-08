"""
Провайдер Realtek USB LAN (внешние USB-адаптеры Ethernet, докстанции
и т.п.) — отдельная категория от встроенных PCIe-чипов (providers/realtek_lan.py).

cate_id=585 — "Realtek USB FE / GbE / 2.5GbE / 5G / 10G Family Controller
Software". USB-устройства Realtek иногда числятся под VendorID 10EC
(как PCIe), а иногда под 0BDA (как USB-аудиокодеки, например ALC4080) —
проверяем оба.
"""

from providers.realtek_base import RealtekCategoryProvider

DEFAULT_CATE_ID = "585"


class RealtekUsbLanProvider(RealtekCategoryProvider):
    name = "realtek_usb_lan"

    def __init__(self, cate_id: str = DEFAULT_CATE_ID, match_substrings=None):
        super().__init__(cate_id=cate_id, match_substrings=match_substrings)

    def matches(self, device: dict) -> bool:
        return (
            device.get("VendorID") in ("10EC", "0BDA")
            and "USB" in device.get("DeviceID", "").upper()
            and "FAMILY CONTROLLER" in device.get("DeviceName", "").upper()
        )

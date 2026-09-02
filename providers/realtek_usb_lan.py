"""
Realtek USB LAN provider (external USB Ethernet adapters, docking
stations, etc.) — a separate category from the built-in PCIe chips
(providers/realtek_lan.py).

cate_id=585 — "Realtek USB FE / GbE / 2.5GbE / 5G / 10G Family Controller
Software". USB-based Realtek devices are sometimes listed under
VendorID 10EC (like PCIe), and sometimes under 0BDA (like USB audio
codecs, e.g. the ALC4080) — we check both.
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
            and (device.get("DeviceClass") or "").upper() == "NET"
        )

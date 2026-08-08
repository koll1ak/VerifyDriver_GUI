"""
Провайдер Realtek WLAN (WiFi) — тонкая обёртка над RealtekCategoryProvider.

cate_id=673 — "Realtek PCIe WLAN Family Controller Software", покрывает
чипы RTL8723BE/RTL8821AE/RTL8822BE/RTL8821CE/RTL8723DE (WLAN+Bluetooth
комбо) и RTL8812AE/RTL8192EE/RTL8188EE (только WLAN).
"""

from providers.realtek_base import RealtekCategoryProvider

DEFAULT_CATE_ID = "673"


class RealtekWifiProvider(RealtekCategoryProvider):
    name = "realtek_wifi"

    def __init__(self, cate_id: str = DEFAULT_CATE_ID, match_substrings=None):
        super().__init__(cate_id=cate_id, match_substrings=match_substrings)

    def matches(self, device: dict) -> bool:
        return (
            device.get("VendorID") == "10EC"
            and any(kw in device.get("DeviceName", "").upper() for kw in ("WLAN", "WIRELESS", "802.11"))
        )

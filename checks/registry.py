from checks.bios import check_bios
from checks.chipset import check_amd_chipset, check_intel_chipset
from checks.gpu import check_nvidia, check_amd_gpu, check_intel_gpu
from checks.audio import check_audio, check_senary_audio
from checks.network import (
    check_realtek_lan, check_realtek_wifi, check_realtek_usb_lan,
    check_intel_lan, check_intel_wifi, check_intel_bluetooth,
    check_bluetooth_via_windows_update, check_wifi_via_windows_update,
)
from checks.laptop import (
    check_dell_bios, check_dell_audio,
    check_acer_bios, check_acer_audio, check_acer_lan,
    check_asus_laptop_bios, check_asus_laptop_audio, check_asus_laptop_networking,
    check_huawei_bios,
    check_lenovo_bios, check_lenovo_audio,
)

CATEGORY_ORDER = [
    "BIOS", "Chipset", "Integrated GPU", "GPU", "Audio", "LAN", "WiFi", "Bluetooth",
]

# (category, function) — the category is only used for ordering in the
# final summary; the check itself runs in parallel with all the others,
# the order of live output (as they complete) doesn't depend on this
CHECKS = [
    ("BIOS", check_bios),
    ("BIOS", check_dell_bios),
    ("BIOS", check_acer_bios),
    ("BIOS", check_asus_laptop_bios),
    ("BIOS", check_huawei_bios),
    ("BIOS", check_lenovo_bios),
    ("Chipset", check_amd_chipset),
    ("Chipset", check_intel_chipset),
    ("Integrated GPU", check_intel_gpu),
    ("GPU", check_nvidia),
    ("GPU", check_amd_gpu),
    ("Audio", check_audio),
    ("Audio", check_dell_audio),
    ("Audio", check_acer_audio),
    ("Audio", check_asus_laptop_audio),
    ("Audio", check_senary_audio),
    ("Audio", check_lenovo_audio),
    ("LAN", check_realtek_lan),
    ("LAN", check_realtek_usb_lan),
    ("LAN", check_intel_lan),
    ("LAN", check_acer_lan),
    ("WiFi", check_intel_wifi),
    ("WiFi", check_realtek_wifi),
    ("WiFi", check_wifi_via_windows_update),
    ("WiFi", check_asus_laptop_networking),
    ("Bluetooth", check_intel_bluetooth),
    ("Bluetooth", check_bluetooth_via_windows_update),
]

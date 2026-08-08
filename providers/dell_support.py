"""
Dell laptops — BIOS/Audio.

Originally attempted as a scraping provider (heuristic text patterns
over the drivers page, like providers/asus_bios.py's fallback path) —
dropped after live testing: Dell's site is behind Akamai and returns a
flat 403 "Access Denied" for the drivers page, with or without
curl_cffi's impersonate="chrome" (the same trick that works for MSI/
Lenovo). There is no content to parse — the block happens before any
HTML is served. ASRock's checks were later dropped the same way, for
the same underlying reason (site now blocked, see checks/bios.py and
checks/audio.py).

Same situation and same fix as providers/huawei_support.py: no chip
maker has a public page for BIOS (it's always vendor-written), and here
Audio has no other source either — so instead of a broken automatic
check, we give a link to the drivers page for a manual check.

    https://www.dell.com/support/home/en-us/product-support/servicetag/<TAG>/drivers
"""


def dell_drivers_url(service_tag: str) -> str | None:
    if not service_tag:
        return None
    return f"https://www.dell.com/support/home/en-us/product-support/servicetag/{service_tag}/drivers"

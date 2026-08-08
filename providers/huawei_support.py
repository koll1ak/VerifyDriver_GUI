"""
Huawei laptops — BIOS.

There used to be an attempt at fully automatic resolution via Huawei's
own API (model from WMI -> offeringCode -> BIOS version), including a
headless browser (Playwright) to get past the site's protection — that
approach was dropped: too heavy a dependency (a full Chromium) for a
single vendor, and even with it the site remains a fragile source.

Components (chipset/WiFi/Bluetooth — Intel; Audio/LAN — Realtek) are
already compared directly against the CHIP MAKERS' sites (main.py:
check_intel_*, check_realtek_*) — those work the same way on any laptop
regardless of vendor, including Huawei, with zero vendor-specific code.
A dedicated source is only missing for BIOS — no chip maker has a public
page for it (BIOS is always written by the laptop/board vendor), so we
just give a link to search Huawei's site manually, without attempting to
automatically download/compare the version.
"""


def huawei_search_url(wmi_model: str) -> str | None:
    """
    A link to search Huawei's site — for a manual check. The format is
    confirmed against real network traffic from the site (search page
    consumer.huawei.com/en/search/?keyword=<query>).

    WMI sometimes duplicates the last character of the model code (e.g.
    "MCLF-XX", whereas the real code on the site is "MCLF-X", a single
    "X") — confirmed empirically on a real device: searching with a
    doubled character at the end finds nothing. If the last two
    characters match, we drop one — this doesn't change the model
    number itself, just removes the duplication.
    """
    if not wmi_model:
        return None
    if len(wmi_model) >= 2 and wmi_model[-1] == wmi_model[-2]:
        wmi_model = wmi_model[:-1]
    from urllib.parse import quote
    return f"https://consumer.huawei.com/en/search/?keyword={quote(wmi_model)}"

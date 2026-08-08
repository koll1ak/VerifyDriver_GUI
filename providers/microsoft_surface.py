"""
Microsoft Surface laptops — BIOS/Audio (and everything else).

Confirmed live: Microsoft doesn't offer per-component driver downloads
at all — each Surface model gets ONE cumulative MSI package bundling
every driver AND the system firmware/BIOS update together (a real
Surface Pro 8 page lists a single ~966MB
"SurfacePro8_Win11_22631_...msi" with one version/date, no separate
BIOS or Audio entries to compare). Microsoft's own guidance recommends
Windows Update for this anyway — the support page explicitly labels
"Automatically update Windows, Surface drivers, and firmware" as
"Recommended for most users", with the manual MSI download called out
as the "Advanced option for experienced users" path instead.

Given there's nothing meaningful to version-compare per component, we
just link to the model's official download page rather than attempt a
check that doesn't map onto this project's per-category model at all.

Source for the model -> download page table below: Microsoft's own
maintained documentation, confirmed live —
https://learn.microsoft.com/surface/manage-surface-driver-and-firmware-updates
This list WILL go stale as Microsoft ships new Surface models — it
needs periodic refreshing against that page, same caveat as any other
hardcoded catalog.
"""

SURFACE_DOWNLOAD_URLS = {
    "Surface Pro 12th Edition (Snapdragon)": "https://www.microsoft.com/download/details.aspx?id=108706",
    "Surface Pro for Business 12th Edition (Intel)": "https://www.microsoft.com/download/details.aspx?id=108671",
    "Surface Pro 12-inch 1st Edition": "https://www.microsoft.com/download/details.aspx?id=108199",
    "Surface Pro for Business 11th Edition (Intel)": "https://www.microsoft.com/download/details.aspx?id=108013",
    "Surface Pro 11th Edition (Snapdragon)": "https://www.microsoft.com/download/details.aspx?id=106119",
    "Surface Pro 10 with 5G for Business": "https://www.microsoft.com/download/details.aspx?id=106292",
    "Surface Pro 10": "https://www.microsoft.com/download/details.aspx?id=105947",
    "Surface Pro 9 with 5G (SQ3)": "https://www.microsoft.com/download/details.aspx?id=105941",
    "Surface Pro 9 (Intel)": "https://www.microsoft.com/download/details.aspx?id=104680",
    "Surface Pro 8": "https://www.microsoft.com/download/details.aspx?id=103503",
    "Surface Pro 7+ and Surface Pro 7+ (LTE)": "https://www.microsoft.com/download/details.aspx?id=102633",
    "Surface Pro 7": "https://www.microsoft.com/download/details.aspx?id=100419",
    "Surface Pro 6": "https://www.microsoft.com/download/details.aspx?id=57514",
    "Surface Pro 5 (LTE)": "https://www.microsoft.com/download/details.aspx?id=56278",
    "Surface Pro 5 (Wi-Fi)": "https://www.microsoft.com/download/details.aspx?id=55484",
    "Surface Pro 4": "https://www.microsoft.com/download/details.aspx?id=49498",
    "Surface Pro 3": "https://www.microsoft.com/download/details.aspx?id=38826",
    "Surface Pro 2": "https://www.microsoft.com/download/details.aspx?id=49042",
    "Surface Pro": "https://www.microsoft.com/download/details.aspx?id=49038",
    "Surface Laptop 8th Edition (Snapdragon)": "https://www.microsoft.com/download/details.aspx?id=108705",
    "Surface Laptop for Business 8th Edition (Intel)": "https://www.microsoft.com/download/details.aspx?id=108669",
    "Surface Laptop 13-inch 1st Edition (Intel)": "https://www.microsoft.com/download/details.aspx?id=108670",
    "Surface Laptop 13-inch 1st Edition (Snapdragon)": "https://www.microsoft.com/download/details.aspx?id=108198",
    "Surface Laptop 5G for Business 7th Edition (Intel)": "https://www.microsoft.com/download/details.aspx?id=108347",
    "Surface Laptop for Business 7th Edition (Intel)": "https://www.microsoft.com/download/details.aspx?id=108014",
    "Surface Laptop 7th Edition (Snapdragon)": "https://www.microsoft.com/download/details.aspx?id=106120",
    "Surface Laptop 6": "https://www.microsoft.com/download/details.aspx?id=105946",
    "Surface Laptop 5": "https://www.microsoft.com/download/details.aspx?id=104679",
    "Surface Laptop 4 (Intel)": "https://www.microsoft.com/download/details.aspx?id=102924",
    "Surface Laptop 4 (AMD)": "https://www.microsoft.com/download/details.aspx?id=102923",
    "Surface Laptop 3 (Intel)": "https://www.microsoft.com/download/details.aspx?id=100429",
    "Surface Laptop 3 (AMD)": "https://www.microsoft.com/download/details.aspx?id=100428",
    "Surface Laptop 2": "https://www.microsoft.com/download/details.aspx?id=57515",
    "Surface Laptop": "https://www.microsoft.com/download/details.aspx?id=55489",
    "Surface Laptop Go 3": "https://www.microsoft.com/download/details.aspx?id=105608",
    "Surface Laptop Go 2": "https://www.microsoft.com/download/details.aspx?id=104251",
    "Surface Laptop Go": "https://www.microsoft.com/download/details.aspx?id=102261",
    "Surface Laptop Studio 2": "https://www.microsoft.com/download/details.aspx?id=105610",
    "Surface Laptop Studio": "https://www.microsoft.com/download/details.aspx?id=103505",
    "Surface Book 3": "https://www.microsoft.com/download/details.aspx?id=101315",
    "Surface Book 2": "https://www.microsoft.com/download/details.aspx?id=56261",
    "Surface Book": "https://www.microsoft.com/download/details.aspx?id=49497",
    "Surface Go 4": "https://www.microsoft.com/download/details.aspx?id=105609",
    "Surface Go 3": "https://www.microsoft.com/download/details.aspx?id=103504",
    "Surface Go 2": "https://www.microsoft.com/download/details.aspx?id=101304",
    "Surface Go (Wi-Fi)": "https://www.microsoft.com/download/details.aspx?id=57439",
    "Surface Go (LTE)": "https://www.microsoft.com/download/details.aspx?id=57601",
    "Surface Studio 2+": "https://www.microsoft.com/download/details.aspx?id=104681",
    "Surface Studio 2": "https://www.microsoft.com/download/details.aspx?id=57593",
    "Surface Studio": "https://www.microsoft.com/download/details.aspx?id=54311",
    "Surface 3 (Wi-Fi)": "https://www.microsoft.com/download/details.aspx?id=49040",
}


def surface_drivers_url(model: str) -> str | None:
    """
    Best-effort match of a raw WMI Model string (e.g. "Surface Laptop
    6") against the table above. Many current model names match a
    table key exactly (confirmed: "Surface Laptop 6", "Surface Pro 8",
    "Surface Go 4" etc. are literal keys) — falls back to a prefix
    match for cases where the table's entry has an extra suffix
    ("for Business", "(Intel)", "(Snapdragon)") that a plain consumer
    device's Model string likely won't include, preferring the
    shortest (least suffixed / most likely plain-consumer) match.
    """
    if not model:
        return None
    model_upper = model.strip().upper()

    exact = next((v for k, v in SURFACE_DOWNLOAD_URLS.items() if k.upper() == model_upper), None)
    if exact:
        return exact

    prefix_matches = [(k, v) for k, v in SURFACE_DOWNLOAD_URLS.items() if k.upper().startswith(model_upper)]
    if prefix_matches:
        prefix_matches.sort(key=lambda pair: len(pair[0]))
        return prefix_matches[0][1]

    return None

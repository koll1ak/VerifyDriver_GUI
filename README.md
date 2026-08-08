# VerifyDriver (driver-watch)

An autonomous Python script for Windows that checks whether your drivers
are up to date across many categories and vendors at once — no manual
input required, everything is auto-detected from the machine's own
hardware.

## What gets checked

| Category | Sources |
|---|---|
| BIOS | MSI, Gigabyte, ASRock, ASUS (desktop) · Dell, Acer, ASUS, Lenovo, Huawei (laptops, manual link) |
| Chipset | AMD, Intel |
| Integrated GPU | Intel |
| GPU | NVIDIA, AMD, Intel |
| Audio | Motherboard vendor's page (MSI/Gigabyte/ASRock/ASUS) → Microsoft Update Catalog as fallback · Dell, Acer, ASUS, Lenovo (laptops) · SenaryTech |
| LAN | Realtek (PCIe + USB), Intel, Acer (Killer/Realtek/Intel) |
| WiFi | Intel, Realtek, Microsoft Update Catalog (non-Intel chips), ASUS Networking |
| Bluetooth | Intel, Microsoft Update Catalog (non-Intel chips) |

Checks run in parallel (`ThreadPoolExecutor`); output is collected and
printed all at once after everything finishes — in a fixed order by
category, not by which site happened to respond fastest.

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

## Architecture

```
main.py              — entry point: collect devices, run checks, print the report
board_detect.py       — auto-detects desktop motherboard vendor/model
laptop_detect.py       — auto-detects laptop vendor/model/serial number
scanner.py              — collects installed devices and driver versions (WMI)
net_utils.py             — internet connectivity check, error classification

checks/
  common.py            — shared helpers (find_device, safe_get_latest, report, ...)
  bios.py, chipset.py, gpu.py, audio.py, network.py, laptop.py
  registry.py           — CHECKS (registry of all checks) and CATEGORY_ORDER

providers/              — one file per source (vendor/chip website)
```

There are no manual-configuration files — everything is either
auto-detected from the hardware, or (where auto-detection is simply
not possible, e.g. the support page for a specific AMD GPU model) is
hardcoded directly in the relevant `checks/` module.

## Verification status by vendor

Some providers have been confirmed against real hardware (MSI, AMD,
NVIDIA, Intel, Realtek LAN, Acer, ASUS — page structure and version
comparison logic verified in practice). Others — Dell and Lenovo — were
written from documented or reverse-engineered API/page formats found in
third-party open-source tools, but **have not been verified on real
hardware**: this is stated explicitly in each such provider's docstring
(`providers/dell_support.py`, `providers/lenovo_support.py`). If you own
hardware from these vendors, feedback/PRs with real-world data are
welcome.

## Requirements

- Windows (uses `Get-CimInstance`/WMI via PowerShell)
- Python 3.10+
- `pip install -r requirements.txt` (requests, beautifulsoup4, curl_cffi)

# VerifyDriver (driver-watch)

An autonomous Windows driver update checker that covers many hardware
categories and vendors at once — no manual input required, everything
is auto-detected from the machine's own hardware. Ships as both a
desktop GUI app and a CLI script, sharing the same detection/checking
core.

## What gets checked

| Category | Sources |
|---|---|
| BIOS | MSI, Gigabyte, ASUS (desktop) · Dell, Acer, ASUS, Lenovo, HP, MSI, Gigabyte, LG, Huawei, Samsung, Microsoft Surface (laptops, manual link for Dell/Huawei/Samsung/LG/Microsoft Surface) · ASRock (desktop, manual link — site now blocked) |
| Chipset | AMD, Intel |
| Integrated GPU | Intel |
| GPU | NVIDIA, AMD, Intel |
| NPU | Intel |
| Audio | Motherboard vendor's page (MSI/Gigabyte/ASUS) → Microsoft Update Catalog as fallback · Dell, Acer, ASUS, Lenovo, HP, MSI, Gigabyte, LG (laptops) · Samsung, Microsoft Surface (laptops, manual link) · SenaryTech · ASRock (desktop, manual link — site now blocked) |
| LAN | Realtek (PCIe + USB), Intel, Acer (Killer/Realtek/Intel) |
| WiFi | Intel, Realtek, Microsoft Update Catalog (non-Intel chips), ASUS Networking |
| Bluetooth | Intel, Microsoft Update Catalog (non-Intel chips) |

Checks run in parallel (`ThreadPoolExecutor`); results are collected and
presented all at once after everything finishes — in a fixed order by
category, not by which site happened to respond fastest.

## GUI app

```
python gui_main.py
```

A Tkinter desktop app (`gui/`) that runs the same scan/check pipeline
and shows results in a sortable Device/Current/Available/Status table,
grouped by category. Double-clicking a row:

- opens the vendor's manual-check/download page in the default browser,
  when that's the check's source; or
- for a Microsoft Update Catalog-sourced result with a direct `.cab`
  link (Bluetooth/WiFi non-Intel chips), downloads, unpacks, and
  installs the update via `pnputil` in place — progress is shown in the
  status bar, and the app automatically re-scans afterward so the table
  reflects the newly installed version (if Windows reports the install
  needs a reboot to finish, that's also surfaced as a popup first).

The app requires administrator rights (installing a driver via
`pnputil` needs them) and elevates itself via a UAC prompt on launch —
this way `pnputil` never needs a second prompt mid-install. Launching a
browser link from an elevated process is handled specially (via
`explorer.exe`, see `gui/app.py:_open_in_browser`) so the browser itself
still opens at normal, non-elevated integrity.

## CLI

```
python main.py
```

Prints the same per-category results as plain text, plus an "Updates
available" summary section — no interaction, no admin rights required
(it doesn't install anything).

## Install

```bash
pip install -r requirements.txt
```

## Building a standalone .exe

The GUI is packaged as a single-file Nuitka executable, entry point
`gui_main.py`, output to `build/` (not Nuitka's default `dist/`):

```
python -m nuitka --onefile --enable-plugin=tk-inter --windows-console-mode=disable --windows-uac-admin --include-data-files=data/usb.ids=data/usb.ids --include-data-files=data/pci.ids=data/pci.ids --output-dir=build gui_main.py
```

`--windows-uac-admin` embeds a `requireAdministrator` manifest so
Windows elevates the exe before it even starts. The two
`--include-data-files` flags are required — `hardware_ids.py` resolves
`data/usb.ids`/`data/pci.ids` relative to its own file at runtime, and
without them the packaged exe silently loses generic-driver name
resolution (falls back to Windows' own unhelpful names like "Generic
Bluetooth Adapter") with no error.

## Architecture

```
main.py                — CLI entry point: collect devices, run checks, print the report
gui_main.py             — GUI entry point: self-elevate via UAC, then launch the GUI
gui/
  app.py                — Tkinter window, results table, double-click dispatch (browser link / driver install)
  worker.py              — runs the scan on a background thread, posts progress to the GUI via a queue

board_detect.py         — auto-detects desktop motherboard vendor/model
laptop_detect.py        — auto-detects laptop vendor/model/serial number
scanner.py               — collects installed devices and driver versions (WMI/PowerShell), plus
                            Get-PnpDevice fallback lookups for devices Win32_PnPSignedDriver misses
hardware_ids.py          — resolves a better device name from bundled usb.ids/pci.ids when a device
                            is stuck on Windows' generic/inbox driver
driver_install.py        — downloads, unpacks, and installs a driver .cab via expand.exe/pnputil.exe
net_utils.py             — internet connectivity check, error classification
ps_utils.py              — shared PowerShell subprocess helper
orchestrator.py          — runs all checks in parallel, groups results by category

checks/
  common.py              — shared helpers (find_device, safe_get_latest, report, resolve_device_name, ...)
  bios.py, chipset.py, gpu.py, npu.py, audio.py, network.py, laptop.py
  registry.py             — CHECKS (registry of all checks) and CATEGORY_ORDER

providers/                — one file per source (vendor/chip website)
data/                     — bundled usb.ids/pci.ids hardware-ID registries
```

There are no manual-configuration files — everything is either
auto-detected from the hardware, or (where auto-detection is simply
not possible, e.g. the support page for a specific AMD GPU model) is
hardcoded directly in the relevant `checks/` module.

### Generic-driver name resolution

When a device is stuck on Windows' generic/inbox driver, Windows
reports an unhelpful name (e.g. "Generic Bluetooth Adapter") instead of
anything identifying the actual hardware. `checks/common.py`'s
`resolve_device_name` detects this (a hardcoded placeholder `DriverDate`
Windows' inbox drivers all share) and resolves a real vendor/product
name from the bundled `usb.ids`/`pci.ids` registries via the device's
VID/PID, applied across every check in the app.

Some composite USB devices' relevant sub-function (the audio codec on a
combo USB-audio device, a Bluetooth radio on a combo Bluetooth/WiFi
adapter) don't show up in the normal `Win32_PnPSignedDriver` device
scan at all. For those, `scanner.py` also offers `Get-PnpDevice`-based
fallback lookups — by a known vendor ID for audio
(`get_devices_by_id_pattern`), or by PNP device class for Bluetooth
(`get_devices_by_class`, since Bluetooth chips come from many vendors
with no single fixed ID to search for) — used automatically when the
primary scan doesn't find a match.

## Verification status by vendor

Some providers have been confirmed against real hardware (MSI, AMD,
NVIDIA, Intel, Realtek LAN, Acer, ASUS — page structure and version
comparison logic verified in practice). Others — Dell, Lenovo, HP, MSI
laptop, and Gigabyte laptop — were written from documented/
reverse-engineered API formats or (for HP and Gigabyte laptop) by
driving the real site with a browser and capturing its actual network
requests, but **have not been verified on real hardware**: this is
stated explicitly in each such provider's docstring
(`providers/dell_support.py`, `providers/lenovo_support.py`,
`providers/hp_support.py`). If you own
hardware from these vendors, feedback/PRs with real-world data are
welcome.

Microsoft Surface is a manual-link-only check (`providers/microsoft_surface.py`):
confirmed live that Surface devices don't expose per-component driver
downloads at all — everything (BIOS, drivers, firmware) ships as one
cumulative MSI package per model — so there's nothing to
version-compare, and the check just resolves the model to its official
download page from a hardcoded table sourced from Microsoft's own
documentation. That table will go stale as new Surface models ship and
needs periodic refreshing.

## Requirements

- Windows (uses `Get-CimInstance`/`Get-PnpDevice` via PowerShell)
- Python 3.10+
- `pip install -r requirements.txt` (requests, beautifulsoup4, curl_cffi)
- Administrator rights for the GUI app (only needed to install a driver
  update via `pnputil`; the CLI never needs elevation)

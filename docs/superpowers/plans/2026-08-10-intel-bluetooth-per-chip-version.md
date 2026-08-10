# Intel Bluetooth per-chip driver version matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `check_intel_bluetooth` from falsely flagging correctly-installed Bluetooth drivers as outdated by comparing against Intel's per-chip driver version (parsed from the download page's own "Purpose" section) instead of the generic package version.

**Architecture:** A new parser in `providers/intel_download.py` extracts the chip→version mapping from the same page `IntelDownloadCenterProvider` already fetches for LAN/WiFi/Chipset-fallback (a new `IntelBluetoothProvider` class does its own single fetch, reusing the existing `_find_meta` helper). `check_intel_bluetooth` (`checks/network.py`) then matches the installed chip's code — found by searching the Bluetooth device's name, falling back to the WiFi adapter's name on the same combo card — against that mapping, and substitutes the matched per-chip version in place of the package version before the existing `report()`/`no_downgrade_match` comparison. If no chip code is found, behavior is unchanged from today (compares against the package version).

**Tech Stack:** Python, `curl_cffi` (Chrome-impersonating HTTP client, already used for intel.com), `BeautifulSoup` (already a dependency).

## Global Constraints

- This codebase has no automated test suite (see `docs/superpowers/plans/2026-08-10-auto-scan-on-open.md`'s Global Constraints for the same note). Verification here is interpreter-based: parsing is verified against a static HTML fixture (captured live from Intel's page, embedded in the verification script so it doesn't depend on network access to re-check); the end-to-end check is verified once against the live page, matching how other providers in this codebase document "confirmed live" verification in their commit messages.
- Per the approved design doc (`docs/superpowers/specs/2026-08-10-intel-bluetooth-per-chip-version-design.md`): Killer-branded product codes and extending this approach to `check_intel_wifi` are explicitly out of scope.
- No hardcoded chip-code list — chip codes always come from parsing Intel's page at request time.

---

### Task 1: Parse the Purpose section and match a device name to its chip's versions

**Files:**
- Modify: `providers/intel_download.py` (add two module-level functions, after `_find_meta`, before `class IntelDownloadCenterProvider`)

**Interfaces:**
- Consumes: `BeautifulSoup` (already imported in this file), `re` (already imported).
- Produces:
  - `_parse_purpose_chip_versions(soup: BeautifulSoup) -> list[dict]` — each dict is `{"version": str, "chips": set[str]}`. Used by Task 2's `IntelBluetoothProvider.get_latest()`.
  - `find_chip_versions_for_device(chip_versions: list[dict], *device_names: str | None) -> list[str] | None` — used by Task 2's `check_intel_bluetooth`.

- [ ] **Step 1: Add the Purpose-section parser and chip-matching helper**

In `providers/intel_download.py`, add after `_find_meta` (before `class IntelDownloadCenterProvider`):

```python
_PURPOSE_LI_RE = re.compile(r"^Driver version\s+(\S+)\s*:\s*For\s+(.+)$", re.IGNORECASE)


def _parse_purpose_chip_versions(soup: BeautifulSoup) -> list[dict]:
    """
    Extracts the "Purpose" section's chip -> driver version mapping from
    an Intel download page's Detailed Description block (confirmed live
    on the Bluetooth driver page, download ID 18649), e.g.:
        "Driver version 24.60.0.4 : For BE213, BE211, ... AX211"
        "Driver version 24.40.11.1 : For AX411, AX211, ... 9260"
    -> [{"version": "24.60.0.4", "chips": {"BE213", "BE211", ..., "AX211"}}, ...]

    A single chip can legitimately appear in more than one entry (the
    same silicon paired with different platforms, e.g. AX211 on Panther
    Lake vs. Wildcat Lake) -- callers decide how to handle that.

    Scoped to the "Detailed Description" block (found via its <h2>
    heading) rather than the whole page, so an unrelated "Driver
    version ... : For ..." string elsewhere can't leak in. Returns []
    if the page doesn't have this section at all -- callers already
    treat an empty list as "no chip-specific data available" and fall
    back to the package-level version.
    """
    heading = soup.find(lambda tag: tag.name == "h2" and tag.get_text(strip=True) == "Detailed Description")
    if heading is None:
        return []
    container = heading.find_next("div")
    if container is None:
        return []

    entries = []
    for li in container.find_all("li"):
        text = li.get_text(" ", strip=True)
        m = _PURPOSE_LI_RE.match(text)
        if not m:
            continue
        version, chip_list = m.groups()
        chips = {c.strip().upper() for c in chip_list.split(",") if c.strip()}
        if chips:
            entries.append({"version": version, "chips": chips})
    return entries


def find_chip_versions_for_device(chip_versions: list[dict], *device_names) -> list[str] | None:
    """
    Given _parse_purpose_chip_versions's output and one or more device
    name strings to check (in priority order -- e.g. the Bluetooth
    device's own name, then a fallback like the WiFi adapter's name on
    the same combo card, since Bluetooth's own Windows name is
    typically generic -- confirmed live: "Intel(R) Wireless
    Bluetooth(R)", no chip code), returns every driver version Intel
    lists for whichever known chip code is found first, or None if none
    of the given names contain a chip code from chip_versions at all.
    """
    all_chips = {chip for entry in chip_versions for chip in entry["chips"]}
    for name in device_names:
        if not name:
            continue
        name_upper = name.upper()
        matched_chips = {chip for chip in all_chips if re.search(rf"\b{re.escape(chip)}\b", name_upper)}
        if matched_chips:
            return [entry["version"] for entry in chip_versions if entry["chips"] & matched_chips]
    return None
```

- [ ] **Step 2: Verify parsing against a static fixture of the real page structure**

Write `scratch_test_purpose_parse.py` (anywhere convenient, e.g. the scratchpad dir — not part of the repo) with the actual HTML captured live from `intel.com/.../18649/intel-wireless-bluetooth-drivers-for-windows-10-and-windows-11.html`'s Detailed Description block:

```python
from bs4 import BeautifulSoup
from providers.intel_download import _parse_purpose_chip_versions, find_chip_versions_for_device

FIXTURE_HTML = """
<h2>Detailed Description</h2>
<div>
<p><strong>Purpose<br/></strong></p>
<p>Intel Wireless Bluetooth is recommended for end-users.</p>
<p>Intel Wireless Bluetooth Package version 24.60.0</p>
<p>Windows 10 64-bit and Windows 11</p>
<ul>
<li>Driver version <strong>24.60.0.4</strong> : For BE213, BE211, BE202, BE201, BE200, AX231, AX211</li>
<li>Driver version <strong>24.40.11.1</strong> : For AX411, AX211, AX210, AX231, AX203, AX201, AX101, 9560, 9462, 9461, 9260</li>
<li><div><strong>AX231, AX211</strong>: 24.60.0.4 (Panther Lake platform), <strong>AX231</strong>: 24.40.11.1 (Wildcat Lake platform)</div></li>
<li>The drivers also work on Intel Killer products BE1775(i/s), BE1750(x/w).</li>
</ul>
<p><strong>Notes<br/></strong></p>
<ul>
<li>Some unrelated note that must NOT be picked up as a driver version entry.</li>
</ul>
</div>
"""

soup = BeautifulSoup(FIXTURE_HTML, "html.parser")
entries = _parse_purpose_chip_versions(soup)
print(entries)
assert len(entries) == 2, f"expected exactly 2 driver-version entries, got {len(entries)}"
assert entries[0] == {"version": "24.60.0.4", "chips": {"BE213", "BE211", "BE202", "BE201", "BE200", "AX231", "AX211"}}
assert entries[1]["version"] == "24.40.11.1"
assert "AX201" in entries[1]["chips"]
assert "9260" in entries[1]["chips"]

# AX201 (WiFi adapter's name, Bluetooth's own name is generic) -> only the 24.40.11.1 entry
result = find_chip_versions_for_device(entries, "Intel(R) Wireless Bluetooth(R)", "Intel(R) Wi-Fi 6 AX201 160MHz")
print(result)
assert result == ["24.40.11.1"], result

# AX211 appears in both entries (ambiguous platform) -> both versions returned
result = find_chip_versions_for_device(entries, None, "Intel(R) Wi-Fi 6E AX211 160MHz")
print(sorted(result))
assert sorted(result) == ["24.40.11.1", "24.60.0.4"], result

# unknown chip -> None
result = find_chip_versions_for_device(entries, "Intel(R) Wireless Bluetooth(R)", "Intel(R) Wi-Fi 6E AX999 160MHz")
assert result is None, result

print("all Task 1 checks passed")
```

Run it (with the project root on `PYTHONPATH` so `providers` resolves, using the project's venv):

```
PYTHONPATH="E:\Project\VerifyDriverGUI" ./build-venv312/Scripts/python.exe scratch_test_purpose_parse.py
```

Expected: prints the parsed entries and match results, ends with `all Task 1 checks passed`, no assertion errors.

- [ ] **Step 3: Commit**

```bash
git add providers/intel_download.py
git commit -m "Parse Intel's per-chip Bluetooth driver version list from its Purpose section"
```

---

### Task 2: Use the per-chip version in check_intel_bluetooth

**Files:**
- Modify: `checks/network.py:201-220` (`check_intel_bluetooth`)
- Modify: `providers/intel_download.py` (add `IntelBluetoothProvider`, after `class IntelDownloadCenterProvider`)

**Interfaces:**
- Consumes: `_parse_purpose_chip_versions`, `find_chip_versions_for_device` (Task 1), `_find_meta`, `DOWNLOAD_URL_TEMPLATE` (all already in `providers/intel_download.py`), `no_downgrade_match` (already imported in `checks/network.py`).
- Produces: nothing consumed elsewhere — this is the last task.

- [ ] **Step 1: Add `IntelBluetoothProvider`**

In `providers/intel_download.py`, add after `class IntelDownloadCenterProvider` (after its `get_latest` method, before `def get_current_intel_chipset_version`):

```python
class IntelBluetoothProvider(DriverProvider):
    """
    Like IntelDownloadCenterProvider, but also extracts the per-chip
    driver version list from the page's "Purpose" section (see
    _parse_purpose_chip_versions), so check_intel_bluetooth can match
    against the exact installed chip instead of just the overall
    package version -- those differ (e.g. package 24.60.0 ships both
    driver 24.60.0.4 and 24.40.11.1, for different chips).
    """
    name = "intel_bluetooth"

    def __init__(self, download_id: str, slug: str):
        self.download_id = download_id
        self.slug = slug

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        url = DOWNLOAD_URL_TEMPLATE.format(download_id=self.download_id, slug=self.slug)

        session = requests.Session(impersonate="chrome")
        resp = session.get(url, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        version = _find_meta(soup, "DownloadVersion")
        date = _find_meta(soup, "lastModifieddate")

        if version is None:
            return None

        return {
            "version": version, "date": date, "url": url,
            "chip_versions": _parse_purpose_chip_versions(soup),
        }
```

- [ ] **Step 2: Rewrite `check_intel_bluetooth`**

In `checks/network.py`, replace:

```python
def check_intel_bluetooth(devices, board, laptop):
    # IMPORTANT: Intel Bluetooth devices in Windows are listed under a
    # DIFFERENT PCI/USB Vendor ID — 8087, not 8086 (which is used for
    # WiFi/chipset/GPU) — confirmed on a real device.
    device = find_device_by_vendor_and_keywords(devices, "8087", ("BLUETOOTH",))
    if device is None:
        return None  # no Intel Bluetooth module in the system — silently skip
    current = device.get("DriverVersion")

    provider = IntelDownloadCenterProvider(
        download_id=INTEL_BLUETOOTH_DOWNLOAD_ID, slug=INTEL_BLUETOOTH_SLUG, name="intel_bluetooth"
    )
    ok, latest = safe_get_latest("Intel Bluetooth", provider)
    if not ok:
        latest = None
    return report(
        "Intel Bluetooth", latest, current, comparator=no_downgrade_match,
        page_url=intel_download_url(INTEL_BLUETOOTH_DOWNLOAD_ID, INTEL_BLUETOOTH_SLUG),
        device_name=device.get("DeviceName"), current_date=device.get("DriverDate"),
    )
```

with:

```python
def check_intel_bluetooth(devices, board, laptop):
    # IMPORTANT: Intel Bluetooth devices in Windows are listed under a
    # DIFFERENT PCI/USB Vendor ID — 8087, not 8086 (which is used for
    # WiFi/chipset/GPU) — confirmed on a real device.
    device = find_device_by_vendor_and_keywords(devices, "8087", ("BLUETOOTH",))
    if device is None:
        return None  # no Intel Bluetooth module in the system — silently skip
    current = device.get("DriverVersion")

    provider = IntelBluetoothProvider(download_id=INTEL_BLUETOOTH_DOWNLOAD_ID, slug=INTEL_BLUETOOTH_SLUG)
    ok, latest = safe_get_latest("Intel Bluetooth", provider)
    if not ok:
        latest = None

    if latest is not None and latest.get("chip_versions"):
        # Bluetooth's own Windows name is typically generic (confirmed
        # live: "Intel(R) Wireless Bluetooth(R)", no chip code) — fall
        # back to the WiFi adapter's name on the same combo card, which
        # does include it (e.g. "Intel(R) Wi-Fi 6 AX201 160MHz")
        wifi_device = find_device_by_vendor_and_keywords(devices, "8086", ("WI-FI", "WIRELESS"))
        chip_versions = find_chip_versions_for_device(
            latest["chip_versions"],
            device.get("DeviceName"),
            wifi_device.get("DeviceName") if wifi_device else None,
        )
        if chip_versions:
            # up to date if the installed version matches (or isn't
            # older than) ANY version Intel lists for this chip — some
            # chips are documented under two platform-specific versions
            # (e.g. AX211 on Panther Lake vs. Wildcat Lake) and a
            # Windows device name alone can't tell us which platform;
            # only suggest an update, to the newest matched version, if
            # the installed one is older than all of them
            if any(no_downgrade_match(current, v) for v in chip_versions):
                matched_version = current
            else:
                matched_version = max(chip_versions, key=lambda v: [int(p) for p in v.split(".")])
            latest = {**latest, "version": matched_version}

    return report(
        "Intel Bluetooth", latest, current, comparator=no_downgrade_match,
        page_url=intel_download_url(INTEL_BLUETOOTH_DOWNLOAD_ID, INTEL_BLUETOOTH_SLUG),
        device_name=device.get("DeviceName"), current_date=device.get("DriverDate"),
    )
```

Add `IntelBluetoothProvider` and `find_chip_versions_for_device` to the existing import line at the top of `checks/network.py`:

```python
from providers.intel_download import IntelDownloadCenterProvider, intel_download_url
```
becomes:
```python
from providers.intel_download import (
    IntelDownloadCenterProvider, IntelBluetoothProvider, find_chip_versions_for_device, intel_download_url,
)
```

- [ ] **Step 3: Verify against the real reported case (live network)**

Write `scratch_test_bt_repro.py`:

```python
from checks.chipset import check_intel_chipset  # unused, just confirms PYTHONPATH is set correctly
from checks.network import check_intel_bluetooth

# the exact real device pair reported: AX201 combo card, Bluetooth
# driver 24.40.11.1 -- which Intel's own Purpose section lists as
# correct for AX201, so this must come back "Up to date", not
# "Download update"
bt_device = {
    "VendorID": "8087", "DeviceName": "Intel(R) Wireless Bluetooth(R)",
    "DriverVersion": "24.40.11.1", "DriverDate": "20260207020000.000000-000",
}
wifi_device = {
    "VendorID": "8086", "DeviceName": "Intel(R) Wi-Fi 6 AX201 160MHz",
    "DriverVersion": "24.60.0.3", "DriverDate": "20261106020000.000000-000",
}
result = check_intel_bluetooth([bt_device, wifi_device], {}, {"is_laptop": False})
print(result)
assert result.status == "Up to date", f"expected Up to date, got {result.status!r}: {result}"
assert result.current.startswith("24.40.11.1"), result.current

# a genuinely outdated chip should still be flagged — use a chip in the
# 24.40.11.1 list with an older-than-either-version current version
old_device = {**bt_device, "DriverVersion": "23.50.0.1"}
result2 = check_intel_bluetooth([old_device, wifi_device], {}, {"is_laptop": False})
print(result2)
assert result2.status == "Download update", f"expected Download update, got {result2.status!r}: {result2}"

print("all Task 2 checks passed")
```

Run it:

```
PYTHONPATH="E:\Project\VerifyDriverGUI" ./build-venv312/Scripts/python.exe scratch_test_bt_repro.py
```

Expected: prints both results, ends with `all Task 2 checks passed`. This hits the live Intel page once (network required).

- [ ] **Step 4: Commit**

```bash
git add checks/network.py providers/intel_download.py
git commit -m "Match Intel Bluetooth's installed chip to its correct per-chip driver version"
```

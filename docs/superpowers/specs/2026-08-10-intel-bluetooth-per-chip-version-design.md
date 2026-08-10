# Intel Bluetooth per-chip driver version matching

## Problem

`check_intel_bluetooth` (`checks/network.py`) compares the installed
Bluetooth driver version against Intel's *package* version (e.g.
`24.60.0`, from the `DownloadVersion` meta tag on Intel's download
page), not the version of the specific driver file actually shipped for
the installed chip. Intel's package bundles multiple driver builds per
release — e.g. package `24.60.0` ships both `24.60.0.4` (for
BE213/BE211/BE202/BE201/BE200/AX231/AX211) and `24.40.11.1` (for
AX411/AX211/AX210/AX231/AX203/AX201/AX101/9560/9462/9461/9260).

Confirmed live on a real machine: an Intel Wi-Fi 6 AX201 combo card
correctly running Bluetooth driver `24.40.11.1` (exactly what Intel's
own page says is correct for AX201) gets falsely flagged as "Download
update available" because `24.40.11.1` numerically compares as older
than the package version `24.60.0`.

This is the same class of bug already fixed for Intel Chipset (package
version vs. per-component version) — see
`docs/superpowers/specs/` git history — but here Intel's own download
page already contains the chip→version mapping (a "Purpose" section in
the page's Detailed Description), so no third-party database is needed.

## Design

### 1. Parse the Purpose section

A new parser (in `providers/intel_download.py`, alongside the existing
`IntelDownloadCenterProvider` — same page, different content, so no
separate HTTP fetch) reads the "Detailed Description" HTML block and
extracts each `Driver version <X.X.X.X> : For <chip list>` list item
into `[(version, {chip_codes}), ...]`. Confirmed live structure:

```html
<p><strong>Purpose</strong></p>
...
<ul>
<li>Driver version <strong>24.60.0.4</strong> : For BE213, BE211, BE202, BE201, BE200, AX231, AX211</li>
<li>Driver version <strong>24.40.11.1</strong> : For AX411, AX211, AX210, AX231, AX203, AX201, AX101, 9560, 9462, 9461, 9260</li>
...
</ul>
```

Parsing stops at the next `<strong>` heading after "Purpose" (e.g.
"Notes"), so it doesn't accidentally sweep up unrelated list items.

### 2. Chip identification

Confirmed live: the Bluetooth device's own Windows name is generic
(`Intel(R) Wireless Bluetooth(R)`, no chip code), while the WiFi
adapter on the same combo card includes it (`Intel(R) Wi-Fi 6 AX201
160MHz`). `check_intel_bluetooth` gets the chip code by searching for
any code from the parsed Purpose list as a whole-word match — first in
the Bluetooth device's own name (defensive, in case a future/OEM device
does include it), then in the matching WiFi device found via the same
`find_device_by_vendor_and_keywords(devices, "8086", ("WI-FI",
"WIRELESS"))` lookup `check_intel_wifi` already uses. No hardcoded chip
list — the codes come from Intel's page itself every time, so the
matching logic doesn't go stale as Intel adds new chips.

### 3. Ambiguity (a chip listed under two versions)

Some chips (AX231, AX211) appear under two different driver versions
for two different platforms (Panther Lake vs. Wildcat Lake), which
isn't reliably distinguishable from a Windows device name. Once a chip
code is identified, collect *all* versions Intel lists for it. The
installed version is considered up to date if it matches (or,
per-version, is not older than) any one of them; only report "update
available" if it's older than all of them — and point at the newest of
the matched versions as the suggested update.

### 4. Fallback

If no chip code from the Purpose list is found in either device name
(older/unlisted chip, or an Intel Killer-branded product — the page
lists Killer product codes but doesn't map them to a specific driver
version), fall back to today's behavior: compare against the package
version. Same heuristic imprecision as today for that case, not a
regression.

## Out of scope

- Killer-branded product code matching (no version mapping given in the
  source page to key off of).
- Applying the same per-chip Purpose-section approach to `check_intel_wifi`
  (separate download page; worth doing later, not part of this change).

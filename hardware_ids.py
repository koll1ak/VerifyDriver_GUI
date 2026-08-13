"""
Looks up a hardware vendor/product name from bundled snapshots of the
standard usb.ids/pci.ids registries (data/usb.ids, data/pci.ids) -- the
same databases Linux, Wireshark, and most other tools use. Used as a
fallback ONLY for devices stuck on Windows' generic/inbox driver, whose
own reported name is unhelpful (e.g. "Generic Bluetooth Adapter") -- see
checks/common.py's resolve_device_name.

Both files share the same syntax:
    0489  Foxconn / Hon Hai          <- vendor line, no leading whitespace
    \td00c  Rollei ...               <- device line, exactly one leading tab
    \t\t00  some interface           <- deeper-indented lines (interfaces,
                                         subvendor sub-entries) are ignored
"""

import os

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

_USB_IDS_PATH = os.path.join(_DATA_DIR, "usb.ids")
_PCI_IDS_PATH = os.path.join(_DATA_DIR, "pci.ids")


def _parse_ids_file(path):
    """
    Parses a usb.ids/pci.ids-format file into
    {vendor_hex: (vendor_name, {device_hex: device_name})}, all hex keys
    lowercased. Returns {} if the file can't be read -- missing/corrupt
    bundled data must never crash the app, it just means name resolution
    silently finds nothing, same as an unrecognized ID.
    """
    vendors = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return vendors

    current_vendor_hex = None
    for raw_line in lines:
        line = raw_line.rstrip("\n").rstrip("\r")
        if not line or line.startswith("#"):
            continue
        if line.startswith("\t\t"):
            continue  # interface/subvendor line, not needed
        if line.startswith("\t"):
            if current_vendor_hex is None:
                continue
            device_hex, _, device_name = line[1:].partition("  ")
            device_hex = device_hex.strip().lower()
            device_name = device_name.strip()
            if device_hex and device_name:
                vendors[current_vendor_hex][1][device_hex] = device_name
            continue
        # top-level vendor line
        vendor_hex, _, vendor_name = line.partition("  ")
        vendor_hex = vendor_hex.strip().lower()
        vendor_name = vendor_name.strip()
        if vendor_hex and vendor_name:
            vendors[vendor_hex] = (vendor_name, {})
            current_vendor_hex = vendor_hex
        else:
            current_vendor_hex = None  # malformed line, don't attribute devices to it

    return vendors


_usb_vendors = None
_pci_vendors = None


def _usb_db():
    global _usb_vendors
    if _usb_vendors is None:
        _usb_vendors = _parse_ids_file(_USB_IDS_PATH)
    return _usb_vendors


def _pci_db():
    global _pci_vendors
    if _pci_vendors is None:
        _pci_vendors = _parse_ids_file(_PCI_IDS_PATH)
    return _pci_vendors


def lookup(namespace: str, vendor_hex: str | None, product_hex: str | None) -> tuple[str | None, str | None]:
    """
    namespace: "usb" or "pci" -- PCI and HD Audio codec vendor IDs share
    the PCI-SIG vendor ID space, so HDAUDIO devices use "pci" too (see
    checks/common.py's resolve_device_name for how namespace is picked).
    Returns (vendor_name, product_name) -- either may be None if not
    found. vendor_hex/product_hex are case-insensitive 4-hex strings.
    """
    if not vendor_hex:
        return None, None
    db = _usb_db() if namespace == "usb" else _pci_db()
    entry = db.get(vendor_hex.lower())
    if entry is None:
        return None, None
    vendor_name, devices = entry
    product_name = devices.get(product_hex.lower()) if product_hex else None
    return vendor_name, product_name

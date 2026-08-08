import sys

from net_utils import classify_error
from checks.common import report, overall_drivers_page_url
from providers.msi_bios import MsiBiosProvider, get_current_bios_version
from providers.gigabyte_bios import GigabyteBiosProvider
from providers.asus_bios import AsusBiosProvider


def _asus_desktop_bios_versions_match(current: str, latest: str) -> bool:
    """
    For desktop ASUS boards, the version on the site and in Windows is a
    plain number with no prefix (e.g. "2403" installed, "3004" on the
    site), unlike ASUS laptops (where the version has a board-model
    prefix). Confirmed on a real device.
    """
    if not current or not latest:
        return False
    try:
        return int(current.strip()) == int(latest.strip())
    except ValueError:
        return current.strip() == latest.strip()


def _bios_versions_match(current: str, latest: str) -> bool:
    """
    Windows returns the BIOS version in a shortened form (e.g. "1.A92"),
    while MSI's site shows the full code with the board model (e.g.
    "7E51v1A92"). We compare the "tail" after 'v' from the site against
    the Windows version with dots stripped.
    """
    if not current or not latest:
        return False
    tail = latest.split("v")[-1] if "v" in latest else latest
    return current.replace(".", "").upper() == tail.replace(".", "").upper()


def check_bios(devices, board, laptop):
    # on laptops Win32_BaseBoard often returns garbage instead of the
    # actual board vendor (e.g. a reference-platform codename) — real
    # BIOS support for laptops is covered by separate vendor-specific
    # checks (check_dell_bios, check_acer_bios, etc.), this function is
    # for desktops
    if laptop.get("is_laptop"):
        return None

    vendor = board.get("vendor")

    if vendor == "msi":
        slug = board.get("msi_slug")
        if slug is None:
            print("[BIOS] MSI: could not determine the board model", file=sys.stderr)
            return None
        try:
            latest = MsiBiosProvider(product_slug=slug).get_latest()
        except Exception as e:
            print(f"[BIOS] error (MSI): {classify_error(e)}", file=sys.stderr)
            return None
        return report("BIOS", latest, get_current_bios_version(), comparator=_bios_versions_match)

    if vendor == "gigabyte":
        slug = board.get("gigabyte_slug")
        if slug is None:
            print("[BIOS] Gigabyte: could not determine the board model", file=sys.stderr)
            return None
        try:
            latest = GigabyteBiosProvider(product_slug=slug).get_latest()
        except Exception as e:
            print(f"[BIOS] error (Gigabyte): {classify_error(e)}", file=sys.stderr)
            return None
        # no reliable way yet to compare against the installed version
        # (Windows doesn't give a single BIOS code in a predictable
        # format for Gigabyte)
        return report("BIOS", latest, current=None)

    if vendor == "asrock":
        model = board.get("asrock_model")
        if model is None:
            print("[BIOS] ASRock: could not determine the board model", file=sys.stderr)
            return None
        # automatic checking isn't possible: confirmed live that ASRock's
        # site is blocked by Incapsula (a JS-challenge bot-protection
        # system) — curl_cffi's Chrome TLS impersonation, which works
        # for the Akamai-protected sites elsewhere (Gigabyte/Lenovo/
        # MSI), does NOT get past it. Worse, the block returns HTTP 200
        # with a fake page instead of a clean error, so it silently
        # looks exactly like "board not found" rather than "blocked" —
        # same underlying situation as Dell, same fix: a manual link
        # instead of a check that can never actually succeed.
        url = overall_drivers_page_url(board, laptop)
        return f"[ASRock BIOS] automatic check unavailable — visit the site manually: {url}", None

    if vendor == "asus":
        model = board.get("asus_model")
        if model is None:
            print("[BIOS] ASUS: could not determine the board model", file=sys.stderr)
            return None
        try:
            latest = AsusBiosProvider(model=model).get_latest()
        except Exception as e:
            print(f"[BIOS] error (ASUS): {classify_error(e)}", file=sys.stderr)
            return None
        return report("BIOS", latest, get_current_bios_version(), comparator=_asus_desktop_bios_versions_match)

    print(f"[BIOS] board vendor not recognized (manufacturer: {board.get('manufacturer_raw')})", file=sys.stderr)
    return None

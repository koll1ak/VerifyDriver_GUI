import sys

from scanner import get_installed_devices
from net_utils import has_internet_connection
from board_detect import detect_board
from laptop_detect import detect_laptop
from checks.common import overall_drivers_page_url
from checks.registry import CATEGORY_ORDER
from orchestrator import run_checks, group_by_category


def main():
    # on some systems (non-UTF8 console locale) output may contain
    # characters not present in the console encoding — switch stdout/stderr
    # to UTF-8 with replacement of unreadable characters instead of crashing
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    if not has_internet_connection():
        print(
            "No internet connection — cannot check for updates.\n"
            "Check your network and try again.",
            file=sys.stderr,
        )
        return

    print("Scanning hardware and drivers...")

    devices = get_installed_devices()
    board = detect_board()
    laptop = detect_laptop()

    # each check doesn't print by itself, it RETURNS (display, update) —
    # all printing happens here, after everything finishes, in a fixed
    # order by category (not by completion speed)
    results = run_checks(devices, board, laptop)
    display_by_category, updates_by_category = group_by_category(results, CATEGORY_ORDER)

    for category in CATEGORY_ORDER:
        for line in display_by_category[category]:
            print(line)

    any_updates = any(updates_by_category[category] for category in CATEGORY_ORDER)

    if any_updates:
        print("\n=== Updates available ===")
        for category in CATEGORY_ORDER:
            for line in updates_by_category[category]:
                print(line)
    else:
        print("\nEverything is up to date (where a comparison was possible).")

    drivers_url = overall_drivers_page_url(board, laptop)
    if drivers_url:
        print(f"\nPage with all available drivers for this device: {drivers_url}")


if __name__ == "__main__":
    main()

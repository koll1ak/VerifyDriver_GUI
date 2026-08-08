import sys
import concurrent.futures

from scanner import get_installed_devices
from net_utils import has_internet_connection, classify_error
from board_detect import detect_board
from laptop_detect import detect_laptop
from checks.common import overall_drivers_page_url
from checks.registry import CATEGORY_ORDER, CHECKS


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

    # checks are independent of each other and mostly network-bound (I/O) —
    # run them all in parallel instead of waiting for each sequentially.
    # Each check doesn't print by itself, it RETURNS (display, update) —
    # all printing happens here, after everything finishes, in a fixed
    # order by category (not by completion speed).
    results = []  # [(category, display_line, update_line), ...]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(CHECKS)) as executor:
        future_to_category = {
            executor.submit(check, devices, board, laptop): category
            for category, check in CHECKS
        }
        for future in concurrent.futures.as_completed(future_to_category):
            category = future_to_category[future]
            try:
                result = future.result()
            except Exception as e:
                print(f"[{category}] unexpected error: {classify_error(e)}", file=sys.stderr)
                result = None
            if result is None:
                continue  # silent skip (device not found, etc.)
            display_line, update_line = result
            results.append((category, display_line, update_line))

    display_by_category = {category: [] for category in CATEGORY_ORDER}
    updates_by_category = {category: [] for category in CATEGORY_ORDER}
    for category, display_line, update_line in results:
        display_by_category.setdefault(category, []).append(display_line)
        if update_line:
            updates_by_category.setdefault(category, []).append(update_line)

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

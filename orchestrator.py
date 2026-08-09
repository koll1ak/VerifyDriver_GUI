import sys
import concurrent.futures

from net_utils import classify_error
from checks.registry import CHECKS


def run_checks(devices, board, laptop, on_error=None):
    """
    Runs every check in CHECKS in parallel (checks are independent of each
    other and mostly network-bound, see checks/registry.py). Returns the
    full list of (category, CheckResult) pairs, in completion order —
    callers that need a fixed display order (the CLI, the GUI) re-group
    by CATEGORY_ORDER themselves via group_pairs_by_category().

    on_error(category, message): called instead of the default stderr
    print when a check raises. Optional; omitting it reproduces main.py's
    original behavior exactly.
    """
    results = []
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
                message = classify_error(e)
                if on_error:
                    on_error(category, message)
                else:
                    print(f"[{category}] unexpected error: {message}", file=sys.stderr)
                continue
            if result is None:
                continue  # silent skip (device not found, etc.)
            results.append((category, result))
    return results


def group_pairs_by_category(pairs, category_order):
    """
    Groups (category, item) pairs into {category: [item, ...]}, in
    category_order -- generic over whatever "item" is (a CheckResult for
    the GUI's table, an error message string for its error list, ...).
    """
    grouped = {category: [] for category in category_order}
    for category, item in pairs:
        grouped.setdefault(category, []).append(item)
    return grouped


def group_by_category(results, category_order):
    """
    Groups (category, CheckResult) pairs the way the CLI presents them:
    display lines and update lines (only where a check actually found
    one), each per category in category_order. Returns plain strings
    (result.display_line/.update_line) -- this is what the CLI prints
    directly, unchanged from before this project had a GUI.
    """
    by_category = group_pairs_by_category(results, category_order)
    display_by_category = {c: [r.display_line for r in items] for c, items in by_category.items()}
    updates_by_category = {c: [r.update_line for r in items if r.update_line] for c, items in by_category.items()}
    return display_by_category, updates_by_category

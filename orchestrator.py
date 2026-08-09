import sys
import concurrent.futures

from net_utils import classify_error
from checks.registry import CHECKS


def run_checks(devices, board, laptop, on_result=None, on_error=None):
    """
    Runs every check in CHECKS in parallel (checks are independent of each
    other and mostly network-bound, see checks/registry.py). Returns the
    full list of (category, display_line, update_line) tuples, in
    completion order — callers that need a fixed display order (the CLI)
    re-group by CATEGORY_ORDER themselves.

    on_result(category, display_line, update_line): called once per
    successful, non-None result, as soon as each check completes — lets a
    caller (the GUI) show progress instead of waiting for everything to
    finish. Optional; omitting it just skips the progress callback.

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
            display_line, update_line = result
            results.append((category, display_line, update_line))
            if on_result:
                on_result(category, display_line, update_line)
    return results


def group_by_category(results, category_order):
    """
    Groups (category, display_line, update_line) tuples the way both the
    CLI and the GUI present them: display lines and update lines (only
    where a check actually found one), each per category in category_order.
    """
    display_by_category = {category: [] for category in category_order}
    updates_by_category = {category: [] for category in category_order}
    for category, display_line, update_line in results:
        display_by_category.setdefault(category, []).append(display_line)
        if update_line:
            updates_by_category.setdefault(category, []).append(update_line)
    return display_by_category, updates_by_category

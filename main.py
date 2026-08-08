import sys
import concurrent.futures

from scanner import get_installed_devices
from net_utils import has_internet_connection, classify_error
from board_detect import detect_board
from laptop_detect import detect_laptop
from checks.common import overall_drivers_page_url
from checks.registry import CATEGORY_ORDER, CHECKS


def main():
    # на некоторых системах (не-UTF8 локаль консоли) вывод может содержать
    # символы, которых нет в кодировке консоли — переключаем stdout/stderr
    # на UTF-8 с заменой нечитаемых символов вместо падения программы
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    if not has_internet_connection():
        print(
            "Нет подключения к интернету — проверка обновлений невозможна.\n"
            "Проверь сеть и попробуй снова.",
            file=sys.stderr,
        )
        return

    print("Выполняем поиск оборудования и драйверов...")

    devices = get_installed_devices()
    board = detect_board()
    laptop = detect_laptop()

    # проверки независимы друг от друга и в основном сетевые (I/O-bound) —
    # запускаем все параллельно вместо последовательного ожидания каждой.
    # Каждая проверка не печатает сама, а ВОЗВРАЩАЕТ (display, update) —
    # печать всего разом делаем здесь, после того как все завершатся, в
    # фиксированном порядке по категориям (а не по скорости выполнения).
    results = []  # [(категория, display_line, update_line), ...]
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
                print(f"[{category}] неожиданная ошибка: {classify_error(e)}", file=sys.stderr)
                result = None
            if result is None:
                continue  # молчаливый пропуск (устройство не найдено и т.п.)
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
        print("\n=== Найдены обновления ===")
        for category in CATEGORY_ORDER:
            for line in updates_by_category[category]:
                print(line)
        # TODO: подключить уведомление (Telegram/toast)
    else:
        print("\nВсё установлено актуально (там, где сверка возможна).")

    drivers_url = overall_drivers_page_url(board, laptop)
    if drivers_url:
        print(f"\nСтраница со всеми доступными драйверами для устройства: {drivers_url}")


if __name__ == "__main__":
    main()

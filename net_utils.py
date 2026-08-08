"""
Общие утилиты для сетевых проверок: быстрая проверка интернета перед
основным прогоном и классификация ошибок в понятные сообщения — чтобы
при отсутствии сети не получить 10 разных непонятных traceback-ов
подряд, а одно ясное сообщение.
"""

import socket


def has_internet_connection(timeout: float = 3.0) -> bool:
    """
    Быстрая проверка: получается ли вообще открыть TCP-соединение наружу.
    Не проверяет доступность конкретных сайтов вендоров (они могут быть
    недоступны и при рабочем интернете) — только сам факт наличия сети.
    """
    hosts_to_try = [
        ("1.1.1.1", 443),   # Cloudflare
        ("8.8.8.8", 443),   # Google DNS
    ]
    for host, port in hosts_to_try:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def classify_error(exc: Exception) -> str:
    """
    Превращает исключение (из requests, curl_cffi или сети вообще)
    в короткое понятное сообщение на русском.
    """
    exc_name = type(exc).__name__
    exc_text = str(exc)

    # requests / curl_cffi поднимают исключения с похожими именами классов —
    # проверяем по названию типа, чтобы не зависеть от того, какая именно
    # библиотека использована в конкретном провайдере
    if "Timeout" in exc_name:
        return "сайт не отвечает (таймаут)"

    if "ConnectionError" in exc_name or "ConnectError" in exc_name:
        return "не удалось подключиться (сайт недоступен или проблема с сетью)"

    if "HTTPError" in exc_name or "HTTPStatusError" in exc_name:
        # пытаемся вытащить код статуса из текста, если он там есть
        if "403" in exc_text:
            return "доступ запрещён (403) — сайт заблокировал запрос"
        if "404" in exc_text:
            return "страница не найдена (404) — возможно, сменился URL/модель"
        if "500" in exc_text or "502" in exc_text or "503" in exc_text:
            return "сайт вернул ошибку сервера (сайт временно недоступен)"
        return f"сайт вернул ошибку: {exc_text}"

    if "JSONDecodeError" in exc_name or "JSONDecode" in exc_name:
        return "сайт отдал не тот формат данных, что ожидался (возможно, изменилась структура страницы)"

    if "SSLError" in exc_name or "SSL" in exc_name:
        return "ошибка SSL-соединения"

    # неизвестная ошибка — показываем как есть, но без полного traceback
    return f"неизвестная ошибка ({exc_name}: {exc_text})"

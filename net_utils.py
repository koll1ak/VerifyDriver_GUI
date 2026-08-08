"""
Shared utilities for network checks: a quick internet check before the
main run, and classification of errors into readable messages — so that
when there's no network you get one clear message instead of ten
different confusing tracebacks in a row.
"""

import socket


def has_internet_connection(timeout: float = 3.0) -> bool:
    """
    Quick check: can we open an outbound TCP connection at all.
    Does not check the availability of specific vendor sites (they can
    be unreachable even with a working internet connection) — only
    whether there's a network at all.
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
    Turns an exception (from requests, curl_cffi, or the network in
    general) into a short, readable message.
    """
    exc_name = type(exc).__name__
    exc_text = str(exc)

    # requests / curl_cffi raise exceptions with similarly-named classes —
    # check by type name so we don't depend on which specific library a
    # given provider happens to use
    if "Timeout" in exc_name:
        return "site is not responding (timeout)"

    if "ConnectionError" in exc_name or "ConnectError" in exc_name:
        return "could not connect (site unreachable or a network issue)"

    if "HTTPError" in exc_name or "HTTPStatusError" in exc_name:
        # try to pull the status code out of the text if it's there
        if "403" in exc_text:
            return "access denied (403) — the site blocked the request"
        if "404" in exc_text:
            return "page not found (404) — the URL/model may have changed"
        if "500" in exc_text or "502" in exc_text or "503" in exc_text:
            return "the site returned a server error (temporarily unavailable)"
        return f"the site returned an error: {exc_text}"

    if "JSONDecodeError" in exc_name or "JSONDecode" in exc_name:
        return "the site returned an unexpected data format (the page structure may have changed)"

    if "SSLError" in exc_name or "SSL" in exc_name:
        return "SSL connection error"

    # unknown error — show it as-is, but without a full traceback
    return f"unknown error ({exc_name}: {exc_text})"

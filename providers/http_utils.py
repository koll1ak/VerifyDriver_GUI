"""
Shared HTTP constants for the providers — a single User-Agent and
timeout so we don't duplicate the same thing in every file.
"""

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {"User-Agent": DEFAULT_USER_AGENT}

DEFAULT_TIMEOUT = 20

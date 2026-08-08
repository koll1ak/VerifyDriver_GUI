class DriverProvider:
    """
    Base provider interface.
    matches()   — decides whether a device from the scanner belongs to this vendor
    get_latest() — returns the current version from an external source
    """

    name = "base"

    def matches(self, device: dict) -> bool:
        raise NotImplementedError

    def get_latest(self, device: dict) -> dict | None:
        """
        Should return a dict shaped like:
        {"version": "576.88", "date": "2026-06-01", "url": "https://..."}
        or None if no data could be found.
        """
        raise NotImplementedError

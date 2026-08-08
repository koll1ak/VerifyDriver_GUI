class DriverProvider:
    """
    Базовый интерфейс провайдера.
    matches()   — решает, относится ли устройство из сканера к этому вендору
    get_latest() — возвращает актуальную версию из внешнего источника
    """

    name = "base"

    def matches(self, device: dict) -> bool:
        raise NotImplementedError

    def get_latest(self, device: dict) -> dict | None:
        """
        Должен вернуть dict вида:
        {"version": "576.88", "date": "2026-06-01", "url": "https://..."}
        или None, если не удалось найти данные.
        """
        raise NotImplementedError

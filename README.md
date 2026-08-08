# VerifyDriver (driver-watch)

Автономный Python-скрипт для Windows: проверяет актуальность драйверов
сразу по множеству категорий и вендоров, без ручного ввода данных —
всё, что нужно, определяется автоматически по железу конкретной машины.

## Что проверяется

| Категория | Источники |
|---|---|
| BIOS | MSI, Gigabyte, ASRock, ASUS (десктоп) · Dell, Acer, ASUS, Lenovo, Huawei (ноутбуки, ссылка вручную) |
| Chipset | AMD, Intel |
| Integrated GPU | Intel |
| GPU | NVIDIA, AMD, Intel |
| Audio | Страница вендора платы (MSI/Gigabyte/ASRock/ASUS) → Microsoft Update Catalog как fallback · Dell, Acer, ASUS, Lenovo (ноутбуки) · SenaryTech |
| LAN | Realtek (PCIe + USB), Intel, Acer (Killer/Realtek/Intel) |
| WiFi | Intel, Realtek, Microsoft Update Catalog (не-Intel чипы), ASUS Networking |
| Bluetooth | Intel, Microsoft Update Catalog (не-Intel чипы) |

Проверки выполняются параллельно (`ThreadPoolExecutor`), вывод
собирается и печатается разом после завершения всех — в фиксированном
порядке по категориям, а не по скорости отклика конкретного сайта.

## Установка

```bash
pip install -r requirements.txt
```

## Запуск

```bash
python main.py
```

## Архитектура

```
main.py              — точка входа: сбор устройств, запуск проверок, печать отчёта
board_detect.py       — автоопределение вендора/модели материнской платы (десктоп)
laptop_detect.py       — автоопределение вендора/модели/серийника ноутбука
scanner.py              — сбор установленных устройств и версий драйверов (WMI)
net_utils.py             — проверка интернет-соединения, классификация ошибок

checks/
  common.py            — общие хелперы (find_device, safe_get_latest, report, ...)
  bios.py, chipset.py, gpu.py, audio.py, network.py, laptop.py
  registry.py           — CHECKS (реестр всех проверок) и CATEGORY_ORDER

providers/              — по одному файлу на источник (сайт вендора/чипа)
```

Никаких файлов с ручными настройками нет — всё либо автоопределяется
по железу, либо (где автоопределение в принципе невозможно, например
страница поддержки конкретной модели видеокарты AMD) прописано прямо в
соответствующем модуле `checks/`.

## Статус проверенности по вендорам

Часть провайдеров подтверждена на реальном железе (MSI, AMD, NVIDIA,
Intel, Realtek LAN, Acer, ASUS — структура страниц и формат сравнения
версий проверены по факту). Другая часть — Dell и Lenovo — написана по
задокументированному или подсмотренному в сторонних open-source
инструментах формату API/страницы, но **не проверена на реальном
устройстве**: это явно указано в докстринге каждого такого провайдера
(`providers/dell_support.py`, `providers/lenovo_support.py`). Если у
вас есть техника этих вендоров — присылайте фидбек/PR с реальными
данными.

## Требования

- Windows (используются `Get-CimInstance`/WMI через PowerShell)
- Python 3.10+
- `pip install -r requirements.txt` (requests, beautifulsoup4, curl_cffi)

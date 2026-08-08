"""
Провайдер для точного сравнения версии Intel Chipset — использует открытую
community-базу (не официальный источник Intel, но общедоступный и
регулярно обновляемый проект), которая ведёт версию INF-файла отдельно
для КАЖДОЙ платформы (по Hardware ID), а не только версию пакета целиком.

    https://raw.githubusercontent.com/FirstEverTech/Universal-Intel-Chipset-Updater/main/data/intel-chipset-infs-latest.md

Почему это решает проблему, с которой мы бились раньше: версия пакета
Intel Chipset Device Software (например "10.1.20658.8883") никак не
соотносится с версией конкретного установленного компонента (например
"10.1.31.3" для CometLake PCH-H) — это разные системы счёта, и пакет
может обновиться, даже не тронув версию для конкретно твоего поколения
процессора. Эта база даёт версию именно компонента — ту же систему
счёта, что видна в установленной системе — поэтому сравнение получается
осмысленным.

Источник: https://github.com/FirstEverTech/Universal-Intel-Chipset-Updater
Автор: Marcin Grygiel
"""

import re

import requests

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

DB_URL = "https://raw.githubusercontent.com/FirstEverTech/Universal-Intel-Chipset-Updater/main/data/intel-chipset-infs-latest.md"

_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")


def _clean_cell(cell: str) -> str:
    # убираем markdown-экранирование ("\_" -> "_") и лишние пробелы/звёздочки
    return cell.replace("\\_", "_").replace("\\*", "").strip()


def _parse_database(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        m = _TABLE_ROW_RE.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) != 5:
            continue
        inf_cell, package_cell, version_cell, date_cell, hwids_cell = cells

        if not set(package_cell) <= set("-: "):  # пропускаем строку-разделитель таблицы
            if ".inf" not in inf_cell.lower():
                continue  # не строка с данными (например заголовок)
            hwids = [
                _clean_cell(h).upper()
                for h in hwids_cell.split(",")
                if _clean_cell(h)
            ]
            rows.append({
                "inf": _clean_cell(inf_cell),
                "package": _clean_cell(package_cell),
                "version": _clean_cell(version_cell),
                "date": _clean_cell(date_cell),
                "hwids": hwids,
            })
    return rows


class IntelChipsetInfDbProvider(DriverProvider):
    """
    hwid: конкретный Hardware ID устройства (DEV_XXXX без префикса) —
    берём из просканированного устройства чипсета, ищем в базе платформу,
    к которой относится именно этот HWID.
    """

    name = "intel_chipset_inf_db"

    def __init__(self, hwid: str):
        self.hwid = hwid.upper()

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        resp = requests.get(DB_URL, headers=DEFAULT_HEADERS, timeout=20)
        resp.raise_for_status()

        rows = _parse_database(resp.text)

        for row in rows:
            if self.hwid in row["hwids"]:
                return {
                    "version": row["version"],
                    "date": row["date"],
                    "url": DB_URL,
                    "inf": row["inf"],
                    "package": row["package"],
                }

        return None

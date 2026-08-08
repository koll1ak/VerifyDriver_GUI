"""
Провайдер аудио-драйверов SenaryTech (китайский производитель аудио-кодеков
— альтернатива Realtek, встречается на некоторых моделях Huawei и др.).

    https://www.senarytech.com/en/DriverDownload/index.aspx

Страница крошечная и полностью server-rendered (без JS) — на момент
разбора всего 2 записи, каждая покрывает несколько кодов чипов сразу
(например "CX11880 | CX11970 | SN6140"). Версия зашита в имя файла
(например "HDART_2.26.0.9_..." -> "2.26.0.9").

ВАЖНО: у Huawei driver package версия отличается от версии на этой
странице (например "SenaryAudio_3.40.0.40" у Huawei против "3.46.0.9"
здесь) — то же самое явление, что мы видели с MSI/Realtek Audio:
OEM переупаковывает драйвер чипа под своим номером версии. Поэтому
автоматическую сверку версий не делаем — только показываем, что есть.
"""

import re

import requests
from bs4 import BeautifulSoup

from providers.base import DriverProvider
from providers.http_utils import DEFAULT_HEADERS

PAGE_URL = "https://www.senarytech.com/en/DriverDownload/index.aspx"

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+(?:\.\d+)?)_")


class SenaryAudioProvider(DriverProvider):
    """
    chip_code: код чипа для фильтрации (например "SN6140" или "CX11880") —
    если не передан, возвращается первая (самая свежая по списку) запись.
    """

    def __init__(self, chip_code: str | None = None, name: str = "senary_audio"):
        self.chip_code = chip_code.upper() if chip_code else None
        self.name = name

    def matches(self, device: dict) -> bool:
        return False

    def get_latest(self, device: dict = None) -> dict | None:
        resp = requests.get(PAGE_URL, headers=DEFAULT_HEADERS, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        entries = []
        for link in soup.find_all("a", href=True):
            if "Download.aspx?Guid=" not in link["href"]:
                continue
            title = link.get_text(strip=True)
            version_match = _VERSION_RE.search(title)
            if version_match is None:
                continue  # это, скорее всего, дублирующая ссылка "File Down" без версии в тексте
            url = link["href"]
            if url.startswith("/"):
                url = "https://www.senarytech.com" + url
            entries.append({"title": title, "url": url, "version": version_match.group(1)})

        if not entries:
            return None

        if self.chip_code:
            entries = [e for e in entries if self.chip_code in e["title"].upper()] or entries
            latest = entries[0]
            return {"version": latest["version"], "url": latest["url"], "description": latest["title"]}

        # без точного кода чипа (DEV_) не знаем, какая из записей реально
        # твоя — показываем ВСЕ варианты разом, а не гадаем одну наугад
        combined_version = " / ".join(f"{e['version']} ({e['title'].split('|')[0].strip()})" for e in entries)
        return {
            "version": combined_version,
            "url": entries[0]["url"],
            "description": "; ".join(e["title"] for e in entries),
        }

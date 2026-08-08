import json
import os

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def diff_and_update(state: dict, key: str, latest_version: str) -> str | None:
    """
    Сравнивает latest_version с сохранённой версией по ключу key.
    Возвращает старую версию, если обнаружено обновление, иначе None.
    Всегда обновляет state под новую версию.
    """
    old_version = state.get(key, {}).get("version")
    state[key] = {"version": latest_version}

    if old_version is not None and old_version != latest_version:
        return old_version
    return None

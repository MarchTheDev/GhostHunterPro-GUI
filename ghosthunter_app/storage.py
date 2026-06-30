from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import (
    DEFAULT_STATE,
    LEGACY_DATA_DIR,
    LEGACY_STATE_FILE,
    LEGACY_STEAM_CACHE_FILE,
    STATE_FILE,
    STEAM_CACHE_FILE,
)
from .utils import safe_read_json, safe_write_json


def migrate_legacy_files() -> None:
    migrations = [
        (LEGACY_STATE_FILE, STATE_FILE),
        (LEGACY_STEAM_CACHE_FILE, STEAM_CACHE_FILE),
    ]

    if LEGACY_DATA_DIR is not None:
        migrations.extend([
            (LEGACY_DATA_DIR / "ghosthunter_state.json", STATE_FILE),
            (LEGACY_DATA_DIR / "ghosthunter_appcache.json", STEAM_CACHE_FILE),
        ])

    for legacy, current in migrations:
        try:
            if legacy.exists() and not current.exists():
                current.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass


class StateStore:
    def __init__(self) -> None:
        migrate_legacy_files()
        self.data = safe_read_json(STATE_FILE, DEFAULT_STATE.copy())
        if not isinstance(self.data.get("archived_appids"), list):
            self.data["archived_appids"] = []
        if not isinstance(self.data.get("search_history"), list):
            self.data["search_history"] = []
        if not isinstance(self.data.get("theme"), str):
            self.data["theme"] = "neon"
        if not isinstance(self.data.get("font"), str):
            self.data["font"] = "inter"
        if not isinstance(self.data.get("custom_theme_color"), str):
            self.data["custom_theme_color"] = "#d946ef"
        if not isinstance(self.data.get("custom_theme_presets"), list):
            self.data["custom_theme_presets"] = []

    def save(self) -> None:
        safe_write_json(STATE_FILE, self.data)

    def archived_appids(self) -> list[str]:
        return [str(value) for value in self.data.get("archived_appids", [])]

    def set_archived(self, appid: str, archived: bool) -> None:
        bucket = set(self.archived_appids())
        if archived:
            bucket.add(str(appid))
        else:
            bucket.discard(str(appid))
        self.data["archived_appids"] = sorted(bucket)
        self.save()

    def history(self) -> list[dict[str, Any]]:
        return list(self.data.get("search_history", []))

    def record_history(self, game: dict[str, Any]) -> None:
        appid = str(game.get("appid", ""))
        if not appid:
            return
        history = [item for item in self.history() if str(item.get("appid")) != appid]
        history.insert(0, {"appid": appid, "name": game.get("name", f"Unknown Game ({appid})")})
        self.data["search_history"] = history[:20]
        self.save()

    def remove_history_item(self, appid: str) -> None:
        self.data["search_history"] = [
            item for item in self.history() if str(item.get("appid")) != str(appid)
        ]
        self.save()

    def clear_history(self) -> None:
        self.data["search_history"] = []
        self.save()

    def theme(self) -> str:
        return str(self.data.get("theme", "neon"))

    def set_theme(self, theme_name: str) -> None:
        self.data["theme"] = str(theme_name or "neon")
        self.save()

    def font(self) -> str:
        return str(self.data.get("font", "inter"))

    def set_font(self, font_name: str) -> None:
        self.data["font"] = str(font_name or "inter")
        self.save()

    def custom_theme_color(self) -> str:
        return str(self.data.get("custom_theme_color", "#d946ef"))

    def set_custom_theme_color(self, color: str) -> None:
        self.data["custom_theme_color"] = str(color or "#d946ef")
        self.save()

    def custom_theme_presets(self) -> list[dict[str, str]]:
        presets = self.data.get("custom_theme_presets", [])
        if not isinstance(presets, list):
            return []
        result: list[dict[str, str]] = []
        for item in presets:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            color = str(item.get("color", "")).strip()
            if name and color:
                result.append({"name": name, "color": color})
        return result

    def add_custom_theme_preset(self, name: str, color: str) -> None:
        clean_name = str(name or "Custom Theme").strip()[:40] or "Custom Theme"
        clean_color = str(color or "#d946ef").strip()
        presets = [item for item in self.custom_theme_presets() if item.get("name", "").lower() != clean_name.lower()]
        presets.insert(0, {"name": clean_name, "color": clean_color})
        self.data["custom_theme_presets"] = presets[:12]
        self.save()

    def delete_custom_theme_preset(self, name: str) -> None:
        clean_name = str(name or "").strip().lower()
        self.data["custom_theme_presets"] = [
            item for item in self.custom_theme_presets()
            if item.get("name", "").lower() != clean_name
        ]
        self.save()

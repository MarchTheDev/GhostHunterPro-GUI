from __future__ import annotations

import os
import webbrowser
from typing import Any

from .file_ops import delete_paths as delete_paths_impl
from .file_ops import open_path as open_path_impl
from .scanner import ScanEngine
from .save_scanner import SaveScanner
from .steam_api import SteamAPI
from .storage import StateStore
from .updater import UpdateManager
from .utils import normalize_name


class Backend:
    THEME_OPTIONS = [
        {"id": "neon", "label": "Neon", "description": "Classic cyan and purple look."},
        {"id": "rubellite", "label": "Rubellite", "description": "Deep rubellite red based on #660011."},
        {"id": "midnight", "label": "Midnight", "description": "Cool blue and steel accents."},
        {"id": "ember", "label": "Ember", "description": "Warm orange and crimson accents."},
        {"id": "emerald", "label": "Emerald", "description": "Green highlights with a darker base."},
        {"id": "custom", "label": "Custom", "description": "Pick your own accent color with the color picker or a hex code."},
    ]

    FONT_OPTIONS = [
        {"id": "inter", "label": "Inter", "description": "Modern UI default with clean spacing."},
        {"id": "system", "label": "System UI", "description": "Uses the native Windows/system interface font."},
        {"id": "dm-mono", "label": "DM Mono", "description": "Rounded mono style with softer spacing."},
        {"id": "trebuchet", "label": "Trebuchet MS", "description": "Rounded and friendly without needing bundled font files."},
        {"id": "georgia", "label": "Georgia", "description": "Elegant serif option with strong readability."},
        {"id": "mono", "label": "JetBrains-style Mono", "description": "Sharper developer-style monospace stack."},
        {"id": "roboto-slab", "label": "Roboto Slab", "description": "A sharper slab-serif look for the whole app."},
        {"id": "roboto-condensed", "label": "Roboto Condensed", "description": "Narrower, compact interface style."},
        {"id": "fraktur", "label": "Fraktur", "description": "Decorative gothic display style."},
        {"id": "atkinson-hyperlegible", "label": "Atkinson Hyperlegible", "description": "Built for readability with clearer character shapes."},
    ]

    def __init__(self) -> None:
        self.state = StateStore()
        self.steam = SteamAPI()
        self.updater = UpdateManager()
        self._installed_catalog: dict[str, dict[str, Any]] | None = None

    def _save(self) -> None:
        self.state.save()
        self.steam.save_cache()

    def _ensure_installed_catalog(self) -> dict[str, dict[str, Any]]:
        if self._installed_catalog is None:
            self._installed_catalog = ScanEngine.discover_installed_games(self.steam)
            self._save()
        return self._installed_catalog

    def ping(self) -> dict[str, Any]:
        return {"ok": True, "desktop": True}

    def open_url(self, url: str) -> dict[str, Any]:
        try:
            webbrowser.open_new_tab(url)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_path(self, path: str) -> dict[str, Any]:
        return open_path_impl(path)

    def set_archived(self, appid: str, archived: bool) -> dict[str, Any]:
        self.state.set_archived(str(appid), archived)
        self._save()
        return {"ok": True, "appid": str(appid), "archived": archived}

    def get_history(self) -> list[dict[str, Any]]:
        return self.state.history()

    def remove_history_item(self, appid: str) -> dict[str, Any]:
        self.state.remove_history_item(str(appid))
        self._save()
        return {"ok": True}

    def clear_history(self) -> dict[str, Any]:
        self.state.clear_history()
        self._save()
        return {"ok": True}

    def search_suggestions(self, query: str) -> list[dict[str, Any]]:
        raw = (query or '')
        clean = raw.strip()
        clean_norm = normalize_name(clean)
        catalog = self._ensure_installed_catalog()
        suggestions: list[dict[str, Any]] = []
        seen: set[str] = set()

        if clean:
            def score_installed(item: dict[str, Any]) -> tuple[int, str]:
                appid = str(item.get('appid', ''))
                name = str(item.get('name', ''))
                name_norm = normalize_name(name)
                if clean == appid:
                    score = 100
                elif clean_norm and clean_norm == name_norm:
                    score = 95
                elif clean_norm and name_norm.startswith(clean_norm):
                    score = 85
                elif clean_norm and clean_norm in name_norm:
                    score = 70
                elif clean.lower() in name.lower():
                    score = 50
                else:
                    score = 0
                return (-score, name.lower())

            ranked = []
            for item in catalog.values():
                score_key = score_installed(item)
                if score_key[0] == 0:
                    continue
                ranked.append((score_key, item))
            ranked.sort(key=lambda pair: pair[0])
            ranked = [item for _, item in ranked]
            for item in ranked:
                appid = str(item.get('appid', ''))
                if not appid or appid in seen:
                    continue
                seen.add(appid)
                suggestions.append({
                    'id': int(appid) if appid.isdigit() else appid,
                    'name': item.get('name', f'Unknown Game ({appid})'),
                    'tiny_image': item.get('header_image', self.steam.header_image_for_appid(appid) if appid.isdigit() else ''),
                })
                if len(suggestions) >= 6:
                    return suggestions

        remote_matches = self.steam.search_suggestions(clean)
        for item in remote_matches:
            appid = str(item.get('id', ''))
            if not appid or appid in seen:
                continue
            seen.add(appid)
            suggestions.append(item)
            if len(suggestions) >= 6:
                break
        return suggestions[:6]

    def set_theme(self, theme_name: str) -> dict[str, Any]:
        allowed = {option["id"] for option in self.THEME_OPTIONS}
        self.state.set_theme(theme_name if theme_name in allowed else "neon")
        self._save()
        return {"ok": True, "theme": self.state.theme()}

    def set_font(self, font_name: str) -> dict[str, Any]:
        allowed = {option["id"] for option in self.FONT_OPTIONS}
        self.state.set_font(font_name if font_name in allowed else "inter")
        self._save()
        return {"ok": True, "font": self.state.font()}

    @staticmethod
    def _normalize_hex_color(color: str) -> str | None:
        value = str(color or "").strip()
        if not value.startswith("#"):
            value = "#" + value
        hex_part = value[1:]
        if len(hex_part) == 3 and all(char in "0123456789abcdefABCDEF" for char in hex_part):
            hex_part = "".join(char * 2 for char in hex_part)
        if not (len(hex_part) == 6 and all(char in "0123456789abcdefABCDEF" for char in hex_part)):
            return None
        return "#" + hex_part.lower()

    def set_custom_theme_color(self, color: str, color2: str | None = None, use_second: bool | None = None) -> dict[str, Any]:
        value = self._normalize_hex_color(color)
        if not value:
            return {"ok": False, "error": "Use a valid hex color like #d946ef."}
        self.state.set_custom_theme_color(value)
        if color2 is not None:
            value2 = self._normalize_hex_color(color2)
            if not value2:
                return {"ok": False, "error": "Use a valid second hex color like #fb7185."}
            self.state.set_custom_theme_color_2(value2)
        if use_second is not None:
            self.state.set_custom_theme_use_second_color(bool(use_second))
        self.state.set_theme("custom")
        self._save()
        return {
            "ok": True,
            "theme": self.state.theme(),
            "custom_theme_color": self.state.custom_theme_color(),
            "custom_theme_color_2": self.state.custom_theme_color_2(),
            "custom_theme_use_second_color": self.state.custom_theme_use_second_color(),
        }

    def save_custom_theme_preset(self, name: str, color: str, color2: str | None = None, use_second: bool | None = None) -> dict[str, Any]:
        value = self._normalize_hex_color(color)
        if not value:
            return {"ok": False, "error": "Use a valid hex color like #d946ef."}
        value2 = self._normalize_hex_color(color2 or self.state.custom_theme_color_2())
        if not value2:
            return {"ok": False, "error": "Use a valid second hex color like #fb7185."}
        second_enabled = self.state.custom_theme_use_second_color() if use_second is None else bool(use_second)
        clean_name = str(name or "Custom Theme").strip()[:40] or "Custom Theme"
        self.state.add_custom_theme_preset(clean_name, value, value2, second_enabled)
        self.state.set_custom_theme_color(value)
        self.state.set_custom_theme_color_2(value2)
        self.state.set_custom_theme_use_second_color(second_enabled)
        self.state.set_theme("custom")
        self._save()
        return {
            "ok": True,
            "theme": self.state.theme(),
            "custom_theme_color": self.state.custom_theme_color(),
            "custom_theme_color_2": self.state.custom_theme_color_2(),
            "custom_theme_use_second_color": self.state.custom_theme_use_second_color(),
            "custom_theme_presets": self.state.custom_theme_presets(),
        }

    def delete_custom_theme_preset(self, name: str) -> dict[str, Any]:
        self.state.delete_custom_theme_preset(name)
        self._save()
        return {"ok": True, "custom_theme_presets": self.state.custom_theme_presets()}

    def get_settings_info(self) -> dict[str, Any]:
        payload = self.updater.get_settings_payload()
        payload["theme"] = self.state.theme()
        payload["theme_options"] = self.THEME_OPTIONS
        payload["font"] = self.state.font()
        payload["font_options"] = self.FONT_OPTIONS
        payload["custom_theme_color"] = self.state.custom_theme_color()
        payload["custom_theme_color_2"] = self.state.custom_theme_color_2()
        payload["custom_theme_use_second_color"] = self.state.custom_theme_use_second_color()
        payload["custom_theme_presets"] = self.state.custom_theme_presets()
        return payload

    def check_for_updates(self) -> dict[str, Any]:
        return self.updater.check_for_updates()

    def open_releases_page(self) -> dict[str, Any]:
        return self.updater.open_releases_page()

    def download_update_installer(self, url: str) -> dict[str, Any]:
        return self.updater.download_installer_update(url)

    def launch_update_installer(self, path: str) -> dict[str, Any]:
        return self.updater.launch_installer(path)

    def download_portable_update(self, url: str) -> dict[str, Any]:
        return self.updater.download_portable_package(url)

    def rescan_library(self) -> dict[str, Any]:
        self._installed_catalog = ScanEngine.discover_installed_games(self.steam)
        self._save()
        return self.scan_library(use_cached_installed=True)

    def home_search(self, query: str) -> dict[str, Any]:
        catalog = self._ensure_installed_catalog()
        clean_query = (query or "").strip()
        lowered = clean_query.lower()
        normalized_query = normalize_name(clean_query)

        game = None
        if clean_query in catalog:
            game = catalog[clean_query]
        else:
            exact_norm = next(
                (
                    item for item in catalog.values()
                    if normalized_query and normalize_name(str(item.get("name", ""))) == normalized_query
                ),
                None,
            )
            if exact_norm:
                game = exact_norm
            else:
                exact_plain = next(
                    (
                        item for item in catalog.values()
                        if lowered and lowered == str(item.get("name", "")).lower()
                    ),
                    None,
                )
                if exact_plain:
                    game = exact_plain

        # Partial matches are intentionally not used for the final Home search.
        # They can choose the wrong game when the user searches a short name,
        # causing unrelated paths/results. Suggestions can still show partials.

        if not game:
            game = self.steam.search_game(clean_query)

        if not game:
            game = SaveScanner.find_local_game_by_save_name(clean_query, self.steam)

        if not game:
            return {"ok": False, "error": "Game not found or no leftovers/save files were found for that name."}

        if not str(game.get('appid', '')).isdigit():
            game = {**game, 'appid': ''}

        # Build the same save-only index used by Library and reuse its metadata
        # for Home. This removes the confusing split where Home and Library show
        # different names/images/path sets for the same game.
        try:
            save_only_index = SaveScanner.discover_save_library_entries(self.steam)
        except Exception:
            save_only_index = {}
        save_only_entry = None
        game_appid = str(game.get("appid", ""))
        if game_appid:
            save_only_entry = save_only_index.get(game_appid)
        if not save_only_entry:
            game_norm = normalize_name(str(game.get("name", "")))
            save_only_entry = next(
                (entry for entry in save_only_index.values() if normalize_name(str(entry.get("name", ""))) == game_norm),
                None,
            )
        if save_only_entry:
            game = {
                **game,
                "name": save_only_entry.get("name") or game.get("name"),
                "header_image": game.get("header_image") or save_only_entry.get("header_image", ""),
                "short_description": game.get("short_description") or save_only_entry.get("short_description", ""),
                "paths": save_only_entry.get("paths", []),
            }

        candidates = ScanEngine.generate_home_candidates(game)
        resolved: list[dict[str, Any]] = []
        seen: set[str] = set()

        # Local save-only fallback entries can already carry detected paths.
        for match in game.get("paths", []) or []:
            norm = os.path.normcase(os.path.normpath(match["path"]))
            if norm in seen:
                continue
            seen.add(norm)
            resolved.append(match)

        for candidate in candidates:
            for match in ScanEngine.resolve_candidate(candidate):
                norm = os.path.normcase(os.path.normpath(match["path"]))
                if norm in seen:
                    continue
                seen.add(norm)
                resolved.append(match)

        # Also merge the full library-style AppID scan for this game so Home and
        # Library stay consistent even when leftovers are found in non-template
        # locations like Public Documents crack folders or Steam userdata.
        library_index = ScanEngine.build_library_index()
        for match in library_index.get(str(game.get("appid", "")), []):
            norm = os.path.normcase(os.path.normpath(match["path"]))
            if norm in seen:
                continue
            seen.add(norm)
            resolved.append(match)

        # Focused save/config discovery for this one game. This no longer does a
        # broad AppData name walk, which was the reason unrelated folders like
        # ATLauncher could appear in a Balatro search.
        for match in SaveScanner.find_save_paths(game, include_online=True, fetch_online=True):
            norm = os.path.normcase(os.path.normpath(match["path"]))
            if norm in seen:
                continue
            seen.add(norm)
            resolved.append(match)

        if not resolved:
            return {"ok": False, "error": "No leftovers or save/config files were found for this game."}

        resolved = SaveScanner.collapse_nested_paths(resolved)
        resolved.sort(key=lambda item: (item["category"], item["path"].lower()))
        self.state.record_history(game)
        self._save()
        return {
            "ok": True,
            "game": game,
            "paths": resolved,
            "total_size": sum(item.get("size", 0) for item in resolved),
        }

    def scan_library(self, use_cached_installed: bool = False) -> dict[str, Any]:
        hidden_set = set(self.state.archived_appids())
        leftover_index = ScanEngine.build_library_index()
        save_only_index = SaveScanner.discover_save_library_entries(self.steam)
        installed_catalog = self._installed_catalog if use_cached_installed and self._installed_catalog is not None else self._ensure_installed_catalog()
        all_appids = sorted(set(leftover_index.keys()) | set(installed_catalog.keys()) | set(save_only_index.keys()))
        details_map = self.steam.get_many_app_details([appid for appid in all_appids if str(appid).isdigit()], timeout=3)
        items: list[dict[str, Any]] = []

        for appid in all_appids:
            paths = list(leftover_index.get(appid, []))
            save_only_info = save_only_index.get(appid, {})
            for save_path in save_only_info.get("paths", []) or []:
                paths.append(save_path)
            installed_info = installed_catalog.get(appid) or save_only_info or {"sources": [], "name": f"Unknown Game ({appid})"}
            fallback_name = installed_info.get("name", f"Unknown Game ({appid})")
            meta = details_map.get(str(appid)) or self.steam.cached_library_details(str(appid), fallback_name=fallback_name)
            if not meta.get("header_image") and save_only_info.get("header_image"):
                meta = {**meta, "header_image": save_only_info.get("header_image", "")}
            header_image = meta.get("header_image", "") or installed_info.get("header_image", "")

            path_seen = {os.path.normcase(os.path.normpath(path["path"])) for path in paths}
            save_game = {**meta, "appid": appid}
            # Use cached confirmed paths too, but never fetch online while loading
            # the Library. If Home has already cached confirmed data for a game,
            # Library will display the same canonical result after refresh.
            for match in SaveScanner.find_save_paths(save_game, include_online=True, fetch_online=False):
                norm = os.path.normcase(os.path.normpath(match["path"]))
                if norm in path_seen:
                    continue
                path_seen.add(norm)
                paths.append(match)

            paths = SaveScanner.collapse_nested_paths(paths)
            paths.sort(key=lambda item: (item["category"], item["path"].lower()))
            installed_sources = installed_info.get("sources", []) or ScanEngine.detect_installed_sources(appid, meta["name"])
            items.append({
                "appid": appid,
                "name": meta.get("name", fallback_name),
                "developers": meta.get("developers", []),
                "publishers": meta.get("publishers", []),
                "header_image": header_image,
                "short_description": meta.get("short_description", ""),
                "paths": paths,
                "path_count": len(paths),
                "total_size": sum(path.get("size", 0) for path in paths),
                "archived": appid in hidden_set,
                "hidden": appid in hidden_set,
                "installed_sources": installed_sources,
                "installed": bool(installed_sources),
                "has_leftovers": bool(paths),
            })

        def library_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
            name = str(item.get("name", ""))
            appid = str(item.get("appid", ""))
            details_state = str(item.get("details_state", ""))
            is_unknown = name.lower().startswith("unknown game") or details_state == "missing" or appid.startswith("local-save:")
            return (1 if item.get("archived") else 0, 1 if is_unknown else 0, name.lower())

        items.sort(key=library_sort_key)
        self._save()
        return {"ok": True, "items": items}

    def delete_paths(self, paths: list[str]) -> dict[str, Any]:
        return delete_paths_impl(paths)

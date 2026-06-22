from __future__ import annotations

import os
import webbrowser
from typing import Any

from .file_ops import delete_paths as delete_paths_impl
from .file_ops import open_path as open_path_impl
from .scanner import ScanEngine
from .steam_api import SteamAPI
from .storage import StateStore
from .updater import UpdateManager
from .utils import normalize_name


class Backend:
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
        self.state.set_theme(theme_name)
        self._save()
        return {"ok": True, "theme": self.state.theme()}

    def get_settings_info(self) -> dict[str, Any]:
        payload = self.updater.get_settings_payload()
        payload["theme"] = self.state.theme()
        payload["theme_options"] = [
            {"id": "neon", "label": "Neon", "description": "Classic cyan and purple look."},
            {"id": "midnight", "label": "Midnight", "description": "Cool blue and steel accents."},
            {"id": "ember", "label": "Ember", "description": "Warm orange and crimson accents."},
            {"id": "emerald", "label": "Emerald", "description": "Green highlights with a darker base."},
        ]
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
                else:
                    partial_norm = next(
                        (
                            item for item in catalog.values()
                            if normalized_query and normalized_query in normalize_name(str(item.get("name", "")))
                        ),
                        None,
                    )
                    if partial_norm:
                        game = partial_norm
                    else:
                        partial_plain = next(
                            (
                                item for item in catalog.values()
                                if lowered and lowered in str(item.get("name", "")).lower()
                            ),
                            None,
                        )
                        if partial_plain:
                            game = partial_plain

        if not game:
            game = self.steam.search_game(clean_query)

        if not game:
            return {"ok": False, "error": "Game not found. Try a different name or Steam AppID."}

        if not str(game.get('appid', '')).isdigit():
            game = {**game, 'appid': ''}

        candidates = ScanEngine.generate_home_candidates(game)
        resolved: list[dict[str, Any]] = []
        seen: set[str] = set()

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

        resolved.sort(key=lambda item: (item["category"], item["path"].lower()))
        self.state.record_history(game)
        self._save()
        return {
            "ok": True,
            "game": game,
            "paths": resolved,
            "total_size": sum(item.get("size", 0) for item in resolved),
        }

    def scan_library(self) -> dict[str, Any]:
        hidden_set = set(self.state.archived_appids())
        leftover_index = ScanEngine.build_library_index()
        installed_catalog = self._ensure_installed_catalog()
        all_appids = sorted(set(leftover_index.keys()) | set(installed_catalog.keys()))
        items: list[dict[str, Any]] = []

        for appid in all_appids:
            paths = list(leftover_index.get(appid, []))
            installed_info = installed_catalog.get(appid, {"sources": [], "name": f"Unknown Game ({appid})"})
            meta = self.steam.get_app_details(appid) or {
                "name": installed_info.get("name", f"Unknown Game ({appid})"),
                "appid": appid,
                "developers": [],
                "publishers": [],
                "header_image": "",
                "short_description": "Not found on Steam Store.",
            }
            paths.sort(key=lambda item: (item["category"], item["path"].lower()))
            installed_sources = installed_info.get("sources", []) or ScanEngine.detect_installed_sources(appid, meta["name"])
            items.append({
                "appid": appid,
                "name": meta["name"],
                "developers": meta.get("developers", []),
                "publishers": meta.get("publishers", []),
                "header_image": meta.get("header_image", ""),
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

        items.sort(key=lambda item: (item["archived"], item["name"].lower()))
        self._save()
        return {"ok": True, "items": items}

    def delete_paths(self, paths: list[str]) -> dict[str, Any]:
        return delete_paths_impl(paths)

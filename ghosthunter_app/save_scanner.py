from __future__ import annotations

import glob
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .config import PCGW_CACHE_FILE
from .utils import normalize_name, path_size, placeholder_header_image, safe_read_json, safe_write_json


class SaveScanner:
    """Focused save/config discovery layer.

    The scanner is intentionally conservative:
    - Home search checks exact/common locations for one chosen game.
    - Library only adds save-only entries when the folder can be resolved as a game
      or is in our curated rules.
    - It does not walk all of AppData looking for partial name matches, because
      that causes false positives such as launchers/mod managers containing a
      folder with a game name inside them.
    """

    # Folder aliases whose on-disk names are not the nice public title.
    # appid is optional but gives the Library proper Steam art/details.
    KNOWN_GAMES: dict[str, dict[str, Any]] = {
        "balatro": {
            "name": "Balatro",
            "appid": "2379780",
            "aliases": ["Balatro"],
            "save_and_config": True,
            "patterns": [r"{APPDATA}\Balatro"],
        },
        "hitman3": {
            "name": "HITMAN World of Assassination",
            "appid": "1659040",
            "aliases": ["HITMAN3", "HITMAN 3", "HITMAN III", "Hitman 3"],
            "patterns": [
                r"{APPDATA}\IO Interactive\Epic\*\HITMAN3",
                r"{LOCAL}\IO Interactive\Epic\*\HITMAN3",
                r"{APPDATA}\IO Interactive\HITMAN3",
            ],
        },
        "hitmanworldofassassination": {
            "name": "HITMAN World of Assassination",
            "appid": "1659040",
            "aliases": ["HITMAN3", "HITMAN 3", "HITMAN III", "Hitman 3"],
            "patterns": [
                r"{APPDATA}\IO Interactive\Epic\*\HITMAN3",
                r"{LOCAL}\IO Interactive\Epic\*\HITMAN3",
                r"{APPDATA}\IO Interactive\HITMAN3",
            ],
        },
        "hitmaniii": {
            "name": "HITMAN World of Assassination",
            "appid": "1659040",
            "aliases": ["HITMAN3", "HITMAN 3", "HITMAN III", "Hitman 3"],
            "patterns": [
                r"{APPDATA}\IO Interactive\Epic\*\HITMAN3",
                r"{LOCAL}\IO Interactive\Epic\*\HITMAN3",
                r"{APPDATA}\IO Interactive\HITMAN3",
            ],
        },
        "assettocorsaevo": {
            "name": "Assetto Corsa EVO",
            "appid": "3058630",
            "aliases": ["ACE", "Assetto Corsa EVO", "AssettoCorsaEVO"],
            "patterns": [
                r"{LOCAL}\ACE\Saved",
                r"{LOCAL}\ACE\Saved\SaveGames",
                r"{LOCAL}\ACE\Saved\Config",
            ],
        },
        "ace": {
            "name": "Assetto Corsa EVO",
            "appid": "3058630",
            "aliases": ["ACE", "Assetto Corsa EVO", "AssettoCorsaEVO"],
            "patterns": [
                r"{LOCAL}\ACE\Saved",
                r"{LOCAL}\ACE\Saved\SaveGames",
                r"{LOCAL}\ACE\Saved\Config",
            ],
        },
        "legobatmanlegacyofthedarkknight": {
            "name": "LEGO Batman: Legacy of the Dark Knight",
            "appid": "2215200",
            "aliases": [
                "LEGO Batman Legacy of the Dark Knight",
                "LEGO Batman - Legacy of the Dark Knight",
                "LEGO® Batman™: Legacy of the Dark Knight",
                "Dinner",
            ],
            "patterns_only": True,
            "patterns": [
                r"{LOCAL}\Warner Bros. Interactive Entertainment\LEGO Batman - Legacy of the Dark Knight\SaveGames",
                r"{LOCAL}\Dinner\Saved\Config\Windows",
            ],
        },
        "legobatmanlegacyofthedarkknightdinner": {
            "name": "LEGO Batman: Legacy of the Dark Knight",
            "appid": "2215200",
            "aliases": ["Dinner", "LEGO Batman - Legacy of the Dark Knight"],
            "patterns_only": True,
            "patterns": [
                r"{LOCAL}\Warner Bros. Interactive Entertainment\LEGO Batman - Legacy of the Dark Knight\SaveGames",
                r"{LOCAL}\Dinner\Saved\Config\Windows",
            ],
        },
        "dispatch": {
            "name": "Dispatch",
            "aliases": ["Dispatch"],
            "patterns": [
                r"{APPDATA}\Dispatch",
                r"{LOCAL}\Dispatch",
                r"{LOCAL}\Dispatch\Saved",
                r"{LOCAL}\Dispatch\Saved\SaveGames",
                r"{SAVEDGAMES}\Dispatch",
                r"{DOCS}\My Games\Dispatch",
            ],
        },
    }

    NON_GAME_FOLDER_NAMES = {
        "achievements", "adobe", "amd", "apple", "atlauncher", "audacity", "blender foundation",
        "brave", "cache", "code", "discord", "docker", "dropbox", "electron",
        "epicgameslauncher", "githubdesktop", "google", "gog.com", "intel", "java",
        "jetbrains", "microsoft", "mozilla", "nodejs", "notepad++", "npm",
        "nvidia", "obs-studio", "obsstudio", "opera software", "python", "qtproject",
        "spotify", "telegram desktop", "telegramdesktop", "unity", "unreal engine",
        "valve", "vlc", "vscode", "windows", "zoom",
    }

    @staticmethod
    def env_map() -> dict[str, str]:
        user = os.environ.get("USERPROFILE") or str(Path.home())
        return {
            "{APPDATA}": os.environ.get("APPDATA", os.path.join(user, "AppData", "Roaming")),
            "{LOCAL}": os.environ.get("LOCALAPPDATA", os.path.join(user, "AppData", "Local")),
            "{LOCALLOW}": os.path.join(user, "AppData", "LocalLow"),
            "{DOCS}": os.path.join(user, "Documents"),
            "{PUBLICDOCS}": os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Documents"),
            "{PROGRAMDATA}": os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
            "{USERPROFILE}": user,
            "{SAVEDGAMES}": os.path.join(user, "Saved Games"),
            "{STEAM}": r"C:\Program Files (x86)\Steam",
        }

    @classmethod
    def expand_vars(cls, value: str) -> str:
        result = str(value or "")
        for key, replacement in cls.env_map().items():
            result = result.replace(key, replacement)
        result = os.path.expandvars(result)
        if os.sep == "/":
            result = result.replace("\\", os.sep)
        return result

    @staticmethod
    def _dedupe(values: list[str], limit: int = 32) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for value in values:
            value = str(value or "").strip()
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(value)
            if len(out) >= limit:
                break
        return out

    @classmethod
    def known_rule_for_name(cls, name: str) -> dict[str, Any] | None:
        norm = normalize_name(name)
        if not norm:
            return None
        if norm in cls.KNOWN_GAMES:
            return cls.KNOWN_GAMES[norm]
        for rule in cls.KNOWN_GAMES.values():
            keys = [rule.get("name", ""), *(rule.get("aliases") or [])]
            if norm in {normalize_name(item) for item in keys}:
                return rule
        return None

    @classmethod
    def canonical_game_name(cls, name: str) -> str:
        rule = cls.known_rule_for_name(name)
        return str((rule or {}).get("name") or name or "").strip()

    @classmethod
    def folder_names_for_game(cls, game: dict[str, Any]) -> list[str]:
        raw = str(game.get("name") or "").strip()
        values = [raw]
        # Remove common non-game suffixes from store titles.
        if raw:
            values.append(re.sub(r"\s*[-+:|]?\s*(demo|playtest|soundtrack|dedicated server)$", "", raw, flags=re.I).strip())
        rule = cls.known_rule_for_name(raw)
        if rule:
            values.append(str(rule.get("name") or ""))
            values.extend(str(item) for item in (rule.get("aliases") or []))
        return cls._dedupe(values, limit=24)

    @classmethod
    def people_for_game(cls, game: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for key in ("developers", "publishers"):
            for name in game.get(key, []) or []:
                clean = str(name or "").strip()
                if clean:
                    values.append(clean)
        return cls._dedupe(values, limit=10)

    @staticmethod
    def _nice_description(description: str, source: str = "") -> str:
        # Do not show "(Heuristic)" to users. It is developer jargon and made
        # entries look messy. PCGW/manifest labels remain useful and visible.
        if not source or source.lower() in {"heuristic", "common pattern", "verified", "save scan", "known rule"}:
            return description
        return f"{description} ({source})"

    @classmethod
    def _path_entry(cls, path: str, category: str, description: str, source: str = "") -> dict[str, Any] | None:
        if not path or not os.path.exists(path):
            return None
        return {
            "path": path,
            "category": category,
            "description": cls._nice_description(description, source),
            "source": source or "common_pattern",
            "risk": "caution",
            "size": path_size(path),
            "is_dir": os.path.isdir(path),
        }

    @classmethod
    def _add_matches(
        cls,
        results: list[dict[str, Any]],
        seen: set[str],
        pattern: str,
        category: str,
        description: str,
        source: str = "",
    ) -> None:
        expanded = cls.expand_vars(pattern)
        try:
            matches = glob.glob(expanded) if any(ch in expanded for ch in "*?") else ([expanded] if os.path.exists(expanded) else [])
        except Exception:
            matches = []
        for match in matches:
            entry = cls._path_entry(match, category, description, source)
            if not entry:
                continue
            norm = os.path.normcase(os.path.normpath(entry["path"]))
            if norm in seen:
                continue
            seen.add(norm)
            results.append(entry)

    @classmethod
    def common_save_paths(cls, game: dict[str, Any]) -> list[dict[str, Any]]:
        game_names = cls.folder_names_for_game(game)
        people = cls.people_for_game(game)
        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        # Curated patterns first. These solve folder-name mismatches like
        # HITMAN3 and ACE without guessing through unrelated software folders.
        rule = cls.known_rule_for_name(str(game.get("name") or ""))
        if rule:
            for pattern in rule.get("patterns") or []:
                category = "Config Files" if "config" in str(pattern).lower() else "Save Files"
                description = "Save and config folder" if rule.get("save_and_config") else ("Config folder" if category == "Config Files" else "Save folder")
                if rule.get("save_and_config"):
                    category = "Save & Config Files"
                cls._add_matches(results, seen, pattern, category, description, "Known rule")
            if rule.get("patterns_only"):
                results.sort(key=lambda item: (item["category"], item["path"].lower()))
                return results

        for game_name in game_names:
            templates = [
                (r"{APPDATA}\Godot\app_userdata\{GAME}", "Save Files", "Godot app_userdata save folder"),
                (r"{LOCAL}\{GAME}\Saved\SaveGames", "Save Files", "Unreal Engine SaveGames folder"),
                (r"{LOCAL}\{GAME}\Saved", "Save Files", "Unreal Engine Saved folder"),
                (r"{LOCAL}\{GAME}\Saved\Config", "Config Files", "Unreal Engine config folder"),
                (r"{SAVEDGAMES}\{GAME}", "Save Files", "Windows Saved Games folder"),
                (r"{DOCS}\My Games\{GAME}", "Save Files", "Documents My Games folder"),
                (r"{DOCS}\{GAME}", "Save Files", "Documents game folder"),
                (r"{APPDATA}\{GAME}", "Save Files", "Roaming app data folder"),
                (r"{LOCAL}\{GAME}", "Save Files", "Local app data folder"),
                (r"{LOCALLOW}\{GAME}", "Save Files", "LocalLow app data folder"),
                (r"{APPDATA}\*\Epic\*\{GAME}", "Save Files", "Epic nested user save folder"),
                (r"{LOCAL}\*\Epic\*\{GAME}", "Save Files", "Epic nested local save folder"),
            ]
            for template, category, description in templates:
                cls._add_matches(results, seen, template.replace("{GAME}", game_name), category, description)

            for person in people:
                person_templates = [
                    (r"{APPDATA}\{PERSON}\{GAME}", "Save Files", "Developer/publisher Roaming folder"),
                    (r"{LOCAL}\{PERSON}\{GAME}", "Save Files", "Developer/publisher Local folder"),
                    (r"{LOCAL}\{PERSON}\{GAME}\SaveGames", "Save Files", "Developer/publisher SaveGames folder"),
                    (r"{LOCAL}\{PERSON}\{GAME}\Saved", "Save Files", "Developer/publisher Saved folder"),
                    (r"{LOCAL}\{PERSON}\{GAME}\Saved\SaveGames", "Save Files", "Developer/publisher Saved SaveGames folder"),
                    (r"{LOCAL}\{PERSON}\{GAME}\Saved\Config", "Config Files", "Developer/publisher config folder"),
                    (r"{LOCALLOW}\{PERSON}\{GAME}", "Save Files", "Unity LocalLow developer folder"),
                    (r"{APPDATA}\{PERSON}\Epic\*\{GAME}", "Save Files", "Publisher Epic nested user save folder"),
                    (r"{LOCAL}\{PERSON}\Epic\*\{GAME}", "Save Files", "Publisher Epic nested local save folder"),
                ]
                for template, category, description in person_templates:
                    cls._add_matches(
                        results,
                        seen,
                        template.replace("{PERSON}", person).replace("{GAME}", game_name),
                        category,
                        description,
                    )

        results.sort(key=lambda item: (item["category"], item["path"].lower()))
        return results

    @staticmethod
    def _pcgw_cache_key(game: dict[str, Any]) -> str:
        appid = str(game.get("appid") or "").strip()
        if appid.isdigit():
            return f"steam:{appid}"
        return f"name:{normalize_name(str(game.get('name', '')))}"

    @classmethod
    def _pcgw_api_json(cls, params: dict[str, str], timeout: int = 6) -> dict[str, Any] | None:
        url = "https://www.pcgamingwiki.com/w/api.php?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"User-Agent": "GhostHunterPro/SaveScanner"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception:
            return None

    @classmethod
    def _pcgw_page_title(cls, game: dict[str, Any]) -> str:
        appid = str(game.get("appid") or "").strip()
        if appid.isdigit():
            data = cls._pcgw_api_json({
                "action": "cargoquery",
                "tables": "Infobox_game",
                "fields": "Infobox_game._pageName=Page",
                "where": f'Infobox_game.Steam_AppID HOLDS "{appid}"',
                "format": "json",
            })
            try:
                title = data["cargoquery"][0]["title"]["Page"]
                if title:
                    return str(title)
            except Exception:
                pass
        name = str(game.get("name") or "").strip()
        if not name:
            return ""
        data = cls._pcgw_api_json({
            "action": "opensearch",
            "search": name,
            "redirects": "resolve",
            "limit": "1",
            "format": "json",
        })
        try:
            return str(data[1][0]) if data and len(data) > 1 and data[1] else ""
        except Exception:
            return ""

    @classmethod
    def _pcgw_wikitext(cls, title: str) -> str:
        if not title:
            return ""
        data = cls._pcgw_api_json({"action": "parse", "format": "json", "page": title, "prop": "wikitext"})
        try:
            return str(data["parse"]["wikitext"]["*"])
        except Exception:
            return ""

    @staticmethod
    def _strip_wiki_markup(text: str) -> str:
        value = text or ""
        replacements = {
            r"{{p|appdata}}": "{APPDATA}",
            r"{{p|localappdata}}": "{LOCAL}",
            r"{{p|userprofile}}": "{USERPROFILE}",
            r"{{p|documents}}": "{DOCS}",
            r"{{p|savedgames}}": "{SAVEDGAMES}",
            r"{{p|programdata}}": "{PROGRAMDATA}",
            r"{{p|public}}": os.environ.get("PUBLIC", r"C:\Users\Public"),
            r"{{p|steam}}": "{STEAM}",
        }
        for old, new in replacements.items():
            # Lambda avoids re.sub interpreting Windows paths as escapes (\U).
            value = re.sub(re.escape(old), lambda _m, replacement=new: replacement, value, flags=re.I)
        value = re.sub(r"\[https?://[^\s\]]+\s+([^\]]+)\]", r"\1", value)
        value = re.sub(r"\[\[([^\]|]+\|)?([^\]]+)\]\]", r"\2", value)
        value = value.replace("&lt;", "<").replace("&gt;", ">")
        value = re.sub(r"<[^>]+>", "*", value)
        value = re.sub(r"{{[^{}]*}}", "", value)
        value = value.replace("[*]", "*")
        return value.strip()

    @classmethod
    def _extract_pcgw_paths(cls, wikitext: str) -> list[tuple[str, str]]:
        if not wikitext:
            return []
        section_match = re.search(
            r"(=+\s*Game data\s*=+.*?)(?:\n=+\s*(?:Video|Input|Audio|Network|Issues|Other information|System requirements)\s*=+|\Z)",
            wikitext,
            flags=re.I | re.S,
        )
        section = section_match.group(1) if section_match else wikitext
        results: list[tuple[str, str]] = []
        for raw_line in section.splitlines():
            line = raw_line.strip()
            low = line.lower()
            if not any(token in low for token in ("{{p|", "%appdata%", "%localappdata%", "%userprofile%", "windows")):
                continue
            cleaned = cls._strip_wiki_markup(line)
            candidates = re.findall(
                r"(?:\{(?:APPDATA|LOCAL|LOCALLOW|DOCS|USERPROFILE|SAVEDGAMES|PROGRAMDATA|STEAM)\}|%[A-Z_]+%|[A-Z]:\\)[^|\n\r}]+",
                cleaned,
                flags=re.I,
            )
            for candidate in candidates:
                candidate = candidate.strip().strip(" .;,:|").replace("/", "\\")
                if len(candidate) < 5:
                    continue
                kind = "Config Files" if "config" in low else "Save Files"
                results.append((candidate, kind))
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for path, kind in results:
            key = path.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append((path, kind))
        return out[:16]

    @classmethod
    def pcgw_save_paths(cls, game: dict[str, Any], fetch_missing: bool = True) -> list[dict[str, Any]]:
        cache = safe_read_json(PCGW_CACHE_FILE, {})
        key = cls._pcgw_cache_key(game)
        if isinstance(cache, dict) and key in cache:
            raw_paths = cache.get(key) or []
        elif fetch_missing:
            title = cls._pcgw_page_title(game)
            raw_paths = cls._extract_pcgw_paths(cls._pcgw_wikitext(title))
            if isinstance(cache, dict):
                cache[key] = raw_paths
                safe_write_json(PCGW_CACHE_FILE, cache)
        else:
            raw_paths = []

        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for path, kind in raw_paths or []:
            description = "Confirmed config file" if kind == "Config Files" else "Confirmed save folder"
            cls._add_matches(results, seen, path, kind, description, "verified")
        return results

    @staticmethod
    def _merge_categories(parent_category: str, child_category: str) -> str:
        categories = {str(parent_category or ""), str(child_category or "")}
        if "Save & Config Files" in categories:
            return "Save & Config Files"
        if "Save Files" in categories and "Config Files" in categories:
            return "Save & Config Files"
        return str(parent_category or child_category or "Save Files")

    @staticmethod
    def _description_for_category(category: str, fallback: str = "") -> str:
        if category == "Save & Config Files":
            return "Save and config folder"
        if category == "Config Files":
            return "Config folder"
        if category == "Save Files":
            return "Save folder"
        return fallback or "Detected folder"

    @classmethod
    def collapse_nested_paths(cls, paths: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return one canonical displayed path list.

        If a file/folder is already inside another selected folder, keep the
        parent folder but merge the child's meaning into it. For example, if a
        game has saves and config files in the same folder, show one parent item
        as "Save & Config Files" instead of hiding the config meaning.
        """
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in paths or []:
            raw = str(item.get("path") or "")
            if not raw or not os.path.exists(raw):
                continue
            norm = os.path.normcase(os.path.normpath(raw))
            if norm in seen:
                continue
            seen.add(norm)
            unique.append(dict(item))

        # Shortest paths first, so parents win over children.
        unique.sort(key=lambda item: (len(os.path.normpath(str(item.get("path") or ""))), str(item.get("path") or "").lower()))
        kept: list[dict[str, Any]] = []
        kept_norm_dirs: list[tuple[str, dict[str, Any]]] = []
        for item in unique:
            raw = str(item.get("path") or "")
            norm = os.path.normcase(os.path.normpath(raw))
            parent_item = next((parent for parent_norm, parent in kept_norm_dirs if norm == parent_norm or norm.startswith(parent_norm + os.sep)), None)
            if parent_item is not None:
                merged_category = cls._merge_categories(str(parent_item.get("category") or ""), str(item.get("category") or ""))
                parent_item["category"] = merged_category
                parent_item["description"] = cls._description_for_category(merged_category, str(parent_item.get("description") or ""))
                parent_item["contains_nested_paths"] = True
                continue
            kept.append(item)
            if os.path.isdir(raw):
                kept_norm_dirs.append((norm, item))

        kept.sort(key=lambda item: (str(item.get("category") or ""), str(item.get("path") or "").lower()))
        return kept

    @classmethod
    def find_save_paths(
        cls,
        game: dict[str, Any],
        include_online: bool = False,
        fetch_online: bool = True,
    ) -> list[dict[str, Any]]:
        results = cls.common_save_paths(game)
        seen = {os.path.normcase(os.path.normpath(item["path"])) for item in results}
        if include_online:
            for item in cls.pcgw_save_paths(game, fetch_missing=fetch_online):
                norm = os.path.normcase(os.path.normpath(item["path"]))
                if norm in seen:
                    continue
                seen.add(norm)
                results.append(item)
        return cls.collapse_nested_paths(results)

    @classmethod
    def _candidate_scan_patterns(cls) -> list[tuple[str, str]]:
        patterns: list[tuple[str, str]] = []
        for rule in cls.KNOWN_GAMES.values():
            for pattern in rule.get("patterns") or []:
                patterns.append((pattern, "known"))
        patterns.extend([
            (r"{APPDATA}\Godot\app_userdata\*", "godot"),
            (r"{LOCAL}\*\Saved", "unreal"),
            (r"{LOCAL}\*\Saved\SaveGames", "unreal"),
            (r"{LOCAL}\*\Saved\Config", "unreal_config"),
            (r"{LOCAL}\*\Saved\Config\Windows", "unreal_config"),
            (r"{LOCAL}\*\*\SaveGames", "publisher_savegames"),
            (r"{APPDATA}\*", "top_appdata"),
            (r"{SAVEDGAMES}\*", "savedgames"),
            (r"{DOCS}\My Games\*", "mygames"),
            (r"{LOCALLOW}\*\*", "locallow"),
        ])
        return patterns

    @classmethod
    def _name_from_candidate_path(cls, path: str) -> str:
        current = Path(path)
        name = current.name
        norm = normalize_name(name)
        if norm in {"windows", "win64", "win32"} and normalize_name(current.parent.name) == "config":
            current = current.parent
            name = current.name
            norm = normalize_name(name)
        if norm in {"saved", "savegames", "config"}:
            parent = current.parent
            if norm == "savegames" and normalize_name(parent.name) == "saved":
                parent = parent.parent
            elif norm == "config" and normalize_name(parent.name) == "saved":
                parent = parent.parent
            name = parent.name
        rule = cls.known_rule_for_name(name)
        return str((rule or {}).get("name") or name)

    @classmethod
    def _is_blocked_folder(cls, name: str) -> bool:
        low = str(name or "").strip().lower()
        return normalize_name(low) in {normalize_name(item) for item in cls.NON_GAME_FOLDER_NAMES}

    @classmethod
    def _has_save_like_content(cls, path: str) -> bool:
        if not os.path.isdir(path):
            return False
        save_words = ("save", "saves", "savegame", "savegames", "profile", "player", "slot")
        save_exts = (".sav", ".save", ".dat", ".ini", ".cfg", ".json", ".profile", ".slot")
        try:
            checked = 0
            root_depth = len(Path(path).parts)
            for current, dirnames, filenames in os.walk(path):
                checked += 1
                if checked > 80:
                    return True
                depth = len(Path(current).parts) - root_depth
                if depth > 2:
                    dirnames[:] = []
                    continue
                if any(any(word in normalize_name(dirname) for word in save_words) for dirname in dirnames):
                    return True
                for file_name in filenames[:80]:
                    lowered = file_name.lower()
                    stem = normalize_name(Path(file_name).stem)
                    if lowered.endswith(save_exts) or any(word in stem for word in save_words):
                        return True
        except Exception:
            return False
        return False

    @classmethod
    def _resolve_library_game(cls, name: str, steam_api=None, known: bool = False) -> dict[str, Any] | None:
        if not name or cls._is_blocked_folder(name):
            return None
        rule = cls.known_rule_for_name(name)

        # Unknown folders are not enough to create Library cards. This prevents
        # normal app folders such as "Achievements" being converted into an
        # unrelated Steam result like "Achievements City". If a game is not in
        # installed catalogs or curated rules, Home search can still find it, but
        # Library will not auto-create a card for it.
        if not rule:
            return None

        canonical = str(rule.get("name") or name).strip()
        appid = str(rule.get("appid") or "").strip()

        resolved = None
        if steam_api is not None:
            try:
                if appid.isdigit():
                    resolved = steam_api.get_app_details(appid, timeout=2) or steam_api.seed_cache_entry(appid, canonical)
            except Exception:
                resolved = None

        if resolved:
            return dict(resolved)

        header = ""
        if appid.isdigit() and steam_api is not None:
            try:
                header = steam_api.header_image_for_appid(appid)
            except Exception:
                header = ""
        return {
            "appid": appid if appid.isdigit() else f"local-save:{normalize_name(canonical)}",
            "name": canonical,
            "developers": [],
            "publishers": [],
            "header_image": header or placeholder_header_image(canonical, "Save/config folder"),
            "short_description": "Save/config folder found locally.",
            "local_only": not appid.isdigit(),
        }

    @classmethod
    def discover_save_library_entries(cls, steam_api=None) -> dict[str, dict[str, Any]]:
        """Discover save-only games for Library without listing normal apps.

        A candidate is added only if it is a curated known rule or if its folder
        name resolves confidently to a Steam game. This avoids turning AppData
        programs such as launchers into fake games.
        """
        found: dict[str, dict[str, Any]] = {}
        seen_paths: set[str] = set()
        checked = 0
        max_candidates = 450

        for pattern, kind in cls._candidate_scan_patterns():
            try:
                matches = glob.glob(cls.expand_vars(pattern))
            except Exception:
                matches = []
            for match in matches:
                if checked >= max_candidates:
                    return found
                checked += 1
                if not os.path.isdir(match):
                    continue
                norm_path = os.path.normcase(os.path.normpath(match))
                if norm_path in seen_paths:
                    continue
                seen_paths.add(norm_path)

                candidate_name = cls._name_from_candidate_path(match)
                known = kind == "known" or cls.known_rule_for_name(candidate_name) is not None
                if cls._is_blocked_folder(candidate_name):
                    continue
                if not known and not cls._has_save_like_content(match):
                    continue
                rule = cls.known_rule_for_name(candidate_name)
                if rule and rule.get("patterns_only") and kind != "known":
                    # Some games have internal project folder names that are too
                    # generic for engine-wide scanning. Example: LEGO Batman's
                    # config folder uses "Dinner". For those games, only trust
                    # the explicit curated paths, not every generic Saved folder
                    # under that alias.
                    continue

                game = cls._resolve_library_game(candidate_name, steam_api=steam_api, known=known)
                if not game:
                    continue

                appid = str(game.get("appid") or f"local-save:{normalize_name(game.get('name', candidate_name))}")
                if rule and rule.get("save_and_config"):
                    category = "Save & Config Files"
                    description = "Save and config folder"
                else:
                    match_norm = normalize_name(str(match))
                    category = "Config Files" if "config" in match_norm else "Save Files"
                    description = "Detected config folder" if category == "Config Files" else "Detected save folder"
                entry = cls._path_entry(match, category, description, "Save scan")
                if not entry:
                    continue

                bucket = found.setdefault(appid, {
                    **game,
                    "appid": appid,
                    "sources": [],
                    "paths": [],
                    "local_only": game.get("local_only", not appid.isdigit()),
                })
                if not any(os.path.normcase(os.path.normpath(item["path"])) == norm_path for item in bucket["paths"]):
                    bucket["paths"].append(entry)
        return found

    @classmethod
    def find_local_game_by_save_name(cls, query: str, steam_api=None) -> dict[str, Any] | None:
        query = (query or "").strip()
        if not query:
            return None
        rule = cls.known_rule_for_name(query)

        # If the query is one of a known game's aliases, search with the full
        # curated rule instead of a guessed local-only name. This catches cases
        # where the save folder name is unrelated to the public title, e.g.
        # LEGO Batman's config folder using "Dinner".
        if rule:
            canonical = str(rule.get("name") or query).strip()
            appid = str(rule.get("appid") or "").strip()
            game = cls._resolve_library_game(canonical, steam_api=steam_api, known=True) or {
                "appid": appid,
                "name": canonical,
                "developers": [],
                "publishers": [],
                "header_image": placeholder_header_image(canonical, "Local save search"),
                "short_description": "Local save/config search result.",
            }
        else:
            canonical = query
            game = {
                "appid": "",
                "name": canonical,
                "developers": [],
                "publishers": [],
                "header_image": placeholder_header_image(canonical, "Local save search"),
                "short_description": "Local save/config search result.",
            }

        paths = cls.find_save_paths(game, include_online=False)
        if not paths:
            return None
        return {**game, "paths": paths}

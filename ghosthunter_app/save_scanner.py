from __future__ import annotations

import glob
import html
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
        "assettocorsa": {
            "name": "Assetto Corsa",
            "appid": "244210",
            "aliases": ["Assetto Corsa", "assettocorsa"],
            "patterns": [
                r"{DOCS}\Assetto Corsa",
                r"{DOCS}\Assetto Corsa\cfg",
                r"{DOCS}\Assetto Corsa\setups",
                r"{DOCS}\Assetto Corsa\replay",
            ],
        },
        "assettocorsacompetizione": {
            "name": "Assetto Corsa Competizione",
            "appid": "805550",
            "aliases": ["Assetto Corsa Competizione", "ACC"],
            "patterns": [
                r"{DOCS}\Assetto Corsa Competizione",
                r"{DOCS}\Assetto Corsa Competizione\Config",
                r"{DOCS}\Assetto Corsa Competizione\Savegames",
                r"{DOCS}\Assetto Corsa Competizione\Customs",
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
        "thelastofusparti": {
            "name": "The Last of Us Part I",
            "appid": "1888930",
            "aliases": [
                "The Last of Us Part 1",
                "The Last of Us Part I",
                "The Last of Us™ Part I",
                "The Last of Us Part I Remake",
                "TLOU1",
                "TLOU Part I",
            ],
            "patterns": [
                r"{SAVEDGAMES}\The Last of Us Part I",
                r"{SAVEDGAMES}\The Last of Us Part I\users\*\savedata",
                r"{SAVEDGAMES}\The Last of Us Part I\users\*\screeninfo.cfg",
                r"{DOCS}\The Last of Us Part I",
            ],
        },
        "thelastofuspart1": {
            "name": "The Last of Us Part I",
            "appid": "1888930",
            "aliases": ["The Last of Us Part 1", "The Last of Us Part I", "The Last of Us™ Part I"],
            "patterns": [
                r"{SAVEDGAMES}\The Last of Us Part I",
                r"{SAVEDGAMES}\The Last of Us Part I\users\*\savedata",
                r"{SAVEDGAMES}\The Last of Us Part I\users\*\screeninfo.cfg",
                r"{DOCS}\The Last of Us Part I",
            ],
        },
        "thelastofuspartiiremastered": {
            "name": "The Last of Us Part II Remastered",
            "appid": "2531310",
            "aliases": [
                "The Last of Us Part II",
                "The Last of Us Part 2",
                "The Last of Us Part 2 Remastered",
                "TLOU2",
                "TLOU Part II",
            ],
            "patterns": [
                r"{DOCS}\The Last of Us Part II",
                r"{DOCS}\The Last of Us Part II\*\savedata",
                r"{SAVEDGAMES}\The Last of Us Part II",
                r"{SAVEDGAMES}\The Last of Us Part II\*\savedata",
            ],
        },
        "thelastofuspartii": {
            "name": "The Last of Us Part II Remastered",
            "appid": "2531310",
            "aliases": ["The Last of Us Part II", "The Last of Us Part 2"],
            "patterns": [
                r"{DOCS}\The Last of Us Part II",
                r"{DOCS}\The Last of Us Part II\*\savedata",
                r"{SAVEDGAMES}\The Last of Us Part II",
                r"{SAVEDGAMES}\The Last of Us Part II\*\savedata",
            ],
        },
        "kingdomcome2": {
            "name": "Kingdom Come: Deliverance II",
            "appid": "1771300",
            "aliases": [
                "Kingdom Come Deliverance 2",
                "Kingdom Come Deliverance II",
                "Kingdom Come: Deliverance 2",
                "Kingdom Come: Deliverance II",
                "kingdomcome2",
                "KCD2",
            ],
            "patterns": [
                r"{SAVEDGAMES}\kingdomcome2",
                r"{SAVEDGAMES}\kingdomcome2\saves",
                r"{SAVEDGAMES}\kingdomcome2\profiles\default",
            ],
        },
        "kingdomcomedeliveranceii": {
            "name": "Kingdom Come: Deliverance II",
            "appid": "1771300",
            "aliases": ["Kingdom Come Deliverance 2", "kingdomcome2", "KCD2"],
            "patterns": [
                r"{SAVEDGAMES}\kingdomcome2",
                r"{SAVEDGAMES}\kingdomcome2\saves",
                r"{SAVEDGAMES}\kingdomcome2\profiles\default",
            ],
        },
        "cairn": {
            "name": "Cairn",
            "appid": "1588550",
            "aliases": ["Cairn_RETAIL", "Cairn RETAIL", "TheGameBakers Cairn"],
            "patterns": [
                r"{SAVEDGAMES}\TheGameBakers\Cairn_RETAIL",
                r"{SAVEDGAMES}\TheGameBakers\Cairn_RETAIL\SAVEGAMES\RETAIL\STORY",
                r"{SAVEDGAMES}\TheGameBakers\Cairn_RETAIL\PERSISTENT\PLAYER",
                r"{SAVEDGAMES}\TheGameBakers\Cairn",
                r"{SAVEDGAMES}\TheGameBakers\Cairn\SAVEGAMES\STORY",
            ],
        },
        "cairnretail": {
            "name": "Cairn",
            "appid": "1588550",
            "aliases": ["Cairn_RETAIL", "Cairn RETAIL"],
            "patterns": [
                r"{SAVEDGAMES}\TheGameBakers\Cairn_RETAIL",
                r"{SAVEDGAMES}\TheGameBakers\Cairn_RETAIL\SAVEGAMES\RETAIL\STORY",
                r"{SAVEDGAMES}\TheGameBakers\Cairn_RETAIL\PERSISTENT\PLAYER",
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
        "betterdiscord", "brave", "cache", "code", "discord", "docker", "dropbox", "electron",
        "equicord", "epicgameslauncher", "githubdesktop", "google", "gog.com", "intel", "java",
        "jetbrains", "microsoft", "mozilla", "nodejs", "notepad++", "npm",
        "nvidia", "obs-studio", "obsstudio", "openasar", "opera software", "python", "qtproject",
        "spotify", "telegram desktop", "telegramdesktop", "unity", "unreal engine", "vencord",
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
            "{HOME}": user,
            "{SAVEDGAMES}": os.path.join(user, "Saved Games"),
            "{STEAM}": r"C:\Program Files (x86)\Steam",
        }

    @classmethod
    def expand_vars(cls, value: str) -> str:
        """Expand PCGamingWiki/Ludusavi-style save path placeholders."""
        result = html.unescape(str(value or "").strip())
        env = cls.env_map()
        result = re.sub(r"\[\s*(%[A-Z_]+%)\s*\]", r"\1", result, flags=re.I)

        placeholder_map = {
            "<home>": env["{USERPROFILE}"],
            "<winappdata>": env["{APPDATA}"],
            "<winlocalappdata>": env["{LOCAL}"],
            "<winlocalappdatalow>": env["{LOCALLOW}"],
            "<windocuments>": env["{DOCS}"],
            "<winpublic>": os.environ.get("PUBLIC", r"C:\Users\Public"),
            "<winprogramdata>": env["{PROGRAMDATA}"],
            "<steam>": env["{STEAM}"],
            "<root>": "*",
            "<base>": "*",
            "<game>": "*",
            "<osusername>": os.path.basename(env["{USERPROFILE}"].rstrip("\\/")) or "*",
        }
        for old, replacement in placeholder_map.items():
            result = re.sub(re.escape(old), lambda _m, repl=replacement: repl, result, flags=re.I)

        result = re.sub(
            r"[\[\(]?\s*<\s*(?:user[-_ ]?id|store[-_ ]?user[-_ ]?id|steam[-_ ]?user[-_ ]?id|guid|uuid)\s*>\s*[\]\)]?",
            "*",
            result,
            flags=re.I,
        )

        brace_replacements = {
            "{{p|appdata}}": "{APPDATA}",
            "{{p|localappdata}}": "{LOCAL}",
            "{{p|localappdatalow}}": "{LOCALLOW}",
            "{{p|userprofile}}": "{USERPROFILE}",
            "{{p|documents}}": "{DOCS}",
            "{{p|savedgames}}": "{SAVEDGAMES}",
            "{{p|programdata}}": "{PROGRAMDATA}",
            "{{p|public}}": os.environ.get("PUBLIC", r"C:\Users\Public"),
            "{{p|steam}}": "{STEAM}",
            "{{p|uid}}": "*",
        }
        for old, replacement in brace_replacements.items():
            result = re.sub(re.escape(old), lambda _m, repl=replacement: repl, result, flags=re.I)

        percent_replacements = {
            "%APPDATA%": env["{APPDATA}"],
            "%LOCALAPPDATA%": env["{LOCAL}"],
            "%USERPROFILE%": env["{USERPROFILE}"],
            "%PUBLIC%": os.environ.get("PUBLIC", r"C:\Users\Public"),
            "%PROGRAMDATA%": env["{PROGRAMDATA}"],
            "%HOMEPATH%": env["{USERPROFILE}"],
        }
        for old, replacement in percent_replacements.items():
            result = re.sub(re.escape(old), lambda _m, repl=replacement: repl, result, flags=re.I)

        for key, replacement in env.items():
            result = result.replace(key, replacement)
        result = os.path.expandvars(result)
        if os.sep == "/":
            result = result.replace("\\", os.sep)
        return os.path.normpath(result)

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
    def _virtualized_candidates(cls, path: str) -> list[str]:
        """Add Windows VirtualStore equivalent for exact protected paths."""
        raw = str(path or "")
        match = re.match(r"^([A-Z]):[\\/](Program Files(?: \(x86\))?|Windows|ProgramData)[\\/](.+)$", raw, flags=re.I)
        if not match:
            return []
        local = cls.env_map()["{LOCAL}"]
        tail = os.path.join(match.group(2), match.group(3).replace("/", os.sep).replace("\\", os.sep))
        return [os.path.join(local, "VirtualStore", tail)]

    @classmethod
    def _steam_roots(cls) -> list[str]:
        """Return installed Steam roots including libraryfolders.vdf entries."""
        roots = [
            cls.env_map()["{STEAM}"],
            r"C:\Program Files (x86)\Steam",
            r"C:\Program Files\Steam",
            r"D:\Steam",
            r"D:\Games\Steam",
            r"E:\Steam",
            r"E:\Games\Steam",
        ]
        for root in list(roots):
            vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
            if not os.path.isfile(vdf):
                continue
            try:
                text = Path(vdf).read_text(encoding="utf-8", errors="ignore")
                for match in re.finditer(r'"path"\s+"([^"]+)"', text):
                    candidate = match.group(1).replace('\\\\', '\\')
                    if os.path.isdir(candidate):
                        roots.append(candidate)
            except Exception:
                pass
        seen: set[str] = set()
        out: list[str] = []
        for root in roots:
            if not root or not os.path.isdir(root):
                continue
            norm = os.path.normcase(os.path.normpath(root))
            if norm in seen:
                continue
            seen.add(norm)
            out.append(root)
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
    def known_rule_for_pattern(cls, pattern: str) -> dict[str, Any] | None:
        wanted = str(pattern or "").lower()
        if not wanted:
            return None
        for rule in cls.KNOWN_GAMES.values():
            for candidate in rule.get("patterns") or []:
                if str(candidate or "").lower() == wanted:
                    return rule
        return None

    @classmethod
    def canonical_game_name(cls, name: str) -> str:
        rule = cls.known_rule_for_name(name)
        return str((rule or {}).get("name") or name or "").strip()

    @staticmethod
    def _title_save_folder_variants(name: str) -> list[str]:
        """Generate conservative title variants used by save folders.

        Store titles often include trademark symbols or edition suffixes that
        folder names omit, and PC folders may use Roman numerals while Steam
        titles use Arabic numerals. Keep this bounded to exact title variants so
        Home search improves without reintroducing broad AppData scanning.
        """
        raw = str(name or "").strip()
        if not raw:
            return []
        cleaned = re.sub(r"[™®©]", "", raw).replace("(TM)", "").strip()
        variants = {raw, cleaned}
        suffix_pattern = r"\s*[-:–—]?\s*(remastered|remake|definitive edition|complete edition|director'?s cut|game of the year edition|goty edition)$"
        for value in list(variants):
            stripped = re.sub(suffix_pattern, "", value, flags=re.I).strip()
            if stripped and stripped != value:
                variants.add(stripped)

        roman_pairs = [
            (r"\bPart\s+1\b", "Part I"),
            (r"\bPart\s+I\b", "Part 1"),
            (r"\bPart\s+2\b", "Part II"),
            (r"\bPart\s+II\b", "Part 2"),
            (r"\bII\b", "2"),
            (r"\bIII\b", "3"),
            (r"\bIV\b", "4"),
        ]
        for value in list(variants):
            for pattern, replacement in roman_pairs:
                converted = re.sub(pattern, replacement, value, flags=re.I).strip()
                if converted and converted != value:
                    variants.add(converted)
        return [item for item in variants if item]

    @classmethod
    def _saved_games_folder_candidates(cls, game_name: str) -> list[str]:
        """Candidate folders under Saved Games/Documents for one title.

        These are still focused on a selected title, but they cover common
        nested layouts:
        - Saved Games/<Game>/users/<id>/savedata
        - Saved Games/<Studio>/<Game>/SAVEGAMES
        """
        folders: list[str] = []
        roots = [
            r"{SAVEDGAMES}\{GAME}",
            r"{SAVEDGAMES}\*\{GAME}",
            r"{DOCS}\{GAME}",
            r"{DOCS}\*\{GAME}",
        ]
        subfolders = [
            "",
            r"\savedata",
            r"\SaveData",
            r"\SAVEGAMES",
            r"\SaveGames",
            r"\savegames",
            r"\saves",
            r"\Saves",
            r"\PERSISTENT",
            r"\PERSISTENT\PLAYER",
            r"\users\*",
            r"\users\*\savedata",
            r"\users\*\SaveData",
            r"\users\*\saves",
            r"\users\*\Saves",
            r"\*\savedata",
            r"\*\SaveData",
            r"\*\SAVEGAMES",
            r"\*\saves",
            r"\*\Saves",
        ]
        for root in roots:
            for subfolder in subfolders:
                folders.append((root + subfolder).replace("{GAME}", game_name))
        return folders

    @staticmethod
    def _clean_saved_games_name(name: str) -> str:
        clean = re.sub(r"(?i)(?:[-_ ]?(old|backup|bak|copy|autosave|manualsave))+$", "", str(name or "")).strip(" -_()[]")
        return clean or str(name or "").strip()

    @classmethod
    def _saved_games_child_game_dirs(cls, root: str) -> list[str]:
        """Return likely game folders one/two levels below Saved Games.

        This avoids treating a publisher folder like "TheGameBakers" as the
        game when the real game is in a child folder such as "Cairn_RETAIL".
        It also skips backup folders like "Game-old" so they do not become
        separate Library entries.
        """
        if not os.path.isdir(root):
            return []
        save_tokens = {"save", "saves", "savedata", "savegames", "slot", "profile", "users", "persistent"}
        out: list[str] = []
        try:
            for first in Path(root).iterdir():
                if not first.is_dir():
                    continue
                first_name = first.name
                first_norm = normalize_name(first_name)
                if first_norm in {"desktop", "downloads", "documents"}:
                    continue
                # A top-level backup like "Game-old" belongs to the same game;
                # don't create a second card for it.
                if cls._clean_saved_games_name(first_name) != first_name:
                    continue
                child_dirs = []
                try:
                    child_dirs = [child for child in first.iterdir() if child.is_dir()]
                except Exception:
                    child_dirs = []
                promoted = False
                for child in child_dirs[:40]:
                    child_norm = normalize_name(child.name)
                    if child_norm in save_tokens or cls._clean_saved_games_name(child.name) != child.name:
                        continue
                    if cls._has_save_like_content(str(child)):
                        out.append(str(child))
                        promoted = True
                if not promoted and cls._has_save_like_content(str(first)):
                    out.append(str(first))
        except Exception:
            pass
        return cls._dedupe(out, limit=300)


    @classmethod
    def folder_names_for_game(cls, game: dict[str, Any]) -> list[str]:
        raw = str(game.get("name") or "").strip()
        values = cls._title_save_folder_variants(raw)
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
        matches: list[str] = []
        for candidate in [expanded, *cls._virtualized_candidates(expanded)]:
        try:
                if any(ch in candidate for ch in "*?"):
                    matches.extend(glob.glob(candidate))
                elif os.path.exists(candidate):
                    matches.append(candidate)
        except Exception:
                continue
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

        # Steam cloud/userdata is an exact AppID-based signal. This mirrors the
        # save-backup scanner's Steam userdata rule, but stays bounded to the
        # selected game instead of scanning every userdata folder.
        appid = str(game.get("appid") or "").strip()
        if appid.isdigit():
            for steam_root in cls._steam_roots():
                cls._add_matches(results, seen, os.path.join(steam_root, "userdata", "*", appid, "remote"), "Save Files", "Steam Cloud save folder", "Known rule")
                cls._add_matches(results, seen, os.path.join(steam_root, "userdata", "*", appid), "Save Files", "Steam userdata folder", "Known rule")

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
            for candidate in cls._saved_games_folder_candidates(game_name):
                cls._add_matches(results, seen, candidate, "Save Files", "Saved Games/Documents save folder")

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
                    cls._add_matches(results, seen, template.replace("{PERSON}", person).replace("{GAME}", game_name), category, description)

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
        value = html.unescape(text or "")
        replacements = {
            r"{{p|appdata}}": "{APPDATA}",
            r"{{p|localappdata}}": "{LOCAL}",
            r"{{p|localappdatalow}}": "{LOCALLOW}",
            r"{{p|userprofile}}": "{USERPROFILE}",
            r"{{p|documents}}": "{DOCS}",
            r"{{p|savedgames}}": "{SAVEDGAMES}",
            r"{{p|programdata}}": "{PROGRAMDATA}",
            r"{{p|public}}": os.environ.get("PUBLIC", r"C:\Users\Public"),
            r"{{p|steam}}": "{STEAM}",
            r"{{p|uid}}": "*",
        }
        for old, new in replacements.items():
            # Lambda avoids re.sub interpreting Windows paths as escapes (\U).
            value = re.sub(re.escape(old), lambda _match, replacement=new: replacement, value, flags=re.I)
        # Markdown links from copied PCGW text, MediaWiki external links, and wiki links.
        value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
        value = re.sub(r"\[https?://[^\s\]]+\s+([^\]]+)\]", r"\1", value)
        value = re.sub(r"\[\[([^\]|]+\|)?([^\]]+)\]\]", r"\2", value)
        value = value.replace("&lt;", "<").replace("&gt;", ">")
        protected: dict[str, str] = {}
        def protect_placeholder(match: re.Match[str]) -> str:
            key = f"__GHP_PLACEHOLDER_{len(protected)}__"
            protected[key] = match.group(0)
            return key
        value = re.sub(r"<(?:home|winAppData|winLocalAppData|winLocalAppDataLow|winDocuments|winPublic|winProgramData|steam|user[-_ ]?id|store[-_ ]?user[-_ ]?id|steam[-_ ]?user[-_ ]?id|guid|uuid)>", protect_placeholder, value, flags=re.I)
        value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
        value = re.sub(r"<[^>]+>", " ", value)
        for key, original in protected.items():
            value = value.replace(key, original)
        value = re.sub(r"{{[^{}]*}}", "", value)
        value = value.replace("[*]", "*")
        return value.strip()

    @staticmethod
    def _looks_like_windows_save_path(value: str) -> bool:
        low = str(value or "").lower()
        if any(token in low for token in ("macos", "os x", "linux", "android", "ios", "switch", "playstation")):
            return False
        return any(token in low for token in (
            "{appdata}", "{local}", "{locallow}", "{docs}", "{userprofile}", "{savedgames}",
            "{programdata}", "{steam}", "%appdata%", "%localappdata%", "%userprofile%",
            "%programdata%", "<win", "<home>", "c:\\", "c:/",
        ))

    @classmethod
    def _clean_path_candidate(cls, value: str) -> str:
        candidate = cls._strip_wiki_markup(value)
        candidate = re.sub(r"\s+", " ", candidate).strip().strip(" .;,:|\"'")
        # PCGW often wraps placeholder notes in square brackets, e.g. [<user-id>].
        candidate = re.sub(r"\[\s*(<[^>]+>|%[A-Z_]+%)\s*\]", r"\1", candidate, flags=re.I)
        candidate = candidate.replace("/", "\\")
        return candidate

    @classmethod
    def _extract_path_candidates_from_text(cls, text: str, context: str = "") -> list[tuple[str, str]]:
        cleaned = cls._strip_wiki_markup(text)
        if not cls._looks_like_windows_save_path(cleaned):
            return []
        section_match = re.search(
            r"(=+\s*Game data\s*=+.*?)(?:\n=+\s*(?:Video|Input|Audio|Network|Issues|Other information|System requirements)\s*=+|\Z)",
            wikitext,
            flags=re.I | re.S,
        )
        section = section_match.group(1) if section_match else wikitext
        results: list[tuple[str, str]] = []
        pattern = re.compile(
            r"(?:\{(?:APPDATA|LOCAL|LOCALLOW|DOCS|USERPROFILE|SAVEDGAMES|PROGRAMDATA|STEAM|HOME)\}|%[A-Z_]+%|<(?:home|winAppData|winLocalAppData|winLocalAppDataLow|winDocuments|winPublic|winProgramData|steam)>|[A-Z]:[\\/])[^|\n\r}]*",
                flags=re.I,
            )
        for match in pattern.finditer(cleaned):
            candidate = cls._clean_path_candidate(match.group(0))
            candidate = re.split(r"\s{2,}|\t|</td>|</tr>", candidate)[0].strip()
            if len(candidate) < 5 or not cls._looks_like_windows_save_path(candidate):
                    continue
            low = f"{context} {cleaned} {candidate}".lower()
            is_config = any(token in low for token in ("config", "configuration", "settings", ".ini", ".cfg"))
            kind = "Config Files" if is_config else "Save Files"
                results.append((candidate, kind))
        return results

    @staticmethod
    def _dedupe_path_kinds(results: list[tuple[str, str]], limit: int = 24) -> list[tuple[str, str]]:
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for path, kind in results:
            path = str(path or "").strip()
            if not path:
                continue
            key = path.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append((path, kind))
            if len(out) >= limit:
                break
        return out

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
            if line:
                results.extend(cls._extract_path_candidates_from_text(line, line))
        return cls._dedupe_path_kinds(results)

    @classmethod
    def _pcgw_sections(cls, title: str) -> list[dict[str, Any]]:
        if not title:
            return []
        data = cls._pcgw_api_json({"action": "parse", "format": "json", "page": title, "prop": "sections", "formatversion": "2"})
        try:
            return list(data["parse"]["sections"])
        except Exception:
            return []

    @classmethod
    def _pcgw_section_html(cls, title: str, section_index: str) -> str:
        if not title or not section_index:
            return ""
        data = cls._pcgw_api_json({"action": "parse", "format": "json", "page": title, "section": str(section_index), "formatversion": "2"})
        try:
            return str(data["parse"]["text"])
        except Exception:
            return ""

    @classmethod
    def _extract_pcgw_paths_from_html(cls, section_html: str) -> list[tuple[str, str]]:
        if not section_html:
            return []
        text = re.sub(r"<br\s*/?>", "\n", section_html, flags=re.I)
        text = re.sub(r"</t[dh]>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        return cls._dedupe_path_kinds(cls._extract_path_candidates_from_text(text, text))

    @classmethod
    def _pcgw_html_save_paths(cls, title: str) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        for section in cls._pcgw_sections(title):
            line = str(section.get("line") or "").lower()
            if "save game data location" not in line and "configuration file" not in line:
                continue
            results.extend(cls._extract_pcgw_paths_from_html(cls._pcgw_section_html(title, str(section.get("index") or ""))))
        return cls._dedupe_path_kinds(results)

    @classmethod
    def pcgw_save_paths(cls, game: dict[str, Any], fetch_missing: bool = True) -> list[dict[str, Any]]:
        cache = safe_read_json(PCGW_CACHE_FILE, {})
        key = cls._pcgw_cache_key(game)
        if isinstance(cache, dict) and key in cache:
            raw_paths = cache.get(key) or []
        elif fetch_missing:
            title = cls._pcgw_page_title(game)
            raw_paths = cls._dedupe_path_kinds([
                *cls._extract_pcgw_paths(cls._pcgw_wikitext(title)),
                *cls._pcgw_html_save_paths(title),
            ])
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
            # Do not enumerate every Saved Games/Documents folder into the
            # Library. Those locations are useful for focused Home searches, but
            # Library-wide discovery must stay curated or it will turn backups,
            # Discord mods, and utility folders into game cards.
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
        if norm in {"saved", "savegames", "savedata", "saves", "config", "profiles", "profile", "persistent", "player", "story", "retail"}:
            parent = current.parent
            parent_norm = normalize_name(parent.name)
            if norm in {"savegames", "config"} and parent_norm == "saved":
                parent = parent.parent
            elif norm in {"savedata", "saves"} and normalize_name(parent.parent.name) == "users":
                parent = parent.parent.parent
            elif norm == "story" and parent_norm == "retail" and normalize_name(parent.parent.name) in {"savegames", "savedata", "saves"}:
                parent = parent.parent.parent
            elif norm in {"story", "retail"} and parent_norm in {"savegames", "savedata", "saves"}:
                parent = parent.parent
            elif norm in {"player"} and normalize_name(parent.name) == "persistent":
                parent = parent.parent
            elif parent_norm in {"users", "user", "profiles", "profile"}:
                parent = parent.parent
            name = parent.name
        elif norm in {"users", "user"}:
            name = current.parent.name
        name = cls._clean_saved_games_name(name)
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
    def _resolve_library_game(
        cls,
        name: str,
        steam_api=None,
        known: bool = False,
        allow_safe_local: bool = False,
        allow_steam_lookup: bool = False,
    ) -> dict[str, Any] | None:
        if not name or cls._is_blocked_folder(name):
            return None
        rule = cls.known_rule_for_name(name)

        # Unknown AppData/LocalLow folders are not enough to create Library
        # cards. For Windows "Saved Games" and Documents folders, however, the
        # location itself is already a strong save signal, so we allow a bounded
        # Steam lookup or a local-only card.
        if not rule and not allow_safe_local and not allow_steam_lookup:
            return None

        canonical = str((rule or {}).get("name") or name).strip()
        appid = str((rule or {}).get("appid") or "").strip()

        resolved = None
        if steam_api is not None:
            try:
                if appid.isdigit():
                    resolved = steam_api.get_app_details(appid, timeout=2) or steam_api.seed_cache_entry(appid, canonical)
                elif allow_steam_lookup:
                    resolved = steam_api.search_game(canonical, timeout=2)
                    if resolved:
                        resolved_name = str(resolved.get("name") or "")
                        resolved_norm = normalize_name(resolved_name)
                        canonical_norm = normalize_name(canonical)
                        if not resolved_norm or (
                            resolved_norm != canonical_norm
                            and canonical_norm not in resolved_norm
                            and resolved_norm not in canonical_norm
                        ):
                            resolved = None
            except Exception:
                resolved = None

        if resolved:
            return dict(resolved)

        if not rule and not allow_safe_local:
            return None

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

                pattern_rule = cls.known_rule_for_pattern(pattern) if kind == "known" else None
                if pattern_rule:
                    # Curated patterns may point at nested implementation folders
                    # such as Documents\The Last of Us Part II\<id>\savedata or
                    # Documents\Assetto Corsa\cfg. Keep those paths attached to
                    # the curated game instead of treating the leaf folder as a
                    # separate game card.
                    candidate_name = str(pattern_rule.get("name") or cls._name_from_candidate_path(match))
                else:
                candidate_name = cls._name_from_candidate_path(match)
                    cleaned_candidate_name = cls._clean_saved_games_name(candidate_name)
                    if kind.startswith("savedgames") and cleaned_candidate_name != candidate_name:
                        # Backup folders such as "Game-old" are part of the same
                        # game's save data, not a second game card.
                        continue
                    candidate_name = cleaned_candidate_name
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

                # Library auto-discovery is intentionally strict: only
                # curated known rules may create save-only cards. Focused Home
                # search still checks generic Saved Games/Documents patterns for
                # the selected title.
                game = cls._resolve_library_game(
                    candidate_name,
                    steam_api=steam_api,
                    known=known,
                    allow_safe_local=known,
                    allow_steam_lookup=False,
                )
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

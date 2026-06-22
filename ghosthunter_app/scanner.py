from __future__ import annotations

import glob
import json
import os
import re
from typing import Any

from .utils import get_name_variations, normalize_name, path_size


class ScanEngine:
    HOME_TEMPLATES = [
        ("{APPDATA}\\{GAME}", "AppData (Roaming)", "Game config / save data", False, True, False, False),
        ("{APPDATA}\\{DEV}\\{GAME}", "AppData (Roaming)", "Developer-organized game data", False, True, True, False),
        ("{LOCAL}\\{GAME}", "AppData (Local)", "Local cache / settings", False, True, False, False),
        ("{LOCAL}\\{DEV}\\{GAME}", "AppData (Local)", "Developer-organized local data", False, True, True, False),
        ("{LOCALLOW}\\{GAME}", "AppData (LocalLow)", "LocalLow game data", False, True, False, False),
        ("{LOCALLOW}\\{DEV}\\{GAME}", "AppData (LocalLow)", "Developer-organized LocalLow data", False, True, True, False),
        ("{DOCS}\\{GAME}", "Documents", "Save files / screenshots", False, True, False, False),
        ("{DOCS}\\My Games\\{GAME}", "Documents", "My Games folder", False, True, False, False),
        ("{DOCS}\\{DEV}\\{GAME}", "Documents", "Developer-organized saves", False, True, True, False),
        ("{PUBLICDOCS}\\{GAME}", "Public Documents", "Shared game data", False, True, False, False),
        ("{PROGRAMDATA}\\{GAME}", "ProgramData", "System-wide game data", False, True, False, False),
        ("{PROGRAMDATA}\\{DEV}\\{GAME}", "ProgramData", "Developer-organized ProgramData", False, True, True, False),
        ("{SAVEDGAMES}\\{GAME}", "Saved Games", "Saved Games folder", False, True, False, False),
        ("{TEMP}\\{GAME}", "Temp Files", "Temporary game files", False, True, False, False),
        ("{LOCAL}\\NVIDIA Corporation\\NVIDIA App\\NvBackend\\Recommendations\\{APPID}", "NVIDIA", "NVIDIA recommendations", True, False, False, False),
        ("{LOCAL}\\NVIDIA Corporation\\NVIDIA App\\NvBackend\\ApplicationOntology\\data\\wrappers\\{GAME}", "NVIDIA", "NVIDIA wrappers", False, True, False, False),
        ("{LOCAL}\\NVIDIA Corporation\\NVIDIA App\\NvBackend\\ApplicationOntology\\data\\translations\\{GAME}", "NVIDIA", "NVIDIA translations", False, True, False, False),
        ("{APPDATA}\\STAR\\{APPID}", "Crack Leftovers (STAR)", "STAR app cache by AppID", True, False, False, False),
        ("{APPDATA}\\STAR\\{APPID}\\{STEAMID}", "Crack Leftovers (STAR)", "STAR per-user cache folder", True, False, False, True),
        ("{APPDATA}\\Steam\\CODEX\\{APPID}", "Crack Leftovers (CODEX)", "CODEX save/config data", True, False, False, False),
        ("{APPDATA}\\Steam\\RUNE\\{APPID}", "Crack Leftovers (RUNE)", "RUNE emulator data", True, False, False, False),
        ("{APPDATA}\\OnlineFix\\{APPID}", "Crack Leftovers (OnlineFix)", "OnlineFix data", True, False, False, False),
        ("{APPDATA}\\EMPRESS\\{APPID}", "Crack Leftovers (EMPRESS)", "EMPRESS data", True, False, False, False),
        ("{APPDATA}\\GSE Saves\\{APPID}", "Crack Leftovers (GSE)", "Goldberg Steam Emu saves", True, False, False, False),
        ("{APPDATA}\\SmartSteamEmu\\{APPID}", "Crack Leftovers (SSE)", "SmartSteamEmu data", True, False, False, False),
        ("{APPDATA}\\Goldberg SteamEmu Saves\\{APPID}", "Crack Leftovers (Goldberg)", "Goldberg emulator saves", True, False, False, False),
        ("{APPDATA}\\ALI213\\{APPID}", "Crack Leftovers (ALI213)", "ALI213 crack data", True, False, False, False),
        ("{STEAM}\\userdata\\*\\{APPID}", "Steam Userdata", "Steam cloud saves / configs", True, False, False, False),
        ("{STEAM}\\steamapps\\shadercache\\{APPID}", "Steam Shader Cache", "Compiled shader cache", True, False, False, False),
        ("{STEAM}\\steamapps\\workshop\\content\\{APPID}", "Steam Workshop", "Workshop content", True, False, False, False),
        ("{STEAM}\\steamapps\\compatdata\\{APPID}", "Steam CompatData", "Compatibility / Proton data", True, False, False, False),
    ]

    CRACK_EMU_NAMES = [
        r"Steam\CODEX",
        r"Steam\RUNE",
        "OnlineFix",
        "EMPRESS",
        "GSE Saves",
        "SmartSteamEmu",
        "Goldberg SteamEmu Saves",
        "ALI213",
        "STAR",
    ]

    @staticmethod
    def env_map() -> dict[str, str]:
        user = os.environ.get("USERPROFILE", "%USERPROFILE%")
        return {
            "{APPDATA}": os.environ.get("APPDATA", "%APPDATA%"),
            "{LOCAL}": os.environ.get("LOCALAPPDATA", "%LOCALAPPDATA%"),
            "{LOCALLOW}": os.path.join(user, "AppData", "LocalLow"),
            "{DOCS}": os.path.join(user, "Documents"),
            "{PUBLICDOCS}": os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Documents"),
            "{TEMP}": os.path.join(os.environ.get("LOCALAPPDATA", "%LOCALAPPDATA%"), "Temp"),
            "{PROGRAMDATA}": os.environ.get("PROGRAMDATA", "%PROGRAMDATA%"),
            "{USERPROFILE}": user,
            "{SAVEDGAMES}": os.path.join(user, "Saved Games"),
            "{STEAM}": r"C:\Program Files (x86)\Steam",
        }

    @classmethod
    def expand_template(cls, template: str) -> str:
        value = template
        for key, expanded in cls.env_map().items():
            value = value.replace(key, expanded)
        return value

    @classmethod
    def generate_home_candidates(cls, game: dict[str, Any], steam_id: str = "") -> list[dict[str, Any]]:
        name_vars = get_name_variations(game.get("name", ""))
        dev_vars: list[str] = []
        for dev in game.get("developers", []):
            dev_vars.extend(get_name_variations(dev))
        for pub in game.get("publishers", []):
            dev_vars.extend(get_name_variations(pub))
        dev_vars = list(dict.fromkeys(v for v in dev_vars if v))

        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        has_appid = bool(str(game.get('appid', '')).strip())
        for template, category, description, uses_appid, uses_game, uses_dev, uses_steamid in cls.HOME_TEMPLATES:
            base = cls.expand_template(template)
            game_names = name_vars if uses_game else [None]
            dev_names = dev_vars if uses_dev else [None]
            if uses_dev and not dev_names:
                continue
            for game_name in game_names:
                for dev_name in dev_names:
                    path = base
                    if uses_appid:
                        if not has_appid:
                            continue
                        path = path.replace("{APPID}", str(game.get("appid", "")))
                    if uses_game and game_name is not None:
                        path = path.replace("{GAME}", game_name)
                    if uses_dev and dev_name is not None:
                        path = path.replace("{DEV}", dev_name)
                    if uses_steamid:
                        path = path.replace("{STEAMID}", steam_id.strip() if steam_id.strip() else "*")
                    norm = os.path.normcase(path)
                    if norm in seen:
                        continue
                    seen.add(norm)
                    results.append({
                        "path": path,
                        "category": category,
                        "description": description,
                        "risk": "caution" if category.startswith("Steam ") else "safe",
                    })
        return results

    @staticmethod
    def resolve_candidate(candidate: dict[str, Any]) -> list[dict[str, Any]]:
        raw_path = os.path.expandvars(candidate["path"])
        try:
            matches = glob.glob(raw_path) if "*" in raw_path else ([raw_path] if os.path.exists(raw_path) else [])
        except Exception:
            matches = []
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for match in matches:
            if not os.path.exists(match):
                continue
            norm = os.path.normcase(os.path.normpath(match))
            if norm in seen:
                continue
            seen.add(norm)
            results.append({
                "path": match,
                "category": candidate["category"],
                "description": candidate["description"],
                "risk": candidate.get("risk", "safe"),
                "size": path_size(match),
                "is_dir": os.path.isdir(match),
            })
        return results

    @staticmethod
    def collapse_selected_paths(paths: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for path in paths:
            norm = os.path.normcase(os.path.normpath(path))
            if norm in seen:
                continue
            seen.add(norm)
            normalized.append(os.path.normpath(path))
        normalized.sort(key=lambda value: len(os.path.normpath(value)))
        kept: list[str] = []
        kept_norm: list[str] = []
        for path in normalized:
            norm = os.path.normcase(os.path.normpath(path))
            if any(norm == parent or norm.startswith(parent + os.sep) for parent in kept_norm):
                continue
            kept.append(path)
            kept_norm.append(norm)
        return kept

    @staticmethod
    def detect_steam_install_path() -> str | None:
        if os.name == "nt":
            registry_locations = [
                ("HKEY_LOCAL_MACHINE", r"SOFTWARE\WOW6432Node\Valve\Steam"),
                ("HKEY_LOCAL_MACHINE", r"SOFTWARE\Valve\Steam"),
                ("HKEY_CURRENT_USER", r"Software\Valve\Steam"),
            ]
            for hive_name, key_path in registry_locations:
                try:
                    import winreg  # type: ignore
                    hive = getattr(winreg, hive_name)
                    key = winreg.OpenKey(hive, key_path)
                    path, _ = winreg.QueryValueEx(key, "InstallPath")
                    winreg.CloseKey(key)
                    if os.path.isdir(path):
                        return path
                except Exception:
                    continue
        for candidate in [
            r"C:\Program Files (x86)\Steam",
            r"C:\Program Files\Steam",
            r"D:\Steam",
            r"D:\Games\Steam",
            r"E:\Steam",
            r"E:\Games\Steam",
        ]:
            if os.path.isdir(candidate):
                return candidate
        return None

    @classmethod
    def steam_library_paths(cls) -> list[str]:
        steam_dir = cls.detect_steam_install_path() or cls.expand_template("{STEAM}")
        libraries: list[str] = []
        steamapps = os.path.join(steam_dir, "steamapps")
        if os.path.isdir(steamapps):
            libraries.append(steamapps)
        libraryfolders = os.path.join(steamapps, "libraryfolders.vdf")
        if os.path.isfile(libraryfolders):
            try:
                text = open(libraryfolders, "r", encoding="utf-8", errors="ignore").read()
                for match in re.finditer(r'"path"\s+"([^"]+)"', text):
                    raw = match.group(1).replace('\\\\', '\\')
                    path = os.path.join(raw, "steamapps")
                    if os.path.isdir(path):
                        libraries.append(path)
            except Exception:
                pass

        # Fallback common Steam library locations across drives.
        for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            for tail in [r"SteamLibrary\steamapps", r"Steam\steamapps", r"Games\Steam\steamapps"]:
                candidate = f"{drive}:\\{tail}"
                if os.path.isdir(candidate):
                    libraries.append(candidate)

        seen: set[str] = set()
        result: list[str] = []
        for path in libraries:
            norm = os.path.normcase(os.path.normpath(path))
            if norm in seen:
                continue
            seen.add(norm)
            result.append(path)
        return result

    @staticmethod
    def _name_matches(candidate: str, game_name: str) -> bool:
        cand = normalize_name(candidate)
        game = normalize_name(game_name)
        if not cand or not game:
            return False
        return cand == game or cand in game or game in cand

    @classmethod
    def detect_installed_sources(cls, appid: str, game_name: str) -> list[str]:
        sources: list[str] = []

        for steamapps in cls.steam_library_paths():
            manifest = os.path.join(steamapps, f"appmanifest_{appid}.acf")
            if os.path.isfile(manifest):
                sources.append("Steam")
                break

        epic_manifests = os.path.join(
            os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
            "Epic",
            "EpicGamesLauncher",
            "Data",
            "Manifests",
        )
        if os.path.isdir(epic_manifests):
            try:
                for name in os.listdir(epic_manifests):
                    if not name.lower().endswith('.item'):
                        continue
                    full = os.path.join(epic_manifests, name)
                    try:
                        data = json.loads(open(full, 'r', encoding='utf-8', errors='ignore').read())
                    except Exception:
                        continue
                    display = str(data.get('DisplayName') or '')
                    install_location = str(data.get('InstallLocation') or '')
                    if install_location and os.path.exists(install_location) and cls._name_matches(display, game_name):
                        sources.append("Epic")
                        break
            except Exception:
                pass

        gog_roots = [
            r"C:\GOG Games",
            r"D:\GOG Games",
            r"E:\GOG Games",
        ]
        for root in gog_roots:
            if not os.path.isdir(root):
                continue
            try:
                for name in os.listdir(root):
                    full = os.path.join(root, name)
                    if os.path.isdir(full) and cls._name_matches(name, game_name):
                        sources.append("GOG")
                        raise StopIteration
            except StopIteration:
                break
            except Exception:
                continue

        seen: set[str] = set()
        ordered: list[str] = []
        for source in sources:
            key = source.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(source)
        return ordered

    @classmethod
    def discover_installed_games(cls, steam_api) -> dict[str, dict[str, Any]]:
        catalog: dict[str, dict[str, Any]] = {}

        def add_game(appid: str, name: str, source: str, **extra: Any) -> None:
            appid = str(appid)
            if not appid:
                return
            entry = catalog.setdefault(appid, {
                "appid": appid,
                "name": name,
                "sources": [],
                "header_image": extra.get("header_image", ""),
                "short_description": extra.get("short_description", ""),
                "developers": extra.get("developers", []),
                "publishers": extra.get("publishers", []),
                "local_only": extra.get("local_only", False),
            })
            if name and (not entry.get("name") or str(entry.get("name", "")).startswith("Unknown Game")):
                entry["name"] = name
            for key in ("header_image", "short_description"):
                if extra.get(key) and not entry.get(key):
                    entry[key] = extra[key]
            for key in ("developers", "publishers"):
                if extra.get(key) and not entry.get(key):
                    entry[key] = extra[key]
            if source not in entry["sources"]:
                entry["sources"].append(source)

        # Steam manifests from all libraries
        for steamapps in cls.steam_library_paths():
            if not os.path.isdir(steamapps):
                continue
            try:
                for file_name in os.listdir(steamapps):
                    if not (file_name.startswith("appmanifest_") and file_name.endswith(".acf")):
                        continue
                    appid = file_name[len("appmanifest_"):-4]
                    manifest_path = os.path.join(steamapps, file_name)
                    name = ""
                    install_dir_name = ""
                    try:
                        content = open(manifest_path, 'r', encoding='utf-8', errors='ignore').read()
                        match = re.search(r'"name"\s+"([^"]+)"', content)
                        if match:
                            name = match.group(1)
                        install_match = re.search(r'"installdir"\s+"([^"]+)"', content)
                        if install_match:
                            install_dir_name = install_match.group(1)
                    except Exception:
                        pass
                    final_name = name or install_dir_name or f"Unknown Game ({appid})"
                    normalized = steam_api.seed_cache_entry(appid, final_name)
                    add_game(appid, normalized["name"], "Steam", **normalized)
            except Exception:
                continue

        # Epic manifests
        epic_manifests = os.path.join(
            os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
            "Epic",
            "EpicGamesLauncher",
            "Data",
            "Manifests",
        )
        if os.path.isdir(epic_manifests):
            try:
                for name in os.listdir(epic_manifests):
                    if not name.lower().endswith('.item'):
                        continue
                    full = os.path.join(epic_manifests, name)
                    try:
                        data = json.loads(open(full, 'r', encoding='utf-8', errors='ignore').read())
                    except Exception:
                        continue
                    display = str(data.get('DisplayName') or '')
                    install_location = str(data.get('InstallLocation') or '')
                    if not display or not install_location or not os.path.exists(install_location):
                        continue
                    resolved = steam_api.resolve_candidate_name(display)
                    if resolved:
                        add_game(str(resolved['appid']), resolved['name'], "Epic", **resolved)
                    else:
                        local_id = f"local:{normalize_name(display)}"
                        add_game(local_id, display, "Epic", local_only=True)
            except Exception:
                pass

        # GOG folders
        gog_roots = [
            r"C:\GOG Games",
            r"D:\GOG Games",
            r"E:\GOG Games",
        ]
        for root in gog_roots:
            if not os.path.isdir(root):
                continue
            try:
                for name in os.listdir(root):
                    full = os.path.join(root, name)
                    if not os.path.isdir(full):
                        continue
                    resolved = steam_api.resolve_candidate_name(name)
                    if resolved:
                        add_game(str(resolved['appid']), resolved['name'], "GOG", **resolved)
                    else:
                        local_id = f"local:{normalize_name(name)}"
                        add_game(local_id, name, "GOG", local_only=True)
            except Exception:
                continue

        return catalog

    @classmethod
    def build_library_index(cls) -> dict[str, list[dict[str, Any]]]:
        index: dict[str, list[dict[str, Any]]] = {}

        def add_path(appid: str, path: str, category: str, description: str, risk: str = "safe") -> None:
            if not appid or not appid.isdigit() or not os.path.exists(path):
                return
            entry = {
                "path": path,
                "category": category,
                "description": description,
                "risk": risk,
                "size": path_size(path),
                "is_dir": os.path.isdir(path),
            }
            bucket = index.setdefault(appid, [])
            norm = os.path.normcase(os.path.normpath(path))
            if any(os.path.normcase(os.path.normpath(item["path"])) == norm for item in bucket):
                return
            bucket.append(entry)

        all_bases: list[str] = []
        for env_key in ["APPDATA", "LOCALAPPDATA"]:
            value = os.environ.get(env_key, "")
            if value:
                all_bases.append(value)
        userprofile = os.environ.get("USERPROFILE", "")
        if userprofile:
            all_bases.append(os.path.join(userprofile, "AppData", "LocalLow"))
            all_bases.append(os.path.join(userprofile, "Documents"))
        public_docs = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Documents")
        if public_docs:
            all_bases.append(public_docs)
        localappdata = os.environ.get("LOCALAPPDATA", "")
        if localappdata:
            all_bases.append(os.path.join(localappdata, "Temp"))
        programdata = os.environ.get("PROGRAMDATA", "")
        if programdata:
            all_bases.append(programdata)

        crack_meta = {
            r"Steam\CODEX": ("Crack Leftovers (CODEX)", "CODEX save/config data"),
            r"Steam\RUNE": ("Crack Leftovers (RUNE)", "RUNE emulator data"),
            "OnlineFix": ("Crack Leftovers (OnlineFix)", "OnlineFix data"),
            "EMPRESS": ("Crack Leftovers (EMPRESS)", "EMPRESS data"),
            "GSE Saves": ("Crack Leftovers (GSE)", "Goldberg Steam Emu saves"),
            "SmartSteamEmu": ("Crack Leftovers (SSE)", "SmartSteamEmu data"),
            "Goldberg SteamEmu Saves": ("Crack Leftovers (Goldberg)", "Goldberg emulator saves"),
            "ALI213": ("Crack Leftovers (ALI213)", "ALI213 crack data"),
            "STAR": ("Crack Leftovers (STAR)", "STAR app cache by AppID"),
        }

        for base_path in all_bases:
            if not os.path.isdir(base_path):
                continue
            for emu in cls.CRACK_EMU_NAMES:
                root = os.path.join(base_path, emu)
                if not os.path.isdir(root):
                    continue
                category, description = crack_meta.get(emu, ("Crack Leftovers", "Crack leftover data"))
                try:
                    for entry in os.listdir(root):
                        full = os.path.join(root, entry)
                        if entry.isdigit() and os.path.exists(full):
                            add_path(entry, full, category, description)
                        elif os.path.isdir(full):
                            for sub in os.listdir(full):
                                sub_full = os.path.join(full, sub)
                                if sub.isdigit() and os.path.exists(sub_full):
                                    add_path(sub, sub_full, category, description)
                except Exception:
                    continue

        steam_dir = cls.detect_steam_install_path() or cls.expand_template("{STEAM}")
        steam_scan_dirs = [
            (os.path.join(steam_dir, "steamapps", "shadercache"), "Steam Shader Cache", "Compiled shader cache", "safe"),
            (os.path.join(steam_dir, "steamapps", "workshop", "content"), "Steam Workshop", "Workshop content", "safe"),
            (os.path.join(steam_dir, "steamapps", "compatdata"), "Steam CompatData", "Compatibility / Proton data", "safe"),
            (os.path.join(steam_dir, "userdata"), "Steam Userdata", "Steam cloud saves / configs", "caution"),
        ]

        for scan_dir, category, description, risk in steam_scan_dirs:
            if not os.path.isdir(scan_dir):
                continue
            try:
                if os.path.basename(scan_dir).lower() == "userdata":
                    for steam_user in os.listdir(scan_dir):
                        user_dir = os.path.join(scan_dir, steam_user)
                        if not os.path.isdir(user_dir):
                            continue
                        for appid in os.listdir(user_dir):
                            app_full = os.path.join(user_dir, appid)
                            if appid.isdigit() and os.path.exists(app_full):
                                add_path(appid, app_full, category, description, risk)
                else:
                    for appid in os.listdir(scan_dir):
                        app_full = os.path.join(scan_dir, appid)
                        if appid.isdigit() and os.path.exists(app_full):
                            add_path(appid, app_full, category, description, risk)
            except Exception:
                continue

        # Also scan additional Steam libraries (other drives) for installed-data folders.
        for steamapps in cls.steam_library_paths():
            extra_dirs = [
                (os.path.join(steamapps, "shadercache"), "Steam Shader Cache", "Compiled shader cache", "safe"),
                (os.path.join(steamapps, "workshop", "content"), "Steam Workshop", "Workshop content", "safe"),
                (os.path.join(steamapps, "compatdata"), "Steam CompatData", "Compatibility / Proton data", "safe"),
            ]
            for scan_dir, category, description, risk in extra_dirs:
                if not os.path.isdir(scan_dir):
                    continue
                try:
                    for appid in os.listdir(scan_dir):
                        app_full = os.path.join(scan_dir, appid)
                        if appid.isdigit() and os.path.exists(app_full):
                            add_path(appid, app_full, category, description, risk)
                except Exception:
                    continue

        return index

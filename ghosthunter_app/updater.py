from __future__ import annotations

import json
import os
import subprocess
import tempfile
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from .config import (
    APP_CREATOR,
    APP_EXE_NAME,
    APP_NAME,
    APP_VERSION,
    DOWNLOADS_DIR,
    GITHUB_REPO_URL,
    INSTALLER_BASENAME,
    PORTABLE_BASENAME,
    UPDATE_CHECK_URL,
)


def _version_tuple(value: str) -> tuple[int, ...]:
    cleaned = str(value).strip().lower().lstrip("v")
    parts = []
    for piece in cleaned.replace("-", ".").split("."):
        if piece.isdigit():
            parts.append(int(piece))
        else:
            digits = "".join(ch for ch in piece if ch.isdigit())
            if digits:
                parts.append(int(digits))
    return tuple(parts or [0])


def is_newer_version(latest: str, current: str) -> bool:
    return _version_tuple(latest) > _version_tuple(current)


class UpdateManager:
    def __init__(self) -> None:
        self.current_version = APP_VERSION
        self.repo_url = GITHUB_REPO_URL
        self.check_url = UPDATE_CHECK_URL
        self.downloads_dir = DOWNLOADS_DIR

    def is_configured(self) -> bool:
        return bool(self.repo_url and self.check_url)

    def get_settings_payload(self) -> dict[str, Any]:
        return {
            "app_name": APP_NAME,
            "creator": APP_CREATOR,
            "current_version": self.current_version,
            "repo_url": self.repo_url,
            "check_url": self.check_url,
            "configured": self.is_configured(),
            "installer_name_example": f"{INSTALLER_BASENAME}-{self.current_version}.exe",
            "portable_name_example": f"{PORTABLE_BASENAME}-{self.current_version}.zip",
            "exe_name": APP_EXE_NAME,
            "downloads_dir": str(self.downloads_dir),
        }

    def check_for_updates(self) -> dict[str, Any]:
        if not self.is_configured():
            return {
                "ok": False,
                "configured": False,
                "error": "Updater is not configured yet. Add your GitHub owner/repo in ghosthunter_app/config.py.",
            }
        try:
            request = urllib.request.Request(
                self.check_url,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "GhostHunterPro"},
            )
            with urllib.request.urlopen(request, timeout=12) as response:
                release = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            return {"ok": False, "configured": True, "error": f"Update check failed: {exc}"}

        latest_tag = str(release.get("tag_name") or "").strip()
        body = str(release.get("body") or "")
        assets = release.get("assets") or []

        installer_name = f"{INSTALLER_BASENAME}-{latest_tag}.exe" if latest_tag else ""
        portable_name = f"{PORTABLE_BASENAME}-{latest_tag}.zip" if latest_tag else ""

        installer_url = ""
        portable_url = ""
        for asset in assets:
            name = str(asset.get("name") or "")
            url = str(asset.get("browser_download_url") or "")
            if name == installer_name:
                installer_url = url
            elif name == portable_name:
                portable_url = url

        return {
            "ok": True,
            "configured": True,
            "current_version": self.current_version,
            "latest_version": latest_tag,
            "update_available": bool(latest_tag and is_newer_version(latest_tag, self.current_version)),
            "installer_url": installer_url,
            "portable_url": portable_url,
            "release_notes": body,
            "release_page": self.repo_url + "/releases/latest" if self.repo_url else "",
        }

    def download_asset(self, url: str, target_name: str | None = None, *, to_temp: bool = False) -> dict[str, Any]:
        if not url:
            return {"ok": False, "error": "No download URL available."}
        try:
            download_dir = Path(tempfile.mkdtemp(prefix="ghosthunter_update_")) if to_temp else self.downloads_dir
            download_dir.mkdir(parents=True, exist_ok=True)
            file_name = target_name or Path(url).name or "update.bin"
            target_path = download_dir / file_name
            request = urllib.request.Request(url, headers={"User-Agent": "GhostHunterPro"})
            with urllib.request.urlopen(request, timeout=60) as response:
                target_path.write_bytes(response.read())
            return {"ok": True, "path": str(target_path), "folder": str(download_dir)}
        except Exception as exc:
            return {"ok": False, "error": f"Download failed: {exc}"}

    def open_releases_page(self) -> dict[str, Any]:
        if not self.repo_url:
            return {"ok": False, "error": "GitHub repo URL is not configured yet."}
        try:
            webbrowser.open_new_tab(self.repo_url + "/releases")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def download_installer_update(self, url: str) -> dict[str, Any]:
        # Installer updates are temporary hand-off files. Keep them out of the
        # user's Downloads folder so a normal update does not leave behind a
        # GhostHunterPro folder/setup EXE.
        result = self.download_asset(url, to_temp=True)
        if not result.get("ok"):
            return result
        path = str(result["path"])
        return {"ok": True, "path": path, "folder": result.get("folder", ""), "temporary": True}

    def _schedule_temp_cleanup(self, target: Path) -> None:
        """Best-effort cleanup for the temporary installer folder.

        The installer may keep the EXE locked briefly while UAC/NSIS starts, so
        cleanup runs in a detached helper process with retries. If the installer
        is still using the file, the helper waits and tries again.
        """
        folder = target.parent
        try:
            if os.name == "nt":
                folder_arg = str(folder)
                script = (
                    "$p = " + json.dumps(folder_arg) + "; "
                    "for ($i = 0; $i -lt 40; $i++) { "
                    "Start-Sleep -Seconds 15; "
                    "try { if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop }; break } catch {} "
                    "}"
                )
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                subprocess.Popen(
                    ["/bin/sh", "-c", f"sleep 120; rm -rf -- {json.dumps(str(folder))}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass

    def launch_installer(self, path: str) -> dict[str, Any]:
        try:
            target = Path(path)
            if not target.exists():
                return {"ok": False, "error": "Installer file not found."}
            if os.name == "nt":
                os.startfile(str(target))  # type: ignore[attr-defined]
            else:
                subprocess.Popen([str(target)])
            if target.parent.name.startswith("ghosthunter_update_"):
                self._schedule_temp_cleanup(target)
            return {"ok": True, "cleanup_scheduled": target.parent.name.startswith("ghosthunter_update_")}
        except Exception as exc:
            return {"ok": False, "error": f"Could not launch installer: {exc}"}

    def download_portable_package(self, url: str) -> dict[str, Any]:
        result = self.download_asset(url)
        if not result.get("ok"):
            return result
        return {"ok": True, "path": result["path"], "folder": result.get("folder", "")}

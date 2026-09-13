from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from helpers import AppDefinition, LCUError, normalize_name, runtime_root

CACHE_VERSION = 1
CACHE_MAX_AGE_SECONDS = 86_400


@dataclass(frozen=True)
class IndexedApp:
    name: str
    normalized: str
    source: str
    target: str
    process: str | None = None

    @classmethod
    def from_json(cls, value: Any) -> IndexedApp:
        if not isinstance(value, dict):
            raise ValueError("App cache entry must be an object")
        name = value.get("name")
        normalized = value.get("normalized")
        source = value.get("source")
        target = value.get("target")
        process = value.get("process")
        if not all(
            isinstance(item, str) and item
            for item in (name, normalized, source, target)
        ):
            raise ValueError("App cache entry is missing a required string")
        if source not in {"start-menu", "app-paths"}:
            raise ValueError("App cache source is invalid")
        if process is not None and not isinstance(process, str):
            raise ValueError("App cache process must be a string or null")
        return cls(name, normalized, source, target, process)

    def public_result(self) -> dict[str, str | None]:
        return {"name": self.name, "source": self.source, "process": self.process}

    def as_definition(self) -> AppDefinition:
        return AppDefinition(
            name=self.name,
            aliases=(self.name,),
            commands=(self.target,),
            source=self.source,
        )


class AppIndex:
    def __init__(self, apps: list[IndexedApp], refreshed: bool = False) -> None:
        self.apps = tuple(apps)
        self.refreshed = refreshed

    @classmethod
    def load(
        cls,
        refresh: bool = False,
        *,
        cache_path: Path | None = None,
        start_menu_roots: list[Path] | None = None,
        app_path_entries: list[IndexedApp] | None = None,
        now: float | None = None,
    ) -> AppIndex:
        cache_path = cache_path or runtime_root() / "cache" / "apps.json"
        now = time.time() if now is None else now
        if not refresh:
            cached = cls._read_fresh_cache(cache_path, now)
            if cached is not None:
                return cls(cached, refreshed=False)

        apps = cls.discover(start_menu_roots, app_path_entries)
        try:
            cls._write_cache(cache_path, apps, now)
        except OSError:
            # Discovery is still useful if a locked or read-only cache cannot
            # be updated. The next command can retry the bounded rebuild.
            pass
        return cls(apps, refreshed=True)

    @staticmethod
    def default_start_menu_roots() -> list[Path]:
        roots: list[Path] = []
        for variable in ("APPDATA", "PROGRAMDATA"):
            base = os.environ.get(variable)
            if base:
                roots.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
        return roots

    @classmethod
    def discover(
        cls,
        start_menu_roots: list[Path] | None = None,
        app_path_entries: list[IndexedApp] | None = None,
    ) -> list[IndexedApp]:
        roots = cls.default_start_menu_roots() if start_menu_roots is None else start_menu_roots
        apps = cls._discover_start_menu(roots)
        apps.extend(
            cls._read_windows_app_paths()
            if app_path_entries is None
            else app_path_entries
        )
        return cls._deduplicate(apps)

    @staticmethod
    def _discover_start_menu(roots: list[Path]) -> list[IndexedApp]:
        shortcut_shell: Any | None = None
        if os.name == "nt":
            try:
                import win32com.client

                shortcut_shell = win32com.client.Dispatch("WScript.Shell")
            except (ImportError, OSError):
                shortcut_shell = None

        apps: list[IndexedApp] = []
        for root in roots:
            if not root.is_dir():
                continue
            for shortcut in root.rglob("*.lnk"):
                name = shortcut.stem.strip()
                if not name:
                    continue
                process: str | None = None
                if shortcut_shell is not None:
                    try:
                        target_path = shortcut_shell.CreateShortcut(
                            str(shortcut)
                        ).TargetPath
                        if target_path:
                            process = Path(target_path).name.casefold()
                    except Exception:
                        process = None
                apps.append(
                    IndexedApp(
                        name=name,
                        normalized=normalize_name(name),
                        source="start-menu",
                        target=str(shortcut.resolve(strict=False)),
                        process=process,
                    )
                )
        return apps

    @staticmethod
    def _read_windows_app_paths() -> list[IndexedApp]:
        if os.name != "nt":
            return []
        try:
            import winreg
        except ImportError:
            return []

        base_key = r"Software\Microsoft\Windows\CurrentVersion\App Paths"
        apps: list[IndexedApp] = []
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                root = winreg.OpenKey(hive, base_key)
            except OSError:
                continue
            with root:
                try:
                    count = winreg.QueryInfoKey(root)[0]
                except OSError:
                    continue
                for index in range(count):
                    try:
                        subkey_name = winreg.EnumKey(root, index)
                        with winreg.OpenKey(root, subkey_name) as subkey:
                            target, _ = winreg.QueryValueEx(subkey, None)
                    except OSError:
                        continue
                    if not isinstance(target, str) or not target.strip():
                        continue
                    target = target.strip().strip('"')
                    process = Path(subkey_name).name.casefold()
                    name = Path(subkey_name).stem
                    apps.append(
                        IndexedApp(
                            name=name,
                            normalized=normalize_name(name),
                            source="app-paths",
                            target=target,
                            process=process,
                        )
                    )
        return apps

    @staticmethod
    def _deduplicate(apps: list[IndexedApp]) -> list[IndexedApp]:
        result: list[IndexedApp] = []
        seen: set[tuple[str, str]] = set()
        for app in sorted(
            apps,
            key=lambda item: (
                item.normalized,
                item.process or "",
                0 if item.source == "app-paths" else 1,
                os.path.normcase(item.target),
            ),
        ):
            process = normalize_name(app.process or "")
            identity = (
                app.normalized,
                process or os.path.normcase(app.target),
            )
            if identity not in seen:
                seen.add(identity)
                result.append(app)
        return result

    @staticmethod
    def _read_fresh_cache(cache_path: Path, now: float) -> list[IndexedApp] | None:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            generated_at = datetime.fromisoformat(payload["generatedAt"])
            generated_epoch = generated_at.timestamp()
            if payload.get("version") != CACHE_VERSION:
                return None
            if now - generated_epoch > CACHE_MAX_AGE_SECONDS:
                return None
            raw_apps = payload.get("apps")
            if not isinstance(raw_apps, list):
                return None
            return [IndexedApp.from_json(item) for item in raw_apps]
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _write_cache(cache_path: Path, apps: list[IndexedApp], now: float) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": CACHE_VERSION,
            "generatedAt": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "apps": [asdict(app) for app in apps],
        }
        temporary = cache_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(cache_path)

    def resolve(self, query: str) -> AppDefinition:
        needle = normalize_name(query)
        if not needle:
            raise LCUError("invalid_app_query", "App query cannot be empty")

        exact = [app for app in self.apps if app.normalized == needle]
        candidates = exact or [
            app
            for app in self.apps
            if needle in app.normalized
            or needle in normalize_name(app.process or "")
        ]
        if not candidates:
            raise LCUError("app_not_found", f"No indexed app matched: {query}")
        if len(candidates) > 1:
            raise LCUError(
                "ambiguous_app",
                "Multiple installed apps matched; use a more specific name",
                candidates=[app.public_result() for app in candidates],
            )
        return candidates[0].as_definition()

    def public_apps(self) -> list[dict[str, str | None]]:
        return [app.public_result() for app in self.apps]

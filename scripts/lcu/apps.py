from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import LCUError

CACHE_MAX_AGE_SECONDS = 86_400  # 24 hours


def normalize_app_name(name: str) -> str:
    # Lowercase and remove all whitespace and common punctuation
    return re.sub(r"[\s\-_.:/\\\(\)\[\]]", "", name.lower())


@dataclass
class AppEntry:
    name: str
    target: str
    source: str  # "config", "start-menu", "app-paths"
    aliases: list[str]
    normalized: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AppEntry:
        return cls(
            name=d["name"],
            target=d["target"],
            source=d["source"],
            aliases=d.get("aliases", []),
            normalized=d.get("normalized", normalize_app_name(d["name"])),
        )


def get_cache_file_path() -> Path:
    temp_dir = Path(tempfile.gettempdir()) / "LiteComputerUse"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / "app-index.json"


def load_config_apps(config_path: Path | None = None) -> list[AppEntry]:
    if config_path is None:
        # Check standard config locations
        candidates = [
            Path(__file__).resolve().parent.parent.parent / "config" / "apps.yaml",
            Path.cwd() / "config" / "apps.yaml",
        ]
        for c in candidates:
            if c.is_file():
                config_path = c
                break

    if config_path is None or not config_path.is_file():
        return []

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        return []

    entries: list[AppEntry] = []
    if isinstance(data, dict) and "apps" in data and isinstance(data["apps"], dict):
        for app_id, app_info in data["apps"].items():
            if not isinstance(app_info, dict):
                continue
            aliases = app_info.get("aliases", [])
            commands = app_info.get("commands", [])
            if not commands:
                continue
            target = commands[0]
            name = str(app_id)
            all_aliases = [name] + [str(a) for a in aliases]
            entries.append(
                AppEntry(
                    name=name,
                    target=str(target),
                    source="config",
                    aliases=all_aliases,
                    normalized=normalize_app_name(name),
                )
            )
    return entries


def discover_start_menu_apps() -> list[AppEntry]:
    entries: list[AppEntry] = []
    roots: list[Path] = []
    for var in ("APPDATA", "PROGRAMDATA"):
        val = os.environ.get(var)
        if val:
            p = Path(val) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            if p.is_dir():
                roots.append(p)

    for root in roots:
        try:
            for lnk in root.rglob("*.lnk"):
                stem = lnk.stem.strip()
                if not stem:
                    continue
                entries.append(
                    AppEntry(
                        name=stem,
                        target=str(lnk.resolve()),
                        source="start-menu",
                        aliases=[stem],
                        normalized=normalize_app_name(stem),
                    )
                )
        except Exception:
            continue
    return entries


def discover_app_paths_apps() -> list[AppEntry]:
    if os.name != "nt":
        return []

    entries: list[AppEntry] = []
    try:
        import winreg
    except ImportError:
        return []

    base_key = r"Software\Microsoft\Windows\CurrentVersion\App Paths"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            root = winreg.OpenKey(hive, base_key, 0, winreg.KEY_READ)
        except OSError:
            continue
        with root:
            try:
                count = winreg.QueryInfoKey(root)[0]
            except OSError:
                continue
            for i in range(count):
                try:
                    subkey_name = winreg.EnumKey(root, i)
                    with winreg.OpenKey(root, subkey_name) as subkey:
                        target, _ = winreg.QueryValueEx(subkey, None)
                except OSError:
                    continue
                if not isinstance(target, str) or not target.strip():
                    continue
                target_clean = target.strip().strip('"')
                name = Path(subkey_name).stem
                entries.append(
                    AppEntry(
                        name=name,
                        target=target_clean,
                        source="app-paths",
                        aliases=[name, subkey_name],
                        normalized=normalize_app_name(name),
                    )
                )
    return entries


def build_app_index(config_path: Path | None = None, force_refresh: bool = False) -> list[AppEntry]:
    cache_path = get_cache_file_path()
    now = time.time()

    if not force_refresh and cache_path.is_file():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
            cached_time = cached_data.get("timestamp", 0)
            if now - cached_time < CACHE_MAX_AGE_SECONDS:
                items = cached_data.get("apps", [])
                return [AppEntry.from_dict(item) for item in items]
        except Exception:
            pass

    # Rebuild index
    config_apps = load_config_apps(config_path)
    start_menu_apps = discover_start_menu_apps()
    app_paths_apps = discover_app_paths_apps()

    combined: dict[str, AppEntry] = {}
    # Priority: config > start-menu > app-paths
    for app in app_paths_apps:
        combined[app.normalized] = app
    for app in start_menu_apps:
        combined[app.normalized] = app
    for app in config_apps:
        combined[app.normalized] = app

    result = list(combined.values())
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "timestamp": now,
                    "apps": [app.to_dict() for app in result],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
    except Exception:
        pass

    return result


def find_app_entry(query: str, index: list[AppEntry]) -> tuple[AppEntry | None, list[str]]:
    q_clean = query.strip()
    q_norm = normalize_app_name(q_clean)
    if not q_norm:
        return None, []

    # 1. Exact alias or name match
    exact_matches: list[AppEntry] = []
    for entry in index:
        for alias in entry.aliases:
            if alias.lower() == q_clean.lower() or normalize_app_name(alias) == q_norm:
                exact_matches.append(entry)
                break

    if len(exact_matches) == 1:
        return exact_matches[0], []
    if len(exact_matches) > 1:
        # Deduplicate targets
        unique_targets = {e.target: e for e in exact_matches}
        if len(unique_targets) == 1:
            return list(unique_targets.values())[0], []
        return None, [e.name for e in exact_matches]

    # 2. Normalized prefix/substring match
    partial_matches: list[AppEntry] = []
    for entry in index:
        # Match against normalized aliases
        matched = False
        for alias in entry.aliases:
            a_norm = normalize_app_name(alias)
            if q_norm == a_norm or (len(q_norm) >= 2 and (q_norm in a_norm or a_norm in q_norm)):
                partial_matches.append(entry)
                matched = True
                break
        if not matched and (q_norm in entry.normalized or entry.normalized in q_norm):
            partial_matches.append(entry)

    unique_partial = {e.target: e for e in partial_matches}
    if len(unique_partial) == 1:
        return list(unique_partial.values())[0], []
    if len(unique_partial) > 1:
        return None, [e.name for e in unique_partial.values()]

    return None, []


def open_app(name: str, config_path: Path | None = None) -> dict[str, Any]:
    if not name or not name.strip():
        raise LCUError("invalid_arguments", "Application name cannot be empty")

    index = build_app_index(config_path)
    entry, candidates = find_app_entry(name.strip(), index)

    if candidates:
        raise LCUError(
            "ambiguous_target",
            f"Multiple applications matched '{name}'",
            candidates=candidates[:10],
        )

    if entry is None:
        raise LCUError("not_found", f"No application found matching '{name}'")

    target = entry.target
    try:
        if os.name == "nt":
            os.startfile(target)
        else:
            subprocess.Popen(target, shell=True)
    except Exception as exc:
        raise LCUError("dispatch_failed", f"Failed to launch application '{name}' ({target}): {exc}") from exc

    return {"app": entry.name, "target": target}

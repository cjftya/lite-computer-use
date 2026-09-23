from __future__ import annotations

import json
import ntpath
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import LCUError
from .app_observer import observe_window
from .app_resolver import LaunchSpec, atomic_write_json, cache_fingerprint, inspect_shortcut, resolve_config_path
from .launch_context import get_gui_env_normalization, get_launch_context_snapshot
from .ownership import remember_owned_processes
from .processes import (
    ProcessIdentity,
    snapshot_is_complete,
    snapshot_processes,
)
from .state import load_app_attempt, save_app_attempt
from .win_launch import dispatch as dispatch_launch_spec

CACHE_MAX_AGE_SECONDS = 86_400  # 24 hours
APP_INDEX_CACHE_VERSION = 7
APP_WINDOW_READY_INTERVAL = 0.2
APP_WINDOW_TIMEOUT = 10.0
_APP_INDEX_DIAGNOSTICS: dict[str, Any] = {}

CANDIDATE_PRIORITY: dict[str, int] = {
    "appsfolder": 1,
    "start-menu": 2,
    "uri": 3,
    "app-paths": 4,
    "exe": 5,
}


@dataclass
class LaunchCandidate:
    target: str
    method: str  # "appsfolder", "start-menu", "uri", "app-paths", "exe"
    source: str  # "config", "start-menu", "app-paths"
    args: tuple[str, ...] = ()
    cwd: str | None = None
    expected_identity: dict[str, Any] = field(default_factory=dict)
    priority: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "target": self.target,
            "method": self.method,
            "source": self.source,
        }
        if self.args:
            d["args"] = list(self.args)
        if self.cwd:
            d["cwd"] = self.cwd
        if self.expected_identity:
            d["expected_identity"] = self.expected_identity
        if self.priority is not None:
            d["priority"] = self.priority
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LaunchCandidate:
        raw_args = d.get("args", ())
        args = tuple(str(a) for a in raw_args) if isinstance(raw_args, (list, tuple)) else ()
        p = d.get("priority")
        priority = int(p) if p is not None else None
        return cls(
            target=str(d.get("target", "")),
            method=str(d.get("method", "exe")),
            source=str(d.get("source", "")),
            args=args,
            cwd=str(d["cwd"]) if d.get("cwd") else None,
            expected_identity=dict(d.get("expected_identity", {})),
            priority=priority,
        )


def candidate_priority_key(candidate: LaunchCandidate) -> int:
    if candidate.priority is not None:
        return candidate.priority
    return CANDIDATE_PRIORITY.get(candidate.method, 99)


def _candidate_kind(candidate: LaunchCandidate) -> str:
    return {
        "appsfolder": "packaged",
        "start-menu": "shortcut",
        "uri": "uri",
        "app-paths": "exe",
        "exe": "cmd-wrapper" if candidate.target.lower().endswith((".cmd", ".bat")) else "exe",
    }.get(candidate.method, candidate.method)


def _candidate_to_launch_spec(candidate: LaunchCandidate, app_id: str = "") -> LaunchSpec:
    return LaunchSpec(
        app_id=app_id,
        kind=_candidate_kind(candidate),
        target=candidate.target,
        argv=candidate.args,
        cwd=candidate.cwd,
        source=candidate.source,
        expected_identity=candidate.expected_identity,
        priority=candidate.priority,
    )


def candidate_launch_family(candidate: LaunchCandidate) -> tuple[Any, ...]:
    """Return the exact launch-spec key (kept under the old public name)."""
    return _candidate_to_launch_spec(candidate).identity_key()


def classify_launch_method(target: str, source: str = "") -> str:
    t_trim = target.strip()
    t_lower = t_trim.lower()

    if t_lower.startswith("shell:appsfolder\\"):
        return "appsfolder"
    if t_lower.endswith(".lnk"):
        return "start-menu"

    # URI check: scheme followed by colon, not a Windows drive letter path like C:\
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:(?!\\)", t_trim) and not (
        len(t_trim) > 1 and t_trim[1] == ":"
    ):
        return "uri"

    if source == "app-paths":
        return "app-paths"
    if t_lower.endswith(".exe") or t_lower.endswith(".cmd") or t_lower.endswith(".bat"):
        return "app-paths" if source == "app-paths" else "exe"

    return "exe"


def normalize_app_name(name: str) -> str:
    # Lowercase and remove all whitespace and common punctuation
    return re.sub(r"[\s\-_.:/\\\(\)\[\]]", "", name.lower())


def entry_match_keys(entry: AppEntry) -> set[str]:
    keys = set()
    norm_name = normalize_app_name(entry.name)
    if norm_name:
        keys.add(norm_name)
    for a in entry.aliases:
        norm_a = normalize_app_name(a)
        if norm_a:
            keys.add(norm_a)
    return keys


@dataclass
class AppEntry:
    name: str
    target: str
    source: str  # "config", "start-menu", "app-paths"
    aliases: list[str]
    normalized: str
    commands: list[str] = field(default_factory=list)
    candidates: list[LaunchCandidate] = field(default_factory=list)
    process_cleanup: dict[str, Any] = field(default_factory=dict)
    window_match: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.commands:
            self.commands = [self.target]
        if not self.candidates:
            self.candidates = [
                LaunchCandidate(
                    target=cmd,
                    method=classify_launch_method(cmd, self.source),
                    source=self.source,
                )
                for cmd in self.commands
            ]
        self.sort_and_deduplicate_candidates()

    def sort_and_deduplicate_candidates(self) -> None:
        seen_keys: set[tuple[Any, ...]] = set()
        unique_candidates: list[LaunchCandidate] = []

        sorted_cands = sorted(self.candidates, key=candidate_priority_key)
        for cand in sorted_cands:
            norm_key = candidate_launch_family(cand)
            if norm_key not in seen_keys:
                seen_keys.add(norm_key)
                unique_candidates.append(cand)

        self.candidates = unique_candidates
        if unique_candidates:
            self.commands = [c.target for c in unique_candidates]
            self.target = unique_candidates[0].target

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "target": self.target,
            "source": self.source,
            "aliases": self.aliases,
            "normalized": self.normalized,
            "commands": self.commands,
            "candidates": [c.to_dict() for c in self.candidates],
        }
        if self.process_cleanup:
            d["process_cleanup"] = self.process_cleanup
        if self.window_match:
            d["window_match"] = self.window_match
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AppEntry:
        raw_candidates = d.get("candidates", [])
        if raw_candidates:
            candidates = [LaunchCandidate.from_dict(c) for c in raw_candidates]
        else:
            commands = d.get("commands", [d["target"]])
            source = d.get("source", "")
            candidates = [
                LaunchCandidate(
                    target=c,
                    method=classify_launch_method(c, source),
                    source=source,
                )
                for c in commands
            ]
        return cls(
            name=d["name"],
            target=d["target"],
            source=d["source"],
            aliases=d.get("aliases", []),
            normalized=d.get("normalized", normalize_app_name(d["name"])),
            commands=d.get("commands", [d["target"]]),
            candidates=candidates,
            process_cleanup=d.get("process_cleanup", {}),
            window_match=d.get("window_match", {}),
        )


def merge_app_entries(primary: AppEntry, secondary: AppEntry) -> AppEntry:
    # Primary provides the canonical name, normalized, and primary source
    merged_aliases = list(dict.fromkeys(primary.aliases + secondary.aliases))
    merged_candidates = list(primary.candidates) + list(secondary.candidates)
    proc_cleanup = primary.process_cleanup or secondary.process_cleanup
    window_match = primary.window_match or secondary.window_match
    return AppEntry(
        name=primary.name,
        target=primary.target,
        source=primary.source,
        aliases=merged_aliases,
        normalized=primary.normalized,
        candidates=merged_candidates,
        process_cleanup=proc_cleanup,
        window_match=window_match,
    )


def resolve_executable(target: str) -> str:
    target_clean = target.strip().strip('"')
    p = Path(target_clean)
    if p.is_file():
        return str(p.resolve())

    which_path = shutil.which(target_clean)
    if which_path:
        return which_path

    if os.name == "nt":
        try:
            import winreg

            views = [0]
            for flag_name in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
                flag = getattr(winreg, flag_name, 0)
                if flag not in views:
                    views.append(flag)
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for view in views:
                    try:
                        key_path = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{target_clean}"
                        with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view) as key:
                            val, _ = winreg.QueryValueEx(key, None)
                            if val and isinstance(val, str) and Path(val.strip().strip('"')).is_file():
                                return str(Path(val.strip().strip('"')).resolve())
                    except OSError:
                        continue
        except Exception:
            pass

    return target_clean


def dispatch_candidate(candidate: LaunchCandidate) -> dict[str, Any]:
    kind = _candidate_kind(candidate)
    resolved = candidate.target if kind in {"packaged", "shortcut", "uri"} else resolve_executable(candidate.target)
    spec = _candidate_to_launch_spec(candidate)
    receipt = dispatch_launch_spec(spec, resolved=resolved)
    result = receipt.to_dict()
    result["launch_type"] = receipt.backend
    return result


def _can_merge_discovered_entry(existing: AppEntry, discovered: AppEntry) -> bool:
    """Merge one resolver source into config, never two same-name installations."""
    if existing.source != "config":
        return False
    return not any(candidate.source == discovered.source for candidate in existing.candidates)


def window_match_status(win: dict[str, Any], entry: AppEntry) -> str:
    """Return match, no_match, or insufficient_evidence without trusting titles alone."""
    title = win.get("title", "").strip().lower()
    proc = win.get("process", "").strip().lower()
    image = str(win.get("image_path") or "").strip()
    if not win.get("hwnd") or not win.get("pid"):
        return "insufficient_evidence"

    expected_paths: set[str] = set()
    known_exes: set[str] = set()
    for cand in entry.candidates:
        for path in (cand.target, cand.expected_identity.get("target_path", "")):
            path = str(path).strip().strip('"')
            if not path.lower().endswith(".exe"):
                continue
            known_exes.add(ntpath.basename(path).casefold())
            if ntpath.isabs(path):
                expected_paths.add(ntpath.normcase(ntpath.normpath(path)))
            elif os.name == "nt":
                resolved = resolve_executable(path)
                if ntpath.isabs(resolved):
                    expected_paths.add(ntpath.normcase(ntpath.normpath(resolved)))
    configured_match = entry.window_match
    process_names = {str(p).casefold() for p in configured_match.get("process_names", [])}
    known_exes.update(process_names)
    package_ids = {
        c.target.split("\\", 1)[1].casefold()
        for c in entry.candidates
        if c.target.lower().startswith("shell:appsfolder\\")
    }
    observed_id = str(win.get("app_user_model_id") or "").casefold()
    package_verified = bool(package_ids and observed_id in package_ids)
    if observed_id and package_ids and not package_verified:
        return "no_match"
    if not known_exes:
        known_exes.update({f"{entry.normalized}.exe", f"{entry.name.lower()}.exe"})
    packaged_runtime = any(c.method in {"appsfolder", "uri"} for c in entry.candidates)
    if image and expected_paths and not package_verified:
        if ntpath.normcase(ntpath.normpath(image)) not in expected_paths:
            return "no_match"
    elif expected_paths and not package_verified:
        return "insufficient_evidence"
    if image and ntpath.basename(image).casefold() not in known_exes and not package_verified:
        return "no_match"
    if proc and proc not in known_exes and not package_verified:
        return "no_match"
    if not image or win.get("session_id") is None:
        return "insufficient_evidence"
    if os.name == "nt":
        from .processes import get_current_session_id
        current_session = get_current_session_id()
        if current_session is None:
            return "insufficient_evidence"
        if win["session_id"] != current_session:
            return "no_match"
    if packaged_runtime and expected_paths and not package_verified and proc in process_names:
        return "insufficient_evidence"

    # A browser's process and tab title do not prove it is a normal window
    # rather than an installed web app running under the same executable.
    if entry.normalized in {"chrome", "edge", "firefox"}:
        return "insufficient_evidence"
    if configured_match:
        contains = [str(v).lower() for v in configured_match.get("title_contains_any", [])]
        equals = [str(v).lower() for v in configured_match.get("title_equals_any", [])]
        if contains and not any(v in title for v in contains):
            return "no_match"
        if equals and title not in equals:
            return "no_match"
    return "match" if (proc or image) else "insufficient_evidence"


def is_matching_window(win: dict[str, Any], entry: AppEntry) -> bool:
    return window_match_status(win, entry) == "match"


def find_matching_windows(
    entry: AppEntry, windows_list: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    if windows_list is None:
        from .windows import list_windows
        windows_list = list_windows()

    return [w for w in windows_list if is_matching_window(w, entry)]


def get_cache_file_path() -> Path:
    temp_dir = Path(tempfile.gettempdir()) / "LiteComputerUse"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / "app-index.json"


def get_app_index_diagnostics(config_path: Path | None = None) -> dict[str, Any]:
    fingerprint = cache_fingerprint(config_path)
    cache_path = get_cache_file_path()
    cache_hit = _APP_INDEX_DIAGNOSTICS.get("cache_hit")
    if cache_hit is None:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cache_hit = bool(
                cached.get("version") == APP_INDEX_CACHE_VERSION
                and cached.get("fingerprint") == fingerprint
                and time.time() - float(cached.get("timestamp", 0)) < CACHE_MAX_AGE_SECONDS
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            cache_hit = False
    return {
        "config": fingerprint,
        "cache_path": str(cache_path),
        "cache_version": APP_INDEX_CACHE_VERSION,
        "cache_hit": cache_hit,
    }


def load_config_apps(config_path: Path | None = None) -> list[AppEntry]:
    config_path = resolve_config_path(config_path)

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
            raw_cmds = app_info.get("commands", [])
            if not raw_cmds:
                continue
            proc_cleanup = app_info.get("process_cleanup", {})
            window_match = app_info.get("window_match", {})

            candidates: list[LaunchCandidate] = []
            command_strings: list[str] = []
            for item in raw_cmds:
                if isinstance(item, dict):
                    cand_target = str(item.get("target", "")).strip()
                    raw_args = item.get("args", [])
                    cand_args = tuple(str(a) for a in raw_args) if isinstance(raw_args, (list, tuple)) else ()
                    cand_cwd = str(item["cwd"]) if item.get("cwd") else None
                    p = item.get("priority")
                    cand_priority = int(p) if p is not None else None
                    method = classify_launch_method(cand_target, "config")
                    candidates.append(
                        LaunchCandidate(
                            target=cand_target,
                            method=method,
                            source="config",
                            args=cand_args,
                            cwd=cand_cwd,
                            priority=cand_priority,
                        )
                    )
                    command_strings.append(cand_target)
                elif isinstance(item, str):
                    cand_target = item.strip()
                    method = classify_launch_method(cand_target, "config")
                    candidates.append(
                        LaunchCandidate(
                            target=cand_target,
                            method=method,
                            source="config",
                        )
                    )
                    command_strings.append(cand_target)

            if not command_strings:
                continue
            target = command_strings[0]
            name = str(app_id)
            all_aliases = [name] + [str(a) for a in aliases]
            entries.append(
                AppEntry(
                    name=name,
                    target=str(target),
                    source="config",
                    aliases=all_aliases,
                    normalized=normalize_app_name(name),
                    commands=command_strings,
                    candidates=candidates,
                    process_cleanup=proc_cleanup,
                    window_match=window_match,
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
                metadata = inspect_shortcut(lnk)
                entries.append(
                    AppEntry(
                        name=stem,
                        target=str(lnk.resolve()),
                        source="start-menu",
                        aliases=[stem],
                        normalized=normalize_app_name(stem),
                        candidates=[
                            LaunchCandidate(
                                target=str(lnk.resolve()), method="start-menu", source="start-menu",
                                cwd=metadata.get("working_directory"), expected_identity=metadata,
                            )
                        ],
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
    views = [0]
    for flag_name in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
        flag = getattr(winreg, flag_name, 0)
        if flag not in views:
            views.append(flag)
    seen_targets: set[tuple[str, str]] = set()
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in views:
            try:
                root = winreg.OpenKey(hive, base_key, 0, winreg.KEY_READ | view)
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
                    key = (name.casefold(), os.path.normcase(os.path.normpath(target_clean)))
                    if key in seen_targets:
                        continue
                    seen_targets.add(key)
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
    global _APP_INDEX_DIAGNOSTICS
    cache_path = get_cache_file_path()
    now = time.time()
    fingerprint = cache_fingerprint(config_path)

    if not force_refresh and cache_path.is_file():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
            cached_version = cached_data.get("version")
            cached_time = cached_data.get("timestamp", 0)
            if (
                cached_version == APP_INDEX_CACHE_VERSION
                and cached_data.get("fingerprint") == fingerprint
                and (now - cached_time < CACHE_MAX_AGE_SECONDS)
            ):
                items = cached_data.get("apps", [])
                _APP_INDEX_DIAGNOSTICS = {"cache_hit": True, "fingerprint": fingerprint}
                return [AppEntry.from_dict(item) for item in items]
        except Exception:
            pass

    # Rebuild index
    config_apps = load_config_apps(config_path)
    start_menu_apps = discover_start_menu_apps()
    app_paths_apps = discover_app_paths_apps()

    indexed_entries: list[AppEntry] = []

    # Priority for metadata & candidates: config > start-menu > app-paths
    # 1. Config apps: canonical source
    for app in config_apps:
        indexed_entries.append(app)

    # 2. Start menu apps: alias-aware merge with existing entries
    for app in start_menu_apps:
        app_keys = entry_match_keys(app)
        matched_idx = None
        for i, existing in enumerate(indexed_entries):
            if entry_match_keys(existing) & app_keys and _can_merge_discovered_entry(existing, app):
                matched_idx = i
                break
        if matched_idx is not None:
            indexed_entries[matched_idx] = merge_app_entries(
                primary=indexed_entries[matched_idx], secondary=app
            )
        else:
            indexed_entries.append(app)

    # 3. App paths apps: alias-aware merge with existing entries
    for app in app_paths_apps:
        app_keys = entry_match_keys(app)
        matched_idx = None
        for i, existing in enumerate(indexed_entries):
            if entry_match_keys(existing) & app_keys and _can_merge_discovered_entry(existing, app):
                matched_idx = i
                break
        if matched_idx is not None:
            indexed_entries[matched_idx] = merge_app_entries(
                primary=indexed_entries[matched_idx], secondary=app
            )
        else:
            indexed_entries.append(app)

    result = indexed_entries
    _APP_INDEX_DIAGNOSTICS = {"cache_hit": False, "fingerprint": fingerprint}
    try:
        atomic_write_json(
            cache_path,
            {
                "version": APP_INDEX_CACHE_VERSION,
                "timestamp": now,
                "fingerprint": fingerprint,
                "apps": [app.to_dict() for app in result],
            },
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


def _success_cleanup_policy(entry: AppEntry) -> str:
    cleanup = entry.process_cleanup
    if "success" in cleanup:
        return str(cleanup.get("success", "window-only"))
    legacy_mode = str(cleanup.get("mode", "none"))
    return "owned-after-close" if legacy_mode == "owned-after-close" else "window-only"


def _poll_for_launched_window(
    entry: AppEntry,
    before_hwnds: set[int],
    timeout: float,
) -> dict[str, Any] | None:
    from .windows import list_windows

    observed = observe_window(
        list_windows=list_windows,
        is_match=lambda window: is_matching_window(window, entry),
        baseline_hwnds=before_hwnds,
        timeout=timeout,
        interval=APP_WINDOW_READY_INTERVAL,
    )
    if observed.status == "found":
        return observed.window
    if observed.status == "observation_error":
        raise LCUError(
            "window_observation_failed",
            f"Could not enumerate windows for '{entry.name}'",
            details={"stage": "observe", "observation_error": observed.error},
        )
    if observed.status == "ambiguous":
        raise LCUError(
            "ambiguous_target",
            f"Multiple new windows matched '{entry.name}'",
            candidates=[_window_candidate(window) for window in observed.candidates[:10]],
            details={"stage": "observe", "retry_launch_allowed": False},
        )
    return None


def _window_candidate(window: dict[str, Any]) -> dict[str, Any]:
    return {
        "hwnd": window.get("hwnd"),
        "pid": window.get("pid"),
        "title": window.get("title", ""),
        "process": window.get("process", ""),
        "active": bool(window.get("active")),
    }


def _recheck_window(win: dict[str, Any], entry: AppEntry) -> bool:
    """Do not focus a recycled HWND or a PID that changed since enumeration."""
    from .windows import list_windows
    current = next((w for w in list_windows() if w.get("hwnd") == win.get("hwnd")), None)
    return bool(
        current and current.get("pid") == win.get("pid")
        and current.get("creation_time") == win.get("creation_time")
        and window_match_status(current, entry) == "match"
    )


def _error_details(
    *, attempt_id: str, stage: str, dispatch_accepted: bool | None,
    hwnd: int | None = None, window_pid: int | None = None,
) -> dict[str, Any]:
    return {
        "attempt_id": attempt_id,
        "stage": stage,
        "dispatch_accepted": dispatch_accepted,
        "hwnd": hwnd,
        "window_pid": window_pid,
        "window_verified": hwnd is not None,
        "foreground": False,
        "retry_launch_allowed": False,
    }


def _dispatch_accepted(status: Any) -> bool | None:
    return True if status == "accepted" else False if status == "rejected" else None


def _coerce_receipt(info: dict[str, Any], elapsed_ms: float) -> dict[str, Any]:
    if "status" in info:
        return info
    # Compatibility for custom dispatch adapters written against the v2 dict.
    return {
        **info,
        "status": "accepted",
        "accepted": True,
        "backend": info.get("launch_type", "legacy-adapter"),
        "elapsed_ms": elapsed_ms,
        "fallback_eligible": False,
    }


def _entry_for_attempt(entry: AppEntry) -> dict[str, Any]:
    data = entry.to_dict()
    data["commands"] = []
    for candidate in data.get("candidates", []):
        candidate.pop("args", None)
        expected = candidate.get("expected_identity")
        if isinstance(expected, dict):
            expected.pop("arguments", None)
    return data


def _candidate_target_is_stale(candidate: LaunchCandidate) -> bool:
    if candidate.method in {"uri", "appsfolder"}:
        return False
    target = candidate.target.strip().strip('"')
    path = Path(target)
    return (path.is_absolute() or candidate.method == "start-menu") and not path.is_file()


def open_app(
    name: str,
    config_path: Path | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    if not name or not name.strip():
        raise LCUError("invalid_arguments", "Application name cannot be empty")

    started_at = time.monotonic()
    attempt_id = str(uuid.uuid4())

    resolve_started_at = time.monotonic()
    index = build_app_index(config_path)
    entry, candidates = find_app_entry(name.strip(), index)
    if entry is None and not candidates:
        index = build_app_index(config_path, force_refresh=True)
        entry, candidates = find_app_entry(name.strip(), index)
    resolve_ms = round((time.monotonic() - resolve_started_at) * 1000, 1)

    if candidates:
        raise LCUError(
            "ambiguous_target",
            f"Multiple applications matched '{name}'",
            candidates=candidates[:10],
            details=_error_details(attempt_id=attempt_id, stage="resolve", dispatch_accepted=False),
        )

    if entry is None:
        raise LCUError(
            "target_not_found", f"No application found matching '{name}'",
            details=_error_details(attempt_id=attempt_id, stage="resolve", dispatch_accepted=False),
        )

    if any(_candidate_target_is_stale(candidate) for candidate in entry.candidates):
        refreshed = build_app_index(config_path, force_refresh=True)
        refreshed_entry, refreshed_candidates = find_app_entry(name.strip(), refreshed)
        if refreshed_entry is not None and not refreshed_candidates:
            entry = refreshed_entry

    if entry.candidates and all(_candidate_target_is_stale(c) for c in entry.candidates):
        raise LCUError(
            "target_not_found", f"All resolved launch targets for '{name}' are stale",
            details=_error_details(attempt_id=attempt_id, stage="resolve", dispatch_accepted=False),
        )

    # Phase 6: Pre-check for existing window
    from .windows import focus_window, list_windows
    try:
        existing_windows = find_matching_windows(entry)
    except Exception as exc:
        raise LCUError(
            "window_observation_failed",
            f"Could not inspect existing windows for '{name}'",
            details={
                **_error_details(attempt_id=attempt_id, stage="inspect_existing", dispatch_accepted=False),
                "observation_error": f"{type(exc).__name__}: {exc}",
            },
        ) from exc

    if len(existing_windows) > 1:
        raise LCUError(
            "ambiguous_target",
            f"Multiple existing windows matched '{name}'",
            candidates=[_window_candidate(window) for window in existing_windows[:10]],
            details=_error_details(attempt_id=attempt_id, stage="inspect_existing", dispatch_accepted=False),
        )

    # Single existing window -> restore/focus and reuse
    if len(existing_windows) == 1:
        target_win = existing_windows[0]
        try:
            if not _recheck_window(target_win, entry):
                raise ValueError("Window identity changed before focus")
            focus_window(hwnd=target_win.get("hwnd"))
            win_pid = target_win.get("pid")
            win_proc = target_win.get("process", "")
            result = {
                "app": entry.name,
                "target": None,
                "launch_method": "existing-window",
                "hwnd": target_win.get("hwnd", 0),
                "title": target_win.get("title", entry.name),
                "reused_existing": True,
                "window_pid": win_pid,
                "window_process": win_proc,
                "owned_processes": [],
                "attempt_id": attempt_id,
                "stage": "ready",
                "dispatch_accepted": False,
                "window_verified": True,
                "foreground": True,
            }
            if debug:
                result["debug"] = {
                    "resolve_ms": resolve_ms,
                    "dispatch_ms": 0.0,
                    "window_ready_ms": 0.0,
                    "candidate_count": 0,
                    "launch_context": get_launch_context_snapshot(),
                    "sanitized_env_applied": False,
                }
            return result
        except Exception as exc:
            raise LCUError(
                "window_focus_failed",
                f"Existing window for '{name}' could not be focused: {exc}",
                candidates=[_window_candidate(target_win)],
                details=_error_details(
                    attempt_id=attempt_id, stage="focus", dispatch_accepted=False,
                    hwnd=target_win.get("hwnd"), window_pid=target_win.get("pid"),
                ),
            ) from exc

    # Process data is used only for best-effort cleanup evidence after success.
    try:
        baseline_processes = snapshot_processes()
        baseline_pids = set(baseline_processes.keys())
        baseline_trusted = snapshot_is_complete(baseline_processes)
    except Exception:
        baseline_processes = {}
        baseline_pids = set()
        baseline_trusted = False

    try:
        all_before = list_windows()
        before_hwnds = {int(w.get("hwnd", 0)) for w in all_before}
    except Exception as exc:
        raise LCUError(
            "window_observation_failed", f"Could not establish window baseline for '{name}'",
            details={
                **_error_details(attempt_id=attempt_id, stage="observe", dispatch_accepted=False),
                "observation_error": f"{type(exc).__name__}: {exc}",
            },
        ) from exc

    attempts: list[dict[str, Any]] = []
    success_cleanup = _success_cleanup_policy(entry)
    dispatched_families: set[tuple[Any, ...]] = set()
    candidate_count = 0
    dispatch_ms = 0.0
    sanitized_env_applied = False
    safety_warnings: list[str] = []
    if not baseline_trusted:
        safety_warnings.append("baseline_process_snapshot_untrusted: ownership recording disabled")

    selected_candidate: LaunchCandidate | None = None
    receipt: dict[str, Any] | None = None
    fallback_used = False
    for candidate in entry.candidates:
        if _candidate_target_is_stale(candidate):
            attempts.append({
                "method": candidate.method,
                "target": candidate.target,
                "result": "stale_target",
            })
            continue
        family = candidate_launch_family(candidate)
        if family in dispatched_families:
            continue
        dispatched_families.add(family)
        candidate_count += 1

        try:
            dispatch_started_at = time.monotonic()
            dispatch_info = dispatch_candidate(candidate)
            elapsed_ms = (time.monotonic() - dispatch_started_at) * 1000
            dispatch_ms += elapsed_ms
            receipt = _coerce_receipt(dispatch_info, elapsed_ms)
            sanitized_env_applied = sanitized_env_applied or bool(
                receipt.get("sanitized_env_applied")
            )
        except Exception as exc:
            code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
            receipt = {
                "status": "rejected", "accepted": False, "backend": "adapter",
                "elapsed_ms": round((time.monotonic() - dispatch_started_at) * 1000, 1),
                "error_code": code, "error_type": type(exc).__name__, "message": str(exc),
                "fallback_eligible": code in {2, 3},
            }
        attempts.append({
            "method": candidate.method, "target": candidate.target,
            "result": f"dispatch_{receipt['status']}", "backend": receipt.get("backend"),
            "error_code": receipt.get("error_code"), "error_type": receipt.get("error_type"),
        })
        if receipt["status"] == "rejected":
            if receipt.get("fallback_eligible") and not fallback_used:
                fallback_used = True
                continue
            raise LCUError(
                "dispatch_rejected", f"Windows rejected launch of '{name}'",
                attempts=attempts, candidates=[c.target for c in entry.candidates],
                details={
                    **_error_details(attempt_id=attempt_id, stage="dispatch", dispatch_accepted=False),
                    "backend": receipt.get("backend"), "error_code": receipt.get("error_code"),
                },
            )
        selected_candidate = candidate
        break

    if selected_candidate is None or receipt is None:
        if attempts and all(attempt.get("result") == "stale_target" for attempt in attempts):
            raise LCUError(
                "target_not_found", f"All resolved launch targets for '{name}' are stale",
                attempts=attempts, candidates=[c.target for c in entry.candidates],
                details=_error_details(
                    attempt_id=attempt_id, stage="resolve", dispatch_accepted=False
                ),
            )
        raise LCUError(
            "dispatch_rejected", f"No launch specification was accepted for '{name}'",
            attempts=attempts, candidates=[c.target for c in entry.candidates],
            details=_error_details(attempt_id=attempt_id, stage="dispatch", dispatch_accepted=False),
        )

    dispatch_accepted = _dispatch_accepted(receipt.get("status"))
    # An attempt ID is only advertised after observation state is persisted.
    try:
        save_app_attempt(
            attempt_id,
            {
                "entry": _entry_for_attempt(entry), "baseline_hwnds": sorted(before_hwnds),
                "dispatch": {
                    "status": receipt.get("status"), "backend": receipt.get("backend"),
                    "pid": receipt.get("pid"), "elapsed_ms": receipt.get("elapsed_ms"),
                },
            },
        )
    except OSError as exc:
        raise LCUError(
            "attempt_state_unavailable", "Launch outcome cannot be observed through app_status",
            details={**_error_details(attempt_id=attempt_id, stage="observe",
                                      dispatch_accepted=dispatch_accepted),
                     "observation_error": f"{type(exc).__name__}: {exc}",
                     "attempt_queryable": False},
        ) from exc
    window_wait_started_at = time.monotonic()
    try:
        detected_win = _poll_for_launched_window(entry, before_hwnds, APP_WINDOW_TIMEOUT)
    except LCUError as exc:
        exc.details = {
            **_error_details(
                attempt_id=attempt_id, stage="observe", dispatch_accepted=dispatch_accepted
            ),
            "backend": receipt.get("backend"),
            **exc.details,
        }
        raise

    if detected_win is not None:
            detected_hwnd = detected_win.get("hwnd", 0)
            try:
                if not _recheck_window(detected_win, entry):
                    raise ValueError("Window identity changed before focus")
                focus_window(hwnd=detected_hwnd)
            except Exception as exc:
                raise LCUError(
                    "window_focus_failed",
                    f"Window with hwnd {detected_hwnd} detected for '{name}', but failed to focus: {exc}",
                    candidates=[_window_candidate(detected_win)],
                    details=_error_details(
                        attempt_id=attempt_id, stage="focus", dispatch_accepted=dispatch_accepted,
                        hwnd=detected_hwnd, window_pid=detected_win.get("pid"),
                    ),
                ) from exc

            is_reused = detected_hwnd in before_hwnds
            win_pid = detected_win.get("pid")
            if win_pid is None and os.name == "nt":
                try:
                    import win32process

                    _, win_pid = win32process.GetWindowThreadProcessId(detected_hwnd)
                except Exception:
                    win_pid = None

            win_proc = detected_win.get("process", "")

            # Process Ownership calculation:
            owned_processes: list[dict[str, Any]] = []

            # Only track owned processes if NOT reusing an existing window and window PID is not a baseline process
            raw_dispatch_identity = receipt.get("dispatch_identity")
            try:
                dispatch_identity = ProcessIdentity.from_dict(raw_dispatch_identity) if isinstance(raw_dispatch_identity, dict) else None
            except (KeyError, TypeError, ValueError):
                dispatch_identity = None
            if receipt.get("backend") == "process" and baseline_trusted and not is_reused and dispatch_identity is not None and (
                win_pid is None or win_pid not in baseline_pids
            ) and dispatch_identity.pid not in baseline_pids and dispatch_identity.creation_time is not None and dispatch_identity.session_id is not None and dispatch_identity.image_path:
                try:
                    after_processes = snapshot_processes()
                except Exception:
                    after_processes = {}
                live_dispatcher = after_processes.get(dispatch_identity.pid)
                if (
                    snapshot_is_complete(after_processes)
                    and live_dispatcher is not None
                    and live_dispatcher.creation_time == dispatch_identity.creation_time
                    and live_dispatcher.session_id == dispatch_identity.session_id
                    and live_dispatcher.image_path is not None
                    and ntpath.normcase(live_dispatcher.image_path) == ntpath.normcase(dispatch_identity.image_path)
                ):
                    p_dict = dispatch_identity.to_dict()
                    p_dict["cleanup_mode"] = success_cleanup
                    p_dict["ownership_evidence"] = "exact-dispatch-identity"
                    p_dict["dispatch_backend"] = "process"
                    owned_processes.append(p_dict)

            successful_result: dict[str, Any] = {
                "app": entry.name,
                "target": selected_candidate.target,
                "launch_method": selected_candidate.method,
                "hwnd": detected_hwnd,
                "title": detected_win.get("title", entry.name),
                "reused_existing": is_reused,
                "window_pid": win_pid,
                "window_process": win_proc,
                "owned_processes": owned_processes,
                "attempt_id": attempt_id,
                "stage": "ready",
                "dispatch_accepted": dispatch_accepted,
                "window_verified": True,
                "foreground": True,
            }
            try:
                if owned_processes:
                    remember_owned_processes(
                    app=entry.name,
                    hwnd=int(detected_hwnd),
                    window_pid=int(win_pid) if win_pid is not None else None,
                    owned_processes=owned_processes,
                    )
            except Exception:
                pass
            if debug:
                successful_result["debug"] = {
                    "resolve_ms": resolve_ms,
                    "dispatch_ms": round(dispatch_ms, 1),
                    "window_ready_ms": round((time.monotonic() - window_wait_started_at) * 1000, 1),
                    "total_ms": round((time.monotonic() - started_at) * 1000, 1),
                    "candidate_count": candidate_count,
                    "launch_context": get_launch_context_snapshot(),
                    "sanitized_env_applied": sanitized_env_applied,
                    "gui_env_normalization": get_gui_env_normalization(
                        applied=sanitized_env_applied
                    ),
                    "safety_warnings": safety_warnings,
                }
            return successful_result

    error_code = "window_unconfirmed" if dispatch_accepted is True else "dispatch_outcome_unknown"
    raise LCUError(
        error_code,
        f"Launch was dispatched for '{name}', but no target window was confirmed",
        attempts=attempts,
        candidates=[c.target for c in entry.candidates],
        details={
            **_error_details(attempt_id=attempt_id, stage="observe", dispatch_accepted=dispatch_accepted),
            "backend": receipt.get("backend"),
            "window_wait_ms": round((time.monotonic() - window_wait_started_at) * 1000, 1),
        },
    )


def app_status(attempt_id: str, timeout: float = 0.0) -> dict[str, Any]:
    try:
        payload = load_app_attempt(attempt_id)
    except KeyError as exc:
        raise LCUError("attempt_not_found", f"No app attempt found: {attempt_id}") from exc
    except TimeoutError as exc:
        raise LCUError("attempt_expired", f"App attempt has expired: {attempt_id}") from exc
    except ValueError as exc:
        raise LCUError("attempt_invalid", str(exc)) from exc
    entry = AppEntry.from_dict(payload["entry"])
    before_hwnds = {int(value) for value in payload.get("baseline_hwnds", [])}
    detected = _poll_for_launched_window(entry, before_hwnds, max(0.0, timeout))
    if detected is None:
        return {
            "attempt_id": attempt_id, "stage": "observe", "status": "window_unconfirmed",
            "dispatch_accepted": _dispatch_accepted(payload.get("dispatch", {}).get("status")),
            "window_verified": False, "foreground": False, "retry_launch_allowed": False,
        }
    return {
        "attempt_id": attempt_id, "stage": "observe", "status": "window_found",
        "dispatch_accepted": _dispatch_accepted(payload.get("dispatch", {}).get("status")),
        "hwnd": detected.get("hwnd"), "window_pid": detected.get("pid"),
        "window_verified": True, "foreground": bool(detected.get("active")),
        "title": detected.get("title", ""), "process": detected.get("process", ""),
        "retry_launch_allowed": False,
    }

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import LCUError
from .processes import (
    ProcessIdentity,
    is_same_process,
    snapshot_processes,
    terminate_process,
    validate_termination_safety,
)

CACHE_MAX_AGE_SECONDS = 86_400  # 24 hours
APP_INDEX_CACHE_VERSION = 5
APP_WINDOW_READY_TIMEOUT = 2.5
APP_WINDOW_READY_INTERVAL = 0.1

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
    priority: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "target": self.target,
            "method": self.method,
            "source": self.source,
        }
        if self.args:
            d["args"] = list(self.args)
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
            priority=priority,
        )


def candidate_priority_key(candidate: LaunchCandidate) -> int:
    if candidate.priority is not None:
        return candidate.priority
    return CANDIDATE_PRIORITY.get(candidate.method, 99)


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


def _is_packaged_app_command(command: str) -> bool:
    return command.strip().lower().startswith("shell:appsfolder\\")


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
        seen_keys: set[tuple[str, tuple[str, ...]]] = set()
        unique_candidates: list[LaunchCandidate] = []

        sorted_cands = sorted(self.candidates, key=candidate_priority_key)
        for cand in sorted_cands:
            norm_key = (cand.target.strip().lower(), tuple(cand.args))
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
        )


def merge_app_entries(primary: AppEntry, secondary: AppEntry) -> AppEntry:
    # Primary provides the canonical name, normalized, and primary source
    merged_aliases = list(dict.fromkeys(primary.aliases + secondary.aliases))
    merged_candidates = list(primary.candidates) + list(secondary.candidates)
    proc_cleanup = primary.process_cleanup or secondary.process_cleanup
    return AppEntry(
        name=primary.name,
        target=primary.target,
        source=primary.source,
        aliases=merged_aliases,
        normalized=primary.normalized,
        candidates=merged_candidates,
        process_cleanup=proc_cleanup,
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

            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    key_path = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{target_clean}"
                    with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ) as key:
                        val, _ = winreg.QueryValueEx(key, None)
                        if val and isinstance(val, str) and Path(val.strip().strip('"')).is_file():
                            return str(Path(val.strip().strip('"')).resolve())
                except OSError:
                    continue
        except Exception:
            pass

    return target_clean


def dispatch_candidate(candidate: LaunchCandidate) -> None:
    if candidate.args:
        resolved = resolve_executable(candidate.target)
        resolved_lower = resolved.lower()
        if resolved_lower.endswith(".cmd") or resolved_lower.endswith(".bat"):
            cmd = ["cmd.exe", "/d", "/s", "/c", resolved, *candidate.args]
            subprocess.Popen(cmd, shell=False)
        else:
            subprocess.Popen([resolved, *candidate.args], shell=False)
    else:
        if os.name == "nt":
            os.startfile(candidate.target)
        else:
            subprocess.Popen(candidate.target, shell=True)


def is_matching_window(win: dict[str, Any], entry: AppEntry) -> bool:
    title = win.get("title", "").strip().lower()
    proc = win.get("process", "").strip().lower()

    known_exes = set()
    for cand in entry.candidates:
        t = cand.target.strip().lower()
        if t.endswith(".exe"):
            known_exes.add(Path(t).name.lower())
    if not known_exes:
        known_exes.add(f"{entry.normalized}.exe")
        known_exes.add(f"{entry.name.lower()}.exe")

    # 1. Process matching
    if proc and proc in known_exes:
        return True

    # 2. Title matching
    queries = [entry.name.lower()] + [a.lower() for a in entry.aliases]
    valid_queries = [q for q in queries if len(q) >= 2]

    for q in valid_queries:
        if q == title or (len(q) >= 3 and q in title):
            # Ignore common development tools matching title unless the entry itself is that tool
            if entry.normalized not in (
                "explorer",
                "visualstudiocode",
                "code",
                "cmd",
                "powershell",
                "windowsterminal",
            ) and proc in (
                "code.exe",
                "explorer.exe",
                "windowsterminal.exe",
                "cmd.exe",
                "powershell.exe",
            ):
                continue
            return True

    return False


def find_matching_windows(
    entry: AppEntry, windows_list: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    if windows_list is None:
        try:
            from .windows import list_windows

            windows_list = list_windows()
        except Exception:
            return []

    return [w for w in windows_list if is_matching_window(w, entry)]


def _wait_for_visible_app_window(
    entry: AppEntry,
    timeout: float = APP_WINDOW_READY_TIMEOUT,
    interval: float = APP_WINDOW_READY_INTERVAL,
) -> bool:
    if os.name != "nt":
        return True
    try:
        from .windows import list_windows
    except ImportError:
        return True

    t_end = time.time() + timeout
    max_checks = max(1, int(round(timeout / interval)) + 1) if interval > 0 else 1
    checks = 0

    while checks < max_checks:
        try:
            wins = list_windows()
            matching = [w for w in wins if is_matching_window(w, entry)]
            if matching:
                return True
        except Exception:
            pass

        checks += 1
        if time.time() >= t_end or checks >= max_checks:
            break
        if interval > 0:
            time.sleep(interval)
    return False


def get_cache_file_path() -> Path:
    temp_dir = Path(tempfile.gettempdir()) / "LiteComputerUse"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / "app-index.json"


def load_config_apps(config_path: Path | None = None) -> list[AppEntry]:
    if config_path is None:
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
            raw_cmds = app_info.get("commands", [])
            if not raw_cmds:
                continue
            proc_cleanup = app_info.get("process_cleanup", {})

            candidates: list[LaunchCandidate] = []
            command_strings: list[str] = []
            for item in raw_cmds:
                if isinstance(item, dict):
                    cand_target = str(item.get("target", "")).strip()
                    raw_args = item.get("args", [])
                    cand_args = tuple(str(a) for a in raw_args) if isinstance(raw_args, (list, tuple)) else ()
                    p = item.get("priority")
                    cand_priority = int(p) if p is not None else None
                    method = classify_launch_method(cand_target, "config")
                    candidates.append(
                        LaunchCandidate(
                            target=cand_target,
                            method=method,
                            source="config",
                            args=cand_args,
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
            cached_version = cached_data.get("version")
            cached_time = cached_data.get("timestamp", 0)
            if cached_version == APP_INDEX_CACHE_VERSION and (now - cached_time < CACHE_MAX_AGE_SECONDS):
                items = cached_data.get("apps", [])
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
            if entry_match_keys(existing) & app_keys:
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
            if entry_match_keys(existing) & app_keys:
                matched_idx = i
                break
        if matched_idx is not None:
            indexed_entries[matched_idx] = merge_app_entries(
                primary=indexed_entries[matched_idx], secondary=app
            )
        else:
            indexed_entries.append(app)

    result = indexed_entries
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "version": APP_INDEX_CACHE_VERSION,
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

    # Phase 6: Pre-check for existing window
    try:
        from .windows import focus_window, list_windows

        existing_windows = find_matching_windows(entry)
    except Exception:
        existing_windows = []

    # Single existing window -> restore/focus and reuse
    if len(existing_windows) == 1:
        target_win = existing_windows[0]
        try:
            focus_window(hwnd=target_win.get("hwnd"))
            win_pid = target_win.get("pid")
            win_proc = target_win.get("process", "")
            return {
                "app": entry.name,
                "target": None,
                "launch_method": "existing-window",
                "hwnd": target_win.get("hwnd", 0),
                "title": target_win.get("title", entry.name),
                "reused_existing": True,
                "window_pid": win_pid,
                "window_process": win_proc,
                "owned_processes": [],
            }
        except Exception:
            # If focusing existing window fails (e.g. was closing), proceed to fresh launch
            pass

    # Baseline processes and window handles before any candidate launch
    try:
        baseline_processes = snapshot_processes()
        baseline_pids = set(baseline_processes.keys())
    except Exception:
        baseline_processes = {}
        baseline_pids = set()

    try:
        all_before = list_windows()
        before_hwnds = {w.get("hwnd", 0) for w in all_before}
    except Exception:
        all_before = []
        before_hwnds = set()

    attempts: list[dict[str, Any]] = []
    successful_result: dict[str, Any] | None = None

    cleanup_mode = entry.process_cleanup.get("mode", "none")
    expected_process_names = entry.process_cleanup.get("process_names", [])

    for candidate in entry.candidates:
        # Per-attempt process snapshot BEFORE dispatch
        try:
            before_cand_processes = snapshot_processes()
            before_cand_pids = set(before_cand_processes.keys())
        except Exception:
            before_cand_processes = baseline_processes
            before_cand_pids = set(baseline_pids)

        try:
            dispatch_candidate(candidate)
        except Exception as exc:
            attempts.append(
                {
                    "method": candidate.method,
                    "target": candidate.target,
                    "result": f"dispatch_error: {exc}",
                }
            )
            continue

        # Polling for visible window
        t_end = time.time() + APP_WINDOW_READY_TIMEOUT
        max_checks = (
            max(1, int(round(APP_WINDOW_READY_TIMEOUT / APP_WINDOW_READY_INTERVAL)) + 1)
            if APP_WINDOW_READY_INTERVAL > 0
            else 1
        )
        checks = 0
        detected_win: dict[str, Any] | None = None

        while checks < max_checks:
            try:
                current_windows = list_windows()

                # 1. Check for newly created window matching entry
                new_matching = [
                    w
                    for w in current_windows
                    if w.get("hwnd", 0) not in before_hwnds and is_matching_window(w, entry)
                ]
                if len(new_matching) == 1:
                    detected_win = new_matching[0]
                    break
                elif len(new_matching) > 1:
                    active_new = next((w for w in new_matching if w.get("active")), new_matching[0])
                    detected_win = active_new
                    break

                # 2. Check if an existing matching window became active/foreground
                active_matching = next(
                    (
                        w
                        for w in current_windows
                        if w.get("active") and is_matching_window(w, entry)
                    ),
                    None,
                )
                if active_matching:
                    detected_win = active_matching
                    break

                # 3. If before_hwnds had no matching windows, any matching window counts
                matching_all = [w for w in current_windows if is_matching_window(w, entry)]
                if matching_all and not any(w.get("hwnd", 0) in before_hwnds for w in matching_all):
                    detected_win = matching_all[0]
                    break
            except Exception:
                pass

            checks += 1
            if time.time() >= t_end or checks >= max_checks:
                break
            if APP_WINDOW_READY_INTERVAL > 0:
                time.sleep(APP_WINDOW_READY_INTERVAL)

        if detected_win is not None:
            detected_hwnd = detected_win.get("hwnd", 0)
            try:
                from .windows import focus_window

                focus_window(hwnd=detected_hwnd)
            except Exception as exc:
                raise LCUError(
                    "window_focus_failed",
                    f"Window with hwnd {detected_hwnd} detected for '{name}', but failed to focus: {exc}",
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
            if not is_reused and (win_pid is None or win_pid not in baseline_pids):
                try:
                    after_processes = snapshot_processes()
                except Exception:
                    after_processes = {}

                cand_new_pids = (set(after_processes.keys()) - before_cand_pids) - baseline_pids

                allowed_names = expected_process_names or ([win_proc] if win_proc else [])
                if not allowed_names and candidate.target.endswith(".exe"):
                    allowed_names = [Path(candidate.target).name.lower()]

                for pid in sorted(cand_new_pids):
                    p_ident = after_processes.get(pid)
                    if not p_ident:
                        continue
                    if allowed_names:
                        if not any(p_ident.process_name.lower() == a.lower() for a in allowed_names):
                            continue
                    p_dict = p_ident.to_dict()
                    p_dict["cleanup_mode"] = cleanup_mode
                    owned_processes.append(p_dict)

            successful_result = {
                "app": entry.name,
                "target": candidate.target,
                "launch_method": candidate.method,
                "hwnd": detected_hwnd,
                "title": detected_win.get("title", entry.name),
                "reused_existing": is_reused,
                "window_pid": win_pid,
                "window_process": win_proc,
                "owned_processes": owned_processes,
            }
            break
        else:
            # Candidate failed to produce a visible window -> Rollback on failure!
            rollback_pids: list[int] = []
            if cleanup_mode in ("rollback-on-failure", "owned-after-close"):
                try:
                    after_cand_processes = snapshot_processes()
                    cand_new_pids = (set(after_cand_processes.keys()) - before_cand_pids) - baseline_pids
                    allowed_names = expected_process_names or [Path(candidate.target).name.lower()]

                    for pid in sorted(cand_new_pids):
                        p_ident = after_cand_processes.get(pid)
                        if not p_ident:
                            continue
                        safe, reason = validate_termination_safety(
                            identity=p_ident,
                            baseline_pids=baseline_pids,
                            allowed_process_names=allowed_names,
                        )
                        if safe:
                            if terminate_process(p_ident):
                                rollback_pids.append(pid)
                except Exception:
                    pass

            attempts.append(
                {
                    "method": candidate.method,
                    "target": candidate.target,
                    "result": "no_visible_window",
                    "rolled_back_pids": rollback_pids,
                }
            )

    if successful_result is None:
        raise LCUError(
            "dispatch_failed",
            f"Failed to launch application '{name}' ({entry.target}): no visible window found",
            attempts=attempts,
            candidates=[c.target for c in entry.candidates],
        )

    return successful_result

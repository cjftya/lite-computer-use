from __future__ import annotations

import json
import os
import stat
import tempfile
import time
import ctypes
import hashlib
import uuid
from collections.abc import Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlsplit

import yaml


class LCUError(RuntimeError):
    """Expected, user-actionable Lite Computer Use failure."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True)
class AppDefinition:
    name: str
    aliases: tuple[str, ...]
    commands: tuple[str, ...]
    source: str = "registry"


class AppRegistry:
    def __init__(self, definitions: Iterable[AppDefinition]) -> None:
        self._definitions = tuple(definitions)
        self._aliases: dict[str, AppDefinition] = {}
        for definition in self._definitions:
            for alias in (definition.name, *definition.aliases):
                key = normalize_name(alias)
                existing = self._aliases.get(key)
                if existing and existing.name != definition.name:
                    raise ValueError(f"Duplicate app alias: {alias}")
                self._aliases[key] = definition

    @classmethod
    def load(cls, path: Path) -> AppRegistry:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError as exc:
            raise LCUError("config_not_found", f"App config not found: {path}") from exc
        except yaml.YAMLError as exc:
            raise LCUError("config_invalid", f"Invalid app config: {exc}") from exc

        apps = raw.get("apps")
        if not isinstance(apps, dict):
            raise LCUError(
                "config_invalid", "config/apps.yaml must contain an 'apps' mapping"
            )

        definitions: list[AppDefinition] = []
        for name, value in apps.items():
            if not isinstance(value, dict):
                raise LCUError("config_invalid", f"App '{name}' must be a mapping")
            aliases = value.get("aliases", [])
            commands = value.get("commands", [])
            if not isinstance(aliases, list) or not all(
                isinstance(x, str) for x in aliases
            ):
                raise LCUError(
                    "config_invalid", f"App '{name}' aliases must be strings"
                )
            if (
                not isinstance(commands, list)
                or not commands
                or not all(isinstance(x, str) and x.strip() for x in commands)
            ):
                raise LCUError(
                    "config_invalid", f"App '{name}' needs at least one command"
                )
            definitions.append(
                AppDefinition(
                    name=str(name),
                    aliases=tuple(aliases),
                    commands=tuple(commands),
                )
            )
        return cls(definitions)

    def resolve(self, query: str) -> AppDefinition:
        result = self._aliases.get(normalize_name(query))
        if result is None:
            raise LCUError(
                "app_not_registered",
                f"App is not registered: {query}",
                available=[definition.name for definition in self._definitions],
            )
        return result

    def names(self) -> list[str]:
        return [definition.name for definition in self._definitions]

    def definitions(self) -> tuple[AppDefinition, ...]:
        return self._definitions

    def lookup_terms_for(self, query: str) -> set[str]:
        definition = self._aliases.get(normalize_name(query))
        if definition is None:
            return {query}
        terms = {definition.name, *definition.aliases}
        for command in definition.commands:
            expanded = os.path.expandvars(command)
            if expanded.endswith(":"):
                continue
            filename = Path(expanded).name
            terms.update({filename, Path(filename).stem})
        return {term for term in terms if normalize_name(term)}

    def process_names_for(self, query: str) -> set[str]:
        definition = self._aliases.get(normalize_name(query))
        if definition is None:
            return set()
        names: set[str] = set()
        for command in definition.commands:
            expanded = os.path.expandvars(command)
            if expanded.endswith(":"):
                continue
            filename = Path(expanded).name
            names.add(normalize_name(filename))
            names.add(normalize_name(Path(filename).stem))
        return {name for name in names if name}


def normalize_name(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def target_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()[:12]


def runtime_root() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
    else:
        base = Path(tempfile.gettempdir())
    root = base / "LiteComputerUse"
    root.mkdir(parents=True, exist_ok=True)
    return root


class ActionLock(AbstractContextManager["ActionLock"]):
    """Small cross-process lock that prevents two agents driving the UI together."""

    def __init__(self, timeout: float = 2.0, stale_after: float = 120.0) -> None:
        self.timeout = timeout
        self.stale_after = stale_after
        self.path = runtime_root() / "action.lock"
        self._owned = False

    def __enter__(self) -> Self:
        deadline = time.monotonic() + self.timeout
        payload = json.dumps({"pid": os.getpid(), "created": time.time()})
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                self._owned = True
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                    if age > self.stale_after:
                        self.path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise LCUError(
                        "busy",
                        "Another Lite Computer Use action is in progress",
                    )
                time.sleep(0.05)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._owned:
            self.path.unlink(missing_ok=True)
            self._owned = False


def append_action_log(
    action: str,
    ok: bool,
    details: dict[str, Any] | None = None,
    duration_ms: float | None = None,
) -> None:
    try:
        log_dir = runtime_root() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "ok": ok,
            "details": details or {},
        }
        if duration_ms is not None:
            record["durationMs"] = max(0.0, duration_ms)
        with (log_dir / "actions.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    except OSError:
        # Logging is diagnostic only and must never turn a successful UI action
        # into a reported failure.
        return


def safe_log_details(action: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if action in {"type_text", "set_clipboard", "get_clipboard"}:
        text = arguments.get("text")
        return {"length": len(text) if isinstance(text, str) else None}
    if action == "open_url":
        url = str(arguments.get("url", ""))
        return {"host": urlsplit(url).hostname or ""}
    if action in {"open_file", "open_folder", "reveal_file"}:
        value = Path(str(arguments.get("path", "")))
        return {
            "extension": value.suffix.casefold(),
            "targetFingerprint": target_fingerprint(str(value)),
        }
    if action in {"click", "double_click"}:
        return {
            "x": arguments.get("x"),
            "y": arguments.get("y"),
            "relative_to": arguments.get("relative_to", "screen"),
            "button": arguments.get("button", "left"),
        }
    if action == "move_mouse":
        return {
            "x": arguments.get("x"),
            "y": arguments.get("y"),
            "relative_to": arguments.get("relative_to", "screen"),
        }
    if action == "drag":
        return {
            "start_x": arguments.get("start_x"),
            "start_y": arguments.get("start_y"),
            "end_x": arguments.get("end_x"),
            "end_y": arguments.get("end_y"),
            "duration": arguments.get("duration"),
            "button": arguments.get("button", "left"),
            "relative_to": arguments.get("relative_to", "screen"),
        }
    if action == "launch_app":
        name = str(arguments.get("name", ""))
        return {"name": name, "targetFingerprint": target_fingerprint(normalize_name(name))}
    if action == "list_apps":
        return {"refresh": bool(arguments.get("refresh", False))}
    if action in {
        "focus_window",
        "set_window_state",
        "set_window_bounds",
        "close_window",
        "wait_for_window",
    }:
        title = str(arguments.get("title", ""))
        hwnd = arguments.get("hwnd")
        details = {
            "query_length": len(title),
            "targetFingerprint": target_fingerprint(title) if title else None,
            "hwndSpecified": hwnd is not None,
        }
        for key in ("state", "width", "height", "timeout"):
            if key in arguments:
                details[key] = arguments[key]
        return details
    if action == "scroll":
        return {"amount": arguments.get("amount")}
    if action in {"press_key", "hotkey"}:
        details = {"keys": arguments.get("keys") or arguments.get("key")}
        if action == "press_key":
            details["count"] = arguments.get("count", 1)
        return details
    if action == "screenshot":
        details = {"scale": arguments.get("scale", 1.0)}
        if arguments.get("region"):
            details["region"] = arguments["region"]
        return details
    if action == "sequence":
        # The sequence JSON can contain typed text and window titles. Record
        # only its encoded length; per-step results remain in the CLI response.
        inline = arguments.get("sequence_json")
        source = "inline" if inline is not None else (
            "file" if arguments.get("sequence_file") is not None else "stdin"
        )
        return {
            "payload_length": len(inline) if isinstance(inline, str) else None,
            "source": source,
        }
    if action in {"find_file", "find_folder"}:
        query = str(arguments.get("query", ""))
        return {
            "queryLength": len(query),
            "targetFingerprint": target_fingerprint(normalize_name(query)),
            "explicitRoot": bool(arguments.get("root")),
        }
    return {}


def default_search_roots() -> list[Path]:
    candidates = [Path(item["path"]) for item in known_folders().values()]
    result: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate.resolve(strict=False)))
        if key not in seen and candidate.is_dir():
            seen.add(key)
            result.append(candidate)
    return result


KNOWN_FOLDER_IDS = {
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
}


def _windows_known_folder(folder_id: str) -> Path:
    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    value = uuid.UUID(folder_id)
    raw = value.bytes_le
    guid = GUID.from_buffer_copy(raw)
    output = ctypes.c_wchar_p()
    shell32 = ctypes.windll.shell32
    shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    result = shell32.SHGetKnownFolderPath(
        ctypes.byref(guid), 0, None, ctypes.byref(output)
    )
    if result != 0 or not output.value:
        raise OSError(result, "SHGetKnownFolderPath failed")
    try:
        return Path(output.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(output, ctypes.c_void_p))


def known_folders() -> dict[str, dict[str, Any]]:
    """Return real Windows shell folders, retaining explicit fallback provenance."""
    home = Path.home()
    fallbacks = {
        "desktop": home / "Desktop",
        "documents": home / "Documents",
        "downloads": home / "Downloads",
    }
    result: dict[str, dict[str, Any]] = {}
    for name, fallback in fallbacks.items():
        path = fallback
        source = "fallback"
        fallback_used = True
        if os.name == "nt":
            try:
                path = _windows_known_folder(KNOWN_FOLDER_IDS[name])
                source = "windows-known-folder-api"
                fallback_used = False
            except (AttributeError, OSError, ValueError):
                pass
        result[name] = {
            "path": str(path),
            "source": source,
            "fallbackUsed": fallback_used,
            "exists": path.is_dir(),
        }
    return result


DEFAULT_SEARCH_EXCLUDES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
}


def search_entries(
    query: str,
    roots: Iterable[Path],
    limit: int = 20,
    *,
    kind: str = "file",
    max_depth: int = 6,
    max_visited: int = 20_000,
    timeout: float = 3.0,
    include_ignored: bool = False,
    strict_roots: bool = False,
) -> dict[str, Any]:
    needle = normalize_name(query)
    if not needle:
        raise LCUError("invalid_query", "Search query cannot be empty")
    if not 1 <= limit <= 100:
        raise LCUError("invalid_limit", "Result limit must be between 1 and 100")
    if kind not in {"file", "folder", "any"}:
        raise LCUError("invalid_kind", "Search kind must be file, folder, or any")
    if not 0 <= max_depth <= 32:
        raise LCUError("invalid_max_depth", "Maximum depth must be between 0 and 32")
    if not 1 <= max_visited <= 1_000_000:
        raise LCUError(
            "invalid_max_visited", "Maximum visited entries must be between 1 and 1000000"
        )
    if not 0 < timeout <= 30:
        raise LCUError("invalid_timeout", "Search timeout must be greater than 0 and at most 30 seconds")

    started = time.monotonic()
    resolved_roots: list[Path] = []
    seen_roots: set[str] = set()
    for raw_root in roots:
        root = Path(raw_root).expanduser()
        if not root.is_absolute():
            raise LCUError(
                "relative_path_not_allowed",
                "Search roots must be absolute",
                stage="validate_search_root",
                retryable=False,
                nextAction="provide_absolute_root",
            )
        root = root.resolve(strict=False)
        key = os.path.normcase(str(root))
        if key in seen_roots:
            continue
        try:
            root_mode = root.stat().st_mode
        except FileNotFoundError as exc:
            if strict_roots:
                raise LCUError(
                    "search_root_not_found",
                    "Search root does not exist",
                    stage="validate_search_root",
                    retryable=False,
                    nextAction="verify_search_root",
                ) from exc
            continue
        except PermissionError as exc:
            if strict_roots:
                raise LCUError(
                    "access_denied",
                    "Access was denied while validating a search root",
                    stage="validate_search_root",
                    retryable=False,
                    nextAction="check_access",
                ) from exc
            continue
        except OSError:
            if strict_roots:
                raise LCUError(
                    "search_root_invalid",
                    "Search root could not be validated",
                    stage="validate_search_root",
                    retryable=False,
                    nextAction="verify_search_root",
                )
            continue
        if not stat.S_ISDIR(root_mode):
            if strict_roots:
                raise LCUError(
                    "not_a_folder",
                    "Search root is not a folder",
                    stage="validate_search_root",
                    retryable=False,
                    nextAction="provide_folder_root",
                )
            continue
        seen_roots.add(key)
        resolved_roots.append(root)

    visited = 0
    matches: list[tuple[float, int, Path, str]] = []
    stopped_reason: str | None = None
    excluded = set() if include_ignored else DEFAULT_SEARCH_EXCLUDES
    seen_directories = {os.path.normcase(str(root)) for root in resolved_roots}
    depth_limited = False
    excluded_count = 0

    def budget_available() -> bool:
        nonlocal stopped_reason
        if visited >= max_visited:
            stopped_reason = "visited_limit"
            return False
        if time.monotonic() - started >= timeout:
            stopped_reason = "time_limit"
            return False
        return True

    for root in resolved_roots:
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack and budget_available():
            directory, depth = stack.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if not budget_available():
                            break
                        visited += 1
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                            is_file = entry.is_file(follow_symlinks=False)
                        except OSError:
                            continue
                        normalized = normalize_name(entry.name)
                        entry_kind = "folder" if is_dir else "file"
                        wanted = kind == "any" or kind == entry_kind
                        if wanted and needle in normalized:
                            path = Path(entry.path)
                            try:
                                stat_result = entry.stat(follow_symlinks=False)
                            except OSError:
                                continue
                            matches.append(
                                (
                                    stat_result.st_mtime,
                                    stat_result.st_size if is_file else 0,
                                    path,
                                    entry_kind,
                                )
                            )
                            if len(matches) >= limit:
                                stopped_reason = "result_limit"
                                break
                        if is_dir and normalize_name(entry.name) in excluded:
                            excluded_count += 1
                            continue
                        if is_dir and depth >= max_depth:
                            depth_limited = True
                            continue
                        if (
                            is_dir
                            and depth < max_depth
                            and not entry.is_symlink()
                        ):
                            try:
                                attributes = getattr(
                                    entry.stat(follow_symlinks=False),
                                    "st_file_attributes",
                                    0,
                                )
                            except OSError:
                                continue
                            if attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
                                continue
                            child = Path(entry.path)
                            child_key = os.path.normcase(str(child.resolve(strict=False)))
                            if child_key not in seen_directories:
                                seen_directories.add(child_key)
                                stack.append((child, depth + 1))
                    if stopped_reason:
                        break
            except OSError:
                continue
        if stopped_reason:
            break

    if stopped_reason is None and depth_limited:
        stopped_reason = "depth_limit"

    matches.sort(key=lambda item: (-item[0], normalize_name(item[2].name)))
    elapsed_ms = round((time.monotonic() - started) * 1000, 3)
    return {
        "matches": [
            {
                "path": str(path.resolve(strict=False)),
                "name": path.name,
                "kind": entry_kind,
                "extension": path.suffix.casefold() if entry_kind == "file" else "",
                "size": size,
                "modified": datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
            }
            for mtime, size, path, entry_kind in matches
        ],
        "roots": [str(root) for root in resolved_roots],
        "elapsedMs": elapsed_ms,
        "visitedCount": visited,
        "truncated": stopped_reason is not None,
        "incomplete": stopped_reason is not None,
        "stoppedReason": stopped_reason,
        "excludedDirectories": sorted(excluded),
        "excludedCount": excluded_count,
        "excludedByPolicy": excluded_count > 0,
    }


def find_files(
    query: str, roots: Iterable[Path], limit: int = 20
) -> list[dict[str, Any]]:
    return search_entries(query, roots, limit, kind="file")["matches"]

from __future__ import annotations

import json
import os
import tempfile
import time
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


def normalize_name(value: str) -> str:
    return " ".join(value.casefold().strip().split())


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
    action: str, ok: bool, details: dict[str, Any] | None = None
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
    if action == "open_file":
        value = Path(str(arguments.get("path", "")))
        return {"extension": value.suffix.casefold()}
    if action in {"click", "double_click"}:
        return {
            "x": arguments.get("x"),
            "y": arguments.get("y"),
            "relative_to": arguments.get("relative_to", "screen"),
        }
    if action == "launch_app":
        return {"name": arguments.get("name")}
    if action == "focus_window":
        return {"query_length": len(str(arguments.get("title", "")))}
    if action == "scroll":
        return {"amount": arguments.get("amount")}
    if action in {"press_key", "hotkey"}:
        return {"keys": arguments.get("keys") or arguments.get("key")}
    return {}


def default_search_roots() -> list[Path]:
    home = Path.home()
    candidates = [home / "Desktop", home / "Downloads", home / "Documents"]
    if os.name == "nt":
        profile = Path(os.environ.get("USERPROFILE", str(home)))
        onedrive = Path(os.environ.get("OneDrive", str(profile / "OneDrive")))
        candidates.extend(
            [
                profile / "Desktop",
                profile / "Downloads",
                profile / "Documents",
                onedrive / "Desktop",
                onedrive / "Documents",
            ]
        )

    result: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate.resolve(strict=False)))
        if key not in seen and candidate.is_dir():
            seen.add(key)
            result.append(candidate)
    return result


def find_files(
    query: str, roots: Iterable[Path], limit: int = 20
) -> list[dict[str, Any]]:
    needle = normalize_name(query)
    if not needle:
        raise LCUError("invalid_query", "File query cannot be empty")
    if not 1 <= limit <= 100:
        raise LCUError("invalid_limit", "File result limit must be between 1 and 100")

    matches: list[tuple[float, int, Path]] = []
    for root in roots:
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        for directory, dirnames, filenames in os.walk(
            root, topdown=True, followlinks=False
        ):
            dirnames[:] = [name for name in dirnames if not name.startswith(".")]
            for filename in filenames:
                if needle not in normalize_name(filename):
                    continue
                path = Path(directory) / filename
                try:
                    stat = path.stat()
                except OSError:
                    continue
                matches.append((stat.st_mtime, stat.st_size, path))

    matches.sort(key=lambda item: (-item[0], normalize_name(item[2].name)))
    return [
        {
            "path": str(path.resolve(strict=False)),
            "name": path.name,
            "extension": path.suffix.casefold(),
            "size": size,
            "modified": datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
        }
        for mtime, size, path in matches[:limit]
    ]

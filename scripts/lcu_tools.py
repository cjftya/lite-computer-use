from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import sys
import time
import traceback
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

if sys.version_info < (3, 11):
    print(
        json.dumps(
            {
                "ok": False,
                "action": "startup",
                "error": {
                    "code": "unsupported_python",
                    "message": (
                        "Lite Computer Use requires Python 3.11 or later. "
                        f"Current Python: {sys.version.split()[0]}"
                    ),
                    "details": {},
                },
            },
            separators=(",", ":"),
        )
    )
    raise SystemExit(2)

from helpers import (
    ActionLock,
    AppDefinition,
    AppRegistry,
    LCUError,
    append_action_log,
    known_folders,
    normalize_name,
    safe_log_details,
    search_entries,
)
from app_index import AppIndex

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "apps.yaml"
VERSION = "1.4.0"
MAX_SEQUENCE_CHARS = 100_000


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise LCUError(
            "invalid_arguments",
            message,
            stage="parse",
            retryable=False,
            nextAction="check_help",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        prog="lcu_tools",
        description="Small, JSON-speaking Windows primitives for AI coding agents.",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Print a traceback to stderr on failure"
    )
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG, help="Path to apps.yaml"
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    screenshot = subparsers.add_parser(
        "screenshot", help="Capture the desktop or active window"
    )
    screenshot.add_argument("--active-window", action="store_true")
    screenshot.add_argument("--all-screens", action="store_true")
    screenshot.add_argument(
        "--region",
        nargs=4,
        type=int,
        metavar=("X", "Y", "WIDTH", "HEIGHT"),
    )
    screenshot.add_argument("--output", type=Path)
    screenshot.add_argument("--delay", type=float, default=0.0)
    screenshot.add_argument("--scale", type=float, default=1.0)

    for action in ("click", "double_click"):
        click = subparsers.add_parser(action, aliases=[action.replace("_", "-")])
        click.add_argument("x", type=int)
        click.add_argument("y", type=int)
        click.add_argument(
            "--relative-to",
            choices=("screen", "active-window"),
            default="screen",
        )
        click.add_argument(
            "--button", choices=("left", "right", "middle"), default="left"
        )

    move_mouse = subparsers.add_parser("move_mouse", aliases=["move-mouse"])
    move_mouse.add_argument("x", type=int)
    move_mouse.add_argument("y", type=int)
    move_mouse.add_argument(
        "--relative-to",
        choices=("screen", "active-window"),
        default="screen",
    )

    drag = subparsers.add_parser("drag")
    drag.add_argument("start_x", type=int)
    drag.add_argument("start_y", type=int)
    drag.add_argument("end_x", type=int)
    drag.add_argument("end_y", type=int)
    drag.add_argument("--duration", type=float, default=0.5)
    drag.add_argument(
        "--button", choices=("left", "right", "middle"), default="left"
    )
    drag.add_argument(
        "--relative-to",
        choices=("screen", "active-window"),
        default="screen",
    )

    scroll = subparsers.add_parser("scroll")
    scroll.add_argument("amount", type=int, help="Positive is up; negative is down")

    type_text = subparsers.add_parser("type_text", aliases=["type-text"])
    type_text.add_argument("text")
    type_text.add_argument("--interval", type=float, default=0.0)
    _add_input_target(type_text)

    press_key = subparsers.add_parser("press_key", aliases=["press-key"])
    press_key.add_argument("key")
    press_key.add_argument("--count", type=int, default=1)
    _add_input_target(press_key)

    hotkey = subparsers.add_parser("hotkey")
    hotkey.add_argument("keys", nargs="+")
    _add_input_target(hotkey)

    launch_app = subparsers.add_parser("launch_app", aliases=["launch-app"])
    launch_app.add_argument("name")

    open_file = subparsers.add_parser("open_file", aliases=["open-file"])
    open_file.add_argument("path")

    open_folder = subparsers.add_parser("open_folder", aliases=["open-folder"])
    open_folder.add_argument("path")

    known_folder = subparsers.add_parser(
        "known_folder", aliases=["known-folder"], help="Resolve a Windows known folder"
    )
    known_folder.add_argument("name")
    known_folder.add_argument("--open", action="store_true", dest="open_folder")

    reveal_file = subparsers.add_parser("reveal_file", aliases=["reveal-file"])
    reveal_file.add_argument("path")

    open_url = subparsers.add_parser("open_url", aliases=["open-url"])
    open_url.add_argument("url")

    for command, aliases, kind in (
        ("find_file", ["find-file"], "file"),
        ("find_folder", ["find-folder"], "folder"),
    ):
        search = subparsers.add_parser(command, aliases=aliases)
        search.add_argument("query")
        search.add_argument("--root", action="append", type=Path)
        search.add_argument("--limit", type=int, default=20)
        search.add_argument("--max-depth", type=int, default=6)
        search.add_argument("--max-visited", type=int, default=20_000)
        search.add_argument("--timeout", type=float, default=3.0)
        search.add_argument("--include-ignored", action="store_true")
        search.set_defaults(search_kind=kind)

    subparsers.add_parser("list_windows", aliases=["list-windows"])
    subparsers.add_parser("get_active_window", aliases=["get-active-window"])

    focus_window = subparsers.add_parser("focus_window", aliases=["focus-window"])
    _add_window_target(focus_window)

    set_window_state = subparsers.add_parser(
        "set_window_state", aliases=["set-window-state"]
    )
    set_window_state.add_argument("title", nargs="?")
    set_window_state.add_argument(
        "state", nargs="?", choices=("restore", "minimize", "maximize")
    )
    set_window_state.add_argument("--hwnd", type=int)
    set_window_state.add_argument("--pid", type=int)
    set_window_state.add_argument(
        "--value", dest="state_option", choices=("restore", "minimize", "maximize")
    )

    set_window_bounds = subparsers.add_parser(
        "set_window_bounds", aliases=["set-window-bounds"]
    )
    set_window_bounds.add_argument("title", nargs="?")
    set_window_bounds.add_argument("x", nargs="?", type=int)
    set_window_bounds.add_argument("y", nargs="?", type=int)
    set_window_bounds.add_argument("width", nargs="?", type=int)
    set_window_bounds.add_argument("height", nargs="?", type=int)
    set_window_bounds.add_argument("--hwnd", type=int)
    set_window_bounds.add_argument("--pid", type=int)
    set_window_bounds.add_argument("--bounds", nargs=4, type=int)

    close_window = subparsers.add_parser("close_window", aliases=["close-window"])
    _add_window_target(close_window)

    wait_for_window = subparsers.add_parser(
        "wait_for_window", aliases=["wait-for-window"]
    )
    _add_window_target(wait_for_window)
    wait_for_window.add_argument(
        "--state", choices=("present", "gone", "active"), default="present"
    )
    wait_for_window.add_argument("--timeout", type=float, default=10.0)

    subparsers.add_parser("get_mouse_position", aliases=["get-mouse-position"])

    set_clipboard = subparsers.add_parser("set_clipboard", aliases=["set-clipboard"])
    set_clipboard.add_argument("text")
    subparsers.add_parser("get_clipboard", aliases=["get-clipboard"])

    list_apps = subparsers.add_parser("list_apps", aliases=["list-apps"])
    list_apps.add_argument("--refresh", action="store_true")

    sequence = subparsers.add_parser(
        "sequence", help="Run up to eight safe deterministic actions"
    )
    sequence_input = sequence.add_mutually_exclusive_group(required=True)
    sequence_input.add_argument("--json", dest="sequence_json")
    sequence_input.add_argument("--file", dest="sequence_file", type=Path)
    sequence_input.add_argument("--stdin", dest="sequence_stdin", action="store_true")

    subparsers.add_parser("doctor", help="Report runtime and dependency diagnostics")
    return parser


def _add_window_target(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("title", nargs="?")
    group.add_argument("--hwnd", type=int)
    parser.add_argument("--pid", type=int)


def _add_input_target(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--target")
    group.add_argument("--hwnd", type=int)
    parser.add_argument("--pid", type=int)


def normalized_action(action: str) -> str:
    return action.replace("-", "_")


def windows_backend(registry: AppRegistry | None = None) -> Any:
    if os.name != "nt":
        raise LCUError("unsupported_platform", "Lite Computer Use requires Windows")
    from windows_backend import WindowsBackend

    return WindowsBackend(app_registry=registry)


def direct_backend() -> Any:
    if os.name != "nt":
        raise LCUError("unsupported_platform", "Lite Computer Use requires Windows")
    from direct_backend import DirectWindowsBackend

    return DirectWindowsBackend()


def resolve_app(
    registry: AppRegistry, query: str, index: AppIndex | None = None
) -> AppDefinition:
    try:
        return registry.resolve(query)
    except LCUError as exc:
        if exc.code != "app_not_registered":
            raise
    return (index or AppIndex.load()).resolve(query)


def launch_app_resilient(
    backend: Any, registry: AppRegistry, query: str
) -> dict[str, Any]:
    try:
        configured = registry.resolve(query)
    except LCUError as exc:
        if exc.code != "app_not_registered":
            raise
        index = AppIndex.load()
        app = index.resolve(query)
        try:
            return backend.launch_app(app)
        except LCUError as launch_error:
            if (
                launch_error.code != "app_launch_failed"
                or not launch_error.details.get("notFoundOnly")
                or index.refreshed
            ):
                raise
            refreshed = AppIndex.load(refresh=True)
            return backend.launch_app(refreshed.resolve(query))

    try:
        return backend.launch_app(configured)
    except LCUError as launch_error:
        if (
            launch_error.code != "app_launch_failed"
            or not launch_error.details.get("notFoundOnly")
        ):
            raise
        # Only a definite not-found failure may fall back. Access denial or an
        # accepted Shell request must never fan out into multiple app launches.
        index = AppIndex.load()
        indexed = index.resolve_any(registry.lookup_terms_for(query))
        try:
            result = backend.launch_app(indexed)
        except LCUError as indexed_error:
            if (
                indexed_error.code != "app_launch_failed"
                or not indexed_error.details.get("notFoundOnly")
                or index.refreshed
            ):
                raise
            indexed = AppIndex.load(refresh=True).resolve_any(
                registry.lookup_terms_for(query)
            )
            result = backend.launch_app(indexed)
        result["fallbackFrom"] = "registry-not-found"
        return result


def _doctor(config: Path) -> dict[str, Any]:
    dependencies = {
        name: importlib.util.find_spec(name) is not None
        for name in ("yaml", "pyautogui", "PIL", "win32gui", "win32clipboard")
    }
    gui_ready = os.name == "nt" and all(dependencies.values())
    return {
        "version": VERSION,
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
            "supported": sys.version_info >= (3, 11),
        },
        "platform": {"system": platform.system(), "release": platform.release()},
        "runtime": {
            "projectRoot": str(PROJECT_ROOT),
            "scriptPath": str(Path(__file__).resolve()),
            "configPath": str(config.expanduser().resolve(strict=False)),
        },
        "dependencies": dependencies,
        "directActionsReady": os.name == "nt" and dependencies["yaml"],
        "guiActionsReady": gui_ready,
        "ready": gui_ready,
        "note": "Internal timing excludes Python process startup time",
    }


def run_action(args: argparse.Namespace) -> Any:
    action = normalized_action(args.action)
    sequence_text: str | None = None

    args.config = args.config.expanduser()
    if not args.config.is_absolute():
        raise LCUError(
            "relative_path_not_allowed",
            "App config path must be absolute",
            stage="validate_config",
            retryable=False,
            nextAction="provide_absolute_config_path",
        )

    if action == "sequence":
        sequence_text = read_sequence_input(args)
        parse_sequence(sequence_text)

    if action == "doctor":
        return _doctor(args.config)

    if action in {"find_file", "find_folder"}:
        root_sources: list[dict[str, Any]] | None = None
        if args.root is not None:
            roots = args.root
        else:
            folders = known_folders()
            root_sources = [
                {"name": name, **details}
                for name, details in folders.items()
                if details["exists"]
            ]
            roots = [Path(item["path"]) for item in root_sources]
        result = search_entries(
            args.query,
            roots,
            args.limit,
            kind=args.search_kind,
            max_depth=args.max_depth,
            max_visited=args.max_visited,
            timeout=args.timeout,
            include_ignored=args.include_ignored,
            strict_roots=args.root is not None,
        )
        response = {"query": args.query, "kind": args.search_kind, **result}
        if root_sources is not None:
            response["rootSources"] = root_sources
        return response

    if action in {"open_file", "open_folder", "reveal_file", "open_url", "known_folder"}:
        backend = direct_backend()
        if action == "known_folder":
            result = backend.known_folder(args.name)
            if args.open_folder:
                result["openResult"] = backend.open_folder(result["path"])
            return result
        value = args.url if action == "open_url" else args.path
        return getattr(backend, action)(value)

    registry: AppRegistry | None = None
    needs_registry = action in {
        "launch_app",
        "list_apps",
        "sequence",
        "focus_window",
        "wait_for_window",
        "set_window_state",
        "set_window_bounds",
        "close_window",
    } or (
        action in {"type_text", "press_key", "hotkey"}
        and getattr(args, "target", None) is not None
    )
    if needs_registry:
        registry = AppRegistry.load(args.config)
    if action == "list_apps":
        assert registry is not None
        registered_names = registry.names()
        configured = [
            {"name": definition.name, "configured": True, "installedVerified": False}
            for definition in registry.definitions()
        ]
        if os.name != "nt":
            return {
                "apps": registered_names,
                "configured": configured,
                "indexed": [],
                "registeredCount": len(registered_names),
                "indexedCount": 0,
                "cacheRefreshed": False,
            }
        index = AppIndex.load(refresh=args.refresh)
        for item, definition in zip(configured, registry.definitions(), strict=True):
            try:
                installed = index.resolve_any(
                    registry.lookup_terms_for(definition.name)
                )
            except LCUError:
                continue
            item.update(
                {
                    "installedVerified": True,
                    "indexedName": installed.name,
                    "indexedSource": installed.source,
                }
            )
        names_by_key = {normalize_name(name): name for name in registered_names}
        for indexed_app in index.apps:
            names_by_key.setdefault(indexed_app.normalized, indexed_app.name)
        names = sorted(names_by_key.values(), key=str.casefold)
        return {
            "apps": names,
            "configured": configured,
            "indexed": index.public_apps(),
            "registeredCount": len(registered_names),
            "indexedCount": len(index.apps),
            "cacheRefreshed": index.refreshed,
        }

    backend = windows_backend(registry)
    if action == "sequence":
        assert registry is not None
        assert sequence_text is not None
        return run_sequence(backend, sequence_text, registry)
    dispatch: dict[str, Callable[[], Any]] = {
        "screenshot": lambda: _screenshot(backend, args),
        "click": lambda: backend.click(
            args.x, args.y, args.relative_to, clicks=1, button=args.button
        ),
        "double_click": lambda: backend.click(
            args.x, args.y, args.relative_to, clicks=2, button=args.button
        ),
        "move_mouse": lambda: backend.move_mouse(args.x, args.y, args.relative_to),
        "drag": lambda: backend.drag(
            args.start_x,
            args.start_y,
            args.end_x,
            args.end_y,
            args.duration,
            args.button,
            args.relative_to,
        ),
        "scroll": lambda: backend.scroll(args.amount),
        "type_text": lambda: _targeted_input(
            backend, args, lambda: backend.type_text(args.text, args.interval)
        ),
        "press_key": lambda: _targeted_input(
            backend, args, lambda: backend.press_key(args.key, args.count)
        ),
        "hotkey": lambda: _targeted_input(
            backend, args, lambda: backend.hotkey(args.keys)
        ),
        "list_windows": backend.list_windows,
        "get_active_window": backend.active_window,
        "get_mouse_position": backend.get_mouse_position,
        "focus_window": lambda: backend.focus_window(args.title, args.hwnd, args.pid),
        "set_window_state": lambda: _set_window_state(backend, args),
        "set_window_bounds": lambda: _set_window_bounds(backend, args),
        "close_window": lambda: backend.close_window(args.title, args.hwnd, args.pid),
        "wait_for_window": lambda: backend.wait_for_window(
            args.title, args.state, args.timeout, args.hwnd, args.pid
        ),
        "set_clipboard": lambda: backend.set_clipboard(args.text),
        "get_clipboard": backend.get_clipboard,
    }
    if action == "launch_app":
        assert registry is not None
        return launch_app_resilient(backend, registry, args.name)
    try:
        callback = dispatch[action]
    except KeyError as exc:
        raise LCUError("unknown_action", f"Unknown action: {action}") from exc
    return callback()


def _targeted_input(
    backend: Any, args: argparse.Namespace, callback: Callable[[], Any]
) -> Any:
    return _with_verified_input_target(
        backend,
        getattr(args, "target", None),
        getattr(args, "hwnd", None),
        getattr(args, "pid", None),
        callback,
    )


def _with_verified_input_target(
    backend: Any,
    target: str | None,
    hwnd: int | None,
    pid: int | None,
    callback: Callable[[], Any],
) -> Any:
    verified: dict[str, Any] | None = None
    if target is not None or hwnd is not None:
        verified = backend.ensure_input_target(target, hwnd, pid)
    result = callback()
    if verified is not None and isinstance(result, dict):
        result = dict(result)
        result["target"] = {
            "hwnd": verified["hwnd"],
            "pid": verified.get("pid"),
            "foregroundVerified": True,
        }
    return result


def _validated_window_target(args: argparse.Namespace) -> tuple[str | None, int | None, int | None]:
    title = getattr(args, "title", None)
    hwnd = getattr(args, "hwnd", None)
    pid = getattr(args, "pid", None)
    if (title is None) == (hwnd is None):
        raise LCUError(
            "invalid_window_target",
            "Provide exactly one of a window title or --hwnd",
            stage="validate",
            retryable=False,
            nextAction="run_list_windows",
        )
    if title is not None and not title.strip():
        raise LCUError("invalid_window_query", "Window title query cannot be empty")
    if hwnd is not None and hwnd <= 0:
        raise LCUError("invalid_window_handle", "Window handle must be positive")
    if pid is not None and pid <= 0:
        raise LCUError("invalid_process_id", "Process ID must be positive")
    return title, hwnd, pid


def _set_window_state(backend: Any, args: argparse.Namespace) -> Any:
    title, hwnd, pid = _validated_window_target(args)
    state = args.state_option or args.state
    if state is None:
        raise LCUError("invalid_window_state", "Window state is required")
    return backend.set_window_state(title, state, hwnd, pid)


def _set_window_bounds(backend: Any, args: argparse.Namespace) -> Any:
    title, hwnd, pid = _validated_window_target(args)
    positional = (args.x, args.y, args.width, args.height)
    if args.bounds is not None and any(value is not None for value in positional):
        raise LCUError("invalid_window_bounds", "Use positional bounds or --bounds, not both")
    values = tuple(args.bounds) if args.bounds is not None else positional
    if any(value is None for value in values):
        raise LCUError("invalid_window_bounds", "Window x, y, width, and height are required")
    x, y, width, height = values
    return backend.set_window_bounds(title, x, y, width, height, hwnd, pid)


def read_sequence_input(args: argparse.Namespace) -> str:
    if args.sequence_json is not None:
        value = args.sequence_json
    elif args.sequence_file is not None:
        path = args.sequence_file.expanduser()
        if not path.is_absolute():
            raise LCUError(
                "relative_path_not_allowed",
                "Sequence file path must be absolute",
                stage="read_sequence",
                retryable=False,
            )
        try:
            if path.stat().st_size > MAX_SEQUENCE_CHARS * 4 + 4:
                raise LCUError(
                    "sequence_too_large",
                    f"Sequence JSON is limited to {MAX_SEQUENCE_CHARS} characters",
                )
            value = path.read_text(encoding="utf-8-sig")
        except FileNotFoundError as exc:
            raise LCUError("sequence_file_not_found", "Sequence file does not exist") from exc
        except UnicodeDecodeError as exc:
            raise LCUError("sequence_encoding_invalid", "Sequence file must be UTF-8") from exc
        except OSError as exc:
            raise LCUError(
                "sequence_file_read_failed",
                "Could not read sequence file",
                osError=getattr(exc, "winerror", None) or exc.errno,
            ) from exc
    else:
        value = sys.stdin.read(MAX_SEQUENCE_CHARS + 1)
    if len(value) > MAX_SEQUENCE_CHARS:
        raise LCUError(
            "sequence_too_large", f"Sequence JSON is limited to {MAX_SEQUENCE_CHARS} characters"
        )
    return value


SEQUENCE_FIELDS: dict[str, set[str]] = {
    "launch_app": {"action", "name"},
    "wait_for_window": {"action", "title", "hwnd", "pid", "state", "timeout"},
    "click": {"action", "x", "y", "relative_to", "button"},
    "move_mouse": {"action", "x", "y", "relative_to"},
    "focus_window": {"action", "title", "hwnd", "pid"},
    "hotkey": {"action", "keys", "target", "hwnd", "pid"},
    "press_key": {"action", "key", "count", "target", "hwnd", "pid"},
    "type_text": {"action", "text", "interval", "target", "hwnd", "pid"},
    "scroll": {"action", "amount"},
}


def parse_sequence(value: str) -> list[dict[str, Any]]:
    if len(value) > MAX_SEQUENCE_CHARS:
        raise LCUError(
            "sequence_too_large", "Sequence JSON is limited to 100,000 characters"
        )
    try:
        steps = json.loads(value)
    except json.JSONDecodeError as exc:
        raise LCUError(
            "invalid_sequence_json",
            "Sequence must be valid JSON",
            line=exc.lineno,
            column=exc.colno,
        ) from exc
    if not isinstance(steps, list):
        raise LCUError("invalid_sequence", "Sequence JSON must be an array")
    if not 1 <= len(steps) <= 8:
        raise LCUError(
            "invalid_sequence_length", "Sequence must contain between 1 and 8 actions"
        )

    validated: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise LCUError(
                "invalid_sequence_step",
                "Each sequence action must be an object",
                index=index,
            )
        raw_action = step.get("action")
        if not isinstance(raw_action, str):
            raise LCUError(
                "invalid_sequence_step",
                "Each sequence action needs a string action",
                index=index,
            )
        action = normalized_action(raw_action)
        allowed_fields = SEQUENCE_FIELDS.get(action)
        if allowed_fields is None:
            raise LCUError(
                "sequence_action_not_allowed",
                f"Action is not allowed in a sequence: {action}",
                index=index,
                action=action,
            )
        unknown_fields = sorted(set(step) - allowed_fields)
        if unknown_fields:
            raise LCUError(
                "invalid_sequence_step",
                "Sequence action contains unsupported fields",
                index=index,
                fields=unknown_fields,
            )
        normalized_step = dict(step)
        normalized_step["action"] = action
        _validate_sequence_step(normalized_step, index)
        validated.append(normalized_step)
    return validated


def _validate_sequence_step(step: dict[str, Any], index: int) -> None:
    action = step["action"]

    def require_string(name: str) -> None:
        if not isinstance(step.get(name), str):
            raise LCUError(
                "invalid_sequence_step",
                f"Sequence {action} requires string field: {name}",
                index=index,
            )

    if action == "launch_app":
        require_string("name")
        if not step["name"].strip():
            raise LCUError(
                "invalid_sequence_step",
                "Sequence launch_app name cannot be empty",
                index=index,
            )
    elif action in {"focus_window", "wait_for_window"}:
        title = step.get("title")
        hwnd = step.get("hwnd")
        if (title is None) == (hwnd is None):
            raise LCUError(
                "invalid_sequence_step",
                f"Sequence {action} requires exactly one of title or hwnd",
                index=index,
            )
        if title is not None and (not isinstance(title, str) or not title.strip()):
            raise LCUError(
                "invalid_sequence_step",
                f"Sequence {action} title must be a non-empty string",
                index=index,
            )
        if hwnd is not None and (isinstance(hwnd, bool) or not isinstance(hwnd, int) or hwnd <= 0):
            raise LCUError(
                "invalid_sequence_step",
                f"Sequence {action} hwnd must be a positive integer",
                index=index,
            )
        pid = step.get("pid")
        if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0):
            raise LCUError(
                "invalid_sequence_step",
                f"Sequence {action} pid must be a positive integer",
                index=index,
            )
        if action == "wait_for_window":
            state = step.get("state", "present")
            if state not in {"present", "gone", "active"}:
                raise LCUError(
                    "invalid_sequence_step",
                    "Sequence wait_for_window state is invalid",
                    index=index,
                )
            timeout = step.get("timeout", 10.0)
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                raise LCUError(
                    "invalid_sequence_step",
                    "Sequence wait_for_window timeout must be numeric",
                    index=index,
                )
            if not 0 < timeout <= 30:
                raise LCUError(
                    "invalid_sequence_step",
                    "Sequence wait_for_window timeout must be greater than 0 "
                    "and at most 30 seconds",
                    index=index,
                )
    elif action in {"click", "move_mouse"}:
        for coordinate in ("x", "y"):
            value = step.get(coordinate)
            if isinstance(value, bool) or not isinstance(value, int):
                raise LCUError(
                    "invalid_sequence_step",
                    f"Sequence {action} {coordinate} must be an integer",
                    index=index,
                )
        if step.get("relative_to", "screen") not in {"screen", "active-window"}:
            raise LCUError(
                "invalid_sequence_step",
                f"Sequence {action} relative_to is invalid",
                index=index,
            )
        if action == "click" and step.get("button", "left") not in {
            "left",
            "right",
            "middle",
        }:
            raise LCUError(
                "invalid_sequence_step",
                "Sequence click button is invalid",
                index=index,
            )
    elif action == "hotkey":
        _validate_input_target(step, index)
        keys = step.get("keys")
        if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
            raise LCUError(
                "invalid_sequence_step",
                "Sequence hotkey requires a string array: keys",
                index=index,
            )
        if not 2 <= len(keys) <= 5:
            raise LCUError(
                "invalid_sequence_step",
                "Sequence hotkey requires between 2 and 5 keys",
                index=index,
            )
    elif action == "press_key":
        _validate_input_target(step, index)
        require_string("key")
        count = step.get("count", 1)
        if isinstance(count, bool) or not isinstance(count, int):
            raise LCUError(
                "invalid_sequence_step",
                "Sequence press_key count must be an integer",
                index=index,
            )
        if not 1 <= count <= 100:
            raise LCUError(
                "invalid_sequence_step",
                "Sequence press_key count must be between 1 and 100",
                index=index,
            )
    elif action == "type_text":
        _validate_input_target(step, index)
        require_string("text")
        interval = step.get("interval", 0.0)
        if isinstance(interval, bool) or not isinstance(interval, (int, float)):
            raise LCUError(
                "invalid_sequence_step",
                "Sequence type_text interval must be numeric",
                index=index,
            )
        if not 0 <= interval <= 1:
            raise LCUError(
                "invalid_sequence_step",
                "Sequence type_text interval must be between 0 and 1 second",
                index=index,
            )
        if len(step["text"]) > 10_000:
            raise LCUError(
                "invalid_sequence_step",
                "Sequence type_text is limited to 10,000 characters",
                index=index,
            )
    elif action == "scroll":
        amount = step.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise LCUError(
                "invalid_sequence_step",
                "Sequence scroll amount must be an integer",
                index=index,
            )
        if amount == 0 or abs(amount) > 10_000:
            raise LCUError(
                "invalid_sequence_step",
                "Sequence scroll amount must be between -10000 and 10000, excluding 0",
                index=index,
            )


def _validate_input_target(step: dict[str, Any], index: int) -> None:
    target = step.get("target")
    hwnd = step.get("hwnd")
    if target is not None and hwnd is not None:
        raise LCUError(
            "invalid_sequence_step",
            "Input target and hwnd are mutually exclusive",
            index=index,
        )
    if target is not None and (not isinstance(target, str) or not target.strip()):
        raise LCUError(
            "invalid_sequence_step",
            "Input target must be a non-empty string",
            index=index,
        )
    if hwnd is not None and (isinstance(hwnd, bool) or not isinstance(hwnd, int) or hwnd <= 0):
        raise LCUError(
            "invalid_sequence_step",
            "Input hwnd must be a positive integer",
            index=index,
        )
    pid = step.get("pid")
    if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0):
        raise LCUError(
            "invalid_sequence_step",
            "Input pid must be a positive integer",
            index=index,
        )
    if pid is not None and target is None and hwnd is None:
        raise LCUError(
            "invalid_sequence_step",
            "Input pid requires target or hwnd",
            index=index,
        )


def run_sequence(
    backend: Any,
    sequence_json: str,
    registry: AppRegistry | None = None,
) -> dict[str, Any]:
    steps = parse_sequence(sequence_json)
    results: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        action = step["action"]
        try:
            if action == "launch_app":
                if registry is None:
                    raise LCUError(
                        "config_not_loaded",
                        "App registry is required for sequence launch_app",
                    )
                result = launch_app_resilient(backend, registry, step["name"])
            elif action == "wait_for_window":
                if step.get("hwnd") is None and step.get("pid") is None:
                    result = backend.wait_for_window(
                        step.get("title"),
                        step.get("state", "present"),
                        step.get("timeout", 10.0),
                    )
                else:
                    result = backend.wait_for_window(
                        step.get("title"),
                        step.get("state", "present"),
                        step.get("timeout", 10.0),
                        step.get("hwnd"),
                        step.get("pid"),
                    )
            elif action == "click":
                result = backend.click(
                    step["x"],
                    step["y"],
                    step.get("relative_to", "screen"),
                    clicks=1,
                    button=step.get("button", "left"),
                )
            elif action == "move_mouse":
                result = backend.move_mouse(
                    step["x"],
                    step["y"],
                    step.get("relative_to", "screen"),
                )
            elif action == "focus_window":
                if step.get("hwnd") is None and step.get("pid") is None:
                    result = backend.focus_window(step.get("title"))
                else:
                    result = backend.focus_window(
                        step.get("title"), step.get("hwnd"), step.get("pid")
                    )
            elif action == "hotkey":
                result = _with_verified_input_target(
                    backend,
                    step.get("target"),
                    step.get("hwnd"),
                    step.get("pid"),
                    lambda: backend.hotkey(step["keys"]),
                )
            elif action == "press_key":
                result = _with_verified_input_target(
                    backend,
                    step.get("target"),
                    step.get("hwnd"),
                    step.get("pid"),
                    lambda: backend.press_key(step["key"], step.get("count", 1)),
                )
            elif action == "type_text":
                result = _with_verified_input_target(
                    backend,
                    step.get("target"),
                    step.get("hwnd"),
                    step.get("pid"),
                    lambda: backend.type_text(
                        step["text"], step.get("interval", 0.0)
                    ),
                )
            elif action == "scroll":
                result = backend.scroll(step["amount"])
            else:  # pragma: no cover - parse_sequence guarantees this set.
                raise AssertionError(f"Unhandled sequence action: {action}")
        except LCUError as exc:
            raise LCUError(
                "sequence_failed",
                f"Sequence stopped at action index {index}",
                completed=len(results),
                failedIndex=index,
                failedAction=action,
                results=results,
                cause={
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
                partialEffectPossible=action
                in {"launch_app", "click", "move_mouse", "hotkey", "press_key", "type_text", "scroll"},
            ) from exc
        except Exception as exc:  # Preserve partial completion for ordinary OS errors.
            error_number = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
            raise LCUError(
                "sequence_failed",
                f"Sequence stopped at action index {index}",
                completed=len(results),
                failedIndex=index,
                failedAction=action,
                results=results,
                cause={
                    "code": "os_error" if isinstance(exc, OSError) else "unexpected_step_error",
                    "message": str(exc),
                    "details": {
                        "stage": "execute_step",
                        "osError": error_number,
                        "retryable": False,
                    },
                },
                partialEffectPossible=action
                in {"launch_app", "click", "move_mouse", "hotkey", "press_key", "type_text", "scroll"},
            ) from exc
        results.append({"index": index, "action": action, "result": result})
    return {"completed": len(results), "results": results}


def _screenshot(backend: Any, args: argparse.Namespace) -> Any:
    if not 0 <= args.delay <= 30:
        raise LCUError(
            "invalid_delay", "Screenshot delay must be between 0 and 30 seconds"
        )
    if args.delay:
        time.sleep(args.delay)
    return backend.screenshot(
        args.output,
        args.active_window,
        args.all_screens,
        args.region,
        args.scale,
    )


def action_arguments(args: argparse.Namespace) -> dict[str, Any]:
    result = vars(args).copy()
    result.pop("debug", None)
    result.pop("config", None)
    result["action"] = normalized_action(result["action"])
    return result


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    started = time.perf_counter()
    request_id = uuid.uuid4().hex[:12]
    args: argparse.Namespace | None = None
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    action = _action_hint(raw_argv)
    details: dict[str, Any] = {"requestId": request_id}
    try:
        parser = build_parser()
        args = parser.parse_args(raw_argv)
        action = normalized_action(args.action)
        details.update(safe_log_details(action, action_arguments(args)))
        if action in {"doctor", "find_file", "find_folder", "list_apps"}:
            result = run_action(args)
        else:
            with ActionLock():
                result = run_action(args)
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        append_action_log(action, True, details, duration_ms)
        emit(
            {
                "ok": True,
                "action": action,
                "result": result,
                "meta": {
                    "durationMs": duration_ms,
                    "requestId": request_id,
                    "timingScope": "argument-parse-through-result; excludes-python-startup",
                },
            }
        )
        return 0
    except LCUError as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        append_action_log(
            action, False, {**details, "error": exc.code}, duration_ms
        )
        error_details = exc.details
        payload: dict[str, Any] = {
            "ok": False,
            "action": action,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": error_details,
            },
            "meta": {
                "durationMs": duration_ms,
                "requestId": request_id,
                "timingScope": "argument-parse-through-error; excludes-python-startup",
            },
        }
        if action == "sequence" and exc.code == "sequence_failed":
            payload["result"] = {
                key: exc.details[key]
                for key in (
                    "completed",
                    "failedIndex",
                    "failedAction",
                    "results",
                    "partialEffectPossible",
                )
            }
            payload["error"]["details"] = {"cause": exc.details["cause"]}
        emit(payload)
        if args is not None and args.debug:
            traceback.print_exc(file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI boundary must always emit JSON.
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        append_action_log(
            action,
            False,
            {**details, "error": "unexpected_error"},
            duration_ms,
        )
        emit(
            {
                "ok": False,
                "action": action,
                "error": {
                    "code": "unexpected_error",
                    "message": str(exc),
                    "details": {},
                },
                "meta": {
                    "durationMs": duration_ms,
                    "requestId": request_id,
                    "timingScope": "argument-parse-through-error; excludes-python-startup",
                },
            }
        )
        if args is not None and args.debug:
            traceback.print_exc(file=sys.stderr)
        return 3


def _action_hint(argv: list[str]) -> str:
    value_options = {"--config"}
    skip_next = False
    for value in argv:
        if skip_next:
            skip_next = False
            continue
        if value in value_options:
            skip_next = True
            continue
        if value.startswith("-"):
            continue
        return normalized_action(value)
    return "startup"


if __name__ == "__main__":
    raise SystemExit(main())

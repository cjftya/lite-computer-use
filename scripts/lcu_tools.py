from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
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
    AppRegistry,
    LCUError,
    append_action_log,
    default_search_roots,
    find_files,
    safe_log_details,
)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "apps.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
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
    type_text.add_argument("--interval", type=float, default=0.01)

    press_key = subparsers.add_parser("press_key", aliases=["press-key"])
    press_key.add_argument("key")
    press_key.add_argument("--count", type=int, default=1)

    hotkey = subparsers.add_parser("hotkey")
    hotkey.add_argument("keys", nargs="+")

    launch_app = subparsers.add_parser("launch_app", aliases=["launch-app"])
    launch_app.add_argument("name")

    open_file = subparsers.add_parser("open_file", aliases=["open-file"])
    open_file.add_argument("path")

    open_folder = subparsers.add_parser("open_folder", aliases=["open-folder"])
    open_folder.add_argument("path")

    reveal_file = subparsers.add_parser("reveal_file", aliases=["reveal-file"])
    reveal_file.add_argument("path")

    open_url = subparsers.add_parser("open_url", aliases=["open-url"])
    open_url.add_argument("url")

    find_file = subparsers.add_parser("find_file", aliases=["find-file"])
    find_file.add_argument("query")
    find_file.add_argument("--limit", type=int, default=20)

    subparsers.add_parser("list_windows", aliases=["list-windows"])
    subparsers.add_parser("get_active_window", aliases=["get-active-window"])

    focus_window = subparsers.add_parser("focus_window", aliases=["focus-window"])
    focus_window.add_argument("title")

    set_window_state = subparsers.add_parser(
        "set_window_state", aliases=["set-window-state"]
    )
    set_window_state.add_argument("title")
    set_window_state.add_argument(
        "state", choices=("restore", "minimize", "maximize")
    )

    set_window_bounds = subparsers.add_parser(
        "set_window_bounds", aliases=["set-window-bounds"]
    )
    set_window_bounds.add_argument("title")
    set_window_bounds.add_argument("x", type=int)
    set_window_bounds.add_argument("y", type=int)
    set_window_bounds.add_argument("width", type=int)
    set_window_bounds.add_argument("height", type=int)

    close_window = subparsers.add_parser("close_window", aliases=["close-window"])
    close_window.add_argument("title")

    wait_for_window = subparsers.add_parser(
        "wait_for_window", aliases=["wait-for-window"]
    )
    wait_for_window.add_argument("title")
    wait_for_window.add_argument(
        "--state", choices=("present", "gone", "active"), default="present"
    )
    wait_for_window.add_argument("--timeout", type=float, default=10.0)

    subparsers.add_parser("get_mouse_position", aliases=["get-mouse-position"])

    set_clipboard = subparsers.add_parser("set_clipboard", aliases=["set-clipboard"])
    set_clipboard.add_argument("text")
    subparsers.add_parser("get_clipboard", aliases=["get-clipboard"])

    subparsers.add_parser("list_apps", aliases=["list-apps"])
    return parser


def normalized_action(action: str) -> str:
    return action.replace("-", "_")


def windows_backend() -> Any:
    if os.name != "nt":
        raise LCUError("unsupported_platform", "Lite Computer Use requires Windows")
    from windows_backend import WindowsBackend

    return WindowsBackend()


def run_action(args: argparse.Namespace) -> Any:
    action = normalized_action(args.action)

    if action == "find_file":
        roots = default_search_roots()
        return {
            "query": args.query,
            "roots": [str(root) for root in roots],
            "matches": find_files(args.query, roots, args.limit),
        }

    registry: AppRegistry | None = None
    if action in {"launch_app", "list_apps"}:
        registry = AppRegistry.load(args.config)
    if action == "list_apps":
        assert registry is not None
        return {"apps": registry.names()}

    backend = windows_backend()
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
        "type_text": lambda: backend.type_text(args.text, args.interval),
        "press_key": lambda: backend.press_key(args.key, args.count),
        "hotkey": lambda: backend.hotkey(args.keys),
        "open_file": lambda: backend.open_file(args.path),
        "open_folder": lambda: backend.open_folder(args.path),
        "reveal_file": lambda: backend.reveal_file(args.path),
        "open_url": lambda: backend.open_url(args.url),
        "list_windows": backend.list_windows,
        "get_active_window": backend.active_window,
        "get_mouse_position": backend.get_mouse_position,
        "focus_window": lambda: backend.focus_window(args.title),
        "set_window_state": lambda: backend.set_window_state(args.title, args.state),
        "set_window_bounds": lambda: backend.set_window_bounds(
            args.title, args.x, args.y, args.width, args.height
        ),
        "close_window": lambda: backend.close_window(args.title),
        "wait_for_window": lambda: backend.wait_for_window(
            args.title, args.state, args.timeout
        ),
        "set_clipboard": lambda: backend.set_clipboard(args.text),
        "get_clipboard": backend.get_clipboard,
    }
    if action == "launch_app":
        assert registry is not None
        return backend.launch_app(registry.resolve(args.name))
    try:
        callback = dispatch[action]
    except KeyError as exc:
        raise LCUError("unknown_action", f"Unknown action: {action}") from exc
    return callback()


def _screenshot(backend: Any, args: argparse.Namespace) -> Any:
    if not 0 <= args.delay <= 30:
        raise LCUError(
            "invalid_delay", "Screenshot delay must be between 0 and 30 seconds"
        )
    if args.delay:
        time.sleep(args.delay)
    return backend.screenshot(
        args.output, args.active_window, args.all_screens, args.region
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
    parser = build_parser()
    args = parser.parse_args(argv)
    action = normalized_action(args.action)
    details = safe_log_details(action, action_arguments(args))
    try:
        with ActionLock():
            result = run_action(args)
        append_action_log(action, True, details)
        emit({"ok": True, "action": action, "result": result})
        return 0
    except LCUError as exc:
        append_action_log(action, False, {**details, "error": exc.code})
        emit(
            {
                "ok": False,
                "action": action,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
            }
        )
        if args.debug:
            traceback.print_exc(file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI boundary must always emit JSON.
        append_action_log(action, False, {**details, "error": "unexpected_error"})
        emit(
            {
                "ok": False,
                "action": action,
                "error": {
                    "code": "unexpected_error",
                    "message": str(exc),
                    "details": {},
                },
            }
        )
        if args.debug:
            traceback.print_exc(file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

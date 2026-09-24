from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# Ensure project scripts directory is on sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lcu import apps, batch, capture, direct, launch_context, windows
from lcu.errors import LCUError, format_error, format_success, output_json


def require_input_desktop() -> None:
    attachment = launch_context.get_input_desktop_status()
    if attachment["attached"] is not True:
        raise LCUError(
            "desktop_unavailable",
            "This CLI is not attached to the Windows input desktop; run open_app from an interactive desktop host",
            details={**attachment, "dispatch_accepted": False, "retry_launch_allowed": False},
        )


def run_doctor() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    ok = True

    # 1. OS check
    is_windows = (os.name == "nt")
    checks["os_windows"] = is_windows
    if not is_windows:
        ok = False

    # 2. Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks["python_version"] = py_ver
    checks["python_version_ok"] = sys.version_info >= (3, 11)
    if not checks["python_version_ok"]:
        ok = False

    # 3. Dependencies
    deps: dict[str, bool] = {}
    for mod in ("PIL", "pyautogui", "win32gui", "win32con", "yaml"):
        try:
            __import__(mod)
            deps[mod] = True
        except ImportError:
            deps[mod] = False
            ok = False
    checks["dependencies"] = deps

    # Runtime provenance: useful when multiple installed skill copies exist.
    entrypoint = Path(__file__).resolve()
    apps_module = Path(apps.__file__).resolve()
    checks["runtime"] = {
        "python": sys.executable,
        "entrypoint": str(entrypoint),
        "entrypoint_sha256": hashlib.sha256(entrypoint.read_bytes()).hexdigest(),
        "apps_module": str(apps_module),
        "apps_module_sha256": hashlib.sha256(apps_module.read_bytes()).hexdigest(),
        "app_index": apps.get_app_index_diagnostics(),
    }

    # 4. Desktop attach
    capture.init_windows_environment()
    checks["dpi_initialized"] = True

    # 5. Temp cache dir
    try:
        temp_dir = Path(tempfile.gettempdir()) / "LiteComputerUse"
        temp_dir.mkdir(parents=True, exist_ok=True)
        test_file = temp_dir / ".test"
        test_file.write_text("ok")
        test_file.unlink()
        checks["temp_storage_ok"] = True
    except Exception as exc:
        checks["temp_storage_ok"] = False
        checks["temp_error"] = str(exc)
        ok = False

    return {
        "ok": ok,
        "action": "doctor",
        "result": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="lcu",
        description="Lite Computer Use v2 - Precise Windows Tool Layer for AI Agents",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    # 3.1 Open / Find
    p_open_app = subparsers.add_parser("open_app")
    p_open_app.add_argument("name", help="App name or alias")
    p_open_app.add_argument("--debug", action="store_true", help="Include launch timing and context diagnostics")

    p_app_status = subparsers.add_parser("app_status")
    p_app_status.add_argument("attempt_id", help="Attempt id returned by open_app")
    p_app_status.add_argument("--timeout", type=float, default=0.0, help="Observe for up to 30 seconds without launching")

    p_open_file = subparsers.add_parser("open_file")
    p_open_file.add_argument("path", help="Absolute path to file")

    p_open_folder = subparsers.add_parser("open_folder")
    p_open_folder.add_argument("path", help="Absolute path or alias (desktop, downloads, documents, etc.)")

    p_open_url = subparsers.add_parser("open_url")
    p_open_url.add_argument("url", help="http or https URL")

    p_reveal_file = subparsers.add_parser("reveal_file")
    p_reveal_file.add_argument("path", help="Absolute path to file to reveal in Explorer")

    p_find_path = subparsers.add_parser("find_path")
    p_find_path.add_argument("query", help="Query string to search for")
    p_find_path.add_argument("--root", required=True, help="Root folder path or alias")
    p_find_path.add_argument("--kind", choices=["any", "file", "folder"], default="any", help="Match kind")
    p_find_path.add_argument("--limit", type=int, default=10, help="Max results")
    p_find_path.add_argument("--max-depth", type=int, default=5, help="Max recursion depth")
    p_find_path.add_argument("--timeout", type=float, default=3.0, help="Timeout in seconds")

    # 3.2 Window
    p_list_windows = subparsers.add_parser("list_windows")
    p_list_windows.add_argument("--query", "-q", default=None, help="Filter by title or process")

    p_focus_window = subparsers.add_parser("focus_window")
    p_focus_window.add_argument("query", nargs="?", default=None, help="Window title query")
    p_focus_window.add_argument("--hwnd", type=int, default=None, help="Window handle")

    p_close_window = subparsers.add_parser("close_window")
    p_close_window.add_argument("query", nargs="?", default=None, help="Window title query")
    p_close_window.add_argument("--hwnd", type=int, default=None, help="Window handle")
    p_close_window.add_argument("--owned-processes", default=None, help="JSON string or file path containing owned process metadata to clean up")

    p_set_window_bounds = subparsers.add_parser("set_window_bounds")
    p_set_window_bounds.add_argument("--x", type=int, required=True, help="Left position")
    p_set_window_bounds.add_argument("--y", type=int, required=True, help="Top position")
    p_set_window_bounds.add_argument("--width", type=int, required=True, help="Window width")
    p_set_window_bounds.add_argument("--height", type=int, required=True, help="Window height")
    p_set_window_bounds.add_argument("--hwnd", type=int, default=None, help="Window handle")
    p_set_window_bounds.add_argument("--query", "-q", default=None, help="Window query")

    # 3.3 Vision
    p_screenshot = subparsers.add_parser("screenshot")
    p_screenshot.add_argument(
        "--target",
        choices=["active-window", "screen", "window"],
        default="active-window",
        help="Capture target",
    )
    p_screenshot.add_argument("--hwnd", type=int, default=None, help="Target window hwnd if target is window")
    p_screenshot.add_argument(
        "--region",
        nargs=4,
        type=int,
        metavar=("X", "Y", "WIDTH", "HEIGHT"),
        default=None,
        help="Region bounds relative to target",
    )
    p_screenshot.add_argument(
        "--quality",
        choices=["fast", "normal", "detail"],
        default="normal",
        help="Capture quality preset",
    )
    p_screenshot.add_argument("--from-capture", default=None, help="Capture ID to crop and recapture from")
    p_screenshot.add_argument("--output", type=Path, default=None, help="Optional custom output path")

    # 3.4 Mouse
    p_click = subparsers.add_parser("click")
    p_click.add_argument("x", type=int, help="X coordinate")
    p_click.add_argument("y", type=int, help="Y coordinate")
    p_click.add_argument("--capture", "-c", default=None, help="Capture ID if coordinates are from capture image")
    p_click.add_argument("--button", choices=["left", "right", "middle"], default="left", help="Mouse button")
    p_click.add_argument("--count", type=int, choices=[1, 2], default=1, help="Click count (1 or 2)")

    p_move_mouse = subparsers.add_parser("move_mouse")
    p_move_mouse.add_argument("x", type=int, help="X coordinate")
    p_move_mouse.add_argument("y", type=int, help="Y coordinate")
    p_move_mouse.add_argument("--capture", "-c", default=None, help="Capture ID")

    p_drag = subparsers.add_parser("drag")
    p_drag.add_argument("sx", type=int, help="Start X")
    p_drag.add_argument("sy", type=int, help="Start Y")
    p_drag.add_argument("ex", type=int, help="End X")
    p_drag.add_argument("ey", type=int, help="End Y")
    p_drag.add_argument("--capture", "-c", default=None, help="Capture ID")
    p_drag.add_argument("--duration", type=float, default=0.2, help="Drag duration in seconds")

    p_scroll = subparsers.add_parser("scroll")
    p_scroll.add_argument("amount", type=int, help="Scroll amount (positive=up, negative=down)")

    p_get_mouse_position = subparsers.add_parser("get_mouse_position")

    # 3.5 Keyboard
    p_type_text = subparsers.add_parser("type_text")
    p_type_text.add_argument("text", help="Text to type")
    p_type_text.add_argument("--hwnd", type=int, default=None, help="Verify target window is foreground")

    p_press_key = subparsers.add_parser("press_key")
    p_press_key.add_argument("key", help="Key name (ENTER, TAB, ESC, etc.)")
    p_press_key.add_argument("--count", type=int, default=1, help="Key press count")
    p_press_key.add_argument("--hwnd", type=int, default=None, help="Verify target window is foreground")

    p_hotkey = subparsers.add_parser("hotkey")
    p_hotkey.add_argument("keys", nargs="+", help="Keys to press simultaneously (e.g. CTRL SHIFT S)")
    p_hotkey.add_argument("--hwnd", type=int, default=None, help="Verify target window is foreground")

    p_set_clip = subparsers.add_parser("set_clipboard")
    p_set_clip.add_argument("text", help="Text to copy to clipboard")

    p_get_clip = subparsers.add_parser("get_clipboard")

    # 3.6 Batch
    p_batch = subparsers.add_parser("batch")
    p_batch.add_argument("payload", help="JSON array string or path to JSON file")

    # Diagnostics
    p_doctor = subparsers.add_parser("doctor")
    p_launch_context = subparsers.add_parser("launch_context")

    # Parse arguments
    try:
        args = parser.parse_args()
    except SystemExit:
        # Avoid printing default argparse exit when called directly
        return

    action = args.action
    try:
        if action == "doctor":
            res = run_doctor()
            print(output_json(res))
            if not res["ok"]:
                sys.exit(1)
            return

        elif action == "launch_context":
            res = launch_context.get_launch_context_snapshot()
            print(output_json(format_success("launch_context", res)))

        elif action == "open_app":
            require_input_desktop()
            res = apps.open_app(args.name, debug=args.debug)
            print(output_json(format_success("open_app", res)))

        elif action == "app_status":
            if args.timeout < 0 or args.timeout > 30:
                raise LCUError("invalid_arguments", "app_status --timeout must be between 0 and 30 seconds")
            res = apps.app_status(args.attempt_id, timeout=args.timeout)
            print(output_json(format_success("app_status", res)))

        elif action == "open_file":
            res = direct.open_file(args.path)
            print(output_json(format_success("open_file", res)))

        elif action == "open_folder":
            res = direct.open_folder(args.path)
            print(output_json(format_success("open_folder", res)))

        elif action == "open_url":
            res = direct.open_url(args.url)
            print(output_json(format_success("open_url", res)))

        elif action == "reveal_file":
            res = direct.reveal_file(args.path)
            print(output_json(format_success("reveal_file", res)))

        elif action == "find_path":
            res = direct.find_path(
                query=args.query,
                root=args.root,
                kind=args.kind,
                limit=args.limit,
                max_depth=args.max_depth,
                timeout=args.timeout,
            )
            print(output_json(format_success("find_path", res)))

        elif action == "list_windows":
            res = windows.list_windows(query=args.query)
            print(output_json(format_success("list_windows", {"windows": res, "count": len(res)})))

        elif action == "focus_window":
            res = windows.focus_window(query=args.query, hwnd=args.hwnd)
            print(output_json(format_success("focus_window", res)))

        elif action == "close_window":
            owned_procs = None
            if getattr(args, "owned_processes", None):
                raw_owned = args.owned_processes.strip()
                if raw_owned.startswith("[") or raw_owned.startswith("{"):
                    data = json.loads(raw_owned)
                else:
                    data = json.loads(Path(raw_owned).read_text(encoding="utf-8"))
                if isinstance(data, list):
                    owned_procs = data
                elif isinstance(data, dict):
                    owned_procs = [data]

            res = windows.close_window(
                query=args.query,
                hwnd=args.hwnd,
                owned_processes=owned_procs,
            )
            print(output_json(format_success("close_window", res)))

        elif action == "set_window_bounds":
            res = windows.set_window_bounds(
                x=args.x,
                y=args.y,
                width=args.width,
                height=args.height,
                hwnd=args.hwnd,
                query=args.query,
            )
            print(output_json(format_success("set_window_bounds", res)))

        elif action == "screenshot":
            res = capture.capture_screenshot(
                target=args.target,
                hwnd=args.hwnd,
                region=args.region,
                quality=args.quality,
                from_capture=args.from_capture,
                output_path=args.output,
            )
            print(output_json(format_success("screenshot", res)))

        elif action == "click":
            res = windows.click(
                x=args.x,
                y=args.y,
                button=args.button,
                count=args.count,
                capture_id=args.capture,
            )
            print(output_json(format_success("click", res)))

        elif action == "move_mouse":
            res = windows.move_mouse(x=args.x, y=args.y, capture_id=args.capture)
            print(output_json(format_success("move_mouse", res)))

        elif action == "drag":
            res = windows.drag(
                sx=args.sx,
                sy=args.sy,
                ex=args.ex,
                ey=args.ey,
                capture_id=args.capture,
                duration=args.duration,
            )
            print(output_json(format_success("drag", res)))

        elif action == "scroll":
            res = windows.scroll(args.amount)
            print(output_json(format_success("scroll", res)))

        elif action == "get_mouse_position":
            res = windows.get_mouse_position()
            print(output_json(format_success("get_mouse_position", res)))

        elif action == "type_text":
            res = windows.type_text(args.text, hwnd=args.hwnd)
            print(output_json(format_success("type_text", res)))

        elif action == "press_key":
            res = windows.press_key(args.key, count=args.count, hwnd=args.hwnd)
            print(output_json(format_success("press_key", res)))

        elif action == "hotkey":
            res = windows.hotkey(args.keys, hwnd=args.hwnd)
            print(output_json(format_success("hotkey", res)))

        elif action == "set_clipboard":
            res = windows.set_clipboard(args.text)
            print(output_json(format_success("set_clipboard", res)))

        elif action == "get_clipboard":
            res = windows.get_clipboard()
            print(output_json(format_success("get_clipboard", res)))

        elif action == "batch":
            payload_str = args.payload.strip()
            if payload_str.startswith("[") or payload_str.startswith("{"):
                raw_data = json.loads(payload_str)
            else:
                payload_file = Path(payload_str)
                if not payload_file.is_file():
                    raise LCUError("invalid_arguments", f"Batch payload file not found: {payload_str}")
                with open(payload_file, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)

            if isinstance(raw_data, dict) and "actions" in raw_data:
                actions_list = raw_data["actions"]
            elif isinstance(raw_data, list):
                actions_list = raw_data
            else:
                raise LCUError("invalid_arguments", "Batch payload must be a JSON array or an object with 'actions'")

            if any(isinstance(item, dict) and item.get("action") == "open_app" for item in actions_list):
                require_input_desktop()
            res = batch.execute_batch(actions_list)
            print(output_json(res))
            if not res["ok"]:
                sys.exit(1)

    except Exception as exc:
        err_payload = format_error(action, exc)
        print(output_json(err_payload))
        sys.exit(1)


if __name__ == "__main__":
    main()

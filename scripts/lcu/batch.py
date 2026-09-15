from __future__ import annotations

import time
from typing import Any

from . import apps, direct, windows
from .errors import LCUError

MAX_BATCH_ACTIONS = 12

ALLOWED_BATCH_ACTIONS = {
    "open_app",
    "open_file",
    "open_folder",
    "open_url",
    "reveal_file",
    "focus_window",
    "close_window",
    "set_window_bounds",
    "click",
    "move_mouse",
    "drag",
    "scroll",
    "type_text",
    "press_key",
    "hotkey",
    "set_clipboard",
}

DISALLOWED_BATCH_ACTIONS = {
    "screenshot",
    "find_path",
    "list_windows",
    "get_clipboard",
    "get_mouse_position",
    "doctor",
}


def _validate_single_action_schema(idx: int, item: dict[str, Any]) -> None:
    action = item.get("action")

    if action == "open_app":
        name = item.get("name") if "name" in item else item.get("app")
        if not name or not isinstance(name, str) or not name.strip():
            raise LCUError("invalid_arguments", f"Batch action 'open_app' at index {idx} requires non-empty 'name' or 'app'")

    elif action == "open_file":
        path = item.get("path")
        if not path or not isinstance(path, str) or not path.strip():
            raise LCUError("invalid_arguments", f"Batch action 'open_file' at index {idx} requires non-empty 'path'")

    elif action == "open_folder":
        folder = item.get("path") if "path" in item else item.get("folder")
        if not folder or not isinstance(folder, str) or not folder.strip():
            raise LCUError("invalid_arguments", f"Batch action 'open_folder' at index {idx} requires non-empty 'path' or 'folder'")

    elif action == "open_url":
        url = item.get("url")
        if not url or not isinstance(url, str) or not url.strip():
            raise LCUError("invalid_arguments", f"Batch action 'open_url' at index {idx} requires non-empty 'url'")
        url_lower = url.strip().lower()
        if not (url_lower.startswith("http://") or url_lower.startswith("https://")):
            raise LCUError("invalid_arguments", f"Batch action 'open_url' at index {idx} requires http:// or https:// URL: {url}")

    elif action == "reveal_file":
        path = item.get("path")
        if not path or not isinstance(path, str) or not path.strip():
            raise LCUError("invalid_arguments", f"Batch action 'reveal_file' at index {idx} requires non-empty 'path'")

    elif action in ("focus_window", "close_window"):
        query = item.get("query")
        hwnd = item.get("hwnd")
        if query is None and hwnd is None:
            raise LCUError("invalid_arguments", f"Batch action '{action}' at index {idx} requires 'query' or 'hwnd'")
        if hwnd is not None and not isinstance(hwnd, int):
            raise LCUError("invalid_arguments", f"Batch action '{action}' at index {idx} 'hwnd' must be an integer")
        if query is not None and (not isinstance(query, str) or not query.strip()):
            raise LCUError("invalid_arguments", f"Batch action '{action}' at index {idx} 'query' must be a non-empty string")

    elif action == "set_window_bounds":
        for field in ("x", "y", "width", "height"):
            if field not in item or not isinstance(item[field], (int, float)):
                raise LCUError("invalid_arguments", f"Batch action 'set_window_bounds' at index {idx} requires numeric '{field}'")
        if int(item["width"]) < 50 or int(item["height"]) < 50:
            raise LCUError("invalid_arguments", f"Batch action 'set_window_bounds' at index {idx} width and height must be >= 50px")
        if item.get("hwnd") is None and item.get("query") is None:
            raise LCUError("invalid_arguments", f"Batch action 'set_window_bounds' at index {idx} requires 'hwnd' or 'query'")

    elif action == "click":
        if "x" not in item or "y" not in item or not isinstance(item["x"], (int, float)) or not isinstance(item["y"], (int, float)):
            raise LCUError("invalid_arguments", f"Batch action 'click' at index {idx} requires numeric 'x' and 'y'")
        button = item.get("button", "left")
        if button not in ("left", "right", "middle"):
            raise LCUError("invalid_arguments", f"Batch action 'click' at index {idx} invalid button: '{button}'")
        count = item.get("count", 1)
        if count not in (1, 2):
            raise LCUError("invalid_arguments", f"Batch action 'click' at index {idx} invalid click count: {count} (must be 1 or 2)")

    elif action == "move_mouse":
        if "x" not in item or "y" not in item or not isinstance(item["x"], (int, float)) or not isinstance(item["y"], (int, float)):
            raise LCUError("invalid_arguments", f"Batch action 'move_mouse' at index {idx} requires numeric 'x' and 'y'")

    elif action == "drag":
        sx = item.get("sx", item.get("from_x"))
        sy = item.get("sy", item.get("from_y"))
        ex = item.get("ex", item.get("to_x"))
        ey = item.get("ey", item.get("to_y"))
        if None in (sx, sy, ex, ey) or not all(isinstance(v, (int, float)) for v in (sx, sy, ex, ey)):
            raise LCUError(
                "invalid_arguments",
                f"Batch action 'drag' at index {idx} requires numeric coordinates (sx, sy, ex, ey)",
            )
        duration = item.get("duration", 0.2)
        if not isinstance(duration, (int, float)) or duration < 0:
            raise LCUError("invalid_arguments", f"Batch action 'drag' at index {idx} duration must be non-negative")

    elif action == "scroll":
        if "amount" not in item or not isinstance(item["amount"], (int, float)):
            raise LCUError("invalid_arguments", f"Batch action 'scroll' at index {idx} requires numeric 'amount'")

    elif action == "type_text":
        if "text" not in item or not isinstance(item["text"], str):
            raise LCUError("invalid_arguments", f"Batch action 'type_text' at index {idx} requires string 'text'")

    elif action == "press_key":
        key = item.get("key")
        if not key or not isinstance(key, str) or not key.strip():
            raise LCUError("invalid_arguments", f"Batch action 'press_key' at index {idx} requires non-empty string 'key'")
        count = item.get("count", 1)
        if not isinstance(count, int) or count < 1:
            raise LCUError("invalid_arguments", f"Batch action 'press_key' at index {idx} 'count' must be integer >= 1")

    elif action == "hotkey":
        keys_val = item.get("keys")
        if not keys_val:
            raise LCUError("invalid_arguments", f"Batch action 'hotkey' at index {idx} requires non-empty 'keys'")
        if isinstance(keys_val, str):
            if not keys_val.strip():
                raise LCUError("invalid_arguments", f"Batch action 'hotkey' at index {idx} 'keys' cannot be empty")
        elif isinstance(keys_val, list):
            if len(keys_val) == 0:
                raise LCUError("invalid_arguments", f"Batch action 'hotkey' at index {idx} 'keys' list cannot be empty")
        else:
            raise LCUError("invalid_arguments", f"Batch action 'hotkey' at index {idx} 'keys' must be a string or list of strings")

    elif action == "set_clipboard":
        if "text" not in item or not isinstance(item["text"], str):
            raise LCUError("invalid_arguments", f"Batch action 'set_clipboard' at index {idx} requires string 'text'")


def validate_batch_actions(actions: list[Any]) -> None:
    if not isinstance(actions, list):
        raise LCUError("invalid_arguments", "Batch actions payload must be a list of action objects")

    if len(actions) == 0:
        raise LCUError("invalid_arguments", "Batch actions list cannot be empty")

    if len(actions) > MAX_BATCH_ACTIONS:
        raise LCUError(
            "invalid_arguments",
            f"Batch contains {len(actions)} actions, which exceeds maximum of {MAX_BATCH_ACTIONS}",
        )

    for idx, item in enumerate(actions):
        if not isinstance(item, dict):
            raise LCUError("invalid_arguments", f"Batch item at index {idx} must be a JSON object")

        action_name = item.get("action")
        if not action_name or not isinstance(action_name, str):
            raise LCUError("invalid_arguments", f"Batch item at index {idx} missing 'action' field")

        if action_name in DISALLOWED_BATCH_ACTIONS:
            raise LCUError(
                "invalid_arguments",
                f"Action '{action_name}' is an observation tool and cannot be used inside batch",
            )

        if action_name not in ALLOWED_BATCH_ACTIONS:
            raise LCUError("invalid_arguments", f"Unknown or unsupported batch action: '{action_name}'")

        delay = item.get("delay_after", 0.0)
        if not isinstance(delay, (int, float)):
            raise LCUError("invalid_arguments", f"delay_after at index {idx} must be a number")
        if delay < 0.0 or delay > 5.0:
            raise LCUError(
                "invalid_arguments",
                f"delay_after at index {idx} must be between 0.0 and 5.0 seconds (got {delay})",
            )

        # Full per-action schema validation upfront
        _validate_single_action_schema(idx, item)


def execute_single_action(item: dict[str, Any]) -> None:
    action = item["action"]

    if action == "open_app":
        name = item.get("name") if "name" in item else item.get("app")
        apps.open_app(name=str(name))

    elif action == "open_file":
        path = item.get("path")
        direct.open_file(str(path))

    elif action == "open_folder":
        folder = item.get("path") if "path" in item else item.get("folder")
        direct.open_folder(str(folder))

    elif action == "open_url":
        url = item.get("url")
        direct.open_url(str(url))

    elif action == "reveal_file":
        path = item.get("path")
        direct.reveal_file(str(path))

    elif action == "focus_window":
        windows.focus_window(query=item.get("query"), hwnd=item.get("hwnd"))

    elif action == "close_window":
        windows.close_window(query=item.get("query"), hwnd=item.get("hwnd"))

    elif action == "set_window_bounds":
        windows.set_window_bounds(
            x=int(item["x"]),
            y=int(item["y"]),
            width=int(item["width"]),
            height=int(item["height"]),
            hwnd=item.get("hwnd"),
            query=item.get("query"),
        )

    elif action == "click":
        button = item.get("button", "left")
        count = int(item.get("count", 1))
        capture_id = item.get("capture")
        windows.click(x=int(item["x"]), y=int(item["y"]), button=button, count=count, capture_id=capture_id)

    elif action == "move_mouse":
        capture_id = item.get("capture")
        windows.move_mouse(x=int(item["x"]), y=int(item["y"]), capture_id=capture_id)

    elif action == "drag":
        sx = item.get("sx", item.get("from_x"))
        sy = item.get("sy", item.get("from_y"))
        ex = item.get("ex", item.get("to_x"))
        ey = item.get("ey", item.get("to_y"))
        capture_id = item.get("capture")
        duration = float(item.get("duration", 0.2))
        windows.drag(
            sx=int(sx),
            sy=int(sy),
            ex=int(ex),
            ey=int(ey),
            capture_id=capture_id,
            duration=duration,
        )

    elif action == "scroll":
        windows.scroll(amount=int(item["amount"]))

    elif action == "type_text":
        windows.type_text(text=str(item["text"]), hwnd=item.get("hwnd"))

    elif action == "press_key":
        count = int(item.get("count", 1))
        windows.press_key(key=str(item["key"]), count=count, hwnd=item.get("hwnd"))

    elif action == "hotkey":
        keys_val = item.get("keys")
        if isinstance(keys_val, str):
            keys = keys_val.split()
        else:
            keys = [str(k) for k in keys_val]
        windows.hotkey(keys=keys, hwnd=item.get("hwnd"))

    elif action == "set_clipboard":
        windows.set_clipboard(text=str(item["text"]))

    else:
        raise LCUError("invalid_arguments", f"Unhandled action: {action}")


def execute_batch(actions: list[dict[str, Any]]) -> dict[str, Any]:
    # 1. Full schema validation upfront
    validate_batch_actions(actions)

    completed = 0
    # 2. Sequential execution with fail-fast
    for idx, item in enumerate(actions):
        action_name = item["action"]
        try:
            execute_single_action(item)
            completed += 1
            delay = float(item.get("delay_after", 0.0))
            if delay > 0:
                time.sleep(delay)
        except Exception as exc:
            err_dict: dict[str, Any]
            if isinstance(exc, LCUError):
                err_dict = exc.to_dict()
            else:
                err_dict = {"code": "batch_failed", "message": str(exc)}
            return {
                "ok": False,
                "action": "batch",
                "result": {
                    "completed": completed,
                    "failedIndex": idx,
                    "failedAction": action_name,
                },
                "error": err_dict,
            }

    return {
        "ok": True,
        "action": "batch",
        "result": {
            "completed": completed,
        },
    }

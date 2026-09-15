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


def execute_single_action(item: dict[str, Any]) -> None:
    action = item["action"]

    if action == "open_app":
        name = item.get("name") or item.get("app")
        if not name:
            raise LCUError("invalid_arguments", "open_app requires 'name' or 'app'")
        apps.open_app(name=str(name))

    elif action == "open_file":
        path = item.get("path")
        if not path:
            raise LCUError("invalid_arguments", "open_file requires 'path'")
        direct.open_file(str(path))

    elif action == "open_folder":
        folder = item.get("path") or item.get("folder")
        if not folder:
            raise LCUError("invalid_arguments", "open_folder requires 'path' or 'folder'")
        direct.open_folder(str(folder))

    elif action == "open_url":
        url = item.get("url")
        if not url:
            raise LCUError("invalid_arguments", "open_url requires 'url'")
        direct.open_url(str(url))

    elif action == "reveal_file":
        path = item.get("path")
        if not path:
            raise LCUError("invalid_arguments", "reveal_file requires 'path'")
        direct.reveal_file(str(path))

    elif action == "focus_window":
        windows.focus_window(query=item.get("query"), hwnd=item.get("hwnd"))

    elif action == "close_window":
        windows.close_window(query=item.get("query"), hwnd=item.get("hwnd"))

    elif action == "set_window_bounds":
        for field in ("x", "y", "width", "height"):
            if field not in item:
                raise LCUError("invalid_arguments", f"set_window_bounds requires '{field}'")
        windows.set_window_bounds(
            x=int(item["x"]),
            y=int(item["y"]),
            width=int(item["width"]),
            height=int(item["height"]),
            hwnd=item.get("hwnd"),
            query=item.get("query"),
        )

    elif action == "click":
        if "x" not in item or "y" not in item:
            raise LCUError("invalid_arguments", "click requires 'x' and 'y'")
        button = item.get("button", "left")
        count = int(item.get("count", 1))
        capture_id = item.get("capture")
        windows.click(x=int(item["x"]), y=int(item["y"]), button=button, count=count, capture_id=capture_id)

    elif action == "move_mouse":
        if "x" not in item or "y" not in item:
            raise LCUError("invalid_arguments", "move_mouse requires 'x' and 'y'")
        capture_id = item.get("capture")
        windows.move_mouse(x=int(item["x"]), y=int(item["y"]), capture_id=capture_id)

    elif action == "drag":
        sx = item.get("sx", item.get("from_x"))
        sy = item.get("sy", item.get("from_y"))
        ex = item.get("ex", item.get("to_x"))
        ey = item.get("ey", item.get("to_y"))
        if None in (sx, sy, ex, ey):
            raise LCUError("invalid_arguments", "drag requires (sx, sy, ex, ey) or (from_x, from_y, to_x, to_y)")
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
        if "amount" not in item:
            raise LCUError("invalid_arguments", "scroll requires 'amount'")
        windows.scroll(amount=int(item["amount"]))

    elif action == "type_text":
        if "text" not in item:
            raise LCUError("invalid_arguments", "type_text requires 'text'")
        windows.type_text(text=str(item["text"]), hwnd=item.get("hwnd"))

    elif action == "press_key":
        if "key" not in item:
            raise LCUError("invalid_arguments", "press_key requires 'key'")
        count = int(item.get("count", 1))
        windows.press_key(key=str(item["key"]), count=count, hwnd=item.get("hwnd"))

    elif action == "hotkey":
        keys_val = item.get("keys")
        if not keys_val:
            raise LCUError("invalid_arguments", "hotkey requires 'keys'")
        if isinstance(keys_val, str):
            keys = keys_val.split()
        elif isinstance(keys_val, list):
            keys = [str(k) for k in keys_val]
        else:
            raise LCUError("invalid_arguments", "hotkey 'keys' must be a string or list of strings")
        windows.hotkey(keys=keys, hwnd=item.get("hwnd"))

    elif action == "set_clipboard":
        if "text" not in item:
            raise LCUError("invalid_arguments", "set_clipboard requires 'text'")
        windows.set_clipboard(text=str(item["text"]))

    else:
        raise LCUError("invalid_arguments", f"Unhandled action: {action}")


def execute_batch(actions: list[dict[str, Any]]) -> dict[str, Any]:
    # 1. Validation upfront
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

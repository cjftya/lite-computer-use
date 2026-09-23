from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

from .capture import init_windows_environment, resolve_capture_coordinates
from .errors import LCUError

# Virtual Key constants
VK_MAP: dict[str, int] = {
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "TAB": 0x09,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "BACKSPACE": 0x08,
    "BACK": 0x08,
    "DELETE": 0x2E,
    "DEL": 0x2E,
    "SPACE": 0x20,
    "UP": 0x26,
    "DOWN": 0x28,
    "LEFT": 0x25,
    "RIGHT": 0x27,
    "HOME": 0x24,
    "END": 0x23,
    "PAGEUP": 0x21,
    "PGUP": 0x21,
    "PAGEDOWN": 0x22,
    "PGDN": 0x22,
    "INSERT": 0x2D,
    "CTRL": 0x11,
    "CONTROL": 0x11,
    "SHIFT": 0x10,
    "ALT": 0x12,
    "WIN": 0x5B,
    "WINDOWS": 0x5B,
    "CMD": 0x5B,
    "COMMAND": 0x5B,
    "OPTION": 0x12,
}
for i in range(1, 13):
    VK_MAP[f"F{i}"] = 0x6F + i

# SendInput structures
ULONG_PTR = wintypes.WPARAM


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004


def _send_keybd_input(vk: int = 0, scan: int = 0, flags: int = 0) -> None:
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.union.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def get_process_name_for_pid(pid: int) -> str | None:
    if os.name != "nt":
        return None
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not hproc:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name
    finally:
        kernel32.CloseHandle(hproc)
    return None


def get_app_user_model_id(pid: int) -> str | None:
    if os.name != "nt":
        return None
    kernel32 = ctypes.windll.kernel32
    from .processes import _configure_kernel32
    _configure_kernel32(kernel32)
    try:
        kernel32.GetApplicationUserModelId.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR]
        kernel32.GetApplicationUserModelId.restype = wintypes.LONG
    except AttributeError:
        return None
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(0)
        kernel32.GetApplicationUserModelId(handle, ctypes.byref(size), None)
        if size.value < 2 or size.value > 4096:
            return None
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.GetApplicationUserModelId(handle, ctypes.byref(size), buffer) == 0:
            return buffer.value or None
    except (AttributeError, OSError):
        pass
    finally:
        kernel32.CloseHandle(handle)
    return None


def list_windows(query: str | None = None) -> list[dict[str, Any]]:
    init_windows_environment()
    import win32gui
    import win32process

    windows: list[dict[str, Any]] = []
    from .processes import get_process_identity
    identities: dict[int, Any] = {}
    app_ids: dict[int, str | None] = {}
    fg_hwnd = win32gui.GetForegroundWindow()

    def enum_proc(hwnd: int, _: Any) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return True

        # Cloaked check
        cloaked = ctypes.c_int(0)
        res = ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        if res == 0 and cloaked.value != 0:
            return True

        rect = win32gui.GetWindowRect(hwnd)
        w = max(0, rect[2] - rect[0])
        h = max(0, rect[3] - rect[1])
        if w <= 0 or h <= 0:
            return True

        # Process name
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc_name = get_process_name_for_pid(pid) or ""
        if pid not in identities:
            identities[pid] = get_process_identity(pid)
            app_ids[pid] = get_app_user_model_id(pid)
        identity = identities[pid]

        # Query filter
        if query:
            q_lower = query.strip().lower()
            if q_lower not in title.lower() and q_lower not in proc_name.lower():
                return True

        is_min = bool(win32gui.IsIconic(hwnd))
        is_active = (hwnd == fg_hwnd)

        windows.append(
            {
                "hwnd": hwnd,
                "pid": pid,
                "title": title,
                "process": proc_name,
                "image_path": identity.image_path if identity else None,
                "session_id": identity.session_id if identity else None,
                "creation_time": identity.creation_time if identity else None,
                "app_user_model_id": app_ids[pid],
                "class_name": win32gui.GetClassName(hwnd),
                "active": is_active,
                "minimized": is_min,
                "bounds": {
                    "x": rect[0],
                    "y": rect[1],
                    "width": w,
                    "height": h,
                },
            }
        )
        return True

    win32gui.EnumWindows(enum_proc, None)
    return windows


def find_target_window(query: str | None = None, hwnd: int | None = None) -> dict[str, Any]:
    if hwnd is not None:
        import win32gui
        import win32process

        if not win32gui.IsWindow(hwnd):
            raise LCUError("window_not_found", f"Window with hwnd {hwnd} not found")
        title = win32gui.GetWindowText(hwnd)
        rect = win32gui.GetWindowRect(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = get_process_name_for_pid(pid) or ""
        from .processes import get_process_identity
        identity = get_process_identity(pid)
        return {
            "hwnd": hwnd,
            "pid": pid,
            "title": title,
            "process": proc,
            "image_path": identity.image_path if identity else None,
            "session_id": identity.session_id if identity else None,
            "creation_time": identity.creation_time if identity else None,
            "app_user_model_id": get_app_user_model_id(pid),
            "class_name": win32gui.GetClassName(hwnd),
            "active": (hwnd == win32gui.GetForegroundWindow()),
            "minimized": bool(win32gui.IsIconic(hwnd)),
            "bounds": {"x": rect[0], "y": rect[1], "width": rect[2] - rect[0], "height": rect[3] - rect[1]},
        }

    if not query or not query.strip():
        raise LCUError("invalid_arguments", "Must specify either query or hwnd")

    matches = list_windows(query.strip())
    if not matches:
        raise LCUError("window_not_found", f"No window matched query: '{query}'")
    if len(matches) > 1:
        candidates = [f"{w['title']} (hwnd: {w['hwnd']}, process: {w['process']})" for w in matches[:10]]
        raise LCUError("ambiguous_target", f"Multiple windows matched query: '{query}'", candidates=candidates)
    return matches[0]


def focus_window(query: str | None = None, hwnd: int | None = None) -> dict[str, Any]:
    init_windows_environment()
    import win32api
    import win32con
    import win32gui
    import win32process

    target = find_target_window(query=query, hwnd=hwnd)
    target_hwnd = target["hwnd"]

    # Restore if minimized
    if win32gui.IsIconic(target_hwnd):
        win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
    else:
        win32gui.ShowWindow(target_hwnd, win32con.SW_SHOW)

    fg_hwnd = win32gui.GetForegroundWindow()
    if fg_hwnd != target_hwnd:
        curr_thread = win32api.GetCurrentThreadId()
        fg_thread, _ = win32process.GetWindowThreadProcessId(fg_hwnd) if fg_hwnd else (0, 0)
        target_thread, _ = win32process.GetWindowThreadProcessId(target_hwnd)

        attached_curr = False
        attached_fg = False
        try:
            try:
                if fg_thread and fg_thread != target_thread:
                    win32process.AttachThreadInput(fg_thread, target_thread, True)
                    attached_fg = True
                win32process.AttachThreadInput(curr_thread, target_thread, True)
                attached_curr = True
            except Exception:
                # UWP / UIPI permission denied: proceed without raising
                pass

            try:
                win32gui.BringWindowToTop(target_hwnd)
                win32gui.SetForegroundWindow(target_hwnd)
            except Exception:
                pass
        finally:
            if attached_curr:
                try:
                    win32process.AttachThreadInput(curr_thread, target_thread, False)
                except Exception:
                    pass
            if attached_fg:
                try:
                    win32process.AttachThreadInput(fg_thread, target_thread, False)
                except Exception:
                    pass

        # Fallback 1: Synthesize Alt key event to unlock Windows foreground lock
        if win32gui.GetForegroundWindow() != target_hwnd:
            try:
                ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
                ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
                win32gui.BringWindowToTop(target_hwnd)
                win32gui.SetForegroundWindow(target_hwnd)
            except Exception:
                pass

        # Fallback 2: SwitchToThisWindow
        if win32gui.GetForegroundWindow() != target_hwnd:
            try:
                ctypes.windll.user32.SwitchToThisWindow(target_hwnd, True)
            except Exception:
                pass

    # Ensure window has reached foreground
    new_fg = win32gui.GetForegroundWindow()
    if new_fg != target_hwnd:
        t_end = time.time() + 0.5
        while time.time() < t_end:
            time.sleep(0.05)
            new_fg = win32gui.GetForegroundWindow()
            if new_fg == target_hwnd:
                break

    if new_fg != target_hwnd:
        raise LCUError("window_focus_failed", f"Failed to focus window (hwnd: {target_hwnd}, title: '{target['title']}')")

    return {"hwnd": target_hwnd, "title": target["title"]}


def close_window(
    query: str | None = None,
    hwnd: int | None = None,
    timeout: float = 4.0,
    interval: float = 0.05,
    owned_processes: list[dict[str, Any] | Any] | None = None,
    cleanup_owned_processes: bool = True,
) -> dict[str, Any]:
    init_windows_environment()
    import win32con
    import win32gui

    target = find_target_window(query=query, hwnd=hwnd)
    target_hwnd = target["hwnd"]
    cleanup_warnings: list[dict[str, Any]] = []

    if cleanup_owned_processes:
        try:
            from .ownership import authorize_owned_processes, owned_processes_for_window

            if owned_processes is None:
                owned_processes = owned_processes_for_window(
                    hwnd=target_hwnd,
                    window_pid=target.get("pid"),
                )
            else:
                requested_count = len(owned_processes)
                owned_processes = authorize_owned_processes(
                    hwnd=target_hwnd,
                    window_pid=target.get("pid"),
                    candidates=owned_processes,
                )
                if len(owned_processes) != requested_count:
                    cleanup_warnings.append(
                        {
                            "code": "ownership_not_authorized",
                            "message": "Caller-supplied process metadata was not backed by live ledger evidence",
                        }
                    )
        except Exception:
            cleanup_warnings.append(
                {
                    "code": "ownership_lookup_failed",
                    "message": "Owned-process cleanup was skipped because authorization could not be verified",
                }
            )
            owned_processes = None

    # Post WM_CLOSE message
    win32gui.PostMessage(target_hwnd, win32con.WM_CLOSE, 0, 0)

    if os.name != "nt":
        return {"hwnd": target_hwnd, "title": target["title"], "closed": True}

    def is_window_destroyed(h: int) -> bool:
        try:
            return not bool(win32gui.IsWindow(h))
        except Exception:
            return False

    t_end = time.time() + timeout
    max_checks = max(1, int(round(timeout / interval)) + 1) if interval > 0 else 1
    checks = 0

    destroyed = False
    while checks < max_checks:
        if interval > 0:
            time.sleep(interval)
        checks += 1

        if is_window_destroyed(target_hwnd):
            destroyed = True
            break

        if time.time() >= t_end or checks >= max_checks:
            break

    # Final check if loop ended without seeing destruction
    if not destroyed:
        destroyed = is_window_destroyed(target_hwnd)

    if not destroyed:
        raise LCUError(
            "window_close_failed",
            f"Failed to close window (hwnd: {target_hwnd}, title: '{target['title']}') within {timeout}s",
        )

    cleaned_processes: list[int] = []

    # Owned process cleanup (Section 14 & 23)
    if owned_processes and cleanup_owned_processes:
        from .processes import (
            ProcessIdentity,
            is_process_alive,
            terminate_process,
            validate_termination_safety,
        )

        parsed_identities: list[ProcessIdentity] = []
        for p in owned_processes:
            if isinstance(p, ProcessIdentity):
                parsed_identities.append(p)
            elif isinstance(p, dict):
                mode = p.get("cleanup_mode")
                if mode is not None and mode != "owned-after-close":
                    continue
                try:
                    parsed_identities.append(ProcessIdentity.from_dict(p))
                except (KeyError, TypeError, ValueError):
                    cleanup_warnings.append(
                        {"code": "invalid_process_identity", "message": "Invalid cleanup identity was skipped"}
                    )

        if parsed_identities:
            # 1. Natural exit wait: poll up to 1.0s
            t_exit_end = time.time() + 1.0
            while time.time() < t_exit_end:
                states = [is_process_alive(p) for p in parsed_identities]
                if all(state is False for state in states):
                    break
                time.sleep(0.1)

            # 2. For any still alive, perform safety validation and terminate
            for p in parsed_identities:
                alive = is_process_alive(p)
                if alive is False:
                    continue
                if alive is None:
                    cleanup_warnings.append(
                        {
                            "code": "process_state_unknown",
                            "pid": p.pid,
                            "message": "Process state could not be verified; cleanup was skipped",
                        }
                    )
                    continue
                safe, reason = validate_termination_safety(
                    identity=p,
                    exclude_hwnd=target_hwnd,
                )
                if safe:
                    if terminate_process(p, timeout=2.0):
                        cleaned_processes.append(p.pid)
                    else:
                        cleanup_warnings.append(
                            {
                                "code": "terminate_failed",
                                "pid": p.pid,
                                "message": "Process termination was not confirmed",
                            }
                        )
                else:
                    cleanup_warnings.append(
                        {"code": "cleanup_blocked", "pid": p.pid, "message": reason}
                    )

            released = [p for p in parsed_identities if is_process_alive(p) is False]
            if released:
                try:
                    from .ownership import forget_owned_processes

                    forget_owned_processes(released)
                except Exception:
                    pass

    res: dict[str, Any] = {"hwnd": target_hwnd, "title": target["title"], "closed": True}
    if cleaned_processes:
        res["cleaned_processes"] = cleaned_processes
    if cleanup_warnings:
        res["cleanup_warnings"] = cleanup_warnings
    return res



def set_window_bounds(
    x: int,
    y: int,
    width: int,
    height: int,
    hwnd: int | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    init_windows_environment()
    import win32api
    import win32con
    import win32gui

    if width < 50 or height < 50:
        raise LCUError("invalid_arguments", f"Window width and height must be at least 50px (given: {width}x{height})")

    # Validate virtual screen bounds intersection
    vx = win32api.GetSystemMetrics(76)
    vy = win32api.GetSystemMetrics(77)
    vw = win32api.GetSystemMetrics(78)
    vh = win32api.GetSystemMetrics(79)

    inter_x = max(x, vx) < min(x + width, vx + vw)
    inter_y = max(y, vy) < min(y + height, vy + vh)
    if not (inter_x and inter_y):
        raise LCUError(
            "invalid_arguments",
            f"Bounds ({x}, {y}, {width}, {height}) do not intersect virtual screen ({vx}, {vy}, {vw}, {vh})",
        )

    target = find_target_window(query=query, hwnd=hwnd)
    target_hwnd = target["hwnd"]

    if win32gui.IsIconic(target_hwnd):
        win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)

    win32gui.MoveWindow(target_hwnd, x, y, width, height, True)

    time.sleep(0.05)
    rect = win32gui.GetWindowRect(target_hwnd)
    actual_bounds = {
        "x": rect[0],
        "y": rect[1],
        "width": max(0, rect[2] - rect[0]),
        "height": max(0, rect[3] - rect[1]),
    }

    return {"hwnd": target_hwnd, "bounds": actual_bounds}


# Mouse & Keyboard actions


def get_mouse_position() -> dict[str, int]:
    init_windows_environment()
    import win32gui

    pt = win32gui.GetCursorPos()
    return {"x": pt[0], "y": pt[1]}


def move_mouse(x: int, y: int, capture_id: str | None = None) -> dict[str, int]:
    init_windows_environment()
    if capture_id:
        target_x, target_y = resolve_capture_coordinates(capture_id, x, y)
    else:
        target_x, target_y = x, y

    import pyautogui

    pyautogui.moveTo(target_x, target_y, duration=0.0)
    return {"x": target_x, "y": target_y}


def click(
    x: int,
    y: int,
    button: str = "left",
    count: int = 1,
    capture_id: str | None = None,
) -> dict[str, Any]:
    init_windows_environment()
    if button not in ("left", "right", "middle"):
        raise LCUError("invalid_arguments", f"Invalid mouse button: '{button}'. Must be left, right, or middle.")
    if count not in (1, 2):
        raise LCUError("invalid_arguments", f"Invalid click count: {count}. Must be 1 or 2.")

    if capture_id:
        target_x, target_y = resolve_capture_coordinates(capture_id, x, y)
    else:
        target_x, target_y = x, y

    import pyautogui

    pyautogui.click(target_x, target_y, button=button, clicks=count, interval=0.05)
    return {"x": target_x, "y": target_y, "button": button, "count": count}


def drag(
    sx: int,
    sy: int,
    ex: int,
    ey: int,
    capture_id: str | None = None,
    duration: float = 0.2,
) -> dict[str, Any]:
    init_windows_environment()
    if capture_id:
        start_x, start_y = resolve_capture_coordinates(capture_id, sx, sy)
        end_x, end_y = resolve_capture_coordinates(capture_id, ex, ey)
    else:
        start_x, start_y = sx, sy
        end_x, end_y = ex, ey

    import pyautogui

    pyautogui.FAILSAFE = False
    pyautogui.moveTo(start_x, start_y, duration=0.0)
    time.sleep(0.05)
    pyautogui.mouseDown(button="left")
    time.sleep(0.05)
    pyautogui.moveTo(end_x, end_y, duration=max(0.1, min(duration, 2.0)))
    time.sleep(0.05)
    pyautogui.mouseUp(button="left")

    return {
        "from": {"x": start_x, "y": start_y},
        "to": {"x": end_x, "y": end_y},
    }


def scroll(amount: int) -> dict[str, int]:
    init_windows_environment()
    import pyautogui

    pyautogui.scroll(amount * 120)
    return {"amount": amount}


def _verify_hwnd_foreground(hwnd: int | None) -> None:
    if hwnd is None:
        return
    import win32gui

    if not win32gui.IsWindow(hwnd):
        raise LCUError("window_not_found", f"Window with hwnd {hwnd} not found")
    fg = win32gui.GetForegroundWindow()
    if fg != hwnd:
        raise LCUError(
            "window_not_foreground",
            f"Specified window {hwnd} is not foreground (current foreground is {fg})",
        )


def type_text(text: str, hwnd: int | None = None) -> dict[str, int]:
    init_windows_environment()
    _verify_hwnd_foreground(hwnd)

    for char in text:
        if char in ("\r", "\n"):
            # Send Enter
            _send_keybd_input(vk=VK_MAP["ENTER"], flags=0)
            _send_keybd_input(vk=VK_MAP["ENTER"], flags=KEYEVENTF_KEYUP)
        elif char == "\t":
            # Send Tab
            _send_keybd_input(vk=VK_MAP["TAB"], flags=0)
            _send_keybd_input(vk=VK_MAP["TAB"], flags=KEYEVENTF_KEYUP)
        else:
            # Send Unicode char
            code = ord(char)
            _send_keybd_input(vk=0, scan=code, flags=KEYEVENTF_UNICODE)
            _send_keybd_input(vk=0, scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
        time.sleep(0.005)

    return {"chars": len(text)}


def press_key(key: str, count: int = 1, hwnd: int | None = None) -> dict[str, Any]:
    init_windows_environment()
    _verify_hwnd_foreground(hwnd)

    k_upper = key.strip().upper()
    vk = VK_MAP.get(k_upper)
    if vk is None:
        if len(k_upper) == 1:
            vk = ord(k_upper)
        else:
            raise LCUError("invalid_arguments", f"Unsupported key: '{key}'")

    if count < 1:
        raise LCUError("invalid_arguments", "Key count must be at least 1")

    for _ in range(count):
        _send_keybd_input(vk=vk, flags=0)
        _send_keybd_input(vk=vk, flags=KEYEVENTF_KEYUP)
        time.sleep(0.01)

    return {"key": key, "count": count}


def hotkey(keys: list[str], hwnd: int | None = None) -> dict[str, Any]:
    init_windows_environment()
    _verify_hwnd_foreground(hwnd)

    if not keys:
        raise LCUError("invalid_arguments", "Hotkey requires at least one key")

    vks: list[int] = []
    for k in keys:
        k_upper = k.strip().upper()
        vk = VK_MAP.get(k_upper)
        if vk is None:
            if len(k_upper) == 1:
                vk = ord(k_upper)
            else:
                raise LCUError("invalid_arguments", f"Unsupported key in hotkey: '{k}'")
        vks.append(vk)

    # Press keys in order
    for vk in vks:
        _send_keybd_input(vk=vk, flags=0)
        time.sleep(0.005)

    # Release in reverse order
    for vk in reversed(vks):
        _send_keybd_input(vk=vk, flags=KEYEVENTF_KEYUP)
        time.sleep(0.005)

    return {"keys": keys}


def set_clipboard(text: str) -> dict[str, int]:
    init_windows_environment()
    import win32clipboard
    import win32con

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    finally:
        win32clipboard.CloseClipboard()

    return {"chars": len(text)}


def get_clipboard() -> dict[str, str]:
    init_windows_environment()
    import win32clipboard
    import win32con

    win32clipboard.OpenClipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        elif win32clipboard.IsClipboardFormatAvailable(win32con.CF_TEXT):
            data = win32clipboard.GetClipboardData(win32con.CF_TEXT)
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")
        else:
            data = ""
    finally:
        win32clipboard.CloseClipboard()

    return {"text": data or ""}

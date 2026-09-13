from __future__ import annotations

import ctypes
import math
import ntpath
import os
import shutil
import struct
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

from direct_backend import DirectWindowsBackend
from helpers import AppDefinition, AppRegistry, LCUError, normalize_name

KEY_ALIASES = {
    "CONTROL": "ctrl",
    "CTRL": "ctrl",
    "ESCAPE": "esc",
    "ESC": "esc",
    "RETURN": "enter",
    "ENTER": "enter",
    "WINDOWS": "win",
    "WIN": "win",
    "COMMAND": "win",
    "CMD": "win",
    "OPTION": "alt",
    "ALT": "alt",
    "DELETE": "delete",
    "DEL": "delete",
    "BACKSPACE": "backspace",
    "BACK": "backspace",
    "PAGEUP": "pageup",
    "PAGEDOWN": "pagedown",
    "SPACE": "space",
    "TAB": "tab",
    "HOME": "home",
    "END": "end",
    "INSERT": "insert",
    "UP": "up",
    "DOWN": "down",
    "LEFT": "left",
    "RIGHT": "right",
    "SHIFT": "shift",
}


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


class WindowsBackend(DirectWindowsBackend):
    def __init__(self, app_registry: AppRegistry | None = None) -> None:
        if os.name != "nt":
            raise LCUError("unsupported_platform", "Lite Computer Use requires Windows")

        self._enable_dpi_awareness()
        self._attach_to_default_desktop()
        try:
            import pyautogui
            import pywintypes
            import win32api
            import win32clipboard
            import win32con
            import win32gui
            import win32process
            from PIL import Image, ImageGrab
        except ImportError as exc:
            raise LCUError(
                "dependency_missing",
                f"Missing Windows dependency: {exc.name}. "
                "Run: py -3.13 -m pip install -r requirements.txt",
            ) from exc

        self.pyautogui = pyautogui
        self.pywintypes = pywintypes
        self.win32api = win32api
        self.win32clipboard = win32clipboard
        self.win32con = win32con
        self.win32gui = win32gui
        self.win32process = win32process
        self.Image = Image
        self.ImageGrab = ImageGrab
        self.app_registry = app_registry

        self.pyautogui.FAILSAFE = True
        # A short global pause keeps interactive desktop actions reliable while
        # avoiding the 150 ms penalty that dominated simple fast-path calls.
        self.pyautogui.PAUSE = 0.08

    @staticmethod
    def _attach_to_default_desktop() -> None:
        try:
            import win32con
            import win32service
            hdesk = win32service.OpenDesktop("default", 0, False, win32con.GENERIC_ALL)
            if hdesk:
                ctypes.windll.user32.SetThreadDesktop(int(hdesk))
        except Exception:
            pass

    @staticmethod
    def _enable_dpi_awareness() -> None:
        user32 = ctypes.windll.user32
        try:
            per_monitor_v2 = ctypes.c_void_p(-4)
            if user32.SetProcessDpiAwarenessContext(per_monitor_v2):
                return
        except (AttributeError, OSError):
            pass
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass

    def screen_bounds(self, primary_only: bool = False) -> dict[str, int]:
        if primary_only:
            left = 0
            top = 0
            width = self.win32api.GetSystemMetrics(0)
            height = self.win32api.GetSystemMetrics(1)
        else:
            left = self.win32api.GetSystemMetrics(76)
            top = self.win32api.GetSystemMetrics(77)
            width = self.win32api.GetSystemMetrics(78)
            height = self.win32api.GetSystemMetrics(79)
        return {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "right": left + width,
            "bottom": top + height,
        }

    def active_window(self) -> dict[str, Any]:
        hwnd = self.win32gui.GetForegroundWindow()
        if not hwnd:
            raise LCUError("no_active_window", "No active window was found")
        title = self.win32gui.GetWindowText(hwnd)
        left, top, right, bottom = self.win32gui.GetWindowRect(hwnd)
        return {
            "hwnd": int(hwnd),
            "title": title,
            "bounds": {
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
                "width": max(0, right - left),
                "height": max(0, bottom - top),
            },
        }

    def screenshot(
        self,
        output: Path | None,
        active_window: bool,
        all_screens: bool,
        region: list[int] | tuple[int, int, int, int] | None = None,
        scale: float = 1.0,
    ) -> dict[str, Any]:
        if not math.isfinite(scale) or not 0.25 <= scale <= 1.0:
            raise LCUError(
                "invalid_scale", "Screenshot scale must be between 0.25 and 1.0"
            )
        if active_window and all_screens:
            raise LCUError(
                "invalid_screenshot_options",
                "--active-window and --all-screens cannot be used together",
            )
        if region is not None and (active_window or all_screens):
            raise LCUError(
                "invalid_screenshot_options",
                "--region cannot be combined with --active-window or --all-screens",
            )

        if region is not None:
            bounds = self._region_bounds(region)
            try:
                title = self.active_window().get("title", "")
            except LCUError:
                title = ""
        elif active_window:
            active = self.active_window()
            bounds = active["bounds"]
            if bounds["width"] <= 0 or bounds["height"] <= 0:
                raise LCUError(
                    "invalid_window_bounds", "The active window has no visible area"
                )
            title = active["title"]
        else:
            bounds = self.screen_bounds(primary_only=not all_screens)
            try:
                title = self.active_window().get("title", "")
            except LCUError:
                title = ""

        if output is None:
            directory = Path(tempfile.gettempdir()) / "LiteComputerUse" / "screenshots"
            directory.mkdir(parents=True, exist_ok=True)
            self._clean_old_screenshots(directory)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            output = (
                directory / f"screenshot-{stamp}-{time.time_ns() % 1_000_000:06d}.png"
            )
        else:
            output = output.expanduser().resolve(strict=False)
            if output.suffix.casefold() not in {"", ".png"}:
                raise LCUError("invalid_output", "Screenshot output must be a PNG file")
            if not output.suffix:
                output = output.with_suffix(".png")
            if output.exists():
                raise LCUError(
                    "output_exists",
                    "Screenshot output already exists; choose a new path",
                    path=str(output),
                )
            output.parent.mkdir(parents=True, exist_ok=True)

        bbox = (bounds["left"], bounds["top"], bounds["right"], bounds["bottom"])
        image = self.ImageGrab.grab(bbox=bbox, all_screens=True)
        original_width = image.width
        original_height = image.height
        if scale < 1.0:
            size = (
                max(1, round(original_width * scale)),
                max(1, round(original_height * scale)),
            )
            image = image.resize(size, self.Image.Resampling.BILINEAR)
        image.save(output, format="PNG")
        return {
            "path": str(output),
            "width": image.width,
            "height": image.height,
            "originalWidth": original_width,
            "originalHeight": original_height,
            "scale": scale,
            "bounds": bounds,
            "imageCoordinateSpace": "active-window" if active_window else "screen",
            "activeWindow": title,
            "activeWindowOnly": active_window,
            "regionOnly": region is not None,
        }

    def _region_bounds(
        self, region: list[int] | tuple[int, int, int, int]
    ) -> dict[str, int]:
        if len(region) != 4:
            raise LCUError("invalid_region", "Region must contain x, y, width, height")
        x, y, width, height = region
        if width <= 0 or height <= 0:
            raise LCUError(
                "invalid_region", "Region width and height must be greater than zero"
            )
        desktop = self.screen_bounds(primary_only=False)
        if (
            x < desktop["left"]
            or y < desktop["top"]
            or x + width > desktop["right"]
            or y + height > desktop["bottom"]
        ):
            raise LCUError(
                "region_out_of_bounds",
                "Screenshot region is outside the virtual desktop",
                region={"x": x, "y": y, "width": width, "height": height},
                bounds=desktop,
            )
        return {
            "left": x,
            "top": y,
            "right": x + width,
            "bottom": y + height,
            "width": width,
            "height": height,
        }

    @staticmethod
    def _clean_old_screenshots(directory: Path, max_age_seconds: int = 86_400) -> None:
        cutoff = time.time() - max_age_seconds
        for path in directory.glob("screenshot-*.png"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue

    def _absolute_point(self, x: int, y: int, relative_to: str) -> tuple[int, int]:
        if relative_to == "active-window":
            bounds = self.active_window()["bounds"]
            if not 0 <= x < bounds["width"] or not 0 <= y < bounds["height"]:
                raise LCUError(
                    "coordinate_out_of_bounds",
                    "Window-relative coordinate is outside the active window",
                    x=x,
                    y=y,
                    bounds=bounds,
                )
            x += bounds["left"]
            y += bounds["top"]
        elif relative_to != "screen":
            raise LCUError(
                "invalid_coordinate_space", f"Unknown coordinate space: {relative_to}"
            )

        bounds = self.screen_bounds(primary_only=False)
        if (
            not bounds["left"] <= x < bounds["right"]
            or not bounds["top"] <= y < bounds["bottom"]
        ):
            raise LCUError(
                "coordinate_out_of_bounds",
                "Coordinate is outside the virtual desktop",
                x=x,
                y=y,
                bounds=bounds,
            )
        return x, y

    def click(
        self,
        x: int,
        y: int,
        relative_to: str = "screen",
        clicks: int = 1,
        button: str = "left",
    ) -> dict[str, Any]:
        button = self._validate_mouse_button(button)
        x, y = self._absolute_point(x, y, relative_to)
        self.pyautogui.click(
            x=x,
            y=y,
            clicks=clicks,
            interval=0.12 if clicks > 1 else 0,
            button=button,
        )
        return {"x": x, "y": y, "clicks": clicks, "button": button}

    @staticmethod
    def _validate_mouse_button(button: str) -> str:
        normalized = button.strip().casefold()
        if normalized not in {"left", "right", "middle"}:
            raise LCUError("invalid_mouse_button", f"Unsupported mouse button: {button}")
        return normalized

    def move_mouse(
        self, x: int, y: int, relative_to: str = "screen"
    ) -> dict[str, int]:
        x, y = self._absolute_point(x, y, relative_to)
        self.pyautogui.moveTo(x, y)
        return {"x": x, "y": y}

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5,
        button: str = "left",
        relative_to: str = "screen",
    ) -> dict[str, Any]:
        if not 0 <= duration <= 10:
            raise LCUError(
                "invalid_duration", "Drag duration must be between 0 and 10 seconds"
            )
        button = self._validate_mouse_button(button)
        start = self._absolute_point(start_x, start_y, relative_to)
        end = self._absolute_point(end_x, end_y, relative_to)
        self.pyautogui.moveTo(*start)
        try:
            self.pyautogui.mouseDown(button=button)
            self.pyautogui.moveTo(*end, duration=duration)
        finally:
            # Keep drag atomic: even a fail-safe or input error must not leave
            # the desktop with a mouse button logically held down.
            self.pyautogui.mouseUp(button=button)
        return {
            "start": {"x": start[0], "y": start[1]},
            "end": {"x": end[0], "y": end[1]},
            "duration": duration,
            "button": button,
        }

    def get_mouse_position(self) -> dict[str, int]:
        x, y = self.win32api.GetCursorPos()
        return {"x": int(x), "y": int(y)}

    def scroll(self, amount: int) -> dict[str, int]:
        if amount == 0 or abs(amount) > 10_000:
            raise LCUError(
                "invalid_scroll",
                "Scroll amount must be between -10000 and 10000, excluding 0",
            )
        self.pyautogui.scroll(amount)
        return {"amount": amount}

    def normalize_key(self, key: str) -> str:
        normalized = KEY_ALIASES.get(key.strip().upper(), key.strip().casefold())
        if normalized not in self.pyautogui.KEYBOARD_KEYS:
            raise LCUError("invalid_key", f"Unsupported key: {key}")
        return normalized

    def press_key(self, key: str, count: int = 1) -> dict[str, Any]:
        if not 1 <= count <= 100:
            raise LCUError("invalid_count", "Key press count must be between 1 and 100")
        normalized = self.normalize_key(key)
        self.pyautogui.press(normalized, presses=count)
        return {"key": normalized, "count": count}

    def hotkey(self, keys: list[str]) -> dict[str, list[str]]:
        if not 2 <= len(keys) <= 5:
            raise LCUError(
                "invalid_hotkey", "A hotkey must contain between 2 and 5 keys"
            )
        normalized = [self.normalize_key(key) for key in keys]
        self.pyautogui.hotkey(*normalized)
        return {"keys": normalized}

    def type_text(self, text: str, interval: float = 0.0) -> dict[str, Any]:
        if len(text) > 10_000:
            raise LCUError(
                "text_too_long", "Text input is limited to 10,000 characters per action"
            )
        if not 0 <= interval <= 1:
            raise LCUError(
                "invalid_interval", "Typing interval must be between 0 and 1 second"
            )

        # KEYEVENTF_UNICODE avoids PyAutoGUI's ASCII-only write path and does not
        # overwrite the user's clipboard. Newlines and tabs remain real keys.
        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
        for segment_index, segment in enumerate(normalized_text.split("\n")):
            if segment_index:
                self.pyautogui.press("enter")
            chunks = segment.split("\t")
            for chunk_index, chunk in enumerate(chunks):
                if chunk_index:
                    self.pyautogui.press("tab")
                self._send_unicode(chunk, interval)
        return {"length": len(text), "method": "unicode-sendinput"}

    def _send_unicode(self, text: str, interval: float) -> None:
        if not text:
            return

        utf16 = text.encode("utf-16-le")
        code_units = struct.unpack(f"<{len(utf16) // 2}H", utf16)
        user32 = ctypes.windll.user32
        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        user32.SendInput.restype = wintypes.UINT

        # With the default zero interval, submit bounded batches instead of one
        # Windows call per UTF-16 unit. Non-zero intervals retain per-unit pacing.
        batch_size = 128 if interval == 0 else 1
        for offset in range(0, len(code_units), batch_size):
            self.pyautogui.failSafeCheck()
            batch = code_units[offset : offset + batch_size]
            events = self._unicode_input_events(batch)
            sent = user32.SendInput(len(events), events, ctypes.sizeof(INPUT))
            if sent != len(events):
                raise LCUError(
                    "input_failed", "Windows SendInput did not accept Unicode input"
                )
            if interval:
                time.sleep(interval)

    @staticmethod
    def _unicode_input_events(code_units: tuple[int, ...]) -> Any:
        input_keyboard = 1
        keyeventf_keyup = 0x0002
        keyeventf_unicode = 0x0004
        values: list[INPUT] = []
        for code_unit in code_units:
            values.extend(
                [
                    INPUT(
                        type=input_keyboard,
                        ki=KEYBDINPUT(0, code_unit, keyeventf_unicode, 0, 0),
                    ),
                    INPUT(
                        type=input_keyboard,
                        ki=KEYBDINPUT(
                            0,
                            code_unit,
                            keyeventf_unicode | keyeventf_keyup,
                            0,
                            0,
                        ),
                    ),
                ]
            )
        return (INPUT * len(values))(*values)

    def list_windows(self) -> list[dict[str, Any]]:
        active_hwnd = self.win32gui.GetForegroundWindow()
        windows: list[dict[str, Any]] = []
        process_cache: dict[int, str | None] = {}

        def callback(hwnd: int, _: Any) -> bool:
            if not self.win32gui.IsWindowVisible(hwnd):
                return True
            title = self.win32gui.GetWindowText(hwnd).strip()
            if not title:
                return True
            pid, process = self._window_identity(hwnd, process_cache)
            windows.append(
                {
                    "hwnd": int(hwnd),
                    "title": title,
                    "active": hwnd == active_hwnd,
                    "minimized": bool(self.win32gui.IsIconic(hwnd)),
                    "pid": pid,
                    "process": process,
                    "bounds": self._window_bounds(hwnd),
                }
            )
            return True

        self.win32gui.EnumWindows(callback, None)
        return windows

    def _window_identity(
        self,
        hwnd: int,
        process_cache: dict[int, str | None] | None = None,
    ) -> tuple[int | None, str | None]:
        try:
            _, pid = self.win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return None, None
        pid = int(pid)
        if process_cache is not None and pid in process_cache:
            return pid, process_cache[pid]
        try:
            process = self._process_basename(pid)
        except Exception:
            process = None
        if process_cache is not None:
            process_cache[pid] = process
        return pid, process

    @staticmethod
    def _process_basename(pid: int) -> str | None:
        kernel32 = ctypes.windll.kernel32
        query_limited_information = 0x1000
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.OpenProcess(query_limited_information, False, pid)
        if not handle:
            return None
        try:
            buffer = ctypes.create_unicode_buffer(32_768)
            size = wintypes.DWORD(len(buffer))
            if not kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                return None
            return Path(buffer.value).name.casefold() or None
        finally:
            kernel32.CloseHandle(handle)

    def _window_bounds(self, hwnd: int) -> dict[str, int]:
        left, top, right, bottom = self.win32gui.GetWindowRect(hwnd)
        return {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "width": max(0, right - left),
            "height": max(0, bottom - top),
        }

    def _resolve_window(
        self,
        query: str | None = None,
        hwnd: int | None = None,
        expected_pid: int | None = None,
        *,
        prefer_active: bool = True,
    ) -> dict[str, Any]:
        windows = self.list_windows()
        if hwnd is not None:
            candidates = [window for window in windows if window["hwnd"] == hwnd]
            if not candidates:
                raise LCUError(
                    "stale_window_handle",
                    "The requested window handle no longer exists",
                    hwnd=hwnd,
                    stage="resolve_window",
                    retryable=False,
                    nextAction="run_list_windows",
                )
            target = candidates[0]
            if expected_pid is not None and target.get("pid") != expected_pid:
                raise LCUError(
                    "window_pid_mismatch",
                    "The window handle belongs to a different process",
                    hwnd=hwnd,
                    expectedPid=expected_pid,
                    actualPid=target.get("pid"),
                    stage="resolve_window",
                    retryable=False,
                    nextAction="run_list_windows",
                )
            return target

        needle = normalize_name(query or "")
        if not needle:
            raise LCUError("invalid_window_query", "Window title query cannot be empty")
        aliases = {needle, normalize_name(Path(query or "").stem)}
        app_registry = getattr(self, "app_registry", None)
        if app_registry is not None:
            aliases.update(app_registry.process_names_for(query))

        def normalized_process(window: dict[str, Any]) -> tuple[str, str]:
            process = normalize_name(window.get("process") or "")
            return process, normalize_name(Path(process).stem)

        stages = (
            [window for window in windows if normalize_name(window["title"]) == needle],
            [
                window
                for window in windows
                if any(value in aliases for value in normalized_process(window))
            ],
            [window for window in windows if needle in normalize_name(window["title"])],
            [
                window
                for window in windows
                if any(
                    alias in value
                    for value in normalized_process(window)
                    for alias in aliases
                    if alias
                )
            ],
        )
        candidates = next((stage for stage in stages if stage), [])
        if not candidates:
            raise LCUError("window_not_found", f"No window matched: {query}")
        active_matches = [window for window in candidates if window["active"]]
        if active_matches and prefer_active:
            candidates = active_matches
        elif len(candidates) > 1:
            raise LCUError(
                "ambiguous_window",
                "Multiple windows matched; use a more specific title or app name",
                candidates=[
                    {"title": window["title"], "process": window.get("process")}
                    for window in candidates
                ],
            )
        target = candidates[0]
        if expected_pid is not None and target.get("pid") != expected_pid:
            raise LCUError(
                "window_pid_mismatch",
                "The matched window belongs to a different process",
                expectedPid=expected_pid,
                actualPid=target.get("pid"),
                stage="resolve_window",
                retryable=False,
                nextAction="run_list_windows",
            )
        return target

    def focus_window(
        self,
        query: str | None = None,
        hwnd: int | None = None,
        expected_pid: int | None = None,
        timeout: float = 1.0,
    ) -> dict[str, Any]:
        target = self._resolve_window(query, hwnd, expected_pid)
        hwnd = target["hwnd"]
        if self.win32gui.IsIconic(hwnd):
            self.win32gui.ShowWindow(hwnd, self.win32con.SW_RESTORE)
        try:
            self.win32gui.SetForegroundWindow(hwnd)
        except self.pywintypes.error:
            # Windows sometimes rejects focus stealing. Briefly tapping Alt is
            # the least invasive documented workaround for an interactive tool.
            self.win32api.keybd_event(self.win32con.VK_MENU, 0, 0, 0)
            self.win32api.keybd_event(
                self.win32con.VK_MENU, 0, self.win32con.KEYEVENTF_KEYUP, 0
            )
            self.win32gui.BringWindowToTop(hwnd)
            self.win32gui.SetForegroundWindow(hwnd)
        deadline = time.monotonic() + timeout
        while self.win32gui.GetForegroundWindow() != hwnd:
            if time.monotonic() >= deadline:
                raise LCUError(
                    "window_focus_unverified",
                    "Windows did not make the requested window foreground",
                    hwnd=hwnd,
                    stage="verify_foreground",
                    retryable=True,
                    nextAction="focus_once_then_stop_if_rejected",
                )
            time.sleep(0.05)
        return {
            "hwnd": hwnd,
            "pid": target.get("pid"),
            "title": target["title"],
            "status": "verified",
            "osStateVerified": True,
            "focusChanged": True,
        }

    def ensure_input_target(
        self,
        query: str | None = None,
        hwnd: int | None = None,
        expected_pid: int | None = None,
    ) -> dict[str, Any]:
        target = self._resolve_window(query, hwnd, expected_pid)
        if self.win32gui.GetForegroundWindow() == target["hwnd"]:
            return {
                "hwnd": target["hwnd"],
                "pid": target.get("pid"),
                "title": target["title"],
                "status": "verified",
                "osStateVerified": True,
                "focusChanged": False,
            }
        return self.focus_window(
            hwnd=target["hwnd"], expected_pid=target.get("pid")
        )

    def set_window_state(
        self,
        query: str | None,
        state: str,
        hwnd: int | None = None,
        expected_pid: int | None = None,
    ) -> dict[str, Any]:
        commands = {
            "restore": self.win32con.SW_RESTORE,
            "minimize": self.win32con.SW_MINIMIZE,
            "maximize": self.win32con.SW_MAXIMIZE,
        }
        try:
            command = commands[state]
        except KeyError as exc:
            raise LCUError(
                "invalid_window_state", f"Unknown window state: {state}"
            ) from exc
        target = self._resolve_window(
            query, hwnd, expected_pid, prefer_active=False
        )
        self.win32gui.ShowWindow(target["hwnd"], command)
        return {"hwnd": target["hwnd"], "title": target["title"], "state": state}

    def set_window_bounds(
        self,
        query: str | None,
        x: int,
        y: int,
        width: int,
        height: int,
        hwnd: int | None = None,
        expected_pid: int | None = None,
    ) -> dict[str, Any]:
        if width <= 0 or height <= 0:
            raise LCUError(
                "invalid_window_bounds",
                "Window width and height must be greater than zero",
            )
        desktop = self.screen_bounds(primary_only=False)
        if (
            x < desktop["left"]
            or y < desktop["top"]
            or x + width > desktop["right"]
            or y + height > desktop["bottom"]
        ):
            raise LCUError(
                "window_bounds_out_of_range",
                "Requested window bounds are outside the virtual desktop",
                requested={"x": x, "y": y, "width": width, "height": height},
                bounds=desktop,
            )
        target = self._resolve_window(
            query, hwnd, expected_pid, prefer_active=False
        )
        if self.win32gui.IsIconic(target["hwnd"]) or self.win32gui.IsZoomed(
            target["hwnd"]
        ):
            self.win32gui.ShowWindow(target["hwnd"], self.win32con.SW_RESTORE)
        flags = self.win32con.SWP_NOZORDER | self.win32con.SWP_NOACTIVATE
        self.win32gui.SetWindowPos(target["hwnd"], 0, x, y, width, height, flags)
        return {
            "hwnd": target["hwnd"],
            "title": target["title"],
            "bounds": {
                "left": x,
                "top": y,
                "right": x + width,
                "bottom": y + height,
                "width": width,
                "height": height,
            },
        }

    def close_window(
        self,
        query: str | None = None,
        hwnd: int | None = None,
        expected_pid: int | None = None,
    ) -> dict[str, Any]:
        target = self._resolve_window(
            query, hwnd, expected_pid, prefer_active=False
        )
        self.win32gui.PostMessage(target["hwnd"], self.win32con.WM_CLOSE, 0, 0)
        return {"hwnd": target["hwnd"], "title": target["title"], "requested": True}

    def wait_for_window(
        self,
        query: str | None,
        state: str = "present",
        timeout: float = 10.0,
        hwnd: int | None = None,
        expected_pid: int | None = None,
    ) -> dict[str, Any]:
        if state not in {"present", "gone", "active"}:
            raise LCUError("invalid_window_state", f"Unknown wait state: {state}")
        if not 0 < timeout <= 30:
            raise LCUError(
                "invalid_timeout",
                "Window wait timeout must be greater than 0 and at most 30 seconds",
            )

        deadline = time.monotonic() + timeout
        while True:
            target: dict[str, Any] | None
            try:
                target = self._resolve_window(query, hwnd, expected_pid)
            except LCUError as exc:
                if exc.code not in {"window_not_found", "stale_window_handle"}:
                    raise
                target = None

            matched = (
                (state == "present" and target is not None)
                or (state == "gone" and target is None)
                or (state == "active" and target is not None and target["active"])
            )
            if matched:
                if target is None:
                    return {"found": False, "state": state}
                return {
                    "found": True,
                    "hwnd": target["hwnd"],
                    "pid": target.get("pid"),
                    "title": target["title"],
                    "state": state,
                    "status": "verified" if state == "active" else "present_unverified",
                    "inputReady": state == "active",
                }
            if time.monotonic() >= deadline:
                raise LCUError(
                    "window_wait_timeout",
                    f"Timed out waiting for window state: {state}",
                    state=state,
                    timeout=timeout,
                )
            time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))

    def launch_app(self, app: AppDefinition) -> dict[str, Any]:
        failures: list[dict[str, Any]] = []
        not_found_only = True
        for command in app.commands:
            try:
                launched = self._launch_command(command)
                result: dict[str, Any] = {
                    "name": app.name,
                    "source": app.source,
                    "status": "dispatch_accepted",
                    "dispatchAccepted": True,
                    "osStateVerified": False,
                    "verification": "unverified",
                }
                if app.source == "registry":
                    result["command"] = self._public_command(launched)
                return result
            except OSError as exc:
                error_number = getattr(exc, "winerror", None) or exc.errno
                not_found_only = not_found_only and error_number in {2, 3}
                failure: dict[str, Any] = {"osError": error_number}
                if app.source == "registry":
                    failure["command"] = self._public_command(command)
                failures.append(failure)
        details: dict[str, Any] = {
            "source": app.source,
            "failures": failures,
            "notFoundOnly": bool(failures) and not_found_only,
            "stage": "dispatch",
            "retryable": bool(failures) and not_found_only,
            "nextAction": "resolve_installed_app_once" if not_found_only else "stop",
        }
        if app.source == "registry":
            details["attempted"] = [self._public_command(command) for command in app.commands]
        raise LCUError(
            "app_launch_failed",
            f"Could not launch app: {app.name}",
            **details,
        )

    @staticmethod
    def _public_command(command: str) -> str:
        if command.endswith(":"):
            return command
        return ntpath.basename(command) or "configured-command"

    def _launch_command(self, command: str) -> str:
        expanded = os.path.expandvars(command)
        if expanded.endswith(":"):
            os.startfile(expanded)
            return command

        executable = shutil.which(expanded) or self._find_app_path(expanded)
        if executable:
            os.startfile(executable)
            return command

        # ShellExecute can resolve Windows App Execution Aliases that are not on PATH.
        os.startfile(expanded)
        return command

    @staticmethod
    def _find_app_path(executable: str) -> str | None:
        try:
            import winreg
        except ImportError:
            return None
        subkey = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{executable}"
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    value, _ = winreg.QueryValueEx(key, None)
                    if value and Path(value).exists():
                        return str(value)
            except OSError:
                continue
        return None

    def set_clipboard(self, text: str) -> dict[str, int]:
        self._open_clipboard()
        try:
            self.win32clipboard.EmptyClipboard()
            self.win32clipboard.SetClipboardText(text, self.win32con.CF_UNICODETEXT)
        finally:
            self.win32clipboard.CloseClipboard()
        return {"length": len(text)}

    def get_clipboard(self) -> dict[str, Any]:
        self._open_clipboard()
        try:
            if not self.win32clipboard.IsClipboardFormatAvailable(
                self.win32con.CF_UNICODETEXT
            ):
                return {"text": None, "length": 0, "format": "non-text-or-empty"}
            text = self.win32clipboard.GetClipboardData(self.win32con.CF_UNICODETEXT)
            return {"text": text, "length": len(text), "format": "unicode-text"}
        finally:
            self.win32clipboard.CloseClipboard()

    def _open_clipboard(self) -> None:
        for attempt in range(10):
            try:
                self.win32clipboard.OpenClipboard()
                return
            except self.pywintypes.error:
                if attempt == 9:
                    raise LCUError("clipboard_busy", "The Windows clipboard is busy")
                time.sleep(0.05)

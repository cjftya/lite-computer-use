from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from helpers import LCUError
from windows_backend import INPUT, WindowsBackend


class WindowsBackendSafetyTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "ctypes.wintypes uses host-native sizes")
    def test_send_input_structure_has_native_windows_size(self) -> None:
        expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        self.assertEqual(expected, ctypes.sizeof(INPUT))

    def test_non_http_url_is_rejected_before_launch(self) -> None:
        with self.assertRaises(LCUError) as context:
            WindowsBackend.open_url("file:///C:/Windows/System32/calc.exe")
        self.assertEqual("invalid_url", context.exception.code)

    def test_executable_file_is_rejected_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "sample.exe"
            executable.write_bytes(b"not executable")
            with self.assertRaises(LCUError) as context:
                WindowsBackend.open_file(str(executable))
        self.assertEqual("executable_file_blocked", context.exception.code)

    def test_open_folder_rejects_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "document.txt"
            file_path.write_text("test", encoding="utf-8")
            with self.assertRaises(LCUError) as context:
                WindowsBackend.open_folder(str(file_path))
        self.assertEqual("not_a_folder", context.exception.code)

    def test_reveal_file_rejects_missing_target(self) -> None:
        with self.assertRaises(LCUError) as context:
            WindowsBackend.reveal_file("definitely-missing-lcu-test-file.pdf")
        self.assertEqual("file_not_found", context.exception.code)

    def test_open_folder_and_reveal_file_use_explorer_without_opening_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            file_path = folder / "document with spaces.pdf"
            file_path.write_text("test", encoding="utf-8")
            with patch("windows_backend.os.startfile", create=True) as startfile:
                result = WindowsBackend.open_folder(str(folder))
            startfile.assert_called_once_with(str(folder.resolve()))
            self.assertEqual(str(folder.resolve()), result["path"])

            with patch("windows_backend.subprocess.Popen") as popen:
                result = WindowsBackend.reveal_file(str(file_path))
            popen.assert_called_once_with(
                ["explorer.exe", f"/select,{file_path.resolve()}"], close_fds=True
            )
            self.assertEqual(str(file_path.resolve()), result["path"])


class WindowsBackendPrimitiveTests(unittest.TestCase):
    def make_backend(self) -> WindowsBackend:
        backend = WindowsBackend.__new__(WindowsBackend)
        backend.pyautogui = Mock()
        backend.pyautogui.KEYBOARD_KEYS = ["tab", "enter", "ctrl"]
        backend.win32api = Mock()
        backend.win32con = SimpleNamespace(
            SW_RESTORE=9,
            SW_MINIMIZE=6,
            SW_MAXIMIZE=3,
            SWP_NOZORDER=4,
            SWP_NOACTIVATE=16,
            WM_CLOSE=16,
        )
        backend.win32gui = Mock()
        backend.pywintypes = SimpleNamespace(error=RuntimeError)
        backend.screen_bounds = Mock(
            return_value={
                "left": -1920,
                "top": 0,
                "right": 1920,
                "bottom": 1080,
                "width": 3840,
                "height": 1080,
            }
        )
        return backend

    def test_active_window_coordinates_are_converted(self) -> None:
        backend = self.make_backend()
        backend.active_window = Mock(
            return_value={
                "bounds": {
                    "left": -100,
                    "top": 20,
                    "right": 500,
                    "bottom": 420,
                    "width": 600,
                    "height": 400,
                }
            }
        )
        self.assertEqual((-90, 40), backend._absolute_point(10, 20, "active-window"))

    def test_negative_virtual_desktop_coordinate_is_valid(self) -> None:
        backend = self.make_backend()
        self.assertEqual((-100, 50), backend._absolute_point(-100, 50, "screen"))

    def test_invalid_mouse_button_is_rejected(self) -> None:
        backend = self.make_backend()
        with self.assertRaises(LCUError) as context:
            backend.click(10, 10, button="side")
        self.assertEqual("invalid_mouse_button", context.exception.code)

    def test_right_click_is_forwarded(self) -> None:
        backend = self.make_backend()
        result = backend.click(10, 20, button="right")
        backend.pyautogui.click.assert_called_once_with(
            x=10, y=20, clicks=1, interval=0, button="right"
        )
        self.assertEqual("right", result["button"])

    def test_drag_validates_both_points_before_input(self) -> None:
        backend = self.make_backend()
        with self.assertRaises(LCUError) as context:
            backend.drag(10, 10, 4000, 20)
        self.assertEqual("coordinate_out_of_bounds", context.exception.code)
        backend.pyautogui.moveTo.assert_not_called()

    def test_drag_releases_mouse_when_move_fails(self) -> None:
        backend = self.make_backend()
        backend.pyautogui.moveTo.side_effect = [None, RuntimeError("input failed")]
        with self.assertRaisesRegex(RuntimeError, "input failed"):
            backend.drag(10, 10, 20, 20, button="middle")
        backend.pyautogui.mouseDown.assert_called_once_with(button="middle")
        backend.pyautogui.mouseUp.assert_called_once_with(button="middle")

    def test_press_key_count_is_bounded(self) -> None:
        backend = self.make_backend()
        result = backend.press_key("TAB", 4)
        backend.pyautogui.press.assert_called_once_with("tab", presses=4)
        self.assertEqual(4, result["count"])
        for invalid in (0, 101):
            with self.subTest(invalid=invalid), self.assertRaises(LCUError) as context:
                backend.press_key("TAB", invalid)
            self.assertEqual("invalid_count", context.exception.code)

    def test_region_accepts_negative_monitor_coordinates(self) -> None:
        backend = self.make_backend()
        bounds = backend._region_bounds((-1800, 10, 800, 600))
        self.assertEqual(-1800, bounds["left"])
        self.assertEqual(800, bounds["width"])

    def test_region_rejects_invalid_size_and_desktop_overflow(self) -> None:
        backend = self.make_backend()
        for region, error_code in (
            ((0, 0, 0, 100), "invalid_region"),
            ((1800, 0, 200, 100), "region_out_of_bounds"),
        ):
            with self.subTest(region=region), self.assertRaises(LCUError) as context:
                backend._region_bounds(region)
            self.assertEqual(error_code, context.exception.code)

    def test_region_conflicts_with_active_window(self) -> None:
        backend = self.make_backend()
        with self.assertRaises(LCUError) as context:
            backend.screenshot(None, True, False, [0, 0, 100, 100])
        self.assertEqual("invalid_screenshot_options", context.exception.code)

    def test_list_windows_includes_bounds(self) -> None:
        backend = self.make_backend()
        backend.win32gui.GetForegroundWindow.return_value = 7
        backend.win32gui.IsWindowVisible.return_value = True
        backend.win32gui.GetWindowText.return_value = "Notepad"
        backend.win32gui.IsIconic.return_value = False
        backend.win32gui.GetWindowRect.return_value = (-100, 20, 700, 620)

        def enumerate_windows(callback: object, parameter: object) -> None:
            callback(7, parameter)

        backend.win32gui.EnumWindows.side_effect = enumerate_windows
        windows = backend.list_windows()
        self.assertEqual(800, windows[0]["bounds"]["width"])
        self.assertEqual(-100, windows[0]["bounds"]["left"])

    def test_window_resolver_prefers_exact_then_active(self) -> None:
        backend = self.make_backend()
        backend.list_windows = Mock(
            return_value=[
                {"hwnd": 1, "title": "Chrome - Docs", "active": False},
                {"hwnd": 2, "title": "Chrome", "active": True},
            ]
        )
        self.assertEqual(2, backend._resolve_window(" chrome ")["hwnd"])

        backend.list_windows.return_value = [
            {"hwnd": 1, "title": "Chrome - Docs", "active": False},
            {"hwnd": 2, "title": "Chrome - Search", "active": True},
        ]
        self.assertEqual(2, backend._resolve_window("chrome")["hwnd"])

    def test_window_resolver_rejects_ambiguous_and_missing(self) -> None:
        backend = self.make_backend()
        backend.list_windows = Mock(
            return_value=[
                {"hwnd": 1, "title": "Chrome - Docs", "active": False},
                {"hwnd": 2, "title": "Chrome - Search", "active": False},
            ]
        )
        with self.assertRaises(LCUError) as context:
            backend._resolve_window("chrome")
        self.assertEqual("ambiguous_window", context.exception.code)

        backend.list_windows.return_value = []
        with self.assertRaises(LCUError) as context:
            backend._resolve_window("chrome")
        self.assertEqual("window_not_found", context.exception.code)

    def test_set_window_bounds_supports_negative_monitor(self) -> None:
        backend = self.make_backend()
        backend._resolve_window = Mock(
            return_value={"hwnd": 7, "title": "Notepad", "active": False}
        )
        backend.win32gui.IsIconic.return_value = False
        backend.win32gui.IsZoomed.return_value = False
        result = backend.set_window_bounds("Notepad", -1920, 0, 1920, 1080)
        backend.win32gui.SetWindowPos.assert_called_once_with(
            7, 0, -1920, 0, 1920, 1080, 20
        )
        self.assertEqual(-1920, result["bounds"]["left"])

    def test_set_window_state_and_close_use_normal_window_messages(self) -> None:
        backend = self.make_backend()
        backend._resolve_window = Mock(
            return_value={"hwnd": 7, "title": "Notepad", "active": False}
        )
        state = backend.set_window_state("Notepad", "maximize")
        backend.win32gui.ShowWindow.assert_called_once_with(7, 3)
        self.assertEqual("maximize", state["state"])

        result = backend.close_window("Notepad")
        backend.win32gui.PostMessage.assert_called_once_with(7, 16, 0, 0)
        self.assertTrue(result["requested"])

    def test_wait_for_window_immediate_present_and_gone(self) -> None:
        backend = self.make_backend()
        backend._resolve_window = Mock(
            return_value={"hwnd": 7, "title": "Calculator", "active": True}
        )
        self.assertTrue(backend.wait_for_window("Calculator", "active", 1)["found"])

        backend._resolve_window.side_effect = LCUError(
            "window_not_found", "not found"
        )
        self.assertFalse(backend.wait_for_window("Calculator", "gone", 1)["found"])

    def test_wait_for_window_timeout_is_structured(self) -> None:
        backend = self.make_backend()
        backend._resolve_window = Mock(
            side_effect=LCUError("window_not_found", "not found")
        )
        with patch("windows_backend.time.sleep"), patch(
            "windows_backend.time.monotonic", side_effect=[0.0, 1.0]
        ):
            with self.assertRaises(LCUError) as context:
                backend.wait_for_window("Calculator", "present", 0.5)
        self.assertEqual("window_wait_timeout", context.exception.code)

    def test_shortcut_file_is_rejected_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            shortcut = Path(temp_dir) / "website.url"
            shortcut.write_text("URL=https://example.com", encoding="utf-8")
            with self.assertRaises(LCUError) as context:
                WindowsBackend.open_file(str(shortcut))
        self.assertEqual("executable_file_blocked", context.exception.code)


if __name__ == "__main__":
    unittest.main()

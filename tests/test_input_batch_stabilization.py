from __future__ import annotations

import ctypes
from unittest.mock import MagicMock, patch

import pytest

from scripts.lcu import batch, windows
from scripts.lcu.errors import LCUError


def test_sendinput_zero_is_an_error_without_text_leak() -> None:
    with patch.object(ctypes.windll.user32, "SendInput", return_value=0):
        with patch.object(windows, "init_windows_environment"):
            with pytest.raises(LCUError) as exc:
                windows.type_text("secret")
    assert exc.value.code == "input_dispatch_failed"
    assert "secret" not in exc.value.message


def test_hotkey_releases_pressed_keys_after_later_dispatch_failure() -> None:
    events = []

    def send(vk=0, scan=0, flags=0):
        events.append((vk, flags))
        if len(events) == 2:
            raise LCUError("input_dispatch_failed", "key press failed")

    with patch.object(windows, "init_windows_environment"), patch.object(windows, "_send_keybd_input", side_effect=send):
        with pytest.raises(LCUError):
            windows.hotkey(["CTRL", "V"])
    assert events == [(0x11, 0), (ord("V"), 0), (0x11, windows.KEYEVENTF_KEYUP)]


def test_stroke_retries_failed_release() -> None:
    events = []

    def send(vk=0, scan=0, flags=0):
        events.append(flags)
        if len(events) == 2:
            raise LCUError("input_dispatch_failed", "key release failed")

    with patch.object(windows, "init_windows_environment"), patch.object(windows, "_send_keybd_input", side_effect=send):
        with pytest.raises(LCUError):
            windows.press_key("TAB")
    assert events == [0, windows.KEYEVENTF_KEYUP, windows.KEYEVENTF_KEYUP]


def test_text_normalizes_crlf_and_sends_surrogate_pair() -> None:
    with patch.object(windows, "init_windows_environment"), patch.object(windows, "_send_keybd_input") as send:
        assert windows.type_text("A\r\nB😀한") == {"chars": 6}
    downs = [(call.kwargs["vk"], call.kwargs["scan"], call.kwargs["flags"])
             for call in send.call_args_list if not call.kwargs["flags"] & windows.KEYEVENTF_KEYUP]
    assert downs == [
        (0, ord("A"), windows.KEYEVENTF_UNICODE),
        (windows.VK_MAP["ENTER"], 0, 0),
        (0, ord("B"), windows.KEYEVENTF_UNICODE),
        (0, 0xD83D, windows.KEYEVENTF_UNICODE),
        (0, 0xDE00, windows.KEYEVENTF_UNICODE),
        (0, ord("한"), windows.KEYEVENTF_UNICODE),
    ]


def test_unpaired_surrogate_rejected_before_dispatch() -> None:
    with patch.object(windows, "init_windows_environment"), patch.object(windows, "_send_keybd_input") as send:
        with pytest.raises(LCUError):
            windows.type_text("valid\ud800")
    send.assert_not_called()


def test_drag_releases_button_and_restores_failsafe_after_move_error() -> None:
    gui = MagicMock()
    gui.FAILSAFE = True
    gui.moveTo.side_effect = [None, RuntimeError("move failed")]
    with patch.object(windows, "init_windows_environment"), patch.object(windows.time, "sleep"), patch.dict("sys.modules", {"pyautogui": gui}):
        with pytest.raises(RuntimeError, match="move failed"):
            windows.drag(10, 20, 30, 40)
    gui.mouseUp.assert_called_once_with(button="left")
    assert gui.FAILSAFE is True


def test_drag_normal_path_keeps_failsafe_and_releases_button() -> None:
    gui = MagicMock()
    gui.FAILSAFE = True
    with patch.object(windows, "init_windows_environment"), patch.object(windows.time, "sleep"), patch.dict("sys.modules", {"pyautogui": gui}):
        assert windows.drag(10, 20, 30, 40) == {"from": {"x": 10, "y": 20}, "to": {"x": 30, "y": 40}}
    gui.mouseUp.assert_called_once_with(button="left")
    assert gui.FAILSAFE is True


def test_drag_preserves_move_error_if_release_also_fails() -> None:
    gui = MagicMock()
    gui.FAILSAFE = True
    gui.moveTo.side_effect = [None, RuntimeError("move failed")]
    gui.mouseUp.side_effect = RuntimeError("release failed")
    with patch.object(windows, "init_windows_environment"), patch.object(windows.time, "sleep"), patch.dict("sys.modules", {"pyautogui": gui}):
        with pytest.raises(RuntimeError, match="move failed"):
            windows.drag(10, 20, 30, 40)
    gui.mouseUp.assert_called_once()
    assert gui.FAILSAFE is True


@pytest.mark.parametrize("bad", [
    {"action": "hotkey", "keys": [None]},
    {"action": "hotkey", "keys": [""]},
    {"action": "press_key", "key": "NOT_A_KEY"},
    {"action": "focus_window", "hwnd": True},
    {"action": "click", "x": float("nan"), "y": 1},
    {"action": "drag", "sx": 1, "sy": 2, "ex": 3, "ey": 4, "duration": float("inf")},
    {"action": "click", "x": 1, "y": 2, "capture": 7},
    {"action": "type_text", "text": "valid\ud800"},
    {"action": "set_clipboard", "text": "later", "delay_after": float("nan")},
])
def test_late_static_error_prevents_first_dispatch(bad: dict) -> None:
    with patch.object(windows, "set_clipboard") as clipboard:
        with pytest.raises(LCUError):
            batch.execute_batch([{"action": "set_clipboard", "text": "first"}, bad])
    clipboard.assert_not_called()


def test_batch_preserves_open_app_metadata_on_later_runtime_failure() -> None:
    metadata = {"hwnd": 123, "reused_existing": False, "launch_method": "test", "owned_processes": [42], "ready": True}
    with patch.object(batch.apps, "open_app", return_value=metadata), patch.object(windows, "click", side_effect=LCUError("stale_capture", "moved")):
        result = batch.execute_batch([{"action": "open_app", "name": "notepad"}, {"action": "click", "x": 1, "y": 2}])
    assert result["ok"] is False
    assert result["result"]["completed"] == 1
    assert result["result"]["failedIndex"] == 1
    assert result["result"]["results"] == [{"index": 0, "action": "open_app", "result": metadata}]


def test_batch_success_preserves_open_app_metadata() -> None:
    metadata = {"hwnd": 123, "reused_existing": False, "owned_processes": [42]}
    with patch.object(batch.apps, "open_app", return_value=metadata):
        result = batch.execute_batch([{"action": "open_app", "name": "notepad"}])
    assert result == {"ok": True, "action": "batch", "result": {"completed": 1, "results": [{"index": 0, "action": "open_app", "result": metadata}]}}


def test_failed_input_stops_batch_without_running_later_action() -> None:
    with patch.object(windows, "press_key", side_effect=LCUError("input_dispatch_failed", "failed")), patch.object(windows, "set_clipboard") as clipboard:
        result = batch.execute_batch([{"action": "press_key", "key": "A"}, {"action": "set_clipboard", "text": "later"}])
    assert result["result"]["completed"] == 0
    assert result["error"]["code"] == "input_dispatch_failed"
    clipboard.assert_not_called()

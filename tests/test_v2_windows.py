from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.lcu.errors import LCUError
from scripts.lcu.windows import (
    click,
    find_target_window,
    hotkey,
    press_key,
    set_window_bounds,
    type_text,
)


def test_find_target_window_ambiguity() -> None:
    mock_windows = [
        {"hwnd": 101, "title": "Chrome Tab 1", "process": "chrome.exe"},
        {"hwnd": 102, "title": "Chrome Tab 2", "process": "chrome.exe"},
    ]
    with patch("scripts.lcu.windows.list_windows", return_value=mock_windows):
        with pytest.raises(LCUError) as exc:
            find_target_window(query="Chrome")
        assert exc.value.code == "ambiguous_target"
        assert exc.value.candidates is not None
        assert len(exc.value.candidates) == 2


def test_find_target_window_not_found() -> None:
    with patch("scripts.lcu.windows.list_windows", return_value=[]):
        with pytest.raises(LCUError) as exc:
            find_target_window(query="NonExistent")
        assert exc.value.code == "window_not_found"


def test_set_window_bounds_validation() -> None:
    # Too small
    with pytest.raises(LCUError) as exc:
        set_window_bounds(x=0, y=0, width=40, height=100, hwnd=123)
    assert exc.value.code == "invalid_arguments"
    assert "at least 50px" in exc.value.message

    # Outside virtual screen
    with patch("win32api.GetSystemMetrics", side_effect=[0, 0, 1920, 1080]):
        with pytest.raises(LCUError) as exc:
            set_window_bounds(x=5000, y=5000, width=500, height=400, hwnd=123)
        assert exc.value.code == "invalid_arguments"
        assert "do not intersect virtual screen" in exc.value.message


def test_press_key_validation() -> None:
    with pytest.raises(LCUError) as exc:
        press_key("INVALID_KEY_NAME_XYZ")
    assert exc.value.code == "invalid_arguments"

    with pytest.raises(LCUError) as exc:
        press_key("ENTER", count=0)
    assert exc.value.code == "invalid_arguments"


def test_hotkey_validation() -> None:
    with pytest.raises(LCUError) as exc:
        hotkey([])
    assert exc.value.code == "invalid_arguments"

    with pytest.raises(LCUError) as exc:
        hotkey(["CTRL", "INVALID_HOTKEY_123"])
    assert exc.value.code == "invalid_arguments"


def test_click_validation() -> None:
    with pytest.raises(LCUError) as exc:
        click(x=10, y=20, button="invalid")
    assert exc.value.code == "invalid_arguments"

    with pytest.raises(LCUError) as exc:
        click(x=10, y=20, count=3)
    assert exc.value.code == "invalid_arguments"


def test_type_text_foreground_check() -> None:
    with patch("win32gui.IsWindow", return_value=True), patch(
        "win32gui.GetForegroundWindow", return_value=999
    ):
        with pytest.raises(LCUError) as exc:
            type_text("test", hwnd=123)
        assert exc.value.code == "window_not_foreground"

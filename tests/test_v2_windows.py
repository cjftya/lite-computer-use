from __future__ import annotations

from platform_mock import simulated_windows_os

from unittest.mock import MagicMock, patch

import pytest

from scripts.lcu.errors import LCUError
from scripts.lcu.windows import (
    click,
    close_window,
    find_target_window,
    focus_window,
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


def test_focus_window_attach_thread_success() -> None:
    target = {"hwnd": 100, "title": "My Target App", "process": "app.exe"}
    with patch("scripts.lcu.windows.find_target_window", return_value=target), \
         patch("win32gui.IsIconic", return_value=False), \
         patch("win32gui.ShowWindow"), \
         patch("win32gui.GetForegroundWindow", side_effect=[200, 100, 100, 100]), \
         patch("win32api.GetCurrentThreadId", return_value=1), \
         patch("win32process.GetWindowThreadProcessId", side_effect=[(0, 2), (0, 3)]), \
         patch("win32process.AttachThreadInput") as mock_attach, \
         patch("win32gui.BringWindowToTop"), \
         patch("win32gui.SetForegroundWindow"):
        res = focus_window(hwnd=100)
        assert res["hwnd"] == 100
        assert res["title"] == "My Target App"
        assert mock_attach.call_count >= 2


def test_focus_window_uwp_attach_thread_denied_fallback_success() -> None:
    target = {"hwnd": 100, "title": "UWP Calculator", "process": "ApplicationFrameHost.exe"}
    with patch("scripts.lcu.windows.find_target_window", return_value=target), \
         patch("win32gui.IsIconic", return_value=False), \
         patch("win32gui.ShowWindow"), \
         patch("win32gui.GetForegroundWindow", side_effect=[200, 200, 100, 100]), \
         patch("win32api.GetCurrentThreadId", return_value=1), \
         patch("win32process.GetWindowThreadProcessId", side_effect=[(0, 2), (0, 3)]), \
         patch("win32process.AttachThreadInput", side_effect=Exception("(5, 'AttachThreadInput', '액세스가 거부되었습니다.')")), \
         patch("win32gui.BringWindowToTop"), \
         patch("win32gui.SetForegroundWindow"), \
         patch("ctypes.windll.user32.keybd_event") as mock_keybd:
        res = focus_window(hwnd=100)
        assert res["hwnd"] == 100
        assert res["title"] == "UWP Calculator"
        assert mock_keybd.call_count >= 2


def test_focus_window_fallback_failure() -> None:
    target = {"hwnd": 100, "title": "Stubborn Window", "process": "stubborn.exe"}
    with patch("scripts.lcu.windows.find_target_window", return_value=target), \
         patch("win32gui.IsIconic", return_value=False), \
         patch("win32gui.ShowWindow"), \
         patch("win32gui.GetForegroundWindow", return_value=200), \
         patch("win32api.GetCurrentThreadId", return_value=1), \
         patch("win32process.GetWindowThreadProcessId", side_effect=[(0, 2), (0, 3)]), \
         patch("win32process.AttachThreadInput", side_effect=Exception("Access Denied")), \
         patch("win32gui.BringWindowToTop"), \
         patch("win32gui.SetForegroundWindow"):
        with pytest.raises(LCUError) as exc_info:
            focus_window(hwnd=100)
        assert exc_info.value.code == "window_focus_failed"
        assert "Failed to focus window" in exc_info.value.message


# ============================================================================
# Phase 15 / Section 21 close_window Tests
# ============================================================================

def test_close_window_normal_destruction() -> None:
    """정상 종료: WM_CLOSE -> window disappears -> closed=true"""
    target = {"hwnd": 100, "title": "Test Window", "process": "test.exe"}
    with patch("scripts.lcu.windows.find_target_window", return_value=target), \
         patch("win32gui.PostMessage") as mock_post, \
         patch("win32gui.IsWindow", return_value=0), \
         simulated_windows_os():
        res = close_window(hwnd=100)
        assert res["hwnd"] == 100
        assert res["title"] == "Test Window"
        assert res["closed"] is True
        mock_post.assert_called_once()
        import win32con
        assert mock_post.call_args[0][1] == win32con.WM_CLOSE


def test_close_window_late_destruction() -> None:
    """늦은 종료: 첫 polling에서는 존재, 다음 polling에서 소멸 -> success"""
    target = {"hwnd": 100, "title": "Late Window", "process": "late.exe"}
    with patch("scripts.lcu.windows.find_target_window", return_value=target), \
         patch("win32gui.PostMessage") as mock_post, \
         patch("win32gui.IsWindow", side_effect=[1, 0]), \
         patch("win32gui.IsWindowVisible", side_effect=[1, 0]), \
         patch("time.sleep") as mock_sleep, \
         simulated_windows_os():
        res = close_window(hwnd=100, timeout=1.0, interval=0.05)
        assert res["hwnd"] == 100
        assert res["closed"] is True
        mock_post.assert_called_once()
        assert mock_sleep.call_count == 2


def test_close_window_timeout_failure() -> None:
    """종료 실패: timeout까지 hwnd 유지 -> window_close_failed"""
    target = {"hwnd": 100, "title": "Unclosable Window", "process": "app.exe"}
    with patch("scripts.lcu.windows.find_target_window", return_value=target), \
         patch("win32gui.PostMessage"), \
         patch("win32gui.IsWindow", return_value=1), \
         patch("win32gui.IsWindowVisible", return_value=1), \
         patch("time.sleep"), \
         simulated_windows_os():
        with pytest.raises(LCUError) as exc_info:
            close_window(hwnd=100, timeout=0.1, interval=0.05)
        assert exc_info.value.code == "window_close_failed"
        assert "within 0.1s" in exc_info.value.message


def test_close_window_no_force_kill() -> None:
    """강제 종료 금지: TerminateProcess, taskkill, os.kill 등이 호출되지 않는지 보장"""
    target = {"hwnd": 100, "title": "Stubborn Window", "process": "app.exe"}
    with patch("scripts.lcu.windows.find_target_window", return_value=target), \
         patch("win32gui.PostMessage"), \
         patch("win32gui.IsWindow", return_value=1), \
         patch("win32gui.IsWindowVisible", return_value=1), \
         patch("time.sleep"), \
         simulated_windows_os(), \
         patch("subprocess.Popen") as mock_popen, \
         patch("subprocess.run") as mock_run, \
         patch("os.kill") as mock_os_kill:
        with pytest.raises(LCUError) as exc_info:
            close_window(hwnd=100, timeout=0.1, interval=0.05)
        assert exc_info.value.code == "window_close_failed"
        # Ensure no force killing tools were ever invoked
        mock_popen.assert_not_called()
        mock_run.assert_not_called()
        mock_os_kill.assert_not_called()


def test_close_window_hidden_only_fails() -> None:
    """Test B2: IsWindow=true, IsWindowVisible=false 상태만으로 성공 처리 금지 -> window_close_failed"""
    target = {"hwnd": 100, "title": "Hidden Window", "process": "app.exe"}
    with patch("scripts.lcu.windows.find_target_window", return_value=target), \
         patch("win32gui.PostMessage"), \
         patch("win32gui.IsWindow", return_value=1), \
         patch("win32gui.IsWindowVisible", return_value=0), \
         patch("time.sleep"), \
         simulated_windows_os():
        with pytest.raises(LCUError) as exc_info:
            close_window(hwnd=100, timeout=0.1, interval=0.05)
        assert exc_info.value.code == "window_close_failed"


def test_close_window_cloaked_only_fails() -> None:
    """Test B3: IsWindow=true, DWM cloaked=true 상태만으로 성공 처리 금지 -> window_close_failed"""
    target = {"hwnd": 100, "title": "Cloaked Window", "process": "app.exe"}
    with patch("scripts.lcu.windows.find_target_window", return_value=target), \
         patch("win32gui.PostMessage"), \
         patch("win32gui.IsWindow", return_value=1), \
         patch("time.sleep"), \
         simulated_windows_os():
        with pytest.raises(LCUError) as exc_info:
            close_window(hwnd=100, timeout=0.1, interval=0.05)
        assert exc_info.value.code == "window_close_failed"



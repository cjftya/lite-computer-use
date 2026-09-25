from __future__ import annotations

from platform_mock import simulated_windows_os

from unittest.mock import MagicMock, patch

from scripts.lcu.launch_context import get_input_desktop_status


def test_input_desktop_mismatch_is_detected_and_handle_closed() -> None:
    user32 = MagicMock()
    user32.OpenInputDesktop.return_value = 123
    with simulated_windows_os('scripts.lcu.launch_context'), patch(
        "scripts.lcu.launch_context._desktop_context",
        return_value=({"status": "ok", "value": "WinSta0"},
                      {"status": "ok", "value": "CodexSandboxDesktop"}),
    ), patch(
        "scripts.lcu.launch_context._configure_desktop_apis", return_value=(user32, MagicMock())
    ), patch(
        "scripts.lcu.launch_context._user_object_name",
        return_value={"status": "ok", "value": "Default"},
    ):
        result = get_input_desktop_status()

    assert result["status"] == "ok"
    assert result["attached"] is False
    user32.OpenInputDesktop.assert_called_once_with(0, False, 0x0001)
    user32.CloseDesktop.assert_called_once_with(123)


def test_input_desktop_match_allows_interactive_host() -> None:
    user32 = MagicMock()
    user32.OpenInputDesktop.return_value = 456
    with simulated_windows_os('scripts.lcu.launch_context'), patch(
        "scripts.lcu.launch_context._desktop_context",
        return_value=({"status": "ok", "value": "WinSta0"},
                      {"status": "ok", "value": "Default"}),
    ), patch(
        "scripts.lcu.launch_context._configure_desktop_apis", return_value=(user32, MagicMock())
    ), patch(
        "scripts.lcu.launch_context._user_object_name",
        return_value={"status": "ok", "value": "default"},
    ):
        result = get_input_desktop_status()

    assert result["attached"] is True
    user32.CloseDesktop.assert_called_once_with(456)

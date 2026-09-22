from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.lcu.batch import execute_batch, validate_batch_actions
from scripts.lcu.errors import LCUError


def test_validate_batch_empty() -> None:
    with pytest.raises(LCUError) as exc:
        validate_batch_actions([])
    assert exc.value.code == "invalid_arguments"


def test_validate_batch_max_limit() -> None:
    actions = [{"action": "set_clipboard", "text": "hi"}] * 13
    with pytest.raises(LCUError) as exc:
        validate_batch_actions(actions)
    assert exc.value.code == "invalid_arguments"
    assert "exceeds maximum" in exc.value.message


def test_validate_batch_disallowed_actions() -> None:
    disallowed = ["screenshot", "list_windows", "find_path", "get_clipboard", "get_mouse_position", "doctor", "app_status"]
    for action in disallowed:
        with pytest.raises(LCUError) as exc:
            validate_batch_actions([{"action": action}])
        assert exc.value.code == "invalid_arguments"
        assert "observation tool" in exc.value.message


def test_validate_batch_delay_range() -> None:
    with pytest.raises(LCUError) as exc:
        validate_batch_actions([{"action": "set_clipboard", "text": "hi", "delay_after": -0.1}])
    assert exc.value.code == "invalid_arguments"

    with pytest.raises(LCUError) as exc:
        validate_batch_actions([{"action": "set_clipboard", "text": "hi", "delay_after": 5.1}])
    assert exc.value.code == "invalid_arguments"


def test_batch_execution_success() -> None:
    actions = [
        {"action": "set_clipboard", "text": "one", "delay_after": 0.01},
        {"action": "set_clipboard", "text": "two"},
    ]
    with patch("scripts.lcu.windows.set_clipboard") as mock_clip:
        res = execute_batch(actions)
        assert res["ok"] is True
        assert res["result"]["completed"] == 2
        assert mock_clip.call_count == 2


def test_batch_execution_fail_fast() -> None:
    actions = [
        {"action": "set_clipboard", "text": "first"},
        {"action": "click", "x": 100, "y": 200},
        {"action": "set_clipboard", "text": "third"},
    ]

    with patch("scripts.lcu.windows.set_clipboard") as mock_clip, patch(
        "scripts.lcu.windows.click", side_effect=LCUError("stale_capture", "Window moved")
    ) as mock_click:
        res = execute_batch(actions)
        assert res["ok"] is False
        assert res["result"]["completed"] == 1
        assert res["result"]["failedIndex"] == 1
        assert res["result"]["failedAction"] == "click"
        assert res["error"]["code"] == "stale_capture"
        # Ensure third step was never called
        assert mock_clip.call_count == 1


def test_batch_pre_validation_zero_side_effects_on_invalid_second_action() -> None:
    # Second action is invalid (missing x, y)
    actions = [
        {"action": "set_clipboard", "text": "should_never_run"},
        {"action": "click"},
    ]
    with patch("scripts.lcu.windows.set_clipboard") as mock_clip:
        with pytest.raises(LCUError) as exc:
            execute_batch(actions)
        assert exc.value.code == "invalid_arguments"
        assert "click" in exc.value.message
        # First action MUST NOT have been executed!
        mock_clip.assert_not_called()


def test_batch_pre_validation_zero_side_effects_on_invalid_last_action() -> None:
    # Third action is invalid (missing text)
    actions = [
        {"action": "set_clipboard", "text": "should_never_run"},
        {"action": "click", "x": 100, "y": 200},
        {"action": "type_text"},
    ]
    with patch("scripts.lcu.windows.set_clipboard") as mock_clip, patch(
        "scripts.lcu.windows.click"
    ) as mock_click:
        with pytest.raises(LCUError) as exc:
            execute_batch(actions)
        assert exc.value.code == "invalid_arguments"
        assert "type_text" in exc.value.message
        mock_clip.assert_not_called()
        mock_click.assert_not_called()


def test_batch_action_schema_validation_details() -> None:
    # open_app missing name
    with pytest.raises(LCUError) as exc:
        validate_batch_actions([{"action": "open_app"}])
    assert exc.value.code == "invalid_arguments"

    # open_url invalid scheme
    with pytest.raises(LCUError) as exc:
        validate_batch_actions([{"action": "open_url", "url": "ftp://bad.com"}])
    assert exc.value.code == "invalid_arguments"

    # click invalid count
    with pytest.raises(LCUError) as exc:
        validate_batch_actions([{"action": "click", "x": 10, "y": 20, "count": 3}])
    assert exc.value.code == "invalid_arguments"

    # drag missing coordinates
    with pytest.raises(LCUError) as exc:
        validate_batch_actions([{"action": "drag", "sx": 10}])
    assert exc.value.code == "invalid_arguments"

    # press_key count 0
    with pytest.raises(LCUError) as exc:
        validate_batch_actions([{"action": "press_key", "key": "ENTER", "count": 0}])
    assert exc.value.code == "invalid_arguments"

    # hotkey empty
    with pytest.raises(LCUError) as exc:
        validate_batch_actions([{"action": "hotkey", "keys": []}])
    assert exc.value.code == "invalid_arguments"

    # set_window_bounds too small
    with pytest.raises(LCUError) as exc:
        validate_batch_actions([{"action": "set_window_bounds", "x": 0, "y": 0, "width": 40, "height": 100, "hwnd": 123}])
    assert exc.value.code == "invalid_arguments"

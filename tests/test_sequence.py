from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from helpers import AppDefinition, LCUError
from lcu_tools import main, parse_sequence, run_sequence


class SequenceValidationTests(unittest.TestCase):
    def test_accepts_only_bounded_deterministic_actions(self) -> None:
        steps = [
            {"action": "launch-app", "name": "chrome"},
            {
                "action": "wait_for_window",
                "title": "Chrome",
                "state": "present",
                "timeout": 5,
            },
            {"action": "move_mouse", "x": 10, "y": 20},
            {"action": "click", "x": 10, "y": 20, "button": "left"},
            {"action": "focus-window", "title": "Chrome"},
            {"action": "hotkey", "keys": ["CTRL", "L"]},
            {"action": "type_text", "text": "OpenAI"},
            {"action": "press_key", "key": "ENTER", "count": 1},
        ]
        parsed = parse_sequence(json.dumps(steps))
        self.assertEqual("launch_app", parsed[0]["action"])
        self.assertEqual("focus_window", parsed[4]["action"])
        self.assertEqual(steps[1:4], parsed[1:4])
        self.assertEqual(steps[5:], parsed[5:])

    def test_rejects_malformed_json(self) -> None:
        with self.assertRaises(LCUError) as context:
            parse_sequence("[not-json]")
        self.assertEqual("invalid_sequence_json", context.exception.code)

    def test_rejects_more_than_eight_actions(self) -> None:
        value = json.dumps([{"action": "press_key", "key": "TAB"}] * 9)
        with self.assertRaises(LCUError) as context:
            parse_sequence(value)
        self.assertEqual("invalid_sequence_length", context.exception.code)

    def test_rejects_screenshot_and_unknown_fields(self) -> None:
        cases = (
            ([{"action": "screenshot"}], "sequence_action_not_allowed"),
            ([{"action": "drag"}], "sequence_action_not_allowed"),
            (
                [{"action": "type_text", "text": "safe", "retry": True}],
                "invalid_sequence_step",
            ),
        )
        for value, code in cases:
            with self.subTest(value=value), self.assertRaises(LCUError) as context:
                parse_sequence(json.dumps(value))
            self.assertEqual(code, context.exception.code)

    def test_validates_all_steps_before_execution(self) -> None:
        backend = Mock()
        value = json.dumps(
            [
                {"action": "press_key", "key": "TAB"},
                {"action": "press_key", "key": "TAB", "count": 101},
            ]
        )
        with self.assertRaises(LCUError) as context:
            run_sequence(backend, value)
        self.assertEqual("invalid_sequence_step", context.exception.code)
        backend.press_key.assert_not_called()


class SequenceExecutionTests(unittest.TestCase):
    def test_runs_expanded_actions_in_order(self) -> None:
        backend = Mock()
        registry = Mock()
        app = AppDefinition("chrome", ("browser",), ("chrome.exe",))
        registry.resolve.return_value = app
        value = json.dumps(
            [
                {"action": "launch_app", "name": "chrome"},
                {"action": "wait_for_window", "title": "Chrome"},
                {"action": "move_mouse", "x": 10, "y": 20},
                {
                    "action": "click",
                    "x": 10,
                    "y": 20,
                    "relative_to": "active-window",
                    "button": "right",
                },
            ]
        )

        result = run_sequence(backend, value, registry)

        self.assertEqual(4, result["completed"])
        backend.launch_app.assert_called_once_with(app)
        backend.wait_for_window.assert_called_once_with("Chrome", "present", 10.0)
        backend.move_mouse.assert_called_once_with(10, 20, "screen")
        backend.click.assert_called_once_with(
            10, 20, "active-window", clicks=1, button="right"
        )

    def test_preserves_action_result_order(self) -> None:
        backend = Mock()
        backend.focus_window.return_value = {"hwnd": 7, "title": "Chrome"}
        backend.hotkey.return_value = {"keys": ["ctrl", "l"]}
        backend.type_text.return_value = {"length": 6}
        backend.press_key.return_value = {"key": "enter", "count": 1}
        value = json.dumps(
            [
                {"action": "focus_window", "title": "Chrome"},
                {"action": "hotkey", "keys": ["CTRL", "L"]},
                {"action": "type_text", "text": "OpenAI"},
                {"action": "press_key", "key": "ENTER"},
            ]
        )

        result = run_sequence(backend, value)

        self.assertEqual(4, result["completed"])
        self.assertEqual(
            ["focus_window", "hotkey", "type_text", "press_key"],
            [item["action"] for item in result["results"]],
        )
        backend.focus_window.assert_called_once_with("Chrome")
        backend.hotkey.assert_called_once_with(["CTRL", "L"])
        backend.type_text.assert_called_once_with("OpenAI", 0.0)
        backend.press_key.assert_called_once_with("ENTER", 1)

    def test_stops_at_first_lcu_failure(self) -> None:
        backend = Mock()
        backend.press_key.side_effect = [
            {"key": "tab", "count": 1},
            LCUError("input_failed", "keyboard rejected input"),
        ]
        value = json.dumps(
            [
                {"action": "press_key", "key": "TAB"},
                {"action": "press_key", "key": "ENTER"},
                {"action": "press_key", "key": "ESC"},
            ]
        )

        with self.assertRaises(LCUError) as context:
            run_sequence(backend, value)

        error = context.exception
        self.assertEqual("sequence_failed", error.code)
        self.assertEqual(1, error.details["completed"])
        self.assertEqual(1, error.details["failedIndex"])
        self.assertEqual("input_failed", error.details["cause"]["code"])
        self.assertEqual(
            [call("TAB", 1), call("ENTER", 1)], backend.press_key.call_args_list
        )

    def test_cli_failure_reports_partial_result_and_duration(self) -> None:
        backend = Mock()
        backend.press_key.side_effect = [
            {"key": "tab", "count": 1},
            LCUError("input_failed", "keyboard rejected input"),
        ]
        value = json.dumps(
            [
                {"action": "press_key", "key": "TAB"},
                {"action": "press_key", "key": "ENTER"},
            ]
        )
        output = io.StringIO()
        with (
            patch("lcu_tools.windows_backend", return_value=backend),
            patch("lcu_tools.append_action_log"),
            patch("sys.stdout", output),
        ):
            return_code = main(["sequence", "--json", value])

        payload = json.loads(output.getvalue())
        self.assertEqual(2, return_code)
        self.assertEqual("sequence_failed", payload["error"]["code"])
        self.assertEqual(1, payload["result"]["completed"])
        self.assertEqual(1, payload["result"]["failedIndex"])
        self.assertEqual(
            "input_failed", payload["error"]["details"]["cause"]["code"]
        )
        self.assertGreaterEqual(payload["meta"]["durationMs"], 0)


if __name__ == "__main__":
    unittest.main()

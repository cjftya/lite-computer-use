from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "lcu_tools.py"
sys.path.insert(0, str(ROOT / "scripts"))

from lcu_tools import build_parser, run_action


class CLITests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_list_apps_returns_json(self) -> None:
        completed = self.run_cli("list_apps")
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertIn("chrome", payload["result"]["apps"])
        self.assertGreaterEqual(payload["meta"]["durationMs"], 0)

    @unittest.skipIf(os.name == "nt", "Non-Windows behavior only")
    def test_windows_action_returns_structured_platform_error(self) -> None:
        completed = self.run_cli("get_active_window")
        self.assertEqual(2, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual("unsupported_platform", payload["error"]["code"])

    def test_alias_reports_canonical_action(self) -> None:
        completed = self.run_cli("list-apps")
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("list_apps", payload["action"])

    @unittest.skipIf(os.name == "nt", "Parser-only platform test")
    def test_new_command_aliases_parse(self) -> None:
        commands = (
            ("move-mouse", "1", "2"),
            ("open-folder", "."),
            ("reveal-file", "example.txt"),
            ("get-mouse-position",),
            ("set-window-state", "Notepad", "maximize"),
            ("set-window-bounds", "Notepad", "0", "0", "800", "600"),
            ("close-window", "Notepad"),
            ("wait-for-window", "Notepad"),
        )
        for command in commands:
            with self.subTest(command=command):
                completed = self.run_cli(*command)
                self.assertEqual(2, completed.returncode)
                payload = json.loads(completed.stdout)
                self.assertEqual(
                    command[0].replace("-", "_"), payload["action"]
                )
                self.assertEqual("unsupported_platform", payload["error"]["code"])

    def test_region_and_active_window_are_rejected_by_backend_contract(self) -> None:
        completed = self.run_cli(
            "screenshot", "--region", "0", "0", "100", "100", "--active-window"
        )
        if os.name != "nt":
            self.assertEqual(2, completed.returncode)
            payload = json.loads(completed.stdout)
            self.assertEqual("unsupported_platform", payload["error"]["code"])
            self.assertGreaterEqual(payload["meta"]["durationMs"], 0)

    @unittest.skipIf(os.name == "nt", "Non-Windows behavior only")
    def test_sequence_rejects_disallowed_action_before_backend_use(self) -> None:
        completed = self.run_cli(
            "sequence", "--json", '[{"action":"screenshot"}]'
        )
        self.assertEqual(2, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("sequence_action_not_allowed", payload["error"]["code"])

    def test_invalid_arguments_are_structured_json(self) -> None:
        completed = self.run_cli("--unknown-option")
        self.assertEqual(2, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("invalid_arguments", payload["error"]["code"])
        self.assertEqual("parse", payload["error"]["details"]["stage"])

    def test_relative_config_path_is_rejected(self) -> None:
        completed = self.run_cli("--config", "config/apps.yaml", "doctor")
        self.assertEqual(2, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("relative_path_not_allowed", payload["error"]["code"])
        self.assertEqual("validate_config", payload["error"]["details"]["stage"])

    def test_doctor_uses_runtime_root_from_a_different_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                [sys.executable, str(CLI), "doctor"],
                cwd=temp_dir,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)
        result = json.loads(completed.stdout)["result"]
        self.assertEqual(str(ROOT), result["runtime"]["projectRoot"])
        self.assertEqual(str(CLI), result["runtime"]["scriptPath"])
        self.assertEqual("1.4.0", result["version"])

    @unittest.skipIf(os.name == "nt", "Non-Windows parser test")
    def test_sequence_accepts_utf8_file_and_stdin(self) -> None:
        sequence = '[{"action":"type_text","text":"한글"}]'
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sequence.json"
            path.write_text(sequence, encoding="utf-8-sig")
            from_file = self.run_cli("sequence", "--file", str(path))
        from_stdin = subprocess.run(
            [sys.executable, str(CLI), "sequence", "--stdin"],
            cwd=ROOT,
            input=sequence,
            text=True,
            capture_output=True,
            check=False,
        )
        for completed in (from_file, from_stdin):
            with self.subTest(args=completed.args):
                self.assertEqual(2, completed.returncode)
                payload = json.loads(completed.stdout)
                self.assertEqual("unsupported_platform", payload["error"]["code"])

    def test_sequence_inputs_are_mutually_exclusive(self) -> None:
        completed = self.run_cli("sequence", "--json", "[]", "--stdin")
        self.assertEqual(2, completed.returncode)
        self.assertEqual(
            "invalid_arguments", json.loads(completed.stdout)["error"]["code"]
        )

    def test_direct_open_route_never_constructs_gui_backend(self) -> None:
        args = build_parser().parse_args(["open_file", str(ROOT / "README.md")])
        direct = Mock()
        direct.open_file.return_value = {"status": "dispatch_accepted"}
        with patch("lcu_tools.direct_backend", return_value=direct), patch(
            "lcu_tools.windows_backend", side_effect=AssertionError("GUI backend loaded")
        ):
            result = run_action(args)
        self.assertEqual("dispatch_accepted", result["status"])
        direct.open_file.assert_called_once_with(str(ROOT / "README.md"))

    def test_targeted_standalone_input_loads_alias_registry(self) -> None:
        args = build_parser().parse_args(["type_text", "한글", "--target", "크롬"])
        backend = Mock()
        backend.ensure_input_target.return_value = {"hwnd": 7, "pid": 10}
        backend.type_text.return_value = {"length": 2}
        with patch("lcu_tools.windows_backend", return_value=backend) as factory:
            result = run_action(args)
        registry = factory.call_args.args[0]
        self.assertEqual("chrome", registry.resolve("크롬").name)
        backend.ensure_input_target.assert_called_once_with("크롬", None, None)
        backend.type_text.assert_called_once_with("한글", 0.0)
        self.assertTrue(result["target"]["foregroundVerified"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "lcu_tools.py"


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
        # Platform validation happens before the sequence parser because all
        # sequence actions are Windows primitives.
        self.assertEqual(2, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("unsupported_platform", payload["error"]["code"])


if __name__ == "__main__":
    unittest.main()

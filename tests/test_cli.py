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


if __name__ == "__main__":
    unittest.main()

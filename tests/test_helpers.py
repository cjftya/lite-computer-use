from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.helpers import (
    ActionLock,
    AppRegistry,
    LCUError,
    append_action_log,
    find_files,
    normalize_name,
    safe_log_details,
)

ROOT = Path(__file__).resolve().parents[1]


class AppRegistryTests(unittest.TestCase):
    def test_resolves_english_and_korean_aliases(self) -> None:
        registry = AppRegistry.load(ROOT / "config" / "apps.yaml")
        self.assertEqual("chrome", registry.resolve("  Google   Chrome ").name)
        self.assertEqual("notepad", registry.resolve("메모장").name)

    def test_unknown_app_is_an_expected_error(self) -> None:
        registry = AppRegistry.load(ROOT / "config" / "apps.yaml")
        with self.assertRaises(LCUError) as context:
            registry.resolve("not-real")
        self.assertEqual("app_not_registered", context.exception.code)


class FileSearchTests(unittest.TestCase):
    def test_finds_partial_name_and_sorts_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            older = root / "contract-old.pdf"
            newer = root / "Contract final.pdf"
            ignored = root / "notes.txt"
            older.write_text("old", encoding="utf-8")
            newer.write_text("new", encoding="utf-8")
            ignored.write_text("no", encoding="utf-8")
            now = time.time()
            os.utime(older, (now - 20, now - 20))
            os.utime(newer, (now, now))

            matches = find_files("CONTRACT", [root], limit=10)

            self.assertEqual(
                [newer.name, older.name], [item["name"] for item in matches]
            )

    def test_empty_query_is_rejected(self) -> None:
        with self.assertRaises(LCUError) as context:
            find_files("  ", [], limit=10)
        self.assertEqual("invalid_query", context.exception.code)


class SafetyTests(unittest.TestCase):
    def test_sensitive_text_is_not_returned_in_log_details(self) -> None:
        secret = "do-not-log-this"
        details = safe_log_details("type_text", {"text": secret})
        self.assertNotIn(secret, json.dumps(details))
        self.assertEqual(len(secret), details["length"])

    def test_url_log_contains_only_host(self) -> None:
        details = safe_log_details(
            "open_url",
            {"url": "https://example.com/private?token=secret"},
        )
        self.assertEqual({"host": "example.com"}, details)

    def test_normalize_name_collapses_case_and_spaces(self) -> None:
        self.assertEqual("google chrome", normalize_name(" Google   Chrome "))

    def test_window_logs_do_not_include_title(self) -> None:
        secret_title = "Confidential merger notes"
        details = safe_log_details(
            "set_window_bounds",
            {"title": secret_title, "x": 0, "y": 0, "width": 800, "height": 600},
        )
        self.assertNotIn(secret_title, json.dumps(details))
        self.assertEqual(len(secret_title), details["query_length"])

    def test_sequence_log_does_not_include_typed_text(self) -> None:
        secret = "do-not-log-this-sequence-text"
        payload = json.dumps([{"action": "type_text", "text": secret}])
        details = safe_log_details("sequence", {"sequence_json": payload})
        self.assertNotIn(secret, json.dumps(details))
        self.assertEqual(len(payload), details["payload_length"])

    def test_action_log_records_nonnegative_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("scripts.helpers.runtime_root", return_value=Path(temp_dir)):
                append_action_log("hotkey", True, {"keys": ["ctrl", "l"]}, -1.0)
            record = json.loads(
                (Path(temp_dir) / "logs" / "actions.jsonl").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(0.0, record["durationMs"])

    def test_action_lock_rejects_concurrent_owner(self) -> None:
        with (
            ActionLock(timeout=0.1),
            self.assertRaises(LCUError) as context,
            ActionLock(timeout=0.05),
        ):
            pass
        self.assertEqual("busy", context.exception.code)


if __name__ == "__main__":
    unittest.main()

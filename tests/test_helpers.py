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
    known_folders,
    normalize_name,
    safe_log_details,
    search_entries,
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

    def test_result_limit_stops_large_walk_and_marks_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(200):
                (root / f"match-{index:03d}.txt").write_text("x", encoding="utf-8")
            result = search_entries("match", [root], limit=1)
        self.assertEqual(1, len(result["matches"]))
        self.assertLess(result["visitedCount"], 200)
        self.assertTrue(result["incomplete"])
        self.assertEqual("result_limit", result["stoppedReason"])

    def test_folder_search_and_explicit_root_scope(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_root = Path(first)
            second_root = Path(second)
            (first_root / "Project Alpha").mkdir()
            (second_root / "Project Beta").mkdir()
            result = search_entries("Project", [first_root], kind="folder")
        self.assertEqual(["Project Alpha"], [item["name"] for item in result["matches"]])
        self.assertEqual([str(first_root)], result["roots"])

    def test_visited_budget_marks_search_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(20):
                (root / f"other-{index}.txt").write_text("x", encoding="utf-8")
            result = search_entries("missing", [root], max_visited=5)
        self.assertEqual(5, result["visitedCount"])
        self.assertTrue(result["truncated"])
        self.assertEqual("visited_limit", result["stoppedReason"])

    def test_default_excludes_can_be_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ignored = root / "node_modules"
            ignored.mkdir()
            (ignored / "target.txt").write_text("x", encoding="utf-8")
            excluded = search_entries("target", [root])
            included = search_entries("target", [root], include_ignored=True)
        self.assertEqual([], excluded["matches"])
        self.assertEqual(1, len(included["matches"]))

    def test_relative_search_root_is_rejected(self) -> None:
        with self.assertRaises(LCUError) as context:
            search_entries("anything", [Path("relative")])
        self.assertEqual("relative_path_not_allowed", context.exception.code)

    def test_explicit_missing_root_is_not_silently_skipped(self) -> None:
        missing = Path(tempfile.gettempdir()) / "lcu-definitely-missing-search-root"
        with self.assertRaises(LCUError) as context:
            search_entries("anything", [missing], strict_roots=True)
        self.assertEqual("search_root_not_found", context.exception.code)

    def test_depth_limit_and_exclusions_are_disclosed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "deep").mkdir()
            (root / "node_modules").mkdir()
            result = search_entries("missing", [root], max_depth=0)
        self.assertTrue(result["incomplete"])
        self.assertEqual("depth_limit", result["stoppedReason"])
        self.assertTrue(result["excludedByPolicy"])

    def test_known_folder_fallback_discloses_source(self) -> None:
        with patch("scripts.helpers.os.name", "posix"):
            folders = known_folders()
        self.assertEqual({"desktop", "documents", "downloads"}, set(folders))
        self.assertTrue(all(item["fallbackUsed"] for item in folders.values()))


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

    def test_path_log_uses_extension_and_fingerprint_only(self) -> None:
        secret_path = r"C:\Users\me\Secret Client\contract.pdf"
        details = safe_log_details("open_file", {"path": secret_path})
        self.assertNotIn(secret_path, json.dumps(details))
        self.assertIn("targetFingerprint", details)

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

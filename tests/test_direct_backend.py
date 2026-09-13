from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from direct_backend import DirectWindowsBackend, _dispatch_error, _expand_path
from helpers import LCUError


class PathContractTests(unittest.TestCase):
    def test_empty_and_relative_paths_are_rejected(self) -> None:
        for value, code in (
            ("", "invalid_path"),
            ("   ", "invalid_path"),
            ("notes/report.pdf", "relative_path_not_allowed"),
            ("C:notes\\report.pdf", "drive_relative_path"),
            ("\\root-relative\\report.pdf", "root_relative_path"),
        ):
            with self.subTest(value=value), self.assertRaises(LCUError) as context:
                _expand_path(value)
            self.assertEqual(code, context.exception.code)

    def test_unresolved_environment_variable_is_rejected(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LCUError) as context:
                _expand_path("%LCU_MISSING%\\report.pdf")
        self.assertEqual("unresolved_environment_variable", context.exception.code)

    def test_absolute_path_is_independent_of_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as cwd:
            file_path = Path(temp_dir) / "한글, document.pdf"
            file_path.write_text("test", encoding="utf-8")
            original = Path.cwd()
            try:
                os.chdir(cwd)
                with patch("direct_backend.os.startfile", create=True) as startfile:
                    result = DirectWindowsBackend.open_file(str(file_path))
            finally:
                os.chdir(original)
        startfile.assert_called_once_with(str(file_path))
        self.assertEqual(str(file_path), result["path"])
        self.assertEqual("unverified", result["verification"])

    def test_reveal_preserves_spaces_korean_and_commas_as_one_argument(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "한글, document.pdf"
            file_path.write_text("test", encoding="utf-8")
            with patch("direct_backend.subprocess.Popen") as popen:
                DirectWindowsBackend.reveal_file(str(file_path))
        popen.assert_called_once_with(
            ["explorer.exe", f"/select,{file_path}"], close_fds=True
        )

    def test_dispatch_errors_remain_distinct(self) -> None:
        for error_number, code in ((5, "access_denied"), (1155, "file_association_missing")):
            exc = OSError(error_number, "failure")
            exc.winerror = error_number
            with self.subTest(error_number=error_number):
                self.assertEqual(code, _dispatch_error(exc, "open_file").code)

    def test_access_denied_during_validation_is_not_reported_as_missing(self) -> None:
        with patch.object(Path, "stat", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(LCUError) as context:
                DirectWindowsBackend.open_file(str(Path(tempfile.gettempdir()) / "private.pdf"))
        self.assertEqual("access_denied", context.exception.code)
        self.assertEqual("validate", context.exception.details["stage"])

    def test_default_open_reports_dispatch_not_document_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "document.pdf"
            file_path.write_text("test", encoding="utf-8")
            with patch("direct_backend.os.startfile", create=True):
                result = DirectWindowsBackend.open_file(str(file_path))
        self.assertTrue(result["dispatchAccepted"])
        self.assertFalse(result["osStateVerified"])
        self.assertEqual("dispatch_accepted", result["status"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from helpers import LCUError
from windows_backend import INPUT, WindowsBackend


class WindowsBackendSafetyTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "ctypes.wintypes uses host-native sizes")
    def test_send_input_structure_has_native_windows_size(self) -> None:
        expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        self.assertEqual(expected, ctypes.sizeof(INPUT))

    def test_non_http_url_is_rejected_before_launch(self) -> None:
        with self.assertRaises(LCUError) as context:
            WindowsBackend.open_url("file:///C:/Windows/System32/calc.exe")
        self.assertEqual("invalid_url", context.exception.code)

    def test_executable_file_is_rejected_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "sample.exe"
            executable.write_bytes(b"not executable")
            with self.assertRaises(LCUError) as context:
                WindowsBackend.open_file(str(executable))
        self.assertEqual("executable_file_blocked", context.exception.code)

    def test_shortcut_file_is_rejected_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            shortcut = Path(temp_dir) / "website.url"
            shortcut.write_text("URL=https://example.com", encoding="utf-8")
            with self.assertRaises(LCUError) as context:
                WindowsBackend.open_file(str(shortcut))
        self.assertEqual("executable_file_blocked", context.exception.code)


if __name__ == "__main__":
    unittest.main()

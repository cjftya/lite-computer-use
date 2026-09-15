from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

LCU_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "lcu.py"


def run_lcu(*args: str) -> tuple[int, dict[str, Any]]:
    cmd = [sys.executable, str(LCU_SCRIPT)] + list(args)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout)
    except Exception:
        data = {"stdout": proc.stdout, "stderr": proc.stderr}
    return proc.returncode, data


def test_cli_doctor() -> None:
    code, data = run_lcu("doctor")
    assert code == 0
    assert data["ok"] is True
    assert data["action"] == "doctor"
    assert data["result"]["os_windows"] is True
    assert data["result"]["dependencies"]["PIL"] is True


def test_cli_get_mouse_position() -> None:
    code, data = run_lcu("get_mouse_position")
    assert code == 0
    assert data["ok"] is True
    assert "x" in data["result"]
    assert "y" in data["result"]


def test_cli_clipboard() -> None:
    code, data = run_lcu("set_clipboard", "cli_test_string_123")
    assert code == 0
    assert data["ok"] is True

    code2, data2 = run_lcu("get_clipboard")
    assert code2 == 0
    assert data2["ok"] is True
    assert data2["result"]["text"] == "cli_test_string_123"


def test_cli_invalid_arguments() -> None:
    # Invalid URL
    code, data = run_lcu("open_url", "ftp://invalid.com")
    assert code == 1
    assert data["ok"] is False
    assert data["error"]["code"] == "invalid_arguments"

    # Invalid region (negative or zero)
    code, data = run_lcu("screenshot", "--region", "10", "10", "0", "50")
    assert code == 1
    assert data["ok"] is False
    assert data["error"]["code"] == "invalid_arguments"


def test_cli_batch_fail_fast() -> None:
    payload = json.dumps([
        {"action": "set_clipboard", "text": "cli_step_1"},
        {"action": "open_file", "path": "C:\\non_existent_path_xyz123.txt"},
    ])
    code, data = run_lcu("batch", payload)
    assert code == 1
    assert data["ok"] is False
    assert data["result"]["completed"] == 1
    assert data["result"]["failedIndex"] == 1
    assert data["error"]["code"] == "not_found"

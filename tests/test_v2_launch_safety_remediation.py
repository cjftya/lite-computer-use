from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from scripts.lcu.apps import AppEntry, open_app
from scripts.lcu.launch_context import _desktop_context, get_launch_context_snapshot
from scripts.lcu.ownership import authorize_owned_processes, load_owned_processes
from scripts.lcu.processes import (
    ProcessIdentity,
    ProcessSnapshot,
    terminate_process,
    validate_termination_safety,
)


def _identity(pid: int = 101, creation_time: int = 1000) -> ProcessIdentity:
    return ProcessIdentity(
        pid=pid,
        parent_pid=1,
        process_name="Code.exe",
        image_path=r"C:\Apps\Code.exe",
        creation_time=creation_time,
        session_id=1,
    )


def test_d01_diagnostics_never_emit_prefix_secret_values() -> None:
    secrets = {
        "NODE_AUTH_TOKEN": "node-secret-value",
        "VSCODE_PRIVATE_TOKEN": "vscode-secret-value",
        "CHROME_API_KEY": "chrome-secret-value",
        "Path": r"C:\Windows\System32",
    }

    encoded = json.dumps(get_launch_context_snapshot(secrets))

    for value in secrets.values():
        assert value not in encoded
    assert "NODE_AUTH_TOKEN" in encoded
    assert get_launch_context_snapshot(secrets)["gui_env_normalization"]["applied"] is False


def test_d02_desktop_api_failure_is_reported_as_error() -> None:
    with patch("scripts.lcu.launch_context.os.name", "nt"), patch(
        "scripts.lcu.launch_context._configure_desktop_apis",
        side_effect=OSError("desktop unavailable"),
    ):
        station, desktop = _desktop_context()

    assert station["status"] == "error"
    assert desktop["status"] == "error"
    assert station["value"] is None


def test_d03_path_lookup_is_case_insensitive() -> None:
    upper = get_launch_context_snapshot({"PATH": "/one:/two"})["path"]
    mixed = get_launch_context_snapshot({"Path": "/one:/two"})["path"]

    assert upper == mixed


def test_s01_untrusted_baseline_disables_ownership() -> None:
    identity = _identity()
    entry = AppEntry(
        name="vscode",
        target="code.exe",
        source="config",
        aliases=["vscode"],
        normalized="vscode",
        commands=["code.exe"],
        process_cleanup={"success": "owned-after-close", "process_names": ["Code.exe"]},
    )
    detected = {
        "hwnd": 9001,
        "title": "Visual Studio Code",
        "process": "Code.exe",
        "pid": 101,
        "active": True,
    }

    with patch("scripts.lcu.apps.load_owned_processes", return_value=[]), patch(
        "scripts.lcu.apps.build_app_index", return_value=[entry]
    ), patch("scripts.lcu.apps.find_matching_windows", return_value=[]), patch(
        "scripts.lcu.windows.list_windows", return_value=[]
    ), patch(
        "scripts.lcu.apps.snapshot_processes",
        side_effect=[
            ProcessSnapshot(status="error", complete=False),
            {},
        ],
    ), patch(
        "scripts.lcu.apps.dispatch_candidate",
        return_value={
            "sanitized_env_applied": True,
            "dispatch_identity": identity.to_dict(),
        },
    ), patch(
        "scripts.lcu.apps._poll_for_launched_window", return_value=detected
    ), patch(
        "scripts.lcu.windows.focus_window", return_value={"hwnd": 9001}
    ), patch("scripts.lcu.apps.remember_owned_processes"), patch(
        "scripts.lcu.apps.get_launch_context_snapshot", return_value={}
    ), patch("os.name", "nt"):
        result = open_app("vscode", debug=True)

    assert result["owned_processes"] == []
    assert "baseline_process_snapshot_untrusted" in result["debug"]["safety_warnings"][0]


def test_s02_missing_creation_or_session_blocks_termination() -> None:
    no_creation = ProcessIdentity(101, 1, "Code.exe", r"C:\Apps\Code.exe", None, 1)
    no_session = ProcessIdentity(101, 1, "Code.exe", r"C:\Apps\Code.exe", 1000, None)

    assert validate_termination_safety(no_creation)[0] is False
    assert validate_termination_safety(no_session)[0] is False


def test_s03_window_enumeration_unknown_blocks_termination() -> None:
    with patch("scripts.lcu.processes.get_current_session_id", return_value=1), patch(
        "scripts.lcu.processes.is_same_process", return_value=True
    ), patch("scripts.lcu.processes.has_visible_windows", return_value=None):
        safe, reason = validate_termination_safety(_identity())

    assert safe is False
    assert "could not be verified" in reason


def test_s04_atomic_termination_handle_rechecks_identity() -> None:
    kernel32 = MagicMock()
    kernel32.OpenProcess.return_value = 55
    reused = _identity(creation_time=2000)
    fake_windll = MagicMock(kernel32=kernel32)

    with patch("scripts.lcu.processes.os.name", "nt"), patch.object(
        __import__("scripts.lcu.processes", fromlist=["ctypes"]).ctypes,
        "windll",
        fake_windll,
        create=True,
    ), patch("scripts.lcu.processes._identity_from_handle", return_value=reused), patch(
        "scripts.lcu.processes.get_current_session_id", return_value=1
    ), patch("scripts.lcu.processes.has_visible_windows", return_value=False):
        assert terminate_process(_identity(creation_time=1000)) is False

    kernel32.TerminateProcess.assert_not_called()
    kernel32.CloseHandle.assert_called_once_with(55)


def test_s05_open_process_failure_is_not_reported_as_success() -> None:
    kernel32 = MagicMock()
    kernel32.OpenProcess.return_value = 0
    fake_windll = MagicMock(kernel32=kernel32)

    with patch("scripts.lcu.processes.os.name", "nt"), patch.object(
        __import__("scripts.lcu.processes", fromlist=["ctypes"]).ctypes,
        "windll",
        fake_windll,
        create=True,
    ):
        assert terminate_process(_identity()) is False


def test_l06_caller_metadata_without_ledger_evidence_is_rejected() -> None:
    candidate = _identity().to_dict()
    candidate["ownership_evidence"] = "exact-dispatch-identity"

    with patch("scripts.lcu.ownership.owned_processes_for_window", return_value=[]):
        assert authorize_owned_processes(9001, 101, [candidate]) == []


def test_l02_identity_lookup_error_preserves_record_but_never_authorizes(tmp_path) -> None:
    ledger = tmp_path / "owned-processes.json"
    record = _identity().to_dict()
    record.update(
        {
            "hwnd": 9001,
            "window_pid": 101,
            "ownership_evidence": "exact-dispatch-identity",
        }
    )
    ledger.write_text(json.dumps({"version": 1, "records": [record]}), encoding="utf-8")

    with patch("scripts.lcu.ownership.get_ledger_path", return_value=ledger), patch(
        "scripts.lcu.ownership.is_same_process", return_value=None
    ):
        loaded = load_owned_processes()
        assert loaded[0]["validation_status"] == "unknown"
        assert authorize_owned_processes(9001, 101, [record]) == []

    assert json.loads(ledger.read_text(encoding="utf-8"))["records"]

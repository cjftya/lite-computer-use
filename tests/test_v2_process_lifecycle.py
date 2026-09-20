from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from scripts.lcu.apps import (
    AppEntry,
    LaunchCandidate,
    candidate_priority_key,
    load_config_apps,
    open_app,
)
from scripts.lcu.errors import LCUError
from scripts.lcu.processes import (
    SYSTEM_PROCESS_DENYLIST,
    ProcessIdentity,
    get_process_identity,
    has_visible_windows,
    is_process_alive,
    is_same_process,
    snapshot_processes,
    terminate_process,
    validate_termination_safety,
)
from scripts.lcu.windows import close_window


# ============================================================================
# Section 29: Tests — Process Snapshot (P1 - P4)
# ============================================================================

def test_p1_snapshot_fields() -> None:
    """P1: snapshot 결과에 pid, process_name, creation_time, session_id 존재"""
    # Test on real system or mock
    procs = snapshot_processes()
    if procs:
        sample = next(iter(procs.values()))
        assert hasattr(sample, "pid")
        assert hasattr(sample, "process_name")
        assert hasattr(sample, "creation_time")
        assert hasattr(sample, "session_id")
        assert hasattr(sample, "parent_pid")
        assert hasattr(sample, "image_path")


def test_p2_pid_reuse_creation_time_mismatch() -> None:
    """P2: 동일 PID라도 creation_time이 다르면 is_same_process = False"""
    ident1 = ProcessIdentity(
        pid=99999,
        parent_pid=1,
        process_name="notepad.exe",
        image_path=r"C:\Windows\System32\notepad.exe",
        creation_time=1000000,
        session_id=1,
    )
    ident2 = ProcessIdentity(
        pid=99999,
        parent_pid=1,
        process_name="notepad.exe",
        image_path=r"C:\Windows\System32\notepad.exe",
        creation_time=2000000,  # Reused PID with different creation time
        session_id=1,
    )

    with patch("scripts.lcu.processes.get_process_identity", return_value=ident2):
        assert is_same_process(ident1) is False


def test_p3_baseline_process_not_owned() -> None:
    """P3: baseline process는 owned가 아님"""
    baseline_ident = ProcessIdentity(
        pid=1001,
        parent_pid=1,
        process_name="chrome.exe",
        image_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        creation_time=500000,
        session_id=1,
    )
    # Baseline check in validate_termination_safety
    safe, reason = validate_termination_safety(
        identity=baseline_ident,
        baseline_pids={1001},
        allowed_process_names=["chrome.exe"],
    )
    assert safe is False
    assert "baseline" in reason


def test_p4_after_only_process_is_new_candidate() -> None:
    """P4: after-only process만 new candidate"""
    before = {
        101: ProcessIdentity(101, 1, "proc1.exe", None, 10, 1),
        102: ProcessIdentity(102, 1, "proc2.exe", None, 20, 1),
    }
    after = {
        101: ProcessIdentity(101, 1, "proc1.exe", None, 10, 1),
        102: ProcessIdentity(102, 1, "proc2.exe", None, 20, 1),
        201: ProcessIdentity(201, 1, "newapp.exe", None, 30, 1),
    }

    new_pids = set(after.keys()) - set(before.keys())
    assert new_pids == {201}


# ============================================================================
# Section 30: Tests — Notepad (N1 - N3)
# ============================================================================

def test_n1_notepad_broker_launch_does_not_claim_process_ownership() -> None:
    """A Shell/broker launch cannot claim a same-name process as LCU-owned."""
    entry = AppEntry(
        name="notepad",
        target=r"shell:AppsFolder\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App",
        source="config",
        aliases=["notepad", "메모장"],
        normalized="notepad",
        commands=[r"shell:AppsFolder\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App", "notepad.exe"],
        process_cleanup={"mode": "owned-after-close", "process_names": ["Notepad.exe"]},
    )

    notepad_ident = ProcessIdentity(
        pid=100,
        parent_pid=1,
        process_name="Notepad.exe",
        image_path=r"C:\Windows\System32\notepad.exe",
        creation_time=1234567,
        session_id=1,
    )
    mock_win = {"hwnd": 7771, "title": "Untitled - Notepad", "process": "Notepad.exe", "pid": 100, "active": True}

    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("scripts.lcu.apps.snapshot_processes", side_effect=[{}, {}, {100: notepad_ident}]), \
         patch("scripts.lcu.windows.list_windows", side_effect=[[], [], [mock_win]]), \
         patch("scripts.lcu.windows.focus_window", return_value={"hwnd": 7771, "title": "Untitled - Notepad"}), \
         patch("os.name", "nt"), \
         patch("os.startfile"):
        res = open_app("notepad")
        assert res["app"] == "notepad"
        assert res["hwnd"] == 7771
        assert res["reused_existing"] is False
        assert res["window_pid"] == 100
        assert res["owned_processes"] == []


def test_n2_notepad_cleanup_terminates_lingering_owned_process() -> None:
    """N2: close_window -> HWND destroyed -> PID 100 remains -> natural exit wait -> still alive -> PID 100 terminate"""
    notepad_ident = ProcessIdentity(
        pid=100,
        parent_pid=1,
        process_name="Notepad.exe",
        image_path=r"C:\Windows\System32\notepad.exe",
        creation_time=1234567,
        session_id=1,
    )
    target = {"hwnd": 7771, "title": "Untitled - Notepad", "process": "Notepad.exe", "pid": 100}
    owned = notepad_ident.to_dict()
    owned["cleanup_mode"] = "owned-after-close"
    owned["ownership_evidence"] = "exact-dispatch-identity"

    with patch("scripts.lcu.windows.find_target_window", return_value=target), \
         patch("scripts.lcu.ownership.authorize_owned_processes", return_value=[owned]), \
         patch("win32gui.PostMessage"), \
         patch("win32gui.IsWindow", return_value=0), \
         patch("scripts.lcu.processes.is_process_alive", return_value=True), \
         patch("scripts.lcu.processes.validate_termination_safety", return_value=(True, "ok")), \
         patch("scripts.lcu.processes.terminate_process", return_value=True) as mock_terminate, \
         patch("time.sleep"), \
         patch("os.name", "nt"):
        res = close_window(
            hwnd=7771,
            owned_processes=[owned],
        )
        assert res["closed"] is True
        assert res["cleaned_processes"] == [100]
        mock_terminate.assert_called_once()


def test_n2b_close_window_recovers_owned_processes_from_ledger() -> None:
    """A later CLI invocation can recover exact HWND/PID-bound ownership metadata."""
    notepad_ident = ProcessIdentity(
        pid=101,
        parent_pid=1,
        process_name="Notepad.exe",
        image_path=r"C:\Windows\System32\notepad.exe",
        creation_time=7654321,
        session_id=1,
    )
    owned = notepad_ident.to_dict()
    owned["cleanup_mode"] = "owned-after-close"
    owned["ownership_evidence"] = "exact-dispatch-identity"
    target = {"hwnd": 7773, "title": "Untitled - Notepad", "process": "Notepad.exe", "pid": 101}

    with patch("scripts.lcu.windows.find_target_window", return_value=target), \
         patch("scripts.lcu.ownership.owned_processes_for_window", return_value=[owned]) as lookup, \
         patch("scripts.lcu.ownership.forget_owned_processes") as forget, \
         patch("win32gui.PostMessage"), \
         patch("win32gui.IsWindow", return_value=0), \
         patch("scripts.lcu.processes.is_process_alive", return_value=False), \
         patch("os.name", "nt"):
        result = close_window(hwnd=7773)

    assert result["closed"] is True
    lookup.assert_called_once_with(hwnd=7773, window_pid=101)
    forget.assert_called_once()


def test_n3_existing_notepad_preserved() -> None:
    """N3: BEFORE: Notepad PID 200 + visible HWND -> open_app notepad -> reused_existing=true, owned_processes=[]"""
    entry = AppEntry(
        name="notepad",
        target="notepad.exe",
        source="config",
        aliases=["notepad", "메모장"],
        normalized="notepad",
        commands=["notepad.exe"],
    )
    existing_win = {"hwnd": 7772, "title": "My Notes - Notepad", "process": "notepad.exe", "pid": 200, "active": True}

    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("scripts.lcu.windows.list_windows", return_value=[existing_win]), \
         patch("scripts.lcu.windows.focus_window", return_value={"hwnd": 7772, "title": "My Notes - Notepad"}), \
         patch("os.name", "nt"):
        res = open_app("notepad")
        assert res["reused_existing"] is True
        assert res["hwnd"] == 7772
        assert res["owned_processes"] == []


# ============================================================================
# Section 31: Tests — Chrome (C1 - C4)
# ============================================================================

def test_c1_c2_chrome_new_window_with_background_baseline() -> None:
    """C1 & C2: background Chrome PIDs exist, no visible window -> open_app chrome dispatches --new-window -> baseline PID protected (owned_processes=[])"""
    bg_chrome_ident = ProcessIdentity(
        pid=5555,
        parent_pid=1,
        process_name="chrome.exe",
        image_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        creation_time=999999,
        session_id=1,
    )
    # Config entry with priority 0 --new-window
    chrome_cmd = LaunchCandidate(
        target="chrome.exe",
        method="exe",
        source="config",
        args=("--new-window", "about:blank"),
        priority=0,
    )
    entry = AppEntry(
        name="chrome",
        target="chrome.exe",
        source="config",
        aliases=["chrome", "google chrome"],
        normalized="chrome",
        candidates=[chrome_cmd, LaunchCandidate("chrome.exe", "exe", "config")],
        process_cleanup={"mode": "rollback-on-failure", "process_names": ["chrome.exe"]},
    )

    # Window created attached to baseline Chrome PID 5555
    mock_new_win = {"hwnd": 8881, "title": "Google Chrome", "process": "chrome.exe", "pid": 5555, "active": True}

    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("scripts.lcu.apps.snapshot_processes", return_value={5555: bg_chrome_ident}), \
         patch("scripts.lcu.windows.list_windows", side_effect=[[], [], [mock_new_win]]), \
         patch("scripts.lcu.windows.focus_window", return_value={"hwnd": 8881, "title": "Google Chrome"}), \
         patch("scripts.lcu.apps.dispatch_candidate", return_value={"sanitized_env_applied": True}) as mock_dispatch, \
         patch("os.name", "nt"):
        res = open_app("chrome")
        # Priority 0 candidate dispatched with --new-window
        mock_dispatch.assert_called_once_with(chrome_cmd)

        # C1: visible window found
        assert res["hwnd"] == 8881
        assert res["reused_existing"] is False

        # C2: Baseline PID 5555 must NOT be in owned_processes!
        assert res["owned_processes"] == []


def test_c3_chrome_cleanup_preserves_baseline() -> None:
    """C3: 새 Chrome window를 닫더라도 baseline Chrome process는 살아 있어야 함"""
    target = {"hwnd": 8881, "title": "Google Chrome", "process": "chrome.exe", "pid": 5555}
    with patch("scripts.lcu.windows.find_target_window", return_value=target), \
         patch("win32gui.PostMessage"), \
         patch("win32gui.IsWindow", return_value=0), \
         patch("scripts.lcu.processes.terminate_process") as mock_terminate, \
         patch("os.name", "nt"):
        # owned_processes is empty
        res = close_window(hwnd=8881, owned_processes=[])
        assert res["closed"] is True
        mock_terminate.assert_not_called()


def test_c4_chrome_failed_launch_rollback() -> None:
    """C4: new chrome PID created, but visible window never appeared -> rollback terminates new PID only, baseline preserved"""
    baseline_ident = ProcessIdentity(5555, 1, "chrome.exe", None, 100, 1)
    failed_new_ident = ProcessIdentity(6666, 5555, "chrome.exe", None, 200, 1)

    entry = AppEntry(
        name="chrome",
        target="chrome.exe",
        source="config",
        aliases=["chrome"],
        normalized="chrome",
        commands=["chrome.exe"],
        process_cleanup={"mode": "rollback-on-failure", "process_names": ["chrome.exe"]},
    )

    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("scripts.lcu.apps.snapshot_processes", side_effect=[
             {5555: baseline_ident},  # baseline
             {5555: baseline_ident},  # before candidate
             {5555: baseline_ident, 6666: failed_new_ident},  # staged-wait liveness
             {5555: baseline_ident, 6666: failed_new_ident},  # after candidate failure
         ]), \
         patch("scripts.lcu.windows.list_windows", return_value=[]), \
         patch("scripts.lcu.apps.terminate_process", return_value=True) as mock_terminate, \
         patch("scripts.lcu.apps.validate_termination_safety", return_value=(True, "ok")), \
         patch("time.sleep"), \
         patch("os.name", "nt"), \
         patch("scripts.lcu.apps.dispatch_candidate", return_value={
             "sanitized_env_applied": True,
             "dispatch_identity": failed_new_ident.to_dict(),
         }):
        with pytest.raises(LCUError) as exc_info:
            open_app("chrome")
        assert exc_info.value.code == "dispatch_failed"
        # Only new PID 6666 was terminated, NOT 5555!
        mock_terminate.assert_called_once_with(failed_new_ident)


# ============================================================================
# Section 32: Tests — VS Code (V1 - V3)
# ============================================================================

def test_v1_v2_vscode_new_window_with_daemon_processes() -> None:
    """V1 & V2: daemon Code.exe processes exist, no visible window -> code.exe --new-window dispatched -> baseline Code PID protected"""
    bg_code_ident = ProcessIdentity(7001, 1, "Code.exe", None, 100, 1)
    code_cand = LaunchCandidate(
        target="code.exe",
        method="exe",
        source="config",
        args=("--new-window",),
        priority=0,
    )
    entry = AppEntry(
        name="vscode",
        target="code.exe",
        source="config",
        aliases=["vscode"],
        normalized="vscode",
        candidates=[code_cand],
        process_cleanup={"mode": "rollback-on-failure", "process_names": ["Code.exe"]},
    )
    mock_new_win = {"hwnd": 9991, "title": "Welcome - Visual Studio Code", "process": "Code.exe", "pid": 7001, "active": True}

    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("scripts.lcu.apps.snapshot_processes", return_value={7001: bg_code_ident}), \
         patch("scripts.lcu.windows.list_windows", side_effect=[[], [], [mock_new_win]]), \
         patch("scripts.lcu.windows.focus_window", return_value={"hwnd": 9991, "title": "Welcome - Visual Studio Code"}), \
         patch("scripts.lcu.apps.dispatch_candidate", return_value={"sanitized_env_applied": True}) as mock_dispatch, \
         patch("os.name", "nt"):
        res = open_app("vscode")
        mock_dispatch.assert_called_once_with(code_cand)
        assert res["hwnd"] == 9991
        # Baseline Code PID 7001 must NOT be in owned_processes
        assert res["owned_processes"] == []


def test_v3_vscode_failed_launch_rollback() -> None:
    """V3: failed launch rollback terminates newly created Code PID only"""
    baseline_code = ProcessIdentity(7001, 1, "Code.exe", None, 100, 1)
    new_orphan_code = ProcessIdentity(7002, 1, "Code.exe", None, 200, 1)

    entry = AppEntry(
        name="vscode",
        target="code.exe",
        source="config",
        aliases=["vscode"],
        normalized="vscode",
        commands=["code.exe"],
        process_cleanup={"mode": "rollback-on-failure", "process_names": ["Code.exe"]},
    )

    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("scripts.lcu.apps.snapshot_processes", side_effect=[
            {7001: baseline_code},
            {7001: baseline_code},
            {7001: baseline_code, 7002: new_orphan_code},
            {7001: baseline_code, 7002: new_orphan_code},
        ]), \
         patch("scripts.lcu.windows.list_windows", return_value=[]), \
         patch("scripts.lcu.apps.terminate_process", return_value=True) as mock_terminate, \
         patch("scripts.lcu.apps.validate_termination_safety", return_value=(True, "ok")), \
         patch("time.sleep"), \
         patch("os.name", "nt"), \
         patch("scripts.lcu.apps.dispatch_candidate", return_value={
             "sanitized_env_applied": True,
             "dispatch_identity": new_orphan_code.to_dict(),
         }):
        with pytest.raises(LCUError) as exc_info:
            open_app("vscode")
        assert exc_info.value.code == "dispatch_failed"
        mock_terminate.assert_called_once_with(new_orphan_code)


# ============================================================================
# Section 33: Tests — Safety (S1 - S4)
# ============================================================================

def test_s1_no_wholesale_process_kill() -> None:
    """S1: taskkill /IM, Stop-Process -Name 등 프로세스 이름 일괄 종료 금지"""
    # Verify that nowhere in lcu codebase is taskkill or Stop-Process invoked
    import scripts.lcu.apps as lcu_apps
    import scripts.lcu.windows as lcu_windows
    import scripts.lcu.processes as lcu_procs

    for mod in (lcu_apps, lcu_windows, lcu_procs):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "taskkill" not in src
        assert "Stop-Process" not in src


def test_s2_system_process_denylist_rejection() -> None:
    """S2: ApplicationFrameHost, RuntimeBroker, explorer 등은 terminate 금지"""
    for denied in ("ApplicationFrameHost.exe", "RuntimeBroker.exe", "explorer.exe", "dwm.exe"):
        ident = ProcessIdentity(
            pid=1234,
            parent_pid=1,
            process_name=denied,
            image_path=rf"C:\Windows\System32\{denied}",
            creation_time=5000,
            session_id=1,
        )
        safe, reason = validate_termination_safety(ident, allowed_process_names=[denied])
        assert safe is False
        assert "SYSTEM_PROCESS_DENYLIST" in reason


def test_s3_pid_reuse_mismatch_blocks_termination() -> None:
    """S3: PID reuse identity mismatch 시 terminate 금지"""
    original = ProcessIdentity(5001, 1, "notepad.exe", None, 1000, 1)
    reused = ProcessIdentity(5001, 1, "notepad.exe", None, 2000, 1)

    with patch("scripts.lcu.processes.get_process_identity", return_value=reused), \
         patch("scripts.lcu.processes.get_current_session_id", return_value=1):
        safe, reason = validate_termination_safety(original, allowed_process_names=["notepad.exe"])
        assert safe is False
        assert "identity verification failed" in reason


def test_s4_other_visible_window_blocks_termination() -> None:
    """S4: owned PID가 다른 visible window도 소유한다면 process terminate 금지"""
    ident = ProcessIdentity(6001, 1, "notepad.exe", None, 1000, 1)

    with patch("scripts.lcu.processes.has_visible_windows", return_value=True), \
         patch("scripts.lcu.processes.is_same_process", return_value=True), \
         patch("scripts.lcu.processes.get_current_session_id", return_value=1):
        safe, reason = validate_termination_safety(ident, allowed_process_names=["notepad.exe"])
        assert safe is False
        assert "still owns visible top-level windows" in reason


# ============================================================================
# Section 24 & 25: Timeout and IsWindow Exception Tests
# ============================================================================

def test_close_window_iswindow_exception_does_not_count_as_closed() -> None:
    """Section 25: IsWindow 예외 발생 시 closed=true 처리 금지 -> window_close_failed"""
    target = {"hwnd": 100, "title": "Crash Window", "process": "app.exe"}
    with patch("scripts.lcu.windows.find_target_window", return_value=target), \
         patch("win32gui.PostMessage"), \
         patch("win32gui.IsWindow", side_effect=Exception("RPC failure")), \
         patch("time.sleep"), \
         patch("os.name", "nt"):
        with pytest.raises(LCUError) as exc_info:
            close_window(hwnd=100, timeout=0.1, interval=0.05)
        assert exc_info.value.code == "window_close_failed"

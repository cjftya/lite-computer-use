from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from scripts.lcu.apps import (
    APP_WINDOW_TIMEOUT,
    AppEntry,
    LaunchCandidate,
    dispatch_candidate,
    is_matching_window,
    open_app,
)
from scripts.lcu.launch_context import build_gui_launch_env, get_launch_context_snapshot
from scripts.lcu.ownership import (
    load_owned_processes,
    owned_processes_for_window,
    remember_owned_processes,
)
from scripts.lcu.processes import ProcessIdentity


def test_gui_launch_env_drops_only_confirmed_cli_inheritance() -> None:
    source = {
        "Path": r"C:\Windows\System32",
        "USERPROFILE": r"C:\Users\tester",
        "ELECTRON_RUN_AS_NODE": "1",
        "electron_no_attach_console": "1",
        "VSCODE_IPC_HOOK_CLI": r"\\.\pipe\vscode-test",
        "NODE_OPTIONS": "--trace-warnings",
        "CUSTOM_SETTING": "keep",
    }

    normalized = build_gui_launch_env(source)

    assert "ELECTRON_RUN_AS_NODE" not in normalized
    assert "electron_no_attach_console" not in normalized
    assert "VSCODE_IPC_HOOK_CLI" not in normalized
    assert normalized["NODE_OPTIONS"] == "--trace-warnings"
    assert normalized["Path"] == source["Path"]
    assert normalized["USERPROFILE"] == source["USERPROFILE"]
    assert normalized["CUSTOM_SETTING"] == "keep"


def test_launch_context_reports_selected_env_and_path_hash_only() -> None:
    source = {
        "PATH": "/one:/two",
        "SHELL": "/bin/bash",
        "ELECTRON_RUN_AS_NODE": "1",
        "UNRELATED_SECRET": "do-not-report",
    }

    snapshot = get_launch_context_snapshot(source)

    assert snapshot["environment"]["ELECTRON_RUN_AS_NODE"]["value"] == "1"
    assert snapshot["environment"]["SHELL"]["present"] is True
    assert "/bin/bash" not in json.dumps(snapshot["environment"])
    assert snapshot["path"]["sha256"]
    assert "PATH" not in snapshot["environment"]
    assert "UNRELATED_SECRET" not in json.dumps(snapshot)


def test_dispatch_executable_uses_sanitized_env_and_detached_stdio(tmp_path: Path) -> None:
    candidate = LaunchCandidate("code.exe", "exe", "config", args=("--new-window",))
    process = MagicMock(pid=321)
    source_env = {
        "USERPROFILE": str(tmp_path),
        "PATH": "test-path",
        "ELECTRON_RUN_AS_NODE": "1",
        "VSCODE_IPC_HOOK_CLI": "pipe",
        "NODE_OPTIONS": "--trace-warnings",
    }

    with patch.dict("os.environ", source_env, clear=True), patch(
        "scripts.lcu.apps.resolve_executable", return_value="code.exe"
    ), patch("subprocess.Popen", return_value=process) as popen:
        result = dispatch_candidate(candidate)

    command = popen.call_args.args[0]
    kwargs = popen.call_args.kwargs
    assert command == ["code.exe", "--new-window"]
    assert "ELECTRON_RUN_AS_NODE" not in kwargs["env"]
    assert "VSCODE_IPC_HOOK_CLI" not in kwargs["env"]
    assert kwargs["env"]["NODE_OPTIONS"] == "--trace-warnings"
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert result["sanitized_env_applied"] is True


def test_candidate_dedupe_preserves_args_wrappers_and_shell_fallback() -> None:
    entry = AppEntry(
        name="vscode",
        target="code.exe",
        source="config",
        aliases=["vscode"],
        normalized="vscode",
        candidates=[
            LaunchCandidate("code.exe", "exe", "config", args=("--new-window",), priority=0),
            LaunchCandidate("code.exe", "exe", "config"),
            LaunchCandidate("code.cmd", "exe", "config"),
            LaunchCandidate(r"C:\Menu\Visual Studio Code.lnk", "start-menu", "start-menu"),
        ],
    )

    assert [(candidate.method, candidate.target) for candidate in entry.candidates] == [
        ("exe", "code.exe"),
        ("exe", "code.exe"),
        ("exe", "code.cmd"),
        ("start-menu", r"C:\Menu\Visual Studio Code.lnk"),
    ]


def test_chrome_window_match_rejects_gpt_pwa() -> None:
    entry = AppEntry(
        name="chrome",
        target="chrome.exe",
        source="config",
        aliases=["chrome", "google chrome"],
        normalized="chrome",
        commands=["chrome.exe"],
        window_match={
            "process_names": ["chrome.exe"],
            "title_contains_any": ["Google Chrome"],
        },
    )

    assert not is_matching_window(
        {"title": "ChatGPT", "process": "chrome.exe"},
        entry,
    )
    assert is_matching_window(
        {"title": "New Tab - Google Chrome", "process": "chrome.exe"},
        entry,
    )


def test_shared_wait_does_not_depend_on_dispatcher_lifetime() -> None:
    identity = ProcessIdentity(101, 1, "Code.exe", None, 1000, 1)
    entry = AppEntry(
        name="vscode",
        target="code.exe",
        source="config",
        aliases=["vscode"],
        normalized="vscode",
        commands=["code.exe"],
        process_cleanup={"success": "window-only", "failure": "rollback-owned", "process_names": ["Code.exe"]},
    )
    detected = {
        "hwnd": 9001,
        "title": "Visual Studio Code",
        "process": "Code.exe",
        "pid": 101,
        "active": True,
    }

    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]
    ), patch("scripts.lcu.apps.find_matching_windows", return_value=[]), patch(
        "scripts.lcu.windows.list_windows", return_value=[]
    ), patch(
        "scripts.lcu.apps.snapshot_processes",
        side_effect=[{}, {}, {101: identity}, {101: identity}],
    ), patch(
        "scripts.lcu.apps.dispatch_candidate",
        return_value={
            "status": "accepted",
            "accepted": True,
            "backend": "process",
            "sanitized_env_applied": True,
            "dispatch_identity": identity.to_dict(),
        },
    ), patch(
        "scripts.lcu.apps._poll_for_launched_window",
        return_value=detected,
    ) as poll, patch(
        "scripts.lcu.windows.focus_window", return_value={"hwnd": 9001}
    ), patch("scripts.lcu.apps.remember_owned_processes"), patch("os.name", "nt"):
        result = open_app("vscode")

    assert result["hwnd"] == 9001
    assert poll.call_args_list == [
        call(entry, set(), APP_WINDOW_TIMEOUT),
    ]


def test_process_ownership_ledger_revalidates_and_finds_window(tmp_path: Path) -> None:
    ledger_path = tmp_path / "owned-processes.json"
    process = ProcessIdentity(
        pid=456,
        parent_pid=1,
        process_name="Notepad.exe",
        image_path=r"C:\Windows\System32\notepad.exe",
        creation_time=987654,
        session_id=1,
    ).to_dict()
    process["cleanup_mode"] = "owned-after-close"
    process["ownership_evidence"] = "exact-dispatch-identity"

    with patch("scripts.lcu.ownership.get_ledger_path", return_value=ledger_path), patch(
        "scripts.lcu.ownership.is_same_process", return_value=True
    ):
        remember_owned_processes("notepad", 7001, 456, [process])
        loaded = load_owned_processes()
        matched = owned_processes_for_window(7001, 456)

    assert loaded[0]["pid"] == 456
    assert loaded[0]["app"] == "notepad"
    assert matched == loaded


def test_process_ownership_ledger_prunes_pid_reuse(tmp_path: Path) -> None:
    ledger_path = tmp_path / "owned-processes.json"
    ledger_path.write_text(
        json.dumps(
            {
                "version": 1,
                "records": [
                    {
                        "pid": 456,
                        "parent_pid": 1,
                        "process_name": "Notepad.exe",
                        "image_path": r"C:\Windows\System32\notepad.exe",
                        "creation_time": 987654,
                        "session_id": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with patch("scripts.lcu.ownership.get_ledger_path", return_value=ledger_path), patch(
        "scripts.lcu.ownership.is_same_process", return_value=False
    ):
        assert load_owned_processes() == []

    assert json.loads(ledger_path.read_text(encoding="utf-8"))["records"] == []

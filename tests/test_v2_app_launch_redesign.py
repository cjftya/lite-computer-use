from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.lcu.app_observer import observe_window
from scripts.lcu.apps import (
    AppEntry,
    LaunchCandidate,
    _can_merge_discovered_entry,
    _entry_for_attempt,
    app_status,
    open_app,
)
from scripts.lcu.errors import LCUError


def _entry() -> AppEntry:
    return AppEntry(
        name="demo",
        target="primary.exe",
        source="config",
        aliases=["demo"],
        normalized="demo",
        candidates=[
            LaunchCandidate("primary.exe", "exe", "config", args=("--one",)),
            LaunchCandidate("secondary.exe", "exe", "config", args=("--two",)),
        ],
    )


def test_candidate_dedupe_uses_full_launch_spec() -> None:
    entry = AppEntry(
        "demo", "code.exe", "config", ["demo"], "demo",
        candidates=[
            LaunchCandidate("code.exe", "exe", "config", args=("--one",)),
            LaunchCandidate("code.exe", "exe", "config", args=("--two",)),
            LaunchCandidate("code.cmd", "exe", "config", args=("--one",)),
            LaunchCandidate(r"C:\One\app.exe", "exe", "config", cwd=r"C:\One"),
            LaunchCandidate(r"D:\Two\app.exe", "exe", "config", cwd=r"D:\Two"),
            LaunchCandidate(r"C:\One\app.exe", "exe", "config", cwd=r"C:\One"),
        ],
    )
    assert len(entry.candidates) == 5


def test_attempt_state_omits_launch_arguments() -> None:
    entry = AppEntry(
        "demo", "demo.exe", "config", ["demo"], "demo",
        candidates=[LaunchCandidate("demo.exe", "exe", "config", args=("--token", "secret"))],
    )
    serialized = str(_entry_for_attempt(entry))
    assert "--token" not in serialized
    assert "secret" not in serialized


def test_same_alias_discovered_installations_are_not_merged() -> None:
    first = AppEntry("Demo", r"C:\One\Demo.lnk", "start-menu", ["demo"], "demo")
    second = AppEntry("Demo", r"D:\Two\Demo.lnk", "start-menu", ["demo"], "demo")
    assert _can_merge_discovered_entry(first, second) is False


def test_stale_absolute_target_refreshes_once_without_dispatch(tmp_path: Path) -> None:
    missing = tmp_path / "missing.exe"
    entry = AppEntry("demo", str(missing), "config", ["demo"], "demo")
    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]) as build, patch(
        "scripts.lcu.apps.dispatch_candidate"
    ) as dispatch:
        with pytest.raises(LCUError) as raised:
            open_app("demo")
    assert raised.value.code == "target_not_found"
    assert build.call_count == 2
    dispatch.assert_not_called()


def test_accepted_dispatch_never_launches_second_candidate() -> None:
    entry = _entry()
    receipt = {"status": "accepted", "accepted": True, "backend": "process", "pid": 42}
    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), patch(
        "scripts.lcu.apps.find_matching_windows", return_value=[]
    ), patch("scripts.lcu.windows.list_windows", return_value=[]), patch(
        "scripts.lcu.apps.dispatch_candidate", return_value=receipt
    ) as dispatch, patch("scripts.lcu.apps._poll_for_launched_window", return_value=None), patch(
        "scripts.lcu.apps.save_app_attempt"
    ), patch("scripts.lcu.apps.snapshot_processes", return_value={}):
        with pytest.raises(LCUError) as raised:
            open_app("demo")
    assert raised.value.code == "window_unconfirmed"
    assert raised.value.details["dispatch_accepted"] is True
    dispatch.assert_called_once_with(entry.candidates[0])


def test_only_explicit_eligible_rejection_gets_one_fallback() -> None:
    entry = _entry()
    rejected = {
        "status": "rejected", "accepted": False, "backend": "process",
        "error_code": 2, "fallback_eligible": True,
    }
    accepted = {"status": "accepted", "accepted": True, "backend": "process", "pid": 42}
    window = {"hwnd": 7, "pid": 42, "title": "demo", "process": "secondary.exe"}
    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), patch(
        "scripts.lcu.apps.find_matching_windows", return_value=[]
    ), patch("scripts.lcu.windows.list_windows", return_value=[]), patch(
        "scripts.lcu.apps.dispatch_candidate", side_effect=[rejected, accepted]
    ) as dispatch, patch("scripts.lcu.apps._poll_for_launched_window", return_value=window), patch(
        "scripts.lcu.windows.focus_window", return_value={"hwnd": 7}
    ), patch("scripts.lcu.apps._recheck_window", return_value=True
    ), patch("scripts.lcu.apps.snapshot_processes", return_value={}), patch(
        "scripts.lcu.apps.remember_owned_processes"
    ):
        result = open_app("demo")
    assert result["target"] == "secondary.exe"
    assert dispatch.call_count == 2


def test_observation_exception_is_not_not_found() -> None:
    def fail() -> list[dict[str, object]]:
        raise PermissionError("desktop denied")

    result = observe_window(
        list_windows=fail, is_match=lambda _: True, baseline_hwnds=set(), timeout=0,
    )
    assert result.status == "observation_error"
    assert "desktop denied" in (result.error or "")


def test_existing_focus_failure_never_dispatches() -> None:
    entry = _entry()
    existing = {"hwnd": 9, "pid": 10, "title": "demo", "process": "primary.exe"}
    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), patch(
        "scripts.lcu.apps.find_matching_windows", return_value=[existing]
    ), patch("scripts.lcu.windows.focus_window", side_effect=OSError("focus denied")), patch(
        "scripts.lcu.apps.dispatch_candidate"
    ) as dispatch:
        with pytest.raises(LCUError) as raised:
            open_app("demo")
    assert raised.value.code == "window_focus_failed"
    dispatch.assert_not_called()


def test_app_status_observes_without_dispatch() -> None:
    entry = _entry()
    payload = {
        "entry": entry.to_dict(), "baseline_hwnds": [],
        "dispatch": {"status": "accepted", "backend": "process"},
    }
    with patch("scripts.lcu.apps.load_app_attempt", return_value=payload), patch(
        "scripts.lcu.apps._poll_for_launched_window", return_value=None
    ), patch("scripts.lcu.apps.dispatch_candidate") as dispatch:
        result = app_status("12345678-1234-1234-1234-123456789abc")
    assert result["status"] == "window_unconfirmed"
    dispatch.assert_not_called()

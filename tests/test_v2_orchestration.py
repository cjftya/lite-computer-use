from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch
import pytest

from scripts.lcu.errors import LCUError
from scripts.lcu.state import (
    PlanState,
    Task,
    create_plan,
    MetricsTracker,
    VALID_TASK_STATUSES,
)


# ============================================================================
# 1. State Schema & Validation Tests
# ============================================================================

def test_task_creation_and_validation() -> None:
    task = Task(id=1, goal="계산기 열기", done_when="계산기 창이 열림")
    assert task.status == "pending"
    assert task.result is None

    # Serialization
    d = task.to_dict()
    assert d == {
        "id": 1,
        "goal": "계산기 열기",
        "done_when": "계산기 창이 열림",
        "status": "pending",
        "result": None,
    }

    # Deserialization
    restored = Task.from_dict(d)
    assert restored.id == 1
    assert restored.goal == "계산기 열기"

    # Reject invalid status
    with pytest.raises(ValueError, match="Invalid task status"):
        Task(id=2, goal="g", done_when="d", status="running")  # type: ignore

    # Reject extra fields
    invalid_data = d.copy()
    invalid_data["extra_field"] = 123
    with pytest.raises(ValueError, match="Unexpected fields in Task data"):
        Task.from_dict(invalid_data)


def test_plan_state_schema_and_immutability() -> None:
    plan = create_plan(
        goal="테스트 목표",
        tasks=[
            {"id": 1, "goal": "작업 1", "done_when": "완료 1"},
            {"id": 2, "goal": "작업 2", "done_when": "완료 2"},
        ],
    )

    # First task automatically becomes active
    assert plan.current_task_index == 0
    assert plan.tasks[0].status == "active"
    assert plan.tasks[1].status == "pending"
    assert plan.recovery_used is False
    assert plan.current_capture_id is None
    assert plan.last_error is None

    # Check dict structure
    state_dict = plan.to_dict()
    assert set(state_dict.keys()) == {
        "goal",
        "tasks",
        "current_task_index",
        "completed_tasks_summary",
        "current_capture_id",
        "last_error",
        "recovery_used",
    }

    # Reject extra fields on PlanState.from_dict
    invalid_state = state_dict.copy()
    invalid_state["custom_tag"] = "prohibited"
    with pytest.raises(ValueError, match="Unexpected fields in PlanState"):
        PlanState.from_dict(invalid_state)


def test_json_roundtrip() -> None:
    plan = create_plan(
        goal="JSON 직렬화 검증",
        tasks=[{"id": 1, "goal": "T1", "done_when": "D1"}],
    )
    json_str = plan.to_json()
    loaded = PlanState.from_json(json_str)
    assert loaded.goal == "JSON 직렬화 검증"
    assert len(loaded.tasks) == 1
    assert loaded.tasks[0].status == "active"


# ============================================================================
# 2. State Transition & Context Compression Tests
# ============================================================================

def test_task_completion_and_context_compression() -> None:
    plan = create_plan(
        goal="검색 후 파일 다운로드",
        tasks=[
            {"id": 1, "goal": "네이버 열기", "done_when": "네이버 표시됨"},
            {"id": 2, "goal": "파일 검색", "done_when": "검색 결과 표시됨"},
        ],
    )
    plan.set_current_capture_id("c_old_capture_123")
    assert plan.current_capture_id == "c_old_capture_123"

    # Complete Task 1 with minimal result
    completed = plan.complete_current_task(
        result={"url": "https://www.naver.com"},
        summary="Task 1 완료: 네이버 열림",
    )
    assert completed.status == "completed"
    assert completed.result == {"url": "https://www.naver.com"}

    # Capture ID must be cleared upon task boundary (stale prevention)
    assert plan.current_capture_id is None

    # Task 2 automatically becomes active
    assert plan.current_task_index == 1
    current = plan.get_current_task()
    assert current is not None
    assert current.id == 2
    assert current.status == "active"

    # Context compression test
    compressed = plan.format_compressed_context()
    assert "Task 1 완료: 네이버 열림" in compressed
    assert "Current Task [2]: 파일 검색" in compressed
    # Previous raw tool responses or capture IDs are NOT retained in the prompt
    assert "c_old_capture_123" not in compressed


def test_failure_and_single_recovery_constraint() -> None:
    plan = create_plan(
        goal="복구 제약 테스트",
        tasks=[{"id": 1, "goal": "앱 실행", "done_when": "앱 열림"}],
    )

    # Initial state
    assert plan.can_attempt_recovery() is True

    # 1st failure occurs
    plan.fail_current_task(error="stale_capture")
    assert plan.tasks[0].status == "failed"
    assert plan.last_error == "stale_capture"

    # Recovery 1st attempt permitted
    assert plan.can_attempt_recovery() is True
    plan.record_recovery_attempt()
    assert plan.recovery_used is True

    # 2nd failure check: no more recovery attempts allowed!
    assert plan.can_attempt_recovery() is False
    with pytest.raises(RuntimeError, match="Recovery already used once"):
        plan.record_recovery_attempt()


# ============================================================================
# 3. Metrics Tracker Tests
# ============================================================================

def test_metrics_tracker() -> None:
    tracker = MetricsTracker()
    tracker.record_task()
    tracker.record_task()
    assert tracker.task_count == 2

    # Direct tool calls
    tracker.record_tool_call("open_app")
    tracker.record_tool_call("type_text")

    # Batch with 3 actions
    tracker.record_tool_call("batch", batch_actions_count=3)
    # Batch with 2 actions
    tracker.record_tool_call("batch", batch_actions_count=2)

    # Captures
    tracker.record_capture(is_unnecessary=False)
    tracker.record_capture(is_unnecessary=True)

    # Failures and recovery
    tracker.record_failure()
    tracker.record_recovery(is_unnecessary=False)

    summary = tracker.get_summary()
    assert summary["task_count"] == 2
    assert summary["capture_count"] == 2
    assert summary["unnecessary_capture_count"] == 1
    assert summary["batch_count"] == 2
    assert summary["avg_batch_actions"] == 2.5
    assert summary["failure_count"] == 1
    assert summary["recovery_count"] == 1


# ============================================================================
# 4. Orchestration Simulation Tests for 8 Scenarios (Section 19)
# ============================================================================

def test_scenario_1_calculator() -> None:
    """1. 계산기 열기: Direct Tool 우선, 0 captures."""
    plan = create_plan(
        goal="계산기 열기",
        tasks=[{"id": 1, "goal": "계산기 앱을 연다", "done_when": "계산기 창이 열림"}],
    )
    metrics = MetricsTracker()
    metrics.record_task()

    # Orchestrator decides: Direct Tool available (open_app "calc")
    metrics.record_tool_call("open_app")
    # Direct tool succeeds -> Task complete
    plan.complete_current_task(result={"process": "CalculatorApp.exe"})

    assert plan.tasks[0].status == "completed"
    assert metrics.capture_count == 0  # Zero captures!
    assert metrics.unnecessary_capture_count == 0


def test_scenario_2_notepad_text_entry() -> None:
    """2. 메모장 열고 문장 입력: Direct-first sequence, 0 captures."""
    plan = create_plan(
        goal="메모장 열고 문장 입력",
        tasks=[
            {"id": 1, "goal": "메모장을 연다", "done_when": "메모장 창이 열림"},
            {"id": 2, "goal": "문장을 입력한다", "done_when": "문장 입력 완료"},
        ],
    )
    metrics = MetricsTracker()
    metrics.record_task()
    metrics.record_task()

    # Task 1: Direct open_app
    metrics.record_tool_call("open_app")
    plan.complete_current_task(result={"hwnd": 12345})

    # Task 2: Direct type_text to foreground/hwnd
    metrics.record_tool_call("type_text")
    plan.complete_current_task(result={"typed": "Hello World"})

    assert plan.tasks[0].status == "completed"
    assert plan.tasks[1].status == "completed"
    assert metrics.capture_count == 0  # Zero captures!


def test_scenario_3_naver_search_observation_boundary() -> None:
    """3. 네이버 열고 검색: Direct open_url + Capture #1 + batch + Observation Boundary + Capture #2 -> complete."""
    plan = create_plan(
        goal="네이버에서 OpenAI 검색",
        tasks=[
            {"id": 1, "goal": "네이버를 연다", "done_when": "네이버 페이지 열림"},
            {"id": 2, "goal": "OpenAI를 검색한다", "done_when": "OpenAI 검색 결과 표시됨"},
        ],
    )
    metrics = MetricsTracker()
    metrics.record_task()
    metrics.record_task()

    # Task 1: Direct open_url (no capture)
    metrics.record_tool_call("open_url")
    plan.complete_current_task(result={"url": "https://www.naver.com"})
    assert metrics.capture_count == 0

    # Task 2: GUI interaction required
    # Step 1: Capture #1 of search page
    metrics.record_capture()
    plan.set_current_capture_id("c_naver_home")

    # Actions: click searchbox, type "OpenAI", press ENTER
    # All can be deduced deterministically from the current screen -> bundled into 1 batch!
    batch_actions = [
        {"action": "click", "x": 300, "y": 150, "capture": "c_naver_home", "delay_after": 0.1},
        {"action": "type_text", "text": "OpenAI", "delay_after": 0.1},
        {"action": "press_key", "key": "ENTER"},
    ]
    metrics.record_tool_call("batch", batch_actions_count=len(batch_actions))

    # Observation Boundary: ENTER is pressed; results will load.
    # Batch succeeded, but done_when requires verifying "OpenAI 검색 결과 표시됨".
    # Task must still be active!
    assert plan.tasks[1].status == "active"

    # Step 2: Capture #2 at Observation Boundary to verify done_when
    metrics.record_capture()
    plan.set_current_capture_id("c_naver_results")

    # done_when verified from Capture #2 -> complete Task
    plan.complete_current_task(result={"query": "OpenAI"})

    assert plan.tasks[1].status == "completed"
    assert metrics.capture_count == 2
    assert len(metrics.batch_action_counts) == 1
    assert metrics.batch_action_counts[0] == 3


def test_scenario_4_open_specific_search_result() -> None:
    """4. 검색 결과에서 특정 결과 열기: Capture #1 -> click -> Observation Boundary -> Capture #2 -> complete."""
    plan = create_plan(
        goal="공식 사이트 링크 열기",
        tasks=[
            {"id": 1, "goal": "공식 사이트 링크를 연다", "done_when": "공식 사이트 열림"},
        ],
    )
    metrics = MetricsTracker()
    metrics.record_task()

    # Capture #1: Results page observed to find official site link
    metrics.record_capture()
    plan.set_current_capture_id("c_results_page")

    # Agent identifies the official link coordinates and clicks
    metrics.record_tool_call("click")

    # Click succeeded, but done_when requires verifying "공식 사이트 열림" (Observation Boundary).
    # Task must still be active!
    assert plan.tasks[0].status == "active"

    # Capture #2 at Observation Boundary to verify official site opened
    metrics.record_capture()
    plan.set_current_capture_id("c_official_site")

    # done_when verified from Capture #2 -> complete Task
    plan.complete_current_task(result={"target": "OpenAI Official Site"})

    assert plan.tasks[0].status == "completed"
    assert metrics.capture_count == 2


def test_scenario_5_download_file_search_and_open() -> None:
    """5. 다운로드 폴더에서 파일 찾아 열기: Discovery tool (find_path) + Direct tool (open_file)."""
    plan = create_plan(
        goal="다운로드 파일 찾아 열기",
        tasks=[
            {"id": 1, "goal": "다운로드 폴더에서 report.pdf 찾기", "done_when": "경로 확인"},
            {"id": 2, "goal": "report.pdf 열기", "done_when": "파일 열림"},
        ],
    )
    metrics = MetricsTracker()
    metrics.record_task()
    metrics.record_task()

    # Task 1: Discovery Tool
    metrics.record_tool_call("find_path")
    found_path = r"C:\Users\test\Downloads\report.pdf"
    plan.complete_current_task(
        result={"path": found_path},
        summary=f"Task 1 완료: report.pdf = {found_path}",
    )

    # Task 2: Direct Tool using result from Task 1
    metrics.record_tool_call("open_file")
    plan.complete_current_task(
        result={"opened": found_path},
        summary=f"Task 2 완료: {found_path} 열림",
    )

    # Verification: Zero vision captures needed for filesystem operations!
    assert metrics.capture_count == 0
    assert len(plan.completed_tasks_summary) == 2
    assert found_path in plan.completed_tasks_summary[0]


def test_scenario_6_multi_app_switching() -> None:
    """6. 앱 두 개를 오가며 작업: Direct focus_window, 0 captures."""
    plan = create_plan(
        goal="메모장과 계산기 오가며 작업",
        tasks=[
            {"id": 1, "goal": "메모장 활성화", "done_when": "메모장 포커스됨"},
            {"id": 2, "goal": "계산기 활성화", "done_when": "계산기 포커스됨"},
        ],
    )
    metrics = MetricsTracker()
    metrics.record_task()
    metrics.record_task()

    metrics.record_tool_call("focus_window")
    plan.complete_current_task(result={"focused": "notepad"})

    metrics.record_tool_call("focus_window")
    plan.complete_current_task(result={"focused": "calc"})

    assert metrics.capture_count == 0
    assert plan.tasks[0].status == "completed"
    assert plan.tasks[1].status == "completed"


def test_scenario_7_stale_capture_recovery() -> None:
    """7. stale_capture 발생: 1회 recovery 허용 후 성공."""
    plan = create_plan(
        goal="버튼 클릭",
        tasks=[{"id": 1, "goal": "확인 버튼 클릭", "done_when": "확인됨"}],
    )
    metrics = MetricsTracker()
    metrics.record_task()

    # Initial capture
    metrics.record_capture()
    plan.set_current_capture_id("c_old_stale")

    # Click fails with stale_capture
    metrics.record_tool_call("click")
    metrics.record_failure()
    plan.fail_current_task(error="stale_capture")

    # Failure Plan triggers:
    # 1. Cause: stale_capture
    # 2. Alternative: Retake fresh capture 1 time
    assert plan.can_attempt_recovery() is True
    plan.record_recovery_attempt()
    metrics.record_recovery()

    # Execute alternative (1 recapture + 1 click)
    metrics.record_capture()
    plan.set_current_capture_id("c_fresh_new")
    metrics.record_tool_call("click")

    # Success
    plan.complete_current_task(result={"clicked": True})
    assert plan.tasks[0].status == "completed"
    assert plan.recovery_used is True
    # Can no longer recover if another failure were to happen
    assert plan.can_attempt_recovery() is False


def test_scenario_8_ambiguous_target_resolution() -> None:
    """8. ambiguous_target 발생: 컨텍스트로 1회 식별 가능하면 실행, 불가 시 즉시 중단."""
    # Case A: Context clarifies candidate
    plan_a = create_plan(
        goal="크롬 창 전환",
        tasks=[{"id": 1, "goal": "네이버 크롬 창 포커스", "done_when": "창 활성화"}],
    )
    # focus_window "chrome" returns ambiguous_target candidates:
    # [{"hwnd": 101, "title": "네이버 - Chrome"}, {"hwnd": 102, "title": "Google - Chrome"}]
    plan_a.fail_current_task(
        error={"code": "ambiguous_target", "candidates": [101, 102]}
    )
    assert plan_a.can_attempt_recovery() is True
    plan_a.record_recovery_attempt()

    # Use explicit hwnd 101 based on goal context "네이버"
    plan_a.complete_current_task(result={"hwnd": 101})
    assert plan_a.tasks[0].status == "completed"

    # Case B: Context cannot disambiguate -> must abort immediately without infinite loop
    plan_b = create_plan(
        goal="브라우저 창 열기",
        tasks=[{"id": 1, "goal": "아무 창이나 포커스", "done_when": "창 활성화"}],
    )
    plan_b.fail_current_task(
        error={"code": "ambiguous_target", "candidates": [201, 202]}
    )
    # No clear deterministic candidate -> cannot recover safely -> immediate abort
    assert plan_b.tasks[0].status == "failed"
    assert plan_b.recovery_used is False  # Aborted without blind recovery attempt


# ============================================================================
# 5. App Ownership & Cleanup Tests (Phase 16 / Section 22)
# ============================================================================

def test_scenario_a_temporary_and_final_result_cleanup() -> None:
    """Scenario A: 계산기로 계산하고 메모장에 결과를 적어줘
    Calculator: reused_existing=false, temporary=true
    Notepad: reused_existing=false, final_result=true
    완료: Calculator close, Notepad 유지
    """
    plan = create_plan(
        goal="계산기로 계산하고 메모장에 결과를 적어줘",
        tasks=[
            {"id": 1, "goal": "계산기 열기", "done_when": "계산기 열림"},
            {"id": 2, "goal": "계산 수행", "done_when": "계산 완료"},
            {"id": 3, "goal": "메모장 열기", "done_when": "메모장 열림"},
            {"id": 4, "goal": "결과 입력", "done_when": "결과 작성됨"},
        ],
    )
    # Task 1: Open Calculator (temporary app)
    calc_res = {"app": "Calculator", "hwnd": 1111, "reused_existing": False, "launch_method": "appsfolder"}
    plan.complete_current_task(result=calc_res)

    # Task 2: Calculate
    plan.complete_current_task(result={"calc_output": 42})

    # Task 3: Open Notepad (Final result app)
    notepad_res = {"app": "Notepad", "hwnd": 2222, "reused_existing": False, "launch_method": "appsfolder"}
    plan.complete_current_task(result=notepad_res)

    # Task 4: Write Result
    plan.complete_current_task(result={"written": True})

    # Orchestrator cleanup phase: keep Notepad (final result), close Calculator
    targets = plan.get_cleanup_targets(keep_apps={"notepad"})
    assert len(targets) == 1
    assert targets[0]["app"] == "Calculator"
    assert targets[0]["hwnd"] == 1111


def test_scenario_b_reused_chrome_preserved() -> None:
    """Scenario B: 기존 Chrome 재사용 (reused_existing=True) -> Chrome close 금지"""
    plan = create_plan(
        goal="크롬에서 정보 확인",
        tasks=[
            {"id": 1, "goal": "크롬 활성화", "done_when": "크롬 창 활성화"},
            {"id": 2, "goal": "정보 확인", "done_when": "확인 완료"},
        ],
    )
    chrome_res = {"app": "Chrome", "hwnd": 4852350, "reused_existing": True, "launch_method": "existing-window"}
    plan.complete_current_task(result=chrome_res)
    plan.complete_current_task(result={"data": "found"})

    targets = plan.get_cleanup_targets()
    # Chrome must NOT be cleaned up because reused_existing is True
    assert len(targets) == 0


def test_scenario_c_reused_notepad_preserved() -> None:
    """Scenario C: 기존 Notepad 재사용 (reused_existing=True) -> Notepad close 금지"""
    plan = create_plan(
        goal="메모장에 메모 추가",
        tasks=[
            {"id": 1, "goal": "메모장 활성화", "done_when": "메모장 활성화"},
            {"id": 2, "goal": "메모 추가", "done_when": "작성 완료"},
        ],
    )
    notepad_res = {"app": "Notepad", "hwnd": 3333, "reused_existing": True, "launch_method": "existing-window"}
    plan.complete_current_task(result=notepad_res)
    plan.complete_current_task(result={"appended": True})

    targets = plan.get_cleanup_targets()
    # Notepad must NOT be cleaned up because reused_existing is True
    assert len(targets) == 0


def test_scenario_d_cleanup_failure_does_not_fail_main_goal() -> None:
    """Scenario D: cleanup 실패 시 main result는 success로 유지되고 cleanup warning 기록"""
    plan = create_plan(
        goal="작업 수행 후 임시 창 정리",
        tasks=[
            {"id": 1, "goal": "임시 앱 실행", "done_when": "앱 열림"},
            {"id": 2, "goal": "작업 완료", "done_when": "완료"},
        ],
    )
    temp_res = {"app": "TempApp", "hwnd": 9999, "reused_existing": False, "launch_method": "exe"}
    plan.complete_current_task(result=temp_res)
    plan.complete_current_task(result={"done": True})

    targets = plan.get_cleanup_targets()
    assert len(targets) == 1
    assert targets[0]["hwnd"] == 9999

    # Cleanup execution simulation
    cleanup_warnings = []
    with patch("scripts.lcu.windows.close_window", side_effect=LCUError("window_close_failed", "Stubborn window")):
        for target in targets:
            try:
                from scripts.lcu.windows import close_window
                close_window(hwnd=target["hwnd"])
            except Exception as exc:
                cleanup_warnings.append(f"Cleanup warning for hwnd {target['hwnd']}: {exc}")

    # Main goal remains completed!
    assert all(t.status == "completed" for t in plan.tasks)
    assert len(cleanup_warnings) == 1
    assert "Cleanup warning for hwnd 9999" in cleanup_warnings[0]


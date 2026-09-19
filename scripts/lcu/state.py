from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

TaskStatus = Literal["pending", "active", "completed", "failed"]
VALID_TASK_STATUSES: set[TaskStatus] = {"pending", "active", "completed", "failed"}


@dataclass
class Task:
    id: int
    goal: str
    done_when: str
    status: TaskStatus = "pending"
    result: Any = None

    def __post_init__(self) -> None:
        if self.status not in VALID_TASK_STATUSES:
            raise ValueError(
                f"Invalid task status '{self.status}'. Must be one of {sorted(VALID_TASK_STATUSES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "done_when": self.done_when,
            "status": self.status,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        allowed_keys = {"id", "goal", "done_when", "status", "result"}
        extra_keys = set(data.keys()) - allowed_keys
        if extra_keys:
            raise ValueError(f"Unexpected fields in Task data: {sorted(extra_keys)}")

        status = data.get("status", "pending")
        if status not in VALID_TASK_STATUSES:
            raise ValueError(f"Invalid task status '{status}'. Must be one of {sorted(VALID_TASK_STATUSES)}")

        return cls(
            id=int(data["id"]),
            goal=str(data["goal"]),
            done_when=str(data["done_when"]),
            status=status,
            result=data.get("result", None),
        )


CLEANUP_OWNED_LAUNCH_METHODS: set[str] = {
    "appsfolder",
    "start-menu",
    "uri",
    "app-paths",
    "exe",
}


@dataclass
class PlanState:
    """Minimal state representation for Lite Computer Use v2 Phase 2 orchestration."""

    goal: str
    tasks: list[Task] = field(default_factory=list)
    current_task_index: int = 0
    completed_tasks_summary: list[str] = field(default_factory=list)
    current_capture_id: str | None = None
    last_error: Any | None = None
    recovery_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "tasks": [task.to_dict() for task in self.tasks],
            "current_task_index": self.current_task_index,
            "completed_tasks_summary": list(self.completed_tasks_summary),
            "current_capture_id": self.current_capture_id,
            "last_error": self.last_error,
            "recovery_used": self.recovery_used,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanState:
        allowed_keys = {
            "goal",
            "tasks",
            "current_task_index",
            "completed_tasks_summary",
            "current_capture_id",
            "last_error",
            "recovery_used",
        }
        extra_keys = set(data.keys()) - allowed_keys
        if extra_keys:
            raise ValueError(f"Unexpected fields in PlanState: {sorted(extra_keys)}")

        tasks_raw = data.get("tasks", [])
        tasks = [t if isinstance(t, Task) else Task.from_dict(t) for t in tasks_raw]

        return cls(
            goal=str(data.get("goal", "")),
            tasks=tasks,
            current_task_index=int(data.get("current_task_index", 0)),
            completed_tasks_summary=list(data.get("completed_tasks_summary", [])),
            current_capture_id=data.get("current_capture_id"),
            last_error=data.get("last_error"),
            recovery_used=bool(data.get("recovery_used", False)),
        )

    @classmethod
    def from_json(cls, json_str: str) -> PlanState:
        return cls.from_dict(json.loads(json_str))

    def get_current_task(self) -> Task | None:
        if 0 <= self.current_task_index < len(self.tasks):
            return self.tasks[self.current_task_index]
        return None

    def complete_current_task(self, result: Any = None, summary: str | None = None) -> Task:
        task = self.get_current_task()
        if task is None:
            raise RuntimeError(f"No active task at current_task_index {self.current_task_index}")

        task.status = "completed"
        task.result = result

        # Compress context: record only concise summary
        if summary is None:
            summary = f"Task {task.id} 완료: {task.goal}"
            if result is not None:
                summary += f" -> result={result}"
        self.completed_tasks_summary.append(summary)

        # Invalidate old capture upon task boundary to ensure freshness
        self.current_capture_id = None
        self.last_error = None

        self.current_task_index += 1
        next_task = self.get_current_task()
        if next_task is not None and next_task.status == "pending":
            next_task.status = "active"

        return task

    def fail_current_task(self, error: Any) -> Task:
        task = self.get_current_task()
        if task is None:
            raise RuntimeError(f"No active task at current_task_index {self.current_task_index}")

        task.status = "failed"
        self.last_error = error
        return task

    def can_attempt_recovery(self) -> bool:
        """Failure Plan allows at most 1 recovery execution."""
        return not self.recovery_used

    def record_recovery_attempt(self) -> None:
        if self.recovery_used:
            raise RuntimeError("Recovery already used once. Second failure must abort immediately.")
        self.recovery_used = True

    def set_current_capture_id(self, capture_id: str | None) -> None:
        self.current_capture_id = capture_id

    def format_compressed_context(self) -> str:
        """Produce compressed context for the host AI agent.

        Discards raw screenshots, past coordinates, full tool payloads,
        and verbose reasoning, keeping only essential goal, progress summaries,
        and active task requirements.
        """
        lines = [f"Goal: {self.goal}"]
        if self.completed_tasks_summary:
            lines.append("Completed Tasks:")
            for s in self.completed_tasks_summary:
                lines.append(f"  - {s}")
        else:
            lines.append("Completed Tasks: None")

        current = self.get_current_task()
        if current:
            lines.append(f"Current Task [{current.id}]: {current.goal}")
            lines.append(f"  Done When: {current.done_when}")
            lines.append(f"  Status: {current.status}")
        else:
            lines.append("Current Task: All tasks processed")

        remaining = [t for t in self.tasks[self.current_task_index + 1 :]]
        if remaining:
            lines.append("Pending Tasks:")
            for t in remaining:
                lines.append(f"  - [{t.id}] {t.goal} (done_when: {t.done_when})")

        if self.last_error is not None:
            lines.append(f"Last Error: {self.last_error}")
        lines.append(f"Recovery Used: {self.recovery_used}")
        return "\n".join(lines)

    def get_cleanup_targets(
        self,
        keep_hwnds: set[int] | None = None,
        keep_apps: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Identify temporary application windows that should be cleaned up upon goal completion.

        Criteria:
        - Must be completed task result with a verified hwnd.
        - Must have reused_existing == False explicitly.
        - Must have app and launch_method in CLEANUP_OWNED_LAUNCH_METHODS.
        - Must not be in keep_hwnds or keep_apps (e.g. final result apps).
        - Returned in reverse order of task execution.
        """
        keep_hwnds = keep_hwnds or set()
        keep_apps = {a.lower() for a in (keep_apps or set())}
        targets: list[dict[str, Any]] = []
        seen_hwnds: set[int] = set()

        for task in reversed(self.tasks):
            if task.status != "completed" or not isinstance(task.result, dict):
                continue
            res = task.result
            hwnd = res.get("hwnd")
            if not hwnd or res.get("reused_existing") is not False:
                continue
            if not res.get("app"):
                continue
            launch_method = res.get("launch_method")
            if not launch_method or launch_method not in CLEANUP_OWNED_LAUNCH_METHODS:
                continue
            if hwnd in seen_hwnds or hwnd in keep_hwnds:
                continue
            app_name = str(res.get("app", "")).lower()
            if app_name in keep_apps:
                continue

            seen_hwnds.add(hwnd)
            targets.append(res)

        return targets



def create_plan(goal: str, tasks: list[dict[str, Any] | Task]) -> PlanState:
    """Create an initial PlanState from a goal and a list of semantic tasks."""
    parsed_tasks: list[Task] = []
    for idx, t in enumerate(tasks, start=1):
        if isinstance(t, Task):
            task_obj = t
        else:
            t_id = t.get("id", idx)
            task_obj = Task(
                id=int(t_id),
                goal=str(t["goal"]),
                done_when=str(t["done_when"]),
                status=t.get("status", "pending"),
                result=t.get("result", None),
            )
        parsed_tasks.append(task_obj)

    # Set the first task to active if pending
    if parsed_tasks and parsed_tasks[0].status == "pending":
        parsed_tasks[0].status = "active"

    return PlanState(
        goal=goal,
        tasks=parsed_tasks,
        current_task_index=0,
        completed_tasks_summary=[],
        current_capture_id=None,
        last_error=None,
        recovery_used=False,
    )


@dataclass
class MetricsTracker:
    """Lightweight tracker to measure Phase 2 efficiency metrics (Section 20)."""

    task_count: int = 0
    capture_count: int = 0
    tool_call_count: int = 0
    batch_action_counts: list[int] = field(default_factory=list)
    failure_count: int = 0
    recovery_count: int = 0
    unnecessary_capture_count: int = 0
    unnecessary_retry_count: int = 0

    def record_task(self) -> None:
        self.task_count += 1

    def record_capture(self, is_unnecessary: bool = False) -> None:
        self.capture_count += 1
        self.tool_call_count += 1
        if is_unnecessary:
            self.unnecessary_capture_count += 1

    def record_tool_call(self, action: str, batch_actions_count: int = 0) -> None:
        self.tool_call_count += 1
        if action == "batch":
            self.batch_action_counts.append(batch_actions_count)

    def record_failure(self) -> None:
        self.failure_count += 1

    def record_recovery(self, is_unnecessary: bool = False) -> None:
        self.recovery_count += 1
        if is_unnecessary:
            self.unnecessary_retry_count += 1

    def get_summary(self) -> dict[str, Any]:
        avg_batch = (
            sum(self.batch_action_counts) / len(self.batch_action_counts)
            if self.batch_action_counts
            else 0.0
        )
        return {
            "task_count": self.task_count,
            "capture_count": self.capture_count,
            "tool_call_count": self.tool_call_count,
            "batch_count": len(self.batch_action_counts),
            "avg_batch_actions": round(avg_batch, 2),
            "failure_count": self.failure_count,
            "recovery_count": self.recovery_count,
            "unnecessary_capture_count": self.unnecessary_capture_count,
            "unnecessary_retry_count": self.unnecessary_retry_count,
        }

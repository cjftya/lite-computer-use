from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Observation:
    status: str  # found | not_found | observation_error | ambiguous
    window: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def snapshot_windows(list_windows: Callable[[], list[dict[str, Any]]]) -> Observation:
    try:
        return Observation("found", candidates=list_windows())
    except Exception as exc:
        return Observation("observation_error", error=f"{type(exc).__name__}: {exc}")


def observe_window(
    *,
    list_windows: Callable[[], list[dict[str, Any]]],
    is_match: Callable[[dict[str, Any]], bool],
    baseline_hwnds: set[int],
    timeout: float = 10.0,
    interval: float = 0.2,
) -> Observation:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            windows = list_windows()
        except Exception as exc:
            return Observation("observation_error", error=f"{type(exc).__name__}: {exc}")
        matching = [window for window in windows if is_match(window)]
        new_matching = [w for w in matching if int(w.get("hwnd", 0)) not in baseline_hwnds]
        candidates = new_matching or (
            [w for w in matching if w.get("active")] if any(w.get("active") for w in matching) else []
        )
        if len(candidates) == 1:
            return Observation("found", window=candidates[0])
        if len(candidates) > 1:
            return Observation("ambiguous", candidates=candidates)
        if time.monotonic() >= deadline:
            return Observation("not_found", candidates=matching)
        if interval > 0:
            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))

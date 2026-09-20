from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .processes import ProcessIdentity, is_same_process


LEDGER_VERSION = 1


def get_ledger_path() -> Path:
    directory = Path(tempfile.gettempdir()) / "LiteComputerUse"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "owned-processes.json"


def _write_records(records: list[dict[str, Any]]) -> None:
    path = get_ledger_path()
    payload = {"version": LEDGER_VERSION, "records": records}
    fd, temp_name = tempfile.mkstemp(prefix="owned-processes-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _read_raw_records() -> list[dict[str, Any]]:
    path = get_ledger_path()
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, dict) or payload.get("version") != LEDGER_VERSION:
        return []
    records = payload.get("records", [])
    return [record for record in records if isinstance(record, dict)]


def load_owned_processes(prune: bool = True) -> list[dict[str, Any]]:
    """Load only identities that still match PID + creation time on this host."""

    raw_records = _read_raw_records()
    valid: list[dict[str, Any]] = []
    for record in raw_records:
        try:
            identity = ProcessIdentity.from_dict(record)
        except (KeyError, TypeError, ValueError):
            continue
        if identity.creation_time is None:
            continue
        try:
            if is_same_process(identity):
                valid.append(record)
        except Exception:
            continue
    if prune and valid != raw_records:
        try:
            _write_records(valid)
        except OSError:
            pass
    return valid


def remember_owned_processes(
    app: str,
    hwnd: int,
    window_pid: int | None,
    owned_processes: Iterable[dict[str, Any]],
) -> None:
    current = load_owned_processes(prune=True)
    by_identity: dict[tuple[int, int], dict[str, Any]] = {}
    for record in current:
        creation_time = record.get("creation_time")
        if creation_time is not None:
            by_identity[(int(record["pid"]), int(creation_time))] = record

    for process in owned_processes:
        creation_time = process.get("creation_time")
        if creation_time is None:
            continue
        record = dict(process)
        record.update(
            {
                "app": app,
                "hwnd": int(hwnd),
                "window_pid": int(window_pid) if window_pid is not None else None,
            }
        )
        by_identity[(int(record["pid"]), int(creation_time))] = record
    _write_records(list(by_identity.values()))


def owned_processes_for_window(hwnd: int, window_pid: int | None = None) -> list[dict[str, Any]]:
    records = load_owned_processes(prune=True)
    matched = []
    for record in records:
        if int(record.get("hwnd", 0)) != int(hwnd):
            continue
        if window_pid is not None and record.get("window_pid") != window_pid:
            continue
        matched.append(record)
    return matched


def forget_owned_processes(processes: Iterable[ProcessIdentity | dict[str, Any]]) -> None:
    identity_keys: set[tuple[int, int]] = set()
    for process in processes:
        try:
            identity = process if isinstance(process, ProcessIdentity) else ProcessIdentity.from_dict(process)
        except (KeyError, TypeError, ValueError):
            continue
        if identity.creation_time is not None:
            identity_keys.add((identity.pid, identity.creation_time))

    if not identity_keys:
        return
    remaining = []
    for record in _read_raw_records():
        creation_time = record.get("creation_time")
        key = (int(record.get("pid", -1)), int(creation_time)) if creation_time is not None else None
        if key not in identity_keys:
            remaining.append(record)
    _write_records(remaining)

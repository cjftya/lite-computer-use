from __future__ import annotations

import hashlib
import json
import ntpath
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class LaunchSpec:
    """A resolved, typed launch request.

    ``target`` and ``argv`` deliberately remain separate.  The normalized key is
    used only to remove byte-for-byte equivalent launch specifications; it must
    never collapse distinct installations or argument sets.
    """

    app_id: str
    kind: str
    target: str
    argv: tuple[str, ...] = ()
    cwd: str | None = None
    source: str = ""
    expected_identity: dict[str, Any] = field(default_factory=dict, compare=False)
    priority: int | None = field(default=None, compare=False)

    def identity_key(self) -> tuple[str, str, tuple[str, ...], str, str]:
        target = ntpath.normcase(ntpath.normpath(self.target.strip().strip('"')))
        cwd = ntpath.normcase(ntpath.normpath(self.cwd)) if self.cwd else ""
        return (self.kind, target, self.argv, cwd, self.app_id.casefold())


def deduplicate_specs(specs: Iterable[LaunchSpec]) -> list[LaunchSpec]:
    seen: set[tuple[str, str, tuple[str, ...], str, str]] = set()
    result: list[LaunchSpec] = []
    for spec in specs:
        key = spec.identity_key()
        if key not in seen:
            seen.add(key)
            result.append(spec)
    return result


def resolve_config_path(config_path: Path | None = None) -> Path | None:
    candidates = (
        [config_path]
        if config_path is not None
        else [
            Path(__file__).resolve().parents[2] / "config" / "apps.yaml",
            Path.cwd() / "config" / "apps.yaml",
        ]
    )
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    return None


def cache_fingerprint(config_path: Path | None) -> dict[str, str]:
    resolved = resolve_config_path(config_path)
    config_bytes = resolved.read_bytes() if resolved is not None else b""
    path_value = next(
        (value for key, value in os.environ.items() if key.casefold() == "path"),
        "",
    )
    user_scope = "|".join(
        os.environ.get(key, "") for key in ("USERDOMAIN", "USERNAME", "USERPROFILE")
    )
    return {
        "config_path": str(resolved) if resolved is not None else "",
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "path_sha256": hashlib.sha256(path_value.encode("utf-8", "surrogatepass")).hexdigest(),
        "user_sha256": hashlib.sha256(user_scope.encode("utf-8", "surrogatepass")).hexdigest(),
    }


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def inspect_shortcut(path: Path) -> dict[str, str]:
    """Read Shell Link metadata without changing its activation semantics."""
    if os.name != "nt" or not path.is_file():
        return {}
    try:
        import pythoncom
        from win32com.client import Dispatch
    except ImportError:
        return {}
    initialized = False
    try:
        pythoncom.CoInitialize()
        initialized = True
        shortcut = Dispatch("WScript.Shell").CreateShortcut(str(path))
        result: dict[str, str] = {}
        if shortcut.TargetPath:
            result["target_path"] = str(shortcut.TargetPath)
        if shortcut.WorkingDirectory:
            result["working_directory"] = str(shortcut.WorkingDirectory)
        if shortcut.Arguments:
            result["arguments"] = str(shortcut.Arguments)
        return result
    except Exception:
        return {}
    finally:
        if initialized:
            pythoncom.CoUninitialize()

from __future__ import annotations

import ctypes
import hashlib
import hmac
import os
import secrets
import shutil
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path
from typing import Any, Mapping


GUI_ENV_DROP_EXACT = {
    "ELECTRON_RUN_AS_NODE",
    "ELECTRON_NO_ATTACH_CONSOLE",
    "VSCODE_IPC_HOOK_CLI",
}

_ENV_EXACT = {
    "TERM",
    "TERM_PROGRAM",
    "MSYSTEM",
    "SHELL",
    "COMSPEC",
    "SESSIONNAME",
    "PYTHONHOME",
    "PYTHONPATH",
    "CI",
}
_ENV_PREFIXES = ("ELECTRON_", "VSCODE_", "NODE_", "CHROME_", "WT_")
_RESOLVE_NAMES = ("py", "python", "code", "code.exe", "cmd.exe", "powershell.exe")
_VISIBLE_FLAGS = {"ELECTRON_RUN_AS_NODE", "ELECTRON_NO_ATTACH_CONSOLE"}
_VISIBLE_FLAG_VALUES = {"", "0", "1", "false", "true"}


def _last_error_code() -> int | None:
    getter = getattr(ctypes, "get_last_error", None)
    return int(getter()) if getter is not None else None


def _set_signature(function: Any, argtypes: list[Any], restype: Any) -> None:
    try:
        function.argtypes = argtypes
        function.restype = restype
    except Exception:
        pass


def _configure_desktop_apis() -> tuple[Any, Any]:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    _set_signature(user32.GetProcessWindowStation, [], wintypes.HANDLE)
    _set_signature(user32.GetThreadDesktop, [wintypes.DWORD], wintypes.HANDLE)
    _set_signature(
        user32.GetUserObjectInformationW,
        [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)],
        wintypes.BOOL,
    )
    _set_signature(kernel32.GetCurrentThreadId, [], wintypes.DWORD)
    return user32, kernel32


def build_gui_launch_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a copy of the host environment safe for launching desktop GUI apps.

    Windows environment keys are case-insensitive, so comparison is normalized while
    the original key spelling and every unrelated value are preserved.
    """

    env = dict(os.environ if source is None else source)
    drop_upper = {key.upper() for key in GUI_ENV_DROP_EXACT}
    for key in list(env):
        if key.upper() in drop_upper:
            env.pop(key, None)
    return env


def get_gui_env_normalization(
    source: Mapping[str, str] | None = None,
    *,
    applied: bool = False,
) -> dict[str, Any]:
    original = dict(os.environ if source is None else source)
    normalized = build_gui_launch_env(original)
    remaining_upper = {key.upper() for key in normalized}
    dropped = sorted(key for key in original if key.upper() not in remaining_upper)
    return {
        "applied": applied,
        "dropped_keys": dropped,
    }


def _case_insensitive_get(source: Mapping[str, str], name: str) -> str:
    wanted = name.upper()
    for key, value in source.items():
        if key.upper() == wanted:
            return value
    return ""


def _diagnostic_key() -> bytes:
    """Return a local-only HMAC key so two shells can compare without exposing values."""

    path = Path(tempfile.gettempdir()) / "LiteComputerUse" / "diagnostic.key"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            key = path.read_bytes()
            if len(key) >= 32:
                return key[:64]
        key = secrets.token_bytes(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, key)
        finally:
            os.close(fd)
        return key
    except FileExistsError:
        try:
            key = path.read_bytes()
            return key[:64] if len(key) >= 32 else secrets.token_bytes(32)
        except OSError:
            return secrets.token_bytes(32)
    except OSError:
        return secrets.token_bytes(32)


def _value_metadata(key: str, value: str, digest_key: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {
        "present": True,
        "length": len(value),
        "fingerprint": hmac.new(
            digest_key,
            value.encode("utf-8", errors="replace"),
            hashlib.sha256,
        ).hexdigest(),
    }
    normalized = value.strip().lower()
    if key.upper() in _VISIBLE_FLAGS and normalized in _VISIBLE_FLAG_VALUES:
        result["value"] = normalized
    return result


def _user_object_name(handle: int | None) -> dict[str, Any]:
    if os.name != "nt":
        return {"status": "unsupported", "value": None}
    if not handle:
        return {"status": "error", "value": None, "error_code": _last_error_code()}
    try:
        user32, _ = _configure_desktop_apis()
        UOI_NAME = 2
        needed = wintypes.DWORD()
        user32.GetUserObjectInformationW(handle, UOI_NAME, None, 0, ctypes.byref(needed))
        if not needed.value:
            return {"status": "error", "value": None, "error_code": _last_error_code()}
        char_count = max(1, needed.value // ctypes.sizeof(ctypes.c_wchar))
        buffer = ctypes.create_unicode_buffer(char_count)
        if user32.GetUserObjectInformationW(
            handle,
            UOI_NAME,
            buffer,
            needed.value,
            ctypes.byref(needed),
        ):
            return {"status": "ok", "value": buffer.value}
        return {"status": "error", "value": None, "error_code": _last_error_code()}
    except Exception:
        return {"status": "error", "value": None, "error_code": _last_error_code()}


def _desktop_context() -> tuple[dict[str, Any], dict[str, Any]]:
    if os.name != "nt":
        unsupported = {"status": "unsupported", "value": None}
        return dict(unsupported), dict(unsupported)
    try:
        user32, kernel32 = _configure_desktop_apis()
        window_station = user32.GetProcessWindowStation()
        thread_id = kernel32.GetCurrentThreadId()
        desktop = user32.GetThreadDesktop(thread_id)
        return _user_object_name(window_station), _user_object_name(desktop)
    except Exception:
        error = {"status": "error", "value": None, "error_code": _last_error_code()}
        return dict(error), dict(error)


def _selected_environment(source: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    digest_key = _diagnostic_key()
    for key, value in source.items():
        upper = key.upper()
        if upper in _ENV_EXACT or upper.startswith(_ENV_PREFIXES):
            selected[key] = _value_metadata(key, value, digest_key)
    return dict(sorted(selected.items(), key=lambda item: item[0].upper()))


def _path_diagnostics(source: Mapping[str, str]) -> dict[str, Any]:
    path_value = _case_insensitive_get(source, "PATH")
    resolved = {name: shutil.which(name, path=path_value) for name in _RESOLVE_NAMES}
    return {
        "sha256": hashlib.sha256(path_value.encode("utf-8", errors="replace")).hexdigest(),
        "resolved_executables": resolved,
    }


def get_launch_context_snapshot(source: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = dict(os.environ if source is None else source)
    parent_pid = os.getppid()
    parent_process: str | None = None
    session_id: int | None = None

    if os.name == "nt":
        try:
            from .processes import get_current_session_id, get_process_identity

            session_id = get_current_session_id()
            parent = get_process_identity(parent_pid)
            if parent is not None:
                parent_process = parent.image_path or parent.process_name
        except Exception:
            pass
    else:
        try:
            parent_process = str(Path(f"/proc/{parent_pid}/exe").resolve())
        except Exception:
            pass

    window_station, desktop = _desktop_context()
    return {
        "python_exe": sys.executable,
        "pid": os.getpid(),
        "parent_pid": parent_pid,
        "parent_process": parent_process,
        "session_id": session_id,
        "window_station": window_station,
        "desktop": desktop,
        "cwd": str(Path.cwd()),
        "shell": "SHELL" if _case_insensitive_get(env, "SHELL") else (
            "COMSPEC" if _case_insensitive_get(env, "COMSPEC") else None
        ),
        "environment": _selected_environment(env),
        "path": _path_diagnostics(env),
        "gui_env_normalization": get_gui_env_normalization(env, applied=False),
    }

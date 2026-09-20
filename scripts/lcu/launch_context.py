from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import sys
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


def get_gui_env_normalization(source: Mapping[str, str] | None = None) -> dict[str, Any]:
    original = dict(os.environ if source is None else source)
    normalized = build_gui_launch_env(original)
    remaining_upper = {key.upper() for key in normalized}
    dropped = sorted(key for key in original if key.upper() not in remaining_upper)
    return {
        "applied": True,
        "dropped_keys": dropped,
    }


def _user_object_name(handle: int | None) -> str | None:
    if os.name != "nt" or not handle:
        return None
    try:
        UOI_NAME = 2
        needed = wintypes.DWORD()
        ctypes.windll.user32.GetUserObjectInformationW(handle, UOI_NAME, None, 0, ctypes.byref(needed))
        if not needed.value:
            return None
        char_count = max(1, needed.value // ctypes.sizeof(ctypes.c_wchar))
        buffer = ctypes.create_unicode_buffer(char_count)
        if ctypes.windll.user32.GetUserObjectInformationW(
            handle,
            UOI_NAME,
            buffer,
            needed.value,
            ctypes.byref(needed),
        ):
            return buffer.value
    except Exception:
        return None
    return None


def _desktop_context() -> tuple[str | None, str | None]:
    if os.name != "nt":
        return None, None
    try:
        window_station = ctypes.windll.user32.GetProcessWindowStation()
        thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        desktop = ctypes.windll.user32.GetThreadDesktop(thread_id)
        return _user_object_name(window_station), _user_object_name(desktop)
    except Exception:
        return None, None


def _selected_environment(source: Mapping[str, str]) -> dict[str, str]:
    selected: dict[str, str] = {}
    for key, value in source.items():
        upper = key.upper()
        if upper in _ENV_EXACT or upper.startswith(_ENV_PREFIXES):
            selected[key] = value
    return dict(sorted(selected.items(), key=lambda item: item[0].upper()))


def _path_diagnostics(source: Mapping[str, str]) -> dict[str, Any]:
    path_value = source.get("PATH", "")
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
        "shell": env.get("SHELL") or env.get("COMSPEC"),
        "environment": _selected_environment(env),
        "path": _path_diagnostics(env),
        "gui_env_normalization": get_gui_env_normalization(env),
    }

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .app_resolver import LaunchSpec
from .launch_context import build_gui_launch_env, get_gui_env_normalization
from .processes import get_process_identity


def package_family_installed(target: str) -> bool | None:
    """Check an AppsFolder package family before ShellExecute can show a modal error."""
    if os.name != "nt":
        return None
    prefix = "shell:appsfolder\\"
    if not target.casefold().startswith(prefix) or "!" not in target[len(prefix):]:
        return None
    family = target[len(prefix):].split("!", 1)[0]
    if not family:
        return None
    try:
        function = ctypes.WinDLL("kernel32", use_last_error=True).GetPackagesByPackageFamily
        function.argtypes = [
            wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR,
        ]
        function.restype = wintypes.LONG
        count = wintypes.DWORD()
        buffer_length = wintypes.DWORD()
        status = function(family, ctypes.byref(count), None, ctypes.byref(buffer_length), None)
    except (AttributeError, OSError):
        return None
    if status in (0, 122):
        return count.value > 0
    return None


@dataclass
class DispatchReceipt:
    status: str  # accepted | rejected | unknown
    backend: str
    elapsed_ms: float
    pid: int | None = None
    dispatch_identity: dict[str, Any] | None = None
    resolved: str | None = None
    error_code: int | None = None
    error_type: str | None = None
    message: str | None = None
    fallback_eligible: bool = False
    sanitized_env_applied: bool = False

    @property
    def accepted(self) -> bool | None:
        return True if self.status == "accepted" else False if self.status == "rejected" else None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "status": self.status,
            "accepted": self.accepted,
            "backend": self.backend,
            "elapsed_ms": self.elapsed_ms,
            "pid": self.pid,
            "dispatch_identity": self.dispatch_identity,
            "resolved": self.resolved,
            "error_code": self.error_code,
            "error_type": self.error_type,
            "message": self.message,
            "fallback_eligible": self.fallback_eligible,
            "sanitized_env_applied": self.sanitized_env_applied,
        }
        if self.sanitized_env_applied:
            result["gui_env_normalization"] = get_gui_env_normalization(applied=True)
        return result


def _cwd_for(spec: LaunchSpec, resolved: str, env: dict[str, str]) -> str:
    if spec.cwd:
        return spec.cwd
    path = Path(resolved.strip().strip('"'))
    if path.is_file():
        return str(path.resolve().parent)
    profile = env.get("USERPROFILE")
    return profile if profile and Path(profile).is_dir() else str(Path.home())


def dispatch_process(spec: LaunchSpec, resolved: str) -> DispatchReceipt:
    started = time.monotonic()
    env = build_gui_launch_env()
    suffix = Path(resolved.strip().strip('"')).suffix.casefold()
    command = [resolved, *spec.argv]
    if suffix in {".cmd", ".bat"}:
        command = ["cmd.exe", "/d", "/s", "/c", resolved, *spec.argv]
    creationflags = 0
    is_console_target = os.name == "nt" and Path(resolved).name.casefold() in {
        "cmd.exe", "powershell.exe", "pwsh.exe"
    }
    if is_console_target:
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    try:
        process = subprocess.Popen(
            command,
            shell=False,
            env=env,
            cwd=_cwd_for(spec, resolved, env),
            stdin=None if is_console_target else subprocess.DEVNULL,
            stdout=None if is_console_target else subprocess.DEVNULL,
            stderr=None if is_console_target else subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    except OSError as exc:
        code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
        return DispatchReceipt(
            status="rejected",
            backend="process",
            elapsed_ms=round((time.monotonic() - started) * 1000, 1),
            resolved=resolved,
            error_code=code,
            error_type=type(exc).__name__,
            message=str(exc),
            fallback_eligible=code in {2, 3},
            sanitized_env_applied=True,
        )
    try:
        identity = get_process_identity(process.pid) if os.name == "nt" else None
        observation_error = None
    except Exception as exc:
        identity = None
        observation_error = f"identity lookup: {type(exc).__name__}: {exc}"
    return DispatchReceipt(
        status="accepted",
        backend="process",
        elapsed_ms=round((time.monotonic() - started) * 1000, 1),
        pid=process.pid,
        dispatch_identity=identity.to_dict() if identity is not None else None,
        resolved=resolved,
        message=observation_error,
        sanitized_env_applied=True,
    )


def dispatch_shell(spec: LaunchSpec) -> DispatchReceipt:
    started = time.monotonic()
    if os.name != "nt":
        return DispatchReceipt(
            "rejected", "shell-execute", 0.0, error_type="OSError",
            message="Windows Shell activation is unavailable", fallback_eligible=False,
        )

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SW_SHOWNORMAL = 1
    params = subprocess.list2cmdline(list(spec.argv)) if spec.argv else None
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "open"
    info.lpFile = spec.target
    info.lpParameters = params
    info.lpDirectory = spec.cwd
    info.nShow = SW_SHOWNORMAL
    initialized = False
    try:
        import pythoncom
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        initialized = True
    except Exception as exc:
        return DispatchReceipt(
            "rejected", "shell-execute", round((time.monotonic() - started) * 1000, 1),
            error_type=type(exc).__name__, message=str(exc), fallback_eligible=False,
        )
    try:
        try:
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
            shell32.ShellExecuteExW.restype = wintypes.BOOL
            ctypes.set_last_error(0)
        except Exception as exc:
            return DispatchReceipt(
                "rejected", "shell-execute", round((time.monotonic() - started) * 1000, 1),
                error_type=type(exc).__name__, message=str(exc), fallback_eligible=False,
            )
        try:
            ok = shell32.ShellExecuteExW(ctypes.byref(info))
        except Exception as exc:
            return DispatchReceipt(
                "unknown", "shell-execute", round((time.monotonic() - started) * 1000, 1),
                error_type=type(exc).__name__, message=str(exc), fallback_eligible=False,
            )
        if not ok:
            code = ctypes.get_last_error()
            return DispatchReceipt(
                "rejected", "shell-execute", round((time.monotonic() - started) * 1000, 1),
                error_code=code, error_type="WinError", message=ctypes.FormatError(code),
                fallback_eligible=code in {2, 3, 1155},
            )
        pid: int | None = None
        identity = None
        observation_error = None
        try:
            if info.hProcess:
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.GetProcessId.argtypes = [wintypes.HANDLE]
                kernel32.GetProcessId.restype = wintypes.DWORD
                raw_pid = kernel32.GetProcessId(info.hProcess)
                pid = int(raw_pid) if raw_pid else None
                identity = get_process_identity(pid) if pid is not None else None
        except Exception as exc:
            observation_error = f"{type(exc).__name__}: {exc}"
        finally:
            if info.hProcess:
                try:
                    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
                    kernel32.CloseHandle.restype = wintypes.BOOL
                    kernel32.CloseHandle(info.hProcess)
                    info.hProcess = None
                except Exception as exc:
                    observation_error = f"handle close: {type(exc).__name__}: {exc}"
        return DispatchReceipt(
            "accepted", "shell-execute", round((time.monotonic() - started) * 1000, 1),
            pid=pid, dispatch_identity=identity.to_dict() if identity is not None else None,
            resolved=spec.target, message=observation_error,
        )
    finally:
        if info.hProcess:
            try:
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel32.CloseHandle.restype = wintypes.BOOL
                kernel32.CloseHandle(info.hProcess)
            except Exception:
                pass
        if initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass  # Shell receipt must not be reclassified after activation.


def dispatch(spec: LaunchSpec, resolved: str | None = None) -> DispatchReceipt:
    if spec.kind in {"shortcut", "packaged", "uri"}:
        return dispatch_shell(spec)
    return dispatch_process(spec, resolved or spec.target)

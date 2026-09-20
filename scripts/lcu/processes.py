from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProcessSnapshot(dict[int, "ProcessIdentity"]):
    """A process map that preserves whether collection was trustworthy."""

    def __init__(
        self,
        *args: Any,
        status: str = "ok",
        complete: bool = True,
        error_code: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.status = status
        self.complete = complete
        self.error_code = error_code


def snapshot_is_complete(snapshot: dict[int, "ProcessIdentity"]) -> bool:
    return bool(getattr(snapshot, "complete", True))

SYSTEM_PROCESS_DENYLIST: set[str] = {
    "explorer.exe",
    "applicationframehost.exe",
    "runtimebroker.exe",
    "shellexperiencehost.exe",
    "startmenuexperiencehost.exe",
    "dwm.exe",
    "csrss.exe",
    "winlogon.exe",
    "services.exe",
    "svchost.exe",
    "conhost.exe",
    "system",
    "registry",
    "smss.exe",
    "lsass.exe",
    "fontdrvhost.exe",
    "searchindexer.exe",
    "searchhost.exe",
    "taskhostw.exe",
    "sihost.exe",
    "ctfmon.exe",
}


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    parent_pid: int | None
    process_name: str
    image_path: str | None
    creation_time: int | None
    session_id: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "parent_pid": self.parent_pid,
            "process_name": self.process_name,
            "image_path": self.image_path,
            "creation_time": self.creation_time,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProcessIdentity:
        return cls(
            pid=int(d["pid"]),
            parent_pid=int(d["parent_pid"]) if d.get("parent_pid") is not None else None,
            process_name=str(d.get("process_name", "")),
            image_path=str(d["image_path"]) if d.get("image_path") is not None else None,
            creation_time=int(d["creation_time"]) if d.get("creation_time") is not None else None,
            session_id=int(d["session_id"]) if d.get("session_id") is not None else None,
        )


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


def _last_error_code() -> int | None:
    getter = getattr(ctypes, "get_last_error", None)
    return int(getter()) if getter is not None else None


def _set_signature(function: Any, argtypes: list[Any], restype: Any) -> None:
    try:
        function.argtypes = argtypes
        function.restype = restype
    except Exception:
        pass


def _configure_kernel32(kernel32: Any) -> None:
    handle = wintypes.HANDLE
    _set_signature(kernel32.OpenProcess, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], handle)
    _set_signature(kernel32.CloseHandle, [handle], wintypes.BOOL)
    _set_signature(kernel32.GetProcessTimes, [handle, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)], wintypes.BOOL)
    _set_signature(kernel32.QueryFullProcessImageNameW, [handle, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL)
    _set_signature(kernel32.ProcessIdToSessionId, [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL)
    _set_signature(kernel32.CreateToolhelp32Snapshot, [wintypes.DWORD, wintypes.DWORD], handle)
    _set_signature(kernel32.Process32FirstW, [handle, ctypes.POINTER(PROCESSENTRY32W)], wintypes.BOOL)
    _set_signature(kernel32.Process32NextW, [handle, ctypes.POINTER(PROCESSENTRY32W)], wintypes.BOOL)
    _set_signature(kernel32.GetExitCodeProcess, [handle, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL)
    _set_signature(kernel32.TerminateProcess, [handle, wintypes.UINT], wintypes.BOOL)
    _set_signature(kernel32.WaitForSingleObject, [handle, wintypes.DWORD], wintypes.DWORD)


def _identity_from_handle(
    kernel32: Any,
    handle: int,
    pid: int,
    parent_pid: int | None = None,
    process_name: str | None = None,
) -> ProcessIdentity | None:
    create_t = FILETIME()
    exit_t = FILETIME()
    kernel_t = FILETIME()
    user_t = FILETIME()
    if not kernel32.GetProcessTimes(
        handle,
        ctypes.byref(create_t),
        ctypes.byref(exit_t),
        ctypes.byref(kernel_t),
        ctypes.byref(user_t),
    ):
        return None
    creation_time = (create_t.dwHighDateTime << 32) | create_t.dwLowDateTime

    buf = ctypes.create_unicode_buffer(1024)
    size = wintypes.DWORD(1024)
    if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
        return None
    image_path = buf.value

    sess_id = wintypes.DWORD()
    if not kernel32.ProcessIdToSessionId(pid, ctypes.byref(sess_id)):
        return None
    return ProcessIdentity(
        pid=pid,
        parent_pid=parent_pid,
        process_name=process_name or Path(image_path).name,
        image_path=image_path,
        creation_time=creation_time,
        session_id=sess_id.value,
    )


def get_current_session_id() -> int | None:
    if os.name != "nt":
        return None
    kernel32 = ctypes.windll.kernel32
    _configure_kernel32(kernel32)
    sess_id = wintypes.DWORD()
    if kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sess_id)):
        return sess_id.value
    return None


def get_process_identity(
    pid: int,
    parent_pid: int | None = None,
    process_name: str | None = None,
) -> ProcessIdentity | None:
    if os.name != "nt":
        return None

    kernel32 = ctypes.windll.kernel32
    _configure_kernel32(kernel32)
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not hproc:
        return None

    try:
        return _identity_from_handle(
            kernel32,
            hproc,
            pid,
            parent_pid=parent_pid,
            process_name=process_name,
        )
    finally:
        kernel32.CloseHandle(hproc)


def snapshot_processes() -> dict[int, ProcessIdentity]:
    if os.name != "nt":
        return ProcessSnapshot(status="unsupported", complete=False)

    kernel32 = ctypes.windll.kernel32
    _configure_kernel32(kernel32)
    TH32CS_SNAPPROCESS = 0x00000002
    h_snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if h_snap == invalid_handle or not h_snap:
        return ProcessSnapshot(status="error", complete=False, error_code=_last_error_code())

    pe = PROCESSENTRY32W()
    pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)

    raw_entries: list[tuple[int, int, str]] = []
    success = kernel32.Process32FirstW(h_snap, ctypes.byref(pe))
    if not success:
        error_code = _last_error_code()
        kernel32.CloseHandle(h_snap)
        return ProcessSnapshot(status="error", complete=False, error_code=error_code)
    while success:
        raw_entries.append((pe.th32ProcessID, pe.th32ParentProcessID, pe.szExeFile))
        success = kernel32.Process32NextW(h_snap, ctypes.byref(pe))
    kernel32.CloseHandle(h_snap)

    result: ProcessSnapshot = ProcessSnapshot()
    complete = True
    for pid, ppid, exe_file in raw_entries:
        if pid == 0:
            continue
        ident = get_process_identity(pid, parent_pid=ppid, process_name=exe_file)
        if ident is not None:
            result[pid] = ident
        else:
            complete = False
            result[pid] = ProcessIdentity(
                pid=pid,
                parent_pid=ppid,
                process_name=exe_file,
                image_path=None,
                creation_time=None,
                session_id=None,
            )
    result.complete = complete
    result.status = "ok" if complete else "partial"
    return result


def is_same_process(identity: ProcessIdentity) -> bool | None:
    if os.name != "nt":
        return False
    current_ident = get_process_identity(identity.pid)
    if current_ident is None:
        return None
    if identity.creation_time is None or current_ident.creation_time is None:
        return None
    if current_ident.creation_time != identity.creation_time:
        return False
    if identity.session_id is None or current_ident.session_id is None:
        return None
    if identity.session_id != current_ident.session_id:
        return False
    if identity.image_path and current_ident.image_path:
        if identity.image_path.lower() != current_ident.image_path.lower():
            return False
    elif identity.process_name and current_ident.process_name:
        if identity.process_name.lower() != current_ident.process_name.lower():
            return False
    return True


def is_process_alive(target: ProcessIdentity | int) -> bool | None:
    if isinstance(target, ProcessIdentity):
        return is_same_process(target)
    if os.name != "nt":
        return None
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, target)
    if not hproc:
        return None
    try:
        exit_code = wintypes.DWORD()
        STILL_ACTIVE = 259
        if kernel32.GetExitCodeProcess(hproc, ctypes.byref(exit_code)):
            return exit_code.value == STILL_ACTIVE
        return None
    finally:
        kernel32.CloseHandle(hproc)


def has_visible_windows(pid: int, exclude_hwnd: int | None = None) -> bool | None:
    """Conservatively report any protected top-level HWND for a process.

    The historical name is retained for API compatibility. Hidden, cloaked, untitled,
    and zero-sized top-level windows are protective because their presence can indicate
    shared or user-owned process state.
    """
    if os.name != "nt":
        return False
    try:
        import win32gui
        import win32process

        found = False

        def enum_win(h: int, _: Any) -> bool:
            nonlocal found
            if exclude_hwnd and h == exclude_hwnd:
                return True
            _, win_pid = win32process.GetWindowThreadProcessId(h)
            if win_pid == pid:
                found = True
                return False
            return True

        win32gui.EnumWindows(enum_win, None)
        return found
    except Exception:
        return None


def validate_termination_safety(
    identity: ProcessIdentity,
    baseline_pids: set[int] | None = None,
    allowed_process_names: list[str] | None = None,
    exclude_hwnd: int | None = None,
) -> tuple[bool, str]:
    # 1. Baseline check: was PID alive before this launch?
    if baseline_pids is not None and identity.pid in baseline_pids:
        return False, f"PID {identity.pid} was present in baseline process snapshot"

    # 2. Denylist check
    proc_name = identity.process_name.lower()
    if proc_name in SYSTEM_PROCESS_DENYLIST:
        return (
            False,
            f"Process '{identity.process_name}' (PID {identity.pid}) is in SYSTEM_PROCESS_DENYLIST",
        )

    # 3. Allowed process names check
    if allowed_process_names:
        allowed_lower = [n.lower() for n in allowed_process_names]
        if proc_name not in allowed_lower and not any(proc_name.endswith(n) for n in allowed_lower):
            return (
                False,
                f"Process '{identity.process_name}' (PID {identity.pid}) does not match allowed names: {allowed_process_names}",
            )

    if identity.creation_time is None:
        return False, f"Process PID {identity.pid} has no creation-time identity"
    if identity.session_id is None:
        return False, f"Process PID {identity.pid} has no session identity"
    if not identity.image_path and not identity.process_name:
        return False, f"Process PID {identity.pid} has no image identity"

    # 4. Same interactive session
    curr_sess = get_current_session_id()
    if curr_sess is None:
        return False, "Current interactive session could not be verified"
    if identity.session_id != curr_sess:
        return (
            False,
            f"Process PID {identity.pid} belongs to session {identity.session_id}, current session is {curr_sess}",
        )

    # 5. Identity verification (PID reuse check)
    same_process = is_same_process(identity)
    if same_process is not True:
        return (
            False,
            f"Process PID {identity.pid} identity verification failed or was unavailable",
        )

    # 6. Check for other visible windows
    window_state = has_visible_windows(identity.pid, exclude_hwnd=exclude_hwnd)
    if window_state is None:
        return False, f"Process PID {identity.pid} window ownership could not be verified"
    if window_state:
        return False, f"Process PID {identity.pid} still owns visible top-level windows"

    return True, "ok"


def terminate_process(identity: ProcessIdentity, timeout: float = 2.0) -> bool:
    if os.name != "nt":
        return False

    if identity.creation_time is None or identity.session_id is None:
        return False
    if identity.process_name.lower() in SYSTEM_PROCESS_DENYLIST:
        return False

    kernel32 = ctypes.windll.kernel32
    _configure_kernel32(kernel32)
    PROCESS_TERMINATE = 0x0001
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    SYNCHRONIZE = 0x00100000

    hproc = kernel32.OpenProcess(
        PROCESS_TERMINATE | SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION,
        False,
        identity.pid,
    )
    if not hproc:
        return False

    try:
        verified = _identity_from_handle(kernel32, hproc, identity.pid)
        if verified is None:
            return False
        if verified.creation_time != identity.creation_time or verified.session_id != identity.session_id:
            return False
        if identity.image_path:
            if not verified.image_path or verified.image_path.lower() != identity.image_path.lower():
                return False
        elif identity.process_name.lower() != verified.process_name.lower():
            return False

        current_session = get_current_session_id()
        if current_session is None or verified.session_id != current_session:
            return False
        window_state = has_visible_windows(identity.pid)
        if window_state is not False:
            return False

        exit_code = wintypes.DWORD()
        STILL_ACTIVE = 259
        if not kernel32.GetExitCodeProcess(hproc, ctypes.byref(exit_code)):
            return False
        if exit_code.value != STILL_ACTIVE:
            return True

        if not kernel32.TerminateProcess(hproc, 0):
            return False
        WAIT_OBJECT_0 = 0x00000000
        res = kernel32.WaitForSingleObject(hproc, int(timeout * 1000))
        return res == WAIT_OBJECT_0
    finally:
        kernel32.CloseHandle(hproc)

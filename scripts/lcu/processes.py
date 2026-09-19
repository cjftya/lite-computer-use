from __future__ import annotations

import ctypes
import os
import signal
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def get_current_session_id() -> int | None:
    if os.name != "nt":
        return None
    sess_id = wintypes.DWORD()
    if ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sess_id)):
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
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not hproc:
        return None

    try:
        create_t = FILETIME()
        exit_t = FILETIME()
        kernel_t = FILETIME()
        user_t = FILETIME()
        c_time: int | None = None
        if kernel32.GetProcessTimes(
            hproc,
            ctypes.byref(create_t),
            ctypes.byref(exit_t),
            ctypes.byref(kernel_t),
            ctypes.byref(user_t),
        ):
            c_time = (create_t.dwHighDateTime << 32) | create_t.dwLowDateTime

        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        img_path: str | None = None
        if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
            img_path = buf.value

        sess_id = wintypes.DWORD()
        session: int | None = None
        if kernel32.ProcessIdToSessionId(pid, ctypes.byref(sess_id)):
            session = sess_id.value

        p_name = process_name
        if not p_name and img_path:
            p_name = Path(img_path).name

        return ProcessIdentity(
            pid=pid,
            parent_pid=parent_pid,
            process_name=p_name or "",
            image_path=img_path,
            creation_time=c_time,
            session_id=session,
        )
    finally:
        kernel32.CloseHandle(hproc)


def snapshot_processes() -> dict[int, ProcessIdentity]:
    if os.name != "nt":
        return {}

    kernel32 = ctypes.windll.kernel32
    TH32CS_SNAPPROCESS = 0x00000002
    h_snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if h_snap == -1 or not h_snap:
        return {}

    pe = PROCESSENTRY32W()
    pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)

    raw_entries: list[tuple[int, int, str]] = []
    success = kernel32.Process32FirstW(h_snap, ctypes.byref(pe))
    while success:
        raw_entries.append((pe.th32ProcessID, pe.th32ParentProcessID, pe.szExeFile))
        success = kernel32.Process32NextW(h_snap, ctypes.byref(pe))
    kernel32.CloseHandle(h_snap)

    result: dict[int, ProcessIdentity] = {}
    for pid, ppid, exe_file in raw_entries:
        if pid == 0:
            continue
        ident = get_process_identity(pid, parent_pid=ppid, process_name=exe_file)
        if ident is not None:
            result[pid] = ident
        else:
            result[pid] = ProcessIdentity(
                pid=pid,
                parent_pid=ppid,
                process_name=exe_file,
                image_path=None,
                creation_time=None,
                session_id=None,
            )
    return result


def is_same_process(identity: ProcessIdentity) -> bool:
    if os.name != "nt":
        return False
    current_ident = get_process_identity(identity.pid)
    if current_ident is None:
        return False
    if identity.creation_time is not None and current_ident.creation_time != identity.creation_time:
        return False
    if identity.image_path and current_ident.image_path:
        if identity.image_path.lower() != current_ident.image_path.lower():
            return False
    elif identity.process_name and current_ident.process_name:
        if identity.process_name.lower() != current_ident.process_name.lower():
            return False
    return True


def is_process_alive(target: ProcessIdentity | int) -> bool:
    if isinstance(target, ProcessIdentity):
        return is_same_process(target)
    if os.name != "nt":
        return False
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, target)
    if not hproc:
        return False
    try:
        exit_code = wintypes.DWORD()
        STILL_ACTIVE = 259
        if kernel32.GetExitCodeProcess(hproc, ctypes.byref(exit_code)):
            return exit_code.value == STILL_ACTIVE
        return True
    finally:
        kernel32.CloseHandle(hproc)


def has_visible_windows(pid: int, exclude_hwnd: int | None = None) -> bool:
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
            if not win32gui.IsWindowVisible(h):
                return True
            title = win32gui.GetWindowText(h).strip()
            if not title:
                return True
            rect = win32gui.GetWindowRect(h)
            if rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0:
                return True
            _, win_pid = win32process.GetWindowThreadProcessId(h)
            if win_pid == pid:
                cloaked = ctypes.c_int(0)
                res = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                    h, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
                )
                if res == 0 and cloaked.value != 0:
                    return True
                found = True
                return False
            return True

        win32gui.EnumWindows(enum_win, None)
        return found
    except Exception:
        return False


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

    # 4. Same interactive session
    curr_sess = get_current_session_id()
    if curr_sess is not None and identity.session_id is not None and identity.session_id != curr_sess:
        return (
            False,
            f"Process PID {identity.pid} belongs to session {identity.session_id}, current session is {curr_sess}",
        )

    # 5. Identity verification (PID reuse check)
    if not is_same_process(identity):
        return (
            False,
            f"Process PID {identity.pid} identity verification failed (process exited or PID reused)",
        )

    # 6. Check for other visible windows
    if has_visible_windows(identity.pid, exclude_hwnd=exclude_hwnd):
        return False, f"Process PID {identity.pid} still owns visible top-level windows"

    return True, "ok"


def terminate_process(identity: ProcessIdentity, timeout: float = 2.0) -> bool:
    if os.name != "nt":
        try:
            os.kill(identity.pid, signal.SIGTERM)
            return True
        except Exception:
            return False

    kernel32 = ctypes.windll.kernel32
    PROCESS_TERMINATE = 0x0001
    SYNCHRONIZE = 0x00100000

    hproc = kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, identity.pid)
    if not hproc:
        return True

    try:
        if not kernel32.TerminateProcess(hproc, 0):
            return False
        WAIT_OBJECT_0 = 0x00000000
        res = kernel32.WaitForSingleObject(hproc, int(timeout * 1000))
        return res == WAIT_OBJECT_0
    finally:
        kernel32.CloseHandle(hproc)

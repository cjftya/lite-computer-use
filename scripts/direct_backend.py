from __future__ import annotations

import ntpath
import os
import re
import stat
import subprocess
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from helpers import LCUError, known_folders


BLOCKED_OPEN_EXTENSIONS = {
    ".appref-ms",
    ".application",
    ".bat",
    ".chm",
    ".cmd",
    ".com",
    ".cpl",
    ".exe",
    ".hta",
    ".iso",
    ".jar",
    ".js",
    ".jse",
    ".lnk",
    ".msc",
    ".msi",
    ".ps1",
    ".py",
    ".pyw",
    ".reg",
    ".scr",
    ".sh",
    ".url",
    ".vbs",
    ".vbe",
    ".ws",
    ".wsf",
}

_PERCENT_ENV = re.compile(r"%([^%]+)%")
_DOLLAR_ENV = re.compile(r"\$(?:\{([^}]+)\}|([A-Za-z_][A-Za-z0-9_]*))")


def _expand_path(value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise LCUError(
            "invalid_path",
            "Path cannot be empty",
            stage="validate",
            retryable=False,
            nextAction="provide_absolute_path",
        )
    raw = value.strip()

    missing: set[str] = set()

    def replace_percent(match: re.Match[str]) -> str:
        name = match.group(1)
        replacement = os.environ.get(name)
        if replacement is None:
            missing.add(name)
            return match.group(0)
        return replacement

    def replace_dollar(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        replacement = os.environ.get(name)
        if replacement is None:
            missing.add(name)
            return match.group(0)
        return replacement

    expanded = _PERCENT_ENV.sub(replace_percent, raw)
    expanded = _DOLLAR_ENV.sub(replace_dollar, expanded)
    expanded = os.path.expanduser(expanded)
    if missing:
        raise LCUError(
            "unresolved_environment_variable",
            "Path contains an environment variable that is not defined",
            variables=sorted(missing),
            stage="validate",
            retryable=False,
            nextAction="provide_resolved_absolute_path",
        )

    drive, tail = ntpath.splitdrive(expanded)
    if drive and not tail.startswith(("\\", "/")):
        raise LCUError(
            "drive_relative_path",
            "Drive-relative paths such as C:folder are not allowed",
            stage="validate",
            retryable=False,
            nextAction="provide_absolute_path",
        )
    if not drive and (
        expanded.startswith("\\") or (os.name == "nt" and expanded.startswith("/"))
    ):
        raise LCUError(
            "root_relative_path",
            "Root-relative paths require an explicit drive or UNC share",
            stage="validate",
            retryable=False,
            nextAction="provide_absolute_path",
        )
    if not (ntpath.isabs(expanded) or Path(expanded).is_absolute()):
        raise LCUError(
            "relative_path_not_allowed",
            "Relative paths are not allowed",
            stage="validate",
            retryable=False,
            nextAction="provide_absolute_path",
        )
    return Path(expanded)


def _dispatch_error(exc: OSError, operation: str) -> LCUError:
    winerror = getattr(exc, "winerror", None)
    errno = getattr(exc, "errno", None)
    error_number = winerror if winerror is not None else errno
    details = {
        "stage": "dispatch",
        "operation": operation,
        "osError": error_number,
    }
    if error_number in {2, 3}:
        return LCUError(
            "target_not_found",
            "Windows could not find the target while dispatching the request",
            **details,
            retryable=False,
            nextAction="verify_target_path",
        )
    if error_number == 5:
        return LCUError(
            "access_denied",
            "Windows denied access to the target",
            **details,
            retryable=False,
            nextAction="check_access",
        )
    if error_number == 1155:
        return LCUError(
            "file_association_missing",
            "No application is registered for this file type",
            **details,
            retryable=False,
            nextAction="choose_an_application",
        )
    return LCUError(
        "dispatch_failed",
        "Windows rejected the open request",
        **details,
        retryable=False,
        nextAction="inspect_os_error",
    )


def _accepted(**values: Any) -> dict[str, Any]:
    return {
        **values,
        "status": "dispatch_accepted",
        "dispatchAccepted": True,
        "osStateVerified": False,
        "verification": "unverified",
    }


def _validate_existing(path: Path, expected: str) -> None:
    try:
        mode = path.stat().st_mode
    except FileNotFoundError as exc:
        code = "file_not_found" if expected == "file" else "folder_not_found"
        raise LCUError(
            code,
            f"{expected.title()} does not exist",
            stage="validate",
            retryable=False,
            nextAction="verify_target_path",
        ) from exc
    except PermissionError as exc:
        raise LCUError(
            "access_denied",
            "Access was denied while validating the target",
            stage="validate",
            osError=getattr(exc, "winerror", None) or exc.errno,
            retryable=False,
            nextAction="check_access",
        ) from exc
    except OSError as exc:
        raise LCUError(
            "path_validation_failed",
            "The target could not be validated",
            stage="validate",
            osError=getattr(exc, "winerror", None) or exc.errno,
            retryable=False,
            nextAction="inspect_os_error",
        ) from exc
    matches = stat.S_ISREG(mode) if expected == "file" else stat.S_ISDIR(mode)
    if not matches:
        code = "not_a_file" if expected == "file" else "not_a_folder"
        next_action = "use_open_folder" if expected == "file" else "use_open_file"
        raise LCUError(
            code,
            f"Path is not a {expected}",
            stage="validate",
            retryable=False,
            nextAction=next_action,
        )


class DirectWindowsBackend:
    """Shell-only actions that must not import screenshot or input libraries."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise LCUError("unsupported_platform", "Lite Computer Use requires Windows")

    @staticmethod
    def open_file(path_value: str) -> dict[str, Any]:
        path = _expand_path(path_value)
        _validate_existing(path, "file")
        if path.suffix.casefold() in BLOCKED_OPEN_EXTENSIONS:
            raise LCUError(
                "executable_file_blocked",
                "open_file does not execute programs or scripts",
                extension=path.suffix.casefold(),
                stage="validate",
                retryable=False,
                nextAction="use_launch_app_for_registered_apps",
            )
        try:
            os.startfile(str(path))
        except OSError as exc:
            raise _dispatch_error(exc, "open_file") from exc
        return _accepted(path=str(path))

    @staticmethod
    def open_folder(path_value: str) -> dict[str, Any]:
        path = _expand_path(path_value)
        _validate_existing(path, "folder")
        try:
            os.startfile(str(path))
        except OSError as exc:
            raise _dispatch_error(exc, "open_folder") from exc
        return _accepted(path=str(path))

    @staticmethod
    def reveal_file(path_value: str) -> dict[str, Any]:
        path = _expand_path(path_value)
        _validate_existing(path, "file")
        try:
            # A list invocation lets subprocess quote the single Explorer
            # /select argument correctly without adding literal quote characters.
            subprocess.Popen(["explorer.exe", f"/select,{path}"], close_fds=True)
        except OSError as exc:
            raise _dispatch_error(exc, "reveal_file") from exc
        return _accepted(path=str(path))

    @staticmethod
    def open_url(url: str) -> dict[str, Any]:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise LCUError(
                "invalid_url",
                "Only absolute HTTP and HTTPS URLs are allowed",
                stage="validate",
                retryable=False,
                nextAction="provide_http_url",
            )
        try:
            accepted = webbrowser.open(url, new=0, autoraise=True)
        except OSError as exc:
            raise _dispatch_error(exc, "open_url") from exc
        except webbrowser.Error as exc:
            raise LCUError(
                "browser_launch_failed",
                "The default browser could not handle the URL",
                stage="dispatch",
                retryable=False,
                nextAction="check_default_browser",
            ) from exc
        if not accepted:
            raise LCUError(
                "browser_launch_failed",
                "The default browser rejected the URL",
                stage="dispatch",
                retryable=False,
                nextAction="check_default_browser",
            )
        return _accepted(url=url, host=parsed.hostname)

    @staticmethod
    def known_folder(name: str) -> dict[str, Any]:
        key = name.strip().casefold()
        aliases = {
            "desktop": "desktop",
            "바탕화면": "desktop",
            "documents": "documents",
            "document": "documents",
            "문서": "documents",
            "downloads": "downloads",
            "download": "downloads",
            "다운로드": "downloads",
        }
        canonical = aliases.get(key)
        if canonical is None:
            raise LCUError(
                "unknown_known_folder",
                "Known folder must be Desktop, Documents, or Downloads",
                stage="resolve",
                retryable=False,
                nextAction="choose_known_folder",
            )
        folder = known_folders()[canonical]
        return {"name": canonical, **folder}

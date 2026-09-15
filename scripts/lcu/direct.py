from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import subprocess
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

from .errors import LCUError

BLOCKED_OPEN_EXTENSIONS = {
    ".exe",
    ".bat",
    ".cmd",
    ".com",
    ".msi",
    ".ps1",
    ".vbs",
    ".vbe",
    ".js",
    ".jse",
    ".ws",
    ".wsf",
    ".scr",
    ".hta",
    ".cpl",
    ".reg",
    ".jar",
    ".application",
    ".appref-ms",
}

DEFAULT_EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    "$recycle.bin",
    "system volume information",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
}

FOLDER_ALIASES: dict[str, str] = {
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "바탕화면": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "다운로드": "{374DE290-123F-4565-9164-39C4925E467B}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "문서": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
}


def get_known_folder(alias_or_guid: str) -> Path | None:
    guid_str = FOLDER_ALIASES.get(alias_or_guid.lower(), alias_or_guid)
    if os.name == "nt":
        try:
            fid = uuid.UUID(guid_str)
            guid_cls = ctypes.c_char * 16
            raw_guid = guid_cls(*fid.bytes_le)
            p_path = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(raw_guid, 0, None, ctypes.byref(p_path)) == 0:
                if p_path.value:
                    return Path(p_path.value)
        except Exception:
            pass

    # Fallback to Path.home()
    norm = alias_or_guid.lower()
    home = Path.home()
    if norm in ("desktop", "바탕화면"):
        return home / "Desktop"
    if norm in ("downloads", "다운로드"):
        return home / "Downloads"
    if norm in ("documents", "문서"):
        return home / "Documents"
    return None


def resolve_folder_path(path_or_alias: str) -> Path:
    alias_target = get_known_folder(path_or_alias)
    if alias_target is not None:
        return alias_target

    p = Path(path_or_alias)
    if not p.is_absolute():
        raise LCUError("invalid_arguments", f"Folder path must be absolute or a known alias: {path_or_alias}")
    return p


def open_file(path_str: str) -> dict[str, Any]:
    if not path_str or not path_str.strip():
        raise LCUError("invalid_arguments", "Path cannot be empty")

    path = Path(path_str)
    if not path.is_absolute():
        raise LCUError("invalid_arguments", f"Path must be absolute: {path_str}")
    path = path.resolve()

    if not path.exists():
        raise LCUError("not_found", f"File not found: {path_str}")

    if not path.is_file():
        raise LCUError("invalid_arguments", f"Target is not a file: {path_str}")

    ext = path.suffix.lower()
    if ext in BLOCKED_OPEN_EXTENSIONS:
        raise LCUError(
            "invalid_arguments",
            f"Executable or script files cannot be opened using open_file: {path.name}. Use open_app instead.",
        )

    try:
        os.startfile(str(path))
    except Exception as exc:
        raise LCUError("dispatch_failed", f"Failed to open file: {exc}") from exc

    return {"path": str(path)}


def open_folder(path_or_alias: str) -> dict[str, Any]:
    if not path_or_alias or not path_or_alias.strip():
        raise LCUError("invalid_arguments", "Folder path or alias cannot be empty")

    folder = resolve_folder_path(path_or_alias.strip()).resolve()

    if not folder.exists():
        raise LCUError("not_found", f"Folder not found: {folder}")

    if not folder.is_dir():
        raise LCUError("invalid_arguments", f"Target is not a directory: {folder}")

    try:
        os.startfile(str(folder))
    except Exception as exc:
        raise LCUError("dispatch_failed", f"Failed to open folder: {exc}") from exc

    return {"path": str(folder)}


def open_url(url: str) -> dict[str, Any]:
    if not url or not url.strip():
        raise LCUError("invalid_arguments", "URL cannot be empty")

    parsed = urllib.parse.urlsplit(url.strip())
    if parsed.scheme.lower() not in ("http", "https"):
        raise LCUError("invalid_arguments", f"Only http and https URLs are allowed: {url}")

    try:
        os.startfile(url.strip())
    except Exception:
        import webbrowser

        try:
            webbrowser.open(url.strip())
        except Exception as exc:
            raise LCUError("dispatch_failed", f"Failed to open URL: {exc}") from exc

    return {"url": url.strip()}


def reveal_file(path_str: str) -> dict[str, Any]:
    if not path_str or not path_str.strip():
        raise LCUError("invalid_arguments", "Path cannot be empty")

    path = Path(path_str)
    if not path.is_absolute():
        raise LCUError("invalid_arguments", f"Path must be absolute: {path_str}")
    path = path.resolve()

    if not path.exists():
        raise LCUError("not_found", f"File not found: {path_str}")

    try:
        subprocess.Popen(["explorer.exe", f"/select,{str(path)}"])
    except Exception as exc:
        raise LCUError("dispatch_failed", f"Failed to reveal file: {exc}") from exc

    return {"path": str(path)}


def find_path(
    query: str,
    root: str,
    kind: str = "any",
    limit: int = 10,
    max_depth: int = 5,
    timeout: float = 3.0,
) -> dict[str, Any]:
    if not query or not query.strip():
        raise LCUError("invalid_arguments", "Search query cannot be empty")
    if not root or not root.strip():
        raise LCUError("invalid_arguments", "Search root is required")
    if kind not in ("any", "file", "folder"):
        raise LCUError("invalid_arguments", f"Invalid kind: {kind}. Must be 'any', 'file', or 'folder'.")
    if limit < 1:
        raise LCUError("invalid_arguments", "Limit must be at least 1")
    if max_depth < 1:
        raise LCUError("invalid_arguments", "Max depth must be at least 1")

    root_dir = resolve_folder_path(root.strip()).resolve()
    if not root_dir.exists() or not root_dir.is_dir():
        raise LCUError("not_found", f"Search root directory not found: {root_dir}")

    q_lower = query.strip().lower()
    start_time = time.time()
    results: list[dict[str, Any]] = []

    # BFS or bounded DFS
    def _search(current_dir: Path, current_depth: int) -> None:
        if len(results) >= limit:
            return
        if time.time() - start_time > timeout:
            return
        if current_depth > max_depth:
            return

        try:
            with os.scandir(current_dir) as it:
                entries = list(it)
        except (PermissionError, OSError):
            return

        subdirs: list[Path] = []
        for entry in entries:
            name_lower = entry.name.lower()
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
            except OSError:
                continue

            if is_dir:
                if name_lower in DEFAULT_EXCLUDED_DIRS:
                    continue
                subdirs.append(Path(entry.path))

            matched = q_lower in name_lower
            if matched:
                if is_file and kind in ("any", "file"):
                    try:
                        stat_res = entry.stat()
                        size = stat_res.st_size
                        mtime = stat_res.st_mtime
                    except OSError:
                        size = None
                        mtime = None
                    results.append(
                        {
                            "path": entry.path,
                            "name": entry.name,
                            "kind": "file",
                            "size": size,
                            "modified": mtime,
                        }
                    )
                elif is_dir and kind in ("any", "folder"):
                    try:
                        mtime = entry.stat().st_mtime
                    except OSError:
                        mtime = None
                    results.append(
                        {
                            "path": entry.path,
                            "name": entry.name,
                            "kind": "folder",
                            "size": None,
                            "modified": mtime,
                        }
                    )

            if len(results) >= limit:
                return

        for sub in subdirs:
            _search(sub, current_depth + 1)
            if len(results) >= limit or time.time() - start_time > timeout:
                return

    _search(root_dir, 1)

    return {
        "query": query.strip(),
        "root": str(root_dir),
        "kind": kind,
        "count": len(results),
        "matches": results,
    }

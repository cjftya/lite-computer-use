from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.lcu.apps import (
    APP_INDEX_CACHE_VERSION,
    AppEntry,
    _is_packaged_app_command,
    build_app_index,
    find_app_entry,
    open_app,
)
from scripts.lcu.direct import (
    find_path,
    get_known_folder,
    open_file,
    open_folder,
    open_url,
    resolve_folder_path,
    reveal_file,
)
from scripts.lcu.errors import LCUError


def test_open_file_validation(tmp_path: Path) -> None:
    # Empty
    with pytest.raises(LCUError) as exc_info:
        open_file("")
    assert exc_info.value.code == "invalid_arguments"

    # Non-existent
    non_existent = tmp_path / "not_found.txt"
    with pytest.raises(LCUError) as exc_info:
        open_file(str(non_existent))
    assert exc_info.value.code == "not_found"

    # Relative path
    with pytest.raises(LCUError) as exc_info:
        open_file("relative_file.txt")
    assert exc_info.value.code == "invalid_arguments"
    assert "Path must be absolute" in exc_info.value.message

    # Blocked extension
    exe_file = tmp_path / "malicious.exe"
    exe_file.write_text("test")
    with pytest.raises(LCUError) as exc_info:
        open_file(str(exe_file))
    assert exc_info.value.code == "invalid_arguments"

    # Valid file
    txt_file = tmp_path / "valid.txt"
    txt_file.write_text("hello")
    with patch("os.startfile") as mock_start:
        res = open_file(str(txt_file))
        assert res["path"] == str(txt_file.resolve())
        mock_start.assert_called_once_with(str(txt_file.resolve()))


def test_open_folder(tmp_path: Path) -> None:
    with pytest.raises(LCUError) as exc_info:
        open_folder("")
    assert exc_info.value.code == "invalid_arguments"

    # Non-existent folder
    with pytest.raises(LCUError) as exc_info:
        open_folder(str(tmp_path / "does_not_exist"))
    assert exc_info.value.code == "not_found"

    # Known folder alias
    desktop = get_known_folder("desktop")
    assert desktop is not None
    assert desktop.is_absolute()

    sub = tmp_path / "mysubdir"
    sub.mkdir()
    with patch("os.startfile") as mock_start:
        res = open_folder(str(sub))
        assert res["path"] == str(sub.resolve())
        mock_start.assert_called_once_with(str(sub.resolve()))


def test_open_url() -> None:
    with pytest.raises(LCUError) as exc_info:
        open_url("")
    assert exc_info.value.code == "invalid_arguments"

    with pytest.raises(LCUError) as exc_info:
        open_url("javascript:alert(1)")
    assert exc_info.value.code == "invalid_arguments"

    with patch("os.startfile") as mock_start:
        res = open_url("https://example.com")
        assert res["url"] == "https://example.com"
        mock_start.assert_called_once_with("https://example.com")


def test_reveal_file(tmp_path: Path) -> None:
    # Relative path
    with pytest.raises(LCUError) as exc_info:
        reveal_file("relative_file.txt")
    assert exc_info.value.code == "invalid_arguments"
    assert "Path must be absolute" in exc_info.value.message

    target = tmp_path / "myfile.dat"
    target.write_text("data")

    with patch("subprocess.Popen") as mock_popen:
        res = reveal_file(str(target))
        assert res["path"] == str(target.resolve())
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "explorer.exe"
        assert f"/select,{str(target.resolve())}" in cmd[1]


def test_find_path(tmp_path: Path) -> None:
    # Setup files
    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "beta.md").write_text("b")
    sub = tmp_path / "subfolder"
    sub.mkdir()
    (sub / "alpha_sub.txt").write_text("as")
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "alpha_git.txt").write_text("git")

    res = find_path("alpha", root=str(tmp_path), kind="file")
    matches = res["matches"]
    paths = [m["name"] for m in matches]
    assert "alpha.txt" in paths
    assert "alpha_sub.txt" in paths
    assert "alpha_git.txt" not in paths  # Ignored .git directory

    # Find folder
    folder_res = find_path("subfolder", root=str(tmp_path), kind="folder")
    assert len(folder_res["matches"]) == 1
    assert folder_res["matches"][0]["name"] == "subfolder"


def test_apps_matching() -> None:
    index = [
        AppEntry("Google Chrome", "chrome.exe", "config", ["chrome", "google chrome", "크롬"], "googlechrome"),
        AppEntry("Notepad", "notepad.exe", "config", ["notepad", "메모장"], "notepad"),
        AppEntry("Calculator", "calc.exe", "config", ["calculator", "계산기"], "calculator"),
        AppEntry("Notepad++", "notepad++.exe", "start-menu", ["notepad++"], "notepad++"),
    ]

    # Exact alias match
    entry, cand = find_app_entry("chrome", index)
    assert entry is not None
    assert entry.name == "Google Chrome"

    # Korean alias match
    entry, cand = find_app_entry("계산기", index)
    assert entry is not None
    assert entry.name == "Calculator"

    # Not found
    entry, cand = find_app_entry("NonExistentApp12345", index)
    assert entry is None
    assert cand == []

    # Ambiguity test
    ambig_index = [
        AppEntry("App Beta 1", "beta1.exe", "start-menu", ["beta1"], "appbeta1"),
        AppEntry("App Beta 2", "beta2.exe", "start-menu", ["beta2"], "appbeta2"),
    ]
    entry, cand = find_app_entry("beta", ambig_index)
    assert entry is None
    assert len(cand) == 2


def test_open_app_mocked() -> None:
    with patch("scripts.lcu.apps.build_app_index") as mock_build:
        mock_build.return_value = [
            AppEntry("Notepad", "notepad.exe", "config", ["notepad", "메모장"], "notepad")
        ]
        with patch("os.startfile") as mock_start:
            res = open_app("notepad")
            assert res["app"] == "Notepad"
            mock_start.assert_called_once_with("notepad.exe")

        # Not found error
        with pytest.raises(LCUError) as exc_info:
            open_app("nonexistent")
        assert exc_info.value.code == "not_found"


def test_open_app_packaged_fallback_on_missing_window() -> None:
    app_x_cmd = r"shell:AppsFolder\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App"
    entry = AppEntry(
        "Notepad",
        "notepad.exe",
        "config",
        ["notepad", "메모장"],
        "notepad",
        commands=["notepad.exe", app_x_cmd],
    )
    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("os.name", "nt"), \
         patch("os.startfile") as mock_start, \
         patch("scripts.lcu.windows.list_windows", return_value=[]), \
         patch("time.sleep"):
        res = open_app("notepad")
        assert res["app"] == "Notepad"
        assert res["target"] == app_x_cmd
        assert mock_start.call_count == 2
        mock_start.assert_any_call("notepad.exe")
        mock_start.assert_any_call(app_x_cmd)


def test_open_app_packaged_fallback_on_dispatch_error() -> None:
    app_x_cmd = r"shell:AppsFolder\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"
    entry = AppEntry(
        "Calculator",
        "calc.exe",
        "config",
        ["calculator", "계산기"],
        "calculator",
        commands=["calc.exe", app_x_cmd],
    )
    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("os.name", "nt"), \
         patch("os.startfile", side_effect=[OSError("Failed to start calc.exe"), None]) as mock_start:
        res = open_app("calculator")
        assert res["app"] == "Calculator"
        assert res["target"] == app_x_cmd
        assert mock_start.call_count == 2


def test_open_app_packaged_fallback_failure_raises_dispatch_failed() -> None:
    app_x_cmd = r"shell:AppsFolder\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App"
    entry = AppEntry(
        "Notepad",
        "notepad.exe",
        "config",
        ["notepad", "메모장"],
        "notepad",
        commands=["notepad.exe", app_x_cmd],
    )
    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("os.name", "nt"), \
         patch("os.startfile", side_effect=[None, OSError("AppX package failed to launch")]) as mock_start, \
         patch("scripts.lcu.windows.list_windows", return_value=[]), \
         patch("time.sleep"):
        with pytest.raises(LCUError) as exc_info:
            open_app("notepad")
        assert exc_info.value.code == "dispatch_failed"
        assert mock_start.call_count == 2


def test_open_app_general_multi_command_no_window_verification() -> None:
    entry = AppEntry(
        "Outlook",
        "outlook.exe",
        "config",
        ["outlook", "아웃룩"],
        "outlook",
        commands=["outlook.exe", "olk.exe"],
    )
    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("os.name", "nt"), \
         patch("os.startfile") as mock_start, \
         patch("scripts.lcu.windows.list_windows") as mock_list, \
         patch("time.sleep") as mock_sleep:
        res = open_app("outlook")
        assert res["app"] == "Outlook"
        assert res["target"] == "outlook.exe"
        mock_start.assert_called_once_with("outlook.exe")
        mock_list.assert_not_called()
        mock_sleep.assert_not_called()


def test_open_app_general_multi_command_fallback_on_error() -> None:
    entry = AppEntry(
        "Teams",
        "ms-teams.exe",
        "config",
        ["teams", "팀즈"],
        "teams",
        commands=["ms-teams.exe", "msteams:"],
    )
    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("os.name", "nt"), \
         patch("os.startfile", side_effect=[OSError("Executable not found"), None]) as mock_start, \
         patch("scripts.lcu.windows.list_windows") as mock_list, \
         patch("time.sleep") as mock_sleep:
        res = open_app("teams")
        assert res["app"] == "Teams"
        assert res["target"] == "msteams:"
        assert mock_start.call_count == 2
        mock_start.assert_any_call("ms-teams.exe")
        mock_start.assert_any_call("msteams:")
        mock_list.assert_not_called()
        mock_sleep.assert_not_called()


def test_is_packaged_app_command() -> None:
    assert _is_packaged_app_command(r"shell:AppsFolder\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App") is True
    assert _is_packaged_app_command(r"shell:appsfolder\windows.immersivecontrolpanel_cw5n1h2txyewy!microsoft.windows.immersivecontrolpanel") is True
    assert _is_packaged_app_command("notepad.exe") is False
    assert _is_packaged_app_command("outlook.exe") is False
    assert _is_packaged_app_command("msteams:") is False
    assert _is_packaged_app_command("ms-settings:") is False


def test_build_app_index_cache_version_invalidation(tmp_path: Path) -> None:
    cache_file = tmp_path / "app-index.json"
    entry_dict = {
        "name": "CachedApp",
        "target": "cached.exe",
        "source": "config",
        "aliases": ["cached"],
        "normalized": "cachedapp",
        "commands": ["cached.exe"],
    }

    with patch("scripts.lcu.apps.get_cache_file_path", return_value=cache_file), \
         patch("scripts.lcu.apps.load_config_apps", return_value=[AppEntry.from_dict(entry_dict)]) as mock_load, \
         patch("scripts.lcu.apps.discover_start_menu_apps", return_value=[]), \
         patch("scripts.lcu.apps.discover_app_paths_apps", return_value=[]):

        # 1. Fresh cache with matching version
        cache_file.write_text(
            json.dumps({"version": APP_INDEX_CACHE_VERSION, "timestamp": time.time(), "apps": [entry_dict]}),
            encoding="utf-8",
        )
        res = build_app_index()
        assert len(res) == 1
        assert res[0].name == "CachedApp"
        mock_load.assert_not_called()

        # 2. Missing version key (legacy cache) -> triggers rebuild
        cache_file.write_text(
            json.dumps({"timestamp": time.time(), "apps": [entry_dict]}),
            encoding="utf-8",
        )
        res = build_app_index()
        assert len(res) == 1
        mock_load.assert_called_once()
        mock_load.reset_mock()

        # 3. Old version (version = 1) -> triggers rebuild
        cache_file.write_text(
            json.dumps({"version": 1, "timestamp": time.time(), "apps": [entry_dict]}),
            encoding="utf-8",
        )
        res = build_app_index()
        assert len(res) == 1
        mock_load.assert_called_once()
        mock_load.reset_mock()

        # 4. Verified newly written cache has version = APP_INDEX_CACHE_VERSION
        written = json.loads(cache_file.read_text(encoding="utf-8"))
        assert written.get("version") == APP_INDEX_CACHE_VERSION
        assert "commands" in written["apps"][0]


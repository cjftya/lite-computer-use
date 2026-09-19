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
    LaunchCandidate,
    _is_packaged_app_command,
    _wait_for_visible_app_window,
    build_app_index,
    classify_launch_method,
    find_app_entry,
    normalize_app_name,
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


# ============================================================================
# Phase 14 / Section 20 Unit Tests
# ============================================================================

def test_classify_launch_method() -> None:
    """20.1 App launch candidate 분류"""
    # shell:AppsFolder\... -> appsfolder
    assert classify_launch_method(r"shell:AppsFolder\Microsoft.Paint_8wekyb3d8bbwe!App") == "appsfolder"
    assert classify_launch_method(r"shell:appsfolder\windows.immersivecontrolpanel_cw5n1h2txyewy!app") == "appsfolder"

    # *.lnk -> start-menu
    assert classify_launch_method(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Visual Studio Code.lnk") == "start-menu"
    assert classify_launch_method("test.lnk") == "start-menu"

    # msteams:, ms-settings: -> uri
    assert classify_launch_method("msteams:") == "uri"
    assert classify_launch_method("ms-settings:") == "uri"
    assert classify_launch_method("https://example.com") == "uri"

    # *.exe -> app-paths or exe
    assert classify_launch_method("notepad.exe", source="config") == "exe"
    assert classify_launch_method("C:\\Program Files\\app.exe", source="app-paths") == "app-paths"
    assert classify_launch_method("code.cmd", source="config") == "exe"


def test_candidate_priority_appsfolder_first() -> None:
    """20.2 AppsFolder 우선: Paint candidate [AppsFolder, mspaint.exe]일 때 AppsFolder가 먼저 정렬되는지 확인"""
    appsfolder_cmd = r"shell:AppsFolder\Microsoft.Paint_8wekyb3d8bbwe!App"
    # Given commands with exe first, candidate sorting must put AppsFolder first
    entry = AppEntry(
        name="Paint",
        target="mspaint.exe",
        source="config",
        aliases=["paint", "그림판"],
        normalized="paint",
        commands=["mspaint.exe", appsfolder_cmd],
    )
    assert len(entry.candidates) == 2
    assert entry.candidates[0].method == "appsfolder"
    assert entry.candidates[0].target == appsfolder_cmd
    assert entry.candidates[1].method == "exe"
    assert entry.candidates[1].target == "mspaint.exe"


def test_open_app_appsfolder_success() -> None:
    """20.3 AppsFolder 성공: dispatch AppsFolder -> visible window 발견 -> exe candidate 실행 안 함, launch_method=appsfolder, hwnd 반환"""
    appsfolder_cmd = r"shell:AppsFolder\Microsoft.Paint_8wekyb3d8bbwe!App"
    entry = AppEntry(
        name="Paint",
        target=appsfolder_cmd,
        source="config",
        aliases=["paint", "그림판"],
        normalized="paint",
        commands=[appsfolder_cmd, "mspaint.exe"],
    )
    mock_win = {"hwnd": 3345694, "title": "Paint", "process": "mspaint.exe", "active": True}

    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("os.name", "nt"), \
         patch("os.startfile") as mock_start, \
         patch("scripts.lcu.windows.list_windows", side_effect=[[], [], [mock_win]]), \
         patch("scripts.lcu.windows.focus_window", return_value={"hwnd": 3345694, "title": "Paint"}) as mock_focus:
        res = open_app("paint")
        assert res["app"] == "Paint"
        assert res["target"] == appsfolder_cmd
        assert res["launch_method"] == "appsfolder"
        assert res["hwnd"] == 3345694
        assert res["title"] == "Paint"
        assert res["reused_existing"] is False
        mock_focus.assert_called_once_with(hwnd=3345694)
        # Only AppsFolder was dispatched, mspaint.exe was NOT executed
        mock_start.assert_called_once_with(appsfolder_cmd)


def test_open_app_appsfolder_fail_exe_fallback_success() -> None:
    """20.4 AppsFolder 실패 -> exe fallback: mock AppsFolder dispatch but no visible window -> exe -> visible window 발견. 두 candidate 각각 1회, exe 성공"""
    appsfolder_cmd = r"shell:AppsFolder\Microsoft.Paint_8wekyb3d8bbwe!App"
    entry = AppEntry(
        name="Paint",
        target=appsfolder_cmd,
        source="config",
        aliases=["paint", "그림판"],
        normalized="paint",
        commands=[appsfolder_cmd, "mspaint.exe"],
    )

    poll_count = 0
    def mock_list():
        nonlocal poll_count
        poll_count += 1
        # Initial checks (calls 1, 2) and Candidate 1 polling (calls 3 to 28): no window found
        # During exe candidate polling (call > 28): window appears
        if poll_count > 28:
            return [{"hwnd": 556677, "title": "Paint", "process": "mspaint.exe", "active": True}]
        return []

    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("os.name", "nt"), \
         patch("os.startfile") as mock_start, \
         patch("scripts.lcu.windows.list_windows", side_effect=mock_list), \
         patch("scripts.lcu.windows.focus_window", return_value={"hwnd": 556677, "title": "Paint"}) as mock_focus, \
         patch("time.sleep"):
        res = open_app("paint")
        assert res["app"] == "Paint"
        assert res["target"] == "mspaint.exe"
        assert res["launch_method"] == "exe"
        assert res["hwnd"] == 556677
        assert res["reused_existing"] is False
        mock_focus.assert_called_once_with(hwnd=556677)
        assert mock_start.call_count == 2
        mock_start.assert_any_call(appsfolder_cmd)
        mock_start.assert_any_call("mspaint.exe")


def test_open_app_all_candidates_fail() -> None:
    """20.5 모든 candidate 실패: dispatch_failed 반환, 동일 command 반복 없음"""
    appsfolder_cmd = r"shell:AppsFolder\Microsoft.Paint_8wekyb3d8bbwe!App"
    entry = AppEntry(
        name="Paint",
        target=appsfolder_cmd,
        source="config",
        aliases=["paint", "그림판"],
        normalized="paint",
        commands=[appsfolder_cmd, "mspaint.exe"],
    )

    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("os.name", "nt"), \
         patch("os.startfile") as mock_start, \
         patch("scripts.lcu.windows.list_windows", return_value=[]), \
         patch("time.sleep"):
        with pytest.raises(LCUError) as exc_info:
            open_app("paint")
        assert exc_info.value.code == "dispatch_failed"
        assert mock_start.call_count == 2
        assert exc_info.value.attempts is not None
        assert len(exc_info.value.attempts) == 2
        assert exc_info.value.attempts[0]["target"] == appsfolder_cmd
        assert exc_info.value.attempts[0]["result"] == "no_visible_window"
        assert exc_info.value.attempts[1]["target"] == "mspaint.exe"
        assert exc_info.value.attempts[1]["result"] == "no_visible_window"


def test_open_app_existing_minimized_window_reused() -> None:
    """20.6 기존 최소화 창: single match -> focus_window(hwnd), no launch candidate dispatch, reused_existing=True"""
    entry = AppEntry(
        name="Chrome",
        target="chrome.exe",
        source="config",
        aliases=["chrome", "google chrome", "크롬"],
        normalized="chrome",
        commands=["chrome.exe"],
    )
    existing_win = {
        "hwnd": 4852350,
        "title": "New Tab - Google Chrome",
        "process": "chrome.exe",
        "active": False,
        "minimized": True,
        "bounds": {"x": -32000, "y": -32000, "width": 160, "height": 30},
    }

    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("os.name", "nt"), \
         patch("os.startfile") as mock_start, \
         patch("scripts.lcu.windows.list_windows", return_value=[existing_win]), \
         patch("scripts.lcu.windows.focus_window", return_value={"hwnd": 4852350, "title": existing_win["title"]}) as mock_focus:
        res = open_app("chrome")
        assert res["app"] == "Chrome"
        assert res["hwnd"] == 4852350
        assert res["reused_existing"] is True
        assert res["launch_method"] == "existing-window"
        assert res["target"] is None
        mock_focus.assert_called_once_with(hwnd=4852350)
        mock_start.assert_not_called()


def test_open_app_multiple_existing_windows_no_arbitrary_focus() -> None:
    """20.7 기존 창 여러 개: 임의 HWND 선택 금지, launch candidate 실행"""
    entry = AppEntry(
        name="Chrome",
        target="chrome.exe",
        source="config",
        aliases=["chrome", "google chrome", "크롬"],
        normalized="chrome",
        commands=["chrome.exe"],
    )
    win1 = {"hwnd": 101, "title": "Chrome Window 1", "process": "chrome.exe", "active": False}
    win2 = {"hwnd": 102, "title": "Chrome Window 2", "process": "chrome.exe", "active": False}
    win3 = {"hwnd": 103, "title": "Chrome Window 3", "process": "chrome.exe", "active": True}

    call_count = 0
    def mock_list_wins():
        nonlocal call_count
        call_count += 1
        # Before launch: 2 windows
        if call_count <= 2:
            return [win1, win2]
        # After launch: 3rd window appears
        return [win1, win2, win3]

    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("os.name", "nt"), \
         patch("os.startfile") as mock_start, \
         patch("scripts.lcu.windows.focus_window", return_value={"hwnd": 103, "title": "Chrome Window 3"}) as mock_focus, \
         patch("scripts.lcu.windows.list_windows", side_effect=mock_list_wins):
        res = open_app("chrome")
        # Should not have called focus_window prior to launching, but calls focus_window after detecting win3 (hwnd 103)
        mock_start.assert_called_once_with("chrome.exe")
        mock_focus.assert_called_once_with(hwnd=103)
        assert res["hwnd"] == 103
        assert res["reused_existing"] is False
        assert res["launch_method"] == "exe"


def test_open_app_response_fields() -> None:
    """20.8 open_app response 필수 필드: app, target, launch_method, hwnd, title, reused_existing"""
    entry = AppEntry("Notepad", "notepad.exe", "config", ["notepad"], "notepad")
    mock_win = {"hwnd": 1234, "title": "Untitled - Notepad", "process": "notepad.exe", "active": True}

    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("os.name", "nt"), \
         patch("os.startfile"), \
         patch("scripts.lcu.windows.list_windows", return_value=[mock_win]), \
         patch("scripts.lcu.windows.focus_window", return_value={"hwnd": 1234, "title": "Untitled - Notepad"}):
        res = open_app("notepad")
        assert "app" in res
        assert "target" in res
        assert "launch_method" in res
        assert "hwnd" in res
        assert "title" in res
        assert "reused_existing" in res


def test_wait_for_visible_app_window_early_exit() -> None:
    entry = AppEntry("TestApp", "test.exe", "config", [], "testapp")
    # Immediate find on check 1
    with patch("os.name", "nt"), \
         patch("scripts.lcu.windows.list_windows", return_value=[{"title": "TestApp", "process": "test.exe"}]), \
         patch("time.sleep") as mock_sleep:
        found = _wait_for_visible_app_window(entry, timeout=1.2, interval=0.1)
        assert found is True
        mock_sleep.assert_not_called()

    # Find on check 2
    with patch("os.name", "nt"), \
         patch("scripts.lcu.windows.list_windows", side_effect=[[], [{"title": "TestApp", "process": "test.exe"}]]), \
         patch("time.sleep") as mock_sleep:
        found = _wait_for_visible_app_window(entry, timeout=1.2, interval=0.1)
        assert found is True
        assert mock_sleep.call_count == 1


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

        # 3. Old version (version = 1 or 2) -> triggers rebuild
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


# ============================================================================
# Hardening C — App Index Alias Merge Tests (C1 - C4)
# ============================================================================

def test_alias_merge_vscode_start_menu() -> None:
    """Test C1: VS Code config entry + Start Menu entry alias merge into one entry with .lnk candidate"""
    config_entry = AppEntry(
        name="vscode",
        target="code.exe",
        source="config",
        aliases=["vscode", "visual studio code", "vs code"],
        normalized="vscode",
        commands=["code.exe", "code.cmd"],
    )
    start_menu_entry = AppEntry(
        name="Visual Studio Code",
        target=r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Visual Studio Code.lnk",
        source="start-menu",
        aliases=["Visual Studio Code"],
        normalized="visualstudiocode",
    )

    with patch("scripts.lcu.apps.get_cache_file_path", return_value=Path(tempfile.gettempdir()) / "nonexistent_cache.json"), \
         patch("scripts.lcu.apps.load_config_apps", return_value=[config_entry]), \
         patch("scripts.lcu.apps.discover_start_menu_apps", return_value=[start_menu_entry]), \
         patch("scripts.lcu.apps.discover_app_paths_apps", return_value=[]):
        index = build_app_index(force_refresh=True)

    assert len(index) == 1
    merged = index[0]
    assert merged.name == "vscode"
    assert "visualstudiocode" in [normalize_app_name(a) for a in merged.aliases]
    # Candidate priority: start-menu (.lnk) priority 2 comes before exe priority 5
    assert merged.candidates[0].method == "start-menu"
    assert merged.candidates[0].target == start_menu_entry.target


def test_alias_merge_chrome_start_menu() -> None:
    """Test C2: Chrome config alias 'google chrome' merges with Start Menu 'Google Chrome'"""
    config_entry = AppEntry(
        name="chrome",
        target="chrome.exe",
        source="config",
        aliases=["chrome", "google chrome"],
        normalized="chrome",
        commands=["chrome.exe"],
    )
    start_menu_entry = AppEntry(
        name="Google Chrome",
        target=r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Google Chrome.lnk",
        source="start-menu",
        aliases=["Google Chrome"],
        normalized="googlechrome",
    )

    with patch("scripts.lcu.apps.get_cache_file_path", return_value=Path(tempfile.gettempdir()) / "nonexistent_cache.json"), \
         patch("scripts.lcu.apps.load_config_apps", return_value=[config_entry]), \
         patch("scripts.lcu.apps.discover_start_menu_apps", return_value=[start_menu_entry]), \
         patch("scripts.lcu.apps.discover_app_paths_apps", return_value=[]):
        index = build_app_index(force_refresh=True)

    assert len(index) == 1
    assert index[0].name == "chrome"
    assert index[0].candidates[0].method == "start-menu"


def test_alias_merge_unrelated_apps_remain_distinct() -> None:
    """Test C3: Unrelated apps without exact alias match do NOT merge"""
    entry1 = AppEntry(
        name="vscode",
        target="code.exe",
        source="config",
        aliases=["vscode", "visual studio code"],
        normalized="vscode",
    )
    entry2 = AppEntry(
        name="Code Writer",
        target=r"C:\Program Files\CodeWriter\writer.exe",
        source="start-menu",
        aliases=["Code Writer"],
        normalized="codewriter",
    )

    with patch("scripts.lcu.apps.get_cache_file_path", return_value=Path(tempfile.gettempdir()) / "nonexistent_cache.json"), \
         patch("scripts.lcu.apps.load_config_apps", return_value=[entry1]), \
         patch("scripts.lcu.apps.discover_start_menu_apps", return_value=[entry2]), \
         patch("scripts.lcu.apps.discover_app_paths_apps", return_value=[]):
        index = build_app_index(force_refresh=True)

    assert len(index) == 2
    names = {e.name for e in index}
    assert names == {"vscode", "Code Writer"}


def test_alias_merge_prevents_ambiguity_regression() -> None:
    """Test C4: Query 'visual studio code' against merged index returns single entry without ambiguous_target"""
    config_entry = AppEntry(
        name="vscode",
        target="code.exe",
        source="config",
        aliases=["vscode", "visual studio code", "vs code"],
        normalized="vscode",
    )
    start_menu_entry = AppEntry(
        name="Visual Studio Code",
        target=r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Visual Studio Code.lnk",
        source="start-menu",
        aliases=["Visual Studio Code"],
        normalized="visualstudiocode",
    )

    with patch("scripts.lcu.apps.get_cache_file_path", return_value=Path(tempfile.gettempdir()) / "nonexistent_cache.json"), \
         patch("scripts.lcu.apps.load_config_apps", return_value=[config_entry]), \
         patch("scripts.lcu.apps.discover_start_menu_apps", return_value=[start_menu_entry]), \
         patch("scripts.lcu.apps.discover_app_paths_apps", return_value=[]):
        index = build_app_index(force_refresh=True)

    entry, candidates = find_app_entry("visual studio code", index)
    assert entry is not None
    assert entry.name == "vscode"
    assert candidates == []


# ============================================================================
# Hardening D — Foreground Focus Tests (D1 - D3)
# ============================================================================

def test_open_app_new_window_focus_success() -> None:
    """Test D1: 새 창 visible + focus 성공 -> focus_window(hwnd) 호출 및 open_app success"""
    entry = AppEntry(
        name="Paint",
        target="mspaint.exe",
        source="config",
        aliases=["paint"],
        normalized="paint",
        commands=["mspaint.exe"],
    )
    mock_win = {"hwnd": 888111, "title": "Paint", "process": "mspaint.exe", "active": True}

    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("os.name", "nt"), \
         patch("os.startfile"), \
         patch("scripts.lcu.windows.list_windows", side_effect=[[], [], [mock_win]]), \
         patch("scripts.lcu.windows.focus_window", return_value={"hwnd": 888111, "title": "Paint"}) as mock_focus:
        res = open_app("paint")
        assert res["hwnd"] == 888111
        assert res["reused_existing"] is False
        mock_focus.assert_called_once_with(hwnd=888111)


def test_open_app_new_window_focus_failure_aborts_without_extra_candidates() -> None:
    """Test D2: 새 창 visible + focus 실패 -> 성공 반환 금지, 추가 candidate 실행 금지, window_focus_failed 반환"""
    entry = AppEntry(
        name="MultiCandidateApp",
        target="primary.exe",
        source="config",
        aliases=["multiapp"],
        normalized="multicandidateapp",
        commands=["primary.exe", "secondary.exe"],
    )
    mock_win = {"hwnd": 888222, "title": "App", "process": "primary.exe", "active": True}

    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("os.name", "nt"), \
         patch("os.startfile") as mock_start, \
         patch("scripts.lcu.windows.list_windows", side_effect=[[], [], [mock_win]]), \
         patch("scripts.lcu.windows.focus_window", side_effect=LCUError("window_focus_failed", "Cannot focus window")):
        with pytest.raises(LCUError) as exc_info:
            open_app("multiapp")
        assert exc_info.value.code == "window_focus_failed"
        assert "failed to focus" in exc_info.value.message
        # Crucial check: only primary.exe was started, secondary.exe was NOT started
        mock_start.assert_called_once_with("primary.exe")


def test_open_app_single_existing_window_reused_d3() -> None:
    """Test D3: 기존 단일 창 존재 -> focus_window -> reused_existing=True 유지"""
    entry = AppEntry(
        name="Chrome",
        target="chrome.exe",
        source="config",
        aliases=["chrome"],
        normalized="chrome",
        commands=["chrome.exe"],
    )
    existing_win = {"hwnd": 888333, "title": "Google Chrome", "process": "chrome.exe", "active": False}

    with patch("scripts.lcu.apps.build_app_index", return_value=[entry]), \
         patch("os.name", "nt"), \
         patch("os.startfile") as mock_start, \
         patch("scripts.lcu.windows.list_windows", return_value=[existing_win]), \
         patch("scripts.lcu.windows.focus_window", return_value={"hwnd": 888333, "title": "Google Chrome"}) as mock_focus:
        res = open_app("chrome")
        assert res["hwnd"] == 888333
        assert res["reused_existing"] is True
        assert res["launch_method"] == "existing-window"
        mock_focus.assert_called_once_with(hwnd=888333)
        mock_start.assert_not_called()


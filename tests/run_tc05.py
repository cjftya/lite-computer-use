from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Ensure project scripts are on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lcu import apps, batch, capture, direct, windows
from lcu.capture import capture_screenshot
from lcu.windows import click, close_window, focus_window, get_clipboard, list_windows, set_window_bounds, type_text, press_key, hotkey
from lcu.batch import execute_batch

STATUS_FILE = Path(tempfile.gettempdir()) / "LiteComputerUse" / "search_tab_status.json"
DESKTOP_DIR = Path.home() / "Desktop"
RESULT_FILE = DESKTOP_DIR / "search-result.txt"
EXPECTED_TITLE = "OpenAI ChatGPT Overview & Capabilities"


def read_status() -> dict:
    if not STATUS_FILE.exists():
        return {}
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def run_tc05() -> dict:
    print("=== Starting TC-05: Web Search + New Tab + Information Copy ===")
    capture.init_windows_environment()

    # 1. Ensure clean initial state
    if RESULT_FILE.exists():
        RESULT_FILE.unlink()
    if STATUS_FILE.exists():
        STATUS_FILE.unlink()

    # 2. Spawn Browser fixture
    fixture_script = Path(__file__).resolve().parent / "browser_search_fixture.py"
    proc = subprocess.Popen([sys.executable, str(fixture_script)])
    print(f"Launched Browser Search fixture (PID: {proc.pid}) from {fixture_script}")

    browser_hwnd = None
    notepad_hwnd = None

    try:
        # Wait for Browser window
        win = None
        for i in range(40):
            time.sleep(0.2)
            if proc.poll() is not None:
                out, err = proc.communicate()
                raise RuntimeError(f"Fixture died with returncode {proc.returncode}!\nStdout: {out}\nStderr: {err}")
            wins = list_windows()
            matches = [w for w in wins if "LCU Browser - Search & Multi-Tab" in w["title"]]
            if matches:
                win = matches[0]
                break

        if not win:
            raise RuntimeError("LCU Browser - Search & Multi-Tab window did not appear")

        browser_hwnd = win["hwnd"]
        print(f"Found Browser window (hwnd: {browser_hwnd})")

        # Set bounds and focus
        set_window_bounds(x=200, y=100, width=700, height=520, hwnd=browser_hwnd)
        focus_window(hwnd=browser_hwnd)
        time.sleep(0.3)

        # Observation Boundary 1: Initial Search Portal
        snap1 = capture_screenshot(target="active-window", quality="normal")
        cid1 = snap1["captureId"]
        print(f"[Observation Boundary 1] Captured Search Portal: {snap1['width']}x{snap1['height']}, id={cid1}")

        # Batch 1: Search Entry & Submit
        # Search Entry is in search_bar (top of tab)
        # In 700x520 window:
        # Tab bar is ~30px, search bar starts at ~40, entry is at x ≈ 300, y ≈ 85
        actions_search = [
            {"action": "click", "x": 300, "y": 85, "capture_id": cid1, "delay_after": 0.1},
            {"action": "type_text", "text": "OpenAI ChatGPT", "delay_after": 0.1},
            {"action": "press_key", "key": "ENTER", "delay_after": 0.8},
        ]
        print("Executing Batch 1 (Type Query & Search)...")
        execute_batch(actions_search)

        # Observation Boundary 2: Search Results Page
        time.sleep(0.4)
        snap2 = capture_screenshot(target="active-window", quality="normal")
        cid2 = snap2["captureId"]
        print(f"[Observation Boundary 2] Captured Search Results: {snap2['width']}x{snap2['height']}, id={cid2}")

        status = read_status()
        assert status.get("search_executed") is True, "Search was not recorded in status"
        assert status.get("search_query") == "OpenAI ChatGPT", f"Wrong search query: {status.get('search_query')}"

        # Center x = 151, y = 293
        actions_new_tab = [
            {"action": "click", "x": 151, "y": 293, "capture_id": cid2, "delay_after": 0.8},
        ]
        print("Executing Batch 2 (Open in New Tab)...")
        execute_batch(actions_new_tab)

        # Observation Boundary 3: New Tab Destination Page
        time.sleep(0.4)
        snap3 = capture_screenshot(target="active-window", quality="normal")
        cid3 = snap3["captureId"]
        print(f"[Observation Boundary 3] Captured New Tab Page: {snap3['width']}x{snap3['height']}, id={cid3}")

        status = read_status()
        assert status.get("new_tab_opened") is True, "New tab was not opened according to status"

        # Batch 3: Click "📋 제목 복사 (Copy Title to Clipboard)" button
        # Center x = 190, y = 259
        actions_copy = [
            {"action": "click", "x": 190, "y": 259, "capture_id": cid3, "delay_after": 0.5},
        ]
        print("Executing Batch 3 (Copy Title to Clipboard)...")
        execute_batch(actions_copy)

        # Verify Clipboard text
        clip = get_clipboard()["text"]
        print(f"Clipboard content: '{clip}'")
        assert clip == EXPECTED_TITLE, f"Clipboard mismatch: expected '{EXPECTED_TITLE}', got '{clip}'"

        # Step 4: Open Notepad, paste result, and save to Desktop
        apps.open_app("notepad")
        time.sleep(1.0)

        for _ in range(30):
            time.sleep(0.2)
            np_wins = [w for w in list_windows() if "Notepad" in w["title"] or "메모장" in w["title"]]
            if np_wins:
                notepad_hwnd = np_wins[0]["hwnd"]
                break

        assert notepad_hwnd is not None, "Notepad failed to open"
        set_window_bounds(x=250, y=150, width=650, height=450, hwnd=notepad_hwnd)
        focus_window(hwnd=notepad_hwnd)
        time.sleep(0.3)

        # Batch 4: Type prefix, paste clipboard, and trigger Ctrl+S
        actions_notepad_save = [
            {"action": "type_text", "text": "검색 결과 제목: ", "delay_after": 0.1},
            {"action": "hotkey", "keys": ["CTRL", "V"], "delay_after": 0.2},
            {"action": "hotkey", "keys": ["CTRL", "S"], "delay_after": 0.8},
        ]
        print("Executing Batch 4 (Type + Paste + Ctrl+S)...")
        execute_batch(actions_notepad_save)

        # Observation Boundary 4: Wait for Save As dialog if new file, or type path
        # In Windows 11 Notepad, Ctrl+S on untitled opens Save As dialog
        time.sleep(0.5)
        # Type the target file path and press Enter
        actions_save_path = [
            {"action": "type_text", "text": str(RESULT_FILE), "delay_after": 0.2},
            {"action": "press_key", "key": "ENTER", "delay_after": 0.8},
        ]
        print("Executing Save Path...")
        execute_batch(actions_save_path)

        # Verify file exists on Desktop
        assert RESULT_FILE.exists(), f"Result file was not saved at {RESULT_FILE}"
        print(f"Verified file saved on Desktop: {RESULT_FILE} ({RESULT_FILE.stat().st_size} bytes)")

        # Close Notepad
        close_window(hwnd=notepad_hwnd)
        notepad_hwnd = None
        time.sleep(0.5)

        # Step 5: Reopen saved file and verify content
        apps.open_app("notepad")
        time.sleep(1.0)
        for _ in range(30):
            time.sleep(0.2)
            np_wins = [w for w in list_windows() if "Notepad" in w["title"] or "메모장" in w["title"]]
            if np_wins:
                notepad_hwnd = np_wins[0]["hwnd"]
                break

        assert notepad_hwnd is not None, "Notepad failed to reopen"
        set_window_bounds(x=250, y=150, width=650, height=450, hwnd=notepad_hwnd)
        focus_window(hwnd=notepad_hwnd)
        time.sleep(0.3)

        # Batch 5: Ctrl+O, type path, Enter
        actions_reopen = [
            {"action": "hotkey", "keys": ["CTRL", "O"], "delay_after": 0.8},
            {"action": "type_text", "text": str(RESULT_FILE), "delay_after": 0.2},
            {"action": "press_key", "key": "ENTER", "delay_after": 0.6},
        ]
        print("Executing Batch 5 (Reopen file in Notepad)...")
        execute_batch(actions_reopen)

        # Observation Boundary 5: Visual Verification of Final Document
        time.sleep(0.5)
        focus_window(hwnd=notepad_hwnd)
        snap5 = capture_screenshot(target="active-window", quality="normal")
        cid5 = snap5["captureId"]
        print(f"[Observation Boundary 5] Captured Final Notepad State: {snap5['width']}x{snap5['height']}, id={cid5}")

        # Verify physical file text
        file_content = RESULT_FILE.read_text(encoding="utf-8")
        assert f"검색 결과 제목: {EXPECTED_TITLE}" in file_content, f"Unexpected content in file: '{file_content}'"
        print(f"File text verified: '검색 결과 제목: {EXPECTED_TITLE}'")

        # Cleanup
        close_window(hwnd=notepad_hwnd)
        notepad_hwnd = None
        close_window(hwnd=browser_hwnd)
        browser_hwnd = None

        RESULT_FILE.unlink()
        assert not RESULT_FILE.exists(), "Result file failed to delete"
        print("Desktop file cleaned up.")

        matches = direct.find_path("search-result.txt", str(DESKTOP_DIR))
        assert matches["count"] == 0, f"search-result.txt still on Desktop: {matches}"
        print("Verified Desktop is completely clean.")

        print("\nALL ASSERTIONS PASSED! TC-05 SUCCESSFUL.")
        return {
            "result": "PASS",
            "screenshots": [cid1, cid2, cid3, cid5],
            "clipboard": clip,
        }

    finally:
        if notepad_hwnd:
            try:
                close_window(hwnd=notepad_hwnd)
            except Exception:
                pass
        if browser_hwnd:
            try:
                close_window(hwnd=browser_hwnd)
            except Exception:
                pass
        if proc.poll() is None:
            proc.terminate()
        if RESULT_FILE.exists():
            try:
                RESULT_FILE.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    res = run_tc05()
    print("\nResult:", res["result"])

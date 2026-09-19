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

from lcu import apps, batch, capture, direct, errors, windows
from lcu.capture import capture_screenshot
from lcu.windows import click, close_window, focus_window, list_windows, set_window_bounds, type_text, press_key
from lcu.batch import execute_batch

STATUS_FILE = Path(tempfile.gettempdir()) / "LiteComputerUse" / "download_status.json"
DOWNLOADS_DIR = Path.home() / "Downloads"
DOWNLOADED_FILE = DOWNLOADS_DIR / "sample-report.txt"


def read_status() -> dict:
    if not STATUS_FILE.exists():
        return {}
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def run_tc08() -> dict:
    print("=== Starting TC-08: Web Download End-to-End Flow ===")
    capture.init_windows_environment()

    # 1. Ensure clean initial state
    if DOWNLOADED_FILE.exists():
        DOWNLOADED_FILE.unlink()
    if STATUS_FILE.exists():
        STATUS_FILE.unlink()

    # 2. Spawn download fixture
    fixture_script = Path(__file__).resolve().parent / "download_gui_fixture.py"
    proc = subprocess.Popen([sys.executable, str(fixture_script)])
    print(f"Launched Download GUI fixture (PID: {proc.pid}) from {fixture_script}")

    notepad_hwnd = None
    browser_hwnd = None

    try:
        # Wait for window
        win = None
        for i in range(40):
            time.sleep(0.2)
            if proc.poll() is not None:
                out, err = proc.communicate()
                raise RuntimeError(f"Fixture died with returncode {proc.returncode}!\nStdout: {out}\nStderr: {err}")
            wins = list_windows()
            matches = [w for w in wins if "LCU Browser - Web Download" in w["title"]]
            if matches:
                win = matches[0]
                break

        if not win:
            raise RuntimeError("LCU Browser - Web Download window did not appear")

        browser_hwnd = win["hwnd"]
        print(f"Found Browser window (hwnd: {browser_hwnd})")

        # Set bounds and focus
        set_window_bounds(x=200, y=100, width=650, height=500, hwnd=browser_hwnd)
        focus_window(hwnd=browser_hwnd)
        time.sleep(0.3)

        # Observation Boundary 1: Initial Download Page
        snap1 = capture_screenshot(target="active-window", quality="normal")
        cid1 = snap1["captureId"]
        print(f"[Observation Boundary 1] Captured Download Page: {snap1['width']}x{snap1['height']}, id={cid1}")

        # Batch 1: Click Download Button
        # Button is centered horizontally in content frame
        # Content frame is at x=20..630, title at ~70, desc at ~120, button at ~190..240
        # Center x = 324, y = 262
        actions_dl = [
            {"action": "click", "x": 324, "y": 262, "capture_id": cid1, "delay_after": 0.8},
        ]
        print("Executing Batch 1 (Click Download)...")
        execute_batch(actions_dl)
        print("Batch 1 executed.")

        # Observation Boundary 2: Download Completion & Downloads Flyout Panel
        time.sleep(0.5)
        snap2 = capture_screenshot(target="active-window", quality="normal")
        cid2 = snap2["captureId"]
        print(f"[Observation Boundary 2] Captured Download Complete: {snap2['width']}x{snap2['height']}, id={cid2}")

        # Verify download state & physical file existence
        status = read_status()
        print("Download status:", status)
        assert status.get("download_finished") is True, "Download did not finish in status"
        assert DOWNLOADED_FILE.exists(), f"Downloaded file not found at {DOWNLOADED_FILE}"
        file_size = DOWNLOADED_FILE.stat().st_size
        print(f"Verified physical file created: {DOWNLOADED_FILE} ({file_size} bytes)")

        # Batch 2: Open downloaded file in Notepad via the Downloads Flyout "파일 열기" button
        # dl_panel is at x=350, y=45, width=280, height=180
        # Inside dl_panel: btn_open is in btn_row (y ≈ 180-40=140 relative to panel, so y ≈ 185 overall)
        # x ≈ 350 + 10 + 75 + 30 ≈ 465
        actions_open = [
            {"action": "click", "x": 477, "y": 194, "capture_id": cid2, "delay_after": 1.5},
        ]
        print("Executing Batch 2 (Click Open File in Downloads UI)...")
        execute_batch(actions_open)
        print("Batch 2 executed.")

        # Wait for Notepad window to appear
        for _ in range(30):
            time.sleep(0.2)
            np_wins = [w for w in list_windows() if "Notepad" in w["title"] or "메모장" in w["title"]]
            if np_wins:
                notepad_hwnd = np_wins[0]["hwnd"]
                break

        assert notepad_hwnd is not None, "Notepad failed to open"
        print(f"Notepad opened (hwnd: {notepad_hwnd})")

        # Focus Notepad and open the downloaded file
        focus_window(hwnd=notepad_hwnd)
        set_window_bounds(x=250, y=150, width=650, height=450, hwnd=notepad_hwnd)
        time.sleep(0.3)

        # Batch 3: Hotkey Ctrl+O to open file dialog, enter file path, and press Enter
        print("Executing Batch 3 (Open file in Notepad via Ctrl+O)...")
        actions_load_file = [
            {"action": "hotkey", "keys": ["CTRL", "O"], "delay_after": 0.8},
            {"action": "type_text", "text": str(DOWNLOADED_FILE), "delay_after": 0.2},
            {"action": "press_key", "key": "ENTER", "delay_after": 0.6},
        ]
        execute_batch(actions_load_file)

        # Observation Boundary 3: Visual Verification of Downloaded Content in Editor
        time.sleep(0.5)
        focus_window(hwnd=notepad_hwnd)
        snap3 = capture_screenshot(target="active-window", quality="normal")
        cid3 = snap3["captureId"]
        print(f"[Observation Boundary 3] Captured Notepad content: {snap3['width']}x{snap3['height']}, id={cid3}")

        # Verify content from file directly as well
        content = DOWNLOADED_FILE.read_text(encoding="utf-8")
        assert "LCU Download Verification Successful - 2026" in content, f"Unexpected content: {content}"
        print("Content verified: 'LCU Download Verification Successful - 2026'")

        # Close Notepad
        close_window(hwnd=notepad_hwnd)
        notepad_hwnd = None
        time.sleep(0.3)

        # Cleanup: Delete downloaded file
        DOWNLOADED_FILE.unlink()
        assert not DOWNLOADED_FILE.exists(), "Downloaded file failed to delete"
        print(f"Cleaned up {DOWNLOADED_FILE}")

        # Verify deletion via find_path
        matches = direct.find_path("sample-report.txt", str(DOWNLOADS_DIR))
        assert matches["count"] == 0, f"sample-report.txt still found in Downloads directory: {matches}"
        print("Verified Downloads folder is clean.")

        print("\nALL ASSERTIONS PASSED! TC-08 SUCCESSFUL.")
        return {
            "result": "PASS",
            "screenshots": [cid1, cid2, cid3],
            "status": status,
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
        if DOWNLOADED_FILE.exists():
            try:
                DOWNLOADED_FILE.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    res = run_tc08()
    print("\nResult:", res["result"])

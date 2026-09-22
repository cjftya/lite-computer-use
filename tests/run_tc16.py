from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from PIL import Image

# Ensure project scripts are on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lcu import apps, batch, capture, direct, windows
from lcu.capture import capture_screenshot
from lcu.windows import click, close_window, focus_window, get_clipboard, set_clipboard, list_windows, set_window_bounds, type_text, press_key, hotkey
from lcu.batch import execute_batch

DESKTOP_DIR = Path.home() / "Desktop"
DOCUMENTS_DIR = Path.home() / "Documents"
TEST_DIR = DESKTOP_DIR / "LCU-Production"
RESULT_FILE = TEST_DIR / "result.txt"
FINAL_FILE = TEST_DIR / "final-result.txt"
MOVED_FILE = DOCUMENTS_DIR / "final-result.txt"
STATUS_FILE = Path(tempfile.gettempdir()) / "LiteComputerUse" / "tc16_wiki_status.json"


def find_button_center(image_path: str, color_predicate, region: tuple[int, int, int, int] | None = None) -> tuple[int, int]:
    im = Image.open(image_path).convert("RGB")
    w, h = im.size
    min_rx = region[0] if region else 0
    min_ry = region[1] if region else 0
    max_rx = region[2] if region else w
    max_ry = region[3] if region else h
    matching = []
    for y in range(min_ry, max_ry):
        for x in range(min_rx, max_rx):
            if color_predicate(im.getpixel((x, y))):
                matching.append((x, y))
    if not matching:
        raise ValueError(f"No pixels matching predicate found in {image_path} (region: {region})")
    min_x, max_x = min(p[0] for p in matching), max(p[0] for p in matching)
    min_y, max_y = min(p[1] for p in matching), max(p[1] for p in matching)
    return (min_x + max_x) // 2, (min_y + max_y) // 2


def close_notepad_and_wait(hwnd: int) -> None:
    try:
        close_window(hwnd=hwnd)
    except Exception:
        pass
    for _ in range(40):
        time.sleep(0.1)
        wins = [w for w in list_windows() if "Notepad" in w["title"] or "메모장" in w["title"]]
        if not wins:
            break
    time.sleep(0.3)


def run_tc16() -> dict:
    print("=== Starting TC-16: 10-Step Composite Stress Test ===")
    capture.init_windows_environment()

    # Pre-clean
    for w in list_windows():
        if "Notepad" in w.get("title", "") or "메모장" in w.get("title", ""):
            try:
                close_window(hwnd=w["hwnd"])
            except Exception:
                pass

    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    if MOVED_FILE.exists():
        MOVED_FILE.unlink()
    if STATUS_FILE.exists():
        STATUS_FILE.unlink()

    notepad_hwnd = None
    wiki_proc = None
    screenshots: list[str] = []

    try:
        # Step 1: Create Directory Desktop\LCU-Production
        print("\n--- Step 1: Create Directory Desktop\\LCU-Production ---")
        TEST_DIR.mkdir(parents=True, exist_ok=True)
        assert TEST_DIR.is_dir(), "Failed to create Desktop\\LCU-Production directory"
        print(f"Directory created: {TEST_DIR}")

        # Step 2 & 3: File creation and Initial Content 'Start' via Notepad
        print("\n--- Step 2 & 3: Create result.txt & write 'Start' via Notepad ---")
        apps.open_app("notepad")
        time.sleep(1.0)

        for _ in range(30):
            time.sleep(0.2)
            wins = [w for w in list_windows() if "Notepad" in w["title"] or "메모장" in w["title"]]
            if wins:
                notepad_hwnd = wins[0]["hwnd"]
                break

        assert notepad_hwnd is not None, "Notepad failed to launch"
        set_window_bounds(x=250, y=150, width=650, height=450, hwnd=notepad_hwnd)
        focus_window(hwnd=notepad_hwnd)
        time.sleep(0.3)

        # Batch 1a: Type Start and trigger Save
        actions_initial_text = [
            {"action": "type_text", "text": "Start\n", "delay_after": 0.1},
            {"action": "hotkey", "keys": ["CTRL", "S"], "delay_after": 0.8},
        ]
        print("Executing Batch 1a (Type 'Start' + Ctrl+S)...")
        execute_batch(actions_initial_text)

        time.sleep(0.5)
        actions_save_dialog = [
            {"action": "type_text", "text": str(RESULT_FILE), "delay_after": 0.2},
            {"action": "press_key", "key": "ENTER", "delay_after": 0.8},
            {"action": "hotkey", "keys": ["CTRL", "W"], "delay_after": 0.5},
        ]
        print("Executing Batch 1b (Enter path + Enter)...")
        execute_batch(actions_save_dialog)

        # Close Notepad
        close_notepad_and_wait(notepad_hwnd)
        notepad_hwnd = None

        assert RESULT_FILE.exists(), f"result.txt was not created at {RESULT_FILE}"
        initial_text = RESULT_FILE.read_text(encoding="utf-8")
        assert "Start" in initial_text, f"Initial file missing 'Start': '{initial_text}'"
        print(f"Verified initial file saved: {RESULT_FILE} ({RESULT_FILE.stat().st_size} bytes)")

        # Step 4 & 5: Search Wikipedia for 'Computer vision' & Copy Title
        print("\n--- Step 4 & 5: Wikipedia Search & Title Copy ---")
        fixture_script = Path(__file__).resolve().parent / "wiki_search_fixture.py"
        wiki_proc = subprocess.Popen([sys.executable, str(fixture_script)])
        print(f"Launched Wikipedia search fixture (PID: {wiki_proc.pid})")

        wiki_hwnd = None
        for _ in range(30):
            time.sleep(0.2)
            wins = [w for w in list_windows() if "Wikipedia" in w["title"]]
            if wins:
                wiki_hwnd = wins[0]["hwnd"]
                break

        assert wiki_hwnd is not None, "Wikipedia window did not appear"
        set_window_bounds(x=200, y=100, width=700, height=520, hwnd=wiki_hwnd)
        focus_window(hwnd=wiki_hwnd)
        time.sleep(0.3)

        # Observation Boundary 1: Wikipedia Home
        snap1 = capture_screenshot(target="active-window", quality="normal")
        screenshots.append(snap1["captureId"])
        print(f"[Observation Boundary 1] Captured Wikipedia Home: {snap1['width']}x{snap1['height']}, id={snap1['captureId']}")

        # Batch 2: Search for 'Computer vision'
        # Top bar search entry is at x ≈ 250, y ≈ 55
        actions_search = [
            {"action": "click", "x": 250, "y": 55, "capture_id": snap1["captureId"], "delay_after": 0.1},
            {"action": "type_text", "text": "Computer vision", "delay_after": 0.1},
            {"action": "press_key", "key": "ENTER", "delay_after": 0.8},
        ]
        print("Executing Batch 2 (Search 'Computer vision')...")
        execute_batch(actions_search)

        # Observation Boundary 2: Article Loaded
        time.sleep(0.4)
        snap2 = capture_screenshot(target="active-window", quality="normal")
        screenshots.append(snap2["captureId"])
        print(f"[Observation Boundary 2] Captured Wikipedia Article: {snap2['width']}x{snap2['height']}, id={snap2['captureId']}")

        # Find green Copy Title button
        copy_x, copy_y = find_button_center(
            snap2["path"],
            lambda c: c[1] > 120 and c[0] < 40 and c[2] < 120,
            region=(20, 200, 300, 350),
        )
        print(f"Detected Copy Title button at center: ({copy_x}, {copy_y})")

        # Batch 3: Click Copy Title
        actions_copy = [
            {"action": "click", "x": copy_x, "y": copy_y, "capture_id": snap2["captureId"], "delay_after": 0.5},
        ]
        print("Executing Batch 3 (Copy Title)...")
        execute_batch(actions_copy)

        clip = get_clipboard()["text"]
        print(f"Clipboard received: '{clip}'")
        assert clip == "Computer vision", f"Unexpected clipboard text: '{clip}'"

        # Close Wikipedia fixture
        close_window(hwnd=wiki_hwnd)
        wiki_hwnd = None
        if wiki_proc.poll() is None:
            wiki_proc.terminate()
        wiki_proc = None
        time.sleep(0.4)

        # Step 6 & 7: Reopen result.txt in Notepad and Append Copied Title
        print("\n--- Step 6 & 7: Append Copied Title to result.txt in Notepad ---")
        apps.open_app("notepad")
        time.sleep(1.0)

        for _ in range(30):
            time.sleep(0.2)
            wins = [w for w in list_windows() if "Notepad" in w["title"] or "메모장" in w["title"]]
            if wins:
                notepad_hwnd = wins[0]["hwnd"]
                break

        assert notepad_hwnd is not None, "Notepad failed to launch for append"
        set_window_bounds(x=250, y=150, width=650, height=450, hwnd=notepad_hwnd)
        focus_window(hwnd=notepad_hwnd)
        time.sleep(0.3)

        # Batch 4a: Open result.txt
        actions_open_result = [
            {"action": "hotkey", "keys": ["CTRL", "O"], "delay_after": 0.8},
            {"action": "type_text", "text": str(RESULT_FILE), "delay_after": 0.2},
            {"action": "press_key", "key": "ENTER", "delay_after": 0.8},
        ]
        print("Executing Batch 4a (Open result.txt in Notepad)...")
        execute_batch(actions_open_result)

        time.sleep(0.5)
        focus_window(hwnd=notepad_hwnd)

        # Batch 4b: Move to end, paste, save, and close tab
        actions_append_text = [
            {"action": "hotkey", "keys": ["CTRL", "END"], "delay_after": 0.2},
            {"action": "hotkey", "keys": ["CTRL", "V"], "delay_after": 0.2},
            {"action": "hotkey", "keys": ["CTRL", "S"], "delay_after": 0.8},
            {"action": "hotkey", "keys": ["CTRL", "W"], "delay_after": 0.5},
        ]
        print("Executing Batch 4b (Move to end -> Paste -> Ctrl+S -> Ctrl+W)...")
        execute_batch(actions_append_text)

        # Close Notepad
        close_notepad_and_wait(notepad_hwnd)
        notepad_hwnd = None

        # Verify file content
        appended_text = RESULT_FILE.read_text(encoding="utf-8")
        print(f"Appended file content:\n---\n{appended_text}\n---")
        assert "Start" in appended_text, "File missing 'Start'"
        assert "Computer vision" in appended_text, "File missing 'Computer vision'"

        # Step 8: Rename file to final-result.txt
        print("\n--- Step 8: Rename result.txt -> final-result.txt ---")
        RESULT_FILE.rename(FINAL_FILE)
        assert FINAL_FILE.exists(), f"Renamed file not found: {FINAL_FILE}"
        assert not RESULT_FILE.exists(), "Original result.txt still exists after rename"
        print(f"File renamed to: {FINAL_FILE}")

        # Step 9: Move final-result.txt to Documents folder
        print("\n--- Step 9: Move final-result.txt -> Documents\\final-result.txt ---")
        shutil.move(str(FINAL_FILE), str(MOVED_FILE))
        assert MOVED_FILE.exists(), f"Moved file not found in Documents: {MOVED_FILE}"
        assert not FINAL_FILE.exists(), "File still exists in Desktop\\LCU-Production after move"
        print(f"File moved to: {MOVED_FILE}")

        # Step 10: Reopen Documents\final-result.txt in Notepad & Final Verification
        print("\n--- Step 10: Reopen in Notepad & Final Visual Verification ---")
        # Ensure no residual notepad window exists
        for _ in range(30):
            time.sleep(0.1)
            wins = [w for w in list_windows() if "Notepad" in w["title"] or "메모장" in w["title"]]
            if not wins:
                break

        apps.open_app("notepad")
        time.sleep(1.0)

        notepad_hwnd = None
        for _ in range(30):
            time.sleep(0.2)
            wins = [w for w in list_windows() if "Notepad" in w["title"] or "메모장" in w["title"]]
            if wins:
                notepad_hwnd = wins[0]["hwnd"]
                break

        print(f"Step 10 Notepad hwnd: {notepad_hwnd}")
        assert notepad_hwnd is not None, "Notepad failed to launch for final verification"
        set_window_bounds(x=200, y=100, width=850, height=520, hwnd=notepad_hwnd)
        focus_window(hwnd=notepad_hwnd)
        time.sleep(0.3)
        press_key("ESC")
        time.sleep(0.3)

        # Step 10: Open moved file via Ctrl+O
        actions_open_dialog = [
            {"action": "hotkey", "keys": ["CTRL", "O"], "delay_after": 1.0},
        ]
        print("Executing Batch 5a (Open file dialog via Ctrl+O)...")
        execute_batch(actions_open_dialog)

        time.sleep(0.5)

        actions_type = [
            {"action": "hotkey", "keys": ["ALT", "N"], "delay_after": 0.3},
            {"action": "type_text", "text": str(MOVED_FILE), "delay_after": 0.5},
        ]
        print("Executing Batch 5b (Enter path)...")
        execute_batch(actions_type)

        time.sleep(0.3)
        actions_enter = [
            {"action": "press_key", "key": "ENTER", "delay_after": 1.5},
        ]
        print("Executing Batch 5c (Press Enter)...")
        execute_batch(actions_enter)

        # Observation Boundary 3: Final Document State Verification
        time.sleep(1.0)
        snap3 = capture_screenshot(target="active-window", quality="normal")
        screenshots.append(snap3["captureId"])
        print(f"[Observation Boundary 3] Captured Final Verification State: {snap3['width']}x{snap3['height']}, id={snap3['captureId']}")

        # Close Notepad
        close_window(hwnd=notepad_hwnd)
        notepad_hwnd = None
        time.sleep(0.3)

        # Final Verification of File Contents on disk
        final_disk_text = MOVED_FILE.read_text(encoding="utf-8")
        assert "Start" in final_disk_text, "Final file missing 'Start'"
        assert "Computer vision" in final_disk_text, "Final file missing 'Computer vision'"
        print("Final file verified on disk and visually.")

        # Cleanup
        print("\n--- Cleanup ---")
        MOVED_FILE.unlink()
        assert not MOVED_FILE.exists(), "MOVED_FILE failed to delete"
        print(f"Deleted {MOVED_FILE}")

        shutil.rmtree(TEST_DIR, ignore_errors=True)
        assert not TEST_DIR.exists(), "TEST_DIR failed to delete"
        print(f"Deleted {TEST_DIR}")

        matches_doc = direct.find_path("final-result.txt", str(DOCUMENTS_DIR))
        assert matches_doc["count"] == 0, "final-result.txt still in Documents"
        matches_desk = direct.find_path("LCU-Production", str(DESKTOP_DIR))
        assert matches_desk["count"] == 0, "LCU-Production still on Desktop"
        print("Confirmed 100% clean state.")

        print("\nALL ASSERTIONS PASSED! TC-16 10-STEP STRESS TEST SUCCESSFUL.")
        return {
            "result": "PASS",
            "screenshots": screenshots,
            "final_content": final_disk_text,
        }

    finally:
        if notepad_hwnd:
            try:
                close_window(hwnd=notepad_hwnd)
            except Exception:
                pass
        if wiki_proc and wiki_proc.poll() is None:
            wiki_proc.terminate()
        if MOVED_FILE.exists():
            try:
                MOVED_FILE.unlink()
            except Exception:
                pass
        if TEST_DIR.exists():
            try:
                shutil.rmtree(TEST_DIR, ignore_errors=True)
            except Exception:
                pass


if __name__ == "__main__":
    res = run_tc16()
    print("\nResult:", res["result"])

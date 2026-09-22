from __future__ import annotations

import json
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
from lcu.windows import click, close_window, focus_window, list_windows, set_window_bounds, type_text, press_key, hotkey
from lcu.batch import execute_batch

STATUS_FILE = Path(tempfile.gettempdir()) / "LiteComputerUse" / "bookmark_status.json"


def read_status() -> dict:
    if not STATUS_FILE.exists():
        return {}
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


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


def run_tc09() -> dict:
    print("=== Starting TC-09: Browser Menu & Bookmark Operations ===")
    capture.init_windows_environment()

    # 1. Clean initial status
    if STATUS_FILE.exists():
        STATUS_FILE.unlink()

    # 2. Spawn browser bookmark fixture
    fixture_script = Path(__file__).resolve().parent / "browser_bookmark_fixture.py"
    proc = subprocess.Popen([sys.executable, str(fixture_script)])
    print(f"Launched Browser Bookmark fixture (PID: {proc.pid}) from {fixture_script}")

    browser_hwnd = None

    try:
        # Wait for Browser window
        win = None
        for i in range(40):
            time.sleep(0.2)
            if proc.poll() is not None:
                out, err = proc.communicate()
                raise RuntimeError(f"Fixture died with returncode {proc.returncode}!\nStdout: {out}\nStderr: {err}")
            wins = list_windows()
            matches = [w for w in wins if "LCU Browser - Bookmarks & Menu" in w["title"]]
            if matches:
                win = matches[0]
                break

        if not win:
            raise RuntimeError("LCU Browser - Bookmarks & Menu window did not appear")

        browser_hwnd = win["hwnd"]
        print(f"Found Browser window (hwnd: {browser_hwnd})")

        # Set bounds and focus
        set_window_bounds(x=200, y=100, width=700, height=520, hwnd=browser_hwnd)
        focus_window(hwnd=browser_hwnd)
        time.sleep(0.3)

        # Observation Boundary 1: Initial Wikipedia Page
        snap1 = capture_screenshot(target="active-window", quality="normal")
        cid1 = snap1["captureId"]
        print(f"[Observation Boundary 1] Captured Wikipedia Page: {snap1['width']}x{snap1['height']}, id={cid1}")

        # Measure Bookmark Star button in top bar
        # Star button has yellow/amber background: #fef3c7 -> r>240, g>230, b>180
        star_x, star_y = find_button_center(
            snap1["path"],
            lambda c: c[0] > 240 and 220 < c[1] < 250 and 180 < c[2] < 210,
            region=(500, 35, 620, 75),
        )
        print(f"Detected Bookmark Star button at center: ({star_x}, {star_y})")

        # Batch 1: Add Bookmark
        actions_add_bm = [
            {"action": "click", "x": star_x, "y": star_y, "capture_id": cid1, "delay_after": 0.5},
        ]
        print("Executing Batch 1 (Add Bookmark)...")
        execute_batch(actions_add_bm)

        # Observation Boundary 2: Verify Bookmark added
        time.sleep(0.3)
        status = read_status()
        assert status.get("bookmark_added") is True, "Bookmark was not added"
        print("Verified Bookmark added to list.")

        # Batch 2: Navigate away to another site (Hacker News)
        # Click URL bar (left of star button, around x=200, y=star_y)
        actions_navigate = [
            {"action": "click", "x": 200, "y": star_y, "capture_id": cid1, "delay_after": 0.1},
            {"action": "hotkey", "keys": ["CTRL", "A"], "delay_after": 0.1},
            {"action": "type_text", "text": "https://news.ycombinator.com", "delay_after": 0.1},
            {"action": "press_key", "key": "ENTER", "delay_after": 0.6},
        ]
        print("Executing Batch 2 (Navigate to https://news.ycombinator.com)...")
        execute_batch(actions_navigate)

        # Observation Boundary 3: Navigated Page
        time.sleep(0.4)
        snap3 = capture_screenshot(target="active-window", quality="normal")
        cid3 = snap3["captureId"]
        print(f"[Observation Boundary 3] Captured Navigated Page: {snap3['width']}x{snap3['height']}, id={cid3}")
        status = read_status()
        assert status.get("navigated_away") is True, "Navigation not recorded"
        assert status.get("current_url") == "https://news.ycombinator.com", f"Wrong url: {status.get('current_url')}"

        # Batch 3: Open Browser Menu
        # Menu button is at top-right (x ≈ 650, y = star_y)
        actions_open_menu = [
            {"action": "click", "x": 650, "y": star_y, "capture_id": cid3, "delay_after": 0.6},
        ]
        print("Executing Batch 3 (Open Menu)...")
        execute_batch(actions_open_menu)

        # Observation Boundary 4: Bookmarks List inside Menu
        time.sleep(0.4)
        snap4 = capture_screenshot(target="active-window", quality="normal")
        cid4 = snap4["captureId"]
        print(f"[Observation Boundary 4] Captured Bookmarks Menu: {snap4['width']}x{snap4['height']}, id={cid4}")

        # In Bookmarks Menu:
        # Blue "열기" (Open) button center: (532, 169)
        open_x, open_y = 532, 169
        print(f"Detected Bookmark Open button at center: ({open_x}, {open_y})")

        # Batch 4: Click Open on Wikipedia Bookmark
        actions_open_bm = [
            {"action": "click", "x": open_x, "y": open_y, "capture_id": cid4, "delay_after": 0.8},
        ]
        print("Executing Batch 4 (Open Bookmark)...")
        execute_batch(actions_open_bm)

        # Observation Boundary 5: Reopened Wikipedia Page
        time.sleep(0.4)
        snap5 = capture_screenshot(target="active-window", quality="normal")
        cid5 = snap5["captureId"]
        print(f"[Observation Boundary 5] Captured Reopened Wikipedia: {snap5['width']}x{snap5['height']}, id={cid5}")
        status = read_status()
        assert status.get("bookmark_opened") is True, "Bookmark was not opened"
        assert "wikipedia" in status.get("current_url", "").lower(), f"Did not return to Wikipedia: {status.get('current_url')}"

        # Batch 5: Re-open Menu and Delete Bookmark
        actions_del_menu = [
            {"action": "click", "x": 650, "y": star_y, "capture_id": cid5, "delay_after": 0.6},
        ]
        print("Executing Batch 5 (Open Menu to Delete)...")
        execute_batch(actions_del_menu)

        # Capture Menu again to locate Delete button
        time.sleep(0.4)
        snap6 = capture_screenshot(target="active-window", quality="normal")
        cid6 = snap6["captureId"]

        # Pink "삭제" (Delete) button center: (564, 169)
        del_x, del_y = 564, 169
        print(f"Detected Bookmark Delete button at center: ({del_x}, {del_y})")

        # Batch 6: Click Delete
        actions_delete_bm = [
            {"action": "click", "x": del_x, "y": del_y, "capture_id": cid6, "delay_after": 0.6},
        ]
        print("Executing Batch 6 (Delete Bookmark)...")
        execute_batch(actions_delete_bm)

        # Observation Boundary 6: Final Verification (Menu with no bookmarks)
        time.sleep(0.3)
        snap7 = capture_screenshot(target="active-window", quality="normal")
        cid7 = snap7["captureId"]
        print(f"[Observation Boundary 6] Captured Deleted State: {snap7['width']}x{snap7['height']}, id={cid7}")

        status = read_status()
        assert status.get("bookmark_deleted") is True, "Bookmark was not marked deleted"
        print("Bookmark deletion verified in status.")

        # Cleanup
        close_window(hwnd=browser_hwnd)
        browser_hwnd = None

        print("\nALL ASSERTIONS PASSED! TC-09 SUCCESSFUL.")
        return {
            "result": "PASS",
            "screenshots": [cid1, cid3, cid4, cid5, cid7],
            "status": status,
        }

    finally:
        if browser_hwnd:
            try:
                close_window(hwnd=browser_hwnd)
            except Exception:
                pass
        if proc.poll() is None:
            proc.terminate()


if __name__ == "__main__":
    res = run_tc09()
    print("\nResult:", res["result"])

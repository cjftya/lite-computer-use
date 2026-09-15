from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lcu import apps, batch, capture, direct, errors, windows
from lcu.capture import capture_screenshot
from lcu.windows import click, close_window, drag, focus_window, list_windows, set_window_bounds

STATUS_FILE = Path(tempfile.gettempdir()) / "LiteComputerUse" / "smoke_status.json"
EXIT_FLAG = Path(tempfile.gettempdir()) / "LiteComputerUse" / "smoke_exit.flag"


def read_status() -> dict[str, Any]:
    if not STATUS_FILE.exists():
        return {}
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def find_color_center(image_path: str, target_rgb: tuple[int, int, int], tolerance: int = 25) -> tuple[int, int] | None:
    img = Image.open(image_path).convert("RGB")
    width, height = img.size
    pixels = img.load()

    matching_points: list[tuple[int, int]] = []
    tr, tg, tb = target_rgb
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            if abs(r - tr) <= tolerance and abs(g - tg) <= tolerance and abs(b - tb) <= tolerance:
                matching_points.append((x, y))

    if not matching_points:
        return None

    avg_x = sum(p[0] for p in matching_points) // len(matching_points)
    avg_y = sum(p[1] for p in matching_points) // len(matching_points)
    return avg_x, avg_y


def main() -> None:
    print("=== Lite Computer Use v2 Windows Smoke Tests ===")

    # Cleanup flags
    if EXIT_FLAG.exists():
        EXIT_FLAG.unlink()
    if STATUS_FILE.exists():
        STATUS_FILE.unlink()

    # 1. Launch GUI fixture
    fixture_script = Path(__file__).parent / "smoke_gui_fixture.py"
    proc = subprocess.Popen([sys.executable, str(fixture_script)])
    print("Launched smoke GUI fixture (pid:", proc.pid, ")")

    try:
        # 2. Wait for window
        fixture_win = None
        for _ in range(30):
            time.sleep(0.2)
            wins = list_windows(query="LCU Smoke Fixture")
            if wins:
                fixture_win = wins[0]
                break

        if not fixture_win:
            print("FAILED: LCU Smoke Fixture window did not appear!")
            sys.exit(1)

        hwnd = fixture_win["hwnd"]
        print(f"Found fixture window (hwnd: {hwnd})")

        # 3. Set window bounds
        bounds = set_window_bounds(x=150, y=150, width=600, height=450, hwnd=hwnd)
        print("Set window bounds:", bounds["bounds"])

        # 4. Focus window
        focus_window(hwnd=hwnd)
        time.sleep(0.3)
        print("Focused fixture window")

        # 5. Test Button A click with FAST preset
        print("\n--- Test 1: Button A with 'fast' preset ---")
        snap_fast = capture_screenshot(target="active-window", quality="fast")
        cid_fast = snap_fast["captureId"]
        print(f"Captured fast: {snap_fast['width']}x{snap_fast['height']}, id: {cid_fast}")
        # Button A is green #4CAF50 -> (76, 175, 80)
        btn_a_coord = find_color_center(snap_fast["path"], (76, 175, 80))
        assert btn_a_coord is not None, "Button A color not found in screenshot"
        print(f"Detected Button A at image coords: {btn_a_coord}")
        click(btn_a_coord[0], btn_a_coord[1], capture_id=cid_fast)
        time.sleep(0.2)
        st = read_status()
        print("Status hit_A:", st.get("hit_A"))
        assert st.get("hit_A") == 1, f"Expected hit_A == 1, got {st.get('hit_A')}"
        print("PASSED: Button A click via fast captureId!")

        # 6. Test Button B click with NORMAL preset
        print("\n--- Test 2: Button B with 'normal' preset ---")
        snap_norm = capture_screenshot(target="active-window", quality="normal")
        cid_norm = snap_norm["captureId"]
        print(f"Captured normal: {snap_norm['width']}x{snap_norm['height']}, id: {cid_norm}")
        # Button B is blue #2196F3 -> (33, 150, 243)
        btn_b_coord = find_color_center(snap_norm["path"], (33, 150, 243))
        assert btn_b_coord is not None, "Button B color not found in screenshot"
        print(f"Detected Button B at image coords: {btn_b_coord}")
        click(btn_b_coord[0], btn_b_coord[1], capture_id=cid_norm)
        time.sleep(0.2)
        st = read_status()
        print("Status hit_B:", st.get("hit_B"))
        assert st.get("hit_B") == 1, f"Expected hit_B == 1, got {st.get('hit_B')}"
        print("PASSED: Button B click via normal captureId!")

        # 7. Test Button C click with DETAIL preset
        print("\n--- Test 3: Button C with 'detail' preset ---")
        snap_detail = capture_screenshot(target="active-window", quality="detail")
        cid_detail = snap_detail["captureId"]
        print(f"Captured detail: {snap_detail['width']}x{snap_detail['height']}, id: {cid_detail}")
        # Button C is orange #FF9800 -> (255, 152, 0)
        btn_c_coord = find_color_center(snap_detail["path"], (255, 152, 0))
        assert btn_c_coord is not None, "Button C color not found in screenshot"
        print(f"Detected Button C at image coords: {btn_c_coord}")
        click(btn_c_coord[0], btn_c_coord[1], capture_id=cid_detail)
        time.sleep(0.2)
        st = read_status()
        print("Status hit_C:", st.get("hit_C"))
        assert st.get("hit_C") == 1, f"Expected hit_C == 1, got {st.get('hit_C')}"
        print("PASSED: Button C click via detail captureId!")

        # 8. Test Region capture & click on Button A
        print("\n--- Test 4: Region capture around Button A ---")
        # Region in window coordinates: around (90, 70, 120, 70)
        snap_region = capture_screenshot(target="active-window", region=(90, 70, 120, 70), quality="normal")
        cid_reg = snap_region["captureId"]
        print(f"Captured region: {snap_region['width']}x{snap_region['height']}, id: {cid_reg}")
        btn_a_reg_coord = find_color_center(snap_region["path"], (76, 175, 80))
        assert btn_a_reg_coord is not None, "Button A not found in region screenshot"
        print(f"Detected Button A at region image coords: {btn_a_reg_coord}")
        click(btn_a_reg_coord[0], btn_a_reg_coord[1], capture_id=cid_reg)
        time.sleep(0.2)
        st = read_status()
        print("Status hit_A (second time):", st.get("hit_A"))
        assert st.get("hit_A") == 2, f"Expected hit_A == 2, got {st.get('hit_A')}"
        print("PASSED: Region capture and click!")

        # 9. Test from-capture partial recapture on Button B
        print("\n--- Test 5: Recapture from previous capture (from-capture) ---")
        # In snap_norm (from Test 2), Button B was at btn_b_coord
        bx, by = btn_b_coord
        sub_reg = (max(0, bx - 40), max(0, by - 20), 80, 40)
        snap_sub = capture_screenshot(from_capture=cid_norm, region=sub_reg, quality="detail")
        cid_sub = snap_sub["captureId"]
        print(f"Recaptured from-capture: {snap_sub['width']}x{snap_sub['height']}, id: {cid_sub}")
        btn_b_sub_coord = find_color_center(snap_sub["path"], (33, 150, 243))
        assert btn_b_sub_coord is not None, "Button B not found in sub-capture"
        click(btn_b_sub_coord[0], btn_b_sub_coord[1], capture_id=cid_sub)
        time.sleep(0.2)
        st = read_status()
        print("Status hit_B (second time):", st.get("hit_B"))
        assert st.get("hit_B") == 2, f"Expected hit_B == 2, got {st.get('hit_B')}"
        print("PASSED: Partial recapture from-capture and click!")

        # 10. Test Drag on canvas
        print("\n--- Test 6: Drag on canvas ---")
        # In snap_detail, canvas is white area at (400, 260) to (560, 390)
        # Drag from (450, 310) to (520, 360)
        drag(450, 310, 520, 360, capture_id=cid_detail, duration=0.2)
        time.sleep(0.3)
        st = read_status()
        print("Status drag_done:", st.get("drag_done"))
        assert st.get("drag_done") is True, "Expected drag_done == True"
        print("PASSED: Drag operation verified!")

        # 11. Test Batch with delay_after on fixture
        print("\n--- Test 7: Batch sequence execution ---")
        batch_res = batch.execute_batch([
            {"action": "click", "x": btn_c_coord[0], "y": btn_c_coord[1], "capture": cid_detail, "delay_after": 0.1},
            {"action": "set_clipboard", "text": "Batch Smoke OK", "delay_after": 0.05},
        ])
        assert batch_res["ok"] is True
        assert batch_res["result"]["completed"] == 2
        st = read_status()
        print("Status hit_C (second time):", st.get("hit_C"))
        assert st.get("hit_C") == 2, f"Expected hit_C == 2, got {st.get('hit_C')}"
        print("PASSED: Batch execution verified!")

        # 12. Test close_window
        print("\n--- Test 8: Close window ---")
        close_res = close_window(hwnd=hwnd)
        assert close_res["closed"] is True
        print("PASSED: Close window verified!")

    finally:
        EXIT_FLAG.write_text("exit")
        try:
            proc.wait(timeout=2.0)
        except Exception:
            proc.kill()

    print("\n=== ALL REAL WINDOWS SMOKE TESTS PASSED PERFECTLY! ===")


if __name__ == "__main__":
    main()

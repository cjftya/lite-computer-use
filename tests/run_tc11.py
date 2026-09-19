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

STATUS_FILE = Path(tempfile.gettempdir()) / "LiteComputerUse" / "form_status.json"


def read_status() -> dict:
    if not STATUS_FILE.exists():
        return {}
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def run_tc11() -> dict:
    print("=== Starting TC-11: Multi-Step Web Form Fixture ===")
    capture.init_windows_environment()

    # 1. Clean previous status
    if STATUS_FILE.exists():
        STATUS_FILE.unlink()

    # 2. Spawn GUI fixture
    fixture_script = Path(__file__).resolve().parent / "form_gui_fixture.py"
    proc = subprocess.Popen([sys.executable, str(fixture_script)])
    print(f"Launched Form GUI fixture (PID: {proc.pid}) from {fixture_script}")

    try:
        # Wait for window
        win = None
        for i in range(40):
            time.sleep(0.2)
            if proc.poll() is not None:
                out, err = proc.communicate()
                raise RuntimeError(f"Fixture process died with exit code {proc.returncode}!\nStdout: {out.decode('utf-8', errors='replace')}\nStderr: {err.decode('utf-8', errors='replace')}")
            wins = list_windows()
            if i % 10 == 0:
                print(f"Iteration {i}: {len(wins)} windows found: {[w['title'] for w in wins]}")
            matches = [w for w in wins if "Form" in w["title"] or "form" in w["title"].lower()]
            if matches:
                win = matches[0]
                break

        if not win:
            raise RuntimeError("LCU Form Fixture window did not appear")

        hwnd = win["hwnd"]
        print(f"Found window (hwnd: {hwnd})")

        # Set bounds and focus
        set_window_bounds(x=200, y=100, width=600, height=520, hwnd=hwnd)
        focus_window(hwnd=hwnd)
        time.sleep(0.3)

        # Observation Boundary 1: Initial Screen (Step 1)
        snap1 = capture_screenshot(target="active-window", quality="normal")
        cid1 = snap1["captureId"]
        print(f"[Observation Boundary 1] Captured Step 1: {snap1['width']}x{snap1['height']}, id={cid1}")

        # Batch 1: Fill all Step 1 inputs and click Continue
        # Coordinates measured from snap1:
        # Name Entry: x=300, y=160
        # Email Entry: x=300, y=225
        # Country Combobox: x=300, y=292
        # Checkbox B: x=175, y=360
        # Checkbox C: x=260, y=360
        # Continue Button: x=300, y=425

        actions_step1 = [
            {"action": "click", "x": 300, "y": 160, "capture_id": cid1, "delay_after": 0.1},
            {"action": "type_text", "text": "LCU Production", "delay_after": 0.1},
            {"action": "click", "x": 300, "y": 225, "capture_id": cid1, "delay_after": 0.1},
            {"action": "type_text", "text": "lcu@example.com", "delay_after": 0.1},
            # Country: click combobox, down arrow to South Korea, enter
            {"action": "click", "x": 300, "y": 292, "capture_id": cid1, "delay_after": 0.2},
            {"action": "press_key", "key": "DOWN", "delay_after": 0.1},
            {"action": "press_key", "key": "ENTER", "delay_after": 0.1},
            # Option B & C
            {"action": "click", "x": 175, "y": 360, "capture_id": cid1, "delay_after": 0.1},
            {"action": "click", "x": 260, "y": 360, "capture_id": cid1, "delay_after": 0.1},
            # Continue
            {"action": "click", "x": 300, "y": 425, "capture_id": cid1, "delay_after": 0.6},
        ]

        print(f"Executing Batch 1 ({len(actions_step1)} actions)...")
        b1_res = execute_batch(actions_step1)
        print("Batch 1 completed successfully.")

        # Observation Boundary 2: Step 2 Form (Memo)
        time.sleep(0.4)
        snap2 = capture_screenshot(target="active-window", quality="normal")
        cid2 = snap2["captureId"]
        print(f"[Observation Boundary 2] Captured Step 2: {snap2['width']}x{snap2['height']}, id={cid2}")

        # Batch 2: Type memo and click Submit
        # Memo Text: x=300, y=200
        # Submit Button: x=307, y=340
        actions_step2 = [
            {"action": "click", "x": 300, "y": 200, "capture_id": cid2, "delay_after": 0.1},
            {"action": "type_text", "text": "Phase 2 production test", "delay_after": 0.1},
            {"action": "click", "x": 307, "y": 340, "capture_id": cid2, "delay_after": 0.6},
        ]

        print(f"Executing Batch 2 ({len(actions_step2)} actions)...")
        b2_res = execute_batch(actions_step2)
        print("Batch 2 completed successfully.")

        # Observation Boundary 3: Completion Screen Verification
        time.sleep(0.3)
        snap3 = capture_screenshot(target="active-window", quality="normal")
        cid3 = snap3["captureId"]
        print(f"[Observation Boundary 3] Captured Complete Screen: {snap3['width']}x{snap3['height']}, id={cid3}")

        # Verify state
        status = read_status()
        print("\n--- Final Status Verification ---")
        print(json.dumps(status, indent=2, ensure_ascii=False))

        assert status.get("name") == "LCU Production", f"Wrong name: {status.get('name')}"
        assert status.get("email") == "lcu@example.com", f"Wrong email: {status.get('email')}"
        assert status.get("country") == "South Korea", f"Wrong country: {status.get('country')}"
        assert status.get("opt_b") is True, "Option B not checked"
        assert status.get("opt_c") is True, "Option C not checked"
        assert status.get("opt_a") is False, "Option A unexpectedly checked"
        assert status.get("memo") == "Phase 2 production test", f"Wrong memo: {status.get('memo')}"
        assert status.get("submitted") is True, "Form not marked submitted"

        print("\nALL ASSERTIONS PASSED! TC-11 SUCCESSFUL.")
        return {
            "result": "PASS",
            "screenshots": [cid1, cid2, cid3],
            "status": status,
        }

    finally:
        # Cleanup
        try:
            close_window(hwnd=hwnd)
        except Exception:
            pass
        if proc.poll() is None:
            proc.terminate()


if __name__ == "__main__":
    res = run_tc11()
    print("\nResult:", res["result"])

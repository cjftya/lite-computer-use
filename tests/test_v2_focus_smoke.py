import sys
import time
from pathlib import Path

# Add scripts directory
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lcu.apps import open_app
from lcu.windows import focus_window, list_windows
from lcu.errors import LCUError

def main():
    print("=== Lite Computer Use v2 Windows Focus & AppX Smoke Tests ===")

    def wait_for_window(query: str, timeout: float = 3.0):
        t_end = time.time() + timeout
        while time.time() < t_end:
            wins = list_windows(query)
            if wins:
                return wins[0]
            time.sleep(0.2)
        raise AssertionError(f"Window matching '{query}' did not appear within {timeout}s")

    # 1. Open Calculator
    print("\n--- Test 1: Open Calculator (AppX/Win32) ---")
    res_calc = open_app("calculator")
    print("open_app calculator result:", res_calc)
    calc_win = wait_for_window("계산기")
    calc_hwnd = calc_win["hwnd"]
    print(f"PASSED: Calculator window confirmed (hwnd: {calc_hwnd})")

    # 2. Open Notepad
    print("\n--- Test 2: Open Notepad (Modern AppX/Win32) ---")
    res_note = open_app("notepad")
    print("open_app notepad result:", res_note)
    note_win = wait_for_window("메모장")
    note_hwnd = note_win["hwnd"]
    print(f"PASSED: Notepad window confirmed (hwnd: {note_hwnd})")

    # 3. Focus Calculator from Notepad
    print("\n--- Test 3: Focus Calculator ---")
    f_calc = focus_window(hwnd=calc_hwnd)
    time.sleep(0.1)
    import win32gui
    curr_fg = win32gui.GetForegroundWindow()
    print(f"Foreground window: {curr_fg}, expected: {calc_hwnd}")
    assert curr_fg == calc_hwnd, f"Expected {calc_hwnd} to be foreground, got {curr_fg}"
    print("PASSED: Calculator focused successfully!")

    # 4. Focus Notepad from Calculator (UWP -> Win32)
    print("\n--- Test 4: Focus Notepad from Calculator ---")
    f_note = focus_window(hwnd=note_hwnd)
    time.sleep(0.1)
    curr_fg = win32gui.GetForegroundWindow()
    print(f"Foreground window: {curr_fg}, expected: {note_hwnd}")
    assert curr_fg == note_hwnd, f"Expected {note_hwnd} to be foreground, got {curr_fg}"
    print("PASSED: Notepad focused successfully from Calculator!")

    # 5. Focus Calculator back from Notepad (Win32 -> UWP)
    print("\n--- Test 5: Focus Calculator back from Notepad ---")
    f_calc2 = focus_window(hwnd=calc_hwnd)
    time.sleep(0.1)
    curr_fg = win32gui.GetForegroundWindow()
    print(f"Foreground window: {curr_fg}, expected: {calc_hwnd}")
    assert curr_fg == calc_hwnd, f"Expected {calc_hwnd} to be foreground, got {curr_fg}"
    print("PASSED: Calculator focused back successfully!")

    # 6. Ambiguity check when multiple windows exist
    print("\n--- Test 6: Ambiguous window target ---")
    try:
        focus_window("chrome")
        print("Note: Single or no Chrome window, skipping ambiguity assert")
    except LCUError as e:
        assert e.code == "ambiguous_target"
        print(f"PASSED: Ambiguous target caught correctly: {e.message}")

    # 7. Non-existent window failure without retry loops
    print("\n--- Test 7: Non-existent window target ---")
    t0 = time.time()
    try:
        focus_window("DefinitelyNonExistentWindow99999")
        assert False, "Should have raised window_not_found"
    except LCUError as e:
        elapsed = time.time() - t0
        assert e.code == "window_not_found"
        assert elapsed < 1.0, "Must fail fast without retry loops"
        print(f"PASSED: Non-existent target failed fast in {elapsed:.3f}s with code: {e.code}")

    print("\n=== ALL FOCUS & APPX REAL SMOKE TESTS PASSED! ===")

if __name__ == "__main__":
    main()

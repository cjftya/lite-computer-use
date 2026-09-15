# Windows Smoke Tests (v2)

This document describes how to execute automated and interactive verification of the Lite Computer Use v2 tool layer on Windows.

---

## 1. Automated Verification Suite

Run all unit tests and live GUI smoke tests in PowerShell:

```powershell
# 1. Run unit tests
py -3.13 -m pytest

# 2. Run system doctor
py -3.13 scripts\lcu.py doctor

# 3. Run automated GUI coordinate & click smoke tests
py -3.13 tests\run_smoke_tests.py
```

### What `tests\run_smoke_tests.py` verifies:
- Spawns a live Tkinter GUI fixture (`tests\smoke_gui_fixture.py`) with Button A, Button B, Button C, Entry, and Canvas.
- Enumerate & find window via `list_windows`
- Positions and resizes window via `set_window_bounds`
- Foreground focus via `focus_window`
- **Fast preset**: Screenshot -> detect Button A in image -> click via `captureId` -> verify click received.
- **Normal preset**: Screenshot -> detect Button B in image -> click via `captureId` -> verify click received.
- **Detail preset**: Screenshot -> detect Button C in image -> click via `captureId` -> verify click received.
- **Region capture**: Active-window sub-box -> detect Button A -> click via `captureId` -> verify click received.
- **From-capture recapture**: Zoom in on Button B from previous capture -> click -> verify click received.
- **Drag operation**: Drag on canvas area -> verify drag motion received.
- **Batch sequence**: Multi-action sequence with `delay_after` -> verify sequential execution.
- **Close window**: Cleanly close fixture via `close_window`.

---

## 2. Interactive Smoke Tests Checklist

| Tool | Command | Verification Criteria |
|---|---|---|
| `doctor` | `py -3.13 scripts\lcu.py doctor` | `ok: true`, all dependencies and DPI checks pass |
| `open_app` | `py -3.13 scripts\lcu.py open_app notepad` | Notepad window opens |
| `open_app` (Korean) | `py -3.13 scripts\lcu.py open_app 계산기` | Windows Calculator opens |
| `open_folder` | `py -3.13 scripts\lcu.py open_folder downloads` | Explorer opens Downloads folder |
| `open_url` | `py -3.13 scripts\lcu.py open_url "https://www.naver.com"` | Default browser opens URL |
| `list_windows` | `py -3.13 scripts\lcu.py list_windows --query notepad` | Returns hwnd, title, process, bounds |
| `focus_window` | `py -3.13 scripts\lcu.py focus_window "notepad"` | Notepad brought to foreground |
| `set_window_bounds` | `py -3.13 scripts\lcu.py set_window_bounds --query notepad --x 100 --y 100 --width 800 --height 600` | Window moves and resizes to 800x600 |
| `type_text` | `py -3.13 scripts\lcu.py type_text "Hello Windows! 한국어 입력"` | Text typed into Notepad correctly |
| `hotkey` | `py -3.13 scripts\lcu.py hotkey CTRL A` | Text in Notepad selected |
| `set_clipboard` | `py -3.13 scripts\lcu.py set_clipboard "Clipboard test"` | Clipboard updated |
| `get_clipboard` | `py -3.13 scripts\lcu.py get_clipboard` | Returns `"Clipboard test"` |
| `hotkey` | `py -3.13 scripts\lcu.py hotkey CTRL V` | Pastes clipboard text into Notepad |
| `close_window` | `py -3.13 scripts\lcu.py close_window "notepad"` | Closes Notepad (prompts save dialog if modified) |
| `batch` | `py -3.13 scripts\lcu.py batch '[{"action": "set_clipboard", "text": "Batch"}, {"action": "open_file", "path": "bad"}]'` | Fails fast at step 2, step 1 completed |

---

## 3. Key Hardening Contracts Verified

- **Batch Pre-validation**: All action schemas are validated upfront before execution. An invalid action anywhere in the list causes the entire batch to fail immediately with zero side effects.
- **Path Resolution**: `open_file` and `reveal_file` strictly reject relative paths with `invalid_arguments`.
- **Pixel Boundaries**: Image pixel coordinates in `resolve_capture_coordinates` require `0 <= x < width` and `0 <= y < height`. Boundary values `x == width` or `y == height` are rejected with `coordinate_out_of_bounds`.
- **Screen Region Coordinates**: `screenshot --target screen --region x y w h` always computes coordinates relative to virtual desktop `(0, 0)` regardless of multi-monitor origin offsets.
- **Cache Boundedness**: Retains at most 50 captures within 24 hours in `%TEMP%\LiteComputerUse\`; older records and image files are purged automatically.
- **Window Screenshot Limitation**: `screenshot --target window` captures visible screen pixels within window bounds. Use `focus_window` first if window might be obscured.

# Lite Computer Use (v2)

Lite Computer Use is a minimalist, ultra-precise Windows tool layer designed for AI coding agents such as Google Antigravity, Claude Code, and Gemini CLI.

Core Philosophy:
> **AI plans and reasons. Python provides small, explicit Windows manipulation tools.**

No planner, retry loop, visual fallback heuristics, OCR, or DOM crawlers inside Python.
Every tool executes once, validates parameters, and returns structured JSON immediately.

---

## Requirements

- Windows 10 / Windows 11 (x64)
- Python 3.11+ (`py -3.13` recommended)
- Antigravity CLI or compatible host agent

---

## Dependencies & Installation

1. Install Python dependencies:
```powershell
py -3.13 -m pip install -r requirements.txt
```

`requirements.txt`:
- `Pillow`
- `PyAutoGUI`
- `PyYAML`
- `pywin32`
- `pytest` (for tests)

2. Verify environment setup using `doctor`:
```powershell
py -3.13 scripts\lcu.py doctor
```

Output:
```json
{
  "ok": true,
  "action": "doctor",
  "result": {
    "os_windows": true,
    "python_version": "3.13.15",
    "python_version_ok": true,
    "dependencies": {
      "PIL": true,
      "pyautogui": true,
      "win32gui": true,
      "win32con": true,
      "yaml": true
    },
    "dpi_initialized": true,
    "temp_storage_ok": true
  }
}
```

---

## Public Toolset

All tools speak standard JSON:
- On success: `{"ok": true, "action": "<name>", "result": { ... }}`
- On failure: `{"ok": false, "action": "<name>", "error": {"code": "...", "message": "...", "candidates": [...]}}`

### 1. Open & Discovery
```powershell
# Launch by name: resolve -> inspect existing -> dispatch once -> observe -> focus
py -3.13 scripts\lcu.py open_app chrome
py -3.13 scripts\lcu.py open_app notepad
py -3.13 scripts\lcu.py open_app 계산기
py -3.13 scripts\lcu.py open_app paint

# Include stage timing and launch-context diagnostics
py -3.13 scripts\lcu.py open_app vscode --debug

# Resume observation without launching again (use an attempt_id from an error)
py -3.13 scripts\lcu.py app_status 12345678-1234-1234-1234-123456789abc --timeout 10

# Open file with default application (rejects executables/scripts)
py -3.13 scripts\lcu.py open_file "C:\Users\me\Documents\report.pdf"

# Open folder (supports aliases: desktop, documents, downloads, 바탕화면, 문서, 다운로드)
py -3.13 scripts\lcu.py open_folder downloads

# Open URL (http/https only)
py -3.13 scripts\lcu.py open_url "https://github.com"

# Reveal file in Explorer
py -3.13 scripts\lcu.py reveal_file "C:\Users\me\Downloads\invoice.pdf"

# Bounded file/folder search
py -3.13 scripts\lcu.py find_path "data" --root downloads --kind file --limit 10
```

### 2. Window Management
```powershell
# List visible windows
py -3.13 scripts\lcu.py list_windows --query chrome

# Focus window (restores if minimized, brings to foreground)
py -3.13 scripts\lcu.py focus_window --hwnd 12345
py -3.13 scripts\lcu.py focus_window "Visual Studio Code"

# Close window (standard WM_CLOSE, verifies window destruction via polling, optional --owned-processes for safe orphan cleanup)
py -3.13 scripts\lcu.py close_window --hwnd 12345
py -3.13 scripts\lcu.py close_window --hwnd 12345 --owned-processes '[{"pid": 4321, "creation_time": 12345, "process_name": "Notepad.exe"}]'

# Position and resize window (stabilize coordinate space)
py -3.13 scripts\lcu.py set_window_bounds --hwnd 12345 --x 100 --y 100 --width 1400 --height 900
```

### 3. Vision & Screenshot (with `captureId`)
Lite Computer Use maps image coordinates back to physical screen coordinates automatically.
```powershell
# Capture active window with normal preset (max 1600px, WebP ~80KB)
py -3.13 scripts\lcu.py screenshot --target active-window --quality normal

# Capture whole virtual screen with fast preset (max 1024px, WebP ~30KB)
py -3.13 scripts\lcu.py screenshot --target screen --quality fast

# Capture specific window region (relative to window top-left)
py -3.13 scripts\lcu.py screenshot --target active-window --region 100 80 400 300

# Partial re-capture from an existing capture (detail preset: 1.0x lossless)
py -3.13 scripts\lcu.py screenshot --from-capture c_8f2a91 --region 50 50 200 150 --quality detail
```

Output:
```json
{
  "ok": true,
  "action": "screenshot",
  "result": {
    "captureId": "c_8f2a91",
    "path": "C:\\Users\\...\\c_8f2a91.webp",
    "width": 1600,
    "height": 900
  }
}
```

- **Screen region coordinates**: `screenshot --target screen --region x y w h` always treats the top-left of the multi-monitor virtual desktop image as `(0, 0)`.
- **Window capture note**: `screenshot --target window` captures visible screen pixels within the window bounds; use `focus_window` first if other windows might overlap.
- **Cache policy**: Retains up to 50 most recent captures within 24 hours in `%TEMP%\LiteComputerUse\`; older captures and image files are pruned automatically.

### 4. Mouse & Keyboard
AI clicks the exact coordinates seen in the image; Python translates scale, region crop offset, and window offset:
```powershell
# Click coordinates seen in screenshot
py -3.13 scripts\lcu.py click 842 311 --capture c_8f2a91
py -3.13 scripts\lcu.py click 842 311 --capture c_8f2a91 --button right
py -3.13 scripts\lcu.py click 842 311 --capture c_8f2a91 --count 2

# Move mouse & Drag
py -3.13 scripts\lcu.py move_mouse 842 311 --capture c_8f2a91
py -3.13 scripts\lcu.py drag 100 200 400 500 --capture c_8f2a91

# Scroll & Mouse Position
py -3.13 scripts\lcu.py scroll -5
py -3.13 scripts\lcu.py get_mouse_position

# Unicode & Hangul text input (SendInput KEYEVENTF_UNICODE)
py -3.13 scripts\lcu.py type_text "Hello Windows! 한국어 입력 테스트"

# Special keys & Hotkeys
py -3.13 scripts\lcu.py press_key ENTER
py -3.13 scripts\lcu.py press_key TAB --count 3
py -3.13 scripts\lcu.py hotkey CTRL SHIFT S

# Clipboard
py -3.13 scripts\lcu.py set_clipboard "Copied text"
py -3.13 scripts\lcu.py get_clipboard
```

### 5. Batch Execution
Execute deterministic multi-action sequences with static validation and fail-fast execution:
- **Upfront validation**: The entire static action schema, including supported key names, is checked before execution. A static error prevents every action from running.
- **Runtime failure**: Stops at the first execution error without retry. Earlier actions may already have changed the desktop or clipboard; batch is not a transaction.
- **Results**: `result.completed` counts completed actions. `result.results` contains each completed action's `index`, `action`, and original `result`, including launch ownership metadata. On failure, `failedIndex`, `failedAction`, and `error` accompany the partial results. A later action cannot reference an earlier result inside the same batch; split calls if a new `hwnd` is needed.
- **Input**: `input_dispatch_failed` means Windows did not confirm insertion of a key event. Successful insertion does not confirm that the target app used or saved the input. `type_text` returns `chars` as the original Python character count; CRLF sends one Enter and supplementary Unicode characters use UTF-16 surrogate pairs.

```powershell
py -3.13 scripts\lcu.py batch '[
  {"action": "click", "x": 620, "y": 350, "capture": "c_8f2a91", "delay_after": 0.2},
  {"action": "type_text", "text": "Search Query"},
  {"action": "press_key", "key": "ENTER"}
]'
```

---

## Running Smoke Tests & Verification

### Unit Tests
```powershell
py -3.13 -m pytest
```

### PowerShell / Antigravity launch-context parity

Run the same diagnostic once from PowerShell and once from Antigravity Bash before
comparing GUI behavior. Selected environment values are reported only as presence,
length, and a locally keyed fingerprint; only validated boolean flags may show a value.
It also reports a PATH hash, executable resolution, session, window station, and desktop
status. Raw token, IPC-hook, shell-path, complete environment, and PATH values are not emitted.

```powershell
py -3.13 scripts\lcu.py launch_context > powershell-launch-context.json
```

```bash
py -3.13 scripts/lcu.py launch_context > antigravity-launch-context.json
```

Executable GUI launches currently receive a copied environment with only
`ELECTRON_RUN_AS_NODE`, `ELECTRON_NO_ATTACH_CONSOLE`, and `VSCODE_IPC_HOOK_CLI`
removed. This is a bounded candidate policy pending same-host PowerShell/Antigravity
A/B confirmation, not a confirmed root cause. `NODE_OPTIONS` and other variable families
remain untouched. Standard input/output/error are detached, and the launch working
directory is the executable directory or the user profile fallback.

Window readiness uses one shared 10-second observation budget, including Shell/URI and
fast-exiting handoff launchers. Once dispatch is accepted or its outcome is unknown, no
other candidate is launched and no process is killed. `app_status` can resume observation
for the same attempt without dispatch. A validated missing-file or missing-handler rejection
may use at most one alternate specification.

Window titles are only supporting hints. A window needs a matching executable image
path or verified package identity; an unavailable image lookup leaves it unconfirmed.
Browser and PWA windows sharing a process cannot be distinguished by process name
and tab title, so ambiguous cases remain unconfirmed. A reused HWND/PID is checked
again immediately before focus. `app_status` observes only: `window_found` is not
foreground readiness, and `dispatch_accepted` remains `null` for an unknown outcome.
Only dispatched attempts with saved observation state have queryable IDs.

Launch-spec deduplication includes kind, full normalized target, arguments, and working
directory. Different installations, wrappers, or argument sets are not collapsed by stem.

Only exact direct-process dispatcher identities can be recorded as LCU-owned in
`%TEMP%\LiteComputerUse\owned-processes.json`. Shell, shortcut, URI, broker, and
same-name-only observations remain unowned. Later cleanup requires live ledger evidence
plus PID, creation time, image, session, and window checks. Lookup errors fail closed and
the ledger never authorizes process-name-wide termination.
Shell/URI/shortcut/packaged activation handles and PIDs are observations, never
process ownership. Old ledger version 1 records are ignored because their dispatch
backend cannot be established.

### Real Windows Smoke Test Suite
Launches a live Tkinter GUI fixture with known button and canvas targets, captures screenshots across presets, resolves coordinates, tests hits, drags, and batch actions:
```powershell
py -3.13 tests\run_smoke_tests.py
```

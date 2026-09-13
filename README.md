# Lite Computer Use

Lite Computer Use is a lightweight Windows computer-use skill for host agents such as Antigravity, Gemini CLI, Claude Code, and Codex CLI. The host model interprets natural-language requests and screenshots; the bundled Python layer executes only explicit mouse, keyboard, window, app, file, URL, screenshot, and clipboard primitives.

The project deliberately has no DOM integration, Playwright, Selenium, OCR engine, accessibility-tree crawler, app-specific automation framework, autonomous agent loop, scheduler, or background workflow engine.

## What changed in v1.4

v1.4 fixes the execution path failures that caused agents to guess folders or repeat the same launch:

- File/folder/reveal paths now require an absolute target and distinguish empty, relative, missing, inaccessible, wrong-kind, and missing-association failures.
- Direct file, folder, URL, and Explorer actions use a shell-only backend without loading PyAutoGUI, Pillow, screenshot, clipboard, or window modules.
- Desktop, Documents, and Downloads come from the Windows Known Folder API, with fallback provenance reported explicitly.
- Configured app launch falls back to the installed-app index only after a definite not-found failure; access denial or an accepted dispatch never fans out.
- Standalone and sequence window commands share aliases, support `hwnd`/PID verification, and targeted input refuses to type until the exact target is foreground.
- File/folder searches have root, depth, visited-entry, time, and generated-directory budgets and report incomplete results.
- Sequence JSON can come from inline JSON, an absolute UTF-8 file, or stdin. Ordinary OS errors preserve partial completion.
- CLI argument errors are JSON, `doctor` identifies the actual runtime, and successful shell dispatch is no longer described as completed document/page loading.

The main rule is: **screenshot is fallback, not default**. Token savings come from fewer images, smaller visual scope, fewer model/tool turns, and deterministic actions—not from guessing at image compression ratios.

## Requirements

- Windows 11
- Python 3.11 or later; Python 3.13 is recommended
- An interactive desktop session
- A host agent with vision support for visually guided tasks

Check the Python installations registered with the Windows launcher:

```powershell
py -0p
py -3.13 --version
```

## Install

Clone the repository and install its dependencies into the global Python 3.13 installation. A virtual environment is not required for the intended Antigravity setup.

```powershell
git clone https://github.com/cjftya/lite-computer-use.git
cd lite-computer-use
py -3.13 -m pip install --upgrade pip
py -3.13 -m pip install -r requirements.txt
```

Resolve the runtime once and verify it without moving the pointer or opening an app:

```powershell
$LcuRoot = (Resolve-Path .).Path
$Lcu = Join-Path $LcuRoot "scripts\lcu_tools.py"
py -3.13 "$Lcu" doctor
py -3.13 "$Lcu" list_apps
```

Expected shape:

```json
{"ok":true,"action":"list_apps","result":{"apps":["chrome","Discord"],"configured":[{"name":"chrome","configured":true,"installedVerified":false}],"indexed":[{"name":"Discord","source":"app-paths","process":"discord.exe"}],"registeredCount":19,"indexedCount":42,"cacheRefreshed":true},"meta":{"durationMs":18.234,"requestId":"..."}}
```

Every invocation prints exactly one JSON object. Expected failures exit with code `2`; unexpected failures exit with code `3`.

## Install as an Antigravity global skill

Place the complete repository runtime at:

```text
C:\Users\<USER>\.gemini\antigravity\skills\lite-computer-use\
├─ SKILL.md
├─ scripts\
├─ config\
├─ docs\
├─ tests\
├─ README.md
└─ requirements.txt
```

Copy the root `SKILL.md`, `scripts`, `config`, and supporting files together. Do not copy only `.agents\skills\lite-computer-use\SKILL.md`; that file is a repository adapter and does not contain the runtime.

Fully restart Antigravity CLI after installing or updating the skill. Then use natural-language requests such as:

```text
계산기 열어서 100+400 해줘.
크롬 열고 네이버 들어가줘.
메모장 열고 "테스트 성공"이라고 입력해줘.
다운로드 폴더에서 계약서 PDF 찾아서 열어줘.
그림판 열어서 네모 하나 그려줘.
크롬을 왼쪽에 놓고 메모장을 오른쪽에 놓아줘.
```

The checked-in adapters also support repository-scoped discovery:

| Host | Workspace skill path |
|---|---|
| Codex CLI / Gemini CLI | `.agents/skills/lite-computer-use/SKILL.md` |
| Claude Code | `.claude/skills/lite-computer-use/SKILL.md` |

## Primitive examples

Always invoke the script with its resolved absolute path so a host's current working directory cannot select a different script or config.

```powershell
$LcuRoot = (Resolve-Path "C:\Users\<USER>\.gemini\antigravity\skills\lite-computer-use").Path
$Lcu = Join-Path $LcuRoot "scripts\lcu_tools.py"
```

```powershell
# Observe
py -3.13 "$Lcu" screenshot
py -3.13 "$Lcu" screenshot --active-window --scale 0.5
py -3.13 "$Lcu" screenshot --region 500 300 800 600
py -3.13 "$Lcu" get_active_window
py -3.13 "$Lcu" list_windows
py -3.13 "$Lcu" get_mouse_position

# Mouse and keyboard
py -3.13 "$Lcu" move_mouse 500 400
py -3.13 "$Lcu" click 500 400 --button right
py -3.13 "$Lcu" double_click 500 400
py -3.13 "$Lcu" drag 100 100 500 500 --duration 0.7
py -3.13 "$Lcu" scroll -5
py -3.13 "$Lcu" type_text "OpenAI 테스트" --target "메모장"
py -3.13 "$Lcu" press_key TAB --count 4 --target "메모장"
py -3.13 "$Lcu" hotkey CTRL L --target "크롬"

# Window control and bounded waiting
py -3.13 "$Lcu" focus_window "Chrome"
py -3.13 "$Lcu" set_window_state "Chrome" maximize
py -3.13 "$Lcu" set_window_bounds "Chrome" 0 0 960 1080
py -3.13 "$Lcu" wait_for_window "Calculator" --state active --timeout 10
py -3.13 "$Lcu" close_window "Notepad"

# Apps, web, files, and folders
py -3.13 "$Lcu" list_apps
py -3.13 "$Lcu" list_apps --refresh
py -3.13 "$Lcu" launch_app chrome
py -3.13 "$Lcu" open_url "https://www.naver.com"
py -3.13 "$Lcu" known_folder downloads
py -3.13 "$Lcu" find_file "contract" --root "C:\Users\me\Downloads" --limit 10
py -3.13 "$Lcu" find_folder "project" --root "C:\Users\me\Documents"
py -3.13 "$Lcu" open_file "C:\Users\me\Downloads\contract.pdf"
py -3.13 "$Lcu" open_folder "C:\Users\me\Downloads"
py -3.13 "$Lcu" reveal_file "C:\Users\me\Downloads\contract.pdf"

# Bounded deterministic sequence
py -3.13 "$Lcu" sequence --json '[{"action":"focus_window","title":"Chrome"},{"action":"hotkey","keys":["CTRL","L"],"target":"Chrome"},{"action":"type_text","text":"OpenAI","target":"Chrome"},{"action":"press_key","key":"ENTER","target":"Chrome"}]'
```

`reveal_file` selects a file in Explorer without opening it. `close_window` posts a normal close request; it never force-kills the process, so the application's own unsaved-document dialog remains in control.

For coordinates obtained from an active-window screenshot, use the same cropped coordinate space:

```powershell
py -3.13 "$Lcu" click 420 260 --relative-to active-window
py -3.13 "$Lcu" drag 100 100 500 500 --relative-to active-window
```

Negative screen coordinates are valid on monitors located left of or above the primary monitor. Region screenshots, pointer actions, and window bounds are checked against the full Windows virtual desktop. Move the pointer to the upper-left fail-safe corner to abort a PyAutoGUI mouse or keyboard action.

## Fast Path

Use the cheapest reliable route:

| Request | Preferred primitive | Screenshot |
|---|---|---|
| Launch Calculator, Chrome, or Notepad | `launch_app` | No |
| Focus an open window | `focus_window` | No |
| Open a known website | `open_url` | No |
| Find or open a file | `find_file` / `open_file` | No |
| Focus the address bar or open Print | `hotkey CTRL L` / `hotkey CTRL P` | Normally no |
| Type text or press Enter/Escape | `type_text` / `press_key` | No |
| Find a visible button or unknown popup | screenshot | Yes |
| Interpret a visual result | screenshot | Yes |

For example, “네이버에서 OpenAI 검색해줘” can use a known HTTP(S) search URL directly. If a specific search result must then be selected, switch to the Vision Path for that visual choice. Lite Computer Use never inspects the page DOM.

## Verification policy

- **Tier 0 — tool result:** a successful return is enough for a simple, low-risk deterministic action.
- **Tier 1 — OS state:** use `get_active_window`, `list_windows`, or `wait_for_window` when state confirmation matters.
- **Tier 2 — visual:** capture a screenshot when the result depends on screen meaning, a coordinate action may branch, or a popup/error is plausible.

This removes patterns such as screenshot → `Ctrl+L` → screenshot → type → screenshot → Enter → screenshot. The deterministic part should be one sequence, followed by at most one screenshot if the resulting page must be interpreted.

## Vision Path and screenshots

Capture in this order:

1. `screenshot --active-window --scale 0.5` for a broad preview.
2. Primary-screen `screenshot --scale 0.5` if the target is outside the active window.
3. `screenshot --all-screens --scale 0.5` only when the monitor is unknown.
4. `screenshot --region X Y WIDTH HEIGHT --scale 1` when the target needs detail.

Use the smallest scope that still contains the target. After a visual click, capture again only if the outcome is ambiguous, can branch, or is important to verify.

`--scale` accepts `0.25` through `1.0` and returns `width`, `height`, `originalWidth`, `originalHeight`, and `scale`. Downscaling uses bilinear resampling. Do not pass raw coordinates from a scaled image to an input action; take a full-scale region capture first so the host does not need repeated coordinate conversion.

Active-window image coordinates start at `(0, 0)`. Keep the same window active and pass `--relative-to active-window` to `click`, `double_click`, `move_mouse`, or `drag`. `--region X Y WIDTH HEIGHT` instead uses virtual-desktop screen coordinates and cannot be combined with `--active-window` or `--all-screens`.

## Deterministic sequence

`sequence` reduces model/tool round trips and Python startup overhead for a short chain whose steps are known in advance.

Allowed actions:

- `launch_app`
- `wait_for_window`
- `focus_window`
- `move_mouse`
- `click` (single click only)
- `hotkey`
- `press_key`
- `type_text`
- `scroll`

Rules:

- The JSON value must be an array containing 1–8 action objects.
- Supply exactly one of inline `--json`, absolute UTF-8 `--file`, or `--stdin`.
- Every step and field is validated before execution begins.
- Steps run in order and stop on the first LCU error.
- There are no conditions, branches, loops, retries, screenshots, clipboard or file actions, drags, double-clicks, or arbitrary Python/shell execution.
- A failure exits with code `2`; `result.completed`, `result.failedIndex`, `result.failedAction`, `result.partialEffectPossible`, and ordered prior results describe partial execution. A failed input/click/launch step may have a partial side effect even when `completed` is zero.

Example success:

```json
{"ok":true,"action":"sequence","result":{"completed":2,"results":[{"index":0,"action":"hotkey","result":{"keys":["ctrl","l"]}},{"index":1,"action":"type_text","result":{"length":6,"method":"unicode-sendinput"}}]},"meta":{"durationMs":95.2}}
```

Do not use a sequence if a later step depends on interpreting the earlier step's screen result. Stop the sequence at that boundary and use the Vision Path.

## How it works

```text
Natural-language request
→ direct primitive or compact state query
→ optional bounded sequence
→ Windows GUI
→ vision only when meaning or coordinates require it
```

The Python layer is not an autonomous agent. `wait_for_window` is only bounded polling of one window state, with a maximum timeout of 30 seconds. It does not reason, retry a goal, or continue in the background.

## Text input optimization

`type_text` uses Windows Unicode `SendInput`, so Korean and other Unicode text do not require replacing the clipboard. The default interval is `0`; zero-delay text is sent in bounded batches of 128 UTF-16 units. Emoji surrogate pairs preserve their original UTF-16 order. Newlines and tabs remain explicit Enter and Tab key events.

Use `--interval` only for an application that demonstrably drops fast input:

```powershell
py -3.13 "$Lcu" type_text "한글 입력 테스트" --target "메모장" --interval 0.01
```

## App configuration

Trusted app aliases and launch commands live in `config/apps.yaml`. They have exact-match priority. When no configured alias matches, `launch_app` checks an installed-app index built from Start Menu `.lnk` files and 32/64-bit current-user/machine Windows App Paths registry views. If a configured command fails with a definite not-found error, its canonical name, aliases, and executable basename may resolve the same app in the index once. Access denial, ambiguity, or an already accepted OS request never triggers candidate fan-out. Exact indexed names win; a partial name or process match must be unique or returns `ambiguous_app`.

```yaml
apps:
  my-app:
    aliases: [my app, 사내 프로그램]
    commands: [MyApp.exe]
```

The index is cached at `%LOCALAPPDATA%\LiteComputerUse\cache\apps.json` for 24 hours. `list_apps` uses the cache; run `list_apps --refresh` after installing, removing, or renaming apps. Discovery happens only during a command—there is no watcher, daemon, or background refresh. Public results and logs omit executable and shortcut paths, and there is still no arbitrary command or shell-execution primitive.

Store/protocol apps can be launched when a trusted protocol such as `ms-settings:` is configured or when Windows exposes a usable Start Menu shortcut. Packaged apps with neither a shortcut nor an App Paths entry are outside automatic discovery. Multiple side-by-side installations remain ambiguous unless the configured alias identifies one exact command.

## Window resolution

`list_windows` returns visible titled windows with `hwnd`, `pid`, and a lowercase process basename such as `chrome.exe`; process lookup failures return `null` without aborting enumeration. Full executable paths are never returned. Window actions resolve in this order: exact title, exact configured app/process alias, partial title, then partial process. An active match may break a low-impact focus/wait tie; `close_window` rejects ambiguity. Follow-up actions can use `--hwnd` and optional `--pid`; a stale handle or PID mismatch is never replaced silently.

`wait_for_window --state present` confirms presence only. Use `focus_window`, `--target`, or `--hwnd` before keyboard input. Targeted input waits for the requested handle to become the real foreground window and sends nothing when focus verification fails.

`os.startfile`/ShellExecute-style launches do not return a reliable PID, and a single-instance app may activate an existing process. A successful launch therefore remains `dispatch_accepted`/`unverified`; use the resolver and returned window handle for explicit follow-up verification.

## Files and folders

`known_folder` resolves Desktop, Documents, and Downloads through the Windows Known Folder API and reports whether a fallback was used. This handles localized and redirected folders without guessing a profile or OneDrive path.

`find_file` and `find_folder` perform case-insensitive partial-name searches. With no `--root`, they use the existing known folders; with an explicit absolute root they never add another location. Defaults are 3 seconds, depth 6, 20,000 visited entries, and common generated-directory exclusions such as `.git`, `.venv`, `node_modules`, and `build`. Results include roots, elapsed time, visited count, `truncated`/`incomplete`, and stop reason. Modification ordering applies only to the collected budget. UNC traversal is cooperative and cannot guarantee a hard timeout while an individual network filesystem call is blocked.

`open_file` opens an exact existing normal document through its Windows file association. It rejects executables, installers, scripts, shortcuts, registry files, disk images, and other launch-capable extensions. `open_folder` validates and opens a directory. `reveal_file` opens Explorer with an existing file selected without launching that file. There are no delete, rename, move, copy, create, or overwrite primitives.

## Browser use

`open_url` accepts only absolute `http://` or `https://` URLs and sends them to the default browser. Prefer direct known URLs and encoded search URLs because they need no image or DOM inspection. Use `hotkey CTRL L` plus deterministic text input when working in an already open browser. Use a screenshot only when the next step depends on visible page content.

Lite Computer Use does not inspect DOM nodes, control developer tools, install a browser extension, bypass site security, or infer that a loaded URL means the page's visual task succeeded.

## Runtime logs and screenshots

Screenshots are stored under `%TEMP%\LiteComputerUse\screenshots` and files older than 24 hours are cleaned when a new screenshot is taken.

The installed-app cache is stored under `%LOCALAPPDATA%\LiteComputerUse\cache` and is rebuilt after 24 hours or with `list_apps --refresh`.

Redacted action logs are stored at `%LOCALAPPDATA%\LiteComputerUse\logs\actions.jsonl`. Each entry records UTC time, action name, success, minimal redacted metadata, and non-negative `durationMs`. Typed text, clipboard text, complete paths, complete URLs, complete window titles, and screenshot pixels are never logged. Sequence logs store only the JSON payload length.

`durationMs` measures local execution from argument-parser construction through the result and includes action-lock acquisition for mutating/UI actions. Read-only diagnostics and searches do not take that UI lock. Timing excludes Python process startup, is not the model's end-to-end latency, and does not estimate host or vision tokens. `requestId` links the redacted response and diagnostic log without storing a path, URL, title, or typed text.

## Safety

Within the user's request, the host may capture the screen, inspect or focus windows, launch configured or uniquely indexed installed apps, open normal documents or known websites, search, navigate menus, scroll, move or resize windows, perform harmless drags, open folders, and reveal files.

The host must ask immediately before a final action that sends or submits data; makes a purchase, payment, booking, or agreement; deletes data; overwrites a file; installs software; or changes security/system settings.

Password or recovery-code entry, MFA entry, UAC approval, CAPTCHA bypass, security-warning bypass, secret extraction, arbitrary shell execution, process termination, and registry modification are prohibited.

## Emergency stop

PyAutoGUI's fail-safe remains enabled. Move the pointer to the upper-left corner of the desktop to abort a PyAutoGUI-driven mouse or keyboard action. Atomic `drag` still attempts `mouseUp` during failure cleanup so the button is not left logically held down.

## Troubleshooting

### `typing.Self` import error or `unsupported_python`

The wrong Python version is running. Lite Computer Use requires Python 3.11 or later.

```powershell
py -0p
py -3.13 --version
```

Use `py -3.13`, not an unqualified `python`, when multiple versions are installed.

### `ModuleNotFoundError`

Install dependencies into the same Python 3.13 runtime used for commands:

```powershell
py -3.13 -m pip install -r requirements.txt
```

### `app_not_found` or `ambiguous_app`

Run `list_apps --refresh`. For ambiguity, use the exact listed app name; for a missing app, add a trusted exact alias and command to `config/apps.yaml`. There is intentionally no arbitrary executable or shell-command argument.

### `window_not_found` or `ambiguous_window`

Run `list_windows`. For a missing window, launch it first; for an ambiguous result, use a longer unique title. The resolver never chooses randomly.

### `coordinate_out_of_bounds`

Refresh the relevant bounds with `get_active_window` or `list_windows`. If coordinates came from a cropped screenshot, pass `--relative-to active-window`. Negative coordinates are valid on monitors left of or above the primary display.

### `clipboard_busy`

Another application currently owns the clipboard. Wait briefly and retry once. Prefer `type_text` when clipboard transfer is not required.

### Window focus fails

Confirm the window is visible in the current interactive desktop session. Services, locked sessions, UAC desktops, and headless execution are unsupported.

### Korean or emoji input is incomplete

Confirm Python 3.11+ and current dependencies, then retry the affected app with `--interval 0.01`. Record the app name and result in the Windows smoke test because some applications process Unicode input differently.

### Multi-monitor coordinates do not match

Confirm Windows display arrangement and scaling, then compare `list_windows` bounds with `screenshot --all-screens`. Do not assume the primary monitor begins at the virtual desktop's top-left corner.

### Antigravity cannot find the skill

Confirm that the complete runtime is under:

```text
C:\Users\<USER>\.gemini\antigravity\skills\lite-computer-use\
```

Then fully exit and restart Antigravity CLI. Test the runtime directly first:

```powershell
py -3.13 "$Lcu" doctor
py -3.13 "$Lcu" list_apps
```

## Tests

```powershell
py -3.13 -m unittest discover -s tests -v
py -3.13 -m compileall scripts tests
```

Real mouse, keyboard, screenshot, Explorer, and window behavior must also be checked on an interactive Windows desktop. Follow [`docs/windows-smoke-tests.md`](docs/windows-smoke-tests.md).

## Performance benchmark

Use the repeatable L1–L7 procedure and record template in [`docs/performance.md`](docs/performance.md). Compare success rate first, then screenshot pixels, vision use, CLI invocations, retries, `meta.durationMs`, and end-to-end time. Do not accept a faster result that lowers reliability or weakens the safety boundary.

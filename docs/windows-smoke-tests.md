# Windows smoke tests

Run these checks on a non-production Windows 11 desktop with no sensitive data visible. Use global Python 3.13, keep the pointer away from the upper-left fail-safe corner unless testing abort behavior, and record the display scale and monitor layout.

Start with automated checks:

```powershell
py -3.13 -m unittest discover -s tests -v
py -3.13 -m compileall scripts tests
$LcuRoot = (Resolve-Path .).Path
$Lcu = Join-Path $LcuRoot "scripts\lcu_tools.py"
py -3.13 "$Lcu" doctor
py -3.13 "$Lcu" list_apps
py -3.13 "$Lcu" list_apps --refresh
```

Record each item as pass, fail, or blocked.

## Mouse and keyboard

1. Open Paint and run `move_mouse`; confirm the pointer moves without clicking.
2. Run left, right, and middle `click` on harmless targets; confirm the correct button is used.
3. Run `click --relative-to active-window`; confirm cropped-image coordinates map correctly.
4. Run `double_click` on a harmless test file.
5. Draw a line and a four-edge rectangle in Paint with `drag`.
6. Abort a drag by moving to the fail-safe corner; confirm the mouse button is released afterward.
7. Drag a slider and a scrollbar; confirm duration and endpoints behave predictably.
8. Confirm positive and negative `scroll` values move in opposite directions.
9. Type `OpenAI test` and `한글 입력 테스트` in Notepad.
10. Run `press_key TAB --count 4`, `press_key ESC`, and `hotkey CTRL L` in suitable apps.
11. Run `get_mouse_position` and compare the returned coordinate with the visible pointer.
12. Type at least 500 mixed Korean/ASCII characters with the default zero interval; confirm order and completeness.
13. Type emoji containing surrogate pairs; confirm no missing or reordered characters.
14. Repeat the affected input with `--interval 0.01` if an app cannot accept the zero-delay batch.

## Windows and waiting

1. Launch Notepad and confirm `list_windows` includes accurate `active`, `minimized`, `bounds`, `pid`, and process-basename fields without a full executable path.
2. Open two similarly titled windows; confirm an ambiguous query returns `ambiguous_window` rather than selecting one.
3. Maximize, restore, minimize, and restore Notepad with `set_window_state`.
4. Move and resize Notepad with `set_window_bounds`.
5. On a second monitor left of the primary one, use negative X coordinates for `set_window_bounds`.
6. Run `wait_for_window "Notepad" --state present` and `--state active`.
7. Close Notepad and run `wait_for_window "Notepad" --state gone`.
8. Wait for a missing test title with a short timeout; confirm `window_wait_timeout`.
9. Modify an unsaved Notepad document and run `close_window`; confirm the normal save dialog appears and the process is not force-killed.
10. Focus a window whose title omits its app name using the configured app/process alias.
11. Inspect a protected process and confirm lookup failure returns `process:null` without dropping other windows.

## Screenshots

1. Confirm full, active-window, and all-screen captures return readable PNGs with correct dimensions and bounds.
2. Capture a small popup with `screenshot --region X Y WIDTH HEIGHT`; verify the PNG dimensions equal the requested width and height.
3. Capture a region on a monitor with negative coordinates.
4. Confirm zero-sized and out-of-desktop regions are rejected.
5. Confirm `--region` combined with `--active-window` or `--all-screens` is rejected.
6. Capture the same screen with `--scale 1`, `0.5`, and `0.25`; confirm returned original/output dimensions and bilinear readability.
7. Use a 0.5 preview to identify a target, then a scale-1 region for detail; do not reuse raw scaled-image coordinates.
8. Confirm scales below 0.25, above 1.0, and non-finite values return `invalid_scale`.

## Apps, web, files, and folders

1. Launch Calculator, Notepad, Paint, and Chrome from a closed state where installed.
2. Open `https://www.naver.com` in the default browser.
3. Find a uniquely named PDF under Downloads and open it.
4. Open Downloads with `open_folder`.
5. Use `reveal_file` on the test PDF; confirm Explorer opens with the file selected but the file does not launch.
6. Confirm a missing folder and a file passed to `open_folder` return structured errors.
7. Confirm an executable, script, shortcut, installer, or disk image passed to `open_file` is rejected.
8. Confirm a non-HTTP URL such as `file:///...` is rejected.
9. Launch a uniquely named installed app that is absent from `config/apps.yaml`; confirm the source is `start-menu` or `app-paths`.
10. Confirm a configured alias wins over the installed-app index.
11. Confirm a partial installed-app name with multiple matches returns `ambiguous_app`.
12. Run `list_apps` twice and confirm the second call reuses the cache; then run `--refresh` and confirm `cacheRefreshed:true`.
13. From two unrelated working directories, invoke the absolute `$Lcu` path and open the same absolute test file; confirm the same target and zero retries.
14. Confirm empty, ordinary relative, `C:relative`, `\root-relative`, and unresolved `%VARIABLE%` paths fail before OS dispatch.
15. Run `known_folder desktop`, `documents`, and `downloads`; compare each result to Explorer properties and record `source`/`fallbackUsed`.
16. Use `find_folder`, an explicit `--root`, and low `--max-visited`; confirm no other root is added and an interrupted scan reports `incomplete:true`.
17. Verify file-association-missing and access-denied errors stay distinct from file-not-found and trigger no identical retry.
18. Monitor imported modules or cold timing and confirm `open_file`, `open_folder`, `reveal_file`, and `open_url` do not load PyAutoGUI, Pillow, screenshot, clipboard, or window modules.

## v1.4 target and retry checks

1. Run standalone `focus_window "크롬"` and sequence `focus_window` with the Korean alias; confirm both resolve the configured Chrome process.
2. Use `list_windows`, then focus/type with its `hwnd` and PID. Close the window and reuse the handle; confirm `stale_window_handle` with no retargeting.
3. Supply the wrong PID for a valid handle; confirm `window_pid_mismatch` and no input.
4. Arrange for focus stealing to be rejected; confirm `window_focus_unverified` and zero injected keys/text.
5. Open two similar Notepad windows and run `close_window` with an ambiguous title; confirm neither receives a close request.
6. Break a configured executable alias while leaving the real indexed app installed; confirm one same-app fallback. Repeat with access denied; confirm no fallback.
7. Use a removed cached shortcut; confirm no more than one refresh and no whole-command replay.
8. Trigger an ordinary `OSError` on the second harmless sequence step; confirm prior results, failed index/action, cause, and partial-effect state remain in JSON and no later step runs.
9. Pass the same Korean sequence through `--json`, absolute UTF-8 `--file`, and `--stdin` in PowerShell.
10. Record OS dispatch acceptance separately from visible document/page completion; do not mark a load verified without an explicit state/visual check.

## Antigravity scenarios

After installing the complete skill under `C:\Users\<USER>\.gemini\antigravity\skills\lite-computer-use`, fully restart Antigravity CLI and run:

1. "계산기 열어서 100+400 해줘."
2. "크롬을 열고 준비되면 네이버로 이동해줘."
3. "그림판을 열어서 네모 하나 그려줘."
4. "그림판에 간단한 집 모양을 그려줘."
5. "크롬을 화면 왼쪽 절반에 놓고 메모장을 오른쪽 절반에 놓아줘."
6. "다운로드 폴더 열어줘."
7. "다운로드에 있는 test.pdf 위치 보여줘."
8. "이 아이콘을 우클릭해줘."
9. "현재 화면의 작은 팝업만 자세히 확인해줘."
10. "메모장을 닫아줘."

## Fast Path and token checks

For each request, record CLI invocation count, screenshot count, screenshot scope, retries, `meta.durationMs`, and end-to-end time.

1. "메모장 열어줘": `launch_app`, zero screenshots.
2. "계산기 열어줘": `launch_app`, zero screenshots.
3. "네이버 열어줘": `open_url`, zero screenshots.
4. "열려 있는 Chrome으로 이동해줘": `focus_window`, or `list_windows` then focus; zero screenshots.
5. "주소창으로 이동해줘": `hotkey CTRL L`, zero screenshots.
6. "인쇄 화면까지 열어줘": deterministic `hotkey CTRL P`; no screenshot unless the dialog must be visually verified.
7. "현재 화면의 확인 버튼을 눌러줘": one active-window screenshot before the visual click; recapture only if the result is ambiguous or important.
8. "현재 팝업이 무슨 내용인지 알려줘": active-window screenshot before primary or all-screen fallback.

Fail the check if the host takes a screenshot before and after every deterministic action, uses a full desktop image while the active window contains the target, or claims visual success without inspecting a needed image.

## Sequence checks

1. Run address-bar focus → text → Enter as one sequence and confirm ordered results.
2. Run a sequence with exactly eight allowed steps; confirm success.
3. Confirm nine steps, malformed JSON, unknown fields, and `screenshot` are rejected before any step runs.
4. Cause the second step to fail harmlessly; confirm `completed=1`, `failedIndex=1`, and no later action runs.
5. Confirm typed text and window titles do not appear in `%LOCALAPPDATA%\LiteComputerUse\logs\actions.jsonl`.
6. Confirm every successful and failed response contains non-negative `meta.durationMs`.
7. Run launch → bounded wait → focus/move/click → keyboard actions in one sequence and confirm ordered results.
8. Confirm `drag`, `double_click`, screenshots, file/clipboard actions, and retry/loop fields remain disallowed.

For visually guided scenarios, use a fresh screenshot only when the result is ambiguous, can branch, or materially requires verification. Stop after one reasonable alternate-method retry rather than repeatedly guessing coordinates. Do not approve a send, submit, purchase, delete, overwrite, install, UAC, or security-warning action during smoke testing.

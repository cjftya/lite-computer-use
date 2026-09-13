# Windows smoke tests

Run these checks on a non-production Windows 11 desktop with no sensitive data visible. Use global Python 3.13, keep the pointer away from the upper-left fail-safe corner unless testing abort behavior, and record the display scale and monitor layout.

Start with automated checks:

```powershell
py -3.13 -m unittest discover -s tests -v
py -3.13 -m compileall scripts tests
py -3.13 scripts/lcu_tools.py list_apps
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

## Windows and waiting

1. Launch Notepad and confirm `list_windows` includes accurate `active`, `minimized`, and `bounds` fields.
2. Open two similarly titled windows; confirm an ambiguous query returns `ambiguous_window` rather than selecting one.
3. Maximize, restore, minimize, and restore Notepad with `set_window_state`.
4. Move and resize Notepad with `set_window_bounds`.
5. On a second monitor left of the primary one, use negative X coordinates for `set_window_bounds`.
6. Run `wait_for_window "Notepad" --state present` and `--state active`.
7. Close Notepad and run `wait_for_window "Notepad" --state gone`.
8. Wait for a missing test title with a short timeout; confirm `window_wait_timeout`.
9. Modify an unsaved Notepad document and run `close_window`; confirm the normal save dialog appears and the process is not force-killed.

## Screenshots

1. Confirm full, active-window, and all-screen captures return readable PNGs with correct dimensions and bounds.
2. Capture a small popup with `screenshot --region X Y WIDTH HEIGHT`; verify the PNG dimensions equal the requested width and height.
3. Capture a region on a monitor with negative coordinates.
4. Confirm zero-sized and out-of-desktop regions are rejected.
5. Confirm `--region` combined with `--active-window` or `--all-screens` is rejected.

## Apps, web, files, and folders

1. Launch Calculator, Notepad, Paint, and Chrome from a closed state where installed.
2. Open `https://www.naver.com` in the default browser.
3. Find a uniquely named PDF under Downloads and open it.
4. Open Downloads with `open_folder`.
5. Use `reveal_file` on the test PDF; confirm Explorer opens with the file selected but the file does not launch.
6. Confirm a missing folder and a file passed to `open_folder` return structured errors.
7. Confirm an executable, script, shortcut, installer, or disk image passed to `open_file` is rejected.
8. Confirm a non-HTTP URL such as `file:///...` is rejected.

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

For visually guided scenarios, confirm the host follows Observe → Act → Verify, takes a fresh screenshot after a state change, and stops after one reasonable alternate-method retry rather than repeatedly guessing coordinates. Do not approve a send, submit, purchase, delete, overwrite, install, UAC, or security-warning action during smoke testing.

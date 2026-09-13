# Windows smoke tests

Run these tests on a non-production Windows desktop with no sensitive data visible. Keep the pointer away from the upper-left fail-safe corner unless you intend to abort.

Record each result as pass, fail, or blocked, along with the Windows display scale and monitor count.

## Primitive checks

1. `screenshot` returns a readable PNG with dimensions matching the captured desktop.
2. `screenshot --active-window` returns a cropped image and accurate non-zero bounds.
3. `click` selects a harmless desktop target at the expected coordinate.
4. `click --relative-to active-window` maps a cropped-image coordinate correctly.
5. `double_click` opens a harmless test file.
6. Positive and negative `scroll` values move in opposite directions.
7. `type_text` enters both `OpenAI test` and `한글 입력 테스트` correctly in Notepad.
8. `press_key ESC` and `hotkey CTRL L` work in a suitable test app.
9. Moving the pointer to the upper-left corner aborts a PyAutoGUI-driven action.

## App, file, and window checks

1. Launch Notepad from a closed state.
2. List windows and confirm the active window marker is accurate.
3. Minimize Notepad, then restore and focus it by title.
4. Open `https://www.naver.com` in the default browser.
5. Find a uniquely named PDF under Downloads and open it.
6. Confirm that opening an executable, script, shortcut, installer, or disk image through `open_file` is rejected.
7. Confirm that a non-HTTP URL such as `file:///...` is rejected.
8. Confirm that an ambiguous window title returns candidates instead of choosing one.

## Agent scenarios

Run each scenario at least five times with Claude Code, Gemini CLI, and Codex CLI:

1. "메모장 열어줘."
2. "이미 열려 있는 크롬으로 이동해줘."
3. "네이버 열어줘."
4. "다운로드 폴더에서 최근 PDF 열어줘."
5. "메모장에 테스트라고 입력해줘."
6. "현재 화면을 보고 확인 버튼을 눌러줘."
7. "크롬에서 네이버를 열고 OpenAI를 검색해줘."
8. "이 PDF를 열고 인쇄 화면까지 띄워줘."

For visually guided scenarios, verify that the agent observes again after a state-changing action and stops after one alternate-method retry rather than repeating clicks.

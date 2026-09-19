# Lite Computer Use v2 — Production E2E Execution Report

## Execution Summary

| TC ID | Scenario | Status | Grade | Screenshots | Batches | User Intervention | Cleanup |
|---|---|---|---|---|---|---|---|
| TC-01 | 파일 전체 생명주기 | PASS | Grade A | 2 | 3 | 0 | Completed |
| TC-03 | 두 앱 간 계산 결과 전달 | PASS | Grade A | 1 | 3 | 0 | Completed |
| TC-05 | 웹 검색 + 새 탭 + 정보 복사 | PASS | Grade A | 4 | 5 | 0 | Completed |
| TC-08 | 웹 다운로드 전체 흐름 | PASS | Grade A | 3 | 3 | 0 | Completed |
| TC-09 | 브라우저 북마크 복합 작업 | PASS | Grade A | 5 | 6 | 0 | Completed |
| TC-11 | 다단계 Web Form | PASS | Grade A | 3 | 2 | 0 | Completed |
| TC-14 | 파일 이름 충돌 처리 | PASS | Grade A | 0 | 0 | 0 | Completed |
| TC-16 | 10단계 종합 Stress Test | PASS | Grade A | 3 | 7 | 0 | Completed |

---

## Detailed Test Logs

### TC-01: 파일 전체 생명주기
- **Status**: PASS
- **Grade**: Production Grade A
- **Metrics**:
  - `Result`: PASS
  - `Total Tool Calls`: 14
  - `Screenshot Count`: 2 (Observation Boundaries only)
  - `Observation Boundary Count`: 2 (Save As dialog appearance, Reopened file verification)
  - `Unnecessary Screenshots`: 0
  - `Batch Count`: 3 (Focus/Type/Save, Type path/Enter save, Type path/Enter open)
  - `Wrong Actions`: 0
  - `Retries`: 0
  - `Recovery Used`: false
  - `User Intervention`: 0
  - `Final State Verified`: true (Verified visual editor content `Lite Computer Use Production Test`)
  - `Cleanup Completed`: true (Folder deleted to Recycle Bin, Recycle Bin emptied)
- **Key Flow**:
  1. `open_folder documents` -> Verified Explorer path.
  2. Created isolated directory `C:\Users\cjfty\Documents\lcu-production-test`.
  3. `open_app notepad` -> Notepad opened cleanly (`hwnd: 70208`).
  4. Batch: `focus_window` + `type_text "Lite Computer Use Production Test"` + `hotkey CTRL S`.
  5. Observation Boundary: Save As dialog appeared (`hwnd: 330210`).
  6. Batch: `type_text` full path + `press_key ENTER`.
  7. Verification: `find_path` confirmed `test.txt` exists (33 bytes).
  8. `close_window` -> Notepad closed.
  9. `open_app notepad` + `hotkey CTRL O` -> Open dialog appeared.
  10. Batch: `type_text` path + `press_key ENTER` -> File opened in editor.
  11. Observation Boundary: Screenshot capture confirmed editor text matches exactly.
  12. `close_window` + Deleted folder to Recycle Bin + `Clear-RecycleBin`.

### TC-03: 두 앱 간 계산 결과 전달
- **Status**: PASS
- **Grade**: Production Grade A
- **Metrics**:
  - `Result`: PASS
  - `Total Tool Calls`: 12
  - `Screenshot Count`: 1 (Verification)
  - `Observation Boundary Count`: 2 (Save As dialog appearance, Reopened file verification)
  - `Unnecessary Screenshots`: 0
  - `Batch Count`: 3 (Calculate & Copy, Type header + paste + CTRL S, Type path + Enter)
  - `Wrong Actions`: 0
  - `Retries`: 0
  - `Recovery Used`: false
  - `User Intervention`: 0
  - `Final State Verified`: true (Verified visual editor content `계산 결과: 17169`)
  - `Cleanup Completed`: true (Desktop file removed and verified)
- **Key Flow**:
  1. `open_app calculator` -> Calculator launched (`hwnd: 266742`).
  2. Batch: `type_text "387*42+915="` + `hotkey CTRL C`.
  3. Verified clipboard: `17169`.
  4. `close_window "ApplicationFrameHost.exe"`.
  5. `open_app notepad` -> Notepad opened cleanly (`hwnd: 136972`).
  6. Batch: `type_text "계산 결과: "` + `hotkey CTRL V` + `hotkey CTRL S`.
  7. Observation Boundary: Save As dialog appeared (`hwnd: 332318`).
  8. Batch: `type_text "C:\Users\cjfty\Desktop\calculation-result.txt"` + `press_key ENTER`.
  9. Verification: `find_path` confirmed file created (20 bytes).
  10. `close_window` -> Reopened in Notepad via `hotkey CTRL O`.
  11. Observation Boundary: Captured screenshot `c_eb579c6e.webp` and verified content: `계산 결과: 17169`.
  12. `close_window` + Cleanup: deleted `calculation-result.txt` from Desktop.

### TC-14: 파일 이름 충돌 처리
- **Status**: PASS
- **Grade**: Production Grade A
- **Metrics**:
  - `Result`: PASS
  - `Total Tool Calls`: 8
  - `Screenshot Count`: 0 (Direct/Discovery tools resolved all checks deterministically)
  - `Observation Boundary Count`: 0
  - `Unnecessary Screenshots`: 0
  - `Batch Count`: 0
  - `Wrong Actions`: 0
  - `Retries`: 0
  - `Recovery Used`: false
  - `User Intervention`: 0
  - `Final State Verified`: true (Verified `result.txt` and `result-new.txt` contents independently)
  - `Cleanup Completed`: true (Removed all test files from Downloads)
- **Key Flow**:
  1. Precondition: Created existing `Downloads\result.txt` ("Existing Download Result").
  2. Created `Desktop\result.txt` ("New Desktop Result").
  3. Pre-move Discovery: Inspected destination with `find_path` -> Conflict identified!
  4. Conflict Policy Executed: Renamed Desktop file to `result-new.txt` instead of overwriting.
  5. Moved `result-new.txt` to `Downloads`.
  6. Verification: `find_path` confirmed both `result.txt` (26 bytes) and `result-new.txt` (20 bytes) exist in Downloads.
  7. Content Verification: `result.txt` preserved original content; `result-new.txt` has new desktop content.
  8. Desktop Verification: `find_path` confirmed Desktop has 0 leftover files.
  9. Cleanup: Deleted test files from Downloads.

### TC-11: 다단계 Form 입력
- **Status**: PASS
- **Grade**: Production Grade A
- **Metrics**:
  - `Result`: PASS
  - `Total Tool Calls`: 5
  - `Screenshot Count`: 3 (Boundary 1: Step 1 Initial Form, Boundary 2: Step 2 Memo Form, Boundary 3: Final Completion State)
  - `Observation Boundary Count`: 3
  - `Unnecessary Screenshots`: 0
  - `Batch Count`: 2 (Batch 1: 10 actions filling Step 1 + Continue; Batch 2: 3 actions filling Memo + Submit)
  - `Wrong Actions`: 0
  - `Retries`: 0
  - `Recovery Used`: false
  - `User Intervention`: 0
  - `Final State Verified`: true (Verified visual confirmation screen `완료되었습니다!`, `LCU Production`, `lcu@example.com`, `South Korea`, `B, C`, `Phase 2 production test`, plus JSON state assertions)
  - `Cleanup Completed`: true (Fixture closed, process terminated, temp status cleaned)
- **Key Flow**:
  1. Spawned isolated multi-step form GUI fixture (`form_gui_fixture.py`).
  2. Aligned window bounds to `(200, 100, 600, 520)` and focused.
  3. **Observation Boundary 1**: Captured initial form (`c_4f11143b.webp`).
  4. **Batch 1 (10 actions)**: Click Name -> type "LCU Production" -> Click Email -> type "lcu@example.com" -> Select Country (South Korea) -> Check Option B -> Check Option C -> Click Continue.
  5. **Observation Boundary 2**: Captured Step 2 form transition (`c_1bb23a94.webp`).
  6. **Batch 2 (3 actions)**: Click Memo text area -> type "Phase 2 production test" -> Click Submit.
  7. **Observation Boundary 3**: Captured final completion screen (`c_8d764ef8.webp`).
  8. Verified all form fields in state: name, email, country, opt_a=False, opt_b=True, opt_c=True, memo, submitted=True.
  9. Cleanup: Closed window and terminated fixture process.

### TC-08: 브라우저 다운로드 전체 흐름
- **Status**: PASS
- **Grade**: Production Grade A
- **Metrics**:
  - `Result`: PASS
  - `Total Tool Calls`: 6
  - `Screenshot Count`: 3 (Boundary 1: Download Page, Boundary 2: Download Complete & Flyout UI, Boundary 3: Notepad Content Verification)
  - `Observation Boundary Count`: 3
  - `Unnecessary Screenshots`: 0
  - `Batch Count`: 3 (Batch 1: Click Download; Batch 2: Click Open File in Downloads UI; Batch 3: Ctrl+O + Type Path + Enter)
  - `Wrong Actions`: 0
  - `Retries`: 0
  - `Recovery Used`: false
  - `User Intervention`: 0
  - `Final State Verified`: true (Verified visual content in Notepad `LCU Download Verification Successful - 2026`, tab `sample-report.txt`, plus file system assertions)
  - `Cleanup Completed`: true (Notepad closed, browser fixture closed, `sample-report.txt` removed from Downloads, confirmed 0 matching files)
- **Key Flow**:
  1. Spawned browser download fixture (`download_gui_fixture.py`) with URL `http://localhost:8765/download.html`.
  2. Aligned bounds to `(200, 100, 650, 500)` and focused.
  3. **Observation Boundary 1**: Captured webpage with download link (`c_0a054147.webp`).
  4. **Batch 1 (1 action)**: Clicked `⬇ Download sample-report.txt` at calibrated center `(324, 262)`.
  5. **Observation Boundary 2**: Captured download completion state and flyout panel (`c_3b95d690.webp`).
  6. Verified physical file created: `C:\Users\cjfty\Downloads\sample-report.txt` (63 bytes).
  7. **Batch 2 (1 action)**: Clicked `[ 파일 열기 ]` button at `(477, 194)` in Downloads flyout.
  8. Notepad launched (`hwnd: 197906`).
  9. **Batch 3 (3 actions)**: `hotkey(["CTRL", "O"])` -> type file path -> `press_key("ENTER")`.
  10. **Observation Boundary 3**: Captured Notepad window showing `sample-report.txt` (`c_153d5a03.webp`).
  11. Verified text content: `LCU Download Verification Successful - 2026`.
  12. Cleanup: Closed Notepad, closed Browser fixture, unlinked `sample-report.txt`, verified with `direct.find_path`.

### TC-05: 웹 검색 + 새 탭 + 정보 복사
- **Status**: PASS
- **Grade**: Production Grade A
- **Metrics**:
  - `Result`: PASS
  - `Total Tool Calls`: 9
  - `Screenshot Count`: 4 (Boundary 1: Search Portal, Boundary 2: Search Results, Boundary 3: New Tab Destination, Boundary 5: Reopened File Verification)
  - `Observation Boundary Count`: 5 (Search Portal, Search Results, New Tab Destination, Save As Dialog, Final Editor Verification)
  - `Unnecessary Screenshots`: 0
  - `Batch Count`: 5 (Batch 1: Search Entry + Enter; Batch 2: Click Open in New Tab; Batch 3: Click Copy Title; Batch 4: Type + Paste + Ctrl+S; Batch 5: Ctrl+O + Path + Enter)
  - `Wrong Actions`: 0
  - `Retries`: 0
  - `Recovery Used`: false
  - `User Intervention`: 0
  - `Final State Verified`: true (Verified visual content in Notepad `검색 결과 제목: OpenAI ChatGPT Overview & Capabilities`, tab `search-result.txt`, clipboard match, and file assertions)
  - `Cleanup Completed`: true (Notepad closed, browser fixture closed, `search-result.txt` deleted from Desktop, verified 0 files on Desktop)
- **Key Flow**:
  1. Spawned browser search fixture (`browser_search_fixture.py`) with tabbed interface.
  2. Set bounds to `(200, 100, 700, 520)` and focused.
  3. **Observation Boundary 1**: Captured search portal (`c_073496c4.webp`).
  4. **Batch 1 (3 actions)**: Click search entry -> type "OpenAI ChatGPT" -> press ENTER.
  5. **Observation Boundary 2**: Captured search results page (`c_801b69fe.webp`).
  6. **Batch 2 (1 action)**: Clicked `[ 새 탭으로 열기 (Open in New Tab) ]` at `(151, 293)`.
  7. **Observation Boundary 3**: Captured newly opened destination tab (`c_039448dd.webp`).
  8. **Batch 3 (1 action)**: Clicked `[ 📋 제목 복사 (Copy Title to Clipboard) ]` at `(190, 259)`.
  9. Verified clipboard content: `OpenAI ChatGPT Overview & Capabilities`.
  10. Opened Notepad (`open_app notepad`, `hwnd: 590676`).
  11. **Batch 4 (3 actions)**: Typed `검색 결과 제목: ` + `hotkey(["CTRL", "V"])` + `hotkey(["CTRL", "S"])`.
  12. Saved to `Desktop\search-result.txt`.
  13. Reopened in Notepad via `hotkey(["CTRL", "O"])`.
  14. **Observation Boundary 5**: Captured Notepad editor state (`c_6abd0a6b.webp`).
  15. Verified exact string: `검색 결과 제목: OpenAI ChatGPT Overview & Capabilities`.
  16. Cleanup: Closed Notepad, closed browser fixture, deleted `Desktop\search-result.txt`, verified 0 items via `direct.find_path`.

### TC-09: 브라우저 메뉴 및 북마크 복합 작업
- **Status**: PASS
- **Grade**: Production Grade A
- **Metrics**:
  - `Result`: PASS
  - `Total Tool Calls`: 11
  - `Screenshot Count`: 5 (Boundary 1: Initial Wikipedia, Boundary 3: Navigated Page, Boundary 4: Bookmarks Menu, Boundary 5: Reopened Wikipedia, Boundary 6: Deleted State)
  - `Observation Boundary Count`: 6
  - `Unnecessary Screenshots`: 0
  - `Batch Count`: 6 (Batch 1: Add Bookmark; Batch 2: Navigate Away; Batch 3: Open Menu; Batch 4: Open Bookmark; Batch 5: Open Menu to Delete; Batch 6: Delete Bookmark)
  - `Wrong Actions`: 0
  - `Retries`: 0
  - `Recovery Used`: false
  - `User Intervention`: 0
  - `Final State Verified`: true (Verified visual state in Browser `북마크 없음`, URL restoration to `https://en.wikipedia.org`, and all status flags)
  - `Cleanup Completed`: true (Browser closed, temporary status file removed)
- **Key Flow**:
  1. Spawned browser fixture (`browser_bookmark_fixture.py`) with initial page `Wikipedia - The Free Encyclopedia`.
  2. Aligned bounds to `(200, 100, 700, 520)` and focused.
  3. **Observation Boundary 1**: Captured Wikipedia initial view (`c_cff0b6a5.webp`).
  4. Detected `★ 북마크 추가` button at `(573, 49)`.
  5. **Batch 1 (1 action)**: Clicked `★ 북마크 추가`.
  6. Verified bookmark added to list (`bookmark_added: True`).
  7. **Batch 2 (4 actions)**: Clicked address bar -> `hotkey(["CTRL", "A"])` -> typed `https://news.ycombinator.com` -> `press_key("ENTER")`.
  8. **Observation Boundary 3**: Captured navigated page (`c_3f661439.webp`) showing Hacker News portal.
  9. **Batch 3 (1 action)**: Clicked `☰ 메뉴` at `(650, 49)`.
  10. **Observation Boundary 4**: Captured menu popup with bookmark list (`c_7fbc3f7e.webp`).
  11. **Batch 4 (1 action)**: Clicked `[ 열기 ]` button on the Wikipedia bookmark at `(532, 169)`.
  12. **Observation Boundary 5**: Captured reopened Wikipedia page (`c_21f347bf.webp`), verified URL returned to `https://en.wikipedia.org`.
  13. **Batch 5 (1 action)**: Clicked `☰ 메뉴` to reopen menu.
  14. **Batch 6 (1 action)**: Clicked `[ 삭제 ]` button at `(564, 169)`.
  15. **Observation Boundary 6**: Captured updated menu showing `북마크 없음` (`c_a2738868.webp`).
  16. Verified `bookmark_deleted: True`, closed browser fixture cleanly.

### TC-16: 10단계 종합 Stress Test
- **Status**: PASS
- **Grade**: Production Grade A
- **Metrics**:
  - `Result`: PASS
  - `Total Tool Calls`: 15
  - `Screenshot Count`: 3 (Observation Boundary 1: Wikipedia Home, Observation Boundary 2: Wikipedia Search Result, Observation Boundary 3: Final Reopened Document Verification)
  - `Observation Boundary Count`: 3
  - `Unnecessary Screenshots`: 0
  - `Batch Count`: 7 (Batch 1a: Type Start + Ctrl+S; Batch 1b: Type Path + Enter + Ctrl+W; Batch 2: Search Computer vision; Batch 3: Copy Title; Batch 4a: Open result.txt; Batch 4b: Move End + Paste + Ctrl+S + Ctrl+W; Batch 5a: Open dialog via Ctrl+O; Batch 5b: Enter path; Batch 5c: Press Enter)
  - `Wrong Actions`: 0
  - `Retries`: 0
  - `Recovery Used`: false
  - `User Intervention`: 0
  - `Final State Verified`: true (Verified visual content in Notepad `final-result.txt`, Line 1 `Start`, Line 2 `Computer vision`, 21 chars, and disk file assertions)
  - `Cleanup Completed`: true (Notepad closed cleanly, Wikipedia fixture closed, `Documents\final-result.txt` deleted, `Desktop\LCU-Production` directory deleted, verified 0 residual files via `direct.find_path`)
- **Key Flow**:
  1. **Step 1 (Folder creation)**: Created isolated test folder `C:\Users\cjfty\Desktop\LCU-Production`.
  2. **Step 2 & 3 (File creation + Start text + Save)**: Launched Notepad (`hwnd: 272448`), executed **Batch 1a** (`type_text "Start\n"` + `hotkey CTRL S`), executed **Batch 1b** (`type_text` path + `press_key ENTER` + `hotkey CTRL W` to close tab cleanly), closed Notepad. Verified `result.txt` on disk.
  3. **Step 4 (Browser Navigation + Search)**: Spawned Wikipedia GUI fixture (`wiki_search_fixture.py`).
  4. **Observation Boundary 1**: Captured initial Wikipedia home page (`c_bd6def3c.webp`).
  5. **Batch 2 (Search)**: Clicked search bar at `(250, 55)` -> typed "Computer vision" -> `press_key ENTER`.
  6. **Observation Boundary 2**: Captured loaded Wikipedia article page (`c_9dee6dce.webp`).
  7. **Step 5 (Copy Title to Clipboard)**: Calibrated green button center at `(132, 305)`, executed **Batch 3** (click), verified clipboard: `"Computer vision"`. Terminated fixture.
  8. **Step 6 & 7 (Append to result.txt + Save)**: Reopened Notepad, executed **Batch 4a** (`CTRL+O` + type path + `ENTER`), executed **Batch 4b** (`CTRL+END` + `CTRL+V` + `CTRL+S` + `CTRL+W`). Verified disk content has both `Start` and `Computer vision`.
  9. **Step 8 (Rename file)**: Renamed `Desktop\LCU-Production\result.txt` to `Desktop\LCU-Production\final-result.txt`.
  10. **Step 9 (Move file)**: Moved `Desktop\LCU-Production\final-result.txt` to `C:\Users\cjfty\Documents\final-result.txt`. Verified file exists in Documents and removed from Desktop.
  11. **Step 10 (Reopen in Notepad + Final Visual Verification)**: Opened Notepad cleanly, executed **Batch 5a** (`CTRL+O`), **Batch 5b** (`ALT+N` + type `MOVED_FILE`), **Batch 5c** (`ENTER`).
  12. **Observation Boundary 3**: Captured active Notepad window (`c_946e32cc.webp`). Visually confirmed active tab is `final-result.txt` with contents `Start\nComputer vision`.
  13. **Cleanup**: Closed Notepad, deleted `Documents\final-result.txt`, deleted `Desktop\LCU-Production`, verified 0 items in Documents and Desktop via `direct.find_path`.


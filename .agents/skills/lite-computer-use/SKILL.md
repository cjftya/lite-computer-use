---
name: lite-computer-use
description: Control a local interactive Windows desktop for simple app, file, website, mouse, keyboard, window, and screenshot tasks. Use when the user asks the agent to operate their Windows PC; do not use for browser DOM automation, unattended long-running workflows, or non-Windows hosts.
---

# Lite Computer Use (v2)

Lite Computer Use provides precise, single-execution Windows tools for AI agents.
AI reasons, decomposes tasks, and plans; Python executes deterministic Windows primitives and returns structured JSON.

Python CLI entry point:
```powershell
py -3.13 scripts\lcu.py <tool> [args]
```

---

## 1. Tool 목록 (Public Tools)

### Open & Discovery
- `open_app <name> [--debug]`: Resolve, inspect existing windows, dispatch once, observe, then focus. After Windows accepts a launch, never launch another candidate or kill a process because its window is late. `ok=true` requires a verified foreground window.
- `app_status <attempt-id> [--timeout 0..30]`: Resume observation for an unconfirmed attempt without dispatching or terminating anything.
- `open_file <absolute-path>`: Open file with default associated application.
- `open_folder <absolute-path-or-alias>`: Open folder in Explorer (`desktop`, `documents`, `downloads`, `바탕화면`, `문서`, `다운로드`).
- `open_url <url>`: Open `http://` or `https://` URL in default browser.
- `reveal_file <absolute-path>`: Open Explorer and highlight specific file.
- `find_path <query> --root <root> [--kind any|file|folder] [--limit 10]`: Bounded search under root.

### Window Management
- `list_windows [--query <query>]`: List visible top-level windows (`hwnd`, `pid`, `title`, `process`, `active`, `bounds`).
- `focus_window [query] [--hwnd <int>]`: Restore and bring window to foreground.
- `close_window [query] [--hwnd <int>] [--owned-processes <json>]`: Send standard WM_CLOSE and verify actual HWND destruction via polling (default timeout 4.0s with early-exit; no force-kill; hidden or cloaked status alone is not considered closed). When `--owned-processes` is passed, lingering owned processes are safely terminated after window destruction.
- `set_window_bounds --x <int> --y <int> --width <int> --height <int> [--hwnd <int>]`: Resize and reposition window.

### Vision & Screenshot
- `screenshot [--target active-window|screen|window] [--hwnd <int>] [--region x y w h] [--quality fast|normal|detail] [--from-capture <id>]`:
  Capture desktop or window. Always returns `captureId` for coordinate resolution.

### Mouse & Keyboard
- `click <x> <y> [--capture <id>] [--button left|right|middle] [--count 1|2]`: Click screen or capture image coordinates.
- `move_mouse <x> <y> [--capture <id>]`: Move cursor.
- `drag <sx> <sy> <ex> <ey> [--capture <id>] [--duration 0.2]`: Drag between coordinates.
- `scroll <amount>`: Scroll vertically (positive=up, negative=down).
- `get_mouse_position`: Get current mouse coordinates `(x, y)`.
- `type_text <text> [--hwnd <int>]`: Type Unicode / Korean text into foreground window.
- `press_key <key> [--count <n>] [--hwnd <int>]`: Press special key (`ENTER`, `TAB`, `ESC`, etc.).
- `hotkey <key1> <key2> ... [--hwnd <int>]`: Press key combination (`CTRL SHIFT S`, `CTRL V`, etc.).
- `set_clipboard <text>`: Set system clipboard text.
- `get_clipboard`: Read system clipboard text.

### Execution
- `batch <json-array-or-file>`: Execute a sequence of deterministic actions with optional `delay_after`.

### Diagnostics
- `doctor`: Check the platform, dependencies, desktop, active Python/module hashes, config fingerprint, and cache location.
- `launch_context`: Report the selected shell/parent/session/desktop environment needed to compare PowerShell and Antigravity without exposing the full environment or PATH.

### App launch state contract

Use input tools only after `ready`. For `window_focus_failed`, retry focus only on the returned HWND. For `window_unconfirmed` or `dispatch_outcome_unknown`, use `app_status` or one necessary screen check and do not call `open_app` again. For `ambiguous_target` or `window_observation_failed`, report/select/fix observation without a raw shell fallback.

---

## 2. Orchestration & Planning Protocol (Phase 2)

AI 에이전트는 복잡한 요청을 수행할 때 다음 오케스트레이션 원칙을 반드시 준수합니다:

### 2.1 Initial Plan & Task Queue
- 요청을 받으면 클릭 단위가 아닌 **의미 단위의 작은 Task**로 분해합니다.
- Initial Plan에는 도구 이름, 픽셀 좌표, captureId, retry 계획을 넣지 않습니다.
- **State 구조**:
  ```json
  {
    "goal": "요청 목표",
    "tasks": [
      { "id": 1, "goal": "...", "done_when": "...", "status": "pending|active|completed|failed", "result": null }
    ],
    "current_task_index": 0,
    "completed_tasks_summary": [],
    "current_capture_id": null,
    "last_error": null,
    "recovery_used": false
  }
  ```

### 2.2 Direct-First 도구 우선순위
1. **Direct Tool** (`open_app`, `open_file`, `open_folder`, `open_url`): GUI 클릭/탐색 대신 항상 최우선 사용.
2. **Discovery Tool** (`find_path`, `list_windows`, `focus_window`): 경로 및 창 식별에 우선 사용.
3. **GUI Vision** (`screenshot` -> `batch`): Direct/Discovery로 해결할 수 없을 때만 최후에 사용.
- **Direct Tool 성공 정의**: `open_app`은 단순 dispatch 성공이 아니라 검증된 `hwnd`(`MainWindowHandle`) 확보 및 foreground 포커스가 검증되어야 Task 완료로 판정합니다. 단일 기존 창이 존재하면 자동 restore/focus 후 `reused_existing=true`로 완료합니다.
- **앱 실행 단일 호출**: 앱 실행 요청마다 `open_app <app>`은 정확히 1회만 호출합니다. 실패 뒤에 raw Bash 실행, `Start-Process`, `.lnk` 직접 실행, 동일 `open_app` 재호출을 이어 붙이지 않습니다. 실행 접수 뒤 후보 재실행과 자동 rollback은 금지됩니다.
- **실패 판정**: `ok=true`, 유효한 `hwnd`, `window_verified=true`, `foreground=true`가 함께 있어야 성공입니다. `window_unconfirmed` 또는 `dispatch_outcome_unknown`이면 같은 `attempt_id`를 `app_status`로만 재조회합니다.

### 2.3 Observation Boundary & Batching
- **핵심 불변 규칙**:
  현재 화면에서 확정할 수 있는 모든 행동은 **하나의 `batch`**로 묶어 일괄 실행합니다.
  다음 행동을 결정하기 위해 **새로운 시각 정보가 반드시 필요한 시점(Observation Boundary)**에서만 Screenshot을 1회 촬영합니다.
  - 클릭할 때마다 캡처하지 않습니다.
  - 검색 입력 후 Enter를 친 뒤 결과 화면이 로딩되었을 때 비로소 캡처합니다.

### 2.4 Task 완료 및 Context 압축
- GUI batch 성공 자체는 Task 완료가 아니다. `done_when` 확인에 새 화면 정보가 필요하면 Observation Boundary에서 Capture 후 완료합니다.
- Task가 완료되면 이전 스크린샷 이미지, 픽셀 좌표, 도구의 전체 raw JSON 응답, 상세 reasoning을 컨텍스트에서 폐기합니다.
- `completed_tasks_summary`에 한 줄 요약 및 다음 Task에 필요한 최소 결과값(`path`, `url`, `hwnd` 등)만 유지합니다.
- **Context 압축 예외**: 작업 중 새로 열린 앱의 `hwnd`, `reused_existing`, `launch_method`, `window_pid`, `window_process`, `owned_processes`는 Goal 종료 전 Cleanup을 위해 Task result에 보존해야 하며, cleanup이 완료된 뒤 폐기합니다.

### 2.5 Failure Plan & 단 1회 Recovery 제한 (`recovery_used`)
- 실패 발생 시 문제를 파악하고 명확한 대안이 있는지 검토합니다.
- 명확한 대안이 있고 `recovery_used == false`인 경우:
  `recovery_used = true`로 설정하고 대안을 **단 1회 실행**합니다.
- 대안이 없거나 이미 `recovery_used == true`인 상태에서 또 실패하면 **즉시 중단**합니다.
- 동일한 실패 행동을 반복하는 retry loop를 금지합니다.

### 2.6 Resource Cleanup Protocol (End-of-Goal Cleanup)
작업(Goal) 완료 직전에 AI Orchestrator는 완료된 Task의 `result`를 확인하여 임시 앱과 잔류 프로세스를 안전하게 정리합니다:
- **전체 흐름**:
  Goal completed -> Cleanup Phase -> Task result에서 새로 열린 temporary app 확인 -> `close_window --hwnd <hwnd> --owned-processes '<json>'` (역순 실행) -> Cleanup 종료
- **자동 종료 대상 (모두 충족 시)**:
  1. `open_app`으로 생성됨 (`launch_method`가 `appsfolder`, `start-menu`, `uri`, `app-paths`, `exe` 중 하나)
  2. `reused_existing == false` (명시적)
  3. `app`과 `launch_method` 정보가 유효함
  4. 해당 앱이 중간 작업용 (intermediate task)
  5. 사용자의 최종 결과물(final result)로 남길 필요가 없음
- **자동 종료 금지**:
  1. `reused_existing == true` (사용자가 원래 열어둔 창/앱)
  2. `reused_existing` 필드가 누락되었거나 `focus_window` 결과 등 소유권이 불명확한 창
  3. 사용자의 최종 결과로 남겨야 하는 창 (예: "메모장에 결과를 적어줘" 요청의 메모장)
  4. 기존 브라우저 창 또는 탭
  5. **기존 사용자 프로세스 및 시스템 프로세스**: `taskkill /IM`, `Stop-Process -Name` 등 이름 기반의 일괄 강제 종료는 절대 금지됩니다. 오직 exact executable dispatch identity로 입증된 `owned_processes`만 PID + creation time + image + session + 타 창 검증을 통과한 뒤 정리됩니다. Shell/shortcut/URI/broker 및 새 same-name PID는 소유하지 않습니다. `%TEMP%\LiteComputerUse\owned-processes.json`의 live evidence가 없는 caller JSON도 종료 권한을 부여하지 않습니다.
- **종료 순서**:
  여러 앱을 실행한 경우 최근에 실행한 앱부터 **역순**으로 닫습니다.
- **Cleanup 실패 처리**:
  Main Goal이 성공한 경우, cleanup 도중 창 닫기에 실패하더라도 warning만 기록하며 본 작업 결과를 실패로 뒤집지 않습니다. 임의 프로세스 강제 종료는 절대 수행하지 않습니다.

---

## 3. Screenshot & captureId Coordinate System

비전 작업 시 AI가 이미지에서 본 좌표를 그대로 사용할 수 있도록 `captureId`를 제공합니다:

1. **캡처 생성**:
   ```powershell
   py -3.13 scripts\lcu.py screenshot --target active-window --quality normal
   ```
   반환:
   ```json
   {
     "ok": true,
     "action": "screenshot",
     "result": {
       "captureId": "c_8f2a91",
       "path": "...",
       "width": 1600,
       "height": 900
     }
   }
   ```

2. **이미지 좌표 기반 클릭**:
   AI가 반환된 이미지에서 본 좌표 (예: x=420, y=180)를 그대로 전달:
   ```powershell
   py -3.13 scripts\lcu.py click 420 180 --capture c_8f2a91
   ```
   Python이 자동으로 해상도 역스케일링, DPI, 윈도우 오프셋을 계산하여 정확한 물리 모니터 좌표를 클릭합니다.

3. **품질 프리셋 & 캐시 관리**:
   - `fast`: 최대 1024px, WebP Q70 (전체 화면 파악, 대략적 확인)
   - `normal` (기본값): 최대 1600px, WebP Q82 (일반 UI 조작)
   - `detail`: 1.0x 원본 무손실 (작은 폰트, 정밀 UI)
   - **캐시 관리**: 최근 50개 캡처 및 24시간 이내 데이터만 자동 유지되며, 이전 파일과 메타데이터는 자동 정리됩니다.

---

## 4. Region & Partial Recapture

- **창 기준 부분 캡처**:
  ```powershell
  py -3.13 scripts\lcu.py screenshot --target active-window --region 100 80 400 300
  ```
- **전체 화면 기준 부분 캡처**:
  `screenshot --target screen --region x y w h`의 좌표계는 멀티모니터 가상 데스크톱 전체 캡처 이미지 좌상단을 항상 `(0, 0)`으로 계산합니다.
- **기존 캡처 이미지 내 부분 재캡처 (`from-capture`)**:
  이전 캡처의 특정 영역을 원본 해상도로 확대 관찰할 때 사용:
  ```powershell
  py -3.13 scripts\lcu.py screenshot --from-capture c_8f2a91 --region 200 150 100 80 --quality detail
  ```
- **Window 캡처 주의점**:
  `screenshot --target window`는 화면에 표시된 윈도우 영역 픽셀을 캡처하므로 다른 창에 가려져 있으면 겹친 내용이 들어갈 수 있습니다. 정밀 조작 시 `focus_window` 후 캡처를 권장합니다.

---

## 5. Batch & delay_after

한 번의 관찰로 계획된 여러 deterministic action을 순차 실행합니다.

```powershell
py -3.13 scripts\lcu.py batch '[{"action": "click", "x": 300, "y": 150, "capture": "c_8f2a91", "delay_after": 0.2}, {"action": "type_text", "text": "검색어"}, {"action": "press_key", "key": "ENTER"}]'
```

- **사전 검증 보증**: 실행 전 모든 action의 스키마를 100% 사전 검증하며, 뒤쪽 action이라도 유효하지 않으면 첫 action조차 실행되지 않습니다 (Zero side effects).
- 각 action에 `delay_after` (0.0~5.0초) 지정 가능.
- 최대 12개 action 제한.
- 관찰 도구(`screenshot`, `list_windows`, `find_path`)는 batch 내 포함 불가.
- 첫 실패 시 즉시 중단(fail-fast), 자동 retry 없음.

---

## 6. Ambiguity & Error Handling

- 앱이나 창 검색 시 일치하는 대상이 2개 이상이면 임의 선택하지 않고 즉시 `ambiguous_target` 에러와 후보 목록을 반환합니다.
- 창이 이동하거나 닫힌 경우 `stale_capture` 에러를 반환합니다.
- Python 내부에서 임의 재시도나 visual fallback을 시도하지 않습니다. 실패는 즉시 AI에게 보고되어 AI가 Failure Plan에 따라 판단합니다.

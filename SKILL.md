---
name: lite-computer-use
description: Control a local interactive Windows desktop for simple app, file, website, mouse, keyboard, window, and screenshot tasks. Use when the user asks the agent to operate their Windows PC; do not use for browser DOM automation, unattended long-running workflows, or non-Windows hosts.
---

# Lite Computer Use (v2)

Lite Computer Use provides precise, single-execution Windows tools for AI agents.
AI reasons and plans; Python executes deterministic Windows primitives and returns structured JSON.

Python CLI entry point:
```powershell
py -3.13 scripts\lcu.py <tool> [args]
```

---

## 1. Tool 목록 (Public Tools)

### Open & Discovery
- `open_app <name>`: Launch application by name or alias (Start Menu, App Paths, `apps.yaml`).
- `open_file <absolute-path>`: Open file with default associated application.
- `open_folder <absolute-path-or-alias>`: Open folder in Explorer (`desktop`, `documents`, `downloads`, `바탕화면`, `문서`, `다운로드`).
- `open_url <url>`: Open `http://` or `https://` URL in default browser.
- `reveal_file <absolute-path>`: Open Explorer and highlight specific file.
- `find_path <query> --root <root> [--kind any|file|folder] [--limit 10]`: Bounded search under root.

### Window Management
- `list_windows [--query <query>]`: List visible top-level windows (`hwnd`, `title`, `process`, `active`, `bounds`).
- `focus_window [query] [--hwnd <int>]`: Restore and bring window to foreground.
- `close_window [query] [--hwnd <int>]`: Send standard WM_CLOSE (no force-kill).
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
- `doctor`: Check environment, Windows platform, dependencies, and desktop connection.

---

## 2. Direct Tool 우선 (Direct-First Routing)

AI는 마우스/비전보다 Direct Tool을 항상 최우선으로 선택해야 합니다:
1. 앱 실행: `open_app notepad` (바탕화면 아이콘 클릭 대신)
2. URL 열기: `open_url https://www.naver.com` (브라우저 주소창 클릭/타이핑 대신)
3. 파일 열기: `open_file C:\path\to\doc.pdf` (폴더 더블클릭 탐색 대신)
4. 창 전환: `focus_window --hwnd 12345` 또는 `focus_window "chrome"` (작업표시줄 클릭 대신)

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

3. **품질 프리셋**:
   - `fast`: 최대 1024px, WebP Q70 (전체 화면 파악, 대략적 확인)
   - `normal` (기본값): 최대 1600px, WebP Q82 (일반 UI 조작)
   - `detail`: 1.0x 원본 무손실 (작은 폰트, 정밀 UI)

---

## 4. Region & Partial Recapture

- **창 기준 부분 캡처**:
  ```powershell
  py -3.13 scripts\lcu.py screenshot --target active-window --region 100 80 400 300
  ```
- **기존 캡처 이미지 내 부분 재캡처 (`from-capture`)**:
  이전 캡처의 특정 영역을 원본 해상도로 확대 관찰할 때 사용:
  ```powershell
  py -3.13 scripts\lcu.py screenshot --from-capture c_8f2a91 --region 200 150 100 80 --quality detail
  ```

---

## 5. Batch & delay_after

한 번의 관찰로 계획된 여러 deterministic action을 순차 실행합니다.

```powershell
py -3.13 scripts\lcu.py batch '[{"action": "click", "x": 300, "y": 150, "capture": "c_8f2a91", "delay_after": 0.2}, {"action": "type_text", "text": "검색어"}, {"action": "press_key", "key": "ENTER"}]'
```

- 각 action에 `delay_after` (0.0~5.0초) 지정 가능.
- 최대 12개 action 제한.
- 관찰 도구(`screenshot`, `list_windows`, `find_path`)는 batch 내 포함 불가 (사전 validation 실패).
- 첫 실패 시 즉시 중단(fail-fast), 자동 retry 없음.

---

## 6. Ambiguity & Error Handling

- 앱이나 창 검색 시 일치하는 대상이 2개 이상이면 임의 선택하지 않고 즉시 `ambiguous_target` 에러와 후보 목록을 반환합니다.
- 창이 이동하거나 닫힌 경우 `stale_capture` 에러를 반환합니다.
- Python 내부에서 임의 재시도나 visual fallback을 시도하지 않습니다. 실패는 즉시 AI에게 보고되어 AI가 다음 행동을 판단합니다.

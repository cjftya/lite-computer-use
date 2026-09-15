# Lite Computer Use v2 — Phase 2 Orchestration Specification

## 1. 개요 및 목적

Lite Computer Use v2의 Phase 2는 AI Agent(Antigravity CLI 등)가 Windows 데스크톱을 조작할 때 사용하는 **Planning 및 Orchestration 계층**의 설계와 운영 원칙을 정의합니다.

### 목적
> **사용자 요청을 의미 단위의 작은 Task로 분해하고, Direct Tool을 최우선으로 활용하며, GUI 조작 시 불필요한 Screenshot 캡처와 무의미한 재시도를 최소화하여 결정론적이고 효율적인 작업 완수를 달성한다.**

### 핵심 원칙
- **AI Centric Planning**: 계획 수립, 관찰 판단, 복구 결정은 AI가 담당합니다. Python Tool Layer 내부에는 자율적인 플래너나 무한 재시도 루프를 두지 않습니다.
- **Phase 1 Tool Layer 동결**: Phase 1에서 검증된 Public Tool 계층(`lcu.py`)의 인터페이스와 계약은 그대로 유지하며, 신규 Public Tool을 추가하지 않습니다.
- **Zero Unnecessary Captures**: 마우스 클릭마다 화면을 캡처하지 않습니다. 오직 다음 행동을 결정하기 위해 새로운 시각 정보가 필수적인 순간에만 캡처합니다.

---

## 2. 핵심 불변 규칙 (Core Invariant Rules)

GUI 작업 시 AI 에이전트는 다음 규칙을 엄격히 준수해야 합니다:

```text
현재 화면 관찰
    ↓
다음 행동들을 현재 화면 정보만으로 모두 확정할 수 있는가?
    ├─ Yes → 확정 가능한 모든 행동을 하나의 batch로 묶어 일괄 실행
    └─ No  → 현재 화면에서 확정 가능한 마지막 행동까지만 실행
                 ↓
          새로운 시각 정보가 필요한 순간 (Observation Boundary)
                 ↓
              Capture 1회 수행
```

### 절대 원칙
1. **클릭할 때마다 캡처하지 않는다.**
2. **화면이 바뀌었다는 이유만으로 캡처하지 않는다.**
3. **다음 행동을 결정하기 위해 시각 정보가 반드시 필요한 순간에만 캡처한다.**

---

## 3. 전체 실행 흐름 (End-to-End Workflow)

```text
User Request
    ↓
Initial Plan 수립 (Goal + Semantic Tasks)
    ↓
Task Queue 생성 (첫 번째 Task -> active)
    ↓
[Current Task 실행]
    ├─ 1단계: Direct / Discovery Tool로 해결 가능한가?
    │       ├─ Yes → 실행
    │       │        ├─ 성공 → Task 완료 (Context 압축) → 다음 Task
    │       │        └─ 실패 → Failure Plan
    │       │
    │       └─ No  → 2단계: GUI 작업 (Vision 필요)
    │                ↓
    │             Capture Plan (screenshot 1회)
    │                ↓
    │             현재 화면에서 확정 가능한 Action Batch 실행
    │                ↓
    │             Observation Boundary 도달?
    │                ├─ 추가 화면 필요 → 재Capture 후 Batch 계속
    │                └─ done_when 충족 → Task 완료 (Context 압축)
    │
    └─ 실패 발생 시 → Failure Plan (명확한 대체 경로 1회 시도, 실패 시 즉시 중단)
```

---

## 4. 상태 자료구조 (State Data Structure)

오케스트레이션 상태는 가볍고 직관적인 최소 스키마로 유지되며 필드를 임의로 추가하지 않습니다.

```json
{
  "goal": "OpenAI 공식 사이트에 진입한다",
  "tasks": [
    {
      "id": 1,
      "goal": "네이버를 연다",
      "done_when": "네이버 페이지가 열림",
      "status": "completed",
      "result": { "url": "https://www.naver.com" }
    },
    {
      "id": 2,
      "goal": "OpenAI를 검색한다",
      "done_when": "OpenAI 검색 결과가 표시됨",
      "status": "active",
      "result": null
    },
    {
      "id": 3,
      "goal": "OpenAI 공식 사이트를 연다",
      "done_when": "OpenAI 공식 사이트가 열림",
      "status": "pending",
      "result": null
    }
  ],
  "current_task_index": 1,
  "completed_tasks_summary": [
    "Task 1 완료: 네이버를 연다 -> result={'url': 'https://www.naver.com'}"
  ],
  "current_capture_id": "c_8f2a91",
  "last_error": null,
  "recovery_used": false
}
```

### Task 스키마
```json
{
  "id": 1,
  "goal": "목표 설명",
  "done_when": "완료 판단 조건",
  "status": "pending | active | completed | failed",
  "result": null
}
```

- **허용 status**: `pending`, `active`, `completed`, `failed` (4가지만 허용)
- **추가 금지**: 임의의 플래그, 복잡한 트리 구조, 히스토리 전체 저장을 금지합니다.

---

## 5. Initial Plan 수립 규칙

사용자 요청을 수신하면 즉시 의미 단위의 `Task` 목록으로 분해합니다.

### 올바른 예시
- Task 1: "네이버를 연다" (`done_when`: "네이버 페이지가 열림")
- Task 2: "OpenAI를 검색한다" (`done_when`: "OpenAI 검색 결과가 표시됨")
- Task 3: "OpenAI 공식 사이트를 연다" (`done_when`: "OpenAI 공식 사이트가 열림")

### 금지 패턴 (Anti-Patterns)
Initial Plan에는 다음과 같은 저수준/실행 세부정보를 절대 포함하지 않습니다:
- ❌ Python Tool 이름 (`open_url`, `click`, `screenshot` 등)
- ❌ 화면 픽셀 좌표 (`x=500, y=300`)
- ❌ 임의의 `captureId`
- ❌ 구체적인 마우스 클릭/타이핑 시퀀스
- ❌ 사전 정의된 retry / fallback 계획

---

## 6. Task 처리 및 도구 우선순위 (Direct-First Routing)

Task를 처리할 때 AI는 반드시 아래의 3단계 우선순위를 따릅니다:

```text
우선순위 1: Direct Tool     (open_app, open_file, open_folder, open_url)
    ↓ 불가 시
우선순위 2: Discovery Tool  (find_path, list_windows, focus_window)
    ↓ 불가 시
우선순위 3: GUI Vision      (screenshot -> batch)
```

### Direct Tool 해결 가능 사례
- 브라우저 특정 사이트 열기: `open_url https://www.naver.com` (주소창 캡처 후 클릭/타이핑 금지)
- 응용 프로그램 실행: `open_app calc`, `open_app notepad` (바탕화면 아이콘 캡처 후 더블클릭 금지)
- 파일 직접 열기: `open_file C:\path\report.pdf` (탐색기 캡처 후 파일 찾아 클릭 금지)
- 창 포커스 전환: `focus_window "chrome"` (작업표시줄 캡처 후 클릭 금지)

---

## 7. Direct Tool 성공 처리

- Direct Tool 실행이 성공하면 **별도의 화면 캡처 없이 해당 Task를 즉시 완료(`completed`)** 처리합니다.
- 예: `open_url https://www.naver.com`이 성공하면 "네이버를 연다" Task는 완료됩니다.
- 단, 바로 다음 Task가 화면 상의 UI 요소 조작을 필요로 하는 경우, 다음 Task의 시작 시점에 최초 캡처를 수행합니다.

---

## 8. Capture Plan 및 화면 일괄 조작

화면 시각 정보가 반드시 필요한 Task에 진입하면:
1. `screenshot --target active-window --quality normal`을 1회 호출하여 `captureId`를 획득합니다.
2. 현재 화면에서 확실하게 확정할 수 있는 모든 조작을 파악합니다.
3. 이를 **하나의 `batch`** 명령으로 묶어 실행합니다.

### Batch 번들링 예시
네이버 메인 화면에서 검색 수행:
1. 현재 화면 캡처 (`c_10a9b2` 획득)
2. 이미지 내 검색 입력창 좌표 확인 (`x=320, y=145`)
3. 일괄 batch 실행:
   ```json
   [
     {"action": "click", "x": 320, "y": 145, "capture": "c_10a9b2", "delay_after": 0.1},
     {"action": "type_text", "text": "OpenAI", "delay_after": 0.1},
     {"action": "press_key", "key": "ENTER"}
   ]
   ```
4. 검색 결과가 로딩되는 동안 불필요한 중간 캡처를 전혀 하지 않습니다.

---

## 9. 관찰 경계 (Observation Boundary)

**Observation Boundary**란 "다음 행동을 결정하기 위해 새로운 시각 정보가 반드시 필요한 시점"을 의미합니다.

### 대표적인 Observation Boundary
1. **검색/양식 제출 후**:
   - 검색창 클릭 → 텍스트 입력 → Enter 실행 (하나의 batch)
   - **[Observation Boundary]**: Enter 입력 후 검색 결과 페이지가 렌더링되어야 다음 클릭 대상을 알 수 있음 → 캡처 필요.
2. **동적 팝업 / 메뉴 열기**:
   - 상단 메뉴 버튼 클릭 (batch 실행)
   - **[Observation Boundary]**: 드롭다운 메뉴 항목들이 새로 표시되어야 원하는 항목 좌표를 알 수 있음 → 캡처 필요.
3. **페이지/화면 전환 후**:
   - 링크 클릭 또는 창 열기 (batch 실행)
   - **[Observation Boundary]**: 새 화면의 렌더링이 완료되어야 요소를 선택할 수 있음 → 캡처 필요.

---

## 10. Capture 품질 프리셋 선택 기준

- **`normal` (기본값)**: 일반적인 UI 요소(버튼, 링크, 입력창) 식별 및 클릭에 사용.
- **`fast`**: 대략적인 창 배치, 전체 레이아웃 구조만 빠르게 확인할 때 사용.
- **`from-capture` + `region` + `detail`**:
  - 이미 캡처된 화면의 특정 영역 내 아주 작은 텍스트, 빽빽한 테이블, 미세한 아이콘을 정밀 판독할 때 사용.
  - 화면 전체를 다시 캡처하지 않고 기존 `captureId`의 부분 영역만 고해상도로 요청.

---

## 11. Task 완료 판단 및 Context 압축

### Task 완료 판단
- **Direct Task**: 도구 호출 성공 시 즉시 완료.
- **GUI Task**: `batch` 실행 완료 후 `done_when` 조건 충족을 확인하면 완료.

### Context 압축 (Context Compression)
Task가 완료되면 LLM 대화 컨텍스트에서 불필요한 과거 세부정보를 적극 폐기합니다:
- **폐기할 데이터**:
  - 이전 Task에서 사용한 Screenshot 이미지 파일 및 `captureId`
  - 이전 픽셀 좌표값
  - 도구의 전체 raw JSON 응답
  - 이전 단계의 장황한 추론(reasoning) 텍스트
- **유지할 데이터**:
  - 한 줄 완료 요약 (`completed_tasks_summary`)
  - 다음 Task에 전달할 핵심 결과값 (`result` - 파일 경로, URL, 창 hwnd 등)

---

## 12. Failure Plan 및 단 1회의 대체 실행 (`recovery_used`)

작업 중 실패(오류 응답, 대상 미발견 등)가 발생하면 AI는 정해진 단일 복구 절차를 따릅니다:

```text
실패 발생
   ↓
1. 무슨 문제인가? (오류 코드 및 원인 파악)
2. 그 문제를 우회할 명확한 다른 대안이 있는가?
   ├─ Yes (명확한 대안 존재)
   │     ├─ recovery_used == false 인가?
   │     │     ├─ Yes → recovery_used = true 설정 후 대안 1회 실행
   │     │     └─ No  → 즉시 실행 중단 (Aborted)
   │     │
   │     └─ 대안 실행 후 또 실패? → 즉시 실행 중단 (Aborted)
   │
   └─ No (명확한 대안 없음) → 즉시 실행 중단 (Aborted)
```

### 불변 규칙
- **대체 실행은 최대 1회만 허용 (`recovery_used = true`)**.
- **동일한 실패 행동을 무한 반복(Retry loop)하는 것을 엄격히 금지합니다.**

---

## 13. 구체적 오류 유형별 복구 전략

1. **`stale_capture`** (창 이동, 해상도 변경, 캡처 유효기간 초과):
   - 원인: 참조한 `captureId`가 현재 창 상태와 불일치함.
   - 대안: 신규 screenshot 1회 재캡처 후 좌표 재계산. (`recovery_used = true`)
2. **`ambiguous_target`** (동일 이름의 창이나 앱이 2개 이상):
   - 원인: 지정한 쿼리에 매칭되는 대상이 복수 존재.
   - 대안: 컨텍스트 정보를 통해 후보 중 하나를 명확히 식별할 수 있으면 해당 후보의 고유 속성(예: `hwnd`, 절대 경로)으로 1회 시도. 식별 불가 시 즉시 중단.
3. **`not_found`** (앱, 파일, 창을 찾을 수 없음):
   - 원인: 지정한 이름이나 경로가 없음.
   - 대안: 명확한 다른 경로(예: `find_path`를 통한 탐색, 대체 실행 파일명)가 존재하면 1회 시도. 없으면 즉시 사용자에게 실패 보고 후 종료.

---

## 14. 측정 및 평가 지표 (Metrics)

작업 완료 시 단순히 성공 여부뿐 아니라 실행 효율성을 함께 평가합니다:

| 지표명 | 설명 | 목표치 |
|---|---|---|
| **Task 수** | 생성 및 처리된 semantic task 개수 | 요청 복잡도에 비례 |
| **Capture 횟수** | 실행 중 캡처한 screenshot 총 횟수 | **Observation Boundary 수와 일치 (최소화)** |
| **불필요한 Capture 횟수** | 이전 캡처로 충분한데 다시 캡처한 횟수 | **0회** |
| **Tool 호출 수** | 실행된 총 CLI 도구 호출 수 | 최소화 |
| **Batch 평균 action 수** | batch당 묶인 action의 평균 개수 | **2.0개 이상** (단일 클릭 남발 방지) |
| **Failure 횟수** | 도구 실패 또는 타겟 미발견 발생 횟수 | 최소화 |
| **Recovery 횟수** | 실패 후 대체 경로를 시도한 횟수 | 최대 1회 (`recovery_used <= 1`) |
| **불필요한 재시도 횟수** | 동일 조작 반복 시도 횟수 | **0회** |

---

## 15. 표준 시나리오별 실행 패턴 (Walkthroughs)

### 시나리오 1: 계산기 열기
- Task 1: 계산기 앱을 연다 (`done_when`: 계산기 창이 열림)
- 실행: `open_app calc` (Direct Tool 1회 호출)
- 결과: 성공 -> Task 1 완료 (Capture 0회)

### 시나리오 2: 메모장 열고 문장 입력
- Task 1: 메모장을 연다 (`done_when`: 메모장 창이 열림)
  - 실행: `open_app notepad` (Direct Tool) -> 완료 (Capture 0회)
- Task 2: 문장을 입력한다 (`done_when`: 문장이 메모장에 입력됨)
  - 실행: `type_text "Hello World"` (Direct Tool) -> 완료 (Capture 0회)

### 시나리오 3: 네이버 열고 검색
- Task 1: 네이버를 연다 (`done_when`: 네이버가 열림)
  - 실행: `open_url https://www.naver.com` (Direct Tool) -> 완료 (Capture 0회)
- Task 2: "OpenAI"를 검색한다 (`done_when`: 검색 결과가 표시됨)
  - 관찰: GUI 조작 필요 -> `screenshot` 1회 (`c_01`)
  - 판단: 검색창 클릭 + 타이핑 + Enter는 현재 화면에서 모두 확정 가능
  - 실행: `batch` [click 검색창, type_text OpenAI, press_key ENTER]
  - [Observation Boundary 도달] -> 검색 결과 페이지 로딩 완료 -> 완료 (총 Capture 1회)

### 시나리오 4: 검색 결과에서 특정 결과 열기
- Task 1: 검색 결과 목록에서 공식 사이트 링크를 연다 (`done_when`: 사이트가 열림)
  - 관찰: 새 화면 시각 정보 필요 -> `screenshot` 1회 (`c_02`)
  - 판단: 공식 링크 위치 식별 -> `click x y --capture c_02`
  - 결과: 사이트 열림 -> 완료 (총 Capture 1회)

### 시나리오 5: 다운로드 폴더에서 파일 찾아 열기
- Task 1: 다운로드 폴더에서 `report.pdf` 파일을 찾는다 (`done_when`: 파일 경로가 확인됨)
  - 실행: `find_path "report.pdf" --root downloads` (Discovery Tool) -> `C:\...\report.pdf` 확인
- Task 2: 해당 파일을 연다 (`done_when`: 파일이 열림)
  - 실행: `open_file "C:\...\report.pdf"` (Direct Tool) -> 완료 (Capture 0회)

### 시나리오 6: 두 앱을 오가며 작업
- Task 1: 메모장으로 전환한다 (`done_when`: 메모장이 포커스됨)
  - 실행: `focus_window "notepad"` (Direct Tool) -> 완료 (Capture 0회)
- Task 2: 계산기로 전환한다 (`done_when`: 계산기가 포커스됨)
  - 실행: `focus_window "calc"` (Direct Tool) -> 완료 (Capture 0회)

### 시나리오 7: Stale Capture 복구
- 상황: GUI 클릭 시 창이 움직여 `stale_capture` 에러 발생
- 복구: `recovery_used == false` 확인 -> `recovery_used = true` 설정 -> 신규 `screenshot` 1회 수행 -> 새 좌표로 클릭 1회 실행 -> 성공

### 시나리오 8: Ambiguous Target 해소
- 상황: `focus_window "chrome"` 호출 시 일치하는 창 2개 반환 (`ambiguous_target`)
- 복구: 컨텍스트에서 원하는 탭의 구체적 제목("네이버 - Chrome")을 확인 -> `focus_window "네이버 - Chrome"` 1회 시도 -> 성공

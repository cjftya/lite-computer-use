# Lite Computer Use v2 — Advanced Production E2E Test Plan

## 1. 테스트 목적

이번 Production TC는 자연어 이해 능력을 평가하지 않는다.

핵심 평가 대상은 다음이다.

- 하나의 요청에서 5~10단계 작업을 스스로 분해하는가
- 이전 단계의 결과를 다음 단계에서 정확하게 사용하는가
- 여러 프로그램과 웹페이지를 오가도 작업 목표를 일지 않는가
- GUI 상태가 변하는 지점에서만 다시 관찰하는가
- 한 화면에서 가능한 행동은 최대한 Batch 처리하는가
- 파일 생성/수정/저장/이동/삭제 같은 실제 OS 작업을 끝까지 수행하는가
- 웹에서 메뉴, 검색, 탭 전환, 다운로드 같은 복합 GUI 작업을 수행하는가
- 중간 실패가 발생해도 같은 행동을 반복하지 않는가
- 최종 상태까지 검증하는가

---

## TC-01 — 파일 전체 생명주기

### 명령

> 문서 폴더에 `lcu-production-test` 폴더를 만들고, 그 안에 `test.txt` 파일을 만들어줘. 파일에는 `Lite Computer Use Production Test`라고 적어 저장한 다음 파일을 닫아. 다시 파일을 열어서 내용이 제대로 들어있는지 확인하고, 파일을 삭제한 뒤 휴지통까지 비워줘.

### 예상 단계

1. Documents 폴더 열기
2. `lcu-production-test` 폴더 생성
3. `test.txt` 생성
4. 메모장에서 파일 열기
5. 문자열 입력 및 저장
6. 메모장 닫기
7. `test.txt` 다시 열기
8. 내용 확인
9. 파일 삭제
10. 휴지통 비우기

### 핵심 검증

- 생성한 경로를 이후 단계에서도 유지하는가
- 저장 이후 다시 파일을 정상적으로 찾는가
- 삭제 대상이 정확한가
- 다른 파일을 실수로 삭제하지 않는가
- 휴지통 비우기 확인창을 처리하는가

---

## TC-02 — 파일 생성 → 이름 변경 → 이동 → 삭제

### 명령

> 바탕화면에 `lcu-test-a.txt` 파일을 만들고 내용에 `Phase A`라고 적어 저장해. 파일 이름을 `lcu-test-b.txt`로 바꾸고 다운로드 폴더로 이동해. 다운로드 폴더에서 파일을 다시 열어서 내용이 `Phase A`인지 확인한 다음 삭제해.

### 예상 단계

1. Desktop에서 파일 생성
2. 파일 열기
3. 내용 입력
4. 저장
5. 파일명 변경
6. Downloads로 이동
7. Downloads에서 다시 파일 찾기
8. 파일 열기
9. 내용 확인
10. 삭제

### 검증 포인트

파일 객체의 identity가 이름 및 위치 변경 이후에도 이어지는가.

---

## TC-03 — 두 앱 간 계산 결과 전달

### 명령

> 계산기를 열어서 `387 * 42 + 915`를 계산해. 결과를 복사해서 메모장을 열고 `계산 결과: ` 뒤에 붙여넣은 다음 바탕화면에 `calculation-result.txt`로 저장해. 저장된 파일을 다시 열어서 계산 결과가 제대로 들어갔는지 확인해.

### 예상 단계

1. Calculator 실행
2. 계산식 입력
3. 계산
4. 결과 복사
5. Notepad 실행
6. 텍스트 작성
7. 계산 결과 붙여넣기
8. Save As
9. Desktop에 저장
10. 다시 열어 검증

### 핵심

앱 간 Clipboard와 상태 전달.

---

## TC-04 — 파일 복제 및 내용 차별화

### 명령

> 문서 폴더에 `source.txt`를 만들고 `Original`이라고 적어 저장해. 이 파일을 복사해서 `copy.txt`를 만들고, `copy.txt` 내용만 `Modified`로 바꿔. 마지막으로 두 파일을 각각 열어서 source에는 Original, copy에는 Modified가 들어있는지 확인해.

### 핵심

- 원본과 복사본 혼동 여부
- 현재 편집 중인 파일 identity 유지
- Save / Save As 구분

---

## TC-05 — 브라우저 검색 → 결과 탐색 → 새 탭 → 정보 복사

### 명령

> 브라우저에서 네이버를 열고 `OpenAI ChatGPT`를 검색해. 검색 결과에서 OpenAI 공식 사이트를 찾아 새 탭으로 열어. 새 탭으로 이동해서 ChatGPT 관련 페이지를 찾아 들어간 다음 페이지에서 보이는 제목을 복사해서 메모장에 붙여넣어줘.

### 예상 단계

1. Naver 열기
2. 검색
3. Observation Boundary
4. 공식 OpenAI 결과 탐색
5. 새 탭으로 열기
6. 새 탭 전환
7. ChatGPT 관련 메뉴 또는 링크 탐색
8. 페이지 진입
9. 제목 선택/복사
10. 메모장에 붙여넣기

### 핵심

Web Navigation + Tab State + App Switching

---

## TC-06 — 다중 탭 비교 작업

### 명령

> 브라우저에서 Wikipedia를 열어서 Python 페이지와 Java 페이지를 각각 새 탭으로 열어. Python 탭에서 첫 번째 문단 일부를 복사하고 메모장에 `Python:` 아래에 붙여넣어. Java 탭으로 이동해서 같은 방식으로 복사한 뒤 `Java:` 아래에 붙여넣고 저장해.

### 핵심

- 현재 Browser Tab 추적
- 현재 App 추적
- 중간 Context 유지

---

## TC-07 — 웹 검색 결과를 파일로 정리

### 명령

> 네이버에서 `Windows 11`을 검색한 다음 검색 결과에서 관련된 서로 다른 페이지 두 개를 새 탭으로 열어. 각 탭의 페이지 제목을 확인하고 메모장에 한 줄씩 기록해서 `windows-links.txt`로 문서 폴더에 저장해.

### 평가

- 검색 결과 화면 해석
- 서로 다른 결과 선택
- 새 탭 관리
- Tab ↔ Notepad 반복 전환
- 결과 누적
- 마지막 저장

---

## TC-08 — 브라우저 다운로드 전체 흐름

테스트용 다운로드 URL 또는 자체 Fixture 사용 권장.

### 명령

> 테스트 사이트를 열어서 제공되는 샘플 텍스트 파일을 다운로드해. 다운로드가 끝나면 브라우저 다운로드 목록을 열어서 파일을 확인하고 파일 위치를 연 다음, 다운로드된 파일을 열어서 내용을 확인하고 삭제해.

### 예상 단계

1. 웹사이트 진입
2. Download 링크 탐색
3. 클릭
4. Download 완료 상태 확인
5. Browser 다운로드 UI 열기
6. 대상 파일 확인
7. 파일 위치 열기
8. 다운로드 파일 열기
9. 내용 확인
10. 삭제

### 핵심

Web → Browser UI → Explorer → Application 컨텍스트 이동.

---

## TC-09 — 브라우저 메뉴 및 북마크 복합 작업

### 명령

> 브라우저에서 Wikipedia를 열고 현재 페이지를 북마크에 추가해. 다른 사이트로 이동했다가 북마크 메뉴를 열어서 방금 저장한 Wikipedia 북마크를 찾아 다시 열어. 정상적으로 Wikipedia가 열리면 방금 만든 북마크를 삭제해.

### 예상 단계

1. Wikipedia 열기
2. Bookmark 추가
3. 다른 사이트 이동
4. Browser 메뉴 열기
5. Bookmark UI 진입
6. 방금 생성한 항목 탐색
7. 북마크 열기
8. 페이지 확인
9. Bookmark 메뉴 재진입
10. 테스트 Bookmark 삭제

### 핵심

브라우저 메뉴/북마크 조작 검증.

---

## TC-10 — 웹사이트 내부 다단계 Navigation

### 명령

> GitHub 홈페이지를 열어서 `microsoft/vscode` 저장소를 찾아 들어가. Issues 탭으로 이동한 다음 검색창 또는 필터를 이용해서 `bug`가 포함된 이슈들을 표시하고, 그중 하나를 새 탭에서 열어 제목을 복사해서 메모장에 저장해.

### 핵심

한 웹사이트 내부에서 UI state가 여러 차례 바뀌는 작업.

---

## TC-11 — 웹 입력 Form Fixture

실제 서비스에 부작용을 주지 않도록 전용 Fixture 페이지를 사용하는 것이 좋다.

Fixture 구성 예시:

- Name 입력
- Email 입력
- Country Dropdown
- Checkbox 3개
- Continue
- 2단계 Form
- Confirm
- 완료 화면

### 명령

> 테스트 폼을 열어서 이름은 `LCU Production`, 이메일은 `lcu@example.com`으로 입력하고 국가를 South Korea로 선택해. 옵션 B와 C를 체크하고 다음 단계로 넘어가서 메모에 `Phase 2 production test`라고 입력한 다음 제출해. 마지막 완료 화면까지 확인해.

### 핵심

- 한 화면 내 Action Batch
- Continue 이후 Observation Boundary
- 다음 화면에서 상태 재판단

---

## TC-12 — 동적 메뉴 / Modal / Confirm Fixture

Fixture:

- Settings 버튼
- Settings Popup
- Advanced
- Toggle
- Apply
- Confirm Modal
- Success message

### 명령

> 테스트 페이지 설정을 열고 Advanced 메뉴로 들어가서 Test Mode를 켜. Apply를 누르고 확인 창에서 Confirm을 선택한 뒤 Test Mode가 활성화됐다는 메시지가 나오는지 확인해.

### 핵심

Observation Boundary 판단 능력 검증.

---

## TC-13 — 파일 검색 + 압축 + 압축 해제

전용 테스트 파일만 사용.

### 명령

> 문서 폴더에 `lcu-archive-test` 폴더를 만들고 `a.txt`, `b.txt`, `c.txt` 세 파일을 만들어. 세 파일을 ZIP으로 압축한 다음 원본 세 파일을 삭제해. ZIP 파일을 풀어서 세 파일이 다시 생성되는지 확인하고 테스트 폴더 전체를 삭제해.

### 검증

- 다중 선택
- Context menu
- Archive UI
- Delete
- Extract
- 최종 Verification

---

## TC-14 — 파일 이름 충돌 처리

### 사전 상태

Downloads에 `result.txt` 존재.

### 명령

> 바탕화면에 새로운 `result.txt`를 만든 뒤 다운로드 폴더로 이동해. 같은 이름의 파일이 이미 있다면 덮어쓰지 말고 새 파일 이름을 `result-new.txt`로 바꿔 이동해. 이동된 파일이 있는지 확인해.

### 핵심

예상하지 못한 Modal / Conflict 상태 대응.

---

## TC-15 — Explorer + Browser + Editor 종합 TC

### 명령

> 문서 폴더에 `lcu-web-test` 폴더를 만들어. 브라우저에서 Wikipedia의 Artificial intelligence 페이지를 열고 페이지 제목을 복사해서 메모장에 붙여넣어 `ai.txt`로 방금 만든 폴더에 저장해. 그 다음 브라우저로 돌아가서 Machine learning 페이지를 열고 제목을 복사해서 같은 파일의 다음 줄에 추가해. 저장 후 파일을 닫았다가 다시 열어서 두 줄이 모두 있는지 확인해.

### 핵심

Explorer + Browser + Editor를 오가는 장시간 상태 유지.

---

## TC-16 — 10단계 종합 Stress Test

### 명령

> 바탕화면에 `LCU-Production` 폴더를 만들어. 그 안에 `result.txt`를 만들고 `Start`라고 입력해서 저장해. 브라우저를 열어 Wikipedia에서 Computer vision을 검색하고 해당 페이지 제목을 복사해. 다시 result.txt를 열어서 다음 줄에 제목을 붙여넣고 저장해. 파일 이름을 `final-result.txt`로 바꾼 다음 문서 폴더로 이동해. 이동된 파일을 다시 열어서 Start와 Wikipedia 제목이 둘 다 있는지 확인하고 마지막으로 테스트 파일과 폴더를 모두 삭제해.

### 핵심 평가

- Folder creation
- File creation
- Text input
- Save
- Browser navigation
- Web GUI
- Clipboard
- App switching
- File rename
- File move
- Reopen
- Final verification
- Cleanup

---

# 3. 웹 검증 구성 원칙

## A. Live Web TC

사용 예:

- Naver
- Wikipedia
- GitHub
- OpenAI

검증 대상:

- 실제 사이트의 예측 불가능한 Layout
- Browser Navigation
- Tab
- Search
- Menu
- Dynamic Content

실제 Production TC는 이쪽을 중심으로 수행한다.

---

## B. Production Web Fixture — 별도 보조 검증 세트

Web Fixture는 위 Production TC를 대체하지 않는다.

목적은 외부 사이트 UI 변경의 영향을 제거하고 동일 조건에서 반복 측정하기 위한 것이다.

예:

```text
fixture/
 ├ form.html
 ├ menu.html
 ├ dynamic.html
 ├ download.html
 ├ tabs.html
 └ modal.html
```

검증 요소:

- Dropdown
- Modal
- Checkbox
- Search Results
- Dynamic UI
- Download
- Pagination
- Confirmation
- Delayed Loading

Lite Computer Use는 Fixture에서도 DOM 자동화 없이 Vision + Mouse/Keyboard만 사용한다.

Fixture는 Production TC 안정화 이후 별도 단계로 추가해도 된다.

---

## 4. Production TC 평가 기준

## A — Production Grade

- 목표 완수
- 사용자 개입 0
- 잘못된 조작 0
- 의미 없는 재시도 0
- Observation Boundary 정확
- Screenshot 최소화
- 이전 단계 결과 정확히 전달

## B — Functional

- 최종 목표 성공
- 작은 불필요 Capture 존재
- 가벼운 비효율 존재
- Recovery 최대 1회

## C — Unstable

- 최종 성공
- 여러 번 잘못 클릭
- 화면을 계속 재확인
- 불필요한 재시도
- 상당한 Token 낭비

## FAIL

- 작업 중단
- 잘못된 파일/대상 변경
- 단계 누락
- Context 상실
- 무한 탐색
- 사용자가 개입해야 성공

---

## 5. 기록할 Metrics

각 TC마다 다음을 기록한다.

```text
Result:
Execution Time:
Total Tokens:

Total Tool Calls:
Screenshot Count:
Observation Boundary Count:
Unnecessary Screenshots:

Batch Count:
Actions per Batch:

Wrong Actions:
Retries:
Recovery Used:

User Intervention:
Final State Verified:
Cleanup Completed:
```

핵심 KPI:

```text
End-to-End Completion Rate
Average Screenshots / Workflow
Wrong Action Rate
Tokens / Successful Workflow
```

---

## 6. 1차 Production Gate

우선 실행 권장 TC:

- TC-01 파일 전체 생명주기
- TC-03 앱 간 계산 결과 전달
- TC-05 웹 검색 + 새 탭 + 정보 복사
- TC-08 웹 다운로드 전체 흐름
- TC-09 브라우저 북마크 복합 작업
- TC-11 다단계 Web Form
- TC-14 파일 이름 충돌 처리
- TC-16 10단계 종합 Stress Test

이 8개를 안정적으로 통과하면 단순 GUI 실행이 아니라 여러 상태를 이어 처리하는 Agent 수준의 검증으로 볼 수 있다.

---

## 7. 안전 원칙

파일 삭제, 이동, 압축, 휴지통 비우기 TC는 전용 테스트 파일과 테스트 폴더만 대상으로 한다.

기존 사용자 파일이나 실제 업무 파일을 Production TC에 사용하지 않는다.

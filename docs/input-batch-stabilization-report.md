# 입력·배치 안정화 결과 (2026-09-25)

- 기준 및 작업 시작 HEAD: `bb7b38dd5bd6951fc0779601712de5287435e64d`; 시작 작업 트리 깨끗함.
- 환경: Windows NT 10.0.26200.0, Python 3.13.15, PowerShell `Console`.
- `launch_context`: session 10, `input_desktop.attached=false` (프로세스 데스크톱은 `CodexSandboxDesktop-...`, 입력 데스크톱은 `Default`). 따라서 실제 GUI 입력·드래그·웹 작업은 수행하지 않았다. 코드 수정 및 모의 검증 완료 / Windows 실환경 미검증.
- 관련 테스트 기준선: `python -m pytest tests/test_v2_batch.py tests/test_v2_input_desktop.py tests/test_v2_windows.py -q` → 27 passed.
- 최종: `python -m pytest -q -p no:cacheprovider --basetemp .pytest-run-final2` → 177 passed in 4.58s. 기본 임시 폴더를 사용한 첫 전체 실행은 Windows Temp의 접근 거부로 154 passed / 19 setup errors였고, 작업 공간 임시 폴더를 지정한 재실행에서는 모두 통과했다.

| 항목 | 수정 및 재현 근거 | 회귀 테스트 | Windows 실환경 | 남은 제한 |
|---|---|---|---|---|
| F1 입력 실패 감지 | `windows.py`: SendInput 반환 0을 `input_dispatch_failed`로 전파; hotkey 역순 해제, 단일 키 해제 재시도. 기존 경로는 0을 무시했다. | API 0, hotkey 중간 실패, 해제 실패, 배치 중단 통과 | 미실행 | OS 삽입 성공은 앱 반영·저장 확인이 아님 |
| F2 드래그 해제 | `windows.py`: 진입 전 FAILSAFE 값을 유지하고, 이동 실패·취소에도 mouseUp 시도. 기존 경로는 FAILSAFE=False를 남겼다. | 정상, 이동 실패, 해제 동시 실패 통과 | 미실행 | 실패한 mouseUp은 강제로 복구할 수 없음 |
| F3 배치 사전 검증 | `batch.py`: 키 목록/지원 키, hwnd, capture, 유한 좌표·duration·delay 검증. 기존 `[null]`은 뒤쪽 실행 시점에 실패했다. | 뒤쪽 정적 오류의 zero dispatch 및 실행 실패의 부분 결과 통과 | 미실행 | 창·포커스·파일·capture 상태는 각 실행 시점에 확인 |
| F4 결과 보존 | `batch.py`: `results`에 성공 액션의 원래 결과 및 index/action 유지. 기존 코드는 값을 버렸다. | open_app 메타데이터의 성공·부분 실패 결과 통과 | 미실행 | 같은 배치 안에서 이전 결과를 변수로 참조할 수 없음 |
| F5 문자 입력 | `windows.py`: CRLF를 한 Enter로, 보충 평면 문자를 UTF-16 surrogate 순서로 전송; 단독 surrogate 사전 거부. 기존 경로는 CRLF에 Enter 두 번, 이모지에는 절단된 WORD를 보냈다. | CRLF, emoji, 한글·영문, 단독 surrogate 통과 | 미실행 | Enter/Tab의 앱별 의미는 그대로 다름 |

문서: `README.md` 및 루트·`.agents`·`.claude`의 세 `SKILL.md` 사본에 정적 오류/부분 실행, 결과 보존, 입력 성공 의미를 반영했다. 앱 실행 경로는 변경하지 않았다. 기존 launch 테스트를 포함한 전체 모의 테스트는 통과했다.

실환경 계획의 편집기 문자열 비교, 드래그 후 클릭, 웹 폼 다단계 작업, 브라우저 검색·복사, 실제 GUI 배치 zero dispatch, 대표 앱 실행 회귀는 모두 미실행이다. 고정 fixture나 실제 사이트의 성공률, 도구 호출·캡처·복구 횟수와 시간·토큰 절감은 측정하지 않았다. 입력 데스크톱에 연결된 호스트에서만 해당 결과를 추후 기록할 수 있다.

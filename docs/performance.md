# v1.3 performance benchmark

Measure v1.3 on an interactive Windows 11 desktop through the same host agent and model used for normal work. Keep display layout, scale, app state, network conditions, and prompts stable between baseline and candidate runs. Run each scenario at least five times.

Speed is secondary to task success and safety. If an optimization reduces reliability, restore the slower stable setting.

## Metrics

Record:

- success or failure;
- total screenshots;
- active-window, primary-screen, and all-screen screenshot counts;
- model visual-reasoning turns;
- CLI invocations;
- retry and fallback counts;
- each response's `meta.durationMs`;
- end-to-end duration;
- host-reported input, image, and total tokens when available.

Lite Computer Use does not estimate model token counts. Do not treat PNG file size as vision-token usage.

## Scenarios

| ID | Request | Expected route | Screenshot target |
|---|---|---|---|
| B1 | 계산기 열어줘 | `launch_app calculator` | 0 |
| B2 | 메모장 열어줘 | `launch_app notepad` | 0 |
| B3 | 이미 열린 크롬으로 이동해줘 | `focus_window`, list only if needed | 0 |
| B4 | 네이버 열어줘 | `open_url` | 0 |
| B5 | 크롬에서 네이버를 열고 OpenAI를 검색해줘 | direct search URL or deterministic sequence | 0–1 |
| B6 | 메모장에 한글 테스트라고 입력해줘 | launch/focus plus deterministic input | 0 |
| B7 | 현재 화면을 보고 확인 버튼 눌러줘 | active-window screenshot then click | 1 unless result needs interpretation |
| B8 | 이 PDF를 열고 인쇄 화면까지 띄워줘 | `open_file` then `hotkey CTRL P` | 0–1 |

Use harmless local test data. Opening the print dialog is allowed; do not submit a print job as part of the benchmark.

## Result template

| Version | Scenario | Run | Success | Screenshots A/P/All | Vision turns | CLI calls | Retries | Fallbacks | Local ms | End-to-end ms | Input/image/total tokens | Notes |
|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|---|
| baseline | B1 | 1 | | | | | | | | | | |
| v1.3 | B1 | 1 | | | | | | | | | | |

`A/P/All` means active-window, primary-screen, and all-screen captures.

## Input and pause tuning

Test representative short and long strings in Notepad and at least one Chromium text field:

- ASCII;
- Korean;
- mixed Korean and ASCII;
- newline and tab;
- emoji/surrogate pairs;
- 500+ characters.

Compare default zero interval with `--interval 0.01` only when needed. Confirm the 80 ms PyAutoGUI pause across click, double-click, scroll, hotkey, and focus-then-key actions. Record dropped, duplicated, reordered, or delayed input before considering a lower pause.

## Acceptance

Accept v1.3 when:

- B1–B4 and B6 use zero screenshots by default;
- B7 begins with an active-window screenshot;
- deterministic multi-step work uses fewer CLI invocations;
- repeated screenshots between deterministic steps are gone;
- success rate does not fall below baseline;
- Korean input, focus, active-window coordinates, and multi-monitor coordinates remain reliable;
- the existing confirmation and prohibited-action boundaries remain unchanged.

# v1.4 execution reliability and latency benchmark

Measure on an interactive Windows 11 desktop through the same host/model used for normal work. Keep display layout, scale, app state, network, and prompts stable. Run each scenario at least five times. Compare success and safety first; reject a faster route if either regresses.

## Metrics

Record success, cold/warm app-cache state, CLI calls, screenshots by scope, original and output pixels, vision turns, retries/fallbacks, each `meta.durationMs`, end-to-end time, and host-reported input/image/total tokens when available. Lite Computer Use does not infer model token counts from PNG size.

## L1–L10 scenarios

| ID | Request | Expected route | Main comparison |
|---|---|---|---|
| L1 | 계산기 열어줘 | registered `launch_app` | one CLI call, zero vision |
| L2 | 등록되지 않은 Discord 열어줘 | `launch_app` via installed-app index | cache hit, no Start Menu GUI |
| L3 | 제목에 앱명이 없는 열린 Chrome 창으로 이동해줘 | process-aware `focus_window` | no speculative screenshot/list loop |
| L4 | 현재 화면의 큰 확인 버튼 눌러줘 | scaled active-window preview, then click | resolution, latency, and click success |
| L5 | 작은 체크박스를 찾아 눌러줘 | 0.5 preview, then scale-1 region | pixels/tokens vs repeated full captures |
| L6 | 메모장 열고 테스트라고 입력해줘 | one launch/wait/type sequence | one CLI process, zero vision |
| L7 | Chrome 주소창에 OpenAI 입력 후 Enter | one focus/hotkey/type/key sequence | one CLI process, zero vision |
| L8 | 알려진 절대 PDF 열기 | one direct `open_file` | one CLI call, no GUI-library initialization, no retry |
| L9 | Downloads에서 계약서 찾기 | bounded root `find_file`, choose, direct open | incomplete state and visited/time budget |
| L10 | 크롬 별칭 창에 한글 입력 | wait, verified focus, targeted input | no input before foreground verification |

Use harmless local data. Do not submit, purchase, install, delete, overwrite, approve UAC, or change security settings during measurement.

## Result template

| Version | Scenario | Run | Success | Cache | CLI calls | Screenshots A/P/All/R | Original → output pixels | Vision turns | Retries/fallbacks | Local ms | End-to-end ms | Input/image/total tokens | Notes |
|---|---|---:|---|---|---:|---|---|---:|---|---:|---:|---|---|
| v1.3 | L1 | 1 | | cold | | | | | | | | | |
| v1.4 | L1 | 1 | | cold | | | | | | | | | |

`A/P/All/R` means active-window, primary-screen, all-screen, and region captures. For scaled images, compute output-pixel ratio as `(width × height) / (originalWidth × originalHeight)`; a 0.5 scale should be about 25% of the pixels.

## Focused checks

- L1: confirm the configured registry alias remains the exact-match fast path with one CLI call and no vision.
- L2: verify `%LOCALAPPDATA%\LiteComputerUse\cache\apps.json` is reused before 24 hours and rebuilt when stale or `--refresh` is passed. Record `start-menu` or `app-paths` source and confirm ambiguous partial matches fail safely.
- L3: confirm `list_windows` reports only process basenames and that a protected-process lookup failure leaves the window in the list with `process:null`.
- L4/L5: compare identical desktop state at scale 1, 0.5, and optionally 0.25. Confirm the preview supports target selection and the full-scale region supports precise coordinates.
- L6: confirm all sequence steps validate before launch and later steps never run after a failure. Test Korean, mixed ASCII, newline/tab, emoji, and 500+ characters; use `--interval 0.01` only if the target app drops zero-delay input.
- L7: confirm focus and keyboard actions remain deterministic without a visual turn.

## Acceptance

Accept v1.4 when:

- all L1–L7 scenarios match or exceed the v1.3 success rate;
- registered apps retain a one-call fast path, while warm indexed lookup avoids rescanning and launches uniquely matched installed apps without manual config;
- process-aware window focus avoids screenshots without increasing ambiguous selections;
- L6/L7 use one CLI process and report ordered, fail-fast results;
- scaled previews materially reduce output pixels/image tokens, while precise actions use a scale-1 region;
- L7 and other deterministic scenarios use zero screenshots by default;
- confirmation requirements, fail-safe behavior, and prohibited actions remain unchanged.
- known absolute paths run once from different working directories and never resolve relative to the host project;
- direct opens do not initialize GUI libraries and report dispatch as unverified;
- identical failed host calls are not repeated, and any alternate route is tied to a different recoverable cause.

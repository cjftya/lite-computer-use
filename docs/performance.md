# Lite Computer Use v2 Performance & Token Efficiency Guide

Lite Computer Use v2 is designed to minimize model token usage and round-trip latency through deterministic direct tools, image compression presets, and coordinate auto-mapping.

---

## Benchmark Results (2560x1080 Monitor)

| Capture Mode | Target | Output Dimensions | File Size | Capture Latency | Token / Size Reduction |
|---|---|---|---|---|---|
| **Raw Fullscreen PNG** | Screen | 2560 × 1080 | 671 KB | ~360 ms | Baseline (0%) |
| **v2 Normal WebP (Default)** | Screen | 1600 × 675 | 84 KB | ~306 ms | **-87.5% reduction** |
| **v2 Fast WebP** | Screen | 1024 × 432 | 33 KB | ~260 ms | **-95.1% reduction** |
| **v2 Detail Region** | 400x300 sub-box | 400 × 300 | 6 KB | ~88 ms | **-99.1% reduction** |

---

## Token Saving Strategies in v2

### 1. Direct Tools First (Zero-Vision)
Whenever an action can be performed deterministically, avoid visual turns completely:
- `open_app chrome` instead of clicking taskbar/desktop icons (0 tokens)
- `open_url https://www.naver.com` instead of address bar clicking + typing (0 tokens)
- `open_file <path>` instead of browsing file explorer (0 tokens)
- `focus_window --hwnd <int>` instead of visual window hunting (0 tokens)

### 2. Fast Overview -> Detail Recapture (`from-capture`)
When exploring an unknown UI:
1. Capture overview with `quality: fast` (33 KB, ~1000 tokens).
2. If a small button or text is ambiguous, request a zoomed sub-region using:
   ```powershell
   py -3.13 scripts\lcu.py screenshot --from-capture <id> --region <x> <y> <w> <h> --quality detail
   ```
   This captures only the required area in lossless detail (~6 KB, ~200 tokens) without re-sending the whole screen.

### 3. Batch Sequences with Fail-Fast
Combine multiple planned actions into a single `batch` call:
- One CLI turn executes click, text input, key press, and clipboard actions.
- Reduces multi-step round trips from N tool turns to 1 tool turn.
- Fails fast on the first error without repeating stale operations.

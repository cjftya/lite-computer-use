# Windows launch review fixes — 2026-09-23

## Baseline and scope

- Before: `f303059cd1d04f0b73c299a8ae2b378374e1519e` (clean main).
- After: see the main merge commit for this report.
- Runtime for local checks: Linux, Python 3.12; no interactive Windows session was available.
- Before changes: pytest collected 127 tests; 91 passed, 36 failed on Linux. Most failures directly import Windows-only modules or require a Windows desktop. The stale-target test also failed independently on Linux.

## Fixes and evidence

| Issue | Files | Result |
|---|---|---|
| Chrome title impersonates VS Code, or same executable basename at another path | `apps.py`, `windows.py` | Matching requires a window PID, image path, session and the resolved full path when available. No title-only success. Recheck HWND, PID, creation time and identity before focus. Synthetic positive and negative tests pass. |
| Shell activation marked as directly owned | `apps.py`, `ownership.py` | Only a `process` backend with complete direct identity and trusted snapshots can write ownership. Ledger version 2 rejects unverifiable old version 1 records. Shell/URI/shortcut/packaged receipts never grant termination authority. |
| Unknown receipt becomes false | `apps.py` | Shared tri-state conversion preserves true/false/null in `app_status`; observation state is saved immediately after dispatch. `app_status` does not dispatch or focus. |
| COM and post-dispatch exceptions | `win_launch.py` | Shell caller initializes STA COM and releases it; activation exceptions remain unknown, confirmed rejection remains rejected, accepted activation stays accepted after identity failure. Handles are closed. Direct process creation is likewise preserved as accepted after identity lookup failure. |
| New function tests absent from CI | `.github/workflows/test.yml`, `tests/test_v2_launch_review_fixes.py` | pytest collection and 47 focused launch contract and safety tests are configured on both platforms. Interactive GUI validation remains manual. |
| Agent guidance | root and both installed `SKILL.md` copies, `README.md` | Three skill copies match. Documents identity uncertainty, ownership, status tri-state and no-relaunch rule. |

## Local verification

- `python -m pytest -q tests/test_v2_launch_review_fixes.py`: **20 passed**.
- `python -m pytest -q tests/test_v2_launch_review_fixes.py tests/test_v2_app_launch_redesign.py tests/test_v2_launch_safety_remediation.py tests/test_v2_cli_safe_launch.py`: **47 passed**.
- `python -m pytest --collect-only -q tests`: **147 collected**, including the new function tests.
- `python -m compileall -q scripts tests` and `git diff --check`: passed.
- The full Linux suite remains unsuitable as a green gate: **105 passed, 42 failed**. Before the patch it had 91 passed, 36 failed. Most failures import Windows-only modules or require a desktop. Several older mocked launch tests omit the identity now required; these tests still need updated fixtures. The full suite is not a CI gate in this change. A green Windows CI result has **not** been observed as of writing.
- Windows GUI cold/reuse tests for Notepad, Calculator, Paint, Settings, VS Code, Chrome/PWA, shortcut and URI, and COM activation smoke: **not run**. A packaged app is only confirmed when its process AUMID can be verified; inaccessible identity remains unconfirmed. Browser/PWA distinction is intentionally unconfirmed when the shared process and title are the only evidence.

## Practical limit

This patch prevents false ready/ownership decisions under the modeled conditions. It does not establish that every Windows package or browser window can be positively identified on a real desktop. The existing Windows live test plan should be run before claiming general-purpose launch reliability.

## Git

Implementation committed and pushed to main as requested; record the resulting SHA in the final delivery. No existing user files or live windows were altered by local tests.

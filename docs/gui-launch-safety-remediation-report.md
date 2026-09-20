# GUI Launch Safety Remediation Report

## 1. Baseline / Tested SHA

- Baseline: `ada36eebee5b116cfe8c07fb204c1d51df93417b`
- Implementation branch: `fix/gui-launch-safety-remediation`
- Linux verification cannot replace Windows acceptance.

## 2. Root Cause

- Confirmed in code: selected `NODE_*`, `VSCODE_*`, and other prefix-matched values were emitted raw.
- Confirmed in code: snapshot failure and incomplete collection could be treated as an empty trustworthy baseline.
- Confirmed in code: a new same-name PID could be classified as owned and force-terminated without dispatcher causality.
- Confirmed in code: window enumeration errors were treated as “no other window,” and `OpenProcess` failure could be reported as successful termination.
- Hypothesis only: inherited Electron/VS Code variables cause the Antigravity Bash launch failure.

## 3. PowerShell vs Antigravity Evidence

BLOCKED — this implementation environment is Linux. Run the two `launch_context` commands in section 4.1 of `docs/windows-smoke-tests.md` on the same Windows account, privilege level, desktop, and installation.

## 4. Environment-only A/B Result

BLOCKED — the repository still needs the controlled original-env versus exact-drop-env Windows probe before the environment policy can be called confirmed.

## 5. Ownership Evidence / Protected Processes

- Only a live identity captured from the exact `subprocess.Popen` dispatcher can become an owned candidate.
- Shell, shortcut, URI, broker, child-by-name, and unrelated same-name processes remain unowned.
- An untrusted baseline or per-attempt snapshot disables ownership and rollback.
- Caller-supplied `--owned-processes` data is intersected with revalidated ledger evidence.

## 6. Termination Safety / PID-HWND Reuse

- Termination requires creation time, image/name, session, current-session match, identity match, and a successful window-ownership query.
- The terminating process handle is opened with query and terminate rights; identity is re-read and `TerminateProcess` uses that same handle.
- `OpenProcess` failure and window enumeration failure are fail-closed outcomes, not success or “no windows.”
- Non-Windows `os.kill` is not a fallback for the Windows cleanup policy.

## 7. Dispatcher / Wait / Candidate Deduplication

- Dispatcher now returns the immediate process identity when available.
- Grace wait requires that exact dispatcher identity to remain live; an unrelated new PID is insufficient.
- Candidate path/argument deduplication is not remediated in this phase because the required Windows evidence gate has not been passed.

## 8. Chrome/PWA Result

BLOCKED — title matching remains provisional and needs the live GPT PWA versus ordinary Chrome test.

## 9. Ledger Concurrency / Failure Handling

- Identity lookup errors preserve records as `validation_status=unknown` and prevent authorization.
- Full cross-process locking, bounded corruption reporting, and schema expansion remain Phase 6 work after Windows launch validation.

## 10. Unit / Windows Integration / Full Pytest Result

- Platform-neutral launch-safety tests: **18 passed** with `python -m pytest -q tests/test_v2_cli_safe_launch.py tests/test_v2_launch_safety_remediation.py`.
- Selected process lifecycle/safety regressions: **7 passed**.
- Full Linux collection: **86 passed, 34 failed**. The 34 failures are the same count as baseline and are Windows-only failures caused by unavailable `pywin32`, `os.startfile`, and interactive desktop APIs.
- Windows full pytest: BLOCKED / not run.

## 11. Repetition Tests / Independent Residual Counts

BLOCKED — Notepad 20x, Paint 5x, Calculator 5x, VS Code cold/handoff, and Chrome/PWA repetitions require the target Windows session.

## 12. Remaining Limitations / Blocked Gates

- Same-host PowerShell/Antigravity context capture.
- Controlled environment-only A/B probe.
- VS Code success from both shells.
- Chrome/PWA live identity validation.
- Candidate deduplication, handoff-aware bounded wait, child lineage, and locked ledger phases.
- Windows full pytest and residual inspection.

## 13. Final Review Findings

Pending Windows evidence. No completion claim is made for the full remediation plan.

## 14. Commit / Push Status

Do not merge to `main` until every mandatory Windows gate in the plan passes. Preserve this work on the remediation branch.

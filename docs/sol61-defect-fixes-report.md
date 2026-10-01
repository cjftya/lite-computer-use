# F1-F4 defect fixes report

Validation date: 2026-10-01 (Asia/Seoul).

## Baseline and final state

- Branch: `main`. Starting and validation HEAD: `1c1807f498739f251ae1cdd2f3b2c14f7651c0e0`.
- Starting working tree: clean. `git fetch origin` succeeded and confirmed the same `origin/main` SHA. The initial sandbox fetch could not write `.git/FETCH_HEAD`; the authorized fetch succeeded.
- Environment: Windows 11 build 26200, Python 3.13.15. No dependency changes or installations.
- At validation time, changes were local and uncommitted; no push or merge had been performed. The user subsequently authorized committing and pushing these changes to origin/main. The delivery commit is the commit containing this report.
- Changed files: `scripts/lcu/capture.py`, `scripts/lcu.py`, `scripts/lcu/direct.py`, `tests/test_defect_fixes.py`, `tests/test_v2_capture.py`, `.github/workflows/test.yml`, `README.md`, and this report.
- None of F1-F4 was already fixed. All four were reproduced on the baseline.

## Fixes and evidence

| Defect | Reproduction and cause | Change | Regression tests |
|---|---|---|---|
| F1 | Expired or excess metadata unconditionally unlinked `path`, deleting explicit outputs | Add `cache_owned`, default false for legacy metadata. Require ownership, generated filename, direct internal location, and no symlink/junction or redirected ancestors. Protect reused/shared output paths | `test_user_output_preserved`, `test_owned_capture_pruned`, `test_legacy_external_and_malformed_entries`, `test_shared_output_protects_old_owned_path`, `test_redirected_owned_path_preserved`, `test_screenshot_records_ownership` |
| F2 | Catching argparse SystemExit and returning made invalid arguments exit 0 without JSON | Exit 2 with one `invalid_arguments` JSON on stdout. Preserve help and exit 0. Use recognized first command as action, otherwise `unknown` | `test_cli_parse_error`, `test_cli_help`, `test_cli_parse_does_not_dispatch`, `test_runtime_and_batch_cli_errors` |
| F3 | False from `webbrowser.open` after primary failure was ignored | False and exceptions return `dispatch_failed`. No fallback after primary success; at most one fallback call | `test_open_url_dispatch`, `test_url_batch_stops_on_failure`, existing non-HTTP(S) rejection tests |
| F4 | Index errors were swallowed, direct overwrite could corrupt JSON, and images were deleted before persistence | Write complete JSON to a same-directory temporary file, flush/fsync, then `os.replace`. Report `capture_index_save_failed`. Delete old images only after replacement. Clean failed-call owned images while preserving explicit output | `test_atomic_save_failure`, `test_screenshot_save_failure`, `test_atomic_roundtrip_coordinates` |

Legacy metadata loads without the new field. A malformed item is skipped independently instead of discarding other valid items. An external path is preserved even with an ownership flag. Pathlib comparisons follow host Windows case semantics. Symlink and redirected-ancestor checks were exercised using mocks.

The existing capture tests now isolate both index and capture directory under tmp_path. Their pruning fixture uses generated filenames and explicit ownership. New screenshot acquisitions and URL launches are mocked. No test accesses the user's capture cache or saved images. Metadata retention remains the newest 50 entries and 24 hours; legacy image ownership remains unknown, so such image files are preserved.

## Validation

| Run | Passed | Failed | Skipped | Notes |
|---|---:|---:|---:|---|
| Baseline defect tests | 9 | 19 | 0 | Initial 28 cases reproduced F1-F4 |
| First post-fix capture/defect run | 36 | 1 | 0 | Test assertion used positional argument while existing batch calls `text=`; corrected the assertion |
| Expanded capture/defect run | 41 | 0 | 0 | Ownership and redirect boundaries included |
| Final full Windows test suite with clipboard isolation harness | 239 | 0 | 0 | Existing 207 plus 32 new tests; 7.68 seconds |
| Portable CI selection plus new file, executed locally on Windows | 163 | 0 | 0 | 3.39 seconds; not a Linux execution result |

Baseline command:

```powershell
py -3.13 -m pytest -q tests/test_defect_fixes.py -p no:cacheprovider --basetemp=.test-tmp-defects
```

Targeted command:

```powershell
py -3.13 -m pytest -q tests/test_defect_fixes.py tests/test_v2_capture.py -p no:cacheprovider --basetemp=.test-tmp-targeted
```

Full-suite command was `py -3.13 .test-validation/run_suite.py`. That temporary harness called `pytest.main(['-q', 'tests', '-p', 'no:cacheprovider', '--basetemp=.test-tmp-suite'], plugins=[ClipboardIsolation()])`.

Only `test_cli_clipboard` and `test_cli_batch_fail_fast` had their `run_lcu` helper replaced by the plugin. The replacement started a fresh Python subprocess, patched only `lcu.windows.set_clipboard/get_clipboard` to use an isolated JSON file, and executed the real CLI via `runpy.run_path`. Existing assertions, parsing, dispatch and batch behavior ran normally. The user's clipboard was neither read nor changed. This validates those two CLI contracts with mocked clipboard storage, not actual clipboard OS integration. Temporary harness and test data were removed after validation.

Portable selection and final checks:

```powershell
py -3.13 -m pytest -q tests/test_v2_orchestration.py tests/test_v2_batch.py tests/test_input_batch_stabilization.py tests/test_v2_input_desktop.py tests/test_v2_launch_review_fixes.py tests/test_v2_app_launch_redesign.py tests/test_v2_launch_safety_remediation.py tests/test_v2_cli_safe_launch.py tests/test_defect_fixes.py -p no:cacheprovider --basetemp=.test-tmp-portable
py -3.13 -m compileall -q scripts tests
git diff --check
```

Compileall and diff check exited 0. The Linux CI selection includes the new test file; the full Windows CI command is unchanged. Remote CI and a separate Linux host were not run. No baseline full-suite result is claimed because only the baseline defect tests were run before implementation.

## GUI checks and limitations

Actual `py -3.13 scripts/lcu.py launch_context` reported current desktop `CodexSandboxDesktop-341c42b4e74759981e733b917b1a546b`, input desktop `Default`, and `input_desktop.attached=false`. Per the supplied plan, no alternate launcher or repeated desktop workaround was attempted. Real disposable-window captureId click, real explicit-output screenshot, and browser URL smoke checks were not run. Argument error/help behavior was verified through actual CLI subprocesses.

Normal screenshot responses, coordinate mapping, region and negative virtual desktop handling, stale capture errors, and batch partial-result contracts remain intact. App launch and process ownership implementation was not changed. URL success means dispatch of a launch request, not verified page loading.

Atomic replacement improves sequential persistence; it does not solve concurrent CLI read-modify-write races. Real model-driven web E2E and actual clipboard OS integration remain unverified. No new automation features, retries, telemetry, redesign, or SKILL.md edits were added. No additional out-of-scope product defect was established.

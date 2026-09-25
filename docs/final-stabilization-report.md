# Lite Computer Use final stabilization report

Date: 2026-09-25 (Asia/Seoul)

## State and environment

- Starting HEAD: `8620316353de643a1b55ca2b9374a87d174ab8e3` on `main`. The working tree was clean before the baseline run. Local verification was completed on that HEAD with uncommitted changes; the approved commit and CI outcome are recorded in the post-push section below.
- Environment: Windows, Python 3.13.15 (`C:\Program Files\Python313\python.exe`), session 12. `launch_context` reported `WinSta0`, process desktop `CodexSandboxDesktop-b0724d40e82c2828d69964903f8a1720`, input desktop `Default`, and `input_desktop.attached=false`.
- Baseline: `py -3.13 -m pytest -q -p no:cacheprovider --basetemp .pytest-baseline` → **177 passed**. Dedicated pytest temporary directories were removed after testing.

## Fixes and evidence

| Item | Reproduced cause | Change | Relevant verification |
|---|---|---|---|
| F1 browser windows | The actual default Edge and Firefox entries lacked `window_match`, so `window_match_status` returned `insufficient_evidence` after identity checks. | Added process and ordinary browser title rules in `config/apps.yaml`; `scripts/lcu/apps.py` now requires the observed browser process field. Existing image path, session and Chrome PWA checks remain. | `test_default_browser_rules_check_identity_and_title`, `test_default_browser_existing_window_is_reused_without_dispatch`, `test_default_browser_new_window_observation_uses_same_rules`, and existing Chrome/PWA tests. Normal and wrong path/process/session/title/missing evidence cases pass. Both reuse and new-window observation call the same matcher. Browser titles were not verified on a live desktop. |
| F2 virtual keys | `resolve_key` used `ord()` for every single character, admitting text and punctuation as virtual keys. | Limited single characters to ASCII A–Z/a–z/0–9 while retaining named keys and aliases. Error directs ordinary characters to `type_text`. Direct hotkeys already pre-resolved all keys; batch already validates all actions before dispatch. | `test_supported_virtual_keys`, `test_unsupported_virtual_keys_are_rejected`, `test_late_invalid_hotkey_does_not_press_modifier`, `test_late_invalid_batch_key_prevents_every_dispatch`, plus existing Unicode/CRLF, SendInput failure, key release and partial-result tests. |
| F3 drag cleanup | `mouseDown` was outside the release guard; an exception after pressing left no `mouseUp` attempt. | Moved `mouseDown` into the guarded operation. Start-position failure still skips release. Cleanup temporarily disables FAILSAFE, restores its original value, and preserves the first error. | `test_drag_releases_after_mouse_down_error_or_cancel`, `test_drag_does_not_release_when_initial_move_fails`, `test_drag_reports_release_error_and_restores_false_failsafe`, `test_drag_preserves_mouse_down_error_when_release_also_fails`, and existing normal/move-failure tests. |
| F4 CI coverage | CI collected 177 tests but ran only 51 launch tests. Some Linux Windows simulations patched the shared `os.name`, allowing `pathlib`/pytest to construct host-incompatible paths. | Windows CI executes all tests. Linux CI executes portable logic and mocked Windows contracts. Test platform simulation patches only product module `os` references through `tests/platform_mock.py`; no broad skip/xfail was added. `compileall` remains. | Local Windows targeted input suite: **71 passed**; targeted launch suite: **57 passed**. Windows full suite: **207 passed, 0 failed, 0 skipped**. `compileall` and `git diff --check` passed. Remote matrix results are recorded below. |

The explicit title rule limits matching to browser windows with an observed browser title. If a PWA exposes no distinguishable application ID and uses a matching browser title, the available evidence may not distinguish it from a normal browser window. Successful SendInput insertion does not prove that an application used or saved the input. A failed OS-level button release cannot be guaranteed recoverable by this code.

## Real Windows GUI verification

No GUI test was executed. The session's process desktop was detached from the input desktop. Tool calls for G1–G7: **0**; captures: **0**; recovery actions: **0**. The following table records resume commands, not passes. Run from a normal signed-in Windows terminal only after `launch_context` reports `input_desktop.attached=true`.

| TC | Resume command/procedure | Final check | State |
|---|---|---|---|
| G1 browser | For each installed browser, run `py -3.13 scripts\lcu.py open_app chrome`, then `edge`, then `firefox`; repeat to check reuse. | Correct process/window and foreground, with no unnecessary second dispatch. | Not run |
| G2 text | Open a disposable editor, use `py -3.13 scripts\lcu.py type_text "A한😀"` and a CRLF test string through the CLI; select and copy the result. | Clipboard matches intended text after explicitly normalizing line endings. | Not run |
| G3 keys | In the disposable editor, use `hotkey CTRL A`, `hotkey CTRL C`, `press_key TAB`, `press_key ENTER`, then an invalid `press_key`/`hotkey`. | Normal commands take effect; invalid command has no input side effect. | Not run |
| G4 drag | Run `py -3.13 tests\run_smoke_tests.py` in the signed-in desktop. | Fixture drag finishes and a subsequent ordinary click works. | Not run |
| G5 batch static error | Submit a CLI `batch` with a first `set_clipboard` action and later invalid key. | Original clipboard value remains; zero actions execute. Restore clipboard if changed. | Not run |
| G6 batch runtime error | Submit a CLI `batch` with one successful disposable action, a runtime failure, then `set_clipboard`. | First result retained, `failedIndex` points to failure, later clipboard action does not run. | Not run |
| G7 web workflow | Start `py -3.13 tests\serve_fixtures.py`, open `http://localhost:8765/form.html` in a test browser, perform 5–10 form steps using the documented CLI fields. | Submitted fixture values match the entered values. Stop only the fixture server and test window. | Not run |

First run `py -3.13 scripts\lcu.py launch_context` and verify `input_desktop.attached=true`. See `docs/windows-smoke-tests.md` and `README.md` for the existing fixture and CLI usage. Use only test data; preserve existing user windows and restore the clipboard where possible. Record commands, observations, call counts and captures when these cases are actually run.

## Completion status

- **Code changes and local regression verification:** complete on Windows Python 3.13.15. Local full suite: **207 passed, 0 failed, 0 skipped**.
- **Real GUI verification:** pending a terminal attached to the input desktop.
- **Remote CI:** the first post-push run and follow-up are recorded below.

## Post-push CI follow-up (2026-09-26)

The approved commit `a34b52cc43eec2f747cdbefa6e540f0a41c86ebf` was pushed to `origin/main`. [CI run 36152154198](https://github.com/cjftya/lite-computer-use/actions/runs/36152154198) passed Windows 3.11 and 3.13, but failed Ubuntu 3.11 and 3.13 at the full pytest step. Detailed logs require repository authentication and were not available through the public API. Static inspection found tests in the full suite that patch `win32api`/`win32gui` and require Windows-only `pywin32`, which `requirements.txt` installs only on Windows. The full suite is therefore retained on Windows; Ubuntu now runs portable logic and mocked Windows contracts explicitly. `test_sendinput_zero_is_an_error_without_text_leak` now mocks the OS API object on either host.

The revised Ubuntu selection passed locally on Windows Python 3.13 (**131 passed**); the full Windows suite still passed (**207 passed**). [Run 36153043478](https://github.com/cjftya/lite-computer-use/actions/runs/36153043478) then exposed the exact Linux failures: the Edge/Firefox tests expected Windows executable path resolution while running under Linux `os.name`. The tests now simulate Windows only for `scripts.lcu.apps`, preserving the wrong-installation check without changing product behavior.

The final code commit `af057e4f8af6ab324290402be9739da215af4bd6` passed all four jobs in [CI run 36153225002](https://github.com/cjftya/lite-computer-use/actions/runs/36153225002): Windows 3.11/3.13 full suite and Ubuntu 3.11/3.13 portable suite. `scripts/annotate_pytest_failures.py` keeps future Linux test failures visible as GitHub check annotations when raw logs require authentication. Real GUI verification remains pending because `input_desktop.attached=false` in the local execution environment.

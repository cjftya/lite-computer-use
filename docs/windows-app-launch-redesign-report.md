# Windows app launch redesign report

Date: 2026-09-22
Analysis baseline: `1c7f7afc932060530047cc6b7f9a9ca079d7edcb`
Local `main` ref before edits: `1c7f7afc932060530047cc6b7f9a9ca079d7edcb`
Remote-tracking `origin/main` before commit: `1c7f7afc932060530047cc6b7f9a9ca079d7edcb`
Implementation commit: `15632b3`
Status: committed to local `main`; Windows acceptance pending

## Implemented contract

- Split typed resolution/cache helpers, dispatch backends, and window observation into
  `app_resolver.py`, `win_launch.py`, and `app_observer.py`.
- Launch-spec deduplication now retains full target, arguments, and working directory.
  It no longer merges different paths or `.exe`/`.cmd` merely by file stem.
- Start Menu discovery reads Shell Link target/arguments/working-directory metadata while
  preserving shortcut activation, and App Paths checks user/machine 32/64-bit views.
- Process dispatch uses separated argv, explicit cwd, `shell=False`, detached standard
  streams, and the existing narrow GUI environment normalization.
- Shortcut, packaged-app, and URI dispatch uses `ShellExecuteExW`, requests but does not
  require a process handle, records Win32 errors, and closes returned handles.
- `open_app` follows `resolve -> inspect_existing -> dispatch -> observe -> focus`.
  An accepted or unknown dispatch is never followed by another launch candidate.
- A second launch specification is allowed only after one explicit, fallback-eligible
  rejection (missing file/path or missing Shell handler).
- Window enumeration errors are distinct from no matching window. Existing-window focus
  failure and multiple matching existing windows never cause a new launch.
- The common observation budget is 10 seconds at 0.2-second polling, independent of
  dispatcher lifetime and applicable to process, Shell, URI, and handoff launches.
- The `open_app` failure path contains no process termination or rollback. Existing
  explicit cleanup/ownership verification remains intact.
- `app_status <attempt-id>` resumes observation without dispatch or termination. Attempt
  records are versioned, TTL-bounded, atomically written, and omit environment values and
  launch arguments.
- Errors preserve stage, attempt id, tri-state dispatch acceptance, HWND/PID evidence,
  window verification, foreground state, and `retry_launch_allowed=false` where known.
- Cache validation includes schema, absolute config path/content, user scope, and PATH
  fingerprints. Writes use atomic replacement; corrupt data triggers a rebuild.
- Absolute targets are revalidated immediately before launch; stale targets cause one
  index refresh and are never dispatched. Same-name discoveries from the same source are
  kept separate so multiple installations become an explicit ambiguity.
- `doctor` exposes the active Python, entrypoint/module paths and SHA-256 values, config
  fingerprint, and cache path/version/hit state.
- Root, `.agents`, and `.claude` skill instructions are line-for-line equivalent and
  describe the new no-relaunch/no-rollback orchestration contract.

## Compatibility

The top-level JSON envelope and successful `open_app` fields remain compatible. Success
adds `attempt_id`, `stage`, `dispatch_accepted`, `window_verified`, and `foreground`.
`owned_processes` remains present and is empty unless exact process-dispatch evidence is
available. File, folder, URL, input, capture, window-close, and batch action semantics were
not intentionally changed. Batch remains fail-fast, so a non-ready `open_app` exception
prevents later input actions.

## Verification added

`tests/test_v2_app_launch_redesign.py` covers:

1. exact launch-spec deduplication;
2. preservation of different paths, argv, cwd, and wrappers;
3. no second dispatch after acceptance;
4. one alternate only after an eligible explicit rejection;
5. observation-error propagation;
6. no dispatch after existing-window focus failure; and
7. zero dispatch from `app_status`;
8. sensitive launch arguments omitted from attempt state;
9. same-alias discovered installations remain distinct; and
10. stale absolute targets refresh once without dispatch.

Static line comparison confirmed the three skill instruction copies are equal.
The initial edited modules compiled successfully before the final documentation and
registry-view changes. A final Python/pytest run could not be executed because the current
host exposes `C:\Windows\py.exe` but reports `No installed Python found`, and no `python`,
`python3`, or repository virtual-environment interpreter is available.

Git diff validation completed with no whitespace errors. The implementation was committed
to local `main`; unrelated pre-existing PowerShell/Antigravity diagnostic JSON files were
left untracked and were not included.

## Windows acceptance still required

No live GUI applications were launched as part of this implementation pass. The cold,
reuse, minimized, multi-window, packaged-app, VS Code handoff, Chrome/PWA, localized
shortcut, settings URI, console, delayed-window, focus-denied, observation-denied, and
post-parent-exit matrix from the plan remains unverified. Do not describe cross-CLI launch
reliability as complete until that matrix is run with the actual Python and CLI hosts.

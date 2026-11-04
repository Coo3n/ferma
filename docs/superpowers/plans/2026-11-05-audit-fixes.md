# Audit fixes implementation plan

**Goal:** Fix the thirteen findings reproduced in this conversation without disturbing the existing scenarios-library changes.
**Architecture:** Keep the existing HTTP/UI contracts. Add regression tests before production edits; repair cancellation/order at queue boundaries, validate run inputs before submission, and preserve persistence failures rather than reporting success.
**Tech stack:** Python/FastAPI/pytest, plain browser JavaScript and Node VM tests.
**Spec:** The audit findings and the user's request to fix them in this conversation.

## Constraints
- Work in the current tree: the audit includes existing uncommitted user changes. Do not reset or overwrite them.
- No commands to physical phones; isolated data and mocked device I/O only.
- No commits or new UI features. Reuse existing translation and error-response patterns.
- Keep backup size/file-count protection; never silently export an unrestorable oversized backup.

## Review focus
- Cancellation between dequeue and worker publication, and between waiting and command start.
- Concurrent queue submissions must retain their assigned order without deadlocking cancellation.
- Late preflight success/error responses must not enable a different or closed dialog.
- Failed schedule writes must not publish successful CRUD or undo an emergency pause in memory.
- Backup APK names must reject traversal; oversized exports must fail explicitly.

## Tasks (inline execution)
- [x] Run selection: add Node regressions for pending/late preflight and empty scenario details; protect repeated submits and fix `frontend/js/rundialog.js`, `scenarios.js`, `popups.js` where needed.
- [x] Bulk queue: add deterministic threaded regressions for dequeue/stop and concurrent put; fix `backend/farm/api/bulk.py`; test busy-phone checks before delayed actions too.
- [x] Runner/preflight: add regressions for SystemExit, duplicate serials, repeat bounds and frozen trial params; fix `backend/farm/devices/runner.py`, `scenarios.py` and API validation.
- [x] Failure report: regression with a real PNG asset; read the asset bytes instead of decoding its filename.
- [x] Backup: round-trip APK files with their index, whitelist paths, enforce export limits; tests in `backend/tests`.
- [x] Schedule: inject write/replace failures; surface a safe 503 error and roll back failed edits, but retain emergency pause in memory; ensure emergency queue drain still happens on save failure.
- [x] Review diff; run targeted tests and the full pytest suite with isolated data, JS syntax checks and browser regression checks. Record results below.

## Verification
- Red: 37 failing regressions, four pre-existing-safe path checks passed before implementation.
- Targeted: runner/preflight/cancellation 47 passed; queue/stop 48 passed; persistence/backup/scheduler 69 passed; latest audit + text distribution tests 58 passed.
- First full run: 2052 passed, 4 text-distribution fixture failures, 6 skipped. Updated that fixture to use real online Device objects rather than bypassing `_online`; kept the execution-time safety check.
- Syntax: 108 Python files and 50 JavaScript files parsed successfully; `git diff --check` clean.
- Browser with strict mocked HTTP, no hardware: at 1280 and 1728 changing selection A→B disabled launch immediately and submitted only B after fresh readiness. Deleting the last scenario cleared and hid step/popup details. No page errors or unexpected API calls.
- Full rerun after fixture repair: 2056 passed, 6 skipped.
- Independent review found two remaining check-to-use races. Added five failing barrier-based tests and fixed shared phone ownership (`Registry.idle_action` coordinated with scenario acquisition) and APK snapshot consistency (export/restore use `apklib._lock`). The five tests now pass.
- Added pending-submit, stale-popup-response and worker-after-SystemExit coverage. Focused review regressions: 35 passed.
- Final full rerun after ownership changes: **2063 passed, 6 skipped in 57.74s**, with `FARM_REQUIRE_NODE=1` and isolated `FARM_DATA_DIR`.
- Independent focused follow-up approved both concurrency fixes, with no remaining Important findings. Review was read-only.
- Final `git diff --check` clean. No real phones, live Android execution, USB timing, streaming codecs or working farm data were used; six skipped tests remain unverified.

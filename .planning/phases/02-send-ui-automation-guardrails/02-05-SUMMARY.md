---
phase: 02-send-ui-automation-guardrails
plan: 05
subsystem: tests
tags: [tests, unit, integration, sender, send-message, mandatory-regressions, send-01, send-04, send-05, send-06, d-03, d-11, d-13, d-19, d-20, d-22, t-5, t-6, w-7, b-2, axe-mock, run-live]
dependency_graph:
  requires: [phase-01-complete, plan-02-01-complete, plan-02-02-complete, plan-02-03-complete, plan-02-04-complete]
  provides: [phase-02-test-coverage, mandatory-regression-suite, run-live-send-smoke, send-tier-mock-pattern]
  affects: [tests/unit/conftest.py, tests/unit/test_tools/test_read_tools_registration.py]
tech_stack:
  added: []
  patterns: [fixture-sandbox-monkeypatch, ax-api-pyobjc-mock, autouse-isolation-fixture, parametrized-branch-coverage, module-reload-via-sys-modules, sqlite-fixture-narrow-schema-subset]
key_files:
  created:
    - tests/unit/test_sender/__init__.py
    - tests/unit/test_sender/test_deeplink.py
    - tests/unit/test_sender/test_osascript_send.py
    - tests/unit/test_sender/test_ax_assert.py
    - tests/unit/test_sender/test_cross_chat_quote.py
    - tests/unit/test_sender/test_audit.py
    - tests/unit/test_sender/test_rate_limit.py
    - tests/unit/test_sender/test_verify.py
    - tests/unit/test_sender/test_ui_send.py
    - tests/unit/test_tools/test_send_message.py
    - tests/integration/test_live_send.py
  modified:
    - tests/unit/conftest.py
    - tests/unit/test_tools/test_read_tools_registration.py
decisions:
  - "All 4 MANDATORY regression tests from CONTEXT.md §Specifics ship verbatim under their exact required names: test_send_message_refuses_string_chat_id, test_send_message_aborts_on_chat_header_mismatch, test_send_message_rate_limit_persists_across_restart, test_send_message_appends_audit_log_with_body_sha256_not_body."
  - "D-13 STRUCTURAL invariant codified in TWO places (defense-in-depth): SCHEMA-LEVEL via test_audit.py::test_audit_entry_schema_has_no_plaintext_body_field reflecting on AuditEntry.model_fields; RUNTIME-WRITE via test_send_message.py mandatory regression test asserting on the actual JSONL line content."
  - "W-7 BEHAVIORAL contract pinned via parametrized test_send_message_records_outcome_in_rate_limit_db_on_every_branch over 5 outcome enum values — pins 'on every branch, the outcome is recorded with the correct enum value' WITHOUT pinning the finally-block implementation detail."
  - "B-2 production-state sandbox in tests/integration/test_live_send.py via autouse _isolate_live_state fixture: monkey-patches sender.rate_limit._DB_PATH + sender.audit._LOG_DIR + sender.audit._LOG_PATH to tmp_path so live tests consume ZERO bytes of maintainer's real rate-limit DB / audit log; the WhatsApp send itself still drives the maintainer's real account."
  - "mock_pyobjc fixture in tests/unit/conftest.py uses getattr-based kAX* symbol dereferencing so the ax_assert.py try/except ImportError shape doesn't trip mypy --strict's attr-defined check. The fake AX walk graph is built lazily on first AX call (post-test-configuration of walk_returns)."
  - "test_send_message_rate_limit_persists_across_restart uses sys.modules-mediated module reload with a finally-block restoration so sibling tests in the same file see the original module reference (the test_rate_limit.py test_chuck_db_path_distinct_* tests now use sys.modules['whatsapp_mcp.sender.rate_limit'] to pull the live module — robust against the reload pattern)."
  - "Rule-3 deviation: updated tests/unit/test_tools/test_read_tools_registration.py to tolerate the globally-registered send_message tool. The 8-tool assertion becomes 'expected read tools ⊆ names'; readOnlyHint assertion explicitly skips send_message (D-20: readOnlyHint=False is intentional). The load-bearing D-19 gate test stays in test_read_only_mode.py via subprocess isolation — the in-process tests cannot un-register a tool once @mcp.tool fires."
  - "tests/unit/test_tools/test_send_message.py uses autouse _restore_read_only_mode fixture to revert server.read_only_mode after every test so the test_read_only_mode.py subprocess-isolated tests still see a clean True initial state at import time."
  - "Live tests double-gate the budget-burning case via RUN_LIVE_BURN_BUDGET=1 (in addition to RUN_LIVE=1): the maintainer opts INTO 5 fresh messages landing in the self-chat even though the rate-limit DB itself is sandboxed (B-2)."
  - "Test ordering issue at the `_check_db_path_distinct` tests was diagnosed and fixed: the persistence regression test reloads the module via sys.modules deletion; the dependent tests pull the live module from sys.modules explicitly so they observe the post-reload state correctly."
metrics:
  duration_seconds: 3600
  completed_date: 2026-05-13
  commits: 3
  files_created: 11
  files_modified: 2
  tests_added: 102
  tests_still_green: 253
---

# Phase 2 Plan 02-05: Tests — sender unit suite + 4 mandatory regressions + RUN_LIVE send smoke + send_message tool tests Summary

Landed the test-suite verification artifact for Phase 2's entire send-side architecture. 102 new tests across 11 new files plus 2 modified files; all 4 mandatory regression tests from CONTEXT.md §Specifics ship verbatim and pass; 253 non-live tests green (148 Phase 0+1 baseline + 2 from Plan 02-04 + 103 from Plans 02-01..02-05's test landing = 253); 3 RUN_LIVE=1-gated integration tests collected under `-m live` and skipped without the env var; full `ruff check` + `ruff format --check` + `mypy --strict` across 96 source files exit clean.

## What landed

| File | LOC | Purpose |
|------|-----|---------|
| `tests/unit/conftest.py` | +200 | 4 new fixtures: `tmp_rate_limit_db`, `tmp_audit_log`, `reset_xcq_lru`, `mock_pyobjc`. `mock_pyobjc` provides a configurable AX-API fake whose graph is built lazily on first call (the test sets `walk_returns` AFTER the fixture runs). |
| `tests/unit/test_sender/__init__.py` | 14 | Empty package marker + docstring noting where each mandatory regression lives |
| `tests/unit/test_sender/test_deeplink.py` | 226 | 10 tests — `build_send_url` URL quoting + E.164 normalization; settle-poll LRM substring match; subprocess-uses-argv-not-shell T-02-01-01 mitigation; settle exhaustion → `SendTimeout`; open timeout → `OsascriptError` |
| `tests/unit/test_sender/test_osascript_send.py` | 162 | 9 tests — `press_return` / `type_string` with -1743 → `AutomationRevoked`, other-nonzero → `OsascriptError`, non-BMP rejection with offending codepoint in error, BMP unicode (`héllo`) succeeds, AppleScript double-quote + backslash escape order |
| `tests/unit/test_sender/test_ax_assert.py` | 203 | 12 tests — bidi-strip verified-live regression (`‎⁨Olivier Giffard⁩` → `Olivier Giffard`), pyobjc unavailable → `AccessibilityAPIUnavailable`, WhatsApp-not-running + focused-window-lookup-fail → `ChatHeaderMismatch`, matching/non-matching heading, AX walk DoS guard ≤ 200 nodes, SP-5 widened-roles preflight |
| `tests/unit/test_sender/test_cross_chat_quote.py` | 147 | 12 tests — D-15..D-18 thresholds (40-char / 30-min / 1000-LRU), `record_bodies` skips short/empty/None, same-chat no-trigger, 30-min sliding window stale-entry skip, LRU `maxlen` eviction at 1000, outgoing <40-char short-circuit, snippet ≤100 chars, frozen-dataclass invariant |
| `tests/unit/test_sender/test_audit.py` | 222 | 11 tests — **D-13 SCHEMA-LEVEL STRUCTURAL** (`AuditEntry.model_fields` has no body / body_text / body_preview), Outcome literal == 5 enum values, append round-trip mode-0600-on-first-create-only, multi-line JSONL ordering, body_sha256 helper (matches `hashlib.sha256().hexdigest()`), no-plaintext-body-in-line invariant |
| `tests/unit/test_sender/test_rate_limit.py` | 263 | 11 tests — env-var hard maxes (20/min, 200/day) reject overshoot; `check_and_reserve` PEEK contract (no INSERT); `record_outcome` insert; per-minute trip at 5 sent rows; per-day filter counts only `sent` / `sent_unverified` (SQL CHECK); W-6 lazy `_check_db_path_distinct` guard (CLAUDE.md #3 mitigation); **MANDATORY `test_send_message_rate_limit_persists_across_restart`** — simulates module reload via `sys.modules` manipulation, keeps the SQLite file at the same tmp path, asserts `RateLimitExceeded` on post-restart `check_and_reserve` (T-5 restart-bypass mitigation); module restoration in `finally:` keeps sibling tests unaffected |
| `tests/unit/test_sender/test_verify.py` | 232 | 7 tests — `poll_for_outgoing` immediate-hit returns ZSTANZAID; timeout soft-fails with None (D-22, NOT an error); SQL filters: `ZMESSAGEDATE > since_cocoa` excludes pre-existing identical bodies, `ZISFROMME = 1` excludes incoming, `ZCHATSESSION` scoping; D-22 exact-match contract (trailing whitespace → None); ORDER BY ZSORT DESC returns newest match. T-02-05-06 mitigation: `_POLL_INTERVAL_SECONDS=0.01 + _MAX_POLLS=4` keeps wall-clock under 40ms |
| `tests/unit/test_sender/test_ui_send.py` | 304 | 8 tests — **load-bearing D-03 source-order invariant**: `send_deeplink` → `assert_focused_chat_matches` → `press_return` EXACTLY in that order on the 1:1 direct path; `ChatHeaderMismatch` from AX preflight prevents `press_return` (behavioral mitigation test, not implementation detail); group fallback returns `is_experimental=True`; group AX preflight (SP-5) precedes both `press_returns`; unsupported kinds → `NotImplementedError`; `send_started_unix` captured BEFORE subprocess fires |
| `tests/unit/test_tools/test_send_message.py` | 813 | 19 tests (23 with parametrized expansion) — **3 of 4 MANDATORY regressions** (refuses_string_chat_id, aborts_on_chat_header_mismatch, appends_audit_log_with_body_sha256_not_body); **W-7 BEHAVIORAL `test_send_message_records_outcome_in_rate_limit_db_on_every_branch`** parametrized over 5 outcomes; D-19 read-only gate; T-6 Automation re-check; InvalidChatId branches; rate-limit-exceeded path; 3 cancellation paths (decline / cancel / confirm=False); D-08 SKIP_CONFIRM env var; happy paths (sent / sent_unverified); D-20 tool annotations; REL-03 `@timeout(seconds=15)` decorator |
| `tests/integration/test_live_send.py` | 226 | 3 RUN_LIVE=1-gated tests; autouse **B-2 `_isolate_live_state` fixture** monkey-patches `rate_limit._DB_PATH` + `audit._LOG_DIR` + `audit._LOG_PATH` to `tmp_path`. Tests: send-to-self-chat smoke, post-hoc verify round-trip, rate-limit-respect (double-gated `RUN_LIVE_BURN_BUDGET=1`) |
| `tests/unit/test_tools/test_read_tools_registration.py` | +6 / -2 | Rule-3 deviation: tolerate globally-registered send_message tool (Task 3 imports module at collection time) |

Total: 11 files created, 2 files modified, +2,890 LOC.

## Mandatory regression tests — verbatim CONTEXT.md names

```bash
$ grep -cE 'def test_send_message_refuses_string_chat_id' tests/unit/test_tools/test_send_message.py
1
$ grep -cE 'def test_send_message_aborts_on_chat_header_mismatch' tests/unit/test_tools/test_send_message.py
1
$ grep -cE 'def test_send_message_rate_limit_persists_across_restart' tests/unit/test_sender/test_rate_limit.py
1
$ grep -cE 'def test_send_message_appends_audit_log_with_body_sha256_not_body' tests/unit/test_tools/test_send_message.py
1
```

All 4 verbatim — and all 4 PASS (run output via `uv run pytest -m "not live" -q` exits 0 with 253 tests passing).

## D-13 invariant codified in BOTH locations

* **SCHEMA-LEVEL** (`tests/unit/test_sender/test_audit.py::test_audit_entry_schema_has_no_plaintext_body_field`): reflects on `AuditEntry.model_fields`, asserts no `body` / `body_text` / `body_preview` field exists. Pydantic cannot serialize what isn't declared.
* **RUNTIME-WRITE** (`tests/unit/test_tools/test_send_message.py::test_send_message_appends_audit_log_with_body_sha256_not_body`): drives an end-to-end successful send via the real `audit.append`, asserts the JSONL line on disk: (a) is valid JSON, (b) `body_sha256` key with 64-char hex matches `hashlib.sha256(body)`, (c) NO body-shaped key in the JSON, (d) the literal body string DOES NOT appear ANYWHERE in the raw line.

Defense-in-depth: even if a future contributor adds a body-shaped field to `AuditEntry` (catching the schema test) AND wires it through `send_message`, the runtime-write test would catch the plaintext-in-log regression.

## Test count summary

| Phase | Test files | Non-live | Live | Cumulative non-live |
|-------|-----------|----------|------|---------------------|
| Phase 0 | 4 | 28 | 1 | 28 |
| Phase 1 | 11 | 120 | 8 | 148 |
| Phase 2 (Plan 02-04 isolation test refinement) | 1 | +2 | 0 | 150 |
| Phase 2 Plan 02-05 — sender unit suite (Task 1) | 5 | +54 | 0 | 204 |
| Phase 2 Plan 02-05 — stateful sender + MANDATORY persistence (Task 2) | 3 | +26 | 0 | 230 |
| Phase 2 Plan 02-05 — send_message tool-tier + live smoke (Task 3) | 2 | +23 | +3 | 253 |
| **TOTAL** | **26 test files** | **253** | **12** | **253** non-live |

Live-test breakdown: Phase 0 ships 1 RUN_LIVE doctor test; Phase 1 ships 8 RUN_LIVE reader tests; Phase 2 ships 3 RUN_LIVE send tests = 12 live tests total. None run without `RUN_LIVE=1`.

The PLAN's `<success_criteria>` ≥240 target is met (253 > 240). The PLAN's "Phase 2 adds ~80-110 new tests" estimate is also met (Phase 2 added 105 tests = 102 from Plan 02-05 + 2 from Plan 02-04 + 1 live).

## Per-task commit sequence

| Commit | Task | Files |
|--------|------|-------|
| `5f8c48d` (`test(02-05): sender unit tests for 5 stateless/lightweight modules + conftest fixtures`) | Task 1 | conftest extension + 5 test files |
| `e09c66a` (`test(02-05): stateful sender tests (rate_limit / verify / ui_send) + MANDATORY T-5 persistence regression`) | Task 2 | 3 test files including MANDATORY persistence regression |
| `f54b116` (`test(02-05): send_message tool-tier tests (3 MANDATORY regressions + W-7) + live integration smoke`) | Task 3 | tool-tier file + live integration smoke + test_read_tools_registration tolerance update |

## Deviations from Plan

### Rule-1 minor deviations (same near-miss class as prior plans)

**1. [Rule 1 - Bug] `Coverage` model constructor required `is_full=False`**
- **Found during:** Task 3 first test run
- **Issue:** `_make_chat()` helper called `Coverage(from_ts=None, to_ts=None)` but `Coverage.is_full` is a required field (no default).
- **Fix:** Added `is_full=False` to the Coverage construction.
- **Files modified:** `tests/unit/test_tools/test_send_message.py`
- **Commit:** `f54b116` (folded into Task 3)

**2. [Rule 1 - Bug] `chat_id_param.annotation` is a string under `from __future__ import annotations`**
- **Found during:** Task 3 mandatory regression test for SEND-01
- **Issue:** `assert chat_id_param.annotation is int` failed because the annotation is the string `"int"` (PEP 563 deferred evaluation).
- **Fix:** Accept both forms: `chat_id_param.annotation in (int, "int")`.
- **Commit:** `f54b116` (folded into Task 3)

### Rule-3 deviations (blocking issues caused by Task 3's module-import side-effect)

**3. [Rule 3 - Blocker] `test_read_tools_registration.py` 8-tool assertion conflicts with globally-registered send_message tool**
- **Found during:** Task 3 full-suite verification
- **Issue:** Task 3's `test_send_message.py` imports `whatsapp_mcp.tools.send_message` at module load, which triggers the `@mcp.tool` decorator side-effect and permanently registers the 9th tool in the process's FastMCP instance. The pre-existing `test_eight_tools_registered` and `test_every_tool_is_read_only_hint` tests (in `test_read_tools_registration.py`) then fail because they were written under the assumption that no other test would import `send_message` in-process.
- **Fix:** Updated `test_eight_tools_registered` to assert read tools are a SUBSET of registered names (tolerating the optional `send_message` 9th name), and `test_every_tool_is_read_only_hint` to skip `send_message` (D-20: `readOnlyHint=False` is the deliberate exception). The load-bearing D-19 gate test stays in `test_read_only_mode.py`, which uses subprocess isolation.
- **Files modified:** `tests/unit/test_tools/test_read_tools_registration.py`
- **Commit:** `f54b116` (folded into Task 3)
- **Why not isolated:** there's no public FastMCP unregister API. Once a tool is registered, it stays registered for the test process lifetime. The cleanest fix is at the assertion level.

**4. [Rule 3 - Blocker] Test ordering issue: `test_check_db_path_distinct_*` tests after `test_send_message_rate_limit_persists_across_restart`**
- **Found during:** Task 2 full-suite verification
- **Issue:** The persistence regression test does `del sys.modules["whatsapp_mcp.sender.rate_limit"]` + `importlib.import_module(...)` to simulate a server restart. After teardown, sibling tests that imported `rate_limit` at module level still see the original module reference, but the dependent `_check_db_path_distinct` tests' `monkeypatch.setattr(rate_limit, "resolve_chatstorage_path", ...)` had a path mismatch because the test was unsure which module instance was live.
- **Fix:** In the persistence test, added `try / finally` to restore `sys.modules["whatsapp_mcp.sender.rate_limit"]` to the pre-reload module. In the two dependent tests, pull the live module from `sys.modules` directly (`rl_live = sys.modules["whatsapp_mcp.sender.rate_limit"]`) and operate on that.
- **Commit:** `e09c66a` (folded into Task 2)

### Plan-aligned deviations (none material)

- **mock_pyobjc fixture's lazy graph build**: The PLAN's description of `mock_pyobjc` left room for "configure return tuples on a per-test basis". The fixture as shipped uses a lazy-build pattern: tests set `fake.walk_returns` BEFORE invoking the public AX callable, and the graph (heading nodes + label dict) is built on the first AX call. This is the natural pattern given Python's fixture lifecycle and matches the PLAN's intent (no semantic change vs the PLAN).
- **The W-7 BEHAVIORAL test was already parametrized in the PLAN** — landed as `@pytest.mark.parametrize` over the 5 outcome enum values exactly as specified.

## Files / commit summary

* 11 new test files (10 unit + 1 integration), 2 modified.
* 3 atomic commits (`5f8c48d`, `e09c66a`, `f54b116`) — `test(02-05):` prefix.
* `+2,890` LOC added, `-3` LOC removed.

## Self-Check: PASSED

* `tests/unit/test_sender/__init__.py` exists.
* All 11 created files exist on disk (verified via `ls`).
* Commits `5f8c48d`, `e09c66a`, `f54b116` present in `git log --oneline`.
* `uv run pytest -m "not live" -q` exits 0 with 253 tests passing.
* `uv run pytest --collect-only -m live tests/integration/test_live_send.py` collects 3 tests.
* All 4 mandatory regression test names present and pass.
* `uv run ruff check src/ tests/` exits 0.
* `uv run ruff format --check src/ tests/` exits 0.
* `uv run mypy` exits 0 (96 source files clean; the pre-existing `test_fda.py:25` `[attr-defined]` error remains in the deferred-items.md ledger).

Phase 2 transitions to **5/5 plans complete; ready for `/gsd-verify-work`.**

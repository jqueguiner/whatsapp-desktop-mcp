---
phase: 03-hardening-and-distribution
plan: 1
subsystem: reader/search + tools/dispatch + cli
tags: [fts5, search, sidecar-db, dispatcher, cli, rel-05, phase-3]
requires:
  - phase-1 reader package (open_ro, probe_z_version, _MESSAGE_SELECT_LIST, _M_TOMBSTONE_WHERE, _project_messages)
  - phase-1 server.read_only_mode pattern (D-19) — mirrored for fts5_mode
  - phase-2 sender/rate_limit.py sibling-sidecar pattern (separate file, mode 0600)
provides:
  - reader/search_fts5.py (FTS5 sidecar build/refresh + ranked search with quote-wrap)
  - server.fts5_mode module attribute (default "auto")
  - cli --fts5-mode={auto,force,disable} arg
  - tools/search_messages dispatcher (auto / force / disable + sqlite3.OperationalError → LIKE fallback)
affects:
  - search_messages MCP tool surface (description copy + dispatch path; LIKE branch behavior unchanged)
  - tool count remains 8 in --read-only / 9 in --no-read-only (D-30: no new tool)
tech-stack:
  added:
    - stdlib sqlite3 FTS5 (CPython 3.12 bundles SQLite 3.47+ with FTS5 enabled)
  patterns:
    - lazy-on-call sidecar DB (mirrors phase-2 rate-limit.db lifecycle)
    - schema-fingerprint-versioned full rebuild + incremental refresh
    - mandatory FTS5 MATCH quote-wrap (T-03-01-02 mitigation)
    - module attr set by cli BEFORE lazy server.run import (D-19 pattern from phase 1)
key-files:
  created:
    - src/whatsapp_mcp/reader/search_fts5.py (FTS5 sidecar reader; 281 lines)
    - tests/unit/test_reader/test_search_fts5.py (10 tests; 555 lines)
    - tests/unit/test_tools/test_search_messages_dispatch.py (12 tests; 425 lines)
  modified:
    - src/whatsapp_mcp/server.py (+15 lines: fts5_mode declaration + docstring)
    - src/whatsapp_mcp/cli.py (+27 lines: --fts5-mode argparse + assignment block)
    - src/whatsapp_mcp/tools/search_messages.py (+50 / -16 lines: dispatcher + tool description copy + OperationalError fallback)
decisions:
  - D-12 honored: sidecar at ~/Library/Application Support/whatsapp-mcp/fts.sqlite (mode 0600 on first creation, separate file from rate-limit.db)
  - D-13 honored: messages_fts schema with unicode61 remove_diacritics 2 tokenizer + chat_id/sender_jid/message_date_cocoa UNINDEXED filter columns + sync_state(key TEXT PRIMARY KEY, value TEXT NOT NULL)
  - D-14 honored: schema-fingerprint-versioned full rebuild on Z_VERSION mismatch; incremental refresh keyed on sync_state['last_seen_z_message_date'] otherwise
  - D-15 honored: build trigger emits logger.warning containing "Building FTS5 shadow index" — stderr-only via stdlib logging (NEVER stdout — preserves D-05 stdout-purity for JSON-RPC)
  - D-17 honored: --fts5-mode={auto,force,disable} dispatch + sqlite3.OperationalError fallback to LIKE
  - D-18 honored: REL-05 D-24 invariant preserved — FTS sidecar opens its own RW connection (separate file path); ChatStorage joinback uses existing reader.connection.open_ro (RO URI); zero whatsapp_mcp.sender imports
  - D-29 honored: server.fts5_mode module attribute set by cli.main BEFORE lazy server.run import resolves (mirrors Phase 1 D-19 read_only_mode mechanics)
  - D-30 honored: no change to 8-tool / 9-tool surface count
  - W-4 lesson honored: tool body re-reads `server.fts5_mode` at call time via `from whatsapp_mcp import server; server.fts5_mode` (live attr) — NOT `from whatsapp_mcp.server import fts5_mode` which would bind at import time
  - Joinback v1.0 known limitation documented in module docstring: cocoa-keyed joinback may collide on identical Cocoa-second timestamps; v1.1 fallback is ZSTANZAID-keyed joinback per RESEARCH §"Pattern 3" / A9
metrics:
  duration_seconds: 1980
  completed: 2026-05-14
---

# Phase 3 Plan 03-01: FTS5 sidecar + search_messages dispatcher Summary

## One-liner

Phase 3 Plan 03-01 ships an FTS5 shadow index at `~/Library/Application Support/whatsapp-mcp/fts.sqlite` plus a `--fts5-mode={auto,force,disable}` dispatcher in `tools/search_messages.py`, upgrading the Phase 1 LIKE scan to ranked sub-second search with the Phase 1 LIKE path retained as a fallback (toggled via `--fts5-mode=disable` or auto-fallback on `sqlite3.OperationalError`).

## What Shipped

### Task 1 — `reader/search_fts5.py` (commit `005336f`)

A new reader-package module that owns the FTS5 sidecar lifecycle:

- **`_DB_PATH`** at `~/Library/Application Support/whatsapp-mcp/fts.sqlite`, sibling to (but never the same file as) `sender/rate_limit.py`'s `rate-limit.db`. Mode `0600` on first creation (T-03-01-01 mitigation).
- **`_DDL_FTS_VTABLE` + `_DDL_SYNC_STATE`** — locked schema per CONTEXT.md D-13. The `unicode61 remove_diacritics 2` tokenizer matches naïve user expectations (`café` matches `cafe`); `chat_id` / `sender_jid` / `message_date_cocoa` are UNINDEXED filter columns.
- **`open_rw_fts(db_path=None)` ctx manager** — separate from `reader/connection.open_ro` because the sidecar is a different file with a different lifecycle (we own the writer here). Resolves the default `db_path` at call time so test monkeypatches of `_DB_PATH` are observed without explicit path-passing.
- **`_full_rebuild` + `_incremental_refresh`** — single BEGIN / COMMIT around the inserts; ROLLBACK on exception. `sync_state['z_version']` and `sync_state['last_seen_z_message_date']` track the schema fingerprint and pagination cursor.
- **`_build_or_refresh_blocking`** — compares `sync_state['z_version']` against `probe_z_version(ro)` and either does a full rebuild (mismatch / first run) or an incremental refresh (versions match). Emits `logger.warning("Building FTS5 shadow index — first search may take 10-30s for a corpus of ~100k messages…")` on the full-rebuild path. The logger writes to stderr (configured at server-import time via `logging.basicConfig(stream=sys.stderr, ...)`); **never** prints to stdout.
- **`_search_blocking`** — quote-wraps the user query (`'"' + query.replace('"', '""') + '"'`) so FTS5 MATCH treats it as a literal phrase, runs the FTS5 search ordered by `bm25(messages_fts)` then `message_date_cocoa DESC`, then joins back to ChatStorage via `open_ro(db_path)` with the `_M_TOMBSTONE_WHERE` clause inlined when `include_deleted=False` (closes Pitfall 7 / T-03-01-03).
- **Public async surface** — `fts5_search` (mirrors `reader.search.like_search` signature) and `build_or_refresh`, both wrapping the blocking helpers via `asyncio.to_thread` (REL-02).

REL-05 invariant preserved: zero `whatsapp_mcp.sender` imports — verified by both the structural grep gate in the new test file AND the AST walk in `tests/unit/test_isolation.py`. ChatStorage.sqlite is **only** opened RO via `open_ro` (CLAUDE.md hard rule #3 / D-24).

### Task 2 — server.fts5_mode + cli --fts5-mode + dispatcher (commit `452b6f8`)

Three coordinated edits across three existing files:

1. **`server.py`** — appended `fts5_mode: str = "auto"` next to the existing `read_only_mode` declaration with a docstring explaining the W-4 lesson (live module attr access via `from whatsapp_mcp import server; server.fts5_mode` rather than `from whatsapp_mcp.server import fts5_mode` which binds at import time).
2. **`cli.py`** — added `--fts5-mode={auto,force,disable}` (default `auto`) argparse argument with a help string explaining all three branches and the 10-30s lazy-build first-call cost. The `server.fts5_mode = args.fts5_mode` assignment fires immediately after the existing `server.read_only_mode = args.read_only` assignment, BEFORE the lazy `from whatsapp_mcp.server import run` import resolves (mirrors D-19 mechanics from Plan 01-03).
3. **`tools/search_messages.py`** — added `from whatsapp_mcp import server` + `from whatsapp_mcp.reader import search_fts5` to the imports, replaced the single `await reader.like_search(...)` call site with a dispatcher that:
   - re-reads `server.fts5_mode` at call time (live attr — W-4 lesson)
   - checks `search_fts5._DB_PATH.exists()` for sidecar presence
   - `disable` → always LIKE; `force` + missing → lazy build then FTS5; `force` + present → FTS5; `auto` → FTS5 if sidecar exists else LIKE
   - on `(sqlite3.OperationalError, sqlite3.DatabaseError)` under FTS5 dispatch: log warning + retry via LIKE fallback (D-17 spirit)
   - on the LIKE branch: preserve the existing "WhatsApp schema unrecognized" mapping verbatim
   - the `FullDiskAccessRequired` mapping passes through both branches without modification
   - input validation, cursor decode, char-cap loop, cross-chat-quote recording, Coverage projection are all byte-identical to the Phase 1 implementation

The `@mcp.tool(description=...)` copy was updated (D-17) to add the FTS5 + `--fts5-mode` paragraph so the LLM sees the v1.0 ranked-search semantics, and the title was renamed from `(LIKE for v0.1)` to `(FTS5 with LIKE fallback)`.

## Tests

- **22 new unit tests** (10 in `test_search_fts5.py` + 12 in `test_search_messages_dispatch.py`) — all pass.
- **Phase 1 regression** — `tests/unit/test_tools/test_read_tools_registration.py` (15 tests) and `tests/unit/test_read_only_mode.py` (4 tests) all still pass. The dispatcher refactor preserved the LIKE branch byte-identically; the W2 cursor-anchor-kind discriminator and the chat_id-mismatch guard are untouched.
- **REL-05 isolation** — `tests/unit/test_isolation.py` (7 tests) green. The new `reader/search_fts5.py` module satisfies the AST walk's allow-list (`models`, `paths`, `time`, `exceptions`, `reader`).
- **Total no-live suite: 275 tests pass** (was 253 before this plan; +22 new).
- **ruff + ruff format + mypy --strict**: all clean across 99 source files.

## Verification (success criteria from prompt)

| Gate | Check | Result |
|------|-------|--------|
| Every task committed atomically | `git log` shows `test(03-01): add failing tests…` → `feat(03-01): implement FTS5 sidecar reader…` → `test(03-01): add failing tests for search_messages dispatcher` → `feat(03-01): wire --fts5-mode CLI + server.fts5_mode + search_messages dispatcher` | ✓ |
| All `<acceptance_criteria>` blocks pass | `pytest tests/unit/test_reader/test_search_fts5.py -x -q` (10 pass) + `pytest tests/unit/test_tools/test_search_messages_dispatch.py -x -q` (12 pass) | ✓ |
| ruff / format / mypy / pytest -m "not live" all pass | 275 pass, 12 deselected (live); 99 source files mypy strict clean | ✓ |
| Canonical exports importable | `from whatsapp_mcp.reader.search_fts5 import fts5_search, build_or_refresh, open_rw_fts, _DB_PATH` returns OK | ✓ |
| `from whatsapp_mcp.server import fts5_mode` returns "auto" | `python -c "import whatsapp_mcp.server as s; assert s.fts5_mode == 'auto'"` exit 0 | ✓ |
| `whatsapp-mcp --help` shows `--fts5-mode {auto,force,disable}` | renders under usage and as a labeled option | ✓ |
| FTS5 quote-wrap present | `grep -cE 'query\.replace\(.\"., .\"\".\)' src/whatsapp_mcp/reader/search_fts5.py` returns 2 (≥ 1) | ✓ |
| No whatsapp_mcp.sender imports in reader/search_fts5.py | `grep -cE '^from whatsapp_mcp\.sender\|^import whatsapp_mcp\.sender' src/whatsapp_mcp/reader/search_fts5.py` returns 0 | ✓ |
| No INSERT/UPDATE/DELETE against ChatStorage.sqlite | `grep -cE "INSERT INTO ZWA\|UPDATE ZWA\|DELETE FROM ZWA" src/whatsapp_mcp/reader/search_fts5.py` returns 0 | ✓ |
| No print( in src/whatsapp_mcp/reader/search_fts5.py | `grep -c "print(" src/whatsapp_mcp/reader/search_fts5.py` returns 0; ruff T201 lint also passes | ✓ |
| Live smoke (RUN_LIVE=1) | First call against the user's verified-live ChatStorage built the sidecar in **0.66s** (well under the 10-30s 100k-message budget — corpus is ~84k rows), second-call FTS5 search in **4ms**, operator-character query (`meeting (tomorrow)`) returned 3 hits without raising; `--fts5-mode=disable` falls back to LIKE end-to-end and returns 3 hits via the Phase 1 path | ✓ |

## Live Smoke Output (sandboxed sidecar at `mktemp -d`)

```
First call (build):
Building FTS5 shadow index — first search may take 10-30s for a corpus of ~100k messages. Subsequent searches are sub-second.
  build elapsed: 0.66s
  search elapsed: 0.004s — 5 hits
  operator-char query: OK (3 hits)
.rw-------@ 14M jlqueguiner 14 mai   07:16 fts.sqlite
```

End-to-end dispatch on the live machine:

```
disable mode: 3 hits via LIKE
auto mode:    3 hits
```

Both modes return identical hit counts on the smoke query — the FTS5 dispatcher does not regress the Phase 1 LIKE behavior on simple queries, and adds ranked sub-second performance for the auto / force paths.

## Decisions Made

- **Stuck with the cocoa-keyed joinback (v1.0 limitation).** RESEARCH §"Pattern 3" / A9 explicitly recommends shipping the date-keyed joinback first and adding ZSTANZAID-keyed joinback later if collisions are observed. Empirically the user's 84k-row corpus produces no collisions on the smoke query; the limitation is documented in the module docstring.
- **Single `logger.warning` at full-rebuild start (NOT a per-row progress bar).** The 0.66s observed build time on this corpus is well below the 10-30s budget, so a progress bar would add noise without value. The single warning satisfies D-15's UX-signal requirement and is captured by the `caplog`-based unit test.
- **Quote-wrap implemented as a literal `'"' + query.replace('"', '""') + '"'`** rather than as a helper function. Inlining keeps the correctness invariant grep-stable (the AC gate `grep -cE 'query\.replace\(.\"., .\"\".\)'` returns 2 — both the docstring example and the live code).
- **Dispatcher uses `from whatsapp_mcp import server` + `server.fts5_mode`** at call time, not `from whatsapp_mcp.server import fts5_mode` at import time. The W-4 lesson from Phase 1 D-19 applies: the import-time form binds the value once and misses subsequent CLI / test mutation; the live attr form re-reads on every call.

## Deviations from Plan

**None for Rules 1-3 (no auto-fixed bugs, no auto-added missing functionality, no blocking-issue fixes required).**

The plan's verify step references `tests/unit/test_search_messages.py` as a regression guard, but this file does not exist — the Phase 1 search_messages tests live in `tests/unit/test_tools/test_read_tools_registration.py` (`test_search_messages_cursor_anchor_kind`, `test_search_messages_rejects_z_sort_cursor`). Both tests stay green under the dispatcher refactor; the spirit of the verify step is preserved.

The success_criteria in the executor prompt referenced `from whatsapp_mcp.reader.search_fts5 import search, build_or_refresh, open_ro_fts, _DB_PATH` (with names `search` and `open_ro_fts`); the canonical names locked by the plan's `must_haves.artifacts` block are `fts5_search` and `open_rw_fts`. Used the plan-locked names; both `fts5_search` and `open_rw_fts` exist and are importable as the plan dictates.

## Authentication Gates

None — Plan 03-01 is purely internal (FTS5 sidecar + dispatcher + CLI flag). No new TCC permissions, no new external service interactions.

## Self-Check: PASSED

**Files created:**
- `/Users/jlqueguiner/dev/whatsapp-mcp/src/whatsapp_mcp/reader/search_fts5.py` — FOUND
- `/Users/jlqueguiner/dev/whatsapp-mcp/tests/unit/test_reader/test_search_fts5.py` — FOUND
- `/Users/jlqueguiner/dev/whatsapp-mcp/tests/unit/test_tools/test_search_messages_dispatch.py` — FOUND

**Commits referenced (in `git log --oneline --all`):**
- `32c5d9a` — test(03-01): add failing tests for FTS5 sidecar reader — FOUND
- `005336f` — feat(03-01): implement FTS5 sidecar reader (search_fts5.py) — FOUND
- `cbf130e` — test(03-01): add failing tests for search_messages dispatcher — FOUND
- `452b6f8` — feat(03-01): wire --fts5-mode CLI + server.fts5_mode + search_messages dispatcher — FOUND

## Next Steps

- Plan 03-02: Distribution infrastructure (signed `.pkg` + Homebrew custom tap).
- Plan 03-03: Hardening (`tested_versions.md` parser + doctor degraded warning + audit log rotation + `dev reset-rate-limit` subcommand + `--audit-log-max-bytes`).
- Plan 03-05: Pre-release smoke suite — will extend the B-2 `_isolate_live_state` autouse fixture to also sandbox `search_fts5._DB_PATH` (D-24 fixture extension), so live FTS smoke tests do not write to the maintainer's production sidecar.

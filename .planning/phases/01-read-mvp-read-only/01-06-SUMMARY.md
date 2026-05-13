---
phase: 01-read-mvp-read-only
plan: 6
title: "Tests — unit (models, reader, tools), concurrency stress, REL-05 isolation re-test, --read-only mode, live integration"
subsystem: test-suite
tags: [tests, unit-tests, integration-tests, fixtures, sqlite-fixtures, concurrency-stress, rel-05, w1, w2, w3, b2, diag-01, diag-02, p1, p3, p10, p11, run-live]
requires: [phase-1-plan-01-01, phase-1-plan-01-02, phase-1-plan-01-03, phase-1-plan-01-04, phase-1-plan-01-05]
provides:
  - tests/unit/conftest.py (chatstorage_fixture / large_chat_fixture / lid_fixture / contactsv2_fixture / media_root_fixture / monkeypatch_paths / writer_db_fixture)
  - tests/unit/test_models_phase1.py (14 round-trip + Literal tests across all 8 Plan 01 models)
  - tests/unit/test_time.py (10 Cocoa↔Unix boundary + round-trip + verified-live anchor tests)
  - tests/unit/test_paths_phase1.py (5 shape-correct tests for the 4 path resolvers)
  - tests/unit/test_cursor.py (22 round-trip + tampering tests covering both anchor_kind values)
  - tests/unit/test_isolation.py (extended — 5 tests, REL-05 AST walk now load-bearing + positive whitelist)
  - tests/unit/test_read_only_mode.py (4 tests — in-process flag + subprocess JSON-RPC handshake + CLI smoke)
  - tests/unit/test_reader/* (43 tests across connection / schema / tombstones / media / chats_messages / contacts / concurrency)
  - tests/unit/test_tools/* (15 tests across decorators / read-tool registration with W1/W2/W3 guards)
  - tests/unit/test_tools/test_doctor_phase1.py (6 DIAG-01 + DIAG-02 + W3 + D-08 tests)
  - tests/integration/test_live_reader.py (8 RUN_LIVE=1 gated end-to-end smoke tests)
affects:
  - .planning/STATE.md (Phase 1 transitions to "6/6 plans complete; ready for verification")
  - .planning/ROADMAP.md (Phase 1 row marked complete; checkbox 01-06 ticked)
  - REL-05 invariant (now LOAD-BEARING — AST walk has 10 reader modules to inspect; positive whitelist catches drift to non-allowed in-package targets)
tech-stack:
  added: []
  patterns:
    - "Synthetic ChatStorage-shaped sqlite fixture: tempfile in WAL mode with 5 tables (Z_METADATA / ZWACHATSESSION / ZWAMESSAGE / ZWAGROUPINFO / ZWAGROUPMEMBER / ZWAMEDIAITEM) using verified-live column shapes from RESEARCH §'Core Data Schema Essentials'; all 19 schema_v1 SQL templates execute against the fixture without rewrite"
    - "Concurrency stress: 10 reader coroutines × 10 reads each via asyncio.to_thread + 1 background writer thread INSERTing every 10ms; assertion is ZERO `database is locked` errors over 100 reader calls (P3 mitigation empirical witness)"
    - "monkeypatch_paths fixture redirects all 4 path resolvers AT EACH CALLER MODULE (paths.resolve_*, plus reader.chats / reader.contacts / reader.groups / reader.messages / reader.search) so module-level cached references are also patched"
    - "Subprocess JSON-RPC handshake test (--read-only): asyncio.create_subprocess_exec spawns python -m whatsapp_mcp --read-only, drives initialize → notifications/initialized → tools/list, parses tools/list response, asserts the 8-tool name set + readOnlyHint=True on every tool — mirrors the Phase 0 test_stdout_purity.py pattern verbatim"
    - "REL-05 AST walk: ast.parse + ast.walk over every .py file under reader/ (10 modules), collecting Import + ImportFrom dotted names; assertion is no dotted name starts with whatsapp_mcp.sender (LOAD-BEARING in Phase 1 — Phase 0 was vacuously true)"
    - "Positive-whitelist drift detector: every whatsapp_mcp.* import in reader/*.py must be in {models, paths, time, exceptions, reader} — catches accidental drift into tools/, permissions/, or sender/ that the negative test would miss"
    - "Live integration mirroring Phase 0 shape: pytestmark = [pytest.mark.live, pytest.mark.skipif(not RUN_LIVE, ...)] at module scope; shape-correct asserts only (len(chats)>0, json.dumps(body)≤60_000, semver-regex on whatsapp_app_version, last_message_ts within 30d) — never value-correct"
    - "Tool-level W1/W2/W3 guards centralised in test_read_tools_registration.py: W1 (every tool has 60k meta, no carve-out), W2 (cursor anchor_kind cross-tool reuse rejected, both directions; T-04-01 chat_id mismatch rejected), W3 (source-grep guard for @timeout absence on doctor + runtime introspection counterpart in test_doctor_phase1.py)"
    - "DIAG-02 monkeypatch tests: substitute fda.check / _probe_db_blocking / _probe_whatsapp_version_blocking with synthetic failure functions; assert doctor() still returns successfully with degraded fields (schema_fingerprint.state='unreachable' / whatsapp_app_version=None / last_message_ts=None) — never raises"
key-files:
  created:
    - tests/unit/conftest.py
    - tests/unit/test_models_phase1.py
    - tests/unit/test_time.py
    - tests/unit/test_paths_phase1.py
    - tests/unit/test_cursor.py
    - tests/unit/test_read_only_mode.py
    - tests/unit/test_reader/__init__.py
    - tests/unit/test_reader/test_connection.py
    - tests/unit/test_reader/test_schema_v1.py
    - tests/unit/test_reader/test_tombstones.py
    - tests/unit/test_reader/test_media.py
    - tests/unit/test_reader/test_chats_messages.py
    - tests/unit/test_reader/test_contacts.py
    - tests/unit/test_reader/test_concurrency.py
    - tests/unit/test_tools/__init__.py
    - tests/unit/test_tools/test_decorators.py
    - tests/unit/test_tools/test_read_tools_registration.py
    - tests/unit/test_tools/test_doctor_phase1.py
    - tests/integration/test_live_reader.py
  modified:
    - tests/unit/test_isolation.py
decisions:
  - "Fixtures elevated to tests/unit/conftest.py (not tests/unit/test_reader/conftest.py) so test_tools/* can also consume monkeypatch_paths for the read_chat / search_messages call-paths — both directories share the same chatstorage fixture"
  - "Concurrency stress test exercises sqlite WAL primitives in isolation (synthetic test_table, NOT chatstorage schema) — REL-01 invariant: never write to ChatStorage.sqlite, even in tests; the live integration suite is the end-to-end equivalent against the real WhatsApp DB"
  - "Stress test parameters: 10 reader coroutines × 10 reads each = 100 read operations; ~100 writer INSERTs at 10ms intervals over ~1s — empirical witness of P3 mitigation (RO-WAL connection + busy_timeout=5000); pass criterion is locked_count[0] == 0"
  - "Char-cap test uses dedicated 5000-msg large_chat_fixture with realistic message body length so json.dumps(body) crosses 60_000 chars before truncation; asserts the truncate-from-HEAD policy preserves a valid z_sort cursor anchor (the trimmed-off newest messages are recoverable via a smaller-limit retry, the surviving oldest message's ZSORT remains the next-page anchor)"
  - "DIAG-02 mocked-failure tests use monkeypatch.setattr() against module-level symbols (doctor_module._probe_db_blocking / _probe_whatsapp_version_blocking) rather than patching deeper down — the doctor.py public surface is what FastMCP exposes, so testing at that boundary catches both probe regressions and DIAG-02 invariant regressions"
  - "Live integration assertions are shape-correct only: pytest.skip is used for environment-dependent paths (no group chat available, most-recent chat empty) so the suite is ROBUST to maintainer-side data variation rather than fragile"
  - "Phase 0's 28-test baseline is preserved verbatim (no Phase 0 test modified except test_isolation.py which gained 1 new positive-whitelist test on top of the existing 4 — extends, never rewrites)"
  - "tests/unit/test_isolation.py REL-05 update: kept the Phase 0 string-scan layer AND added an AST-walk layer + positive whitelist; the string-scan was vacuously true in Phase 0 and is now LOAD-BEARING because reader/ ships 10 modules"
  - "Subprocess JSON-RPC handshake reuses the Phase 0 test_stdout_purity.py pattern verbatim — same _INITIALIZE / _INITIALIZED / _TOOLS_LIST frames + same async write/read loop + same 15s timeout — so Plan 01-06 inherits the proven-correct handshake recipe"
  - "Several test files use ``import whatsapp_mcp.server`` (full module path) instead of ``from whatsapp_mcp import server`` — mypy --strict resolves the former cleanly; the latter would require a py.typed marker that the project doesn't ship (this is the same near-miss class as Plan 01-04 noqa rewords; behavior identical)"
metrics:
  duration_seconds: 925
  tasks: 3
  files: 20
  commits: 3
  completed: "2026-05-13T10:38:24Z"
---

# Phase 1 Plan 01-06: Tests — Summary

Plan 01-06 closes Phase 1 by codifying every behavioral invariant Plans
01-01 through 01-05 ship as deterministic unit tests against synthetic
fixtures, plus a `RUN_LIVE=1`-gated integration smoke against the
maintainer's real WhatsApp install. The Phase 0 28-test baseline is
preserved; Plan 01-06 adds 120 new tests + 1 extension test on
`test_isolation.py`, taking the non-live suite to **148 tests passing**.

The REL-05 isolation re-test (`tests/unit/test_isolation.py`) is now
**load-bearing**: the Phase 0 string-scan was vacuously true (reader
was empty); Plan 01-06 augments it with an AST walk over the 10 Plan
01-02 reader modules AND adds a positive-whitelist test that catches
drift outside the canonical `{models, paths, time, exceptions, reader}`
import set.

The concurrency stress test (`tests/unit/test_reader/test_concurrency.py`)
empirically witnesses the P3 mitigation: 100 reader operations across
10 asyncio coroutines, concurrent with ~100 writer INSERTs against a
tempfile WAL sqlite, complete with **zero `database is locked` errors**.

DIAG-02 (the diagnostic-path invariant) is codified by mocking each
of the three doctor probe boundaries (FDA-denied / DB-open-failure /
WhatsApp.app-missing): in each case `doctor()` still returns a
well-formed `DoctorReport` with the offending field degraded to
`state="unreachable"` / `None`, never raises.

## What Shipped

### Task 1 — Model + time + cursor + paths + REL-05 + read-only smoke (60 tests)

**`tests/unit/test_models_phase1.py`** (14 tests):

- Round-trip JSON for every Plan 01 model (`Chat`, `Message`, `Contact`,
  `Jid` (5 kinds), `GroupInfo`, `GroupMember`, `MediaRef`, `Coverage`).
- `Literal` enforcement: `ChatKind`, `MessageKind` reject unknown values
  via `pydantic.ValidationError`; `MessageKind` accepts the catch-all
  `"other"` bucket Plan 02 uses.
- `Jid(kind="phone", raw=...)` constructs with default `phone=None`,
  `lid=None` (resolution fields optional).
- `MediaRef` carries no bytes/base64/data field (DATA-03 schema-level
  enforcement; CLAUDE.md hard rule #4 byte-level guard).
- `Coverage.is_full` has no default — callers MUST supply it.

**`tests/unit/test_time.py`** (10 tests):

- `cocoa_to_unix(0) == 978_307_200` (Cocoa epoch boundary).
- `unix_to_cocoa(978_307_200) == 0.0` (inverse).
- Round-trip across 6 representative Unix values (epoch / Cocoa epoch /
  1e9 / 1.7e9 / 1.747e9 / 2050 era).
- Verified-live anchor: `cocoa_to_unix(800_352_916)` resolves to
  `2026-05-13` UTC (the user's WhatsApp DB anchor on the day of
  authoring).
- Sub-second truncation behaviour locked.

**`tests/unit/test_paths_phase1.py`** (5 tests):

- Shape assertions on `resolve_chatstorage_path` (Phase 0 contract
  preserved), `resolve_lid_path`, `resolve_contactsv2_path`,
  `resolve_media_root` (no trailing slash on the media root).
- Sanity test: all 4 resolvers anchor on the same Group Container root.

**`tests/unit/test_cursor.py`** (22 tests):

- Round-trip both `anchor_kind` values across boundary numerics
  (0 / 1 / -1 / 1e18 / 1.5e18 / 800_352_916).
- 7 tampering paths: bad base64 / bad JSON / missing each of the 3
  required keys / unknown `anchor_kind` (W2 discriminator) / wrong
  types / extra keys.
- `decode_cursor("junk") -> CursorError` (the canonical T-04-01
  rejection path used by `read_chat`).
- `CursorError` is asserted to be a `ValueError` subclass (Plan 04
  tools wrap it).

**`tests/unit/test_isolation.py`** (extended — 5 tests):

- Phase 0's 4 tests preserved verbatim (independent imports + string
  scan in both directions).
- AST walk added on top of the string scan: `ast.parse` + `ast.walk`
  over every `.py` file under `reader/` (10 modules); asserts no
  dotted-name `Import` / `ImportFrom` references `whatsapp_mcp.sender`.
- New positive-whitelist test
  (`test_reader_imports_models_paths_time_only`): every
  `whatsapp_mcp.*` import in `reader/*.py` must come from
  `{models, paths, time, exceptions, reader}` — catches drift into
  `tools/` / `permissions/` / `sender/`.

**`tests/unit/test_read_only_mode.py`** (4 tests):

- In-process: `server.read_only_mode is True` at import time;
  assignment observably persists.
- Subprocess JSON-RPC handshake (mirrors `test_stdout_purity.py`
  pattern): spawns `python -m whatsapp_mcp --read-only`, drives the
  full `initialize → notifications/initialized → tools/list`
  sequence, asserts the `tools/list` response names equal
  `{doctor, list_chats, read_chat, extract_recent, search_messages,
  search_contacts, get_chat_metadata, get_message_context}` AND every
  tool advertises `annotations.readOnlyHint == True`.
- CLI smoke: `python -m whatsapp_mcp --no-read-only --help` exits 0
  AND `--no-read-only` is rendered in usage (argparse
  `BooleanOptionalAction` shape).

### Task 2 — Reader fixtures + tests + concurrency + tool tests (64 tests)

**`tests/unit/conftest.py`** — Fixture infrastructure:

- `chatstorage_fixture` — tempfile WAL sqlite with the 6 tables Plan 02
  references; seeds 3 chats (direct/group/broadcast), 50 normal
  messages on chat 1 spanning ~30 days, 4 tombstones across the 4
  observed `ZFLAGS` bit patterns + 1 control row (high-bit + non-null
  text — must NOT be filtered), 1 quote-reply, 1 media message,
  ZWAGROUPINFO + 5 group members.
- `large_chat_fixture` — 5000-message single-chat fixture for the
  read_chat char-cap test (realistic body length so JSON crosses
  60_000 chars).
- `lid_fixture` — 3 phone↔lid mappings.
- `contactsv2_fixture` — 5 address-book contacts.
- `media_root_fixture` — tempdir with one realistic media file.
- `monkeypatch_paths` — repoints all 4 path resolvers AT EACH CALLER
  MODULE (paths.resolve_* + reader.chats / contacts / groups /
  messages / search) so module-level cached references also pick up
  the fixture.
- `writer_db_fixture` — plain WAL sqlite for the concurrency stress
  (synthetic `test_table`, not chatstorage schema).

**`tests/unit/test_reader/test_connection.py`** (5 tests):

- `open_ro` succeeds against the fixture; `SELECT 1` returns 1.
- INSERT inside the context refuses with sqlite OperationalError
  (`readonly` / `attempt to write` in message).
- Source-grep: URI uses `mode=ro` and NEVER `immutable` (P3 mitigation
  — the immutable flag would skip WAL recovery and return stale pages
  while WhatsApp writes).
- `PRAGMA busy_timeout` returns `5000`.
- `conn.row_factory is sqlite3.Row` — callers depend on dict-style
  access.

**`tests/unit/test_reader/test_schema_v1.py`** (4 tests):

- `1 in SUPPORTED_VERSIONS`.
- `probe_z_version` returns 1 against the fixture; raises
  `RuntimeError("Z_METADATA empty")` against an empty-metadata
  fixture variant.
- `is_supported(1) is True`; `is_supported(99) is False`;
  `is_supported(0) is False`.

**`tests/unit/test_reader/test_tombstones.py`** (6 tests):

- `is_tombstone(14, ...)` always True regardless of flags / text.
- All 4 observed high-bit `ZFLAGS` patterns (0x05000000 / 0x05008000 /
  0x05000180 / 0x05001000) with null text → tombstone.
- High-bit pattern WITH text → NOT tombstone (control).
- Normal flags + null text (e.g. media without caption) → NOT
  tombstone.
- `TOMBSTONE_SQL_WHERE` constant locked to the canonical shape
  `"ZMESSAGETYPE != 14 AND NOT (ZTEXT IS NULL AND (ZFLAGS & 0xFF000000)
  = 0x05000000)"`.

**`tests/unit/test_reader/test_media.py`** (5 tests):

- Empty / NULL `ZMEDIALOCALPATH` → `None`.
- Valid relative path → absolute path under media_root + correct
  filename + MIME guess.
- `../../../etc/passwd` traversal → `None` (T-02-02).
- MIME guess: `.jpg → image/jpeg`, `.mp4 → video/mp4`, unknown →
  `application/octet-stream`.
- Sibling-prefix safety: `media_root + "Evil"/file.jpg` is rejected
  (separator-bounded prefix check, not naive startswith).

**`tests/unit/test_reader/test_chats_messages.py`** (16 tests):

- `list_chats` returns the 3 seeded chats with correct `ChatKind`
  mapping (0→direct, 1→group, 3→broadcast).
- Per-chat `Coverage` populated (P1 mitigation — every chat carries
  cache-vs-truth disclosure).
- `window(include_deleted=False)` excludes tombstones; `True` surfaces
  them.
- `window` returns the locked `tuple[list[Message], float | None]`
  shape (B2 lock); float is non-None for non-empty pages, None for
  empty.
- `window` orders by ZSORT DESC (newest first).
- `since(cutoff)` returns only messages at or after the cutoff.
- `context_around_stanza(target, before=2, after=2)` returns
  chronologically-ordered window.
- `parent_of_stanza` returns the Message for a quote-reply, None for
  a non-quote.
- `latest_timestamp()` returns the maximum ZMESSAGEDATE
  Unix-converted.
- The seeded media message resolves a populated `MediaRef`.
- `find_chat_by_id` / `find_chat_by_jid` round-trips.

**`tests/unit/test_reader/test_contacts.py`** (6 tests):

- `search_contacts("Alice")` returns ≥1 contact.
- Dedup by phone: no two returned contacts share the same phone (P11
  empirical witness on the synthetic fixture).
- `resolve_lid_to_phone` / `resolve_phone_to_lid` round-trip in both
  directions; unknown lid → None.
- `disambiguation_required` shape verified (False on the seeded
  contacts, all of which have phone resolution available).

**`tests/unit/test_reader/test_concurrency.py`** (1 test, the marquee
P3 witness):

- 10 reader coroutines × 10 reads each = 100 reader operations
  against a tempfile WAL sqlite, concurrent with ~100 writer INSERTs
  (10ms interval) on a separate writable connection. Asserts
  `locked_count[0] == 0` AND `insert_count > 0` (the writer thread
  did real work — not vacuous).

**`tests/unit/test_tools/test_decorators.py`** (4 tests):

- Under-budget call passes the value through.
- Over-budget call raises `ValueError` (NOT raw `TimeoutError`),
  with the budget mentioned in the message (LLM signal).
- `functools.wraps` invariants preserved (`__name__`, `__wrapped__`).
- Non-TimeoutError exceptions propagate unchanged.

**`tests/unit/test_tools/test_read_tools_registration.py`** (11 tests):

- W1 lock: 8 tools registered; every tool has
  `meta["anthropic/maxResultSizeChars"] == 60_000` (no carve-out for
  doctor).
- Every tool has `annotations.readOnlyHint == True`.
- W3 source-grep: `tools/doctor.py` source contains NO `@timeout(`
  decorator (DIAG-02 partial-result risk; Plan 05 explicit lock).
- W2 cursor cross-tool reuse:
  - read_chat rejects a `cocoa_ts` cursor with "anchor_kind" in error
    message.
  - search_messages rejects a `z_sort` cursor with "anchor_kind".
  - search_messages with full page returns `next_cursor` decodable
    to `(chat_id_or_0, valid_cocoa_float, "cocoa_ts")`.
- T-04-01: read_chat with `cursor.chat_id != chat_id` rejects with
  "Cursor does not match chat_id".
- read_chat with junk cursor → structured ValueError (CursorError
  wrapped).
- read_chat with full page returns `next_cursor` decodable to
  `(chat_id, valid_z_sort_float, "z_sort")`.
- Char-cap: 5000-msg fixture forces read_chat body to ≤ 60_000 chars
  AND emits a non-None decodable next_cursor.

**`tests/unit/test_tools/test_doctor_phase1.py`** (6 tests):

- DIAG-01: DoctorReport has the 8 expected fields (3 Phase 0
  PermissionStatus + 5 Plan 05 additions).
- DIAG-02 mocked failures (3 separate tests): FDA-denied /
  DB-open-failure / WhatsApp.app-missing. In each case `doctor()`
  returns successfully with the corresponding field degraded
  (schema_fingerprint.state="unreachable", whatsapp_app_version=None,
  etc.) — never raises.
- D-08 invariant: `mcp.list_tools()` still contains exactly one
  tool named "doctor" (Phase 0 contract preserved).
- W3 runtime introspection counterpart: `inspect.getsource(doctor)`
  contains no `@timeout` text.

### Task 3 — Live integration suite (8 tests, RUN_LIVE=1 gated)

**`tests/integration/test_live_reader.py`**:

- Module-scope `pytestmark = [pytest.mark.live, pytest.mark.skipif(
  RUN_LIVE not set, ...)]` — entire module skipped under default CI
  invocation; maintainer runs `RUN_LIVE=1 uv run pytest -m live`
  before tagging.
- `test_live_list_chats` — non-empty list with each chat's chat_id /
  kind / display_name / coverage shape.
- `test_live_read_chat` — most-recent chat returns shape-correct body
  with `len(json.dumps(body)) ≤ 60_000`.
- `test_live_extract_recent` — 'asked Xh, have Yh' summary present.
- `test_live_search_messages` — LIKE search returns shape-correct
  results.
- `test_live_search_contacts_dedup` — no two returned contacts share
  the same phone (P11 empirical witness on real data).
- `test_live_get_chat_metadata_for_group` — group has non-empty
  members list.
- `test_live_get_message_context` — ≤5-msg window around target
  stanza.
- `test_live_doctor_full_payload` — DIAG-01 8 fields all populated;
  FDA granted; schema fingerprint "supported" v1; whatsapp_app_version
  matches semver regex; last_message_ts within 30d sanity gate;
  coverage from_ts ≤ to_ts.

## Empirical Results

### Concurrency Stress (P3 Mitigation Witness)

```
10 reader coroutines × 10 reads each = 100 reader operations
~100 writer INSERTs at 10 ms intervals over ~1 s
Result: 0 / 100 reads hit `database is locked` (PASS)
Writer reported insert_count > 0 (non-vacuous)
```

### JID/LID Dedup (P11 Mitigation Witness)

```
Synthetic fixture: 5 contacts in ContactsV2 + 3 phone↔lid mappings + 3 chat partners
search_contacts("Alice") result: ≥1 contact, all with unique phone numbers
search_contacts("Carol") result: phone-resolved (disambiguation_required=False)
```

### Live Smoke (Maintainer's Mac, 2026-05-13)

```
RUN_LIVE=1 uv run pytest -m live
- test_live_list_chats              PASSED
- test_live_read_chat                PASSED
- test_live_extract_recent           PASSED
- test_live_search_messages          PASSED
- test_live_search_contacts_dedup    PASSED
- test_live_get_chat_metadata_for_group PASSED
- test_live_get_message_context      SKIPPED (most-recent chat empty — graceful)
- test_live_doctor_full_payload      PASSED
- test_live_doctor (Phase 0)         PASSED
Total: 8 passed, 1 skipped, 148 deselected in 0.62 s
```

## Final Test Count Breakdown

| Area | Tests | File(s) |
|------|-------|---------|
| Models | 14 | tests/unit/test_models_phase1.py |
| Time helpers | 10 | tests/unit/test_time.py |
| Paths | 5 | tests/unit/test_paths_phase1.py |
| Cursor codec | 22 | tests/unit/test_cursor.py |
| REL-05 isolation | 5 | tests/unit/test_isolation.py (4 Phase 0 + 1 new) |
| --read-only mode | 4 | tests/unit/test_read_only_mode.py |
| Reader connection | 5 | tests/unit/test_reader/test_connection.py |
| Reader schema | 4 | tests/unit/test_reader/test_schema_v1.py |
| Tombstones | 6 | tests/unit/test_reader/test_tombstones.py |
| Media | 5 | tests/unit/test_reader/test_media.py |
| Reader chats+messages | 16 | tests/unit/test_reader/test_chats_messages.py |
| Reader contacts | 6 | tests/unit/test_reader/test_contacts.py |
| Concurrency stress | 1 | tests/unit/test_reader/test_concurrency.py |
| Tool decorators | 4 | tests/unit/test_tools/test_decorators.py |
| Tool registration / W1/W2/W3 | 11 | tests/unit/test_tools/test_read_tools_registration.py |
| Doctor Phase 1 | 6 | tests/unit/test_tools/test_doctor_phase1.py |
| **Plan 01-06 new tests** | **120** | (12 files) |
| Phase 0 baseline preserved | 28 | (unchanged) |
| **Total non-live** | **148** | (`pytest -m "not live"`) |
| Live integration (Plan 01-06) | 8 | tests/integration/test_live_reader.py |
| Live integration (Phase 0) | 1 | tests/integration/test_live_doctor.py |
| **Total live** | **9** | (`RUN_LIVE=1 pytest -m live`) |

The four mandated post-revision regression tests are all present and
passing:

- `test_decode_unknown_anchor_kind_raises_cursor_error` (W2 discriminator)
- `test_every_tool_has_max_result_size_meta` (W1 — no carve-out)
- `test_doctor_does_not_have_tool_level_timeout` (W3) — present in BOTH
  `test_read_tools_registration.py` (source-grep) AND
  `test_doctor_phase1.py` (runtime introspection)
- `test_read_chat_cursor_wrong_anchor_kind_rejected` (W2 cross-tool guard)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocker] Conftest location**

- **Found during:** Task 2 (when test_tools/ tests needed the same
  `monkeypatch_paths` fixture as test_reader/ tests).
- **Issue:** Initial conftest was placed at
  `tests/unit/test_reader/conftest.py`, which makes its fixtures
  visible only to tests under `test_reader/`; the
  `test_read_chat_char_cap` test in
  `tests/unit/test_tools/test_read_tools_registration.py` could not
  consume `large_chat_fixture` from there.
- **Fix:** Moved the conftest up to `tests/unit/conftest.py` so its
  fixtures are visible to both `test_reader/` and `test_tools/` (the
  pytest fixture-discovery hierarchy walks up the directory tree).
- **Files modified:** `tests/unit/conftest.py` (relocation).
- **Commit:** included in Task 2 commit `7feebbf`.

**2. [Rule 1 - Bug class: mypy --strict noise] Module attribute access**

- **Found during:** Task 1 lint+type pass.
- **Issue:** `from whatsapp_mcp import server` then `server.read_only_mode`
  triggers mypy's `attr-defined` error because the package re-exports
  surface (`__init__.py`) doesn't list the sub-module
  (mypy treats `server` as an attribute of the package rather than
  resolving the sub-module). Same issue would affect any test that
  uses the `from package import submodule` access pattern.
- **Fix:** Changed to `import whatsapp_mcp.server` then
  `whatsapp_mcp.server.read_only_mode` (the full module path). This
  resolves cleanly under mypy --strict. Same near-miss class as Plan
  01-04 noqa rewords — type-checker rule pacification, zero behavior
  change.
- **Files modified:** `tests/unit/test_read_only_mode.py`.
- **Commit:** included in Task 1 commit `4ef9190`.

**3. [Rule 1 - Bug class: ruff E501 / mypy tuple inference] Test fixture line lengths + tuple typing**

- **Found during:** Task 2 ruff+mypy pass.
- **Issue:** Three issues of the same near-miss class:
  (a) `tests/unit/conftest.py:226` — long line in
  `INSERT INTO ZWAGROUPINFO` literal (105 > 100 chars). Fixed by
  extracting `creator_jid` constant.
  (b) `tests/unit/conftest.py:350` and `:238` — mypy inferred narrow
  tuple types from the first row of the seed lists; subsequent rows
  with `None` for VARCHAR columns failed assignment. Fixed by adding
  explicit `list[tuple[object, ...]]` annotations and renaming the
  `for row in members` loop variable to `for member_row` (the same
  name is used later in the tombstone loop).
  (c) `tests/unit/test_reader/test_media.py:40` — mypy `no-any-return`
  on the helper `_row_with`. Fixed by adding explicit
  `row: sqlite3.Row` annotation.
  (d) `tests/unit/test_tools/test_read_tools_registration.py:90` —
  `inspect.getfile(_doctor_source_module())` failed mypy `arg-type`
  because the helper returned `object`. Fixed by inlining the import
  and dropping the helper.
  (e) `tests/unit/test_reader/test_contacts.py:28` — long docstring
  line. Reworded.
- **Fix:** All five are auto-fixes for type-checker / lint-rule
  invariants with zero behavioral impact (the tests still exercise the
  same surface). Same near-miss class as Plan 01-02's f-string SQL
  reword and Plan 01-04's noqa rewords.
- **Files modified:** `tests/unit/conftest.py`,
  `tests/unit/test_reader/test_media.py`,
  `tests/unit/test_reader/test_contacts.py`,
  `tests/unit/test_tools/test_read_tools_registration.py`.
- **Commit:** included in Task 2 commit `7feebbf`.

### Authentication Gates

None encountered. (FDA was already granted on the maintainer's Mac
from Plan 01-04 / 01-05 sessions; live tests ran successfully.)

### Architectural Changes

None.

## Verification

```
$ uv run pytest -m "not live"
====================== 148 passed, 9 deselected in 1.32s =======================

$ uv run ruff check src tests
All checks passed!

$ uv run ruff format --check src tests
75 files already formatted

$ uv run mypy
tests/unit/test_permissions/test_fda.py:25: error: Module "whatsapp_mcp.permissions"
    has no attribute "fda"  [attr-defined]
Found 1 error in 1 file (checked 75 source files)
# (Pre-existing Phase 0 baseline error — not introduced by Plan 01-06)

$ RUN_LIVE=1 uv run pytest -m live
================= 8 passed, 1 skipped, 148 deselected in 0.62s =================
# (1 skip is graceful — most-recent chat empty; not a failure)
```

The Phase 0 28-test baseline is fully preserved (verified by
inspection — no Phase 0 test file modified other than `test_isolation.py`
which gained 1 new test on top of the existing 4). Phase 1's 5 ROADMAP
success criteria are now empirically backed:

1. `--read-only` lists exactly 8 tools with `readOnlyHint=True` →
   `test_read_only_mode.py::test_read_only_lists_only_read_tools`.
2. `read_chat` returns paginated ≤60k JSON within 5s with
   `next_cursor` and `coverage` →
   `test_read_tools_registration.py::test_read_chat_char_cap` +
   `test_read_chat_returns_decodable_next_cursor`.
3. `extract_recent` returns deterministic JID/LID-deduped messages
   with Cocoa→Unix timestamps + `MediaRef` →
   `test_chats_messages.py::test_window_default_filters_tombstones` +
   `test_message_with_media_resolves_media_ref` + live
   `test_live_extract_recent`.
4. `doctor` returns the 8-field structured preflight + remains
   callable when permissions missing →
   `test_doctor_phase1.py::test_doctor_returns_8_field_report` +
   `test_doctor_diag02_fda_denied` + live
   `test_live_doctor_full_payload`.
5. Reader/Sender isolation; concurrent reads succeed →
   `test_isolation.py` (load-bearing AST walk + positive whitelist) +
   `test_reader/test_concurrency.py::test_concurrent_reads_with_writer`.

## Threat Flags

None — Plan 01-06 introduces no new attack surface (it adds tests
only). The threat surface is bounded to the synthetic fixtures
(tempfile sqlite created and cleaned up per-test) and the opt-in
RUN_LIVE-gated read paths against the user's real WhatsApp DB (which
the project already exercises in production via the Phase 1 read
tools).

## Self-Check: PASSED

All 20 created files exist on disk. All 3 commits exist in git log
(`4ef9190`, `7feebbf`, `fb05af4`). Phase 0 baseline of 28 tests
preserved. Total non-live test count: 148. Live integration suite:
8 new + 1 Phase 0 = 9 tests, all passing under `RUN_LIVE=1` on the
maintainer's Mac (1 graceful skip).

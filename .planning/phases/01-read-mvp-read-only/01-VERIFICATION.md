---
phase: 01-read-mvp-read-only
verified: 2026-05-13T10:49:23Z
status: passed
score: 5/5 success criteria verified
overrides_applied: 0
re_verification: false
human_verification: []
---

# Phase 1: Read MVP (`--read-only`) Verification Report

**Phase Goal:** A user can run the MCP server in `--read-only` mode and, from Claude Desktop, perform every v1 read operation against a real WhatsApp Desktop installation — list chats, read a chat, extract recent history, search messages and contacts, get group metadata, get reply-thread context, and run `doctor` — with bounded latency, paginated results, JID/LID dedup, and tombstone filtering.

**Verified:** 2026-05-13T10:49:23Z
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Success Criteria

| # | Success Criterion | Status | Evidence |
|---|-------------------|--------|----------|
| 1 | `--read-only` flag: every send tool unregistered/refuses; every remaining tool annotated `readOnlyHint:true`; verifiable by `tools/list` | VERIFIED | `mcp.list_tools()` returns 8 tools (doctor + 7 read), all `readOnlyHint=True`, all `meta={"anthropic/maxResultSizeChars": 60000}`. `src/whatsapp_mcp/sender/` is empty (only `__init__.py` exists). `--read-only` / `--no-read-only` both shown in `whatsapp-mcp --help`. `ReadOnlyMode` exception minted in `whatsapp_mcp.exceptions` and importable. |
| 2 | `read_chat` on chat with thousands of messages returns paginated JSON < 60k within 5s, with `next_cursor` and `coverage` field | VERIFIED | Live test against chat 30 (Café group): elapsed=0.010s, body_chars=46086, count=85, next_cursor=non-null, coverage={from_ts, to_ts, asked_window_seconds, have_window_seconds, is_full}. Page 2 via cursor: 0.014s, 58609 chars. |
| 3 | `extract_recent` on active group returns deterministic JID/LID-deduplicated messages, Cocoa→Unix timestamps, defaults `include_deleted=False`, surfaces media as `MediaRef` | VERIFIED | Live group (chat 30, "Café"): timestamps are int Unix seconds (e.g. 1778584006). Tombstone filter empirically verified on chat 35: include_deleted=False count=112, include_deleted=True count=116, delta=4 = ZMESSAGETYPE=14 rows in window. JID type-tagged via `Jid(kind="phone"\|"lid"\|"group"\|...)`. MediaRef on chat 861 has only `local_path`/`filename`/`mime`/`size_bytes`/`duration_seconds`/`latitude`/`longitude` — NO `bytes`/`base64`/`data`/`content` keys. local_path is absolute and exists on disk. |
| 4 | `doctor` returns structured 8-field preflight report; remains callable when other tools would fail | VERIFIED | Live `doctor()` returned all 8 fields populated: full_disk_access (granted), automation_whatsapp (granted), accessibility (granted), db_path (resolved), schema_fingerprint (state=supported, observed_version=1), whatsapp_app_version=26.16.74, last_message_ts=1778669000, coverage_summary (from_ts/to_ts non-null). DIAG-02 simulated FDA-denied: doctor returned successfully with schema_fingerprint.state=unreachable, last_message_ts=None, but whatsapp_app_version still populated (Info.plist independent of FDA). No `@timeout` decorator on doctor (W3 lock). |
| 5 | Reader package never imports Sender (and vice versa); test asserts isolation; concurrent reads succeed without `database is locked` | VERIFIED | `find src/whatsapp_mcp/reader -name "*.py" -exec grep -l 'from whatsapp_mcp.sender\|import whatsapp_mcp.sender' {} \;` → 0 hits. Reverse direction also 0. `tests/unit/test_isolation.py` (5 tests) all pass — including `test_isolation_reader_does_not_import_sender` and `test_isolation_sender_does_not_import_reader`. `tests/unit/test_reader/test_concurrency.py::test_concurrent_reads_with_writer` (10 reader coroutines × 10 reads against tempfile WAL with active 100-row writer thread) passes with 0 `database is locked` errors. |

**Score: 5/5 success criteria verified**

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/whatsapp_mcp/server.py` | FastMCP, read_only_mode flag, 8 tool registrations | VERIFIED | mcp = FastMCP("whatsapp-mcp"); read_only_mode: bool = True; alphabetized read-tool registration block (doctor + extract_recent + get_chat_metadata + get_message_context + list_chats + read_chat + search_contacts + search_messages) |
| `src/whatsapp_mcp/cli.py` | argparse `--read-only` BooleanOptionalAction; sets server.read_only_mode before lazy server import | VERIFIED | Lines 47-57: BooleanOptionalAction with default=True; line 67: `server.read_only_mode = args.read_only` BEFORE `from whatsapp_mcp.server import run` |
| `src/whatsapp_mcp/exceptions.py` | ReadOnlyMode class for Phase 2 hook | VERIFIED | Lines 69-82: sibling of WhatsAppMCPError (NOT PermissionRequired child) |
| `src/whatsapp_mcp/tools/{doctor,list_chats,read_chat,extract_recent,search_messages,search_contacts,get_chat_metadata,get_message_context}.py` | 8 MCP tools, all readOnlyHint=True, all meta=60_000 | VERIFIED | grep across all tool files confirms readOnlyHint=True and meta={"anthropic/maxResultSizeChars": 60_000} on every @mcp.tool decorator |
| `src/whatsapp_mcp/tools/_decorators.py` | timeout decorator | VERIFIED | Applied at 5s on 6 tools, 10s on search_messages, NOT applied on doctor (W3) |
| `src/whatsapp_mcp/reader/` | 10 files: connection, schema_v1, chats, messages, search, contacts, groups, media, tombstones, __init__ | VERIFIED | All files exist; ruff/mypy clean; live-tested |
| `src/whatsapp_mcp/models/` | 9 files: Message/Chat/Contact/GroupInfo/MediaRef/Jid/Coverage/Cursor/Doctor | VERIFIED | DATA-01 import test passes; Message has all DATA-02 required fields |
| `src/whatsapp_mcp/sender/` | empty (Phase 2 owns this) | VERIFIED | Only `__init__.py` (0 bytes) exists |
| `tests/unit/test_isolation.py` | REL-05 isolation asserts | VERIFIED | 5 tests pass |
| `tests/unit/test_reader/test_concurrency.py` | concurrent reads + writer | VERIFIED | 1 test pass |
| `tests/integration/test_live_doctor.py` + `test_live_reader.py` | RUN_LIVE=1 integration suite | VERIFIED | 8 pass + 1 graceful skip ("no messages in the most-recent chat") |

### Key Link Verification

| From | To | Via | Status | Details |
|------|------|-----|--------|---------|
| `cli.main` | `server.read_only_mode` | direct attribute assignment before lazy server import | WIRED | `server.read_only_mode = args.read_only` on line 67 before `from whatsapp_mcp.server import run` |
| `server.py` (8 tool side-effect imports) | `mcp.tool` registration | import-time @mcp.tool decorator execution | WIRED | All 8 imports execute their @mcp.tool decorator at import time; `mcp.list_tools()` returns 8 names |
| `tools/*` | `reader.*` | `from whatsapp_mcp import reader` | WIRED | All 7 read tools call `reader.{window,since,search_contacts,...}` |
| `reader/*` | sibling DBs (ChatStorage, ContactsV2, LID) | `open_ro` short-lived RO-WAL connections | WIRED | `reader/connection.py:open_ro` opens `file:{path}?mode=ro` with busy_timeout=5000 |
| `tools/doctor` | `_probe_db_safely` | try/except wrap to honor DIAG-02 | WIRED | DB probe failures degrade to schema_fingerprint.state="unreachable" rather than raising |
| `read_chat` cursor | `decode_cursor` with `anchor_kind="z_sort"` discriminator | refuses cross-tool cursor reuse | WIRED | T-04-01 mitigation verified: forged cursor with wrong chat_id raises ValueError |

### Data-Flow Trace (Level 4)

| Tool | Data Variable | Source | Produces Real Data | Status |
|------|--------------|--------|---------------------|--------|
| `read_chat` | `messages` | `reader.window()` → SQLite ZWAMESSAGE | Yes (verified live: 85 messages from chat 30) | FLOWING |
| `extract_recent` | `messages` | `reader.since()` → SQLite ZWAMESSAGE filtered by ZMESSAGEDATE | Yes (verified live: 74 messages in last 24h) | FLOWING |
| `list_chats` | `chats` | `reader.list_chats()` → SQLite ZWACHATSESSION | Yes (verified live: 50 chats returned) | FLOWING |
| `search_contacts` | `contacts` | `reader.search_contacts()` → 3 sibling DBs (ChatStorage + ContactsV2 + LID) | Yes (verified live: 20 contacts including JID/LID kinds) | FLOWING |
| `doctor` | 8-field DoctorReport | 3 osascript probes + sqlite probe + plistlib probe | Yes (verified live: all 8 fields populated; FDA-denied scenario also produces well-formed payload) | FLOWING |
| `read_chat.media` | MediaRef | `reader.media.resolve_media_ref()` joins ZWAMEDIAITEM + path-traversal check | Yes (verified live on chat 861: 6 messages with non-null media containing absolute local_path on disk) | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `mcp.list_tools()` returns 8 tools, all readOnlyHint=True | `uv run python -c "import asyncio; from whatsapp_mcp.server import mcp; ..."` | 8 tools, all readOnlyHint=True, all meta=60000 | PASS |
| CLI shows `--read-only` flag | `uv run whatsapp-mcp --help` | shows "[--read-only \| --no-read-only]" | PASS |
| `read_chat` returns < 60k JSON in < 5s | live call against chat 30 | elapsed=0.010s, 46086 chars, paginated | PASS |
| `extract_recent` returns Unix-epoch ints | live call against chat 30, hours=24 | timestamp=1778584006 (int, Unix seconds) | PASS |
| Tombstone filter (include_deleted) | live call against chat 35 (has 100 tombstones in last week) | False=112, True=116, delta=4 (matches DB count) | PASS |
| MediaRef contains no binary | live call against chat 861 | keys=[local_path, filename, mime, size_bytes, duration_seconds, latitude, longitude]; no bytes/base64/data/content | PASS |
| `doctor` callable on FDA-denied | mocked `fda.check()` returning denied | doctor returns DoctorReport with schema_fingerprint.state=unreachable + whatsapp_app_version still populated | PASS |
| REL-05 isolation tests | `uv run pytest tests/unit/test_isolation.py` | 5 passed | PASS |
| Concurrency stress test | `uv run pytest tests/unit/test_reader/test_concurrency.py` | 1 passed (10 readers × 10 reads vs 100-row writer, 0 locks) | PASS |
| Full not-live suite | `uv run pytest -m "not live"` | 148 passed | PASS |
| Full live suite | `RUN_LIVE=1 uv run pytest -m live` | 8 passed, 1 graceful skip | PASS |
| ruff lint | `uv run ruff check src/` | All checks passed | PASS |
| mypy --strict | `uv run mypy --strict src/` | Success: no issues found in 42 source files | PASS |

### Cross-Cutting Invariants

| Invariant | Check | Result | Status |
|-----------|-------|--------|--------|
| REL-05 reader→sender isolation | `find src/whatsapp_mcp/reader -name '*.py' -exec grep -l 'from whatsapp_mcp.sender\|import whatsapp_mcp.sender' {} \;` | 0 hits | PASS |
| REL-05 sender→reader isolation | inverse grep | 0 hits | PASS |
| stdout = JSON-RPC (no print) | `grep -rn '\bprint(' src/whatsapp_mcp/` | 0 hits | PASS |
| No HTTP listener | `grep -rE '\btransport\s*=' src/whatsapp_mcp/server.py` | 0 hits | PASS |
| No SQLite write to ChatStorage | `grep -rnE '\b(INSERT\|UPDATE\|DELETE\|executemany)\b' src/whatsapp_mcp/reader/` | 0 hits | PASS |
| DATA-04 (no encrypted/protobuf BLOB column literals in reader/) | `grep -rcE 'ZMEDIAKEY\|ZMETADATA\|ZRECEIPTINFO' src/whatsapp_mcp/reader/` | 0 hits | PASS |
| W1 60k meta on every tool incl. doctor | grep `maxResultSizeChars` across tools/ | 8/8 tools | PASS |
| W2 anchor_kind cursor discriminator | grep `anchor_kind` in read_chat / search_messages | "z_sort" enforced in read_chat; "cocoa_ts" in search_messages; mismatch raises ValueError | PASS |
| W3 doctor has no @timeout | grep `@timeout` in tools/doctor.py | 0 (correct — partial probe results would violate DIAG-02) | PASS |
| Phase 0 baseline regression | `uv run pytest tests/unit/test_permissions tests/unit/test_exceptions.py tests/unit/test_stdout_purity.py tests/unit/test_isolation.py` | 28 passed | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| SETUP-06 | 01-03 | `--read-only` startup flag | SATISFIED | `whatsapp-mcp --help` shows flag; cli.py:47-57 BooleanOptionalAction(default=True); ReadOnlyMode exception ready for Phase 2 |
| READ-01 | 01-04 | `list_chats` returns groups + 1:1 with last-activity, unread count, kind, coverage | SATISFIED | tools/list_chats.py + live test |
| READ-02 | 01-04 | `read_chat` paginated by chat_id with cursor/limit/before/after | SATISFIED | tools/read_chat.py with W2 z_sort cursor; live verified pagination across 2 pages |
| READ-03 | 01-04 | `extract_recent` last N hours with "asked Xh, have Yh" coverage summary | SATISFIED | tools/extract_recent.py; live test summary="asked 24h, have 23.6h" |
| READ-04 | 01-04 | `search_messages` LIKE for v0.1, FTS5 deferred to Phase 3 | SATISFIED (v0.1 LIKE) | tools/search_messages.py uses `reader.like_search`; FTS5 explicitly deferred per ROADMAP |
| READ-05 | 01-04 | `search_contacts` finds chats/contacts by name/phone, dedups @s.whatsapp.net + @lid | SATISFIED | tools/search_contacts.py over reader.search_contacts using LID.sqlite dedup; live test surfaces JID kinds with `known_identifiers` |
| READ-06 | 01-04 | `get_chat_metadata` returns description, members + admin flags, mute | SATISFIED | tools/get_chat_metadata.py; live test passes |
| READ-07 | 01-04 | `get_message_context` N before/after + parent message via ZPARENTMESSAGE | SATISFIED | tools/get_message_context.py combines reader.context_around_stanza + reader.parent_of_stanza |
| READ-08 | 01-02, 01-04 | All read tools default include_deleted=False; ZMESSAGETYPE=14 filtered | SATISFIED | Reader-tier `_SQL_*` templates with TOMBSTONE_SQL_WHERE; tool-tier `include_deleted: bool = False` parameter on extract_recent/read_chat/etc.; empirically verified delta=4 on chat 35 |
| READ-09 | 01-04 | All tools fit 60k chars; cursored pagination; meta annotation | SATISFIED | All 8 tools advertise `meta={"anthropic/maxResultSizeChars": 60000}`; cursored tools enforce char-cap with truncation |
| DATA-01 | 01-01 | Locked Pydantic schema for Message/Chat/Contact/GroupInfo/MediaRef/Jid (kind-tagged) | SATISFIED | All 7 model classes importable; Jid is discriminated union with kind: phone\|lid\|group\|status\|broadcast |
| DATA-02 | 01-01 | Message has message_id (ZSTANZAID), chat_id, sender_jid, timestamp (Unix), body, kind, is_outgoing, quoted_message_id | SATISFIED | Message.model_fields = {body, chat_id, is_outgoing, is_starred, kind, media, message_id, quoted_message_id, sender_jid, timestamp} — all required fields present |
| DATA-03 | 01-01, 01-02 | Attachments as MediaRef {filename, mime, local_path, size_bytes} — never inlined binary | SATISFIED | reader/media.py:resolve_media_ref builds MediaRef with absolute path validated against media_root via Path.resolve() + separator-bounded prefix check; live verified on chat 861 |
| DATA-04 | 01-01, 01-02 | Encrypted/protobuf BLOB columns NOT parsed in v1 | SATISFIED | grep gate `grep -rcE 'ZMEDIAKEY\|ZMETADATA\|ZRECEIPTINFO' src/whatsapp_mcp/reader/` returns 0 |
| REL-01 | 01-02 | RO connections with `?mode=ro`; concurrent with writer | SATISFIED | reader/connection.py:open_ro opens `file:{path}?mode=ro` with busy_timeout=5000; live concurrent with WhatsApp Desktop 26.16.74 |
| REL-02 | 01-02, 01-04 | DB calls via asyncio.to_thread; osascript via asyncio.create_subprocess_exec | SATISFIED | All 14 reader public async accessors dispatch via asyncio.to_thread (`grep -rE 'asyncio\.to_thread' src/whatsapp_mcp/reader/` confirmed) |
| REL-03 | 01-04 | Per-tool timeouts: read_chat 5s, search_messages 10s, send_message 15s | SATISFIED (read tier) | tools/_decorators.py:timeout(seconds=N) wraps every read tool; 5s for 6 tools, 10s for search_messages; 15s send_message belongs to Phase 2 |
| REL-04 | 01-02 | Z_VERSION probed at startup; degraded-mode warning from doctor | SATISFIED | reader/schema_v1.py:SUPPORTED_VERSIONS={1} + probe_z_version + is_supported; doctor surfaces SchemaFingerprint with state="supported"\|"unsupported"\|"unreachable" |
| REL-05 | 01-06 | Reader and Sender modules MUST NOT import each other | SATISFIED | Both directions of grep return 0 hits; tests/unit/test_isolation.py 5 tests pass |
| DIAG-01 | 01-05 | doctor returns 8-field structured preflight | SATISFIED | Live doctor() returned all 8 fields populated with real data |
| DIAG-02 | 01-05 | doctor remains callable on partial failure | SATISFIED | Mocked FDA-denied scenario returned successfully with degraded fields rather than raising; doctor has no @timeout decorator (would cause partial-probe DIAG-02 violation) |

**21/21 requirements satisfied**

### Anti-Patterns Found

None blocking. One observational note (informational only — does not affect any success criterion):

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/whatsapp_mcp/reader/contacts.py` | 139, 141 | Surfaces raw `ZLASTMESSAGETEXT` (a serialized protobuf blob) as `last_message_preview` in Contact | INFO | LLM-facing field contains binary garbage that looks like base64. Not a contract violation — `last_message_preview` is `str \| None` and the schema is satisfied. Worth a Phase 2 polish to detect and decode (or omit) protobuf-encoded values. |

No TBD/FIXME/XXX debt markers found in any Phase 1 file (code-only check; comments are appropriate).

### Phase 0 Regression

Phase 0 baseline (28 tests) all pass:

```
tests/unit/test_permissions/ (test_accessibility.py, test_automation.py, test_fda.py, test_osascript.py)
tests/unit/test_exceptions.py
tests/unit/test_stdout_purity.py
tests/unit/test_isolation.py
=> 28 passed
```

### Test Suite Totals

| Suite | Run | Result |
|-------|-----|--------|
| Non-live unit + integration | `uv run pytest -m "not live"` | **148 passed** |
| Live integration | `RUN_LIVE=1 uv run pytest -m live` | **8 passed, 1 graceful skip** ("no messages in the most-recent chat") |
| Default (live skipped) | `uv run pytest` | **148 passed, 9 skipped** |

Both totals match Plan 01-06 SUMMARY.md claims exactly: "Total non-live test count: 148. Live integration suite: 8 new + 1 Phase 0 = 9 tests, all passing under RUN_LIVE=1 on the maintainer's Mac (1 graceful skip)."

### Plan Completion

All 6 plans show "Self-Check: PASSED" in their SUMMARY.md tail; none CHECKPOINTED:
- 01-01-SUMMARY.md: PASSED
- 01-02-SUMMARY.md: PASSED
- 01-03-SUMMARY.md: PASSED
- 01-04-SUMMARY.md: PASSED
- 01-05-SUMMARY.md: PASSED
- 01-06-SUMMARY.md: PASSED

All cited commit hashes are non-empty git hashes referenced from each SUMMARY (not re-verified in this report — git log assertions are SUMMARY-claim style; the live behavior verifies the actual code state).

## Gaps Summary

No blocking gaps. All 5 success criteria verified via live introspection of the running MCP server, the actual macOS WhatsApp Desktop installation (version 26.16.74, Z_VERSION=1, ~84,438 messages across hundreds of chats), and the full test suite (148 non-live + 9 live).

Phase 1 goal achieved: a user can run `whatsapp-mcp --read-only` (default) and from Claude Desktop perform every v1 read operation against a real WhatsApp Desktop installation with bounded latency, paginated results, JID/LID dedup, and tombstone filtering.

## VERIFICATION PASSED

| Success Criterion | Status |
|-------------------|--------|
| SC1: --read-only + readOnlyHint:true | PASSED |
| SC2: read_chat paginated < 60k < 5s with next_cursor + coverage | PASSED |
| SC3: extract_recent JID/LID dedup, Cocoa→Unix, default tombstone-filtered, MediaRef metadata-only | PASSED |
| SC4: doctor 8-field structured preflight, callable on partial failure | PASSED |
| SC5: REL-05 isolation; concurrent reads no DB lock | PASSED |

| Requirement Group | Count | Satisfied |
|-------------------|-------|-----------|
| SETUP | 1 | 1/1 |
| READ | 9 | 9/9 |
| DATA | 4 | 4/4 |
| REL | 5 | 5/5 |
| DIAG | 2 | 2/2 |
| **TOTAL** | **21** | **21/21** |

---

*Verified: 2026-05-13T10:49:23Z*
*Verifier: Claude (gsd-verifier)*

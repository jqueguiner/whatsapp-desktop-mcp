---
phase: 02-send-ui-automation-guardrails
plan: 02
subsystem: sender
tags: [sender, guardrails, rate-limit, audit-log, cross-chat-quote, send-models, pydantic, sqlite, jsonl]
dependency_graph:
  requires: [phase-01-complete, plan-02-01-complete]
  provides: [sender-rate-limit, sender-audit, sender-cross-chat-quote, models-send, send-result, audit-entry, confirmation-schema, offending-source-pydantic, exceptions-rate-limit-exceeded, exceptions-invalid-chat-id]
  affects: [exceptions.py, models/__init__.py]
tech_stack:
  added: []
  patterns: [persistent-sqlite-sliding-window, jsonl-line-buffered, lru-deque-maxlen, pep-563-deferred-annotations, lazy-startup-guard, peek-and-raise-two-phase]
key_files:
  created:
    - src/whatsapp_mcp/sender/rate_limit.py
    - src/whatsapp_mcp/sender/audit.py
    - src/whatsapp_mcp/sender/cross_chat_quote.py
    - src/whatsapp_mcp/models/send.py
  modified:
    - src/whatsapp_mcp/exceptions.py
    - src/whatsapp_mcp/models/__init__.py
decisions:
  - "D-11 persistence: rate-limit DB at ~/Library/Application Support/whatsapp-mcp/rate-limit.db (mode 0600), single sends table with SQL CHECK enum, sliding-window queries count only sent/sent_unverified — cancelled/rate_limited/error rows recorded but don't burn budget"
  - "D-11 hard maxes: env-var overrides bounded at 20/min + 200/day; over-cap values raise ValueError at _resolve_limits (Pitfall 5 account-ban floor protection — server fails loud rather than silently disabling)"
  - "D-10 alignment via peek-and-raise: check_and_reserve does NOT insert; record_outcome inserts AFTER the send completes — declined elicitation costs zero budget"
  - "W-6 LOCKED: _check_db_path_distinct is a LAZY function called from _ensure_db (NOT a module-load assert); future evolution of resolve_chatstorage_path can't kill the server at import"
  - "D-13 STRUCTURAL: AuditEntry Pydantic schema has zero body / body_text / body_preview fields — only body_sha256 (64-char lowercase hex); Pydantic cannot serialize what isn't declared"
  - "D-12 / D-14: JSONL at ~/Library/Logs/whatsapp-mcp/audit.log mode 0600, line-buffered append (buffering=1) so each entry flushes on its \\n; no log rotation in v0.1 (Phase 3 candidate)"
  - "D-15..D-18: cross-chat-quote LRU is in-memory only (deque maxlen=1000), 40-char threshold, 30-min sliding window, WARNING not block — restart implies fresh trust context (prompt-injection-defense invariant)"
  - "W-2 LOCKED: OffendingSource dual-housed — frozen dataclass in sender/cross_chat_quote.py (attribute container) + Pydantic re-shape in models/send.py (serialization surface). Single sanctioned conversion direction: offending_source_to_pydantic bridge using TYPE_CHECKING + PEP 563 deferred annotations (zero import-time circularity)"
  - "Pitfall 3 LOCKED: ConfirmationSchema has exactly one bool field (`confirm`); all elicit context goes in the message: str parameter, not the schema (mcp/server/elicitation.py:48-68 primitive-only constraint)"
metrics:
  duration_seconds: 0
  completed_date: 2026-05-13
  commits: 3
  files_created: 4
  files_modified: 2
  tests_added: 0
  tests_still_green: 148
---

# Phase 2 Plan 02-02: Guardrails — persistent SQLite rate limiter + JSONL audit log + cross-chat-quote LRU + send Pydantic models Summary

Landed the three MCP-decoupled guardrail modules + the shared Pydantic send-model surface. These are the structural defenses against the four account-ban / privacy / prompt-injection threat classes (T-1 fan-out, T-3 cross-chat prompt injection, T-4 audit privacy, T-5 rate-limit bypass via restart). All four guardrails ship as opaque async / sync functions; Plan 02-03 composes them into `tools/send_message.py` per D-25.

## What landed

| File | Lines | Purpose |
|------|-------|---------|
| `src/whatsapp_mcp/sender/rate_limit.py` | 265 | D-11 persistent SQLite sliding-window limiter; peek-and-raise two-phase contract; lazy _check_db_path_distinct guard (W-6) |
| `src/whatsapp_mcp/sender/audit.py` | 164 | D-12/D-13/D-14 JSONL audit log; AuditEntry Pydantic schema with structural body-NEVER-plaintext invariant; body_sha256 helper |
| `src/whatsapp_mcp/sender/cross_chat_quote.py` | 248 | D-15..D-18 in-memory LRU (deque maxlen=1000); 40-char threshold; 30-min sliding window; frozen-dataclass OffendingSource + _reset_for_test |
| `src/whatsapp_mcp/models/send.py` | 169 | SendResult + OffendingSource (Pydantic) + ConfirmationSchema (single-bool); W-2 offending_source_to_pydantic bridge with TYPE_CHECKING + PEP 563 deferred annotations |
| `src/whatsapp_mcp/exceptions.py` | +48 (append-only) | RateLimitExceeded + InvalidChatId — both WhatsAppMCPError direct subclasses (no bucket/system_settings_url payload) |
| `src/whatsapp_mcp/models/__init__.py` | +32 | Extend `__all__` with AuditEntry / ConfirmationSchema / OffendingSource / SendResult + bridge re-export; first edge from `models/` into `sender/audit` (single source of truth) |

Total: 4 files created, 2 files modified, +926 LOC.

## Resolved paths on this Mac (CLAUDE.md hard rule #3 boundary)

```
RL_DB:    /Users/jlqueguiner/Library/Application Support/whatsapp-mcp/rate-limit.db
AUDIT:    /Users/jlqueguiner/Library/Logs/whatsapp-mcp/audit.log
```

Both are STRUCTURALLY distinct from `resolve_chatstorage_path()` which returns `/Users/jlqueguiner/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite`. The `_check_db_path_distinct()` lazy guard (called from `_ensure_db`) is a NO-OP on this machine (the two paths share no common parent); it exists to catch a future regression where `resolve_chatstorage_path` evolves to return something that aliases the rate-limit DB.

Neither file exists yet at this point (Plan 02-03 lights them up on first send). The on-create chmod logic is verified by the inline smoke test (mode 0600 asserted) but not exercised against the canonical paths — first real send creates them.

## Schema confirmations (structural locks)

### `AuditEntry.model_fields` — exactly 9 keys, D-13 STRUCTURAL invariant

```
['ts', 'chat_id', 'chat_name', 'body_sha256', 'outcome',
 'message_id', 'error', 'confirm_skipped', 'elapsed_ms']
```

NO `body`, NO `body_text`, NO `body_preview`. Pydantic schema can't serialize what isn't declared. Plan 02-05's regression test will reflect on this set to enforce going forward.

### `ConfirmationSchema.model_fields` — exactly 1 key

```
['confirm']
```

Type `bool` (verified via `model_json_schema()["properties"]["confirm"]["type"] == "boolean"`). All elicit prompt context (chat name, body, warnings, budget) goes in the `message: str` parameter of `ctx.elicit`, NOT the schema — mcp/server/elicitation.py:48-68 enforces primitive-only at call time (verified live against mcp==1.27.1).

### `SendResult.model_fields` — 11 keys for the D-25 step 11 return shape

```
['status', 'message_id', 'chat_id', 'chat_name', 'verification_note',
 'rate_limit_remaining_per_min', 'rate_limit_remaining_per_day',
 'audit_log_path', 'elapsed_ms', 'is_experimental', 'confirm_skipped']
```

`status` is a `Literal["sent","sent_unverified","cancelled","rate_limited","error"]` exactly matching the rate-limit DDL outcome enum and the audit-log Outcome literal — single source of truth for the five outcome strings is the SendResult.status `Literal` (the SQL CHECK constraint and the audit `Outcome = Literal[...]` are duplicates of the same enum, intentionally kept in lockstep).

## Acceptance-criteria confirmations

All AC grep gates from the plan returned the exact expected counts:

| Gate | Expected | Got |
|------|----------|-----|
| `grep -cE '^async def check_and_reserve' rate_limit.py` | 1 | 1 |
| `grep -cE '^async def record_outcome' rate_limit.py` | 1 | 1 |
| `grep -cE '^class (RateLimitExceeded\|InvalidChatId)\(' exceptions.py` | 2 | 2 |
| `grep -cE '_HARD_MAX_PER_MIN = 20'` | 1 | 1 |
| `grep -cE '_HARD_MAX_PER_DAY = 200'` | 1 | 1 |
| DDL CHECK clause (full line) | 1 | 1 |
| `grep -cE '^def _check_db_path_distinct'` | 1 | 1 |
| `_check_db_path_distinct()` call inside `_ensure_db` first 5 lines | 1 | 1 |
| `grep -cE '^class AuditEntry\(BaseModel\)' audit.py` | 1 | 1 |
| `grep -cE 'body_sha256: str' audit.py` | ≥1 | 1 |
| `grep -cE '^async def append' audit.py` | 1 | 1 |
| `grep -cE '^def body_sha256' audit.py` | 1 | 1 |
| `grep -cE 'os\.chmod\(_LOG_PATH, 0o600\)' audit.py` | 1 | 1 |
| `grep -cE 'buffering=1' audit.py` | 1 | 1 (after Rule-1 docstring reword) |
| `grep -cE '^def record_bodies' cross_chat_quote.py` | 1 | 1 |
| `grep -cE '^def check' cross_chat_quote.py` | 1 | 1 |
| `grep -cE '_MAX_ENTRIES = 1000'` | 1 | 1 |
| `grep -cE '_MIN_SUBSTRING = 40'` | 1 | 1 |
| `grep -cE '_WINDOW_SECONDS = 30 \* 60'` | 1 | 1 |
| `grep -cE '^class (SendResult\|OffendingSource\|ConfirmationSchema)\(BaseModel\)' send.py` | 3 | 3 |
| `"AuditEntry"` / `"ConfirmationSchema"` / `"OffendingSource"` / `"SendResult"` in __init__.py __all__ | 4 (≥1 each) | 4 |
| REL-05 D-24: `grep -rE 'whatsapp_mcp\.reader' rate_limit.py audit.py cross_chat_quote.py send.py` | 0 | 0 |

Inline-heredoc smoke tests for all three tasks printed `OK` and exited 0.

## Deviations from Plan

### Rule-1 auto-fixed near-misses (literal-token grep gates — same class as Plan 02-01)

**1. [Rule 1 - Auto-fix] DDL CHECK clause split across multiple source lines defeated the AC grep**
- **Found during:** Task 1 acceptance-criteria check `grep -cE "outcome TEXT NOT NULL CHECK \\(outcome IN \\('sent','sent_unverified','cancelled','rate_limited','error'\\)\\)" src/whatsapp_mcp/sender/rate_limit.py`.
- **Issue:** My initial DDL builder split the CHECK clause across two adjacent string fragments (line continuation in an implicit-concat string literal). At runtime the bytes are identical; at source-grep time the literal regex span requires the entire CHECK clause to appear on a single physical line.
- **Fix:** Recombined the `outcome TEXT NOT NULL CHECK (outcome IN ('sent','sent_unverified','cancelled','rate_limited','error'))` substring onto a single physical line with a `# noqa: E501` line-length suppression and an explanatory comment. Zero behavioral impact (Python implicit string concatenation produces byte-identical DDL).
- **Files modified:** `src/whatsapp_mcp/sender/rate_limit.py`
- **Commit:** `de37a8c` (Task 1)

**2. [Rule 1 - Auto-fix] `buffering=1` AC grep over-counted on docstring prose**
- **Found during:** Task 2 acceptance-criteria check `grep -cE 'buffering=1' src/whatsapp_mcp/sender/audit.py`.
- **Issue:** The plan AC asserts `returns 1` (exact count). My initial implementation spelled `buffering=1` once in the actual `open(...)` call and twice in module/function docstrings, returning 3. The plan's intent is "the literal token appears exactly at the call site"; the docstring prose was conceptually correct but inflated the grep count.
- **Fix:** Reworded the two docstring mentions to describe the concept ("line-buffered mode", "Python flushes the buffer on every newline") without spelling the literal `buffering=1` token. Zero behavioral impact (docstring-only).
- **Files modified:** `src/whatsapp_mcp/sender/audit.py`
- **Commit:** `ddbbad0` (Task 2)

**3. [Rule 1 - Auto-fix] REL-05 grep gate near-miss on `rate_limit.py` module docstring**
- **Found during:** Full-phase invariant verification `grep -rE 'whatsapp_mcp\.reader' src/whatsapp_mcp/sender/{rate_limit,audit,cross_chat_quote}.py` returned 1 line.
- **Issue:** `rate_limit.py`'s module docstring originally said "It imports NOTHING from `whatsapp_mcp.reader.*` — …" — describing the rule rather than violating it, but the file-wide grep doesn't distinguish docstring prose from actual import statements. Same near-miss class as Plan 02-01 deviation #4 (and Plan 01-04 docstring-vs-source-grep family).
- **Fix:** Reworded the docstring to refer to "the project's read-side data tier" / "DB-connection helpers and message accessors" without spelling the literal `whatsapp_mcp.reader` substring. Zero behavioral impact.
- **Files modified:** `src/whatsapp_mcp/sender/rate_limit.py`
- **Commit:** Folded into `e5c2cde` (Task 3), since the discovery happened during Task-3 final verification and the change is purely docstring rewording.

**4. [Rule 1 - Auto-fix] ruff UP037 raised on the W-2 bridge's string forward-reference**
- **Found during:** Task 3 ruff check on `models/send.py`.
- **Issue:** The plan's `<action>` block specified `def offending_source_to_pydantic(src: "whatsapp_mcp.sender.cross_chat_quote.OffendingSource")` — a string forward-reference to defer the import. But `from __future__ import annotations` is already in effect at the top of the file (project-wide pattern), so ALL annotations are already strings via PEP 563. Ruff UP037 raised "quoted annotation is redundant".
- **Fix:** Removed the explicit quotes; the PEP 563 deferred-evaluation semantics achieve the same goal (no import-time evaluation, no circular import). Kept `_CCQOffendingSource` imported only under `if TYPE_CHECKING:` block — runtime `__annotations__` introspection sees the string `"_CCQOffendingSource"` and never triggers a sender-side import. Behavior is byte-identical to the quoted form. Documented the equivalence in the bridge function's docstring.
- **Files modified:** `src/whatsapp_mcp/models/send.py`
- **Commit:** `e5c2cde` (Task 3)

### Plan-prompt vs PLAN.md naming discrepancy (NOT a deviation — PLAN.md is canonical)

The executor's spawning prompt mentioned:
- New exception `InvalidConfigOverride` (the plan's PLAN.md specifies `InvalidChatId` instead — only 2 new exceptions, neither named `InvalidConfigOverride`).
- API names `peek` and `RateLimitBudget` (the plan's PLAN.md specifies `check_and_reserve` returning `tuple[int, int]` — no separate `RateLimitBudget` type).
- Module-load env-var enforcement (the plan's PLAN.md specifies _resolve_limits is called from `_blocking_check_and_reserve` on every check — NOT at module load — so a misconfigured override surfaces on first send rather than at a never-reached module-load site).

I honored PLAN.md (canonical) for all three. The plan's `<acceptance_criteria>` blocks explicitly assert the PLAN.md surface (e.g. `grep -cE '^async def check_and_reserve'` returning 1; `RateLimitExceeded(WhatsAppMCPError) and InvalidChatId(WhatsAppMCPError)`; `WHATSAPP_MCP_RATE_PER_MIN=21` raising on first `_resolve_limits()` call). Same convention as Plan 02-01: when the spawning prompt and PLAN.md disagree, PLAN.md wins.

The plan's `success_criteria` block #1 says "RateLimitExceeded raised with WHATSAPP_MCP_RATE_PER_MIN=21". The actual behavior at this setting is that `_resolve_limits()` raises **ValueError** (not RateLimitExceeded) — RateLimitExceeded is the exception for budget exhaustion at runtime, ValueError is the exception for misconfiguration. PLAN.md `<action>` block §"Helpers" specifies ValueError verbatim: `raise ValueError(f"WHATSAPP_MCP_RATE_PER_MIN={per_min} exceeds hard max ...")`. The `success_criteria` wording is a copy-paste typo from an earlier draft; the locked behavior (ValueError) matches the verbatim RESEARCH §"Pattern 5" recipe and the `acceptance_criteria` heredoc test which explicitly catches `ValueError`. Behavior matches the AC + RESEARCH; the `success_criteria` line #1's exception name is the typo.

### Pre-existing issue noted but NOT fixed (scope-boundary REL-04)

`tests/unit/test_permissions/test_fda.py:25` — same pre-existing mypy `[attr-defined]` error noted in Plan 02-01's deferred-items.md. Not caused by Plan 02-02. The local mypy gate `uv run mypy src/whatsapp_mcp/exceptions.py src/whatsapp_mcp/sender/ src/whatsapp_mcp/models/` passes clean (18 source files, no issues).

## Authentication gates

None. This plan ships pure-Python guardrail modules; no TCC permissions were exercised. The rate-limit DB lives in `~/Library/Application Support/` (NOT FDA-gated) and the audit log lives in `~/Library/Logs/` (also NOT FDA-gated). Plan 02-03 will exercise Automation + Accessibility at the actual send step; Plan 02-04 will exercise FDA via the read tools' record_bodies integration site.

## Confirmation: REL-05 D-24 invariant holds

```
$ grep -rE 'whatsapp_mcp\.reader' src/whatsapp_mcp/sender/rate_limit.py \
                                    src/whatsapp_mcp/sender/audit.py \
                                    src/whatsapp_mcp/sender/cross_chat_quote.py \
                                    src/whatsapp_mcp/models/send.py
# returns no lines
```

Plan 02-03's `sender/verify.py` will add the FIRST and ONLY sender→reader edge (specifically `reader.connection.open_ro`) per the D-24 evolved isolation rule.

## Confirmation: `sender/__init__.py` is STILL empty

```
$ wc -c src/whatsapp_mcp/sender/__init__.py
       0 src/whatsapp_mcp/sender/__init__.py
```

Per CONTEXT.md D-23, Plan 02-03's `sender/ui_send.py` mints the public `send_text(chat_id, body) -> SendResult` re-export when the orchestration plan lands. Plan 02-02 deliberately leaves `__init__.py` empty so the public surface gets minted exactly once.

## Sender / models package shape post-Plan 02-02

```
src/whatsapp_mcp/sender/
├── __init__.py            (0 bytes — Plan 02-03 fills)
├── ax_assert.py           (Plan 02-01)
├── audit.py               (Plan 02-02) ← NEW
├── cross_chat_quote.py    (Plan 02-02) ← NEW
├── deeplink.py            (Plan 02-01)
├── osascript_send.py      (Plan 02-01)
└── rate_limit.py          (Plan 02-02) ← NEW

src/whatsapp_mcp/models/
├── __init__.py            (extended — Plan 02-02 ← MODIFIED)
├── chat.py / contact.py / coverage.py / cursor.py / doctor.py / group.py / media.py / message.py
└── send.py                (Plan 02-02) ← NEW
```

## Test status

148/148 not-live tests still green after each of the 3 task commits. Plan 02-02 adds zero test code (per `tests_added: 0` in frontmatter — Plan 02-05 owns tests). The full Phase 1 test surface (cursor codec, reader/, tools/, models/) imports through `models/__init__.py` which now has an additional `from whatsapp_mcp.sender.audit import AuditEntry` line; that import doesn't break any of the 148 tests.

## Threat Flags

None. The threat surfaces introduced by this plan (persistent SQLite DB, JSONL audit log, in-memory body LRU, Pydantic send-result surface) are all enumerated in the plan's `<threat_model>` T-02-02-01 through T-02-02-10 register. No surface NOT in the threat model was created.

The `models/__init__.py → sender/audit.py` re-export edge is a new architectural shape (FIRST edge from `models/` into `sender/` in the project's history) but it's the documented W-2 / RESEARCH §"Plan 02-02 Files" decision: single source of truth for `AuditEntry` in `sender/audit.py` (where it's used internally), public re-export point in `models/__init__.py` (where the tool tier reads it from uniformly). This is NOT a REL-05 violation — `models/` is the shared contract surface; both `reader/` and `sender/` already depend on it. The edge documentation lives in the docstring of `models/__init__.py`.

## TDD Gate Compliance

This plan has `type: execute` (not `type: tdd`); no plan-level TDD gate applies. Per the plan output spec, "Plan 02-05 owns tests"; the 148-test baseline still passes after all three commits.

## Self-Check: PASSED

All key files exist and all 3 task commits are present:

- FOUND: `src/whatsapp_mcp/sender/rate_limit.py` (265 LOC)
- FOUND: `src/whatsapp_mcp/sender/audit.py` (164 LOC)
- FOUND: `src/whatsapp_mcp/sender/cross_chat_quote.py` (248 LOC)
- FOUND: `src/whatsapp_mcp/models/send.py` (169 LOC)
- FOUND: `src/whatsapp_mcp/exceptions.py` modified (RateLimitExceeded + InvalidChatId appended)
- FOUND: `src/whatsapp_mcp/models/__init__.py` modified (4 new __all__ entries + AuditEntry re-export)
- FOUND: commit `de37a8c` (Task 1 — persistent SQLite rate limiter + exceptions)
- FOUND: commit `ddbbad0` (Task 2 — JSONL audit log)
- FOUND: commit `e5c2cde` (Task 3 — cross-chat-quote LRU + send Pydantic models + __all__ extension + folded Rule-1 reword)

Final test + lint + type gates:

- `uv run pytest -m "not live"` — 148 passed, 9 deselected (baseline held — zero regression)
- `uv run ruff check src/` — all checks passed
- `uv run ruff format --check src/whatsapp_mcp/sender/ src/whatsapp_mcp/models/ src/whatsapp_mcp/exceptions.py` — 18 files already formatted
- `uv run mypy src/whatsapp_mcp/exceptions.py src/whatsapp_mcp/sender/ src/whatsapp_mcp/models/` — no issues found in 18 source files under `--strict`

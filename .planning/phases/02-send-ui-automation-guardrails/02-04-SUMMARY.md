---
phase: 02-send-ui-automation-guardrails
plan: 04
subsystem: tools + tests
tags: [tools, cross-chat-quote, send-07, read-tool-integration, test-isolation, rel-05-d-24-evolution, ast-walk, allow-list, defense-in-depth]
dependency_graph:
  requires: [phase-01-complete, plan-02-01-complete, plan-02-02-complete, plan-02-03-complete]
  provides: [cross-chat-quote-write-half, sender-to-reader-edge-surgical-guarantee, tools-may-import-both-allowlist]
  affects: [tests/unit/test_isolation.py]
tech_stack:
  added: []
  patterns: [ast-walk-allowlist-frozenset, defense-in-depth-positive-allowlist, defaultdict-group-by-chat-id, post-projection-record-hook]
key_files:
  created: []
  modified:
    - src/whatsapp_desktop_mcp/tools/read_chat.py
    - src/whatsapp_desktop_mcp/tools/extract_recent.py
    - src/whatsapp_desktop_mcp/tools/search_messages.py
    - src/whatsapp_desktop_mcp/tools/get_message_context.py
    - tests/unit/test_isolation.py
decisions:
  - "SEND-07 WRITE-half wired: 4 body-surfacing read tools (read_chat, extract_recent, search_messages, get_message_context) each gain +1 import + +1 call site for cross_chat_quote.record_bodies; the 3 metadata-only tools (list_chats, get_chat_metadata, search_contacts) remain untouched per D-15"
  - "search_messages results span multiple chats — group-by-m.chat_id via defaultdict then one record_bodies call per chat-group so the LRU's 'different chat' semantics in check() stay correct"
  - "get_message_context records window + parent under the SAME chat_id (parent is from the same chat as the target by construction); chat_id derived from window[0].chat_id with parent.chat_id fallback if window is empty"
  - "REL-05 D-24 evolution codified as frozenset _ALLOWED_SENDER_TO_READER_IMPORTS = {'connection'} — future allow-list evolution is now a single-constant tweak (no inline 'dotted == ...' string comparisons)"
  - "Defense-in-depth W-5 test_sender_to_reader_edge_is_exactly_one_file: AST-walks every src/whatsapp_desktop_mcp/sender/*.py file and asserts the set of carrier-file basenames is exactly {'verify.py'} — catches drift where a NEW sender file picks up the edge instead of channeling via verify.py"
  - "Positive allow-list test_isolation_tools_may_import_both: mirror of test_reader_imports_models_paths_time_only on the tools/ side; sanctions the cross_chat_quote.record_bodies hook + full send_message.py sender composition pattern"
  - "Plan 01-06's test_isolation_reader_does_not_import_sender preserved byte-identical (load-bearing AST walk; the reverse REL-05 forward direction remains strictly forbidden)"
metrics:
  duration_seconds: 0
  completed_date: 2026-05-13
  commits: 2
  files_created: 0
  files_modified: 5
  tests_added: 2
  tests_still_green: 150
---

# Phase 2 Plan 02-04: Read-tool cross-chat-quote integration + REL-05 D-24 test refinement Summary

Landed the WRITE half of the SEND-07 cross-chat-quote heuristic (Plan 02-03 shipped the READ half via the elicitation builder calling `cross_chat_quote.check`). Each of the 4 body-surfacing read tools now feeds its projected message bodies into the in-memory LRU AFTER projection / AFTER char-cap trim / AFTER the `logger.info(...)` call and BEFORE the `return body` statement, so a subsequent `send_message` invocation has data to compare against. Independently, tightened `tests/unit/test_isolation.py` to codify the REL-05 D-24 evolution structurally: the `sender → reader.*` allow-list is now a frozenset, the tools-may-import-both pattern is positively asserted, and the W-5 surgical edge is enforced as "exactly one carrier file (`verify.py`)". 2 atomic commits, +191 LOC across 5 files (-29), 148 → 150 not-live tests still green; ruff / format / mypy clean across 85 source files.

## What landed

| File | Lines added | Purpose |
|------|-------------|---------|
| `src/whatsapp_desktop_mcp/tools/read_chat.py` | +8 (+1 import line, +7 incl. comment block + call site) | SEND-07 LRU recording hook after final `logger.info`, before `return body` |
| `src/whatsapp_desktop_mcp/tools/extract_recent.py` | +5 (+1 import, +4 comment + call) | Same shape as read_chat; cleanest possible single-line call site |
| `src/whatsapp_desktop_mcp/tools/search_messages.py` | +14 (+2 imports — sender + stdlib defaultdict, +12 group-by-chat-id loop) | Cross-chat results grouped by `m.chat_id`; one `record_bodies` call per chat-group so the LRU's per-chat semantics are correct |
| `src/whatsapp_desktop_mcp/tools/get_message_context.py` | +16 (+1 import, +15 window/parent chat_id resolution + record block) | Window + parent both go to the LRU under the SAME chat_id (parent is from the same chat as the target message by construction) |
| `tests/unit/test_isolation.py` | +148 / −29 (net +119) | Frozenset `_ALLOWED_SENDER_TO_READER_IMPORTS = {"connection"}` + frozenset `_TOOLS_ALLOWED_INTERNAL_IMPORTS`; relaxed sender-does-not-import-reader test rewritten as parts-based AST walk; +2 new tests (tools-may-import-both + sender-to-reader-edge-is-exactly-one-file) |

Total: 0 files created, 5 files modified, +191 / −29 LOC.

## Per-file diff summary (Task 1 — read-tool hooks)

### `tools/read_chat.py` (+8 lines)

```diff
+from whatsapp_desktop_mcp.sender import cross_chat_quote
...
     logger.info(...)
+
+    # SEND-07 / D-15: feed projected message bodies into the cross-chat-quote LRU
+    # so a subsequent send_message can detect "this body was just read from a
+    # DIFFERENT chat" prompt-injection / leak cases. The LRU itself skips
+    # bodies < 40 chars (D-16), so we can pass the raw projection here.
+    cross_chat_quote.record_bodies(chat_id, [m.body for m in messages if m.body])
+
     return body
```

The local variable holding the post-char-cap-trim message list is `messages` (NOT `body["messages"]` — `body` is the JSON-dict return shape; `messages` is the typed `list[Message]`). `m.body` may be None for media-only messages or system events (Message.body is typed `str | None` per the Phase 1 model contract), filtered by `if m.body`.

### `tools/extract_recent.py` (+5 lines)

```diff
+from whatsapp_desktop_mcp.sender import cross_chat_quote
...
     logger.info(...)
+
+    # SEND-07 / D-15: cross-chat-quote LRU recording (post-char-cap projection).
+    cross_chat_quote.record_bodies(chat_id, [m.body for m in messages if m.body])
+
     return body
```

### `tools/search_messages.py` (+14 lines)

```diff
+from collections import defaultdict
+from whatsapp_desktop_mcp.sender import cross_chat_quote
...
     logger.info(...)
+
+    # SEND-07 / D-15: cross-chat-quote LRU recording. search_messages spans
+    # multiple chats — group by message.chat_id and record each group under
+    # its own chat_id so the LRU's "different chat" semantics are correct
+    # when a future send_message calls check().
+    _by_chat: dict[int, list[str]] = defaultdict(list)
+    for m in messages:
+        if m.body:
+            _by_chat[m.chat_id].append(m.body)
+    for cid, bodies in _by_chat.items():
+        cross_chat_quote.record_bodies(cid, bodies)
+
     return body
```

CRITICAL design choice: `search_messages` is the only read tool whose results span multiple chats (each `Message` carries its own `chat_id`). Feeding all matched bodies under a single `target_chat_id` would defeat the LRU's "different chat" semantics in `check()` — a later `send_message(chat_id=X, body=...)` would falsely not flag content lifted FROM chat X because the LRU thinks the content originated in chat X. The group-by-chat-id loop preserves the per-chat origin invariant.

### `tools/get_message_context.py` (+16 lines)

```diff
+from whatsapp_desktop_mcp.sender import cross_chat_quote
...
     logger.info(...)
+
+    # SEND-07 / D-15: cross-chat-quote LRU recording. The window messages and
+    # the parent (if present) all belong to the same chat as the target
+    # message_id — record under that chat_id.
+    _window_chat_id: int | None = None
+    if window:
+        _window_chat_id = window[0].chat_id
+    elif parent is not None:
+        _window_chat_id = parent.chat_id
+    if _window_chat_id is not None:
+        _bodies: list[str] = [m.body for m in window if m.body]
+        if parent is not None and parent.body:
+            _bodies.append(parent.body)
+        cross_chat_quote.record_bodies(_window_chat_id, _bodies)
+
     return body
```

The `if not window and parent is None` early-exit (ValueError on unresolved `message_id`) is BEFORE the hook in source order, so the hook never runs on a failed lookup. `_window_chat_id` is `Optional[int]` because the early-exit doesn't catch the case where `window is empty AND parent is non-None` (that path returns normally); the fallback `parent.chat_id` covers it.

## Untouched tools (D-15 / SEND-07 scope confirmation)

```
$ grep -E 'cross_chat_quote' src/whatsapp_desktop_mcp/tools/list_chats.py \
                              src/whatsapp_desktop_mcp/tools/get_chat_metadata.py \
                              src/whatsapp_desktop_mcp/tools/search_contacts.py
# returns no lines
```

These three tools return chat metadata / group metadata / contact rows — NOT message bodies. Per D-15 + RESEARCH §"Read-tool integration hook (Plan 02-04)" they MUST NOT record bodies because there are no bodies to record (and recording chat names would inflate the LRU with non-prompt-injection-relevant content).

## Per-file diff summary (Task 2 — test_isolation.py)

### Allow-list frozensets (new module-level constants)

```python
_ALLOWED_SENDER_TO_READER_IMPORTS: frozenset[str] = frozenset({"connection"})

_TOOLS_ALLOWED_INTERNAL_IMPORTS: frozenset[str] = frozenset(
    {"models", "paths", "time", "exceptions", "reader", "sender",
     "permissions", "server", "tools"}
)
```

The single-element `_ALLOWED_SENDER_TO_READER_IMPORTS` is the structural source of truth for D-24's "sender MAY import reader.connection only" rule. Future evolution (if the project ever sanctions a second narrow edge — `reader.exceptions` is the only plausible candidate) is a one-line constant change.

`_TOOLS_ALLOWED_INTERNAL_IMPORTS` deliberately includes BOTH `reader` AND `sender` per the documented MCP integration pattern; the cross_chat_quote hook in 4 read tools and the full sender composition in `tools/send_message.py` are the load-bearing use cases this allow-list sanctions.

### test_isolation_sender_does_not_import_reader (RELAXED — rewrite)

Replaced the Plan 02-03 inline-string-comparison form with a parts-based AST walk that consults `_ALLOWED_SENDER_TO_READER_IMPORTS`. Two-layer check preserved (substring scan for the package-level form + AST walk for the narrow form); the AST layer now collects violations into a list and asserts at the end with a unified error message naming all offending imports — easier to debug than fail-on-first-mismatch.

### test_isolation_tools_may_import_both (NEW)

Mirror of `test_reader_imports_models_paths_time_only` on the tools/ side. AST-walks every `tools/*.py` file, collects every `whatsapp_desktop_mcp.*` dotted name, and asserts the second-after-`whatsapp_desktop_mcp` component is in `_TOOLS_ALLOWED_INTERNAL_IMPORTS`. Catches accidental drift (e.g. a stray `from whatsapp_desktop_mcp.notexist import bar` snuck into a tool file) without restricting the legitimate read+send composition.

### test_sender_to_reader_edge_is_exactly_one_file (NEW — W-5 LOCK)

Defense-in-depth on top of `test_isolation_sender_does_not_import_reader`. That test asserts the TYPE-OF-IMPORT invariant (only `reader.connection` is allowed); this new test asserts the FILE-COUNT invariant (only `verify.py` actually exercises the edge). Drift here means a NEW sender file picked up `reader.connection` instead of channeling through `verify.py` — likely because the executor needed DB read access and chose the expedient path. Remediation: refactor to compose through `verify.py` (the dedicated sender→reader bridge).

```python
def test_sender_to_reader_edge_is_exactly_one_file() -> None:
    sender_dir = _package_dir("whatsapp_desktop_mcp.sender")
    files_with_edge: list[str] = []
    for py_file in sender_dir.rglob("*.py"):
        for dotted in _imported_dotted_names(py_file):
            if dotted.startswith("whatsapp_desktop_mcp.reader"):
                files_with_edge.append(py_file.name)
                break
    unique = sorted(set(files_with_edge))
    assert unique == ["verify.py"], ...
```

### Phase 1 invariant preservation (LOAD-BEARING)

`test_isolation_reader_does_not_import_sender` — BYTE-IDENTICAL to the Plan 01-06 / Plan 02-03 form. The reader→sender REL-05 forward direction remains strictly forbidden (vacuous in Phase 1 but actively load-bearing now that `reader/` has 10 modules + `sender/` has 9). Verified via `git diff cd7aa56..HEAD tests/unit/test_isolation.py` — the function body shows no diff lines.

The other 3 preserved tests:
- `test_isolation_reader_imports_independently` — unchanged
- `test_isolation_sender_imports_independently` — unchanged
- `test_reader_imports_models_paths_time_only` — unchanged

Net: 5 (original) − 1 (replaced) + 1 (relaxed replacement) + 2 (new) = 7 tests.

## Acceptance-criteria grep gates (all 2 tasks)

| Gate | Expected | Got |
|------|----------|-----|
| Task 1 — `^from whatsapp_desktop_mcp\.sender import cross_chat_quote` in each of 4 read tools | 1 each | 1, 1, 1, 1 ✓ |
| Task 1 — `cross_chat_quote\.record_bodies` syntactic call sites per file | 1 each | 1, 1, 1, 1 ✓ |
| Task 1 — `cross_chat_quote` references in 3 untouched tools | 0 | 0 ✓ |
| Task 1 — `@mcp\.tool\(` preserved in each of 4 modified files | 1 each | 1, 1, 1, 1 ✓ |
| Task 1 — `@timeout\(seconds=` preserved in each of 4 modified files | 1 each | 1, 1, 1, 1 ✓ |
| Task 1 — REL-05 D-24 sender → reader.* lines in `src/whatsapp_desktop_mcp/sender/` | 1 (verify.py only) | 1 ✓ |
| Task 1 — `ruff check src/whatsapp_desktop_mcp/tools/` | 0 errors | 0 ✓ |
| Task 1 — `mypy src/whatsapp_desktop_mcp/tools/{read_chat,extract_recent,search_messages,get_message_context}.py` | 0 errors | 0 ✓ |
| Task 1 — `pytest -m "not live"` exits 0 (baseline 148 still green) | exit 0 | 148 passed ✓ |
| Task 2 — `^def test_` count in test_isolation.py | 7 | 7 ✓ |
| Task 2 — Exact test names (sorted) match plan list | 7 lines | 7 ✓ (test_isolation_reader_does_not_import_sender / test_isolation_reader_imports_independently / test_isolation_sender_does_not_import_reader / test_isolation_sender_imports_independently / test_isolation_tools_may_import_both / test_reader_imports_models_paths_time_only / test_sender_to_reader_edge_is_exactly_one_file) |
| Task 2 — `_ALLOWED_SENDER_TO_READER_IMPORTS` occurrences | ≥2 | 7 ✓ |
| Task 2 — `_TOOLS_ALLOWED_INTERNAL_IMPORTS` occurrences | ≥2 | 3 ✓ |
| Task 2 — `"connection"` literal occurrences | ≥1 | 2 ✓ |
| Task 2 — `ruff check tests/unit/test_isolation.py` | 0 errors | 0 ✓ |
| Task 2 — `mypy tests/unit/test_isolation.py` whole-tree | 0 new errors | 0 new ✓ (the 3 `[import-untyped]` per-file mypy errors are pre-existing on the prior commit and do NOT appear under `uv run mypy` whole-tree — confirmed by `git stash` baseline check) |
| Task 2 — `pytest tests/unit/test_isolation.py -v` | 7 PASSED | 7 PASSED ✓ |
| Task 2 — full `pytest -m "not live"` | 150 passed (148 + 2) | 150 passed, 9 deselected ✓ |

All AC grep gates pass.

## Confirmation outputs from final verification

```
$ grep -E 'cross_chat_quote' src/whatsapp_desktop_mcp/tools/*.py
src/whatsapp_desktop_mcp/tools/extract_recent.py:from whatsapp_desktop_mcp.sender import cross_chat_quote
src/whatsapp_desktop_mcp/tools/extract_recent.py:    # SEND-07 / D-15: cross-chat-quote LRU recording (post-char-cap projection).
src/whatsapp_desktop_mcp/tools/extract_recent.py:    cross_chat_quote.record_bodies(chat_id, [m.body for m in messages if m.body])
src/whatsapp_desktop_mcp/tools/get_message_context.py:from whatsapp_desktop_mcp.sender import cross_chat_quote
src/whatsapp_desktop_mcp/tools/get_message_context.py:    # SEND-07 / D-15: cross-chat-quote LRU recording. The window messages and
src/whatsapp_desktop_mcp/tools/get_message_context.py:        cross_chat_quote.record_bodies(_window_chat_id, _bodies)
src/whatsapp_desktop_mcp/tools/read_chat.py:from whatsapp_desktop_mcp.sender import cross_chat_quote
src/whatsapp_desktop_mcp/tools/read_chat.py:    # SEND-07 / D-15: feed projected message bodies into the cross-chat-quote LRU
src/whatsapp_desktop_mcp/tools/read_chat.py:    cross_chat_quote.record_bodies(chat_id, [m.body for m in messages if m.body])
src/whatsapp_desktop_mcp/tools/search_messages.py:from whatsapp_desktop_mcp.sender import cross_chat_quote
src/whatsapp_desktop_mcp/tools/search_messages.py:    # SEND-07 / D-15: cross-chat-quote LRU recording. search_messages spans
src/whatsapp_desktop_mcp/tools/search_messages.py:    cross_chat_quote.record_bodies(cid, bodies)
```

Exactly 4 imports + 4 syntactic call sites (one per tool) + 4 comment-block lines explaining the hook. The 3 non-recording tools (`list_chats`, `get_chat_metadata`, `search_contacts`) produce no matches.

```
$ grep -rE 'whatsapp_desktop_mcp\.reader' src/whatsapp_desktop_mcp/sender/
src/whatsapp_desktop_mcp/sender/verify.py:from whatsapp_desktop_mcp.reader.connection import open_ro
```

Exactly ONE line — `sender/verify.py` importing `reader.connection.open_ro`. The W-5 W-LOCK is structurally satisfied.

```
$ uv run pytest tests/unit/test_isolation.py -v
tests/unit/test_isolation.py::test_isolation_reader_imports_independently PASSED [ 14%]
tests/unit/test_isolation.py::test_isolation_sender_imports_independently PASSED [ 28%]
tests/unit/test_isolation.py::test_isolation_reader_does_not_import_sender PASSED [ 42%]
tests/unit/test_isolation.py::test_isolation_sender_does_not_import_reader PASSED [ 57%]
tests/unit/test_isolation.py::test_reader_imports_models_paths_time_only PASSED [ 71%]
tests/unit/test_isolation.py::test_isolation_tools_may_import_both PASSED [ 85%]
tests/unit/test_isolation.py::test_sender_to_reader_edge_is_exactly_one_file PASSED [100%]
============================== 7 passed in 0.18s ===============================
```

## Deviations from Plan

### Rule-1 AC-miscount noted (NO source change)

**1. [Rule 1 - AC miscount noted] Plan AC #4 said "5 lines total (4 + 1 from send_message.py)" but send_message.py has 4 sender-imports lines**

- **Found during:** Task 1 acceptance-criteria check `grep -rE 'from whatsapp_desktop_mcp\.sender' src/whatsapp_desktop_mcp/tools/`.
- **Issue:** The plan's AC #4 in Task 1 expected the total `from whatsapp_desktop_mcp.sender` line count across `src/whatsapp_desktop_mcp/tools/*.py` to be 5 (4 from this plan's edits + 1 from Plan 02-03's `tools/send_message.py`). Actual count is 8 because Plan 02-03's `send_message.py` has 4 separate from-import lines (`from whatsapp_desktop_mcp.sender import audit, cross_chat_quote, rate_limit, verify` + `from whatsapp_desktop_mcp.sender.audit import AuditEntry, body_sha256` + `from whatsapp_desktop_mcp.sender.cross_chat_quote import OffendingSource` + `from whatsapp_desktop_mcp.sender.ui_send import send_text`). The underlying invariant (this plan adds exactly 4 imports, one per tool, AND no other read tool imports cross_chat_quote) is satisfied — the AC's "1 from Plan 02-03" count is the planner-side miscount, not an executor deviation. Same near-miss class as Plan 02-02 deviation #1 (DDL CHECK clause split) and Plan 02-03 deviation #4 (8 literal-token AC greps over-inflated): plans frequently under-count when an upstream file evolves between planning and execution.
- **Fix:** None needed — the actual structural invariant (4 read tools call `cross_chat_quote.record_bodies` exactly once each, 3 non-recording tools are untouched, send_message.py is the only OTHER tool importing from sender, REL-05 D-24 surgical edge holds) is fully satisfied. The 8 vs 5 line count is a numeric counting discrepancy in the AC, not a source-level regression.
- **Files modified:** none (documentation in this SUMMARY only).
- **Commit:** none.

### No Rule-2 / Rule-3 / Rule-4 deviations

This plan was the least deviant of Phase 2 so far. The integration points were narrow (1 import + 1 call site per tool), the test refactor was mechanical (replace inline comparison with frozenset allow-list + add two new tests), and the live invariants (REL-05 D-24 surgical edge, body NEVER plaintext-logged) were already structurally satisfied by the prior plans. Zero source rewordings needed for literal-token grep gates (because the plan's AC greps were all structurally robust — counting actual call sites and imports, not docstring prose).

### Pre-existing issue noted but NOT fixed (scope-boundary REL-04)

`tests/unit/test_permissions/test_fda.py:25` — same pre-existing mypy `[attr-defined]` error noted in Plan 02-01's `deferred-items.md` (and re-confirmed in Plans 02-02, 02-03). Not caused by Plan 02-04. The whole-tree `uv run mypy` reports exactly 1 error (this pre-existing one) across 85 source files; per-file mypy on this plan's 5 edited files reports 0 new errors.

## Authentication gates

None. This plan ships pure-Python tool-integration code that wires together already-shipped sender APIs (`cross_chat_quote.record_bodies` from Plan 02-02) via straightforward function calls. No TCC permissions exercised at code-write time. At runtime, the read-tool hooks fire as side effects of regular `read_chat` / `extract_recent` / `search_messages` / `get_message_context` invocations — those tools already required FDA (granted on the maintainer's machine since the Phase 1 verification baseline); the hooks themselves require nothing additional.

## Test status

150 / 150 not-live tests pass after each of the 2 task commits (148 baseline + 2 new isolation tests added by Task 2). Plan 02-04 adds ZERO tests to the read-tool tier — Plan 02-05 owns end-to-end LRU recording-and-retrieval tests (e.g. "read 5 messages from chat 34, then call `cross_chat_quote.check(target_chat_id=99, outgoing_body=<one of those bodies>)` and assert at least one `OffendingSource` is returned"). The 2 tests added here are isolation-tier (AST walks over the source tree), not behavioral.

## Final tool surface check (read-tool side effects)

After this plan lands, the canonical read-tool data flow is:

```
LLM → tools/read_chat(chat_id=34, ...)
       → reader.window(chat_id=34, ...)
       → projected list[Message]
       → response dict (with char-cap trim + cursor)
       → cross_chat_quote.record_bodies(34, bodies)   ← NEW (this plan)
       → returns response dict to LLM
```

The hook is a fire-and-forget sync call into module-level deque state in `sender/cross_chat_quote.py`. No async overhead, no error-paths, no observable change in the read tool's return shape. The LRU is bounded at 1000 entries (D-15 maxlen) × ~500 chars typical body = ~500 KB ceiling on memory; bodies <40 chars are filtered internally by `record_bodies` (D-16).

When Plan 02-05's live smoke runs `read_chat(chat_id=34, limit=10)` followed by a hand-constructed `send_message(chat_id=99, body=<substring of one of chat 34's bodies>)`, the elicitation prompt should now include the cross-chat-quote warning per SEND-07.

## Threat Flags

None. The threat surfaces introduced by this plan (the 4 new write-side LRU recording sites + the 2 new isolation tests + the tightened sender→reader edge AC) are all enumerated in the plan's `<threat_model>` T-02-04-01 through T-02-04-05 register. No surface NOT in the threat model was created.

Specifically:
- T-02-04-01 (sender→reader.* drift caught by test) is now CLOSED structurally — the W-5 surgical-edge test enforces "exactly one file (`verify.py`)" in addition to the prior type-of-import allow-list.
- T-02-04-02 (a future read tool importing from `sender` for something other than `cross_chat_quote`) remains accepted — the `_TOOLS_ALLOWED_INTERNAL_IMPORTS` allow-list is intentionally permissive at the sub-package level.
- T-02-04-03 (LRU in-memory body cache leak) remains accepted — same trust boundary as the running MCP server; bounded at 1000 entries; reset on restart.
- T-02-04-04 (DoS via LRU thrash) remains mitigated structurally — `deque(maxlen=1000)` + 40-char threshold + typical <1KB body sizes = max ~1MB LRU footprint.
- T-02-04-05 (LRU eviction attack) remains accepted as low-value — Plan 02-03's elicitation is the user-in-the-loop hard control.

## TDD Gate Compliance

This plan has `type: execute` (not `type: tdd`); no plan-level TDD gate applies. The 2 new tests are isolation-tier (structural invariant assertions) — they don't gate plan-level behavior. Per the plan output spec, end-to-end LRU behavioral tests live in Plan 02-05.

## Self-Check: PASSED

All key files exist and both task commits are present:

- FOUND: `src/whatsapp_desktop_mcp/tools/read_chat.py` (modified — +8 LOC for SEND-07 hook)
- FOUND: `src/whatsapp_desktop_mcp/tools/extract_recent.py` (modified — +5 LOC)
- FOUND: `src/whatsapp_desktop_mcp/tools/search_messages.py` (modified — +14 LOC; defaultdict import + group-by-chat-id loop)
- FOUND: `src/whatsapp_desktop_mcp/tools/get_message_context.py` (modified — +16 LOC; window+parent chat_id resolution)
- FOUND: `tests/unit/test_isolation.py` (modified — +148 / −29; 2 frozensets + relaxed test rewrite + 2 new tests)
- FOUND: commit `769bb36` (Task 1 — feat(02-04): wire cross_chat_quote.record_bodies into 4 body-surfacing read tools)
- FOUND: commit `11c486d` (Task 2 — test(02-04): tighten REL-05 D-24 evolution — sender→reader edge surgical + tools-may-import-both whitelist)

Final test + lint + type gates:

- `uv run pytest -m "not live"` — 150 passed, 9 deselected (148 baseline + 2 new isolation tests)
- `uv run pytest tests/unit/test_isolation.py -v` — 7 passed in 0.18s
- `uv run ruff check src/ tests/` — all checks passed
- `uv run ruff format --check src/ tests/` — 85 files already formatted
- `uv run mypy` (whole-tree) — 1 pre-existing error in `tests/unit/test_permissions/test_fda.py:25` (documented in deferred-items.md from Plan 02-01); 0 new errors introduced by this plan

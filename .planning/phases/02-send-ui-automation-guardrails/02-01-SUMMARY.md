---
phase: 02-send-ui-automation-guardrails
plan: 01
subsystem: sender
tags: [sender, pyobjc, ax-api, deep-link, osascript, exceptions, wave-0-spikes]
dependency_graph:
  requires: [phase-01-complete]
  provides: [sender-deeplink, sender-osascript-send, sender-ax-assert, sender-exceptions, pyobjc-runtime]
  affects: [pyproject.toml, uv.lock, exceptions.py]
tech_stack:
  added: [pyobjc-core>=12.1, pyobjc-framework-Cocoa>=12.1, pyobjc-framework-ApplicationServices>=12.1]
  patterns: [bidi-strip-bounded-DFS, sync-AX-walk, async-osascript-wrapper, RFC-3986-quote-not-quote_plus]
key_files:
  created:
    - .planning/phases/02-send-ui-automation-guardrails/02-01-SPIKES.md
    - .planning/phases/02-send-ui-automation-guardrails/deferred-items.md
    - src/whatsapp_desktop_mcp/sender/deeplink.py
    - src/whatsapp_desktop_mcp/sender/osascript_send.py
    - src/whatsapp_desktop_mcp/sender/ax_assert.py
  modified:
    - pyproject.toml
    - uv.lock
    - src/whatsapp_desktop_mcp/exceptions.py
decisions:
  - "pyobjc-core / pyobjc-framework-Cocoa / pyobjc-framework-ApplicationServices added to [project] dependencies (runtime, NOT dev-extra) per D-05"
  - "SP-1 LOCKED: Cmd-F reliably focuses the sidebar 'Rechercher' / 'Search' field on WhatsApp Catalyst 26.16.74 — D-02 group fallback uses Cmd-F directly; no AX-click fallback in v0.1"
  - "SP-2 LOCKED: keep `-g` in /usr/bin/open for send_deeplink — WhatsApp surfaces into the AX tree on the first 50ms poll WITHOUT stealing frontmost; substring match `'WhatsApp' in stdout` is mandatory (NOT equality — U+200E LRM trap)"
  - "SP-3 LOCKED: _walk_for_heading default role filter is the narrow {'AXHeading'} — widening to AXStaticText would catastrophically false-positive on message body content"
  - "SP-4 LOCKED: pyobjc 12.1 AXUIElementCopyAttributeValue returns canonical 2-tuple (err: int, value)"
  - "SP-5 LOCKED: sidebar-search first result is an AXButton with chat name in AXDescription; single parameterised _walk_for_heading(roles=frozenset({'AXHeading','AXButton'})) reuses the DFS"
metrics:
  duration_seconds: 664
  completed_date: 2026-05-13
  commits: 3
  files_created: 5
  files_modified: 3
  tests_added: 0
  tests_still_green: 148
---

# Phase 2 Plan 02-01: Sender primitives — pyobjc deps, deeplink builder, osascript_send wrapper, AX preflight (Wave-0 spikes first) Summary

Empirically resolved the four Wave-0 open questions A1..A6 via five live spikes against the maintainer's WhatsApp Desktop 26.16.74 / macOS 26.4, then landed the three MCP-decoupled sender primitive modules (deeplink + osascript_send + ax_assert) plus the five new exception classes the Phase 2 sender surface needs, plus the three pyobjc 12.1 runtime dependencies. Zero tool registrations, zero reader imports, zero MCP coupling — Plans 02-02 (guardrails) and 02-03 (orchestration + send_message tool) now have a stable, RO-tier-coupling-free set of primitives to compose into the unified send path.

## What landed

| File | Lines | Purpose |
|------|-------|---------|
| `02-01-SPIKES.md` | 165 | Empirical findings of SP-1..SP-5 with locked tactical decisions for Tasks 2/3 + Plan 02-03 |
| `pyproject.toml` | +13 (diff) | Three pyobjc deps appended to `[project] dependencies` (D-05) |
| `uv.lock` | (regenerated) | 5 packages added at 12.1: pyobjc-core, Cocoa, ApplicationServices, coretext, quartz |
| `src/whatsapp_desktop_mcp/exceptions.py` | +120 | 5 new exception classes appended below `ReadOnlyMode` (all inherit `WhatsAppMCPError`) |
| `src/whatsapp_desktop_mcp/sender/deeplink.py` | 174 | `build_send_url` + `send_deeplink`; SP-2 locks `-g` flag |
| `src/whatsapp_desktop_mcp/sender/osascript_send.py` | 122 | `press_return` + `type_string` with -1743→AutomationRevoked mapping |
| `src/whatsapp_desktop_mcp/sender/ax_assert.py` | 361 | D-03 load-bearing P5 mitigation; D-06 try/except ImportError; both public callables |
| `deferred-items.md` | 31 | Pre-existing mypy error in `tests/unit/test_permissions/test_fda.py:25` (NOT caused by this plan) |

## Wave-0 spike outcomes (paragraph-each summary)

**SP-1 — Cmd-F focuses sidebar-search (locked):** Live probe on WhatsApp Catalyst 26.16.74: `osascript -e 'tell application "System Events" to keystroke "f" using {command down}'` focuses the sidebar "Rechercher" (FR locale) field with role `AXGenericElement`. The CONTEXT.md D-02 group-fallback orchestrator (Plan 02-03) uses `Cmd-F` directly; no AX-click fallback is needed for v0.1. Belt-and-braces detection (verify `AXFocusedUIElement.description == "Rechercher"` after Cmd-F) belongs in Plan 02-03's orchestrator.

**SP-2 — `open -g` keeps focus, surfaces into AX (locked):** `/usr/bin/open -g whatsapp://send?phone=...` with a backgrounded WhatsApp and a non-routable phone shows: front-window name `‎WhatsApp` (leading U+200E LRM, verified — substring match mandatory) is reachable on the very first 50ms poll (~0.6 s wall, dominated by osascript spawn cost); `Terminal` stays frontmost — `-g` did NOT steal focus. Locked: keep `-g`; settle-poll uses substring `"WhatsApp" in result.stdout`.

**SP-3 — AXHeading carries the chat header (locked narrow filter):** Live `entire contents of front window` on an open chat shows the focused chat's name appears as `AXHeading desc='+33 6 33 63 13 83'`. Hundreds of `AXStaticText` entries also exist for message bodies — widening the walk to AXStaticText would catastrophically false-positive (any message body containing the expected chat name as a substring would falsely "match" the header). Locked: `_walk_for_heading` default role filter stays `frozenset({"AXHeading"})`.

**SP-4 — pyobjc 12.1 return shape is 2-tuple (locked):** Throwaway-venv probe with `pyobjc-core==12.1 + pyobjc-framework-Cocoa==12.1 + pyobjc-framework-ApplicationServices==12.1` confirms `AXUIElementCopyAttributeValue(elem, attr, None)` returns `tuple[int, Any]` where `[0]` is the AX error code (0 on success) and `[1]` is the attribute value (an `AXUIElementRef`, a Python `str`, an `__NSArrayM` of children, or `None`). Locked: every call site uses `err, val = AXUIElementCopyAttributeValue(node, attr, None)` and checks `err == 0` before consuming `val`. Throwaway venv removed after recording.

**SP-5 — sidebar-search first result is an AXButton in AXDescription (locked widening):** After `Cmd-F + keystroke "Discussions"`, the pyobjc walk shows three nodes matching `"Discussion"`: the sidebar-section `AXHeading desc='‎Discussions'`, the search field `AXStaticText value='Discussions'`, and the first **clickable** result `AXButton desc='‎Discussions'` at depth 6. The first-result preflight reuses `_walk_for_heading` with the widened role set `frozenset({"AXHeading", "AXButton"})`; the AXHeading siblings are benign because the substring-after-bidi-strip + casefold algorithm requires the **expected** chat name as a substring of the **observed** label — different names won't match.

## Exact pyobjc versions resolved in uv.lock

```
pyobjc-core == 12.1
pyobjc-framework-applicationservices == 12.1
pyobjc-framework-cocoa == 12.1
pyobjc-framework-coretext == 12.1     # transitive of pyobjc-framework-applicationservices
pyobjc-framework-quartz == 12.1        # transitive of pyobjc-framework-applicationservices
```

Wheel METADATA verification: `Requires-Dist: pyobjc-core>=12.1`, `Requires-Dist: pyobjc-framework-applicationservices>=12.1`, `Requires-Dist: pyobjc-framework-cocoa>=12.1` all appear without an `; extra == 'dev'` marker — i.e. listed as **runtime** deps per D-05, not as extras.

## Deviations from Plan

### Rule-1 auto-fixed near-misses (same class as Phase 0/1 literal-token rewordings)

**1. [Rule 1 - Auto-fix] CLAUDE.md hard rule #5 grep gate near-miss in `deeplink.py` docstring**
- **Found during:** Task 2 acceptance criteria check `grep -rE '(socket|http\.client|httpx|urllib\.request|aiohttp|requests)' src/whatsapp_desktop_mcp/sender/deeplink.py src/whatsapp_desktop_mcp/sender/osascript_send.py | grep -v '^#'`.
- **Issue:** The original deeplink.py docstring said "this module opens NO network sockets" — the literal word `sockets` matched the `socket` regex. `grep -v '^#'` does NOT filter docstring lines (only comment lines starting with `#`), so the AC gate tripped on prose-only text.
- **Fix:** Reworded the docstring to refer to "network endpoints / TCP / UDP / HTTP" without spelling the literal `socket` token. Zero behavioral impact (docstring-only).
- **Files modified:** `src/whatsapp_desktop_mcp/sender/deeplink.py`
- **Commit:** `612bf1f` (Task 2)

**2. [Rule 1 - Auto-fix] mypy strict needs `import-untyped` not `import-not-found` for pyobjc imports**
- **Found during:** Task 3 `uv run mypy src/whatsapp_desktop_mcp/sender/ax_assert.py` pre-commit gate.
- **Issue:** The plan's `<action>` block said to add `# type: ignore[import-not-found]` on each pyobjc import. But pyobjc 12.1 IS installed at the module path — it just lacks a `py.typed` marker / inline stubs. mypy strict raises `[import-untyped]` (skipping analysis, missing stubs) NOT `[import-not-found]`. The `[import-not-found]` ignore was flagged as `[unused-ignore]` AND the actual `[import-untyped]` error stayed.
- **Fix:** Changed both `# type: ignore[import-not-found]` lines to `# type: ignore[import-untyped]`.
- **Files modified:** `src/whatsapp_desktop_mcp/sender/ax_assert.py`
- **Commit:** `b4114aa` (Task 3)

**3. [Rule 1 - Auto-fix] Bidi codepoint grep gate requires escape-literal source form**
- **Found during:** Task 3 acceptance criteria check `grep -cE '\\u200E|\\u2068|\\u2069' src/whatsapp_desktop_mcp/sender/ax_assert.py` returning 0.
- **Issue:** The plan's AC6 requires the three bidi codepoints to appear in source as Python escape-literal sequences (the ASCII byte sequence `\` + `u` + 4 hex digits) so the source file is grep-stable — raw codepoints render as zero-width invisibles in source viewers and would make literal-token greps return 0 lines despite the codepoints being present. My initial implementation used raw codepoints (which Python ALSO accepts in string literals, but defeats the grep stability goal).
- **Fix:** Replaced the raw chars `‎` / `⁨` / `⁩` in the `_INVISIBLE_BIDI` frozenset declaration and surrounding docstring with Python escape-literal form `"‎" / "⁨" / "⁩"`. Python parses both forms to the same three codepoints at module-load time, so the runtime `_strip_bidi("‎⁨Olivier Giffard⁩") == "Olivier Giffard"` smoke check still passes byte-for-byte. AC6 grep now returns 6 (well above the ≥3 threshold).
- **Files modified:** `src/whatsapp_desktop_mcp/sender/ax_assert.py`
- **Commit:** `b4114aa` (Task 3)

**4. [Rule 1 - Auto-fix] REL-05 D-24 grep gate near-miss on docstring prose**
- **Found during:** Task 3 acceptance criteria check `grep -E 'whatsapp_desktop_mcp\.reader' src/whatsapp_desktop_mcp/sender/ax_assert.py`.
- **Issue:** The ax_assert.py docstring originally said "this module imports nothing from `whatsapp_desktop_mcp.reader.*`. Allowed `whatsapp_desktop_mcp.*` imports: `whatsapp_desktop_mcp.exceptions` only." — the prose was *describing* the isolation rule rather than violating it, but the file-wide grep gate doesn't distinguish docstring text from actual import statements.
- **Fix:** Reworded the docstring to refer to "the project's read-side data tier" / "DB connection helpers" / "message accessors" without spelling the literal `whatsapp_desktop_mcp.reader` substring. Same near-miss class as Plan 01-02 `immutable=1` reword, Plan 01-04 `readOnlyHint=True` / `anthropic/maxResultSizeChars` rewords, Plan 02 `transport=` reword, etc. Zero behavioral impact (docstring-only).
- **Files modified:** `src/whatsapp_desktop_mcp/sender/ax_assert.py`
- **Commit:** `b4114aa` (Task 3)

### Plan-prompt vs PLAN.md naming discrepancy (NOT a deviation — PLAN.md is canonical)

The executor's `<deliverables>` block in the spawning prompt mentioned `open_whatsapp_url` and `wait_for_whatsapp_front` as separate deeplink primitives, but the canonical `02-01-PLAN.md` `must_haves.artifacts` block and `<action>` block of Task 2 specify a single unified `send_deeplink` async coroutine that builds the URL + spawns `/usr/bin/open -g` + runs the settle-poll inline. I honored PLAN.md (the per-plan acceptance criteria explicitly assert `grep -cE '^async def send_deeplink'` returning 1). The unified coroutine is the better shape for Plan 02-03's orchestrator because the settle-poll is a closed concern of "open the chat" — splitting it across two callables would let a caller skip the settle and race the keystroke.

The orchestrator in Plan 02-03 will insert the D-03 AX preflight BETWEEN the settle and the keystroke, but the `send_deeplink` shape supports this naturally: `await send_deeplink(...)` returns when the front window is reachable, the caller then runs `assert_focused_chat_matches(...)` (sync), then `await press_return(...)`.

### Pre-existing issue noted but NOT fixed (scope-boundary REL-04)

**`tests/unit/test_permissions/test_fda.py:25` mypy `[attr-defined]` error.** Reproduces on commit `2175e59` (the parent of this plan's work), i.e. unrelated to Plan 02-01. Logged to `.planning/phases/02-send-ui-automation-guardrails/deferred-items.md` with the suggested fix (either add `from . import fda, accessibility, automation` to `permissions/__init__.py`, or replace the test's string-path `monkeypatch.setattr` form with attribute-access form). Plan 02-01's local gate `uv run mypy src/whatsapp_desktop_mcp/exceptions.py src/whatsapp_desktop_mcp/sender/` passes clean; full-tree `uv run mypy` baseline error count held at 1 (pre-existing), not increased.

## Authentication gates

None. All five spikes ran against the maintainer's live WhatsApp Desktop with already-granted Automation + Accessibility TCC; the doctor probe confirmed all-granted as of Phase 1 verification. No new TCC grants were requested by this plan.

## Confirmation that `sender/__init__.py` is STILL empty

```
$ wc -c src/whatsapp_desktop_mcp/sender/__init__.py
       0 src/whatsapp_desktop_mcp/sender/__init__.py
```

Per CONTEXT.md D-23 the `__init__.py` will gain re-exports of `send_text(chat_id, body) -> SendResult` in Plan 02-03 when the unified `ui_send.py` lands. Plan 02-01 deliberately leaves it empty so the public surface gets minted exactly once, by the orchestrator plan.

## File-by-file diff summary

| File | Status | Lines | Notes |
|------|--------|-------|-------|
| `pyproject.toml` | modified | +9 (3 deps + 6 comment lines) | pyobjc deps in `[project] dependencies` per D-05 |
| `uv.lock` | regenerated | (lockfile) | 5 packages added at 12.1 |
| `src/whatsapp_desktop_mcp/exceptions.py` | modified | +120 (append-only) | 5 new exception classes below `ReadOnlyMode` |
| `src/whatsapp_desktop_mcp/sender/deeplink.py` | created | 174 | `build_send_url` (sync) + `send_deeplink` (async); SP-2 `-g` flag |
| `src/whatsapp_desktop_mcp/sender/osascript_send.py` | created | 122 | `press_return` + `type_string`; -1743 → AutomationRevoked |
| `src/whatsapp_desktop_mcp/sender/ax_assert.py` | created | 361 | D-03 load-bearing P5; D-06 try/except; both public callables |
| `.planning/phases/.../02-01-SPIKES.md` | created | 165 | 5 SP sections with locked decisions |
| `.planning/phases/.../deferred-items.md` | created | 31 | Pre-existing mypy error noted (NOT this plan's responsibility) |

Total: 5 files created, 3 files modified.

## Threat Flags

None. The threat surfaces introduced by this plan (deep-link URL builder, osascript keystroke wrappers, AX-API state assertion) are all enumerated in the plan's `<threat_model>` T-02-01-01 through T-02-01-08 register. No surface NOT in the threat model was created.

## TDD Gate Compliance

This plan has `type: execute` (not `type: tdd`); no plan-level TDD gate applies. Per the plan output spec, "no new tests added in this plan — Plan 02-05 owns tests"; the 148-test baseline still passes after all three commits.

## Self-Check: PASSED

All key files exist and all 3 task commits are present:

- FOUND: `src/whatsapp_desktop_mcp/sender/deeplink.py`
- FOUND: `src/whatsapp_desktop_mcp/sender/osascript_send.py`
- FOUND: `src/whatsapp_desktop_mcp/sender/ax_assert.py`
- FOUND: `.planning/phases/02-send-ui-automation-guardrails/02-01-SPIKES.md`
- FOUND: `.planning/phases/02-send-ui-automation-guardrails/deferred-items.md`
- FOUND: commit `d1b6d9e` (Task 1 — chore(02-01): Wave-0 spikes + pyobjc 12.1 runtime deps)
- FOUND: commit `612bf1f` (Task 2 — feat(02-01): sender primitives — deeplink + osascript wrappers + 5 exceptions)
- FOUND: commit `b4114aa` (Task 3 — feat(02-01): AX preflight (D-03 load-bearing P5 mitigation))

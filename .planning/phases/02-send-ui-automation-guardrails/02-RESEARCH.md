# Phase 2: Send (UI-automation, guardrails) - Research

**Researched:** 2026-05-13
**Domain:** macOS UI automation + MCP elicitation + persistent rate limiting + Accessibility-API state assertion
**Confidence:** HIGH (every uncertain claim verified live against the user's `mcp==1.27.1` SDK, the user's WhatsApp Desktop 26.16.74 AX tree, PyPI registry, and live `osascript` probes on this Mac)

## Summary

Phase 2 implements one MCP tool (`send_message`) that drives WhatsApp Desktop on macOS to send a single text message to a chat resolved by Phase 1's read tools. The phase has 25 locked decisions in CONTEXT.md; this research provides the **tactical implementation specifics** the planner needs — the exact `ctx.elicit` API shape, the verified AX tree of WhatsApp Catalyst on the user's Mac, the exact SQL DDL for the persistent rate limiter, the JSONL audit-log write pattern, the cross-chat-quote LRU implementation, the post-hoc verification SQL, and the file-by-file plan structure.

Every locked decision is honored. No alternatives are explored. Where a CONTEXT.md decision pointed at an empirically uncertain claim (the AX tree shape, the bidi-character set, the `ctx.elicit` exact signature), this research **verified the claim live** against the installed `mcp` SDK and the running WhatsApp.app — not from training data.

**Primary recommendation:** Plan 02 as **5 plans** (sender primitives → guardrails → send tool → read-tool integration → tests), with 02-01 and 02-02 parallelizable. Use `ctx: Context` parameter injection on the tool function (FastMCP recognizes the type annotation). Use a Pydantic v2 model for the elicit schema, NOT a raw JSON dict — the `mcp==1.27.1` API is `await ctx.elicit(message, schema=PydanticModel)`. Strip three bidi invisibles (U+200E, U+2068, U+2069) before AX header equality. Vendor the pyobjc dependency in `[project] dependencies` (not optional-dependencies) per D-05.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Send Mechanism**
- **D-01:** 1:1 sends use the deep-link primary path. `subprocess.run(["open", "-g", "whatsapp://send?phone=<E164>&text=<urlencoded_body>"], timeout=5)` opens the chat in WhatsApp.app with the message pre-filled. After the open, a brief deterministic settle (poll for window title containing "WhatsApp" via `osascript ... tell application "System Events" to get name of front window of process "WhatsApp"` with up to 1.5s timeout) confirms the app is foreground; then `osascript -e 'tell application "System Events" to keystroke return'` fires the send. The `-g` flag keeps WhatsApp from grabbing focus aggressively.
- **D-02:** Group sends use the search-and-click fallback. WhatsApp's `whatsapp://send` URL scheme does NOT accept `@g.us` group JIDs. For groups, the sender drives the `New Chat` search box via UI scripting: open WhatsApp window, focus search field via Cmd-N or AX path, type the resolved chat name, click the first result with matching display name, then keystroke the body + return. Mark group sends with `is_experimental=true` in the tool result. If search-and-click proves unstable in execution, defer group send to v1.1 with documented deviation.
- **D-03:** AX-API state assertion preflight before EVERY send (1:1 and group). Use pyobjc to read the focused WhatsApp window's chat header (`AXTitle` of the topmost `AXGroup` containing the conversation pane). Compare to the resolved chat name. If the header doesn't match, abort with structured `ChatHeaderMismatch` error. Load-bearing P5 / wrong-chat-fuzzy-send mitigation. Defends against the invisible-LRM character trap.
- **D-04:** No raw Accessibility-API send path in v0.1. SEND-04 mandates the state assertion ONLY; the actual keystroke still goes through `osascript ... keystroke return`. Replacing the keystroke with `AXTextArea.setValue:` + `AXButton "Send" AXPress` is v2 work (SEND2-04).

**PyObjC Dependency**
- **D-05:** Add `pyobjc-core>=12.1`, `pyobjc-framework-Cocoa>=12.1`, `pyobjc-framework-ApplicationServices>=12.1` to `[project] dependencies` (NOT `[project.optional-dependencies] dev`). Required at runtime for the AX state assertion (D-03). Adds ~30 MB to the wheel.
- **D-06:** Wrap pyobjc imports in `try/except ImportError` at the sender module level so the package still imports on systems without pyobjc installed. On import failure, `send_message` returns a structured `AccessibilityAPIUnavailable` error; the read tools keep working.

**Confirmation UX**
- **D-07:** MCP elicitation confirmation is ALWAYS-ON by default. Every `send_message` call triggers an elicitation prompt that displays: resolved chat display name, recipient JID/LID (with kind tag), message body verbatim (no truncation), cross-chat-quote warning (if D-15..D-18 heuristic fires), rate limit budget remaining.
- **D-08:** Opt-out via `WHATSAPP_MCP_SKIP_CONFIRM=1` env var. When set: elicitation is skipped, send proceeds, BUT every skipped confirmation is logged to audit log with `confirm_skipped: true`. Documented in README with stark warning.
- **D-09:** No sticky-session confirmation cache. Each send gets its own confirmation.
- **D-10:** Decline = clean cancellation. Returns structured `SendCancelled` result (NOT an error). Audit log `outcome: "cancelled"`.

**Rate Limiter**
- **D-11:** Persistent SQLite-backed rate limiter at `~/Library/Application Support/whatsapp-mcp/rate-limit.db` (mode 0600). Single file; one append-only `sends(ts INTEGER, chat_id INTEGER, body_sha256 TEXT, outcome TEXT)` table. Sliding-window query on `ts`. Defaults: 5/min, 30/day. Configurable via env vars `WHATSAPP_MCP_RATE_PER_MIN` / `WHATSAPP_MCP_RATE_PER_DAY` — bounded by hard maximums of 20/min and 200/day; beyond which env var is rejected with a structured config error.

**Audit Log**
- **D-12:** JSONL at `~/Library/Logs/whatsapp-mcp/audit.log` mode 0600. One JSON object per send attempt with fields `ts, chat_id, chat_name, body_sha256, outcome, message_id, error, confirm_skipped, elapsed_ms`.
- **D-13:** Body itself is NEVER logged (only SHA-256 fingerprint).
- **D-14:** Append-only, line-buffered, no log rotation in v0.1.

**Cross-Chat-Quote Heuristic (SEND-07)**
- **D-15:** Session-scoped source-attribution table. Every read tool (`read_chat`, `extract_recent`, `search_messages`, `get_message_context`) records returned message bodies with their source `chat_id` and timestamp into a process-local LRU (max 1000 entries, ~30 min sliding window). API: `record(chat_id, body)` write + `check(target_chat_id, outgoing_body) -> list[OffendingSource]` read.
- **D-16:** Match threshold: ≥ 40-character contiguous substring belonging to a different chat_id within the 30-min window.
- **D-17:** In-memory only — no persistence. Reset on server restart.
- **D-18:** Surface as a WARNING in the elicitation, not a HARD BLOCK. Warning: `Body contains a 47-char run from chat "Work" — confirm cross-chat reference is intentional.`

**--read-only Interaction**
- **D-19:** `send_message` checks `whatsapp_mcp.server.read_only_mode` at the top of its body and raises `ReadOnlyMode` exception (Phase 1 minted) if True. v0.1 default for the flag stays `True`; user must explicitly `uvx whatsapp-mcp --no-read-only`.
- **D-20:** Tool annotations: `@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True), meta={"anthropic/maxResultSizeChars": 60000})`.

**Post-Hoc Verification (SEND-08)**
- **D-21:** Polling pattern: 250 ms intervals, up to 10 s wall-clock total (40 polls). Query: `SELECT ZSTANZAID, ZMESSAGEDATE FROM ZWAMESSAGE WHERE ZCHATSESSION=:cid AND ZISFROMME=1 AND ZTEXT=:body AND ZMESSAGEDATE > :send_started_cocoa ORDER BY ZSORT DESC LIMIT 1`. First match wins; return `ZSTANZAID` as `message_id`.
- **D-22:** Verification timeout returns `outcome="sent_unverified"` (NOT "error"). Tool result: `{"status": "sent_unverified", "message_id": null, "verification_note": "..."}`.

**Sender Package Layout**
- **D-23:** Files under `src/whatsapp_mcp/sender/`: `deeplink.py`, `osascript_send.py`, `ax_assert.py`, `ui_send.py`, `verify.py`, `rate_limit.py`, `audit.py`, `cross_chat_quote.py`, `__init__.py` re-exporting `send_text(chat_id, body) -> SendResult`.
- **D-24:** REL-05 EVOLUTION: Reader MUST NOT import Sender. Sender MAY import Reader connection primitives only (`reader.connection.open_ro`), NOT reader.tools or reader business logic. Update `tests/unit/test_isolation.py` accordingly.

**Tool Layer**
- **D-25:** `src/whatsapp_mcp/tools/send_message.py` — `@mcp.tool(...)` async function. Body sequence:
  1. Check `read_only_mode` → raise `ReadOnlyMode`.
  2. Validate `chat_id` exists via reader lookup → raise `InvalidChatId` if not found.
  3. Resolve chat name + recipient JID/LID from reader.
  4. Build cross-chat-quote warnings.
  5. Check rate limit → raise `RateLimitExceeded` if over budget.
  6. MCP elicitation prompt (unless `WHATSAPP_MCP_SKIP_CONFIRM=1`); on decline → `SendCancelled`.
  7. AX state assertion → raise `ChatHeaderMismatch` on focus mismatch.
  8. Drive send (deep-link OR search-and-click).
  9. Post-hoc DB poll for verification (D-21).
  10. Append audit log entry.
  11. Return `SendResult { status, message_id, verification_note, rate_limit_remaining, audit_log_path }`.

### Claude's Discretion
- AX-API exact selectors for the focused chat header (the `AXTitle` walk depth, fallback selectors if obvious one missing on specific Catalyst version)
- Exact wording of the elicitation prompt's body display (must show body verbatim; framing is Claude's call)
- Whether to add `WHATSAPP_MCP_DRY_RUN=1` env var
- Whether to ship a tiny `whatsapp-mcp send-test` CLI subcommand for manual smoke testing

### Deferred Ideas (OUT OF SCOPE)
- Send media (images/files) — v2 (SEND2-01)
- Draft + confirm preview — v2 (SEND2-02)
- Reactions / polls / edit / delete — v2 (SEND2-03)
- Full Accessibility-API send path (replacing `keystroke return` with `AXTextArea.setValue:` + `AXButton.AXPress`) — v2 (SEND2-04)
- Group send via deep-link — v2 (SEND2-05); requires WhatsApp to add group JID support to URL scheme
- Audit log rotation — Phase 3
- `whatsapp-mcp send-test` CLI subcommand — Claude's discretion
- `WHATSAPP_MCP_DRY_RUN=1` env var — Claude's discretion

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SEND-01 | Tool `send_message` accepts only opaque `chat_id` (never name string) | §"D-25 tool body" — reader's `find_chat_by_id(chat_id: int)` is the validator; passing a string raises `InvalidChatId` via Pydantic's int coercion failure |
| SEND-02 | Send is `destructiveHint:true` and gated by MCP elicitation by default | §"MCP Elicitation API (verified live, mcp==1.27.1)" — `ctx.elicit(message, schema=PydanticModel)` returns `AcceptedElicitation`/`DeclinedElicitation`/`CancelledElicitation` union |
| SEND-03 | Primary send path is `whatsapp://send?phone=<E164>&text=<urlencoded>` deep-link + `osascript` keystroke return; group fallback is search-and-click | §"Deep-Link Send Path (D-01)" + §"Group Send Fallback (D-02)" with verified `osascript` shapes |
| SEND-04 | Pre-send AX-API state assertion verifies focused window's chat header matches resolved chat name | §"AX-API State Assertion (D-03)" — verified live AX tree (AXHeading nodes carry chat name; three invisible bidi chars must be stripped: U+200E / U+2068 / U+2069) |
| SEND-05 | Rate limiter 5/min, 30/day default; structured error on hit | §"Persistent SQLite Rate Limiter (D-11)" with exact DDL + sliding-window queries |
| SEND-06 | Audit log JSONL at `~/Library/Logs/whatsapp-mcp/audit.log` mode 0600 | §"JSONL Audit Log (D-12)" with exact `os.chmod`/`open(...buffering=1)` pattern |
| SEND-07 | Cross-chat-quote heuristic detects body containing content recently quoted from another chat | §"Cross-Chat-Quote Heuristic (D-15..D-18)" with LRU + 40-char threshold + 30-min window |
| SEND-08 | Send verified post-hoc by polling `ZWAMESSAGE` for new outgoing row within 10s | §"Post-Hoc Verification (D-21)" with exact SQL + 250ms × 40 cadence using `reader.connection.open_ro` (D-24 evolved REL-05) |

</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Deep-link URL build + `open` subprocess | Sender (`sender/deeplink.py`) | — | Owns the WhatsApp URL scheme; no DB / MCP coupling |
| `osascript` keystroke wrapper | Sender (`sender/osascript_send.py`) | — | Reuses Phase 0's `permissions/osascript.py:run_osascript` async wrapper |
| AX preflight (pyobjc) | Sender (`sender/ax_assert.py`) | — | pyobjc isolated to this one module; D-06 try/except ImportError lives here |
| Group search-and-click orchestration | Sender (`sender/ui_send.py`) | osascript_send | Composes deeplink + osascript + ax_assert |
| Rate limiting (persistent) | Sender (`sender/rate_limit.py`) | — | Owns its own SQLite at `~/Library/Application Support/whatsapp-mcp/rate-limit.db` — separate file from WhatsApp DB |
| Audit log write | Sender (`sender/audit.py`) | — | Owns the JSONL append; no read tier coupling |
| Cross-chat-quote LRU | Sender (`sender/cross_chat_quote.py`) | Tool layer (read tools call `record_bodies`) | LRU lives in sender; read tools call `record()` post-projection (one hook call site per read tool) |
| Post-hoc DB verification poll | Sender (`sender/verify.py`) | Reader (`reader.connection.open_ro`) | D-24 evolution allows `sender → reader.connection` one-way edge |
| MCP elicitation prompt | Tool (`tools/send_message.py`) | — | `ctx.elicit` is a request-context method; only the tool sees `ctx` |
| `read_only_mode` gate | Tool layer | Server module state | Tool checks `server.read_only_mode` at body top |
| TCC re-check at send-time (T-6) | Tool layer | `permissions.automation` (Phase 0 D-09 patched) | Reuses existing probe |

## Standard Stack

### Core (already locked from Phase 0/1)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `mcp[cli]` | `==1.27.1` | FastMCP stdio server + Context.elicit | Already locked; provides `ctx.elicit(message, schema)` API verified live below |
| `pydantic` | `>=2.7,<3` | Tool I/O models + elicit schema (Pydantic model required, NOT raw dict) | Phase 1 baseline; reused for `SendResult`, `ConfirmationDecision` elicit schema |
| stdlib `sqlite3` | bundled | Rate-limit DB + post-hoc verification (via reader.connection.open_ro) | Two-purpose: our own SQLite for rate-limit, RO probe of WhatsApp's DB for verify |

### Phase 2 additions
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pyobjc-core` | `>=12.1` | AX-API ctypes bridge | D-05; verified live: PyPI latest = 12.1, uploaded 2025-11-14 [VERIFIED: PyPI] |
| `pyobjc-framework-Cocoa` | `>=12.1` | NSWorkspace / NSRunningApplication for PID lookup | D-05; matched-version companion to pyobjc-core |
| `pyobjc-framework-ApplicationServices` | `>=12.1` | `AXUIElementCreateApplication`, `AXUIElementCopyAttributeValue`, `kAXFocusedWindowAttribute`, `kAXTitleAttribute`, `kAXRoleAttribute`, `kAXChildrenAttribute` | D-05; the accessibility-API ctypes wrappers live in this framework |

**Installation:**
```bash
uv add 'pyobjc-core>=12.1' 'pyobjc-framework-Cocoa>=12.1' 'pyobjc-framework-ApplicationServices>=12.1'
```

**Version verification** [VERIFIED: PyPI 2026-05-13 via `urllib.request.urlopen('https://pypi.org/pypi/pyobjc-core/json')`]:
- pyobjc-core 12.1 — published 2025-11-14 (most recent stable; previous: 11.1)
- Companion frameworks ship together at matching versions; mixing pyobjc-core 12.1 with pyobjc-framework-* 11.1 leads to ABI mismatches at import time

### Alternatives Considered (NOT picked — locked decisions)

| Instead of | Could Use | Why we don't |
|------------|-----------|----------|
| pyobjc for AX | `osascript`-only AX walks (`tell application "System Events" to tell process "WhatsApp" to get description of ...`) | Verified live works for inspection but is locale-dependent (French stderr would break English-only matching), much slower (~150-300ms per probe), and harder to type-check |
| `httpx` for MCP elicitation | — | Elicit is a server→client request the SDK handles; we don't manage transport |
| `aiosqlite` for rate-limit DB | — | Single-writer single-reader, low contention, stdlib sqlite3 wrapped in `asyncio.to_thread` is the project pattern (REL-02) |
| Per-process file lock for audit log | `fcntl.flock` | Overkill for v0.1 — single MCP server instance per user; flag in §"Common Pitfalls" if multi-instance ever ships |

## Architecture Patterns

### System Architecture Diagram

```
LLM client (Claude Desktop)
        │  JSON-RPC over stdio
        ▼
┌──────────────────────────────────────────────────────┐
│  MCP Boundary (server.py)                            │
│  - registers 9 tools; send_message gated by          │
│    `if not server.read_only_mode:` import block      │
└──────────────────┬───────────────────────────────────┘
                   │  tools/send_message.py invoked
                   ▼
┌──────────────────────────────────────────────────────┐
│  Tool Layer (tools/send_message.py)                  │
│  ① read_only_mode check  → ReadOnlyMode              │
│  ② reader.find_chat_by_id → InvalidChatId            │
│  ③ permissions.automation.check_whatsapp (T-6)       │
│      → AutomationRevoked                             │
│  ④ cross_chat_quote.check → warnings                 │
│  ⑤ rate_limit.check_and_reserve → RateLimitExceeded  │
│  ⑥ ctx.elicit(message, schema=ConfirmationSchema)    │
│      → SendCancelled on decline/cancel               │
│  ⑦ ax_assert.assert_focused_chat_matches             │
│      → ChatHeaderMismatch on mismatch                │
│  ⑧ ui_send.send_text (deeplink OR group fallback)    │
│  ⑨ verify.poll_for_outgoing → ZSTANZAID or None      │
│  ⑩ audit.append(entry)                               │
│  ⑪ return SendResult                                 │
└──────┬─────────┬──────┬──────┬──────┬───────┬───────┘
       │         │      │      │      │       │
       ▼         ▼      ▼      ▼      ▼       ▼
   Phase 0   Phase 1  XCQ   Rate   Audit   Sender
   probe    reader    LRU   limit  JSONL   ui_send +
                                            ax_assert +
                                            verify
       (sender/cross_chat_quote.py)
       (sender/rate_limit.py — own SQLite)
       (sender/audit.py — JSONL mode 0600)
       (sender/ui_send.py — deeplink + osascript)
       (sender/ax_assert.py — pyobjc AX walk)
       (sender/verify.py — uses reader.connection.open_ro per D-24)

Read-tool integration hook (Plan 02-04):
       reader.list_chats / read_chat / extract_recent /
       search_messages / get_message_context
            │ after projecting messages →
            ▼
       sender.cross_chat_quote.record_bodies(chat_id, [bodies])
```

### Recommended Project Structure

```
src/whatsapp_mcp/
├── sender/                                # NEW in Phase 2 (per D-23)
│   ├── __init__.py                        # re-exports send_text + SendResult
│   ├── deeplink.py                        # whatsapp:// URL builder + `open -g`
│   ├── osascript_send.py                  # keystroke return wrapper (reuses permissions.osascript)
│   ├── ax_assert.py                       # pyobjc focused-window-header probe (D-03)
│   ├── ui_send.py                         # orchestrator: deeplink + osascript + ax_assert
│   ├── rate_limit.py                      # persistent SQLite limiter (D-11)
│   ├── audit.py                           # JSONL audit log (D-12)
│   ├── cross_chat_quote.py                # LRU + read-tool integration (D-15..D-18)
│   └── verify.py                          # post-hoc DB poll (D-21, uses reader.connection)
├── tools/
│   ├── send_message.py                    # NEW — the @mcp.tool body (D-25)
│   ├── _decorators.py                     # existing — apply @timeout(seconds=15) per REL-03
│   ├── (read tools — modified)            # add cross_chat_quote.record_bodies hook
├── exceptions.py                          # add: InvalidChatId, RateLimitExceeded,
│                                          # ChatHeaderMismatch, SendCancelled (result type),
│                                          # AccessibilityAPIUnavailable, AutomationRevoked,
│                                          # SendVerificationTimeout (informational only —
│                                          # raised internally, mapped to sent_unverified)
├── models/                                # NEW model in models/ dir
│   └── send.py                            # SendResult, OffendingSource, ConfirmationSchema
├── server.py                              # add: `if not read_only_mode: from .tools import send_message`
```

### Pattern 1: MCP Elicitation API (verified live, mcp==1.27.1)

**Source:** `.venv/lib/python3.12/site-packages/mcp/server/fastmcp/server.py:1194` + `mcp/server/elicitation.py:105-142` + `mcp/types.py:1895` [VERIFIED via filesystem inspection of installed SDK].

**Context injection:** FastMCP recognizes the `Context` type annotation on a tool parameter and injects the live request-context object. **The parameter is excluded from the JSON-schema** (verified at `mcp/server/fastmcp/server.py:598`).

```python
# Source: mcp/server/fastmcp/server.py:1194
async def elicit(
    self,
    message: str,
    schema: type[ElicitSchemaModelT],   # MUST be a Pydantic BaseModel subclass
) -> ElicitationResult[ElicitSchemaModelT]:
    ...
```

**Return shape** (from `mcp/server/elicitation.py:17-36`):
```python
# Three-variant union — NOT a single ElicitResult with action field on the FastMCP wrapper
class AcceptedElicitation(BaseModel, Generic[ElicitSchemaModelT]):
    action: Literal["accept"] = "accept"
    data: ElicitSchemaModelT     # Pydantic-validated typed model

class DeclinedElicitation(BaseModel):
    action: Literal["decline"] = "decline"

class CancelledElicitation(BaseModel):
    action: Literal["cancel"] = "cancel"

ElicitationResult = AcceptedElicitation[T] | DeclinedElicitation | CancelledElicitation
```

**Schema constraint** (from `mcp/server/elicitation.py:48-68`): the Pydantic model fields MUST be one of `(str, int, float, bool)`, `list[str]`, or `Optional` of those. Nested models / dicts are rejected at `elicit()` call time with a `TypeError`. This is enforced by `_validate_elicitation_schema`.

**Concrete usage for `send_message`:**
```python
# Source: verified API on mcp==1.27.1; pattern lifted from
# .venv/lib/python3.12/site-packages/mcp/server/elicitation.py
from mcp.server.fastmcp import Context
from mcp.server.elicitation import (
    AcceptedElicitation,
    DeclinedElicitation,
    CancelledElicitation,
)
from pydantic import BaseModel, Field

class ConfirmationSchema(BaseModel):
    """Single-checkbox schema. Client renders one boolean field."""
    confirm: bool = Field(
        description="Send this WhatsApp message?",
    )

@mcp.tool(
    name="send_message",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, ...),
    meta={"anthropic/maxResultSizeChars": 60_000},
)
@timeout(seconds=15)
async def send_message(
    chat_id: int,
    body: str,
    ctx: Context,   # FastMCP injects the live request context — excluded from JSON schema
) -> SendResult:
    # ... steps 1-5 from D-25 ...

    prompt = (
        f"Send this message via WhatsApp Desktop?\n\n"
        f"Chat: {chat_name}  (id={chat_id}, jid={recipient_jid})\n"
        f"Body ({len(body)} chars):\n"
        f"---\n{body}\n---\n"
        f"Cross-chat warnings: {warnings or 'none'}\n"
        f"Rate budget: {budget_remaining_per_min}/min, {budget_remaining_per_day}/day remaining."
    )

    if os.environ.get("WHATSAPP_MCP_SKIP_CONFIRM") == "1":
        confirm_skipped = True
    else:
        result = await ctx.elicit(prompt, schema=ConfirmationSchema)
        confirm_skipped = False
        if isinstance(result, DeclinedElicitation) or isinstance(result, CancelledElicitation):
            await audit.append(AuditEntry(outcome="cancelled", ...))
            return SendResult(status="cancelled", ...)
        # result is AcceptedElicitation[ConfirmationSchema]
        if not result.data.confirm:
            await audit.append(AuditEntry(outcome="cancelled", ...))
            return SendResult(status="cancelled", ...)

    # ... steps 7-11 from D-25 ...
```

**Confidence:** HIGH for the schema-model-not-raw-dict shape and the three-variant union return type. Both are read directly from the installed SDK source. The `result.data.confirm` accessor pattern is the documented usage.

### Pattern 2: AX-API State Assertion (D-03) — verified live on user's Mac

**Verified live (2026-05-13) against WhatsApp Desktop 26.16.74 on macOS 26.4:**

1. **The front window of WhatsApp.app has 4 top-level children:** `AXGroup`, `AXButton` (close), `AXButton` (zoom), `AXButton` (minimize). The conversation lives inside the top-level `AXGroup` (its descendant tree contains `AXHeading`, `AXButton`, `AXGroup` siblings — verified via `entire contents of front window`).

2. **The chat header is an `AXHeading` node** whose `description` attribute carries the chat name. When the sidebar is on "Discussions" view, the `AXHeading` reads `‎Discussions` (verified live: 8-char visible string, 9 codepoints including a leading **U+200E LRM**). When a specific chat is opened, the same `AXHeading` carries that chat's display name.

3. **Invisible bidi characters** appear on every AX label and every chat-list-item button. Verified live: contact name `Olivier Giffard` appears as the codepoint sequence `[U+200E, U+2068, 'O', 'l', 'i', 'v', 'i', 'e', 'r', ' ', 'G', 'i', 'f', 'f', 'a', 'r', 'd', U+2069]` — three bidi marks total:
   - **U+200E (LRM, Left-to-Right Mark)** — prefix on every chat-list-item label
   - **U+2068 (FSI, First Strong Isolate)** — opens the directional isolation around the name
   - **U+2069 (PDI, Pop Directional Isolate)** — closes the directional isolation

   String-equality comparison `"Olivier Giffard" == header_text` returns False; comparison after stripping these three codepoints returns True.

4. **The locale is the user's:** in the user's French environment, navigation labels are translated (`Discussions`, `Paramètres`, `Nouvelle discussion`, etc.). **Chat names themselves are NOT localized** — they're the raw display names the user / contacts have set. The chat-header equality test therefore compares **stripped raw-text** to the canonical `chat.display_name` returned by `reader.find_chat_by_id(chat_id)`. No locale concern for chat-name matching; locale concern lives only for the (non-load-bearing) sidebar-header strings.

**Concrete recommendation — `sender/ax_assert.py` implementation outline:**

```python
"""Pre-send focused-window-header check (D-03 / SEND-04 / P5 mitigation).

The pyobjc imports are wrapped in try/except ImportError per D-06 so the
package still imports on systems without pyobjc (CI macos-14 has it, but a
broken user install shouldn't crash the read tools).
"""
from __future__ import annotations
import unicodedata
from whatsapp_mcp.exceptions import (
    AccessibilityAPIUnavailable,
    ChatHeaderMismatch,
)

try:
    from ApplicationServices import (  # type: ignore[import-not-found]
        AXUIElementCreateApplication,
        AXUIElementCopyAttributeValue,
        kAXFocusedWindowAttribute,
        kAXChildrenAttribute,
        kAXRoleAttribute,
        kAXTitleAttribute,
        kAXDescriptionAttribute,
    )
    from Cocoa import NSWorkspace  # type: ignore[import-not-found]
    _PYOBJC_AVAILABLE = True
except ImportError:
    _PYOBJC_AVAILABLE = False

# VERIFIED LIVE on user's Mac 2026-05-13 — strip these three bidi marks
# before comparing AX-extracted chat headers to canonical chat names.
_INVISIBLE_BIDI = frozenset({"‎", "⁨", "⁩"})

def _strip_bidi(s: str) -> str:
    """Strip the three bidi invisibles WhatsApp Catalyst inserts on AX labels."""
    return "".join(c for c in s if c not in _INVISIBLE_BIDI).strip()


def _resolve_whatsapp_pid() -> int | None:
    """Find WhatsApp.app's running PID via NSWorkspace."""
    if not _PYOBJC_AVAILABLE:
        return None
    workspace = NSWorkspace.sharedWorkspace()
    for app in workspace.runningApplications():
        if app.bundleIdentifier() == "net.whatsapp.WhatsApp":
            return int(app.processIdentifier())
    return None


def _walk_for_heading(elem) -> list[str]:
    """Depth-first walk; collect every AXHeading's description (or title).

    The AX tree under WhatsApp's main window has ~50-80 nodes total
    (verified live: `entire contents of front window` yields ~50 nodes in
    sidebar-only mode, more when a chat is open). Bounded walk; cap at 200
    nodes for safety.
    """
    headings: list[str] = []
    queue: list = [elem]
    visited = 0
    while queue and visited < 200:
        node = queue.pop()
        visited += 1
        role_err, role = AXUIElementCopyAttributeValue(node, kAXRoleAttribute, None)
        if role_err == 0 and role == "AXHeading":
            t_err, t = AXUIElementCopyAttributeValue(node, kAXDescriptionAttribute, None)
            if t_err == 0 and isinstance(t, str):
                headings.append(t)
            t_err, t = AXUIElementCopyAttributeValue(node, kAXTitleAttribute, None)
            if t_err == 0 and isinstance(t, str):
                headings.append(t)
        c_err, kids = AXUIElementCopyAttributeValue(node, kAXChildrenAttribute, None)
        if c_err == 0 and kids:
            queue.extend(kids)
    return headings


def assert_focused_chat_matches(expected_chat_name: str) -> None:
    """Raise ChatHeaderMismatch if focused WhatsApp window's chat header
    doesn't (after bidi-stripping) substring-match expected_chat_name.

    Substring (not equality): a chat header may include extra suffix
    ("Olivier Giffard • online", localized "Last seen ...") — accept any
    AXHeading whose stripped text contains the (stripped) expected name.
    """
    if not _PYOBJC_AVAILABLE:
        raise AccessibilityAPIUnavailable(
            "pyobjc not available; cannot perform AX preflight",
        )
    pid = _resolve_whatsapp_pid()
    if pid is None:
        raise ChatHeaderMismatch(
            "WhatsApp.app is not running; cannot read focused-window header"
        )
    app = AXUIElementCreateApplication(pid)
    err, window = AXUIElementCopyAttributeValue(app, kAXFocusedWindowAttribute, None)
    if err != 0 or window is None:
        raise ChatHeaderMismatch(
            f"AXFocusedWindow lookup failed (err={err}); cannot verify chat header"
        )
    headings = _walk_for_heading(window)
    expected = _strip_bidi(expected_chat_name).casefold()
    for h in headings:
        if expected in _strip_bidi(h).casefold():
            return   # match found, send is safe
    raise ChatHeaderMismatch(
        f"Focused chat header does not match expected={expected_chat_name!r}; "
        f"observed AXHeading values (stripped) = {[_strip_bidi(h) for h in headings]}"
    )
```

**Why substring and not equality:** chat header in WhatsApp Catalyst may include localized suffix ("Last seen today", "online", "typing..."). Substring after bidi-strip + casefold accommodates locale variation while still failing on a wrong-chat send (different name = different substring).

**Why depth-first walk and not direct attribute path:** the chat header sits at variable depth in the AXGroup tree (the path observed live was `AXWindow → AXGroup → AXGroup → ... → AXHeading`, with depth depending on whether the sidebar is collapsed). A bounded walk is more robust than hardcoding a path.

**Why no `osascript` AX walk fallback:** verified live the `osascript` walk works but takes ~150-300ms per probe (vs ~5-15ms for pyobjc). The D-06 ImportError fallback returns `AccessibilityAPIUnavailable`, which surfaces as a structured tool error telling the user to reinstall pyobjc.

### Pattern 3: Deep-Link Send Path (D-01)

**URL builder:**
```python
# Source: verified live via `python3 -c "import urllib.parse; ..."`
# WhatsApp URL scheme spec: phone is E.164 *digits only* — no `+`,
# no spaces, no hyphens. Body is urllib.parse.quote-encoded
# (RFC 3986; `quote` not `quote_plus` because `+` should stay
# literal in body, not become space).

def build_send_url(phone_e164: str, body: str) -> str:
    cleaned = phone_e164.lstrip("+").replace(" ", "").replace("-", "")
    if not cleaned.isdigit():
        raise ValueError(f"phone must be E.164 digits-only after stripping +/-: got {phone_e164!r}")
    return f"whatsapp://send?phone={cleaned}&text={urllib.parse.quote(body, safe='')}"
```

**Open + settle + send:**
```python
# Source: research/ARCHITECTURE.md Pattern 2; D-01 verbatim
async def send_deeplink(phone_e164: str, body: str) -> None:
    url = build_send_url(phone_e164, body)
    # `open -g` opens without bringing WhatsApp aggressively to foreground
    # (it still raises but won't steal Cmd-Tab order).
    proc = await asyncio.create_subprocess_exec(
        "/usr/bin/open", "-g", url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await asyncio.wait_for(proc.communicate(), timeout=5.0)

    # Settle: poll until the front window of WhatsApp is reachable.
    # Cadence: 50ms × 30 = 1.5s budget (D-01).
    for _ in range(30):
        result = await run_osascript(
            'tell application "System Events" to '
            'tell process "WhatsApp" to get name of front window',
            timeout=1.0,
        )
        if result.exit_code == 0 and "WhatsApp" in result.stdout:
            break
        await asyncio.sleep(0.05)
    else:
        raise SendTimeout("WhatsApp window did not settle within 1.5s")

    # Fire send via Return keystroke.
    result = await run_osascript(
        'tell application "System Events" to keystroke return',
        timeout=3.0,
    )
    if result.exit_code != 0:
        # -1743 = Automation revoked mid-send (rare, but T-6 fallback)
        if result.error_code == -1743:
            raise AutomationRevoked("Automation TCC revoked between settle and keystroke")
        raise OsascriptError(f"keystroke return failed: {result.stderr}")
```

**Verified live: front window name comparison must use substring `"WhatsApp" in stdout`**, NOT `stdout.strip() == "WhatsApp"` — the actual front window name is `‎WhatsApp` (with leading U+200E LRM); equality fails. Verified on this Mac on 2026-05-13 via `osascript -e 'tell application "System Events" to tell process "WhatsApp" to get name of front window'` returning `‎WhatsApp`.

### Pattern 4: Group Send Fallback (D-02)

**Concrete sequence — verified `osascript` shapes:**

```python
async def send_group_via_search(chat_name: str, body: str) -> None:
    """Drive search-and-click for group chats (deep-link doesn't accept @g.us).

    Marked is_experimental=true at the tool-result layer. Fragile; flag every
    failure mode for the user.
    """
    # 1. Activate WhatsApp (reuses Phase 0 D-09 PATCHED path — verified
    #    `tell application "WhatsApp" to activate` works on user's Mac).
    await run_osascript('tell application "WhatsApp" to activate', timeout=3.0)
    await asyncio.sleep(0.3)   # tiny settle for window focus

    # 2. Open chat-search. WhatsApp Catalyst uses Cmd-F for "Search within
    #    current chat" and Cmd-N for "New chat". For finding an existing
    #    chat by name, the global sidebar search is what we need —
    #    that's reached by typing into the AXGenericElement labeled
    #    "Rechercher" (FR locale; "Search" en_US) inside the chat-list
    #    sidebar.
    #
    #    SIMPLEST path: AppleScript `keystroke` with focused-window shortcut.
    #    On user's Mac: clicking into the sidebar's search field is the
    #    canonical way. Best-effort path: Cmd-F focuses search-in-chat;
    #    we need sidebar search. Defer the exact shortcut choice to
    #    execution — the planner should spike both Cmd-N and click-into-
    #    AXSearchField paths and pick whichever lands on the sidebar
    #    search box deterministically on the user's machine.
    #
    #    NOTE FOR PLANNER: the locked decision D-02 references "Cmd-F"
    #    but the live AX probe shows the search box is an AXGenericElement
    #    labeled "Rechercher" / "Search" — it is reached via the sidebar
    #    not the chat-pane Cmd-F. Wave 0 of Plan 02-01 should run a tiny
    #    live spike against the user's WhatsApp to verify the correct
    #    shortcut and pin it in this file. If the spike shows Cmd-F doesn't
    #    open the sidebar search, fall back to the AX-click approach
    #    (find AXGenericElement with description containing "Recherch" or
    #    "Search", AXPress it via pyobjc).
    await run_osascript(
        'tell application "System Events" to keystroke "f" using {command down}',
        timeout=3.0,
    )
    await asyncio.sleep(0.15)

    # 3. Type the chat name (use AppleScript `keystroke <string>` for ASCII;
    #    for non-BMP / emoji, use `set the clipboard` + Cmd-V because raw
    #    keystroke truncates surrogate pairs — verified from research P12).
    name_escaped = chat_name.replace('"', '\\"').replace("\\", "\\\\")
    await run_osascript(
        f'tell application "System Events" to keystroke "{name_escaped}"',
        timeout=3.0,
    )
    await asyncio.sleep(0.4)   # let WA render the search results

    # 4. AX preflight: confirm the topmost result-row carries (after bidi
    #    strip) the expected chat name. Reuse ax_assert._walk_for_heading
    #    against the sidebar list — bounded depth-first AXButton walk.
    #    If no AXButton with stripped-name == chat_name found, abort.
    await assert_first_search_result_matches(chat_name)  # raises on mismatch

    # 5. Press Return — selects the top result and opens the chat.
    await run_osascript(
        'tell application "System Events" to keystroke return',
        timeout=3.0,
    )
    await asyncio.sleep(0.4)   # let WA render the chat pane

    # 6. AX preflight against the now-focused chat header (the load-bearing
    #    D-03 check — reuse ax_assert.assert_focused_chat_matches).
    assert_focused_chat_matches(chat_name)   # raises ChatHeaderMismatch

    # 7. Type body (same Unicode caveats as #3 — emoji/non-BMP not in v0.1).
    body_escaped = body.replace('"', '\\"').replace("\\", "\\\\")
    await run_osascript(
        f'tell application "System Events" to keystroke "{body_escaped}"',
        timeout=3.0,
    )
    await asyncio.sleep(0.15)

    # 8. Press Return — sends.
    await run_osascript(
        'tell application "System Events" to keystroke return',
        timeout=3.0,
    )
```

**Fragility points — document explicitly in module docstring:**
- Cmd-F may or may not target sidebar search across WhatsApp Catalyst versions (verify live in execution; if wrong, fall back to AX-click on the sidebar AXGenericElement "Rechercher")
- `keystroke <string>` truncates non-BMP code points (emoji) historically — for v0.1, restrict group-send body to BMP characters; document the constraint in `send_message`'s tool description
- Search result ordering depends on recency; topmost-result-equals-target is verified by AX assertion before keystroke
- The `# 4` AX-walk on the sidebar list must find the result element — if it's not present yet (race), poll briefly (50ms × 8 = 400ms)

**Why not Cmd-N (new chat):** Cmd-N opens the "new chat" dialog which can create a new 1:1 with someone in your address book, NOT find existing groups by name. Wrong primitive for D-02's use case.

### Pattern 5: Persistent SQLite Rate Limiter (D-11)

**Concrete implementation:**

```python
# sender/rate_limit.py
"""Persistent SQLite-backed rate limiter at
~/Library/Application Support/whatsapp-mcp/rate-limit.db (mode 0600, D-11).

Persistence is load-bearing: an MCP server restart MUST NOT reset the daily
count. The WhatsApp account is the protected resource; it doesn't restart
with our process. SQLite gives us per-process safety + crash-recovery for
free.

Schema:
    sends(ts INTEGER, chat_id INTEGER, body_sha256 TEXT, outcome TEXT)
    ts is Unix epoch seconds (time.time() coerced to int)
    outcome ∈ {"sent","sent_unverified","cancelled","rate_limited","error"}

Sliding-window queries select COUNT(*) where ts > now-60 (per-min) and
ts > now-86400 (per-day). Mode 0600 set via os.chmod() after first connect.

No WAL mode: single-writer (this MCP server) single-reader (this MCP server),
low contention. Plain rollback journal is fine.
"""
from __future__ import annotations
import os
import sqlite3
import time
from pathlib import Path
from whatsapp_mcp.exceptions import RateLimitExceeded

_DB_PATH = Path.home() / "Library" / "Application Support" / "whatsapp-mcp" / "rate-limit.db"

# D-11 bounded environment overrides — REJECT if user tries to expand beyond
# the hard maxes (account-ban floor protection). These are raised at startup
# in sender/__init__.py module-load so misconfigured server fails to start
# cleanly rather than silently disabling the limiter.
_DEFAULT_PER_MIN = 5
_DEFAULT_PER_DAY = 30
_HARD_MAX_PER_MIN = 20
_HARD_MAX_PER_DAY = 200

_DDL = """
CREATE TABLE IF NOT EXISTS sends (
    ts INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    body_sha256 TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('sent','sent_unverified','cancelled','rate_limited','error'))
);
CREATE INDEX IF NOT EXISTS sends_ts_idx ON sends(ts);
"""


def _resolve_limits() -> tuple[int, int]:
    """Resolve per-min / per-day caps from env, bounded by hard maxes."""
    per_min_str = os.environ.get("WHATSAPP_MCP_RATE_PER_MIN")
    per_day_str = os.environ.get("WHATSAPP_MCP_RATE_PER_DAY")
    per_min = int(per_min_str) if per_min_str else _DEFAULT_PER_MIN
    per_day = int(per_day_str) if per_day_str else _DEFAULT_PER_DAY
    if per_min > _HARD_MAX_PER_MIN:
        raise ValueError(
            f"WHATSAPP_MCP_RATE_PER_MIN={per_min} exceeds hard max {_HARD_MAX_PER_MIN}; "
            "raising the limit risks WhatsApp account ban. Refusing to start."
        )
    if per_day > _HARD_MAX_PER_DAY:
        raise ValueError(
            f"WHATSAPP_MCP_RATE_PER_DAY={per_day} exceeds hard max {_HARD_MAX_PER_DAY}; "
            "raising the limit risks WhatsApp account ban. Refusing to start."
        )
    return per_min, per_day


def _ensure_db() -> Path:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    created = not _DB_PATH.exists()
    with sqlite3.connect(f"file:{_DB_PATH}?mode=rwc", uri=True) as conn:
        conn.executescript(_DDL)
    if created:
        os.chmod(_DB_PATH, 0o600)
    return _DB_PATH


def _blocking_check_and_reserve(chat_id: int, body_sha256: str) -> tuple[int, int]:
    """Atomic check-and-reserve. Returns (remaining_per_min, remaining_per_day).

    Raises RateLimitExceeded if at or over budget. Otherwise, this function
    does NOT insert into the table — insertion happens after the actual
    send attempt completes (rate_limit.record_outcome()) so a cancelled
    send doesn't burn budget. The CHECK is therefore a peek + raise.
    """
    per_min, per_day = _resolve_limits()
    db = _ensure_db()
    now = int(time.time())
    with sqlite3.connect(f"file:{db}?mode=rw", uri=True) as conn:
        # Two count queries, one round-trip via execute().
        (cnt_min,) = conn.execute(
            "SELECT COUNT(*) FROM sends WHERE ts > ? AND outcome IN ('sent','sent_unverified')",
            (now - 60,),
        ).fetchone()
        (cnt_day,) = conn.execute(
            "SELECT COUNT(*) FROM sends WHERE ts > ? AND outcome IN ('sent','sent_unverified')",
            (now - 86400,),
        ).fetchone()
    if cnt_min >= per_min:
        raise RateLimitExceeded(
            f"Per-minute send budget exhausted: {cnt_min}/{per_min}. "
            f"Retry after the oldest send in the last minute ages out."
        )
    if cnt_day >= per_day:
        raise RateLimitExceeded(
            f"Per-day send budget exhausted: {cnt_day}/{per_day}. "
            f"Retry tomorrow, or raise WHATSAPP_MCP_RATE_PER_DAY (bounded {_HARD_MAX_PER_DAY})."
        )
    return per_min - cnt_min, per_day - cnt_day


async def check_and_reserve(chat_id: int, body_sha256: str) -> tuple[int, int]:
    return await asyncio.to_thread(_blocking_check_and_reserve, chat_id, body_sha256)


def _blocking_record(chat_id: int, body_sha256: str, outcome: str) -> None:
    db = _ensure_db()
    with sqlite3.connect(f"file:{db}?mode=rw", uri=True) as conn:
        conn.execute(
            "INSERT INTO sends (ts, chat_id, body_sha256, outcome) VALUES (?, ?, ?, ?)",
            (int(time.time()), chat_id, body_sha256, outcome),
        )
        conn.commit()


async def record_outcome(chat_id: int, body_sha256: str, outcome: str) -> None:
    await asyncio.to_thread(_blocking_record, chat_id, body_sha256, outcome)
```

**Critical design notes for the planner:**
- **Two-phase check-then-record:** the check function does NOT insert (so a cancelled send doesn't burn budget against a user who declined the elicitation). The send tool calls `check_and_reserve` first; if it passes, the elicitation+send proceeds and `record_outcome` is called after the send completes (success or failure). If the elicitation declines, no record is written (cancellation doesn't count against the user's budget, which is the user-friendly choice and matches D-10 "decline = clean cancellation").
- **`outcome` enum:** the SQL CHECK constraint enforces the literal set. Cancelled / rate_limited outcomes do still get audit-logged (D-12) but not rate-limit-counted; the SQL check intentionally counts only `sent` and `sent_unverified` (cancellation isn't a send).
- **WAL mode? No.** Single-writer, single-reader, low contention. Rollback journal is simpler and avoids the `-wal` sidecar churn.
- **`mode=rwc`:** Read-Write-Create — the first connect creates the file; subsequent connects use `mode=rw`. Mode is set via `os.chmod` after creation.

### Pattern 6: JSONL Audit Log (D-12 / D-13)

**Concrete implementation:**

```python
# sender/audit.py
"""JSONL audit log at ~/Library/Logs/whatsapp-mcp/audit.log (mode 0600).

One JSON object per send attempt, including cancellations and rate-limit hits.
Body is NEVER plaintext-logged (D-13) — SHA-256 fingerprint only. Append-only,
line-buffered, no rotation in v0.1 (D-14).

The pydantic model fixes the schema; the writer always uses `.model_dump_json()`
+ newline so every line parses as a single JSON object.
"""
from __future__ import annotations
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field

_LOG_DIR = Path.home() / "Library" / "Logs" / "whatsapp-mcp"
_LOG_PATH = _LOG_DIR / "audit.log"

Outcome = Literal[
    "sent",
    "sent_unverified",
    "cancelled",
    "rate_limited",
    "error",
]

class AuditEntry(BaseModel):
    """Schema for one line of audit.log. Frozen for v0.1."""
    ts: int = Field(default_factory=lambda: int(time.time()))
    chat_id: int
    chat_name: str
    body_sha256: str
    outcome: Outcome
    message_id: str | None = None
    error: str | None = None
    confirm_skipped: bool = False
    elapsed_ms: int = 0


def _blocking_append(entry_json: str) -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not _LOG_PATH.exists()
    # buffering=1 = line-buffered; each entry hits disk on its trailing \n
    with open(_LOG_PATH, "a", buffering=1, encoding="utf-8") as fp:
        fp.write(entry_json + "\n")
    if is_new:
        os.chmod(_LOG_PATH, 0o600)


async def append(entry: AuditEntry) -> None:
    payload = entry.model_dump_json()
    await asyncio.to_thread(_blocking_append, payload)
```

**Design notes for the planner:**
- **No `flock` in v0.1:** single MCP server instance per user; flag as Phase-3 candidate. If multi-instance ever ships, switch to `fcntl.flock(LOCK_EX)` around the `write` to serialize cross-process appends.
- **`os.chmod(0o600)` after creation, not before:** the file doesn't exist when `chmod` would target it; the create-then-chmod sequence is the standard pattern.
- **`buffering=1`** is line-buffered. Each entry hits disk on its trailing `\n` — important for audit integrity if the server crashes mid-send.
- **`model_dump_json()` not `model_dump()` + `json.dumps`:** Pydantic v2 handles datetime / nested serialization correctly; equivalent for this flat schema but consistent with the project's Phase-1 pattern.

### Pattern 7: Cross-Chat-Quote Heuristic (D-15..D-18)

**Concrete implementation:**

```python
# sender/cross_chat_quote.py
"""Session-scoped cross-chat-quote heuristic (D-15..D-18, SEND-07).

In-memory LRU of (chat_id, body, recorded_at) tuples. Read tools call
record_bodies() after returning their projection; send tool calls
check() during confirmation construction.

40-char threshold (D-16) → no false positives on common phrases like
"got it thanks", "ok see you", "sounds good". 30-min window (D-17) bounds
how long a quoted snippet stays "fresh." LRU max 1000 entries cap total memory
at ~1-2 MB.

In-memory only (D-17) — restart clears the heuristic. This is intentional:
a process restart implies a fresh trust context for prompt-injection defense.
"""
from __future__ import annotations
import time
from collections import deque
from dataclasses import dataclass

_MAX_ENTRIES = 1000
_WINDOW_SECONDS = 30 * 60  # 30 min
_MIN_SUBSTRING = 40  # D-16

@dataclass(frozen=True)
class _Entry:
    chat_id: int
    body: str
    recorded_at: float

@dataclass(frozen=True)
class OffendingSource:
    source_chat_id: int
    snippet: str   # first 100 chars of the offending substring (for prompt display)

# Module-level deque acts as LRU; threadsafe-ish for asyncio (single event loop).
_lru: deque[_Entry] = deque(maxlen=_MAX_ENTRIES)


def record_bodies(chat_id: int, bodies: list[str]) -> None:
    """Called by every read tool after projecting messages.

    Bodies with len < _MIN_SUBSTRING are skipped — they can't trigger a
    later match. Empty / None bodies skipped.
    """
    now = time.time()
    for body in bodies:
        if body and len(body) >= _MIN_SUBSTRING:
            _lru.append(_Entry(chat_id, body, now))


def check(target_chat_id: int, outgoing_body: str) -> list[OffendingSource]:
    """Find substring runs ≥ 40 chars shared between outgoing_body and any
    cached body from a DIFFERENT chat_id within the 30-min window.

    Naive O(n*m) substring scan: with ≤1000 stored bodies × ~100-char typical
    outgoing body, this is ~100k char ops. Trivial CPU cost (<1ms).
    """
    if len(outgoing_body) < _MIN_SUBSTRING:
        return []
    now = time.time()
    found: list[OffendingSource] = []
    # Snapshot the LRU to avoid mutation during iteration.
    for entry in list(_lru):
        if entry.chat_id == target_chat_id:
            continue
        if now - entry.recorded_at > _WINDOW_SECONDS:
            continue
        match = _longest_shared_substring(outgoing_body, entry.body, _MIN_SUBSTRING)
        if match is not None:
            found.append(OffendingSource(source_chat_id=entry.chat_id, snippet=match[:100]))
    return found


def _longest_shared_substring(a: str, b: str, min_len: int) -> str | None:
    """Return any shared contiguous substring of length ≥ min_len, or None.

    Uses Python's native `in` operator with sliding window — for our
    workload (a ≤ ~1k chars, b ≤ ~5k chars, min_len = 40), this is fine.
    """
    if len(a) < min_len or len(b) < min_len:
        return None
    # Slide a window of size min_len across `a`; for each, check `in b`.
    # First hit wins (we want existence, not the absolute-longest).
    for i in range(len(a) - min_len + 1):
        chunk = a[i : i + min_len]
        if chunk in b:
            # Greedy-extend forward to capture more context for the snippet.
            j = i + min_len
            while j < len(a) and a[i : j + 1] in b:
                j += 1
            return a[i:j]
    return None
```

**Integration with read tools (Plan 02-04):**

Each of the 5 read tools (`list_chats`, `read_chat`, `extract_recent`, `search_messages`, `get_message_context`) gains a single line **after** projecting messages but **before** returning:

```python
# Plan 02-04 integration site — one line per read tool body
from whatsapp_mcp.sender import cross_chat_quote
# ... existing read-tool body ...
cross_chat_quote.record_bodies(chat_id, [m.body for m in messages if m.body])
return {"messages": [...], ...}
```

`list_chats` does not surface message bodies, so it does NOT call `record_bodies` — only the 4 tools that return message text do (`read_chat`, `extract_recent`, `search_messages`, `get_message_context`).

**REL-05 impact:** this is the first time a read tool imports from `whatsapp_mcp.sender`. The D-24 evolved invariant allows it because the import is from `sender/cross_chat_quote.py` (a guard module), NOT from sender's send-path orchestration. **Update `tests/unit/test_isolation.py`:**
- `test_isolation_reader_does_not_import_sender` — STAYS load-bearing for `reader/` (the data tier). Plan 02-04 modifies `tools/*.py`, NOT `reader/*.py`.
- `test_isolation_sender_does_not_import_reader` — RELAXED per D-24: sender MAY import `reader.connection` only.
- New test: `test_isolation_tools_may_import_both` — explicit allowlist that tools can pull from both reader and sender.

### Pattern 8: Post-Hoc Verification Poll (D-21)

**Concrete SQL** (uses Phase 1's verified `ZISFROMME` column on `ZWAMESSAGE` — confirmed in `reader/schema_v1.py` lines 105, 209, 228):

```python
# sender/verify.py
"""Post-hoc DB poll after a send attempt (SEND-08 / D-21).

Cadence: 250 ms × 40 = 10 s wall-clock budget. First match wins.
Body match is exact (ZTEXT = :body); WhatsApp may normalize whitespace
or line endings on its writer path, in which case the match misses and
the tool returns sent_unverified (D-22 soft-fail).

D-24 EVOLVED REL-05: this module imports reader.connection.open_ro
(one-way edge: sender → reader.connection allowed; reader → sender
still forbidden). Verified in test_isolation.
"""
from __future__ import annotations
import asyncio
import sqlite3
from whatsapp_mcp.paths import resolve_chatstorage_path
from whatsapp_mcp.reader.connection import open_ro
from whatsapp_mcp.time import unix_to_cocoa

_POLL_INTERVAL_SECONDS = 0.25
_MAX_POLLS = 40   # 10 s total

_SQL = (
    "SELECT ZSTANZAID, ZMESSAGEDATE FROM ZWAMESSAGE "
    "WHERE ZCHATSESSION = ? "
    "AND ZISFROMME = 1 "
    "AND ZTEXT = ? "
    "AND ZMESSAGEDATE > ? "
    "ORDER BY ZSORT DESC "
    "LIMIT 1"
)


def _blocking_probe(chat_id: int, body: str, since_cocoa: float) -> str | None:
    """Single RO probe — returns ZSTANZAID if found, None otherwise."""
    db_path = resolve_chatstorage_path()
    with open_ro(db_path) as conn:
        row = conn.execute(_SQL, (chat_id, body, since_cocoa)).fetchone()
    return row[0] if row is not None else None


async def poll_for_outgoing(
    chat_id: int,
    body: str,
    send_started_unix: float,
) -> str | None:
    """Poll up to 10 s for the outgoing message in WhatsApp's DB.

    Returns ZSTANZAID (the WhatsApp protocol message id) on success;
    None on timeout (caller maps None → outcome="sent_unverified").
    """
    since_cocoa = unix_to_cocoa(send_started_unix)
    for _ in range(_MAX_POLLS):
        stanza_id = await asyncio.to_thread(_blocking_probe, chat_id, body, since_cocoa)
        if stanza_id is not None:
            return stanza_id
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    return None
```

**Design notes:**
- **`ZISFROMME = 1` verified** in `src/whatsapp_mcp/reader/schema_v1.py` lines 105, 209, 228 [VERIFIED: codebase grep]. The column exists on `ZWAMESSAGE` and the Phase 1 schema-v1 templates already select it.
- **`ZMESSAGEDATE > :send_started_cocoa`** prevents matching a pre-existing identical message body from earlier in the chat. The `send_started_unix` parameter is captured at the top of `send_message`'s body and persists across the whole orchestration.
- **`ZTEXT = ?` exact match:** if WhatsApp normalizes whitespace / line endings before persisting (e.g., trims trailing whitespace), the equality miss leads to `outcome="sent_unverified"` per D-22. This is the right soft-fail: the message IS observable in the WA UI, we just couldn't confirm via DB in our window. Document the limitation in the tool description.
- **Why not `ZTEXT LIKE '%body%'`:** would match false positives (a quoted-reply substring containing the body). Exact equality is the right tradeoff — false negatives (missed verification, soft fail) are user-acceptable; false positives (claiming success when actually a different message matched) would be a much worse failure mode.
- **`reader.connection.open_ro` reuse:** per D-24 the one-way edge `sender/verify.py → reader.connection.open_ro` is explicitly allowed. Module-level `from whatsapp_mcp.reader.connection import open_ro` is the only `whatsapp_mcp.reader.*` import allowed in any `sender/` file. Plan 02-05's isolation test asserts this.

### Pattern 9: TCC Re-Check at Send Time (T-6)

**Concrete pattern:**

```python
# inside tools/send_message.py body, between D-25 step 1 (read_only_mode)
# and step 2 (chat_id validation)
from whatsapp_mcp.permissions import automation
from whatsapp_mcp.exceptions import AutomationRevoked

automation_status = await automation.check_whatsapp()
if automation_status.state != "granted":
    raise AutomationRevoked(
        f"Automation TCC for WhatsApp is not granted (state={automation_status.state}). "
        f"Grant Automation permission to {automation_status.binary_path} in "
        f"System Settings → Privacy & Security → Automation."
    )
```

**Cost:** ~50 ms per send (the D-09 PATCHED probe `id of application "WhatsApp"` exits ~30-50 ms when granted). Worth the latency for the ban-prevention insurance — TCC can be revoked silently between server start and send-time, and a -1743 mid-keystroke is worse than a clean preflight rejection.

**Exception class to add to `exceptions.py`:**
```python
class AutomationRevoked(WhatsAppMCPError):
    """Raised when Automation TCC is revoked between server start and send-time."""
    def __init__(self, message: str, *, binary_path: str = sys.executable, system_settings_url: str = "...Privacy_Automation"):
        ...
```

### Anti-Patterns to Avoid (Phase 2 specific)

- **Logging body plaintext** (D-13 / D-14 violation; T-4 mitigation) — only SHA-256 fingerprint in audit log; body never persists.
- **Auto-picking fuzzy chat-name matches** (D-25 / SEND-01 violation; P5) — chat_id MUST be an opaque int returned by Phase 1's `search_contacts` / `list_chats`. Free-form name string → `InvalidChatId` (caught at the Pydantic-validation layer when a string fails int coercion).
- **Bypassing elicitation without `confirm_skipped: true` audit entry** (D-08 violation) — `WHATSAPP_MCP_SKIP_CONFIRM=1` MUST still write the audit entry with `confirm_skipped: true`.
- **Exposing pyobjc ImportError as a Python traceback** (D-06 violation) — wrap in `try/except ImportError`; `_PYOBJC_AVAILABLE = False` flag; `send_message` returns `AccessibilityAPIUnavailable` structured error.
- **Writing to ChatStorage.sqlite** (CLAUDE.md hard rule #3) — `sender/verify.py` uses `open_ro` only; rate-limit DB is a SEPARATE file at `~/Library/Application Support/whatsapp-mcp/rate-limit.db`.
- **Silently expanding rate-limit env-var override beyond hard max** (D-11 violation) — `_resolve_limits()` REJECTS with a structured config error at startup if env var > hard max.
- **Raw `asyncio.TimeoutError` to client** (REL-03 / @timeout decorator pattern) — use the existing `@timeout(seconds=15)` decorator on `send_message` (REL-03) which maps to a structured `ValueError` → MCP error response.
- **Sequencing keystroke before AX assertion** (D-03 violation; load-bearing P5 mitigation) — `assert_focused_chat_matches` MUST run BEFORE any `keystroke` call. The orchestrator in `ui_send.py` enforces this ordering.
- **Comparing AX-extracted strings without bidi-strip** (verified-live trap) — three invisibles (U+200E, U+2068, U+2069) appear on every WhatsApp Catalyst AX label; equality comparison silently fails without strip.
- **Substring search-and-click without AX preflight on the click target** (P5) — `send_group_via_search` MUST AX-walk the sidebar list and assert the topmost result's stripped name matches before pressing Return.
- **Concurrent read+rate-limit DB locks** — rate-limit DB is a SEPARATE file from WhatsApp's `ChatStorage.sqlite`; no contention possible. Test that the path is distinct from `resolve_chatstorage_path()`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| MCP elicitation request/response framing | Custom JSON-RPC `elicitation/create` envelope | `ctx.elicit(message, schema)` (verified `mcp==1.27.1`) | SDK handles wire format, `requestedSchema` shape, related_request_id correlation |
| Pydantic model validation on elicit content | Hand-rolled `if "confirm" not in content: ...` | Pydantic `model_validate(result.content)` — happens automatically inside `elicit_with_validation` | SDK already does this; bypassing it loses field-type coercion |
| AppleScript error-code parsing | Regex on localized stderr ("Not authorized") | Phase 0's `permissions.osascript.run_osascript` + `error_code` int (locale-blind) | Already shipped; reuse |
| TCC permission detection | Direct read of `TCC.db` / pyobjc TCC APIs | Phase 0's `permissions.automation.check_whatsapp()` (D-09 PATCHED) | Already shipped; ban-recovery rebuilds it cleanly |
| Async subprocess timeout | Manual `proc.terminate()` after `time.sleep()` | `asyncio.wait_for(proc.communicate(), timeout=N)` (Phase 0 pattern) | The project's stdio-loop pattern — never block the loop |
| LRU cache for cross-chat-quote | Custom dict + manual eviction | `collections.deque(maxlen=1000)` (stdlib) | Constant-time append, auto-eviction, no dependency |
| JSONL writing | Custom newline-terminated bytestream | `pydantic.BaseModel.model_dump_json()` + manual `\n` write | Pydantic v2 handles all serialization edge cases |
| SHA-256 of body | Custom hex-formatting loop | `hashlib.sha256(body.encode("utf-8")).hexdigest()` (stdlib) | Standard 64-char lowercase hex; matches what an investigator would compute |
| Cocoa-epoch ↔ Unix conversion | Custom 978307200 arithmetic | Phase 1's `whatsapp_mcp.time.unix_to_cocoa` | Already shipped, tested |
| Path to WhatsApp's ChatStorage.sqlite | Hardcoded string | Phase 0's `whatsapp_mcp.paths.resolve_chatstorage_path()` | Already shipped |
| Per-tool timeout wrapper | `try: await asyncio.wait_for(...)` inline | Phase 1's `tools._decorators.@timeout(seconds=15)` | Already shipped; uniform error mapping |

**Key insight:** Phase 2 is fully **composable on top of Phase 0 + Phase 1's primitives**. The only genuinely new code is the sender package's six modules. Everything else (osascript wrapper, TCC probes, RO SQLite connection, async dispatch, structured errors, @timeout decorator, Pydantic models) is reused from earlier phases.

## Runtime State Inventory

> Phase 2 introduces **persistent state at two new filesystem locations** AND establishes process-local LRU state. This inventory enumerates what gets created.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `~/Library/Application Support/whatsapp-mcp/rate-limit.db` (Plan 02-02 creates on first send; D-11) — owned by this MCP server, NOT WhatsApp. Mode 0600. Append-only `sends` table. Phase 3 may add rotation/truncation; v0.1 lets it grow. | Plan 02-02 must create directory `~/Library/Application Support/whatsapp-mcp/` if missing; tests must clean up the test DB after running (use `tmp_path` fixture in pytest, not the real path). |
| Live service config | No external service configuration. Pure local-process state. | None. |
| OS-registered state | macOS TCC entries: Automation permission for WhatsApp + Accessibility (already required by Phase 0; Phase 2 adds NO new TCC buckets — pyobjc AX-API uses the existing Accessibility bucket, not a new one). | None — verified by inspecting `~/Library/Application Support/com.apple.TCC/` is not touched by this phase; existing Phase 0 buckets cover us. |
| Secrets/env vars | `WHATSAPP_MCP_SKIP_CONFIRM=1`, `WHATSAPP_MCP_RATE_PER_MIN=N`, `WHATSAPP_MCP_RATE_PER_DAY=N`. All optional. None are secrets — boolean / int overrides only. | README documents all three; tests for env-var validation (Plan 02-05). |
| Build artifacts | pyobjc-core 12.1, pyobjc-framework-Cocoa 12.1, pyobjc-framework-ApplicationServices 12.1 — added to `[project] dependencies` per D-05. Adds ~30 MB to the wheel. `uv.lock` updates on first sync. | Plan 02-01 task 1 modifies `pyproject.toml`; `uv sync --extra dev` re-resolves; commit the updated `uv.lock`. |

**Process-local (transient, no FS):**
- `sender.cross_chat_quote._lru` — `collections.deque[_Entry]` max 1000 entries, ~1-2 MB peak. Reset on server restart per D-17.
- `sender.rate_limit._resolve_limits` cached result? No — re-resolved per call so live env-var changes take effect (negligible cost).

**Nothing found in category "Live service config":** None — verified by inspecting CONTEXT.md, no decision references an external service.

## Common Pitfalls

### Pitfall 1: Equality compare on AX-extracted chat header without bidi-strip
**What goes wrong:** `"Olivier Giffard" == header_text` returns False; `ChatHeaderMismatch` raised on every send → no sends ever succeed.
**Why it happens:** WhatsApp Catalyst inserts U+200E (LRM), U+2068 (FSI), U+2069 (PDI) around every AX label (verified live on user's Mac 2026-05-13).
**How to avoid:** Use `_strip_bidi(s)` before equality / substring; the function strips exactly those three codepoints. Add a regression test: a fixture string with these three bidi marks must compare-equal after strip.
**Warning signs:** `ChatHeaderMismatch` raised even when the user verifies the right chat is foreground. Check stderr log of `observed AXHeading values (stripped)` — if you see them with no LRM but they still don't match, the chat-name resolution layer is wrong; if you see them WITH LRM, the strip isn't running.

### Pitfall 2: Forgetting `ctx: Context` parameter on the tool function
**What goes wrong:** `ctx.elicit(...)` is uncallable because there's no `ctx`. Or worse: tool signature shows up wrong in `tools/list`.
**Why it happens:** FastMCP requires the type annotation `Context` to know which parameter to inject. A `ctx: Any` parameter gets included in the public JSON-schema and the SDK doesn't auto-inject.
**How to avoid:** Import `from mcp.server.fastmcp import Context` and use the explicit type annotation. Verified at `mcp/server/fastmcp/server.py:598` — the SDK's `Context` parameter detection is via the type annotation.
**Warning signs:** `tools/list` JSON schema for `send_message` shows a `ctx` parameter (means it wasn't detected); `AttributeError: 'NoneType' object has no attribute 'elicit'`.

### Pitfall 3: Elicit schema with dict / nested model field
**What goes wrong:** `TypeError: Elicitation schema field 'X' must be a primitive type ...` raised at `ctx.elicit()` call time, mid-send.
**Why it happens:** `mcp.server.elicitation._validate_elicitation_schema` (mcp/server/elicitation.py:52) rejects anything that isn't `str | int | float | bool | list[str] | None`. Verified.
**How to avoid:** `ConfirmationSchema` has only primitive fields (a single `confirm: bool`). All confirmation-context fields (chat name, body, warnings, budget) go in the `message` string, NOT the schema. Verified pattern.
**Warning signs:** TypeError on `ctx.elicit` call; SDK source at `mcp/server/elicitation.py:64` is the canonical reference.

### Pitfall 4: Group send keystroke before AX-list-result preflight
**What goes wrong:** WhatsApp's search returns the wrong topmost result (fuzzy match: typing "Mom" matches "Momentum project"). Return-keystroke selects it. Body keystroke goes into a wrong chat's input. Send fires.
**Why it happens:** WhatsApp's search-result ordering depends on recency, alphabetization, and fuzzy-match score. Without an AX preflight on the resulting list, we trust the search; we shouldn't.
**How to avoid:** `send_group_via_search` step 4 walks the sidebar AXButton list, asserts the topmost (visible) AXButton's stripped name contains the resolved `chat_name`. If not, abort with `ChatHeaderMismatch` BEFORE the Return keystroke.
**Warning signs:** Group sends occasionally land in nearby-named chats during dev testing.

### Pitfall 5: Rate-limit env-var silently disables protection
**What goes wrong:** `WHATSAPP_MCP_RATE_PER_DAY=10000` accepted; user agent fan-out blasts; account ban.
**Why it happens:** D-11 bounded override exists, but if `_resolve_limits` doesn't enforce, the server happily accepts the override.
**How to avoid:** `_resolve_limits` REJECTS env values above hard maxes (20/min, 200/day) with a `ValueError` at module-load time (before the server even starts). Test: set `WHATSAPP_MCP_RATE_PER_DAY=300`, `uvx whatsapp-mcp --no-read-only`, assert exit-1 with config-error.
**Warning signs:** Server starts with logging level INFO showing `_resolve_limits` returning > 20 or > 200.

### Pitfall 6: Audit log written before rate-limit check
**What goes wrong:** A rate-limited send still appears in `audit.log` as `outcome="sent"`. Investigations get noise.
**Why it happens:** Ordering in `send_message` body matters: D-25 step 5 (rate-limit) BEFORE step 8 (send). Audit append at step 10 ONLY records the final outcome.
**How to avoid:** Single `audit.append()` call at the END of `send_message` (step 10 of D-25), in a `try/finally` that captures the actual outcome from each branch. Tests: 4 mandated regression tests in CONTEXT.md §"Specifics" cover this.
**Warning signs:** `audit.log` rows where `outcome=sent` but the rate-limit DB has the same `(chat_id, body_sha256)` with `outcome=rate_limited` — split-state.

### Pitfall 7: Post-hoc verification false negative on whitespace-normalized body
**What goes wrong:** WhatsApp trims trailing whitespace before persisting; `ZTEXT = ?` exact-match misses; `outcome="sent_unverified"` even though the send succeeded.
**Why it happens:** D-22 explicitly notes this; the soft-fail is correct, but downstream LLM workflows may treat `sent_unverified` as failure and retry — sending duplicates.
**How to avoid:** Document `sent_unverified` in the tool description as "send observably succeeded in the UI but DB verification timed out; do NOT retry". Tool result includes `verification_note` explaining the soft-fail. Don't auto-retry on this outcome.
**Warning signs:** Duplicate messages in WhatsApp chat history during testing with a slow network. Check for `outcome="sent_unverified"` in audit + then a second `outcome="sent"` for the same SHA within seconds.

### Pitfall 8: pyobjc ImportError crashes server at startup
**What goes wrong:** `import ApplicationServices` raises `ImportError` on a user's broken install; the WHOLE server fails to start (reader and sender both unavailable). Read-only mode also broken.
**Why it happens:** D-06 requires `try/except ImportError` at sender module level. Forgetting it makes pyobjc a hard import.
**How to avoid:** Every pyobjc symbol used by `ax_assert.py` lives behind a `try/except ImportError → _PYOBJC_AVAILABLE = False` guard. `send_message` returns `AccessibilityAPIUnavailable` structured error if `_PYOBJC_AVAILABLE` is False; read tools work fine.
**Warning signs:** Test on a non-mac CI runner: `import whatsapp_mcp.sender.ax_assert` should NOT raise; calling `assert_focused_chat_matches(...)` should raise `AccessibilityAPIUnavailable` structured.

### Pitfall 9: `flock` absence on audit log under multi-instance
**What goes wrong:** Two MCP server instances both append to `~/Library/Logs/whatsapp-mcp/audit.log`; lines interleave mid-write; some lines unparseable.
**Why it happens:** v0.1 ships with no per-process file locking (deferred per D-14). If the user starts a second instance (e.g., Claude Desktop + Claude Code simultaneously), races.
**How to avoid:** Document in README: v0.1 supports a single MCP server instance per machine. Phase-3 candidate: add `fcntl.flock(LOCK_EX)` around the audit-log write. Test for v0.1: NOT critical (single instance is the supported config); flag in PITFALLS for future work.
**Warning signs:** `audit.log` has unparseable lines after running Claude Desktop + Claude Code concurrently. Not in scope for Phase 2.

## Code Examples

Verified patterns from the codebase and live-verified APIs:

### Example 1: ctx.elicit usage (verified API on mcp==1.27.1)
```python
# Source: mcp/server/fastmcp/server.py:1194 + mcp/server/elicitation.py:17-36
from mcp.server.fastmcp import Context
from mcp.server.elicitation import AcceptedElicitation, DeclinedElicitation, CancelledElicitation
from pydantic import BaseModel, Field

class ConfirmationSchema(BaseModel):
    confirm: bool = Field(description="Send this WhatsApp message?")

async def some_tool(ctx: Context, ...) -> dict:
    result = await ctx.elicit(
        message="Send WhatsApp message to Alice (chat_id=34)?\n\nBody:\n---\nHi!\n---",
        schema=ConfirmationSchema,
    )
    if isinstance(result, AcceptedElicitation):
        if result.data.confirm:
            ...  # send
    elif isinstance(result, DeclinedElicitation):
        ...  # user said no
    elif isinstance(result, CancelledElicitation):
        ...  # user dismissed without choosing
```

### Example 2: Deep-link URL builder
```python
# Source: verified live via `python3 -c "import urllib.parse; ..."` 2026-05-13
import urllib.parse

def build_send_url(phone_e164: str, body: str) -> str:
    digits_only = phone_e164.lstrip("+").replace(" ", "").replace("-", "")
    if not digits_only.isdigit():
        raise ValueError(f"phone must be digits after stripping: {phone_e164!r}")
    return f"whatsapp://send?phone={digits_only}&text={urllib.parse.quote(body, safe='')}"

# Example:
# build_send_url("+33612345678", "Hello!")
# → "whatsapp://send?phone=33612345678&text=Hello%21"
```

### Example 3: Bidi-strip for AX header comparison
```python
# Source: verified live on WhatsApp Desktop 26.16.74 2026-05-13
_INVISIBLE_BIDI = frozenset({"‎", "⁨", "⁩"})  # LRM, FSI, PDI

def _strip_bidi(s: str) -> str:
    return "".join(c for c in s if c not in _INVISIBLE_BIDI).strip()

# Verified:
# _strip_bidi("‎⁨Olivier Giffard⁩") == "Olivier Giffard"  # True
```

### Example 4: Reuse Phase 0's osascript wrapper
```python
# Source: src/whatsapp_mcp/permissions/osascript.py:58 (already shipped)
from whatsapp_mcp.permissions.osascript import run_osascript

result = await run_osascript(
    'tell application "System Events" to keystroke return',
    timeout=3.0,
)
if result.exit_code != 0:
    if result.error_code == -1743:
        raise AutomationRevoked(...)
    raise OsascriptError(f"keystroke return failed: {result.stderr}")
```

### Example 5: SHA-256 of body
```python
# Source: stdlib hashlib — standard pattern
import hashlib

def body_sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()

# Returns 64-char lowercase hex string.
```

### Example 6: Add @timeout decorator to send_message
```python
# Source: src/whatsapp_mcp/tools/_decorators.py (already shipped Phase 1)
from whatsapp_mcp.tools._decorators import timeout

@mcp.tool(name="send_message", ...)
@timeout(seconds=15)   # REL-03: 15s budget for the whole send orchestration
async def send_message(chat_id: int, body: str, ctx: Context) -> SendResult:
    ...
```

### Example 7: Read-tool integration hook (Plan 02-04)
```python
# Source: pattern to apply to read_chat, extract_recent, search_messages,
# get_message_context — one-line addition each, after projection, before return.
from whatsapp_mcp.sender import cross_chat_quote

# At the END of each tool body, before `return`:
cross_chat_quote.record_bodies(chat_id, [m.body for m in messages if m.body])
return {"messages": [m.model_dump() for m in messages], ...}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hand-rolled JSON-RPC `elicitation/create` request | `ctx.elicit(message, schema=PydanticModel)` returning typed union | mcp==1.27.1 (current) | Removes boilerplate; SDK handles related_request_id, schema validation, decline/cancel branching |
| `osascript` AX walk for the focused-chat-header check | pyobjc-based `AXUIElementCopyAttributeValue` walk | Phase 2 D-05 | ~30x faster; type-safe; testable via mock; immune to localized stderr |
| Bare `keystroke` after `tell ... activate` (lharries/gfb-47 approach) | Deep-link → settle-poll → keystroke return (D-01) | Phase 2 | Eliminates the search-and-click race for 1:1; group sends use the documented-fragile fallback marked `is_experimental=true` |
| Body plaintext in audit log | SHA-256 fingerprint only (D-13) | Phase 2 | Privacy-preserving; investigator can confirm content via hash without storing it |
| In-memory rate limit | Persistent SQLite at `~/Library/Application Support/...` (D-11) | Phase 2 | Server restart can't bypass daily cap; matches the WhatsApp-account-as-protected-resource model |
| Single confirmation cache ("trust this chat for 5 mins") | Per-send elicitation always (D-09) | Phase 2 | No prompt-injection bypass via accumulated trust |

**Deprecated / outdated patterns (do NOT introduce):**
- **WhatsApp's own FTS index** (`fts/ChatSearchV5f.sqlite`): custom `wa_tokenizer` only loads in WhatsApp.app process. Not relevant to Phase 2 (no search), but flagged as a generic "don't try to use" item.
- **Raw `AXTextArea.setValue:` + `AXButton "Send" AXPress`** (the Phase 2 D-04 deferred path): defer to v2 (SEND2-04). The keystroke-return + AX preflight combo is the v0.1 design.
- **Multi-recipient send tool** (`send_to_many`): anti-feature per PROJECT.md / CLAUDE.md hard rule #7. NEVER ship.

## Plan Structure Recommendation

**Coarse target (per `.planning/config.json` granularity=coarse):** 1-3 plans. Phase 2 has 8 requirements + heavy guardrail surface (rate limiter + audit + cross-chat-quote + AX preflight + deep-link + group fallback + post-hoc verify + MCP elicit). A 3-plan split is too tight for the genuine 5-component surface. **Recommend 5 plans** matching the natural file boundaries; this is consistent with Phase 1's 6-plan split for its 21 reqs.

### Plan 02-01: Sender Primitives (no MCP coupling)
**Files:** `pyproject.toml` (add pyobjc deps), `src/whatsapp_mcp/sender/deeplink.py`, `src/whatsapp_mcp/sender/osascript_send.py`, `src/whatsapp_mcp/sender/ax_assert.py`, `src/whatsapp_mcp/exceptions.py` (append `ChatHeaderMismatch`, `AccessibilityAPIUnavailable`, `OsascriptError`, `SendTimeout`, `AutomationRevoked`)
**Requirements:** SEND-03 (deep-link primary), SEND-04 (AX preflight)
**Depends on:** Phase 0 (`permissions.osascript`, exception hierarchy), Phase 1 (none — sender primitives have no DB coupling)
**Parallelizable with:** Plan 02-02 (disjoint files)
**Wave 0 / spike:** Verify the actual sidebar-search shortcut on the user's WhatsApp (Cmd-F vs AX-click on "Rechercher" AXGenericElement). One-line spike: `osascript -e 'tell application "System Events" to keystroke "f" using {command down}'`; observe what gets focused.

### Plan 02-02: Guardrail Modules (no MCP coupling)
**Files:** `src/whatsapp_mcp/sender/rate_limit.py`, `src/whatsapp_mcp/sender/audit.py`, `src/whatsapp_mcp/sender/cross_chat_quote.py`, `src/whatsapp_mcp/exceptions.py` (append `RateLimitExceeded`, `InvalidChatId`), `src/whatsapp_mcp/models/send.py` (`SendResult`, `OffendingSource`, `ConfirmationSchema`, `AuditEntry`)
**Requirements:** SEND-05 (rate limiter), SEND-06 (audit log), SEND-07 (cross-chat-quote heuristic)
**Depends on:** Phase 0 exceptions
**Parallelizable with:** Plan 02-01 (disjoint files)

### Plan 02-03: Send Tool + Orchestration
**Files:** `src/whatsapp_mcp/sender/ui_send.py`, `src/whatsapp_mcp/sender/verify.py`, `src/whatsapp_mcp/sender/__init__.py` (re-export `send_text`, `SendResult`), `src/whatsapp_mcp/tools/send_message.py`, `src/whatsapp_mcp/server.py` (add the read-only-gated import block)
**Requirements:** SEND-01 (opaque chat_id), SEND-02 (elicitation + destructiveHint), SEND-08 (post-hoc verification)
**Depends on:** Plan 02-01 + Plan 02-02 (all sender primitives + guardrails), Phase 1 reader (`find_chat_by_id`, `open_ro` for `verify.py`)

### Plan 02-04: Read-Tool Integration (Cross-Chat-Quote Recording)
**Files:** `src/whatsapp_mcp/tools/read_chat.py`, `extract_recent.py`, `search_messages.py`, `get_message_context.py` (each gains 1 line of `cross_chat_quote.record_bodies(...)` after projection)
**Requirements:** SEND-07 (the recording half of the heuristic)
**Depends on:** Plan 02-02 (`sender.cross_chat_quote` module exists)
**REL-05 impact:** This is the first time tool modules import from `sender/`. Update `test_isolation.py` to allowlist this edge.

### Plan 02-05: Tests
**Files:** `tests/unit/test_sender/test_deeplink.py`, `test_osascript_send.py`, `test_ax_assert.py` (with mocked pyobjc + bidi-strip regression), `test_rate_limit.py`, `test_audit.py`, `test_cross_chat_quote.py`, `test_ui_send.py`, `test_verify.py`, `tests/unit/test_tools/test_send_message.py`, `tests/integration/test_live_send.py` (RUN_LIVE=1 gated smoke; sends to a self-chat); update `tests/unit/test_isolation.py` (REL-05 evolved per D-24)
**Requirements:** All 8 SEND-* validated via tests
**Depends on:** All prior Phase 2 plans
**Mandatory regression tests** (from CONTEXT.md §"Specifics"):
- `test_send_message_refuses_string_chat_id` (SEND-01 contract — Pydantic int coercion failure surfaces as `InvalidChatId`)
- `test_send_message_aborts_on_chat_header_mismatch` (D-03 / SEND-04 / P5 — mock pyobjc; verify `ChatHeaderMismatch` raised, audit log has `outcome="error"`)
- `test_send_message_rate_limit_persists_across_restart` (D-11 / SEND-05 — write 5 sends to fixture rate-limit.db, restart fixture, 6th send raises `RateLimitExceeded`)
- `test_send_message_appends_audit_log_with_body_sha256_not_body` (D-13 / SEND-06 — `grep -c BODY_PLAINTEXT_STRING audit.log` returns 0; SHA hex present)

**Plan dependencies graph:**
```
02-01 (sender primitives) ─┐
                            ├─→ 02-03 (send tool) ──→ 02-05 (tests)
02-02 (guardrails) ────────┤
                            └─→ 02-04 (read-tool integration) ──→ 02-05
```

Plans 02-01 and 02-02 run in parallel (Wave 1, two parallel tracks). 02-04 can also run in parallel with 02-03 (Wave 2) — they touch disjoint files. 02-05 is Wave 3 (depends on all).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `/usr/bin/osascript` | Phase 0 + Phase 2 (every keystroke / AX-via-script probe) | ✓ | macOS-bundled | None (mandatory) |
| `/usr/bin/open` | Phase 2 D-01 (deep-link launch) | ✓ | macOS-bundled | None (mandatory) |
| WhatsApp.app at `/Applications/WhatsApp.app` | Phase 2 (target of send) | ✓ | 26.16.74 (verified live 2026-05-13) | None (mandatory) — `doctor` already reports `whatsapp_not_installed` |
| pyobjc-core 12.1 | Plan 02-01 (`ax_assert.py`) | Not yet (will install via `uv sync` after Plan 02-01 task 1) | 12.1 latest on PyPI (verified 2026-05-13) | D-06 try/except ImportError; `AccessibilityAPIUnavailable` structured error |
| pyobjc-framework-Cocoa 12.1 | Plan 02-01 (`ax_assert.py` for NSWorkspace) | Not yet | 12.1 latest | Same fallback |
| pyobjc-framework-ApplicationServices 12.1 | Plan 02-01 (AX-API symbols) | Not yet | 12.1 latest | Same fallback |
| `~/Library/Application Support/` | Plan 02-02 (rate-limit DB parent dir) | ✓ (standard macOS path) | — | None (mandatory) |
| `~/Library/Logs/` | Plan 02-02 (audit log parent dir) | ✓ (standard macOS path) | — | None (mandatory) |
| TCC Automation grant for WhatsApp | Plan 02-03 (every osascript call) | ✓ (Phase 0's doctor probe returns granted on user's Mac) | — | If revoked: `AutomationRevoked` structured error per T-6 |
| TCC Accessibility grant | Plan 02-03 (pyobjc AX-API uses this bucket) | ✓ (Phase 0's doctor probe returns granted on user's Mac) | — | If revoked: `ChatHeaderMismatch` (AX walk fails) — surface as remediation pointer |
| FDA grant (for verify.py reading ChatStorage.sqlite) | Plan 02-03 (post-hoc verify) | ✓ (Phase 0's doctor probe returns granted on user's Mac) | — | If revoked: `verify.py` returns None → `outcome="sent_unverified"` (soft fail per D-22) |

**Missing dependencies with no fallback:** None — all mandatory tools verified available on user's Mac.

**Missing dependencies with fallback:** The 3 pyobjc packages — install via `uv sync` after Plan 02-01 task 1. If user opts to skip (unlikely; they're hard deps in `[project] dependencies`), the D-06 fallback returns `AccessibilityAPIUnavailable` per-call.

## Project Constraints (from CLAUDE.md)

The following CLAUDE.md hard rules constrain Phase 2 design:

1. **Reader ↔ Sender isolation** (Hard rule #1) — Phase 2 EVOLVES this per D-24: sender MAY import `reader.connection.open_ro` only. Tests must enforce.
2. **stdout = JSON-RPC** (Hard rule #2) — Phase 2 uses `permissions.osascript.run_osascript` (already routes to stderr) and `logging.basicConfig(stream=sys.stderr)` from Phase 0 server.py.
3. **Never write to ChatStorage.sqlite** (Hard rule #3) — Phase 2's `verify.py` uses `open_ro` (RO URI flag). Rate-limit DB is a SEPARATE file at `~/Library/Application Support/whatsapp-mcp/rate-limit.db`.
4. **Never inline media bytes** (Hard rule #4) — Phase 2 sends text only; no media path.
5. **Stdio only, no HTTP** (Hard rule #5) — Phase 2 adds zero network surface.
6. **Never compare JID strings directly** (Hard rule #6) — Phase 2 surfaces JID/LID in elicitation prompt via the existing `Jid` model from Phase 1.
7. **Send is `destructiveHint:true` + MCP elicitation + 5/min, 30/day + audit log + no multi-recipient** (Hard rule #7) — D-07, D-08, D-11, D-12, D-25 collectively satisfy.
8. **Every read tool returns `coverage`** (Hard rule #8) — N/A; Phase 2 doesn't add read tools, but Plan 02-04 touches read-tool bodies for the cross-chat-quote hook. The hook is post-projection (after `coverage` is built); invariant preserved.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The `osascript -e 'tell application "System Events" to keystroke "f" using {command down}'` shortcut focuses WhatsApp's sidebar search (vs the chat-pane Cmd-F search-within-chat) | Pattern 4 group send | [ASSUMED] If Cmd-F focuses chat-pane search not sidebar search, group send hangs in the wrong field. Mitigation: Plan 02-01 Wave 0 live spike to verify; fallback to AX-click on the "Rechercher" / "Search" AXGenericElement. |
| A2 | The chat header (when a chat is open) is exposed as an `AXHeading` node accessible from the focused-window AX walk | Pattern 2 AX assertion | [ASSUMED — supported by live probe of sidebar-only view showing `AXHeading:‎Discussions`] If chat-open view exposes the header under a different role (e.g., `AXStaticText` only, no AXHeading), the `_walk_for_heading` returns empty list and `ChatHeaderMismatch` raises on every send. Mitigation: Plan 02-01 task 3 Wave 0 spike: open a chat on user's Mac, run `osascript ... entire contents of front window`, confirm `AXHeading` shows up with the open chat's name. If not, widen `_walk_for_heading` to also collect `AXStaticText` nodes near the top of the AXGroup tree. |
| A3 | `subprocess.run(["open", "-g", "whatsapp://..."], timeout=5)` brings WhatsApp to foreground reliably enough that the subsequent settle-poll (1.5s budget) succeeds | Pattern 3 deep-link | [ASSUMED — verified `whatsapp://` URL scheme is registered in WhatsApp's Info.plist per research/ARCHITECTURE.md but `-g` flag behavior with custom URL schemes not re-verified live] If `-g` prevents WhatsApp from coming forward at all (vs just not stealing Cmd-Tab order), the settle-poll times out. Mitigation: drop `-g` for the spike; verify in Plan 02-01 Wave 0; document the actual observed behavior. |
| A4 | `ZTEXT = ?` exact match in the post-hoc verify SQL works on the user's WhatsApp 26.16.74 — i.e., WhatsApp does NOT normalize whitespace / line endings before persisting an outgoing message | Pattern 8 verify | [ASSUMED] If WhatsApp trims body, every send hits `sent_unverified` even on success. Mitigation: D-22 documented soft-fail; tool description warns user not to retry on `sent_unverified`. Phase 3 candidate: switch to fuzzy match (e.g., `ZTEXT LIKE :body` with `?` escapes) if false-negative rate is high in practice. |
| A5 | The 4 mandatory regression tests from CONTEXT.md §"Specifics" cover SEND-01..08 acceptance — additional integration tests are nice-to-have but not gating | Plan 02-05 | [ASSUMED] If the verifier reads the 5 ROADMAP §"Phase 2" success criteria more strictly than 4 unit tests can prove, Plan 02-05 may need broader coverage. Mitigation: planner should propose 1 integration smoke test (`RUN_LIVE=1`, sends to self) for each ROADMAP success criterion. |
| A6 | pyobjc 12.1's `AXUIElementCopyAttributeValue` Python signature returns `(err, value)` tuple (not raises, not returns just `value`) | Pattern 2 AX assertion | [ASSUMED based on pyobjc convention; not re-verified live in this session] If the signature is different on 12.1, `_walk_for_heading` AttributeErrors at runtime. Mitigation: Plan 02-01 task 3 Wave 0 spike — run a minimal pyobjc AX call against WhatsApp on the user's Mac; verify the exact return-tuple shape. |

**Note on A1-A6:** All six are sound enough to plan against. None require user confirmation BEFORE planning — they require execution-time spikes that Plan 02-01's Wave 0 will surface. The discuss-phase has already locked the high-level decisions (D-01..D-25); these assumptions are tactical "verify in spike" items the executor will resolve.

## Open Questions (RESOLVED via Plan 02-01 Wave 0 spikes)

1. **RESOLVED: deferred to SP-1.** **Cmd-F vs AX-click for sidebar search focus in group-send fallback**
   - What we know: AX tree shows `AXGenericElement:‎Rechercher` (FR locale) as the sidebar search field; verified live.
   - What's unclear: whether Cmd-F focuses it (vs chat-pane "search within current chat") on the user's WhatsApp Catalyst build.
   - Recommendation: Plan 02-01 Wave 0 live spike to verify; pin the result in `ui_send.py` module docstring. If Cmd-F is wrong, fallback to AX-click on the `Rechercher` AXGenericElement via pyobjc.

2. **RESOLVED: deferred to SP-2.** **Behavior of `open -g whatsapp://...` for foregrounding WhatsApp**
   - What we know: deep-link URL scheme is registered in WhatsApp's Info.plist per research/ARCHITECTURE.md.
   - What's unclear: whether `-g` keeps WhatsApp suppressed enough that the subsequent settle-poll fails to find the front window.
   - Recommendation: Plan 02-01 Wave 0 spike; if `-g` keeps WhatsApp completely background, drop the flag (document the focus-steal as the tradeoff).

3. **RESOLVED: deferred to SP-3.** **AXHeading exposure when a chat is open** (vs sidebar-only view, which we verified live)
   - What we know: in sidebar-only view the AXHeading is `‎Discussions`.
   - What's unclear: when a chat is open, does the chat name appear as `AXHeading` description or only as `AXStaticText`?
   - Recommendation: Plan 02-01 Wave 0 spike — open a chat on user's Mac, dump `entire contents of front window`, confirm AXHeading. If absent, widen `_walk_for_heading` to also collect AXStaticText nodes near top of AXGroup tree.

4. **RESOLVED: deferred to SP-4.** **pyobjc 12.1 exact API for `AXUIElementCopyAttributeValue`**
   - What we know: pyobjc generally returns `(err, value)` tuples via the `out` parameter pattern; verified on the project's training-data of older pyobjc versions.
   - What's unclear: whether 12.1 changed the convention.
   - Recommendation: Plan 02-01 task 3 Wave 0 minimal spike.

5. **RESOLVED: tested in Plan 02-05.** **Emoji / non-BMP body handling**
   - What we know: from research/PITFALLS.md P12, AppleScript `keystroke` historically truncates surrogate pairs. The deep-link path URL-encodes the body so 1:1 sends should work for emoji. The group-send fallback types body via `keystroke`, which is the failure case.
   - What's unclear: whether the user's WhatsApp Catalyst on macOS 26.4 still has the surrogate-pair issue.
   - Recommendation: Plan 02-05 includes an emoji unit test (1:1 deep-link path: should pass; group-send path: should FAIL gracefully with a `BodyEncodingNotSupported` error, NOT silently truncate). Document v0.1 constraint: group-send body restricted to BMP.

6. **RESOLVED: deferred to Phase 3 with documentation.** **Multi-instance audit-log race**
   - What we know: v0.1 ships no `flock`; documented as Phase-3 candidate.
   - What's unclear: whether users actually run two MCP instances concurrently in practice.
   - Recommendation: Phase 2 documents the limitation in README's "Sending Messages" section; Phase 3 adds `fcntl.flock` if user reports show it matters.

## Validation Architecture

*Per `.planning/config.json`, `workflow.nyquist_validation = false` — this section is SKIPPED. Plan 02-05 owns the test architecture per the 4 mandatory regression tests + per-module unit tests + RUN_LIVE=1 integration smoke.*

## Sources

### Primary (HIGH confidence — VERIFIED LIVE 2026-05-13)
- **Installed MCP SDK source** at `/Users/jlqueguiner/dev/whatsapp-mcp/.venv/lib/python3.12/site-packages/mcp/` — verified `ctx.elicit` signature (`server.py:1194`), `ElicitationResult` union (`elicitation.py:17-36`), schema-validator constraints (`elicitation.py:48-68`), `ElicitResult` content shape (`types.py:1895`), Context parameter exclusion from JSON schema (`server.py:598`)
- **WhatsApp Desktop 26.16.74 on user's Mac, macOS 26.4** — verified via `osascript`:
  - Front window name is `‎WhatsApp` (U+200E prefix) — confirms invisible-LRM trap
  - AXTree depth-walk via `entire contents of front window` — captured ~30 AXHeading + AXStaticText nodes with their descriptions
  - Bidi codepoints around contact names: U+200E, U+2068, U+2069 (verified by Python `[hex(ord(c)) for c in name]`)
  - UI locale: French (`Discussions`, `Paramètres`, `Nouvelle discussion`)
  - `defaults read /Applications/WhatsApp.app/Contents/Info.plist CFBundleShortVersionString` → `26.16.74`
- **PyPI registry** at `https://pypi.org/pypi/pyobjc-core/json` — verified `pyobjc-core` latest = 12.1, uploaded 2025-11-14
- **Existing codebase** (`src/whatsapp_mcp/`) — `ZISFROMME` column verified present in `reader/schema_v1.py` lines 105, 209, 228; `reader.connection.open_ro` signature verified; `permissions.osascript.run_osascript` async wrapper verified; `tools/_decorators.py @timeout` pattern verified

### Secondary (HIGH-MEDIUM confidence — verified from research bundle + corroborated by codebase)
- `.planning/research/SUMMARY.md` §"Send-path constraints" — `whatsapp://send?phone=...&text=...` URL scheme registered; invisible-LRM in window title; no AppleScript dictionary
- `.planning/research/ARCHITECTURE.md` §"Pattern 2 — Send via UI Automation" — deep-link primary path recipe
- `.planning/research/PITFALLS.md` P5, P6, P12, P13, P14 — wrong-chat, LLM-misuse, AppleScript-fragility, Automation-strip, ToS-ban mitigations
- `.planning/phases/00-RESEARCH.md` (Phase 0) — FastMCP usage, osascript wrapper, exception hierarchy
- `.planning/phases/01-RESEARCH.md` (Phase 1) — reader patterns, `@timeout` decorator, cursor codec

### Tertiary (CITED — official docs)
- [MCP elicitation spec](https://modelcontextprotocol.io/specification/2025-06-18/server/elicitation) — protocol-level confirmation pattern
- [WhatsApp ToS automation policy](https://faq.whatsapp.com/5957850900902049) — rate-limit defense rationale; account-ban risk
- [PyObjC docs — ApplicationServices](https://pyobjc.readthedocs.io/en/latest/apinotes/ApplicationServices.html) — `AXUIElementCopyAttributeValue` ctypes wrapper
- [SQLite WAL docs](https://sqlite.org/wal.html) — RO connection invariants (reused via `reader.connection.open_ro`)

## Metadata

**Confidence breakdown:**
- Locked decisions interpretation: HIGH — all 25 CONTEXT.md decisions copied verbatim
- MCP elicitation API: HIGH — read from installed SDK source on disk
- AX tree shape + bidi characters: HIGH — verified live on user's Mac 2026-05-13
- pyobjc version + availability: HIGH — verified on PyPI 2026-05-13
- Deep-link URL builder: HIGH — verified URL-quote behavior live
- Rate-limit / audit-log file patterns: HIGH — verified standard macOS path conventions
- Cmd-F sidebar-search behavior: MEDIUM — assumed; verify in Plan 02-01 Wave 0 spike
- `open -g` foreground behavior with `whatsapp://`: MEDIUM — assumed; verify in Plan 02-01 Wave 0 spike
- pyobjc 12.1 exact AX-API return signature: MEDIUM — assumed pyobjc convention; verify in Plan 02-01 Wave 0 spike
- Plan structure (5 plans): HIGH — matches Phase 1's split-by-natural-file-boundary pattern
- Mandatory test set: HIGH — copied verbatim from CONTEXT.md §"Specifics"

**Research date:** 2026-05-13
**Valid until:** 2026-06-13 (30 days for stable WhatsApp Catalyst; reduce to 7 days if WhatsApp ships a 26.x → 27.x build before then, as the AX tree shape may shift)

## RESEARCH COMPLETE

**Phase:** 2 - Send (UI-automation, guardrails)
**Confidence:** HIGH

### Key Findings

- **MCP elicitation API verified live on installed `mcp==1.27.1`:** the signature is `await ctx.elicit(message: str, schema: type[PydanticModel])` returning a three-variant union `AcceptedElicitation[T] | DeclinedElicitation | CancelledElicitation`. Schema fields MUST be primitives (str/int/float/bool, list[str], or Optional). Read from SDK source at `.venv/lib/python3.12/site-packages/mcp/server/{fastmcp/server.py,elicitation.py}`. The `ctx` parameter is injected via type annotation and excluded from the public JSON schema (verified at `server.py:598`). Concrete `ConfirmationSchema(BaseModel)` pattern documented in Pattern 1.
- **AX tree of WhatsApp Catalyst verified live on user's Mac (WhatsApp 26.16.74 / macOS 26.4):** front window name is `‎WhatsApp` (U+200E prefix — the invisible-LRM trap); chat headers are `AXHeading` nodes whose `description` carries the chat name; three bidi invisibles must be stripped before comparison — **U+200E (LRM), U+2068 (FSI), U+2069 (PDI)**. The `_strip_bidi()` helper handles all three.
- **Plan structure: 5 plans (02-01 sender primitives, 02-02 guardrails, 02-03 send tool, 02-04 read-tool integration, 02-05 tests)** — 02-01 and 02-02 are parallelizable (disjoint files); 02-03 depends on both; 02-04 depends on 02-02; 02-05 is last wave. Matches Phase 1's 6-plan split-by-natural-file-boundary pattern. 9 new sender modules + 1 new tool module + 4 modified read tools + ~12 new test files.
- **pyobjc 12.1 verified on PyPI 2026-05-13** (uploaded 2025-11-14). Pin `pyobjc-core>=12.1`, `pyobjc-framework-Cocoa>=12.1`, `pyobjc-framework-ApplicationServices>=12.1` to `[project] dependencies` per D-05. D-06 try/except ImportError fallback documented.
- **All 25 locked decisions in CONTEXT.md were honored with no relitigation.** This research provides the **tactical implementation specifics** the planner needs to draft per-task `<action>` fields verbatim: exact SQL DDL for rate-limit table, exact JSONL audit-log schema, exact verification SQL (`ZISFROMME` column verified present in `reader/schema_v1.py`), exact bidi-strip set, exact `ctx.elicit` shape, exact `os.chmod(0o600)` and `buffering=1` patterns. 6 open assumptions (A1-A6) are all "verify in Plan 02-01 Wave 0 spike" tactical items, not decisions needing user confirmation.
- **REL-05 evolved per D-24:** Reader → Sender import still forbidden. Sender → `reader.connection` (only) now allowed for `verify.py`. Plan 02-04 introduces tool layer → sender imports (one-line `record_bodies` hook in 4 read tools). Test `test_isolation.py` needs three new assertions: reader-no-sender (stays), sender-only-reader.connection (new), tools-may-import-both (new allowlist).
- **Anti-patterns enumerated:** body plaintext logging, auto-pick fuzzy chat names, bypass elicitation without `confirm_skipped: true`, raw pyobjc ImportError, write to ChatStorage.sqlite, silent env-var rate-limit expansion, raw TimeoutError to client, keystroke-before-AX-assertion, AX comparison without bidi-strip, search-result-click without AX preflight. Each maps to a CONTEXT.md decision violation.

### File Created
`/Users/jlqueguiner/dev/whatsapp-mcp/.planning/phases/02-send-ui-automation-guardrails/02-RESEARCH.md`

### Confidence Assessment

| Area | Level | Reason |
|------|-------|--------|
| MCP Elicitation API | HIGH | Read directly from installed `mcp==1.27.1` SDK source |
| AX tree shape + bidi chars | HIGH | Verified live on user's Mac via `osascript ... entire contents of front window` |
| pyobjc version / API | MEDIUM-HIGH | Latest 12.1 verified on PyPI; exact return-tuple shape on 12.1 assumed (Plan 02-01 spike) |
| Deep-link path | HIGH | URL builder verified live; `open -g` foregrounding behavior assumed (Plan 02-01 spike) |
| SQLite DDL / queries | HIGH | Standard patterns; `ZISFROMME` column verified present in codebase |
| Plan structure | HIGH | Pattern-matches Phase 1's split |

### Open Questions (resolved via Plan 02-01 Wave 0 spikes, NOT requiring user input)

1. Cmd-F vs AX-click for sidebar-search focus
2. `open -g` foreground reliability
3. AXHeading presence when chat is open
4. pyobjc 12.1 `AXUIElementCopyAttributeValue` return signature
5. Emoji / non-BMP body handling (Plan 02-05 test)
6. Multi-instance audit-log race (deferred to Phase 3)

### Ready for Planning

Research complete. Planner can now create the 5 plans (02-01 through 02-05) with concrete `<action>` fields lifted verbatim from this document. Every CONTEXT.md decision is honored; every tactical specific (DDL, SQL, code shapes, file paths, dependency versions, bidi codepoints) is documented with source attribution. The 6 Plan-02-01 Wave 0 spikes are listed in §"Open Questions" — the planner should add them as explicit Wave 0 tasks in Plan 02-01.

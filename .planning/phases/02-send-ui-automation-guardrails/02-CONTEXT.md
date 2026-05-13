# Phase 2: Send (UI-automation, guardrails) - Context

**Gathered:** 2026-05-13
**Status:** Ready for planning
**Mode:** auto (decisions selected via recommended-default; review before /gsd-plan-phase)

<domain>
## Phase Boundary

Deliver one MCP tool — `send_message` — that drives WhatsApp Desktop on macOS to send a single text message to a chat that the LLM has previously resolved to an opaque `chat_id` via Phase 1's `search_contacts` / `list_chats`. Every send is gated by an MCP elicitation confirmation that displays the resolved chat name + recipient JID/LID + body verbatim; throttled by a persistent rate limiter (5/min, 30/day default); appended to a structured audit log; verified post-hoc by polling `ZWAMESSAGE` for the corresponding outgoing row; and protected by an Accessibility-API state assertion that confirms the focused window's chat header matches the resolved name before any keystroke fires.

User-visible value: from Claude Desktop, the user asks Claude to send a message to a real WhatsApp contact, sees the elicitation confirmation, approves it, and the message is delivered through the running WhatsApp.app — same path the user would take manually, with structural defenses against fan-out, wrong-chat, prompt-injection, and ToS-violation classes of misuse.

In scope: SEND-01 (opaque chat_id only), SEND-02 (MCP elicitation), SEND-03 (deep-link primary path), SEND-04 (AX-API state assertion), SEND-05 (rate limiter), SEND-06 (audit log), SEND-07 (cross-chat-quote heuristic), SEND-08 (post-hoc DB verification).

Out of scope (this phase): media sends (v2 — SEND2-01), draft+confirm preview (v2 — SEND2-02), reactions/polls/edit/delete (v2 — SEND2-03), full Accessibility-API send replacing keystroke (v2 — SEND2-04), group send via deep-link (deferred — WhatsApp doesn't support group JIDs in URL scheme), bulk/broadcast send (anti-feature, never), scheduled send (anti-feature, never), auto-reply loop (anti-feature, never).

</domain>

<decisions>
## Implementation Decisions

### Send Mechanism
- **D-01:** **1:1 sends use the deep-link primary path.** `subprocess.run(["open", "-g", "whatsapp://send?phone=<E164>&text=<urlencoded_body>"], timeout=5)` opens the chat in WhatsApp.app with the message pre-filled. After the open, a brief deterministic settle (poll for window title containing "WhatsApp" via `osascript ... tell application "System Events" to get name of front window of process "WhatsApp"` with up to 1.5s timeout) confirms the app is foreground; then `osascript -e 'tell application "System Events" to keystroke return'` fires the send. The `-g` flag keeps WhatsApp from grabbing focus aggressively (it still comes forward but doesn't steal Cmd-Tab order on activation).
- **D-02:** **Group sends use the search-and-click fallback.** WhatsApp's `whatsapp://send` URL scheme does NOT accept `@g.us` group JIDs (verified in research). For groups, the sender drives the `New Chat` search box via UI scripting: open WhatsApp window, focus search field via Cmd-N or AX path, type the resolved chat name, click the first result with matching display name, then keystroke the body + return. Mark group sends with `is_experimental=true` in the tool result so callers know the brittleness budget. If search-and-click proves unstable in execution-time spike, defer group send to v1.1 with the documented deviation.
- **D-03:** **AX-API state assertion preflight before EVERY send (1:1 and group).** Use pyobjc to read the focused WhatsApp window's chat header (`AXTitle` of the topmost `AXGroup` containing the conversation pane). Compare to the resolved chat name. If the header doesn't match, abort with a structured `ChatHeaderMismatch` error and never fire keystroke. This is the load-bearing P5 / wrong-chat-fuzzy-send mitigation. Defends against the invisible-LRM character trap (verified live on user's Mac).
- **D-04:** **No raw Accessibility-API send path in v0.1.** SEND-04 mandates the state assertion ONLY; the actual keystroke still goes through `osascript ... keystroke return`. Replacing the keystroke with `AXTextArea.setValue:` + `AXButton "Send" AXPress` is v2 work (SEND2-04) — defer because the AX send path needs WhatsApp UI mapping that may break across Catalyst minor versions and the keystroke approach is well-understood.

### PyObjC Dependency
- **D-05:** **Add `pyobjc-core>=12.1`, `pyobjc-framework-Cocoa>=12.1`, `pyobjc-framework-ApplicationServices>=12.1` to `[project] dependencies` (NOT `[project.optional-dependencies] dev`).** Required at runtime for the AX state assertion (D-03). Adds ~30 MB to the wheel; that's the cost of having a working SEND-04 mitigation. Alternative — defer pyobjc and ship a known-broken P5 mitigation — is not acceptable given the account-ban consequences.
- **D-06:** **Wrap pyobjc imports in `try/except ImportError` at the sender module level** so the package still imports on systems without pyobjc installed (CI macos-14 has it; an unfortunate user mis-install shouldn't crash the whole MCP server). On import failure, `send_message` returns a structured `AccessibilityAPIUnavailable` error; the read tools keep working.

### Confirmation UX
- **D-07:** **MCP elicitation confirmation is ALWAYS-ON by default.** Every `send_message` call triggers an elicitation prompt that displays:
  - Resolved chat display name
  - Recipient JID/LID (formatted with the kind tag)
  - Message body verbatim (no truncation; if body > 1000 chars, the elicitation shows full body anyway — sending a long message deserves a long confirmation)
  - Cross-chat-quote warning (if D-12 heuristic fires)
  - Rate limit budget remaining (e.g., "4/5 sends remaining this minute, 28/30 today")
- **D-08:** **Opt-out via `WHATSAPP_MCP_SKIP_CONFIRM=1` env var.** When set: elicitation is skipped, send proceeds, BUT every skipped confirmation is logged to the audit log with `confirm_skipped: true`. Documented in README with a stark warning about prompt-injection consequences.
- **D-09:** **No sticky-session confirmation cache.** "Confirmed once, OK for the next N sends to this chat" defeats the per-send safety. Each send gets its own confirmation.
- **D-10:** **Decline = clean cancellation.** When the user declines the elicitation, `send_message` returns a structured `SendCancelled` result (NOT an error — the user's choice is the success case). Audit log entry `outcome: "cancelled"`.

### Rate Limiter
- **D-11:** **Persistent SQLite-backed rate limiter at `~/Library/Application Support/whatsapp-mcp/rate-limit.db` (mode 0600).** Single file; one append-only `sends(ts INTEGER, chat_id INTEGER, body_sha256 TEXT, outcome TEXT)` table. Sliding-window query on `ts`: `SELECT COUNT(*) FROM sends WHERE ts > now-60` and `WHERE ts > now-86400`. Persistent because a server restart MUST NOT bypass the daily limit — the WhatsApp account is the protected resource and it doesn't restart with the MCP. Defaults: 5/min, 30/day. Configurable via env vars `WHATSAPP_MCP_RATE_PER_MIN` / `WHATSAPP_MCP_RATE_PER_DAY` (must NOT silently expand the defaults — both bounded by hard maximums of 20/min and 200/day respectively, beyond which the env var is rejected with a structured config error).

### Audit Log
- **D-12:** **JSONL at `~/Library/Logs/whatsapp-mcp/audit.log` mode 0600.** One JSON object per send attempt:
  ```json
  {"ts": 1778660000, "chat_id": 30, "chat_name": "Café",
   "body_sha256": "a1b2...", "outcome": "sent|cancelled|rate_limited|error",
   "message_id": "ABCDEF" | null, "error": "ChatHeaderMismatch" | null,
   "confirm_skipped": false, "elapsed_ms": 1240}
  ```
- **D-13:** Body itself is NEVER logged (only the SHA-256 fingerprint). Reasoning: the audit log is for ban-recovery investigation, rate-limit tuning, and detecting compromise — none of which need plaintext bodies, all of which leak privately if the log file is exfiltrated. SHA-256 lets an investigator confirm "yes, the body the user claimed was sent matches what we sent" without storing the body itself.
- **D-14:** **Append-only, line-buffered, no log rotation in v0.1.** The file grows; users who care can `truncate` it manually or wait for Phase 3 to add rotation. Phase 2 doesn't ship a daemon, so no automatic rotation.

### Cross-Chat-Quote Heuristic (SEND-07)
- **D-15:** **Session-scoped source-attribution table.** Every read tool (`read_chat`, `extract_recent`, `search_messages`, `get_message_context`) records returned message bodies with their source `chat_id` and timestamp into a process-local LRU (max 1000 entries, ~30 min sliding window). Implementation: `whatsapp_mcp/sender/cross_chat_quote.py` with a `record(chat_id, body)` write API the read tools call AND a `check(target_chat_id, outgoing_body) -> list[OffendingSource]` read API the send tool calls during confirmation construction.
- **D-16:** **Match threshold: ≥ 40-character contiguous substring** belonging to a different chat_id within the 30-min window. Below 40 chars, false positives on common phrases dominate. Above 80, the obvious "I'm copying that thing from the other chat" case slips through.
- **D-17:** **In-memory only — no persistence.** Reset on server restart. The heuristic is prompt-injection defense for the active session; a restart implies a fresh trust context.
- **D-18:** **Surface as a WARNING in the elicitation, not a HARD BLOCK.** The user may legitimately be forwarding a quote between chats. The warning shows `Body contains a 47-char run from chat "Work" — confirm cross-chat reference is intentional.` The user accepts or declines.

### --read-only Interaction
- **D-19:** **`send_message` checks `whatsapp_mcp.server.read_only_mode` at the top of its body and raises `ReadOnlyMode` exception (Phase 1 minted) if True.** v0.1 default for the flag stays `True` (conservative); user must explicitly `uvx whatsapp-mcp --no-read-only` to enable sends. README documents this.
- **D-20:** **Tool annotations: `@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True), meta={"anthropic/maxResultSizeChars": 60000})`.** `destructiveHint=True` is the MCP signal that calling this tool changes external state. `readOnlyHint=False` distinguishes it from the 8 Phase 0/1 tools.

### Post-Hoc Verification (SEND-08)
- **D-21:** **Polling pattern: 250 ms intervals, up to 10 s wall-clock total (40 polls).** Query: `SELECT ZSTANZAID, ZMESSAGEDATE FROM ZWAMESSAGE WHERE ZCHATSESSION=:cid AND ZISFROMME=1 AND ZTEXT=:body AND ZMESSAGEDATE > :send_started_cocoa ORDER BY ZSORT DESC LIMIT 1`. First match wins; return `ZSTANZAID` as `message_id`.
- **D-22:** **Verification timeout returns `outcome="sent_unverified"` (NOT "error").** WhatsApp.app may sync the send to its DB after the 10 s window — especially over a slow network. The audit log records `outcome="sent_unverified"`; the tool result returns `{"status": "sent_unverified", "message_id": null, "verification_note": "..."}`. The send is observably in the WA UI; we just couldn't confirm via DB in our window.

### Sender Package Layout
- **D-23:** **Files under `src/whatsapp_mcp/sender/`:**
  - `deeplink.py` — `whatsapp://send` URL builder + `open` subprocess wrapper
  - `osascript_send.py` — keystroke-return wrapper with timeout
  - `ax_assert.py` — pyobjc-based focused-window-header probe
  - `ui_send.py` — orchestrates deep-link OR search-and-click + AX assertion + keystroke (the unified send path)
  - `verify.py` — post-hoc DB poll (uses `whatsapp_mcp.reader.connection.open_ro` — this IS allowed because the integration point is the tool layer, but the sender needs DB read for verification; lock the import direction: `sender/verify.py` imports `reader.connection`, NOT vice versa, so REL-05 stays one-way)
  - `rate_limit.py` — SQLite rate limiter
  - `audit.py` — JSONL audit log writer
  - `cross_chat_quote.py` — heuristic + read-tool integration hooks
  - `__init__.py` — re-export public functions: `send_text(chat_id, body) -> SendResult`
- **D-24:** **REL-05 EVOLUTION:** Phase 1 said "Reader and Sender MUST NOT import each other." Phase 2 needs `sender/verify.py` to use `reader.connection.open_ro`. The cleanest evolution: REL-05 becomes "Reader MUST NOT import Sender. Sender MAY import Reader connection primitives only (NOT reader.tools or reader business logic)." Update `tests/unit/test_isolation.py` accordingly: `test_isolation_reader_does_not_import_sender` stays load-bearing; `test_isolation_sender_does_not_import_reader` is RELAXED to assert sender imports ONLY `reader.connection` — no other reader module. Phase 0/1 sender was empty, so this is the first time the constraint actually has bite.

### Tool Layer
- **D-25:** **`src/whatsapp_mcp/tools/send_message.py`** — `@mcp.tool(...)` async function. Body:
  1. Check `read_only_mode` → raise `ReadOnlyMode`.
  2. Validate `chat_id` exists via `reader.list_all` lookup → raise `InvalidChatId` if not found (SEND-01: "passing a free-form name string returns InvalidChatId" — chat_id is opaque int validated against reader; planner should generate test that passes a string → 422 / structured error).
  3. Resolve chat name + recipient JID/LID from reader.
  4. Build cross-chat-quote warnings.
  5. Check rate limit → raise `RateLimitExceeded` if over budget.
  6. MCP elicitation prompt (unless `WHATSAPP_MCP_SKIP_CONFIRM=1`); on decline → `SendCancelled`.
  7. AX state assertion → raise `ChatHeaderMismatch` on focus mismatch.
  8. Drive send (deep-link OR search-and-click).
  9. Post-hoc DB poll for verification (D-21).
  10. Append audit log entry.
  11. Return `SendResult { status, message_id, verification_note, rate_limit_remaining, audit_log_path }`.

### Threat Model (high-level — planner should expand per-task)
- **T-1 (account ban via fan-out):** rate limiter (D-11) + no multi-recipient tool + audit log + 30/day default cap (well under WhatsApp's anti-spam threshold per RESEARCH P14).
- **T-2 (wrong-chat fuzzy send):** opaque chat_id only (no name strings) + AX state assertion (D-03) + ChatHeaderMismatch abort + invisible-LRM-aware comparison.
- **T-3 (prompt injection through user-authored chat content):** description-content invariant on every read tool (Phase 1) + cross-chat-quote heuristic (D-15..18) + always-on confirmation (D-07).
- **T-4 (audit log tampering / privacy leak):** mode 0600 + body SHA-256 only (D-13) + append-only.
- **T-5 (rate-limit bypass via restart):** persistent SQLite (D-11).
- **T-6 (TCC permission slip — Automation revoked between server start and send):** doctor probe at every send entry (sub-100 ms) re-checks Automation; if denied, return structured `AutomationRevoked` and audit log it.

### Claude's Discretion
- AX-API exact selectors for the focused chat header (the `AXTitle` walk depth, fallback selectors if the obvious one is missing on a specific Catalyst version).
- Exact wording of the elicitation prompt's body display (must show body verbatim; framing is Claude's call).
- Whether to add `WHATSAPP_MCP_DRY_RUN=1` env var that walks the entire pipeline up to but not including the keystroke and returns a `dry_run_result` — a useful debugging mode the user might appreciate, not strictly required.
- Whether to ship a tiny `whatsapp-mcp send-test` CLI subcommand for manual smoke testing without going through Claude Desktop.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project decisions
- `.planning/PROJECT.md` — core value, constraints, key decisions
- `.planning/REQUIREMENTS.md` — Phase 2 owns SEND-01..08
- `.planning/ROADMAP.md` §"Phase 2" — goal + 5 success criteria
- `.planning/STATE.md` — current state

### Live-verified domain facts (do NOT re-research)
- `.planning/research/SUMMARY.md` §"Send-path constraints" — no AppleScript dictionary, deep-link works for 1:1, invisible-LRM trap
- `.planning/research/ARCHITECTURE.md` §"Send path"
- `.planning/research/PITFALLS.md` — P5, P6, P12, P13, P14 all own Phase 2
- `.planning/research/STACK.md` — pyobjc dep notes

### Phase 1 inheritance (loaded by sender)
- `src/whatsapp_mcp/exceptions.py` — `ReadOnlyMode` (Phase 1 mint, Phase 2 raises); `PermissionRequired` hierarchy
- `src/whatsapp_mcp/server.py` — `mcp` instance + `read_only_mode` module state
- `src/whatsapp_mcp/reader/connection.py` — `open_ro` context manager (used by `sender/verify.py` per relaxed REL-05 D-24)
- `src/whatsapp_mcp/permissions/automation.py` — D-09 patched probe (used by send-time TCC re-check)
- `src/whatsapp_mcp/paths.py` — `resolve_chatstorage_path`, `system_settings_url`
- `src/whatsapp_mcp/time.py` — `unix_to_cocoa` for the post-hoc DB poll predicate

### External
- WhatsApp URL scheme — `whatsapp://send?phone=<E164>&text=<urlencoded>` (1:1 only)
- WhatsApp ToS — https://faq.whatsapp.com/5957850900902049 (automation prohibition; rate-limit defense rationale)
- macOS Accessibility API (PyObjC) — `pyobjc-framework-ApplicationServices` for `AXUIElementCopyAttributeValue`, `kAXTitleAttribute`, `kAXFocusedWindowAttribute`
- MCP elicitation spec — https://modelcontextprotocol.io/specification/2025-06-18/server/elicitation
- Project guide: `CLAUDE.md` — REL-05 (now D-24 evolved), stdout=JSON-RPC, no HTTP

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `whatsapp_mcp.permissions.osascript.run_osascript` (Phase 0) — async wrapper around `osascript -e <script>`. Reuse for `keystroke return` and any AX-via-osascript fallback.
- `whatsapp_mcp.permissions.automation` (Phase 0, D-09 patched) — `id of application "WhatsApp"` probe. Reuse for the per-send TCC re-check (T-6).
- `whatsapp_mcp.reader.connection.open_ro` (Phase 1) — async RO context manager. `sender/verify.py` calls this for the post-hoc poll (REL-05 evolution per D-24).
- `whatsapp_mcp.time.unix_to_cocoa` (Phase 1) — converts Unix → Cocoa for the `ZMESSAGEDATE > :send_started_cocoa` predicate.
- `whatsapp_mcp.exceptions.ReadOnlyMode` (Phase 1) — raised by `send_message` when server.read_only_mode is True.
- `whatsapp_mcp.exceptions.PermissionRequired` hierarchy (Phase 0) — re-raised when Automation TCC is revoked mid-session (T-6).
- `whatsapp_mcp.paths.resolve_chatstorage_path` + `system_settings_url` (Phase 0/1) — for `ChatHeaderMismatch` / `AutomationRevoked` error payloads.
- `tools/_decorators.py @timeout` (Phase 1) — wrap `send_message` with 15 s timeout per REL-03.

### Established Patterns
- `tools/__init__.py` import side-effect registration — Phase 2 adds `from . import send_message` here.
- `@mcp.tool(annotations=ToolAnnotations(...), meta={"anthropic/maxResultSizeChars": 60000})` — uniform annotation pattern.
- Async-throughout: every tool is `async def`; subprocess calls go through `asyncio.create_subprocess_exec`; SQLite reads via `asyncio.to_thread` (REL-02 inherited).
- Structured errors over raw exceptions to client: `tools/_decorators.py` already maps known exception subclasses to structured MCP error payloads.

### Integration Points
- WhatsApp.app local UI (deep-link, keystroke, AX-API) — process-level integration with the macOS-resident Catalyst app; same trust boundary as the user shell.
- WhatsApp's `ChatStorage.sqlite` (read-only via `open_ro`) — Phase 2 reads but never writes.
- macOS TCC (Automation, Accessibility) — both required at runtime; doctor's existing probes already cover detection.
- MCP elicitation API on the client side (Claude Desktop) — `ctx.elicit(prompt, schema)` per the SDK's `mcp.types.ElicitRequestParams`.

</code_context>

<specifics>
## Specific Ideas

- The 4 mandatory regression tests Phase 2 ships:
  - `test_send_message_refuses_string_chat_id` (SEND-01 contract)
  - `test_send_message_aborts_on_chat_header_mismatch` (D-03 / SEND-04 / P5)
  - `test_send_message_rate_limit_persists_across_restart` (D-11 / SEND-05)
  - `test_send_message_appends_audit_log_with_body_sha256_not_body` (D-13 / SEND-06)
- README addition: a "Sending Messages" section with a stark "WhatsApp can ban your account for automation; the rate limits are deliberately conservative; do not raise them blindly" callout.
- The `send_message` body MUST log latency from start-to-keystroke and start-to-verified, not just total time, so a slow AX assertion vs a slow WA sync are separable in audit log analysis.

</specifics>

<deferred>
## Deferred Ideas

- **Send media (images/files)** — v2 (SEND2-01); AppleScript drag-drop fragile across versions
- **Draft + confirm preview** — v2 (SEND2-02); MCP elicitation is sufficient for v0.1 confirmation
- **Reactions / polls / edit / delete** — v2 (SEND2-03); each requires a different UI path
- **Full Accessibility-API send path** (replacing `keystroke return` with `AXTextArea.setValue:` + `AXButton.AXPress`) — v2 (SEND2-04); the AX preflight assertion (D-03) is sufficient for v0.1 P12 mitigation
- **Group send via deep-link** — v2 (SEND2-05); requires WhatsApp to add group JID support to URL scheme; out of our control
- **Audit log rotation** — Phase 3 alongside other ops polish
- **`whatsapp-mcp send-test` CLI subcommand** — Claude's discretion; nice-to-have
- **`WHATSAPP_MCP_DRY_RUN=1` env var** — Claude's discretion; would help with debugging

</deferred>

---

*Phase: 2-Send (UI-automation, guardrails)*
*Context gathered: 2026-05-13*

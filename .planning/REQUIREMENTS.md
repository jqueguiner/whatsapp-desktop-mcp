# Requirements: WhatsApp MCP

**Defined:** 2026-05-13
**Core Value:** An LLM agent can read and write the user's WhatsApp Desktop the same way the user can — no separate auth, no API key, no business approval — through a small set of MCP tools.

## v1 Requirements

### Setup & Permissions

- [ ] **SETUP-01**: MCP server installs via a single line in `claude_desktop_config.json` (`uvx whatsapp-mcp` for dev / `whatsapp-mcp` from a stable path for end-user)
- [x] **SETUP-02**: Server runs as an MCP stdio server and registers with Claude Desktop / Claude Code without protocol errors *(satisfied by Plan 03 — `whatsapp_mcp.server.mcp = FastMCP("whatsapp-mcp")` + `run()` dispatcher from Plan 02 + `doctor` tool registered by Plan 03 means `mcp.list_tools()` returns exactly one Tool named `doctor` with `readOnlyHint=True`; full Claude-Desktop registration smoke test lands with Plan 04's `test_stdout_purity.py` exercising `initialize → tools/list → tools/call doctor`)*
- [x] **SETUP-03**: All logging goes to stderr; stdout is reserved exclusively for JSON-RPC frames (CI test enforces purity; ruff `T201` blocks `print`) *(scaffolded by Plan 02 — `logging.basicConfig(stream=sys.stderr, ...)` is the first executable statement in `server.py`; `import whatsapp_mcp` and `from whatsapp_mcp.server import mcp` both emit zero stdout bytes; T201 is wired in pyproject.toml since Plan 01; CI test lands in Plan 04)*
- [x] **SETUP-04**: Missing macOS permission produces a structured error (`FullDiskAccessRequired`, `AutomationPermissionRequired`, `AccessibilityPermissionRequired`) naming the exact binary path to grant and a `x-apple.systempreferences:` deep-link *(satisfied by Plan 03 — `doctor` tool returns a structured `DoctorReport` whose `PermissionStatus` payloads carry `binary_path = sys.executable`, `db_path` (FDA only) from `paths.resolve_chatstorage_path()`, `system_settings_url` from the matching exception class attribute (single source of truth, D-11), and a one-line `remediation` string for any non-granted state. Empirically corrected D-09 PATCHED Automation probe `id of application "WhatsApp"` is in source. Phase 1's read tools will raise the matching `*Required` exception classes on real failures.)*
- [ ] **SETUP-05**: README documents WhatsApp ToS automation risk, account-ban thresholds, and "this is your personal account, not a bot" framing
- [ ] **SETUP-06**: `--read-only` startup flag disables every send tool and marks all remaining tools `readOnlyHint:true`

### Read

- [ ] **READ-01**: Tool `list_chats` returns groups + 1:1 chats with last-activity timestamp, unread count, kind (1:1/group/broadcast/community), and a `coverage` window naming the time range present in the local DB
- [ ] **READ-02**: Tool `read_chat` returns messages from a specific chat by `chat_id`, bounded by `limit` (default 200, max enforced by char-cap) OR by `before`/`after` timestamps, with `cursor`/`next_cursor` pagination
- [ ] **READ-03**: Tool `extract_recent` returns all messages from a `chat_id` within the last N hours; response includes `coverage` ("asked Xh, have Yh")
- [ ] **READ-04**: Tool `search_messages` performs full-text search across chats with optional `chat_id`, sender, and date filters; LIKE acceptable for v0.1, FTS5 shadow index for v1.0
- [ ] **READ-05**: Tool `search_contacts` finds chats/contacts by name or phone fragment, deduplicating across `@s.whatsapp.net` and `@lid` representations of the same person
- [ ] **READ-06**: Tool `get_chat_metadata` returns group description, member list (with display names and admin flags), mute status — for groups and 1:1s
- [ ] **READ-07**: Tool `get_message_context` returns N messages before/after a `message_id`, plus the parent message if the target is a quote-reply (uses `ZPARENTMESSAGE` self-join)
- [ ] **READ-08**: All read tools default `include_deleted=False`; tombstoned messages (`ZMESSAGETYPE=14`, deleted-for-everyone, deleted-for-me bit-flagged) are filtered unless caller opts in
- [ ] **READ-09**: All read tool responses fit within MCP's per-result size cap (~60k chars); larger results paginate via opaque cursor; `_meta["anthropic/maxResultSizeChars"]` annotation set on every read tool

### Data Contracts

- [ ] **DATA-01**: All tool returns are JSON conforming to a locked Pydantic schema for `Message`, `Chat`, `Contact`, `GroupInfo`, `MediaRef`, `Jid` (kind-tagged: `phone` / `lid` / `group`)
- [ ] **DATA-02**: Each `Message` includes `message_id` (`ZSTANZAID`), `chat_id`, `sender_jid`, `timestamp` (Unix seconds, converted from Cocoa epoch), `body`, `kind` (text/media/system/etc), `is_outgoing`, `quoted_message_id` (nullable)
- [ ] **DATA-03**: Attachments are surfaced as `MediaRef` with `filename`, `mime`, `local_path` (absolute), `size_bytes` — never inlined as binary in tool responses
- [ ] **DATA-04**: Encrypted/protobuf BLOB columns (`ZMEDIAKEY`, `ZMETADATA`, `ZRECEIPTINFO`) are NOT parsed in v1; surfaced as opaque or omitted

### Send

- [ ] **SEND-01**: Tool `send_message` sends a text-only message to one recipient identified by an opaque `chat_id` previously returned by `search_contacts` or `list_chats` (never a free-form name string)
- [ ] **SEND-02**: Send is annotated `destructiveHint:true` and gated by MCP elicitation confirmation by default; confirmation displays resolved chat name + recipient JID + body verbatim
- [ ] **SEND-03**: Primary send path is `whatsapp://send?phone=<E164>&text=<urlencoded>` deep-link + `osascript` keystroke return; group-chat fallback is a search-and-click sequence with documented brittleness
- [ ] **SEND-04**: Pre-send AX-API state assertion verifies the focused window's chat header matches the resolved chat name (aborts on mismatch; returns structured error)
- [ ] **SEND-05**: Conservative rate limiter active by default: 5 sends/min, 30 sends/day; configurable; rate-limit hit returns structured error, never silently drops
- [ ] **SEND-06**: Every send attempt (success or failure) is appended to an audit log at `~/Library/Logs/whatsapp-mcp/audit.log` (mode 0600) with timestamp, resolved chat_id + name, body hash, outcome
- [ ] **SEND-07**: Cross-chat-quote heuristic detects when the body to send contains content recently quoted from another chat; surfaces a warning in the confirmation prompt
- [ ] **SEND-08**: Send is verified post-hoc by polling `ZWAMESSAGE` for a new outgoing row matching the body within 10s; success returns the resulting `message_id`

### Reliability & Concurrency

- [ ] **REL-01**: SQLite reader uses short-lived connections opened with `?mode=ro` URI flag (never `immutable=1`); reads succeed concurrently with WhatsApp's writer
- [ ] **REL-02**: All DB calls wrapped in `asyncio.to_thread`; all `osascript` calls via `asyncio.create_subprocess_exec` + `asyncio.wait_for(timeout=10)`; the stdio event loop never blocks
- [ ] **REL-03**: Per-tool timeouts enforced: `read_chat` 5s, `search_messages` 10s, `send_message` 15s
- [ ] **REL-04**: Schema fingerprint (`Z_METADATA.Z_VERSION`) probed at startup; out-of-range version returns a degraded-mode warning from `doctor` rather than crashing read tools
- [ ] **REL-05**: Reader and Sender modules MUST NOT import each other; tool layer is the only integration point

### Diagnostics

- [ ] **DIAG-01**: Tool `doctor` returns a structured preflight report covering: DB path resolved, FDA granted, Automation granted, Accessibility granted, schema fingerprint OK, WhatsApp.app version detected, last-message timestamp, `coverage` summary
- [ ] **DIAG-02**: `doctor` is callable even when other tools would fail (it is the diagnosis path)

### Distribution

- [ ] **DIST-01**: Project is published to PyPI as `whatsapp-mcp`, installable via `uvx whatsapp-mcp` for developers
- [ ] **DIST-02**: Project ships an end-user install path that puts the launcher binary at a stable absolute path (so TCC permissions persist across upgrades) — Developer-ID-signed `.pkg` and/or Homebrew formula
- [ ] **DIST-03**: README includes platform requirements (macOS only, WhatsApp Desktop Catalyst build, Python 3.12+ if user-installed) and a 60-second quickstart

## v2 Requirements

### Send (extended)

- **SEND2-01**: Send media (images/files) via AppleScript drag-drop or pasteboard
- **SEND2-02**: Draft + confirm flow (preview the rendered message before send)
- **SEND2-03**: Reactions, polls, edit, delete

### Read (extended)

- **READ2-01**: `download_media` tool that returns a path-resolved `MediaRef` and decrypts if needed
- **READ2-02**: FSEvents-based freshness signal so tools know when WhatsApp wrote new rows
- **READ2-03**: `get_last_interaction` per chat
- **READ2-04**: Per-chat mute / archive / pin status surfaced in `list_chats`

### Sender Hardening

- **SEND2-04**: Replace raw `keystroke` with full Accessibility API path (`AXTextArea` find → `setValue:` → `AXButton` `AXPress`) for state-asserting send
- **SEND2-05**: Group-send via deep-link if WhatsApp adds support for group JIDs

### Other

- **OTH2-01**: Cross-platform support (Windows / Linux WhatsApp Desktop)
- **OTH2-02**: Multi-account orchestration (currently locked to single logged-in Desktop session)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Bulk / broadcast / fan-out send | Anti-feature: WhatsApp ToS bans automation; account-ban risk; #1 prompt-injection blast vector |
| Scheduled / delayed send | Requires persistent background process; out of scope for stdio MCP |
| Auto-reply or agent-reaction loop on incoming messages | Different threat model; massive abuse risk; WhatsApp will ban |
| Inline media binary in tool response | Anti-feature: 4MB image ≈ 1.5M tokens; obliterates context window |
| Writing into `ChatStorage.sqlite` | Anti-feature: corrupts WhatsApp's writer; schema can change |
| HTTP REST surface (any TCP/UDP listener) | Anti-feature: `lharries/whatsapp-mcp` was hit by exactly this — path traversal CVE class + unauth LAN exposure |
| Side-effect "mark as read" on `read_chat` | Surprising side effect from a read tool; user may want to read silently |
| WhatsApp Business / Cloud API integration | Defeats the project — user wants personal account |
| WhatsApp Web protocol (whatsmeow / Baileys) | Different architecture; that's `lharries/whatsapp-mcp`'s design, which PROJECT.md rejects |
| Voice / video call control | Out of project scope — text + media metadata only |
| Reactions, polls, status updates | Defer to v2 — each is a different UI path |
| Sending media (images/files) | Defer to v2 — AppleScript drag-drop fragile across versions |
| Cross-platform (Windows/Linux WhatsApp Desktop) | macOS only for v1 |
| Hosting on a remote server | Strictly local; runs on the same Mac as WhatsApp Desktop |
| Bypassing WhatsApp encryption | Anti-feature: only what the logged-in user can already see |

## Traceability

| Requirement | Phase | Phase Name | Status |
|-------------|-------|------------|--------|
| SETUP-01 | Phase 0 | Setup & Permissions Skeleton | Pending |
| SETUP-02 | Phase 0 | Setup & Permissions Skeleton | Satisfied (Plan 03 — `doctor` registered with `readOnlyHint=True`; full Claude-Desktop smoke test pending Plan 04 stdout-purity gate) |
| SETUP-03 | Phase 0 | Setup & Permissions Skeleton | Scaffolded (Plan 02 — stderr-FIRST logging + import-time stdout purity; live CI gate pending Plan 04) |
| SETUP-04 | Phase 0 | Setup & Permissions Skeleton | Satisfied (Plan 03 — structured `DoctorReport` payloads with binary_path + db_path + system_settings_url + remediation per D-11; D-09 PATCHED probe in source) |
| SETUP-05 | Phase 0 | Setup & Permissions Skeleton | Pending |
| DIST-01 | Phase 0 | Setup & Permissions Skeleton | Pending |
| SETUP-06 | Phase 1 | Read MVP (`--read-only`) | Pending |
| READ-01 | Phase 1 | Read MVP (`--read-only`) | Pending |
| READ-02 | Phase 1 | Read MVP (`--read-only`) | Pending |
| READ-03 | Phase 1 | Read MVP (`--read-only`) | Pending |
| READ-04 | Phase 1 | Read MVP (`--read-only`) | Pending |
| READ-05 | Phase 1 | Read MVP (`--read-only`) | Pending |
| READ-06 | Phase 1 | Read MVP (`--read-only`) | Pending |
| READ-07 | Phase 1 | Read MVP (`--read-only`) | Pending |
| READ-08 | Phase 1 | Read MVP (`--read-only`) | Pending |
| READ-09 | Phase 1 | Read MVP (`--read-only`) | Pending |
| DATA-01 | Phase 1 | Read MVP (`--read-only`) | Pending |
| DATA-02 | Phase 1 | Read MVP (`--read-only`) | Pending |
| DATA-03 | Phase 1 | Read MVP (`--read-only`) | Pending |
| DATA-04 | Phase 1 | Read MVP (`--read-only`) | Pending |
| REL-01 | Phase 1 | Read MVP (`--read-only`) | Pending |
| REL-02 | Phase 1 | Read MVP (`--read-only`) | Pending |
| REL-03 | Phase 1 | Read MVP (`--read-only`) | Pending |
| REL-04 | Phase 1 | Read MVP (`--read-only`) | Pending |
| REL-05 | Phase 1 | Read MVP (`--read-only`) | Pending |
| DIAG-01 | Phase 1 | Read MVP (`--read-only`) | Pending |
| DIAG-02 | Phase 1 | Read MVP (`--read-only`) | Pending |
| SEND-01 | Phase 2 | Send (UI-automation, guardrails) | Pending |
| SEND-02 | Phase 2 | Send (UI-automation, guardrails) | Pending |
| SEND-03 | Phase 2 | Send (UI-automation, guardrails) | Pending |
| SEND-04 | Phase 2 | Send (UI-automation, guardrails) | Pending |
| SEND-05 | Phase 2 | Send (UI-automation, guardrails) | Pending |
| SEND-06 | Phase 2 | Send (UI-automation, guardrails) | Pending |
| SEND-07 | Phase 2 | Send (UI-automation, guardrails) | Pending |
| SEND-08 | Phase 2 | Send (UI-automation, guardrails) | Pending |
| DIST-02 | Phase 3 | Hardening & Distribution | Pending |
| DIST-03 | Phase 3 | Hardening & Distribution | Pending |

**Coverage:**
- v1 requirements: 37 total
- Mapped to phases: 37
- Unmapped: 0 ✓
- Phase 0: 6 reqs · Phase 1: 21 reqs · Phase 2: 8 reqs · Phase 3: 2 reqs

**Note on READ-04 (LIKE → FTS5):** The requirement explicitly admits a two-stage implementation (LIKE in v0.1, FTS5 shadow index for v1.0). The REQ is owned by Phase 1 (LIKE ships and unblocks `search_messages` end-to-end); the FTS5 upgrade is Phase 3 implementation work covered by DIST success criterion 4. This avoids splitting one REQ across two phases.

---
*Requirements defined: 2026-05-13*
*Last updated: 2026-05-13 after Phase 0 Plan 03 executed (SETUP-02 + SETUP-04 satisfied; SETUP-03 scaffolded — full satisfaction lands with Plan 04's CI gate; SETUP-01, SETUP-05, DIST-01 still pending Plan 05)*

# Requirements: WhatsApp MCP

**Defined:** 2026-05-13
**Core Value:** An LLM agent can read and write the user's WhatsApp Desktop the same way the user can — no separate auth, no API key, no business approval — through a small set of MCP tools.

## v1 Requirements

### Setup & Permissions

- [x] **SETUP-01**: MCP server installs via a single line in `claude_desktop_config.json` (`uvx whatsapp-desktop-mcp` for dev / `whatsapp-desktop-mcp` from a stable path for end-user) *(satisfied by Plan 05 — `examples/claude_desktop_config.json` is the authoritative 4-line snippet `{"mcpServers": {"whatsapp": {"command": "uvx", "args": ["whatsapp-desktop-mcp"]}}}`; byte-decodable to the same dict as the README's Quickstart step 1 JSON code fence; resolves through `[project.scripts] whatsapp-desktop-mcp = "whatsapp_desktop_mcp.cli:main"` from Plan 01)*
- [x] **SETUP-02**: Server runs as an MCP stdio server and registers with Claude Desktop / Claude Code without protocol errors *(satisfied by Plan 03 — `whatsapp_desktop_mcp.server.mcp = FastMCP("whatsapp-desktop-mcp")` + `run()` dispatcher from Plan 02 + `doctor` tool registered by Plan 03 means `mcp.list_tools()` returns exactly one Tool named `doctor` with `readOnlyHint=True`; full Claude-Desktop registration smoke test lands with Plan 04's `test_stdout_purity.py` exercising `initialize → tools/list → tools/call doctor`)*
- [x] **SETUP-03**: All logging goes to stderr; stdout is reserved exclusively for JSON-RPC frames (CI test enforces purity; ruff `T201` blocks `print`) *(satisfied by Plan 04 — `tests/unit/test_stdout_purity.py` spawns `python -m whatsapp_desktop_mcp` and asserts every stdout line parses as JSON-RPC 2.0 after a full `initialize → notifications/initialized → tools/list → tools/call doctor` handshake; runs in CI as part of `uv run pytest -m "not live"`; ruff T201 wired since Plan 01; combined defence — lint blocks `print` source, runtime test blocks every other stdout-pollution path)*
- [x] **SETUP-04**: Missing macOS permission produces a structured error (`FullDiskAccessRequired`, `AutomationPermissionRequired`, `AccessibilityPermissionRequired`) naming the exact binary path to grant and a `x-apple.systempreferences:` deep-link *(satisfied by Plan 03 — `doctor` tool returns a structured `DoctorReport` whose `PermissionStatus` payloads carry `binary_path = sys.executable`, `db_path` (FDA only) from `paths.resolve_chatstorage_path()`, `system_settings_url` from the matching exception class attribute (single source of truth, D-11), and a one-line `remediation` string for any non-granted state. Empirically corrected D-09 PATCHED Automation probe `id of application "WhatsApp"` is in source. Phase 1's read tools will raise the matching `*Required` exception classes on real failures.)*
- [x] **SETUP-05**: README documents WhatsApp ToS automation risk, account-ban thresholds, and "this is your personal account, not a bot" framing *(satisfied by Plan 05 — README opens with the locked-D-20 ToS automation-risk blockquote (every required clause present: 'WhatsApp's Terms of Service prohibit "automated or bulk messaging"', 'irrecoverable account ban', 'conservative rate limits (5 sends / minute, 30 sends / day) by default', 'you accept the risk by using it', 'personal account, not a bot'); D-21 four-step quickstart ending in the live `doctor` tool call; D-22 framing inline (no 'WhatsApp Business' mention anywhere). 157-line file replacing the Plan-01 stub.)*
- [ ] **SETUP-06**: `--read-only` startup flag disables every send tool and marks all remaining tools `readOnlyHint:true`

### Read

- [x] **READ-01**: Tool `list_chats` returns groups + 1:1 chats with last-activity timestamp, unread count, kind (1:1/group/broadcast/community), and a `coverage` window naming the time range present in the local DB *(Plan 01-04: `tools/list_chats.py` wraps `reader.list_chats`; per-chat Coverage populated by reader; live-verified.)*
- [x] **READ-02**: Tool `read_chat` returns messages from a specific chat by `chat_id`, bounded by `limit` (default 200, max enforced by char-cap) OR by `before`/`after` timestamps, with `cursor`/`next_cursor` pagination *(Plan 01-04: `tools/read_chat.py` consumes `reader.window`'s B2 tuple, emits W2 `anchor_kind="z_sort"` cursor; live-verified cursor pagination across two pages on the user's 84438-row ZWAMESSAGE.)*
- [x] **READ-03**: Tool `extract_recent` returns all messages from a `chat_id` within the last N hours; response includes `coverage` ("asked Xh, have Yh") *(Plan 01-04: `tools/extract_recent.py` wraps `reader.since`; hours clamped to [1, 168]; `summary` field carries "asked Xh, have Yh" rounded to one decimal.)*
- [x] **READ-04**: Tool `search_messages` performs full-text search across chats with optional `chat_id`, sender, and date filters; LIKE acceptable for v0.1, FTS5 shadow index for v1.0 *(Plan 01-04: `tools/search_messages.py` ships the v0.1 LIKE variant via `reader.like_search`; W2 `anchor_kind="cocoa_ts"` cursor; FTS5 deferred to Phase 3.)*
- [x] **READ-05**: Tool `search_contacts` finds chats/contacts by name or phone fragment, deduplicating across `@s.whatsapp.net` and `@lid` representations of the same person *(Plan 01-04: `tools/search_contacts.py` wraps `reader.search_contacts` which Plan 02 already de-dedups via LID.sqlite per the Pattern 7 6-step recipe.)*
- [x] **READ-06**: Tool `get_chat_metadata` returns group description, member list (with display names and admin flags), mute status — for groups and 1:1s *(Plan 01-04: `tools/get_chat_metadata.py` surfaces the W5-locked v0.1 defaults — `description=None`, `is_muted=False` — verbatim; group member list with admin flags from `reader.get_group_info`; degenerate 1:1 shape with display_name as subject.)*
- [x] **READ-07**: Tool `get_message_context` returns N messages before/after a `message_id`, plus the parent message if the target is a quote-reply (uses `ZPARENTMESSAGE` self-join) *(Plan 01-04: `tools/get_message_context.py` combines `reader.context_around_stanza` + `reader.parent_of_stanza`; before/after clamped to [0, 50].)*
- [x] **READ-08**: All read tools default `include_deleted=False`; tombstoned messages (`ZMESSAGETYPE=14`, deleted-for-everyone, deleted-for-me bit-flagged) are filtered unless caller opts in *(reader-tier satisfied by Plan 01-02 — `is_tombstone` predicate + `TOMBSTONE_SQL_WHERE` SQL filter inlined into every `_SQL_*` window/since/context/search template; the `include_deleted=False` default in every reader accessor selects the tombstone-filtered template. Tool-tier `include_deleted` parameter wiring belongs to Plan 01-04.)*
- [x] **READ-09**: All read tool responses fit within MCP's per-result size cap (~60k chars); larger results paginate via opaque cursor; `_meta["anthropic/maxResultSizeChars"]` annotation set on every read tool *(Plan 01-04: every registered tool — incl. doctor (W1, no carve-out) — carries `meta={"anthropic/maxResultSizeChars": 60000}`; cursored tools emit W2-discriminated opaque cursors with iterative char-cap trim before return; live-verified body sizes under cap.)*

### Data Contracts

- [ ] **DATA-01**: All tool returns are JSON conforming to a locked Pydantic schema for `Message`, `Chat`, `Contact`, `GroupInfo`, `MediaRef`, `Jid` (kind-tagged: `phone` / `lid` / `group`)
- [ ] **DATA-02**: Each `Message` includes `message_id` (`ZSTANZAID`), `chat_id`, `sender_jid`, `timestamp` (Unix seconds, converted from Cocoa epoch), `body`, `kind` (text/media/system/etc), `is_outgoing`, `quoted_message_id` (nullable)
- [x] **DATA-03**: Attachments are surfaced as `MediaRef` with `filename`, `mime`, `local_path` (absolute), `size_bytes` — never inlined as binary in tool responses *(reader-tier satisfied by Plan 01-02 — `reader/media.py:resolve_media_ref` builds `MediaRef` with absolute path validated against `paths.resolve_media_root()` via `Path.resolve()` + separator-bounded prefix check, defending against the lharries#241 path-traversal threat class; never inlines bytes. Tool-tier surfacing belongs to Plan 01-04.)*
- [x] **DATA-04**: Encrypted/protobuf BLOB columns (`ZMEDIAKEY`, `ZMETADATA`, `ZRECEIPTINFO`) are NOT parsed in v1; surfaced as opaque or omitted *(satisfied by Plan 01-02 — the file-wide grep gate `grep -rcE 'ZMEDIAKEY|ZMETADATA|ZRECEIPTINFO' src/whatsapp_desktop_mcp/reader/` returns 0 across every file in the package; the column literal names are deliberately omitted from the source so neither read nor parse can occur.)*

### Send

- [ ] **SEND-01**: Tool `send_message` sends a text-only message to one recipient identified by an opaque `chat_id` previously returned by `search_contacts` or `list_chats` (never a free-form name string)
- [ ] **SEND-02**: Send is annotated `destructiveHint:true` and gated by MCP elicitation confirmation by default; confirmation displays resolved chat name + recipient JID + body verbatim
- [ ] **SEND-03**: Primary send path is `whatsapp://send?phone=<E164>&text=<urlencoded>` deep-link + `osascript` keystroke return; group-chat fallback is a search-and-click sequence with documented brittleness
- [ ] **SEND-04**: Pre-send AX-API state assertion verifies the focused window's chat header matches the resolved chat name (aborts on mismatch; returns structured error)
- [ ] **SEND-05**: Conservative rate limiter active by default: 5 sends/min, 30 sends/day; configurable; rate-limit hit returns structured error, never silently drops
- [ ] **SEND-06**: Every send attempt (success or failure) is appended to an audit log at `~/Library/Logs/whatsapp-desktop-mcp/audit.log` (mode 0600) with timestamp, resolved chat_id + name, body hash, outcome
- [ ] **SEND-07**: Cross-chat-quote heuristic detects when the body to send contains content recently quoted from another chat; surfaces a warning in the confirmation prompt
- [ ] **SEND-08**: Send is verified post-hoc by polling `ZWAMESSAGE` for a new outgoing row matching the body within 10s; success returns the resulting `message_id`

### Reliability & Concurrency

- [x] **REL-01**: SQLite reader uses short-lived connections opened with `?mode=ro` URI flag (never `immutable=1`); reads succeed concurrently with WhatsApp's writer *(satisfied by Plan 01-02 — `reader/connection.py:open_ro` opens `file:{path}?mode=ro` per call with `busy_timeout=5000` and `BEGIN/COMMIT` deferred read; never the WAL-skipping URI flag. Verified live concurrent with WhatsApp Desktop 26.16.74's writer (RUN_LIVE=1 smoke 2026-05-13).)*
- [x] **REL-02**: All DB calls wrapped in `asyncio.to_thread`; all `osascript` calls via `asyncio.create_subprocess_exec` + `asyncio.wait_for(timeout=10)`; the stdio event loop never blocks *(reader-tier satisfied by Plan 01-02 — `grep -rE 'asyncio\.to_thread' src/whatsapp_desktop_mcp/reader/` returns 22 (every public async accessor dispatches to its `_blocking_*` impl); osascript half was satisfied in Phase 0 Plan 03; tool tier in Plan 01-04 uses only `await` against the already-async reader.)*
- [x] **REL-03**: Per-tool timeouts enforced: `read_chat` 5s, `search_messages` 10s, `send_message` 15s *(Plan 01-04 reader-tier portion: `tools/_decorators.py:timeout(seconds=N)` wraps each tool body in `asyncio.wait_for`; converts `TimeoutError` to a structured `ValueError` so FastMCP surfaces a tool-error rather than a Python traceback. 5s for list_chats/read_chat/extract_recent/search_contacts/get_chat_metadata/get_message_context; 10s for search_messages. `send_message`'s 15s budget is Phase 2's portion.)*
- [x] **REL-04**: Schema fingerprint (`Z_METADATA.Z_VERSION`) probed at startup; out-of-range version returns a degraded-mode warning from `doctor` rather than crashing read tools *(reader-tier satisfied by Plan 01-02 — `reader/schema_v1.py` ships `SUPPORTED_VERSIONS = frozenset({1})` + `probe_z_version(conn) -> int` + `is_supported(version) -> bool`. Verified live: `Z_VERSION = 1` matches the supported set. `doctor` integration belongs to Plan 01-05.)*
- [ ] **REL-05**: Reader and Sender modules MUST NOT import each other; tool layer is the only integration point

### Diagnostics

- [ ] **DIAG-01**: Tool `doctor` returns a structured preflight report covering: DB path resolved, FDA granted, Automation granted, Accessibility granted, schema fingerprint OK, WhatsApp.app version detected, last-message timestamp, `coverage` summary
- [ ] **DIAG-02**: `doctor` is callable even when other tools would fail (it is the diagnosis path)

### Distribution

- [x] **DIST-01**: Project is published to PyPI as `whatsapp-desktop-mcp`, installable via `uvx whatsapp-desktop-mcp` for developers *(satisfied at the workflow level by Plan 05 — `.github/workflows/release.yml` triggers on `tags: ['v*']`, reuses `ci.yml` as a gate, then a `publish` job with `permissions: id-token: write` AT THE JOB LEVEL (P-PHASE0-04 mitigation) runs `uv build` + `uv publish` over GitHub OIDC trusted-publisher; no long-lived credential in repo (verified by file-wide grep `'PYPI_TOKEN' not in src and 'password:' not in src`). Closes end-to-end once the manual one-time PyPI trusted-publisher pending-publisher binding (Owner=`gladia`, Repo=`whatsapp-desktop-mcp`, Workflow=`release.yml`, Environment=`pypi`) is configured and the first `git tag v0.1.0 && git push --tags` runs to completion — documented in README's Development section.)*
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
| HTTP REST surface (any TCP/UDP listener) | Anti-feature: `lharries/whatsapp-desktop-mcp` was hit by exactly this — path traversal CVE class + unauth LAN exposure |
| Side-effect "mark as read" on `read_chat` | Surprising side effect from a read tool; user may want to read silently |
| WhatsApp Business / Cloud API integration | Defeats the project — user wants personal account |
| WhatsApp Web protocol (whatsmeow / Baileys) | Different architecture; that's `lharries/whatsapp-desktop-mcp`'s design, which PROJECT.md rejects |
| Voice / video call control | Out of project scope — text + media metadata only |
| Reactions, polls, status updates | Defer to v2 — each is a different UI path |
| Sending media (images/files) | Defer to v2 — AppleScript drag-drop fragile across versions |
| Cross-platform (Windows/Linux WhatsApp Desktop) | macOS only for v1 |
| Hosting on a remote server | Strictly local; runs on the same Mac as WhatsApp Desktop |
| Bypassing WhatsApp encryption | Anti-feature: only what the logged-in user can already see |

## Traceability

| Requirement | Phase | Phase Name | Status |
|-------------|-------|------------|--------|
| SETUP-01 | Phase 0 | Setup & Permissions Skeleton | Satisfied (Plan 05 — `examples/claude_desktop_config.json` is the authoritative 4-line snippet; cross-checked byte-decodable equal to the JSON code fence in README's Quickstart step 1) |
| SETUP-02 | Phase 0 | Setup & Permissions Skeleton | Satisfied (Plan 03 — `doctor` registered with `readOnlyHint=True`; full Claude-Desktop smoke test exercised by Plan 04's stdout-purity test inside Plan 05's ci.yml) |
| SETUP-03 | Phase 0 | Setup & Permissions Skeleton | Satisfied (Plan 04 — `tests/unit/test_stdout_purity.py` spawns `python -m whatsapp_desktop_mcp`, drives full JSON-RPC handshake, asserts every stdout line is JSON-RPC 2.0; ruff T201 lint-blocks `print` from Plan 01; Plan 05's `ci.yml` runs the test on every push/PR — three-layer defense in depth) |
| SETUP-04 | Phase 0 | Setup & Permissions Skeleton | Satisfied (Plan 03 — structured `DoctorReport` payloads with binary_path + db_path + system_settings_url + remediation per D-11; D-09 PATCHED probe in source) |
| SETUP-05 | Phase 0 | Setup & Permissions Skeleton | Satisfied (Plan 05 — README opens with D-20 ToS automation-risk blockquote, contains D-21 four-step 60s quickstart, D-22 framing inline — all locked clauses verified by content greps) |
| DIST-01 | Phase 0 | Setup & Permissions Skeleton | Satisfied at the workflow level (Plan 05 — `.github/workflows/release.yml` triggers on `tags: ['v*']`, runs CI then `uv build` + `uv publish` via OIDC trusted-publisher with job-level `id-token: write` per P-PHASE0-04; closes end-to-end once the manual one-time PyPI pending-publisher binding is configured and v0.1.0 ships) |
| SETUP-06 | Phase 1 | Read MVP (`--read-only`) | Pending |
| READ-01 | Phase 1 | Read MVP (`--read-only`) | Satisfied by Plan 01-04 (`tools/list_chats.py`) |
| READ-02 | Phase 1 | Read MVP (`--read-only`) | Satisfied by Plan 01-04 (`tools/read_chat.py` with W2 cursor) |
| READ-03 | Phase 1 | Read MVP (`--read-only`) | Satisfied by Plan 01-04 (`tools/extract_recent.py` with "asked Xh, have Yh") |
| READ-04 | Phase 1 | Read MVP (`--read-only`) | Satisfied by Plan 01-04 v0.1 LIKE (`tools/search_messages.py`); FTS5 deferred to Phase 3 |
| READ-05 | Phase 1 | Read MVP (`--read-only`) | Satisfied by Plan 01-04 (`tools/search_contacts.py` over Plan 02's dedup recipe) |
| READ-06 | Phase 1 | Read MVP (`--read-only`) | Satisfied by Plan 01-04 (`tools/get_chat_metadata.py` w/ W5 v0.1 locks) |
| READ-07 | Phase 1 | Read MVP (`--read-only`) | Satisfied by Plan 01-04 (`tools/get_message_context.py` w/ parent self-join) |
| READ-08 | Phase 1 | Read MVP (`--read-only`) | Reader tier satisfied by Plan 01-02 (predicate + SQL filter); tool-tier opt-in flag pending Plan 01-04 |
| READ-09 | Phase 1 | Read MVP (`--read-only`) | Satisfied by Plan 01-04 (every registered tool incl. doctor advertises 60k meta; cursored tools char-cap with opaque W2 cursors) |
| DATA-01 | Phase 1 | Read MVP (`--read-only`) | Pending |
| DATA-02 | Phase 1 | Read MVP (`--read-only`) | Pending |
| DATA-03 | Phase 1 | Read MVP (`--read-only`) | Reader tier satisfied by Plan 01-02 (`reader/media.py:resolve_media_ref` with path-traversal defense); tool-tier surfacing pending Plan 01-04 |
| DATA-04 | Phase 1 | Read MVP (`--read-only`) | Satisfied by Plan 01-02 (encrypted/protobuf BLOB column literal names absent across `src/whatsapp_desktop_mcp/reader/` — verified by file-wide grep gate) |
| REL-01 | Phase 1 | Read MVP (`--read-only`) | Satisfied by Plan 01-02 (`reader/connection.py:open_ro` with `?mode=ro` + `busy_timeout=5000`; verified live concurrent with WhatsApp writer 2026-05-13) |
| REL-02 | Phase 1 | Read MVP (`--read-only`) | Reader tier satisfied by Plan 01-02 (22 `asyncio.to_thread` dispatches across the 14 async accessors); osascript half satisfied by Phase 0 Plan 03; tool tier in Plan 01-04 uses async/await against the reader's coroutines |
| REL-03 | Phase 1 | Read MVP (`--read-only`) | Read-tool tier satisfied by Plan 01-04 (`tools/_decorators.py:timeout(seconds=N)` wrapping each tool body; 5s default / 10s search_messages); `send_message` 15s portion belongs to Phase 2 |
| REL-04 | Phase 1 | Read MVP (`--read-only`) | Reader tier satisfied by Plan 01-02 (`reader/schema_v1.py` with `SUPPORTED_VERSIONS = frozenset({1})` + `probe_z_version` + `is_supported`); doctor integration pending Plan 01-05 |
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
*Last updated: 2026-05-13 after Phase 1 Plan 01-04 executed (tool-tier READ-01..07, READ-09, REL-02 tool tier, and REL-03 read-tool portion satisfied; reader-tier REL-01, REL-04, READ-08, DATA-03, DATA-04 already satisfied by Plan 01-02; DIAG-01/02 + SETUP-06 + DATA-01/02 pending Plans 01-05/01-06)*

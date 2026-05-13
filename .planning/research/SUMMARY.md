# Project Research Summary — WhatsApp MCP

**Project:** WhatsApp MCP — Desktop Control Server
**Domain:** Local MCP server bridging an LLM client to the macOS WhatsApp Desktop (Catalyst) app — read via private SQLite, write via UI automation
**Researched:** 2026-05-13
**Overall confidence:** HIGH on stack, feature surface, DB layout (verified live), and pitfall taxonomy. MEDIUM on long-term send-path durability (no AppleScript dictionary; UI may shift) and on schema stability across future WhatsApp Catalyst minor versions.

---

## 1. TL;DR (30-second read for the planner)

- **Stack is settled:** Python 3.12 + `mcp[cli]==1.27.1` (FastMCP, stdio) + stdlib `sqlite3` (read-only) + `subprocess`+`osascript` for sends. Dev distribution `uvx`; user-friendly distribution should be a signed `.pkg` (TCC requires a stable binary path).
- **Read = local SQLite, write = UI automation.** DB at `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite` (verified live, WhatsApp 26.16.74 / macOS 26.4). WhatsApp.app exposes **no AppleScript dictionary** (`sdef` returns -192) — sends MUST use `whatsapp://send?phone=…&text=…` deep-link + System Events return-key, with search-and-click as a group-chat fallback.
- **9 table-stakes tools + 3 differentiators in v1.** Table stakes: `list_chats`, `read_chat`, `extract_recent`, `search_messages` (FTS5), `send_message`, `search_contacts`, structured JSON, attachment metadata, `doctor` preflight. Differentiators chosen: `get_chat_metadata`, `get_message_context`, `--read-only` safe-mode flag.
- **Hard "no" list (anti-features) is non-negotiable:** no bulk/broadcast send, no scheduled send, no auto-reply loop, no inline media bytes, no SQLite writes, no HTTP REST surface (`lharries/whatsapp-mcp` was bitten by exactly this — 0.0.0.0 bind, path-traversal CVE class), no "mark as read" side effects.
- **The two highest-volatility surfaces are isolated:** `reader/` absorbs schema drift, `sender/` absorbs UI drift. They never import each other. Tool-layer JSON contracts stay stable across either kind of breakage.
- **DB is a sync cache, not a source of truth.** WhatsApp Desktop is a *linked secondary device*; older history may not be present. Every read tool MUST return a `coverage` field naming the time range actually present.
- **TCC (Full Disk Access + Accessibility + Apple Events) is the #1 source of "looks broken" bugs.** FDA does NOT inherit through `Claude.app → uvx → python`. Solution: ship a signed launcher at a stable path; document exact binary to add to FDA; preflight `doctor` returns structured `FullDiskAccessRequired` / `AutomationPermissionRequired` with System Settings deep-link.
- **`stdout` is the JSON-RPC channel.** A single stray `print()` corrupts the protocol. Lint-enforce `T201`, send all logging to stderr, CI test asserts stdout is pure JSON-RPC.

---

## 2. Recommended Stack

| Layer | Pick | Version | Why (one line) |
|------|------|---------|----------------|
| Language | Python | 3.12.x | Sweet spot for `mcp` floor (3.10), `uv` cache, pyobjc wheels |
| MCP SDK | `mcp[cli]` | `==1.27.1` | Official, FastMCP decorators, stdio transport |
| DB | stdlib `sqlite3` | bundled | Read-only WAL works; no async needed; zero deps |
| Send | `subprocess` + `osascript` | stdlib | Only viable path — no AS dictionary; debuggable; testable with `pytest-subprocess` |
| Schemas / models | `pydantic` | `>=2.7,<3` | Already transitive; gives free JSON schema for tool contracts |
| Logging | stdlib `logging` to stderr (or `structlog>=24.1` for JSON) | — | **Never to stdout** |
| Optional macOS | `pyobjc-core` + `pyobjc-framework-Cocoa` | `==12.1` | Only when we add Accessibility-API send (recommended in v1.x for state assertions before keystroke) |
| Distribution (dev) | `uvx whatsapp-mcp` | `uv>=0.5` | Single-line `claude_desktop_config.json` install |
| Distribution (end-user, v1.0 recommended) | Signed `.pkg` dropping `/usr/local/bin/whatsapp-mcp` | — | Stable path = TCC permissions persist across upgrades (Pitfall 15) |
| Lint/format | `ruff>=0.6` | — | One binary; enforce `T201` (no `print`) |
| Type check | `mypy>=1.10` (or pyright) | — | Strict on the MCP tool surface |
| Test | `pytest>=8.2` + `pytest-subprocess>=1.5` | — | Subprocess mock is the right test seam for the osascript boundary |

**Explicitly NOT picked:** Go + `whatsmeow`, TS + Baileys (different protocol — that's `lharries/whatsapp-mcp`'s architecture, which PROJECT.md rejects); `aiosqlite` (slower than stdlib for our pattern); SQLAlchemy (overkill for 5 tables we don't own); PyObjC NSAppleScript just to run AppleScript (30MB of wheels for no win); WhatsApp Cloud API (out of scope); Selenium/pywhatkit/pyautogui (browser-based, wrong target); writing to `ChatStorage.sqlite` (corrupts the writer).

---

## 3. Verified Facts About the Target Environment

**VERIFIED LIVE** = directly inspected on this machine on 2026-05-13. **INFERRED** = corroborated by sources but not re-checked here.

### Filesystem layout

| Fact | Status |
|---|---|
| `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/` is the data root | **VERIFIED LIVE** |
| Chat history is in `ChatStorage.sqlite` (89 MB on test machine), with `-wal` and `-shm` siblings | **VERIFIED LIVE** |
| Address book is in sibling `ContactsV2.sqlite` (table `ZWAADDRESSBOOKCONTACT`) | **VERIFIED LIVE** |
| Phone↔LID mapping is in sibling `LID.sqlite` (table `ZWAPHONENUMBERLIDPAIR`) — only authoritative local mapping | **VERIFIED LIVE** |
| WhatsApp's own FTS index at `fts/ChatSearchV5f.sqlite` uses a custom `wa_tokenizer` — **unusable from our process** (tokenizer module loads only inside WhatsApp.app) | **VERIFIED LIVE** |
| Media files at `Message/Media/<chatJid>/<x>/<y>/<uuid>.{ext}`; `ZWAMEDIAITEM.ZMEDIALOCALPATH` stores the relative path | **VERIFIED LIVE** |
| Bundle is sandboxed Mac-App-Store build (`com.apple.security.app-sandbox = true`), team `57T9237FN3`, bundle id `net.whatsapp.WhatsApp` | **VERIFIED LIVE** |
| Data lives in **shared group container** (not per-app), reachable from a non-WhatsApp process — Full Disk Access still required | **VERIFIED LIVE** |

### SQLite operational behavior

| Fact | Status |
|---|---|
| Journal mode is `wal` | **VERIFIED LIVE** |
| Live RO queries succeed concurrent with WhatsApp writing, using `?mode=ro` URI flag (NOT `immutable=1`) | **VERIFIED LIVE** |
| Reader must always have access to `-wal` and `-shm` alongside the main file (copying main alone produces corrupt data) | **INFERRED** (per SQLite WAL docs) |
| `Z_METADATA.Z_VERSION` exposes Core Data schema version — basis for the schema-versioned adapter | **VERIFIED LIVE** |
| Compound index `Z_WAMessage_compoundIndex (ZCHATSESSION, ZSORT)` exists — every chat-window read should hit it | **VERIFIED LIVE** |

### Schema essentials (Core Data lineage from iOS)

| Table | Verified columns / behavior | Status |
|---|---|---|
| `ZWACHATSESSION` | One row per chat. `Z_PK` = chat id. `ZSESSIONTYPE`: 0=1:1 (`@s.whatsapp.net`), 1=group (`@g.us`), 3=broadcast/status, 4=community-announcement | **VERIFIED LIVE** |
| `ZWAMESSAGE` | One row per message. Use `ZSORT` for in-chat order, `ZMESSAGEDATE` for global recency. Dates are **Cocoa epoch** (+978,307,200 → Unix). `ZMESSAGETYPE`: 0=text, 1=image, 2=video/voice, 3=audio, 6=system, 7=location, 8=contact, 10=sticker, 11=call, 14=revoked, 15=ephemeral, 59=poll, 66=reaction. `ZSTANZAID` = global protocol message id → use as `message_id` in MCP responses | **VERIFIED LIVE** distribution; type values **INFERRED** stable from WA iOS forensics |
| `ZWAGROUPINFO` + `ZWAGROUPMEMBER` | Group description, members, admin flags — feeds `get_chat_metadata` | **VERIFIED LIVE** |
| `ZWAMEDIAITEM` | `ZMEDIALOCALPATH` is **relative** to `Message/`; `ZMEDIAKEY` and `ZMETADATA` are encrypted/protobuf BLOBs — **do not parse in v1** | **VERIFIED LIVE** |
| `ZWAMESSAGEINFO.ZRECEIPTINFO` | Encrypted/protobuf BLOB — defer to v2; surface as opaque | **VERIFIED LIVE** |
| Tombstones | Deleted-for-everyone messages survive in `ZWAMESSAGE` (often `ZTEXT IS NULL`, `ZMESSAGETYPE=14`, certain `ZFLAGS` bits set). Default reads MUST filter them | **VERIFIED LIVE** for type 14; flag bits **INFERRED** and need predicate-test on a fresh machine |
| JID heterogeneity | Same person may appear as `<phone>@s.whatsapp.net` in 1:1 and `<lid>@lid` in groups; never compare JID strings directly | **VERIFIED LIVE** |

### Send-path constraints

| Fact | Status |
|---|---|
| `sdef /Applications/WhatsApp.app` returns error **-192** ("not scriptable") — no AppleScript dictionary | **VERIFIED LIVE** |
| URL schemes registered in `Info.plist`: `whatsapp:`, `whatsapp-consumer:`, `upi:`, `fb306069495113:` | **VERIFIED LIVE** |
| `whatsapp://send?phone=<E164>&text=<urlencoded>` opens the chat with text pre-filled — primary send path | **VERIFIED** |
| Deep-link does NOT support group JIDs from a non-WhatsApp process — group sends require search-and-click fallback (fragile) | **INFERRED** |
| WhatsApp's main window title contains an invisible LRM character (`‎WhatsApp` ≠ `WhatsApp`) — string-comparing window names silently fails | **VERIFIED LIVE** |
| Required TCC buckets: Full Disk Access (read DB), Accessibility (System Events keystrokes), Automation/Apple Events (`tell application "WhatsApp"`) — three separate prompts | **VERIFIED** (Apple TCC docs) |

---

## 4. v1 Feature Surface

### TABLE STAKES (must ship in v1) — 9

- `list_chats` — groups + 1:1, last-activity ts, unread count, `coverage` window
- `read_chat` — by chat_id, bounded by count OR time window; default `limit=200`
- `extract_recent` — sugar on `read_chat`: last N hours from a chat (the canonical workflow)
- `search_messages` — FTS5-backed (own shadow index — WhatsApp's `wa_tokenizer` unusable) with sender + date filters; LIKE fallback acceptable for v0.1 but FTS5 lands in v1.0
- `search_contacts` — name fragment → chat_id (with JID + LID dedup)
- `send_message` — single recipient, text only, `destructiveHint:true`, gated by `--read-only`
- Structured JSON output (`Message`, `Chat`, `Contact`, `MediaRef`) — locked schema
- Attachment metadata only (filename, mime, on-disk path; **never inline bytes**)
- `doctor` preflight tool — verifies DB path, FDA, Automation, Accessibility, schema fingerprint, WhatsApp.app version

### DIFFERENTIATORS chosen for v1 — 3

- **`get_chat_metadata`** — group description, member list with display names, admin flags, mute. Highest value-per-line-of-code; data already in `ZWAGROUPINFO` + `ZWAGROUPMEMBER`.
- **`get_message_context`** — given a `message_id`, return N before/after PLUS the parent message if it's a quote-reply (uses `ZPARENTMESSAGE` self-join). Turns the project from "chat dumper" into "thread-aware reader."
- **`--read-only` startup flag** — disables `send_message`, marks all tools `readOnlyHint:true`. Half-day's work, large trust dividend.

### Deferred to v1.1+

`get_last_interaction`, FSEvents-based freshness signal, `download_media` (path-returning), draft+confirm flow for `send_message`, per-chat `mute`/`unread` in `list_chats`, schema-version sniffer with degraded-mode status.

### ANTI-FEATURES (will not ship) — 9

| Feature | Why we refuse (one line) |
|---|---|
| Bulk / broadcast send | WhatsApp ToS bans automation; account-ban risk; #1 prompt-injection blast vector |
| Scheduled / delayed send | Requires persistent background process; out of scope for stdio MCP |
| Auto-reply / agent loop on incoming | Different threat model; massive abuse risk; WhatsApp will ban |
| Inline media binary in tool response | A 4MB image ≈ 1.5M tokens — context-window obliteration |
| Writing into `ChatStorage.sqlite` | Corrupts WhatsApp's writer; schema can change between releases |
| Sending media (images/files) in v1 | AppleScript drag-drop fragile across versions; defer to v2 |
| Reactions / polls / status / edit / delete | Each requires a different UI path; triples maintenance burden; PROJECT.md defers |
| "Mark as read" side effect of `read_chat` | Side effects from a read tool are surprising; user may want to read silently |
| HTTP REST surface (bind 0.0.0.0) | `lharries/whatsapp-mcp` was hit by exactly this — path traversal + unauth LAN exposure |

---

## 5. Top 8 Pitfalls and Mandated Guardrails

One line each: pitfall → mandated mitigation → owning phase.

1. **Cache ≠ source of truth (P1)** → every read response includes a `coverage` field naming the time range actually present in the DB; `extract_recent` returns "asked 6h, have 47m" → **Phase 1**.
2. **Stdout pollution kills JSON-RPC (P7)** → entry point sets `logging.basicConfig(stream=sys.stderr)`; ruff `T201` lint-blocks `print`; CI test asserts stdout is pure JSON-RPC after `initialize` → **Phase 0**.
3. **Wrong-binary FDA (P4)** → ship signed launcher at `/usr/local/bin/whatsapp-mcp`; preflight `os.stat()` the DB and return structured `FullDiskAccessRequired` with the exact path to add and a `x-apple.systempreferences:` deep-link → **Phase 0** (install) + **Phase 1** (preflight).
4. **Wrong-chat send via fuzzy search (P5)** → two-tool flow: `search_contacts/resolve_chat` returns ALL matches above threshold (never auto-pick); `send_message` accepts only the opaque `chat_id`; pre-send AX-API verifies focused window's chat header matches the resolved name → **Phase 2**.
5. **LLM misuse — fan-out blast / prompt-injected send / cross-chat leak (P6)** → MCP elicitation confirmation (showing resolved chat name + body) ON by default; rate limit 5/min, 30/day default; cross-chat-quote heuristic; audit log to `~/Library/Logs/whatsapp-mcp/audit.log` mode 0600; **no multi-recipient tool exists** → **Phase 2**.
6. **Sync DB call blocks the stdio event loop (P8)** → all DB calls via `asyncio.to_thread`; `osascript` via `asyncio.create_subprocess_exec` + `asyncio.wait_for(timeout=10)`; per-tool timeout (`read_chat`:5s, `search_messages`:10s, `send_message`:15s) → **Phase 1**.
7. **Tool result exceeds Claude's 25k-token MCP cap (P9)** → hard char-cap (~60k chars ≈ 15k tokens) per result; mandatory `cursor`/`next_cursor` pagination; set `_meta["anthropic/maxResultSizeChars"]` annotation; never inline media bytes → **Phase 1**.
8. **AppleScript fragility — focus, race, modal-state (P12)** → primary send path is `whatsapp://send?phone=…&text=…` deep-link + `keystroke return` (not search-and-click); v1.x adds Accessibility-API path (`AXTextArea` find → `setValue:` → `AXButton` "Send" `AXPress`) with state assertions before each step; latency log; abort if window title doesn't match (the invisible LRM char trap) → **Phase 2**.

---

## 6. Suggested Build Order — 4 coarse phases

The architecture's 9 steps collapse cleanly into 4 user-visible phases.

### Phase 0 — Setup & Permissions Skeleton
**Rationale:** Permissions and stdio hygiene are the #1 source of "looks broken" bugs. Solve them before writing tool logic.
**Delivers:** project skeleton (`uv init`, `pyproject.toml`, package layout); `mcp[cli]` server stub with no-op `ping`; ruff `T201` enabled; CI stdout-purity test; structured `FullDiskAccessRequired` / `AutomationPermissionRequired` errors with System Settings deep-links; README disclaimer about WhatsApp ToS and account-ban risk; `.pkg`/brew packaging plan documented.
**Avoids pitfalls:** P7 (stdout), P4 (FDA), P13 (Automation), P14 (ToS disclaimer), P15 (TCC churn).

### Phase 1 — Read MVP (DB Reader + read tools)
**Rationale:** The reader is the most stable layer; unblocks 6 of 9 v1 tools and builds the JID lookup that Phase 2 depends on.
**Delivers:**
- `models.py` (`Chat`, `Message`, `Contact`, `GroupInfo`, `MediaRef`, `Jid`), `time.py` (Cocoa↔Unix), `reader/paths.py`, `reader/connection.py` (short-lived RO WAL connection), `reader/schema_v1.py` with `Z_VERSION` probe
- `reader/chats.py`, `reader/messages.py`, `reader/tombstones.py`, `reader/contacts.py`, `reader/search.py` (LIKE for v0.1; FTS5 shadow can ship within Phase 1 or 1.5)
- `cli.py` for end-to-end debug without an MCP client
- MCP boundary + tools: `list_chats`, `read_chat`, `extract_recent`, `search_messages`, `search_contacts`, `get_chat_metadata`, `get_message_context`, `doctor`
- All tools: async wrapper, per-tool timeout, char-cap, pagination, `coverage` field, default `include_deleted=False`, JID/LID dedup
**Stack used:** `mcp[cli]`, stdlib `sqlite3`, `pydantic`
**Addresses features:** 6 read tools + 2 differentiators + `doctor` (8 of 12 v1 tools)
**Avoids pitfalls:** P1, P2, P3, P8, P9, P10, P11
**Acceptance:** can install in Claude Desktop with `--read-only` and use the read tools end-to-end against a real WhatsApp.

### Phase 2 — Send (UI automation, behind safety guardrails)
**Rationale:** Sender is the most fragile layer — ship it last so it can be patched without disturbing reads.
**Delivers:**
- `sender/deeplink.py` (`whatsapp://send` URL build + `open` subprocess), `sender/osascript.py` (subprocess wrapper with timeout), `sender/ui_send.py` (deep-link primary + search-and-click group fallback), `sender/verify.py` (poll `ZWAMESSAGE` for new outgoing row matching body, return `ZSTANZAID`)
- `--read-only` flag (default for v0.1; default-off for v1.0 with explicit opt-in)
- `tools/send_message.py` with `destructiveHint:true`, MCP elicitation confirmation by default (resolved chat + body), rate limiter (5/min, 30/day default), cross-chat-quote heuristic, audit log
- Optional but recommended in v1.x: Accessibility-API send path (`pyobjc-framework-Cocoa`) replacing raw keystroke for state-asserting send (P12 mitigation upgrade)
**Stack used:** `subprocess` + `osascript`; optionally `pyobjc-core` + `pyobjc-framework-Cocoa==12.1`
**Addresses features:** `send_message`
**Avoids pitfalls:** P5, P6, P12, P13, P14
**Acceptance:** end-to-end `send_message` to a 1:1 chat works; group send works with documented brittleness; rate limiter trips correctly; confirmation prompt shows full context.

### Phase 3 — Hardening & Distribution
**Rationale:** Convert "works on the maintainer's Mac" into "works on a fresh Mac after every WhatsApp update."
**Delivers:**
- Signed `.pkg` installer dropping `/usr/local/bin/whatsapp-mcp` at a stable path, Developer ID signed, with `Info.plist` + `NSAppleEventsUsageDescription` + `com.apple.security.automation.apple-events` entitlement; also a brew formula
- FTS5 shadow index for `search_messages` if not already shipped; incremental sync on `ZMESSAGEDATE > last_seen`
- `tested_versions.md` for known-good WhatsApp Desktop versions
- Full integration smoke suite gated by `RUN_LIVE_WHATSAPP=1`
- README install paths: `.pkg` (recommended), brew, uvx (dev-only)
- Recovery doc: schema mismatch → `diagnose` output → patch → release
**Avoids pitfalls:** P15, reinforces P2, P4, P13
**Acceptance:** clean macOS install can go from "download .pkg" → "first successful `read_chat` and `send_message` from Claude Desktop" in under 10 minutes.

### Research flags

Phases likely needing **deeper research during planning**:
- **Phase 2** — Accessibility-API send path with AX state assertions; deep-link group-send fallback experimentation
- **Phase 3** — `.pkg` signing + notarization + TCC entitlement combination for a Python-launcher hybrid

Phases with **standard patterns**:
- **Phase 0** — well-trodden MCP stdio + `uv` + ruff/mypy/pytest scaffolding
- **Phase 1** — SQLite RO-WAL pattern + Core Data reading is well-documented

---

## 7. Open Questions for Phase 1

1. **Exact `ZFLAGS` bit semantics for tombstoned messages.** Bits `0x05000000` and `0x05008000` correlate with deleted/revoked here; need an `is_tombstone(row)` predicate tested on a fresh second machine before v1.0.
2. **Stability of `ZSESSIONTYPE` enum values across WhatsApp Catalyst minor versions.** Verified for 0/1/3/4 here — but values are not formally documented.
3. **`@lid` ↔ phone resolution completeness.** `LID.sqlite` is the only authoritative local mapping, but in stricter-privacy groups the mapping may be incomplete.
4. **WhatsApp Desktop version range that the v1 schema queries support.** Need lower/upper `Z_VERSION` bounds, not just current.
5. **Group-send fallback feasibility.** Deep-link works for 1:1; group sends need search-and-click against a fragile UI. v1 vs v1.1 decision.
6. **Does `.sqlite-wal` need to exist for `mode=ro` to work in all states?** Edge case for `doctor`.
7. **Whether keystroke-injected text handles emoji and non-BMP Unicode reliably.** AppleScript `keystroke` historically truncates surrogate pairs; URL-encoded text may sidestep this.

---

## 8. Watch-Out Section for the Planner

- **PROJECT.md's "Active" tool list is missing 3 of v1's 12 tools.** Roadmap should add `get_chat_metadata`, `get_message_context`, `--read-only`, `doctor` explicitly.
- **PROJECT.md's "Out of Scope" is missing the explicit anti-features.** Bulk send, HTTP REST surface, SQLite write, auto-reply loop, "mark as read" should each appear with the one-line "why not."
- **The DB is a sync cache, not the source of truth.** Older history may simply not be there. If `extract_recent` lacks a `coverage` field, every "where did the last 6 months go" bug looks like *our* bug.
- **WhatsApp.app has NO AppleScript dictionary.** Send path is `whatsapp://send?...` deep-link + `System Events keystroke return`. Plan time accordingly — most fragile component.
- **TCC is the project's biggest UX risk, not the MCP protocol or send path.** Three permission buckets, each granted to the requesting binary. If the roadmap doesn't budget for the signed `.pkg` launcher in Phase 3 (or earlier), users will rage-quit during install.
- **WhatsApp ToS prohibits "automated means"; users have been banned for >20–50/day.** Conservative rate-limit defaults, README disclaimer, and default-off send are MUST-have, not polish.
- **JID/LID is not just a display detail.** Plan a `Jid` type with kind enum + `LID.sqlite` resolution from day one; retrofitting is painful.
- **`stdout` is the JSON-RPC transport.** Single `print()` corrupts the protocol. CI test in Phase 0; lint-block `print`; wrap noisy imports with `contextlib.redirect_stdout(sys.stderr)`.
- **The 25k-token MCP output cap is real and trips on the first call to a busy group's `extract_recent`.** Pagination and char-cap are Phase 1 acceptance, not polish.
- **Reader and Sender must NEVER import each other.** They isolate the two highest-volatility surfaces. Tool Layer JSON contract stays stable across either kind of breakage.
- **Don't try to use WhatsApp's `fts/ChatSearchV5f.sqlite`** — custom `wa_tokenizer` only loaded inside WhatsApp.app. Build your own SQLite FTS5 shadow index.
- **"Send confirmation by default" is Phase 2 acceptance, not stretch goal.** MCP elicitation must show resolved chat name + recipient JID/LID + body verbatim before send fires.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Python/MCP/sqlite/uvx all standard 2026 picks |
| Features | HIGH | 5+ reference projects cross-corroborate the table-stakes set |
| Architecture | HIGH | DB layout, schema, journal mode, lack-of-AS-dictionary, URL schemes — all VERIFIED LIVE |
| Pitfalls | HIGH | Most map to specific GitHub issues, CVEs, or Apple docs |

**Overall:** HIGH for shipping v1 along the suggested phase plan. MEDIUM specifically on long-term Sender durability (P12) and TCC propagation on macOS 26 Tahoe (P4 + P15) — both flagged for Phase 2/3 deeper research.

---
*Research completed: 2026-05-13*
*Ready for roadmap: yes*

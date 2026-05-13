# Roadmap: WhatsApp MCP

**Created:** 2026-05-13
**Granularity:** coarse (3–5 phases, 1–3 plans each)
**Mode:** mvp (every phase delivers an end-to-end user-visible capability)
**Parallelization:** true
**Coverage:** 37/37 v1 requirements mapped ✓

## Phases

- [ ] **Phase 0: Setup & Permissions Skeleton** — Installable MCP server that diagnoses its own permissions and protocol hygiene, end-to-end from Claude Desktop
- [ ] **Phase 1: Read MVP (`--read-only`)** — User can list, read, search, and inspect WhatsApp chats from Claude Desktop with all read tools live behind the `--read-only` flag
- [ ] **Phase 2: Send (UI-automation, behind safety guardrails)** — User can send a single text message to a resolved chat, gated by elicitation confirmation, rate limiter, and audit log
- [ ] **Phase 3: Hardening & Distribution** — End-user can install via signed `.pkg` / brew, permissions persist across upgrades, search is FTS5-backed, and a tested-versions matrix documents known-good WhatsApp Desktop builds

## Phase Details

### Phase 0: Setup & Permissions Skeleton
**Goal:** A user can install the MCP server in `claude_desktop_config.json`, launch it, call `doctor`, and get a structured, actionable report about whether the macOS permissions and protocol hygiene needed by later phases are in place.
**Mode:** mvp
**Depends on:** Nothing (first phase)
**Requirements:** SETUP-01, SETUP-02, SETUP-03, SETUP-04, SETUP-05, DIST-01
**Success Criteria** (what must be TRUE):
  1. A developer can add a single-line `uvx whatsapp-mcp` entry to `claude_desktop_config.json`, restart Claude Desktop, and the server registers as an MCP stdio server with no JSON-RPC protocol errors visible in `~/Library/Logs/Claude/mcp-server-whatsapp.log`.
  2. From Claude Desktop, the user can invoke a `doctor`-style preflight tool (or equivalent ping) and receive a structured response — never a Python traceback — that names which macOS permissions are missing (`FullDiskAccessRequired` / `AutomationPermissionRequired` / `AccessibilityPermissionRequired`) along with the exact binary path to grant and a `x-apple.systempreferences:` deep-link.
  3. CI runs a stdout-purity test that spawns the server, sends `initialize` plus a sample tool call, and fails if any non-JSON-RPC byte hits stdout; ruff's `T201` rule blocks `print` statements at lint time.
  4. The published README opens with a WhatsApp ToS / account-ban disclaimer and a 60-second `uvx`-based quickstart, framed as "this is your personal account, not a bot."
**Plans:** 5 plans
Plans:
- [ ] 00-01-PLAN.md — Project skeleton, pyproject.toml, uv-managed deps
- [ ] 00-02-PLAN.md — FastMCP stdio server, CLI entry point, exception hierarchy, Pydantic models
- [ ] 00-03-PLAN.md — Permission probes (FDA / Automation / Accessibility) and the doctor MCP tool
- [ ] 00-04-PLAN.md — Test suite — stdout purity, doctor registration, exception shape, probe mocking, REL-05 isolation
- [ ] 00-05-PLAN.md — GitHub Actions CI + release.yml + README + claude_desktop_config.json example
**Avoids pitfalls:** P7 (stdout pollution), P4 (wrong-binary FDA), P13 (sandboxed-launch automation strip), P14 (ToS disclaimer), P15 (TCC churn — documented as a Phase 3 problem, flagged here).

### Phase 1: Read MVP (`--read-only`)
**Goal:** A user can run the MCP server in `--read-only` mode and, from Claude Desktop, perform every v1 read operation against a real WhatsApp Desktop installation — list chats, read a chat, extract recent history, search messages and contacts, get group metadata, get reply-thread context, and run `doctor` — with bounded latency, paginated results, JID/LID dedup, and tombstone filtering.
**Mode:** mvp
**Depends on:** Phase 0
**Requirements:** SETUP-06, READ-01, READ-02, READ-03, READ-04, READ-05, READ-06, READ-07, READ-08, READ-09, DATA-01, DATA-02, DATA-03, DATA-04, REL-01, REL-02, REL-03, REL-04, REL-05, DIAG-01, DIAG-02
**Success Criteria** (what must be TRUE):
  1. With `--read-only` set, every send tool is unregistered (or refuses with a structured error) and every remaining tool is annotated `readOnlyHint:true`; this is verifiable by a `tools/list` MCP call.
  2. From Claude Desktop, calling `read_chat` on a chat with thousands of messages returns a paginated JSON response under 60k characters within the 5-second per-tool timeout, with a `next_cursor` for the next page and a `coverage` field naming the time range actually present in the local DB.
  3. `extract_recent` against an active group returns deterministic, JID/LID-deduplicated messages with Cocoa→Unix-converted timestamps, defaults `include_deleted=False` (tombstones and `ZMESSAGETYPE=14` rows filtered), and surfaces media as `MediaRef` (filename + mime + absolute local_path) — never inlined binary.
  4. `doctor` returns a structured preflight report (DB path resolved, FDA / Automation / Accessibility status, schema fingerprint OK, WhatsApp.app version, last-message timestamp, `coverage` summary) and remains callable even when other read tools would fail because of a missing permission or unsupported schema version.
  5. The Reader package never imports the Sender package (and vice versa); a unit test asserts this isolation, and concurrent read calls during active WhatsApp writes succeed without `database is locked` errors.
**Plans:** TBD
**Avoids pitfalls:** P1 (cache-vs-truth via `coverage`), P2 (schema/path drift via fingerprint + `doctor`), P3 (RO WAL connection), P8 (async wrapping + per-tool timeouts), P9 (char-cap + pagination + `_meta`), P10 (tombstone filter), P11 (JID/LID dedup).

### Phase 2: Send (UI-automation, behind safety guardrails)
**Goal:** A user can authorize the MCP to leave `--read-only` mode and, from Claude Desktop, send a single text message to a chat that has been resolved to an opaque `chat_id`, with mandatory elicitation confirmation showing the resolved chat name and body verbatim, a conservative rate limiter, an audit log, post-hoc DB verification, and structured errors on every failure mode.
**Mode:** mvp
**Depends on:** Phase 1
**Requirements:** SEND-01, SEND-02, SEND-03, SEND-04, SEND-05, SEND-06, SEND-07, SEND-08
**Success Criteria** (what must be TRUE):
  1. `send_message` accepts only an opaque `chat_id` previously returned by `search_contacts` or `list_chats` — passing a free-form name string returns a structured `InvalidChatId` error and never sends anything.
  2. Before any send fires, the user sees an MCP elicitation prompt that displays the resolved chat name, recipient JID/LID, and the message body verbatim; declining cancels cleanly with a structured cancellation result, and the cross-chat-quote heuristic surfaces an extra warning when the body matches content recently read from a different chat.
  3. A successful 1:1 send via the `whatsapp://send?phone=…&text=…` deep-link + `osascript` keystroke-return path completes within the 15s per-tool timeout, is verified post-hoc by polling `ZWAMESSAGE` for a new outgoing row matching the body within 10s, and returns the resulting `ZSTANZAID` as `message_id`; group-chat sends use the documented search-and-click fallback and either succeed or return a structured error.
  4. The default rate limiter (5 sends/min, 30 sends/day) trips with a structured error response — never silently dropping — and every send attempt (success or failure) appends a single line to `~/Library/Logs/whatsapp-mcp/audit.log` (mode 0600) recording timestamp, resolved chat_id + name, body hash, and outcome.
  5. The pre-send AX-API state assertion verifies the focused window's chat header matches the resolved chat name and aborts on mismatch (defending against the invisible-LRM trap and wrong-chat fuzzy-search class of bugs).
**Plans:** TBD
**Avoids pitfalls:** P5 (wrong-chat fuzzy send), P6 (LLM misuse — fan-out / leak / prompt injection), P12 (AppleScript fragility), P13 (Automation permission self-check), P14 (TOS / ban — conservative defaults).

### Phase 3: Hardening & Distribution
**Goal:** An end user on a fresh macOS install can download a signed `.pkg` (or `brew install`), grant Full Disk Access + Accessibility + Automation to a single binary at a stable path, and reach a first successful `read_chat` and `send_message` from Claude Desktop in under 10 minutes — and that grant survives subsequent upgrades without re-prompting.
**Mode:** mvp
**Depends on:** Phase 2
**Requirements:** DIST-02, DIST-03
**Success Criteria** (what must be TRUE):
  1. A clean macOS machine can install the project via a Developer-ID-signed, notarized `.pkg` (and/or `brew install whatsapp-mcp`) that drops the launcher binary at a stable absolute path (e.g. `/usr/local/bin/whatsapp-mcp`), and re-installing or upgrading does not require re-granting any TCC permission.
  2. The README's quickstart documents platform requirements (macOS only, WhatsApp Desktop Catalyst build, Python 3.12+ when user-installed), enumerates the three TCC buckets (FDA / Accessibility / Automation) with screenshots, and points users at both the `.pkg`/brew install path (recommended) and the `uvx` path (developer-only, with the TCC-churn caveat).
  3. A `tested_versions.md` document lists known-good WhatsApp Desktop versions and a `RUN_LIVE_WHATSAPP=1`-gated integration smoke suite exercises `doctor`, one read tool, and one send tool against a real WhatsApp install before each release.
  4. `search_messages` is upgraded from the v0.1 `LIKE` implementation to an FTS5 shadow index (built lazily on first run, refreshed incrementally) — verifiable by ranked, sub-second results on a 100k-message corpus where v0.1 LIKE was visibly slow.
**Plans:** TBD
**Avoids pitfalls:** P15 (pipx/uvx TCC churn — solved by stable signed-launcher path), reinforces P2 (schema fingerprint via tested_versions + smoke suite), P4 (FDA documented per binary), P13 (Automation entitlement bundled in `.pkg`).

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 0. Setup & Permissions Skeleton | 0/5 | Planned | - |
| 1. Read MVP (`--read-only`) | 0/0 | Not started | - |
| 2. Send (UI-automation, guardrails) | 0/0 | Not started | - |
| 3. Hardening & Distribution | 0/0 | Not started | - |

## Coverage Summary

| Phase | Requirement count | IDs |
|-------|-------------------|-----|
| Phase 0 | 6 | SETUP-01, SETUP-02, SETUP-03, SETUP-04, SETUP-05, DIST-01 |
| Phase 1 | 21 | SETUP-06, READ-01..09, DATA-01..04, REL-01..05, DIAG-01..02 |
| Phase 2 | 8 | SEND-01..08 |
| Phase 3 | 2 | DIST-02, DIST-03 |
| **Total** | **37** | All v1 requirements mapped, none orphaned ✓ |

## Notes

- **READ-04 dual-implementation:** The requirement explicitly allows LIKE for v0.1 and mandates FTS5 for v1.0. The REQ is owned by Phase 1 (LIKE ships and unblocks `search_messages` end-to-end); the FTS5 upgrade is implementation work in Phase 3 covered by DIST success criterion 4. This is intentional — splitting one REQ across two phases would muddle ownership.
- **Phase 0 as a valid MVP slice:** Phase 0 ships a runnable MCP server with `doctor` (and/or `ping`) only. User-visible value: "I installed it and it diagnoses itself end-to-end from Claude Desktop." This satisfies the MVP rule that every phase delivers a vertical slice — even if the only capability is self-diagnosis, it is observable from the Claude Desktop client.
- **Phase 1 is intentionally large** (21 reqs) because the Read MVP is a single coherent vertical slice — every reader/data/reliability/diagnostics requirement must land together for `--read-only` mode to be honestly usable. Splitting it would create non-shippable intermediate states.
- **Sender↔Reader isolation** is a cross-cutting REL-05 requirement asserted in Phase 1 and re-asserted (by construction) when Sender lands in Phase 2.
- **Phase 3 carries only 2 explicit REQs** but substantial hidden work (FTS5 shadow index, smoke suite, signed-pkg pipeline). This is honest: those activities serve DIST-02 and DIST-03, plus reinforce Phase 1/2 reqs, rather than constituting new requirements.

---
*Roadmap created: 2026-05-13*

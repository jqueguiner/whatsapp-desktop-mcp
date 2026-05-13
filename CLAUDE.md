# WhatsApp MCP — Claude Working Notes

## What this project is

A local MCP (Model Context Protocol) server that controls the macOS **WhatsApp Desktop** app for an LLM client (Claude Desktop / Claude Code). Reads message history from WhatsApp's local SQLite store, sends messages by driving the running Desktop app via `whatsapp://send` deep-link + `osascript`. Strictly local, single-user, single Mac.

**Core Value:** an LLM agent can read and write the user's WhatsApp Desktop the same way the user can — no separate auth, no API key, no business approval — through a small set of MCP tools.

## Stack (locked)

- Python 3.12 + `mcp[cli]==1.27.1` (FastMCP, stdio)
- stdlib `sqlite3` opened with `?mode=ro` URI flag (never `immutable=1`)
- `subprocess` + `osascript` for the send path (WhatsApp.app has **no AppleScript dictionary** — `sdef` returns -192)
- `pydantic >=2.7` for typed tool contracts
- `ruff`, `mypy`, `pytest`, `pytest-subprocess`
- Distribution: `uvx whatsapp-mcp` (dev), signed `.pkg` at `/usr/local/bin/whatsapp-mcp` for end users

Anti-stack (do NOT introduce): `whatsmeow` / Baileys / WhatsApp Cloud API / `aiosqlite` / SQLAlchemy / `pywhatkit` / Selenium / any HTTP REST surface.

## Hard architectural rules

1. **Reader (`reader/`) and Sender (`sender/`) MUST NOT import each other.** They isolate the two highest-volatility surfaces (DB schema vs UI). The tool layer is the only integration point.
2. **`stdout` is the JSON-RPC channel.** Every byte on stdout MUST be a JSON-RPC frame. Logging goes to stderr. `print` is lint-blocked (`ruff T201`). CI test asserts stdout purity after `initialize`.
3. **Never write to `ChatStorage.sqlite`.** WhatsApp owns the writer. Reads only, short-lived connections, `?mode=ro`.
4. **Never inline media bytes in tool responses.** Surface attachments as `MediaRef { filename, mime, local_path, size_bytes }`.
5. **No HTTP / TCP / UDP listener.** Stdio only. `lharries/whatsapp-mcp` was hit by exactly this — path-traversal CVE class.
6. **Never compare JID strings directly.** A person may appear as `<phone>@s.whatsapp.net` and `<lid>@lid` in different chats. Use the `Jid` type and resolve via `LID.sqlite`.
7. **Send is `destructiveHint:true` and gated by MCP elicitation confirmation by default.** Rate limit 5/min, 30/day default. Audit log to `~/Library/Logs/whatsapp-mcp/audit.log` mode 0600. No multi-recipient tool.
8. **Every read tool returns a `coverage` field.** The DB is a sync cache, not a source of truth.

## Verified facts (live, 2026-05-13)

- DB: `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite` (WAL mode, ~89 MB on this Mac, WhatsApp 26.16.74 / macOS 26.4)
- Sibling DBs: `ContactsV2.sqlite`, `LID.sqlite`, `fts/ChatSearchV5f.sqlite` (WhatsApp's own FTS index — uses a custom `wa_tokenizer` only loaded inside WhatsApp.app, **unusable from our process**)
- Schema: Core Data Z-prefixed tables (`ZWACHATSESSION`, `ZWAMESSAGE`, `ZWAGROUPINFO`, `ZWAGROUPMEMBER`, `ZWAMEDIAITEM`, `ZWAMESSAGEINFO`)
- Time: dates are **Cocoa epoch** — add `978_307_200` to convert to Unix
- Send: deep-link `whatsapp://send?phone=<E164>&text=<urlencoded>` works for 1:1; group sends require search-and-click fallback
- Three permissions required, each granted to the *requesting binary*: Full Disk Access, Accessibility, Apple Events / Automation. They do NOT inherit through `Claude.app → uvx → python`.

## GSD workflow

This project uses [Get-Shit-Done (GSD)](https://github.com/...) for planning and execution.

**Planning artifacts** (in `.planning/`):
- `PROJECT.md` — what we're building, core value, constraints, decisions
- `REQUIREMENTS.md` — v1 REQ-IDs by category, traceability to phases
- `ROADMAP.md` — 4 coarse phases (Setup → Read MVP → Send → Hardening), MVP mode (every phase is a vertical slice)
- `STATE.md` — current focus, last action
- `research/` — STACK / FEATURES / ARCHITECTURE / PITFALLS / SUMMARY (ground-truth verified live; consult before changing the stack or send path)
- `config.json` — workflow settings (yolo, coarse, parallel, balanced model profile, research+plan-check+verifier on)

**When the user invokes a GSD command, use the matching skill:**
- `/gsd-plan-phase N` — produce `.planning/phases/N-<slug>/PLAN.md` for phase N
- `/gsd-execute-phase N` — execute the planned phase with atomic commits
- `/gsd-discuss-phase N` — pre-plan questioning to gather context
- `/gsd-verify-work` — validate after a phase completes
- `/gsd-progress` — situational dispatch when unsure
- `/gsd-help` — full skill list

**Do NOT skip the workflow gates** (research → plan → check → execute → verify) unless the user explicitly says "skip planning" or invokes `/gsd-quick` / `/gsd-fast`.

**Atomic commits.** Every phase's planning artifact and every executed plan ships as its own commit. Don't batch.

## Working preferences inferred from setup

- YOLO mode is on — auto-advance through gates without asking unless something changes scope
- Granularity is coarse — don't fragment phases below the 4 already defined
- Run plans in parallel where independent
- Commit `.planning/` to git (it lives alongside source)
- Balanced model profile — Sonnet for most subagents

## Where to read first when picking up new work

1. `.planning/STATE.md` — current focus
2. `.planning/ROADMAP.md` — phase you're in
3. `.planning/research/SUMMARY.md` — TL;DR of everything verified about WhatsApp Desktop's local environment
4. `.planning/PROJECT.md` — values + constraints if a tradeoff comes up

If you're about to touch the DB schema or the send path, read the corresponding research file (`ARCHITECTURE.md` or `PITFALLS.md`) first — both are based on live probing of the user's actual machine, not training data.

---
*Generated 2026-05-13 by `/gsd-new-project --auto`. Update as the project evolves.*

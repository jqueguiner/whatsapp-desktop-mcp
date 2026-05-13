# WhatsApp MCP — Desktop Control Server

## What This Is

An MCP (Model Context Protocol) server that controls the WhatsApp Desktop application on macOS so an LLM client (Claude Desktop, Claude Code, etc.) can read group/thread content, search conversations, send messages, and extract recent message history (e.g., "last 4 hours of #group-x") through standard MCP tools. Target user: a developer/power user who already has WhatsApp Desktop authenticated and wants programmatic access from an AI agent without integrating the official WhatsApp Business API.

## Core Value

An LLM agent can read and write the user's WhatsApp Desktop the same way the user can — no separate auth, no API key, no business approval — through a small set of MCP tools.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] MCP server runs locally and registers with Claude Desktop / Claude Code via stdio
- [ ] Tool: `list_chats` — enumerate groups + 1:1 threads with last-activity timestamp
- [ ] Tool: `read_chat` — read messages from a specific chat (by name or id), bounded by count or time window
- [ ] Tool: `extract_recent` — return all messages from a chat within last N hours
- [ ] Tool: `search_messages` — full-text search across chats with sender/date filters
- [ ] Tool: `send_message` — send text message to a chat (group or contact)
- [ ] Tool: `search_contacts` — find chats/contacts by name fragment
- [ ] Reads the WhatsApp Desktop local SQLite store on macOS for history (preferred over scraping the UI)
- [ ] Sends messages by driving the WhatsApp Desktop app (AppleScript / accessibility / native automation) when SQLite write is unsafe
- [ ] Returns structured JSON (sender, timestamp, body, chat_id, message_id, media flags)
- [ ] Handles attachments: surface filename + mime + local path, do not inline binary blobs
- [ ] Documented installation: install MCP server, point Claude Desktop config at it, ensure WhatsApp Desktop is logged in

### Out of Scope

- WhatsApp Business API / Cloud API integration — defeats the point (user wants personal account)
- Multi-account / multi-device orchestration — v1 is single logged-in desktop session
- Web/mobile clients (whatsapp.com, iOS, Android) — desktop only
- Hosting on a remote server — strictly local; runs on the same Mac as WhatsApp Desktop
- Bypassing WhatsApp encryption / decrypting other users' chats — only what the logged-in user can already see
- Voice/video call control — text + media metadata only
- Reactions, polls, status updates — defer to v2
- Sending media (images/files) — defer to v2 (read-only attachments first)
- Cross-platform (Windows/Linux WhatsApp Desktop) — macOS only for v1

## Context

- WhatsApp Desktop on macOS stores message history in a local SQLite database under `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/` (path subject to verification during research).
- macOS app sandboxing + Full Disk Access permission likely required to read that path from a non-WhatsApp process.
- Existing community projects (`lharries/whatsapp-mcp`, `whatsmeow` Go library) use the multi-device protocol over the network instead of touching Desktop — that's a different design. This project specifically wants to ride the already-running Desktop session.
- MCP spec (Anthropic, 2024) standardizes tool/resource exposure to LLM clients via stdio or HTTP+SSE. Python SDK (`mcp`) and TypeScript SDK (`@modelcontextprotocol/sdk`) both available.
- User has zero appetite for Meta business onboarding flow — that ruled out Cloud API path.

## Constraints

- **Platform**: macOS only (v1) — driven by user's hardware; rely on WhatsApp Desktop binary location, AppleScript, and macOS-specific SQLite path.
- **Auth**: Piggyback on the user's existing WhatsApp Desktop session — no separate login, no QR scan inside the MCP.
- **Security**: All data stays on local machine. MCP server must not phone home or upload chat content anywhere except back to the connected MCP client.
- **Permissions**: Will require Full Disk Access (for SQLite read) and Accessibility / Automation permission (for AppleScript send) granted to whichever process runs the MCP server.
- **Stability**: WhatsApp Desktop schema and DB path can change between releases — must isolate the path/schema knowledge so a single update fixes breakage.
- **Performance**: Tool calls must return within a few seconds for typical chat sizes (≤ 10k messages); avoid loading entire DB into memory per call.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| MCP over plain CLI/REST | Direct integration with Claude Desktop / Code is the explicit goal | — Pending |
| Drive WhatsApp Desktop app instead of WhatsApp Web protocol | User insists on controlling the already-installed Desktop app, not a separate headless session | — Pending |
| Read history from local SQLite, send via AppleScript/UI automation | Reads are far cheaper and more reliable from the DB; sends require actually clicking through the app to keep behavior identical to what the user does manually | — Pending |
| macOS-only v1 | User's environment; cross-platform multiplies the surface area without adding value yet | — Pending |
| Python implementation (likely) | MCP Python SDK is mature, AppleScript bridges (osascript / pyobjc) are first-class on macOS, SQLite read is trivial in Python | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-13 after initialization*

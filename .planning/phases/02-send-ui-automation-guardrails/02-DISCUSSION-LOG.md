# Phase 2: Send (UI-automation, guardrails) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-13
**Phase:** 2-Send (UI-automation, guardrails)
**Mode:** --auto (recommended-default for every gray area; no AskUserQuestion calls)
**Areas discussed:** send mechanism, pyobjc dependency, confirmation UX, rate limiter scope, audit log format, group-send v1-vs-v1.1, cross-chat-quote heuristic, post-hoc verify polling, --read-only default

---

## Send mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Deep-link primary + AX preflight + search-and-click group fallback | 1:1 = `whatsapp://send?phone=&text=`; group = UI-script search-and-click; AX state assertion before keystroke. | ✓ |
| Search-and-click for everything | Uniform path but slower and more fragile for 1:1 | |
| Full Accessibility-API send (no keystroke) | Most robust; pulls in AX UI mapping that breaks across Catalyst versions. v2 stretch goal. | |

**Auto choice:** Deep-link primary + AX preflight + search-and-click fallback (recommended).
**Rationale:** Architecture verified live — WA exposes URL scheme but no AppleScript dictionary. Deep-link is the cheapest, most reliable 1:1 path; group send needs a fallback because WhatsApp doesn't accept group JIDs in URLs.

---

## PyObjC dependency

| Option | Description | Selected |
|--------|-------------|----------|
| Add now (Phase 2 v0.1) | `pyobjc-core` + `pyobjc-framework-Cocoa` + `pyobjc-framework-ApplicationServices`; ~30MB wheels. Required for SEND-04 AX state assertion. | ✓ |
| Defer to v1.x | Ship Phase 2 with a degraded P5 mitigation (no AX assertion); rely solely on chat_id opacity. Account-ban consequence if a wrong-chat slip happens. | |

**Auto choice:** Add now (recommended).
**Rationale:** SEND-04 is non-negotiable given the account-ban consequence class.

---

## Confirmation UX

| Option | Description | Selected |
|--------|-------------|----------|
| MCP elicitation always-on; opt-out via env var with audit warning | Every send asks; `WHATSAPP_MCP_SKIP_CONFIRM=1` skips with audit-log entry `confirm_skipped: true`. | ✓ |
| Always-on; no opt-out | Maximally safe but blocks scripted/non-interactive use cases. | |
| Sticky-session confirmation | "Confirmed once for this chat in last 5 min, skip subsequent" — defeats per-send safety. | |

**Auto choice:** Always-on default with env-var opt-out (recommended).
**Rationale:** Per-send confirmation is the load-bearing safety; opt-out keeps power users unblocked but every skip is observable in the audit log.

---

## Rate limiter scope

| Option | Description | Selected |
|--------|-------------|----------|
| Persistent SQLite at `~/Library/Application Support/whatsapp-mcp/rate-limit.db` | Survives restart; daily limit can't be bypassed by killing the server. | ✓ |
| Memory-only | Cheaper but a restart resets the day-counter — defeats the daily cap. | |
| Both (memory primary + persistent backstop) | Over-engineered for v0.1; persistent IS the source of truth. | |

**Auto choice:** Persistent SQLite (recommended).
**Rationale:** Daily limit is the WhatsApp-account-ban defense; restarts must NOT bypass it. SQLite single file is simple enough.

---

## Audit log format

| Option | Description | Selected |
|--------|-------------|----------|
| JSONL at `~/Library/Logs/whatsapp-mcp/audit.log` mode 0600 | One JSON object per line; machine-grep-able; line-buffered. Body stored as SHA-256 only. | ✓ |
| Custom text format | Easier human read but breaks structured analysis. | |
| Body verbatim in log | UX investigation easier; massive privacy / exfil risk if file leaks. | |

**Auto choice:** JSONL with body SHA-256 (recommended).
**Rationale:** SEND-06 fixes path; JSONL aligns with standard observability tooling; SHA-256 lets investigators confirm body matches without storing plaintext.

---

## Group-send v1 vs v1.1

| Option | Description | Selected |
|--------|-------------|----------|
| Ship in Phase 2 v1.0 with `is_experimental=true` | UI-script search-and-click; documented brittleness; falls back to "groups unsupported" if execution-spike fails. | ✓ |
| Defer to v1.1 | Ship 1:1 only; cleaner v0.1 release; group send blocked behind another phase. | |

**Auto choice:** Ship with experimental flag (recommended).
**Rationale:** ROADMAP Phase 2 SC3 explicitly mentions group sends. Experimental flag tells callers what they're getting.

---

## Cross-chat-quote heuristic

| Option | Description | Selected |
|--------|-------------|----------|
| Session-scoped source-attribution; 40-char substring threshold; warning in elicitation | Read tools record body→chat_id; send tool checks for cross-chat substring matches. ~30 min sliding window. In-memory only. | ✓ |
| Exact-body match only | Misses partial quotes; high false-negative rate. | |
| Block hard on detection | False positives (legitimate forwards) would block real workflows. | |

**Auto choice:** Source-attribution + warning (recommended).
**Rationale:** SEND-07 mandates the heuristic; warning rather than block respects legitimate forwards while flagging the prompt-injection vector.

---

## Post-hoc verification polling

| Option | Description | Selected |
|--------|-------------|----------|
| 250 ms × 40 polls (up to 10 s); match `ZISFROMME=1` + body + ZMESSAGEDATE > started | Tight-grain confirmation; matches WA's typical sync latency on the user's machine. | ✓ |
| Single poll at 5 s | Misses fast syncs and timed-out sends. | |
| Exponential backoff (250→500→1s→2s up to 10 s) | Wastes time on the typical-fast case. | |

**Auto choice:** 250 ms × 40 (recommended).
**Rationale:** SEND-08 specifies "within 10s"; tight-grain wins for the typical case; ZISFROMME flag observed live in user's DB schema.

---

## --read-only default for v0.1

| Option | Description | Selected |
|--------|-------------|----------|
| Default `--read-only=True`; user explicitly runs `--no-read-only` to enable sends | Conservative for v0.1; documented in README. | ✓ |
| Default `--read-only=False` once Phase 2 ships | Sends work out of the box; lower friction. | |

**Auto choice:** Stay default-read-only (recommended).
**Rationale:** Phase 0 D-08 carry-over (default-on for v0.1, default-off considered for v1.0); aligns with the conservative posture for the highest-risk phase.

---

## Claude's Discretion

- AX-API exact selectors for the focused chat header (depth of `AXTitle` walk, fallback paths if Catalyst minor version moves the element)
- Exact wording of the elicitation prompt body display
- Whether to ship `WHATSAPP_MCP_DRY_RUN=1` env var (recommended yes; trivial)
- Whether to ship `whatsapp-mcp send-test` CLI subcommand (recommended yes; trivial smoke-test ergonomics)

## Deferred Ideas

- Send media (images/files) — v2 (SEND2-01)
- Draft + confirm preview — v2 (SEND2-02)
- Reactions / polls / edit / delete — v2 (SEND2-03)
- Full AX-API send (replacing keystroke) — v2 (SEND2-04)
- Group send via deep-link (when WhatsApp supports group JIDs in URL scheme) — v2 (SEND2-05)
- Audit log rotation — Phase 3 ops polish

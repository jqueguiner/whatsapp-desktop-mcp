# Project State: WhatsApp MCP

**Last updated:** 2026-05-13 (after roadmap creation)

## Project Reference

- **Project:** WhatsApp MCP — Desktop Control Server
- **Project doc:** `.planning/PROJECT.md`
- **Requirements:** `.planning/REQUIREMENTS.md` (37 v1 requirements)
- **Roadmap:** `.planning/ROADMAP.md` (4 phases, coarse granularity)
- **Research bundle:** `.planning/research/SUMMARY.md` + STACK / FEATURES / ARCHITECTURE / PITFALLS
- **Mode:** mvp (every phase delivers an end-to-end user-visible capability)
- **Granularity:** coarse (3–5 phases, 1–3 plans each)
- **Parallelization:** enabled

## Core Value (one sentence)

An LLM agent can read and write the user's WhatsApp Desktop the same way the user can — no separate auth, no API key, no business approval — through a small set of MCP tools.

## Current Focus

- **Active phase:** Phase 0 — Setup & Permissions Skeleton
- **Active plan:** None yet (run `/gsd-plan-phase 0` to draft)
- **Status:** Roadmap defined; awaiting first phase plan
- **Next action:** `/gsd-plan-phase 0`

## Progress

```
[                    ] 0/4 phases complete
Phase 0: ▢ Setup & Permissions Skeleton  (Not started)
Phase 1: ▢ Read MVP (`--read-only`)      (Not started)
Phase 2: ▢ Send (UI-automation, guardrails) (Not started)
Phase 3: ▢ Hardening & Distribution      (Not started)
```

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 0. Setup & Permissions Skeleton | 0/0 | Not started | - |
| 1. Read MVP (`--read-only`) | 0/0 | Not started | - |
| 2. Send (UI-automation, guardrails) | 0/0 | Not started | - |
| 3. Hardening & Distribution | 0/0 | Not started | - |

## Performance Metrics

- **Time spent so far:** Initialization + research + requirements + roadmap (one session, 2026-05-13)
- **Phases completed:** 0 / 4
- **Plans completed:** 0 / 0 (none planned yet)
- **Requirements validated:** 0 / 37

## Accumulated Context

### Key Decisions (carried from PROJECT.md)

| Decision | Rationale | Status |
|----------|-----------|--------|
| MCP over plain CLI/REST | Direct integration with Claude Desktop / Code is the explicit goal | Pending validation |
| Drive WhatsApp Desktop app instead of WhatsApp Web protocol | User insists on controlling the already-installed Desktop app, not a separate headless session | Pending validation |
| Read history from local SQLite, send via AppleScript/UI automation | Reads cheap from DB; sends via UI keep behavior identical to manual usage | Pending validation |
| macOS-only v1 | User's environment; cross-platform multiplies surface area | Pending validation |
| Python implementation (`mcp[cli]==1.27.1`, Python 3.12, stdlib `sqlite3`, `subprocess`+`osascript`) | MCP Python SDK is mature; AppleScript bridges first-class on macOS; SQLite read trivial in Python | Pending validation |

### Open Questions (carried from research SUMMARY §7)

1. Exact `ZFLAGS` bit semantics for tombstoned messages — needs `is_tombstone(row)` predicate tested on a fresh second machine before v1.0 (Phase 1).
2. Stability of `ZSESSIONTYPE` enum values across WhatsApp Catalyst minor versions (Phase 1 — verify on second machine).
3. `@lid` ↔ phone resolution completeness in stricter-privacy groups (Phase 1).
4. Lower/upper `Z_VERSION` bounds the v1 schema queries support (Phase 1, refined in Phase 3 `tested_versions.md`).
5. Group-send fallback feasibility — deep-link works for 1:1; group sends need search-and-click (Phase 2 spike).
6. Does `.sqlite-wal` need to exist for `mode=ro` to work in all states? Edge case for `doctor` (Phase 1).
7. Whether keystroke-injected text handles emoji and non-BMP Unicode reliably; URL-encoded path may sidestep (Phase 2).

### Blockers

None.

### Todos / Carry-overs

- (Phase 0 planning) Decide whether the Phase 0 minimum tool surface is `doctor` only, or `doctor` + `ping`. Roadmap success criteria allow either.
- (Phase 0 planning) Decide on `--read-only` default for v0.1 vs v1.0 (research suggests default-on for v0.1, default-off with explicit opt-in for v1.0).
- (Phase 2 planning) Decide whether the Accessibility-API send path (pyobjc) lands in Phase 2 v1.0 or is deferred to v1.x — affects pyobjc dep and TCC entitlements.
- (Phase 3 planning) Decide between signed `.pkg` only, brew formula only, or both; affects scope of the distribution plan.

## Session Continuity

### Last Session

- Initialized PROJECT.md, REQUIREMENTS.md, and full research bundle (SUMMARY, STACK, FEATURES, ARCHITECTURE, PITFALLS).
- Created ROADMAP.md (4 coarse phases with 100% requirement coverage) and this STATE.md.

### Next Session

- Run `/gsd-plan-phase 0` to decompose Phase 0 (Setup & Permissions Skeleton) into executable plans.
- Granularity = coarse → expect 1–3 plans for Phase 0.
- Likely plan candidates: (a) MCP stdio server skeleton + stdout-hygiene CI, (b) `doctor` preflight tool with structured permission errors, (c) README + ToS disclaimer + uvx-publish path.

### Files Most Recently Touched

- `.planning/ROADMAP.md` (created)
- `.planning/STATE.md` (created)
- `.planning/REQUIREMENTS.md` (Traceability section refreshed)

---
*State initialized: 2026-05-13 after roadmap creation*

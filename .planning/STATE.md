# Project State: WhatsApp MCP

**Last updated:** 2026-05-13 (after Phase 0 Plan 01 executed, Wave 1 done)

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
- **Active plan:** Phase 0, Plan 01 complete; Wave 1 done. Wave 2 next (Plans 02..04 if independent, then Plan 05).
- **Status:** Skeleton landed (src-layout, pyproject.toml, ruff/mypy/pytest gates, uv.lock, MIT LICENSE, .gitignore, stub README). `uv sync --extra dev` and `uv build` both succeed.
- **Next action:** Continue `/gsd-execute-phase 0` Wave 2 — typically Plan 02 (FastMCP server + CLI + exception hierarchy + Pydantic models) is the next dependency root.
- **Resume file:** `.planning/phases/00-setup-and-permissions-skeleton/00-01-SUMMARY.md`

## Progress

```
[                    ] 0/4 phases complete
Phase 0: ◐ Setup & Permissions Skeleton  (In progress: 1/5 plans)
Phase 1: ▢ Read MVP (`--read-only`)      (Not started)
Phase 2: ▢ Send (UI-automation, guardrails) (Not started)
Phase 3: ▢ Hardening & Distribution      (Not started)
```

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 0. Setup & Permissions Skeleton | 1/5 | In progress | - |
| 1. Read MVP (`--read-only`) | 0/0 | Not started | - |
| 2. Send (UI-automation, guardrails) | 0/0 | Not started | - |
| 3. Hardening & Distribution | 0/0 | Not started | - |

## Performance Metrics

- **Time spent so far:** Initialization + research + requirements + roadmap + Phase 0 plan 01 (one session, 2026-05-13)
- **Phases completed:** 0 / 4
- **Plans completed:** 1 / 5 (Phase 0, Plan 01 — ~169 s, 3 commits, 15 files)
- **Requirements validated:** 0 / 37 (DIST-01 and SETUP-05 partially scaffolded; full validation in Plan 05)

| Plan | Duration (s) | Tasks | Files | Commits |
|------|--------------|-------|-------|---------|
| 00-01 Project skeleton, pyproject.toml, uv-managed deps | 169 | 3 | 15 | 3 |

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
- Gathered Phase 0 context via `/gsd-discuss-phase 0 --auto`: locked decisions on project layout (src-layout `whatsapp_mcp`), MCP framework (FastMCP decorators, mcp[cli]==1.27.1, stdio only), `doctor` scope (3 permission probes only — no schema/version probes), permission probe technique (try-and-catch on small real actions), CI (GitHub Actions on push/PR + release-on-tag PyPI via OIDC).
- Planned Phase 0 into 5 plans across 4 waves (`/gsd-plan-phase 0 --auto`).
- **Executed Phase 0 Plan 01 (Wave 1):** scaffolded the src-layout package (`whatsapp_mcp` with empty `permissions/`, `models/`, `tools/`, `reader/`, `sender/` subpackages), wrote `pyproject.toml` (hatchling, mcp[cli]==1.27.1, pydantic 2.x, ruff T201 + E,F,I,B,UP,TID, mypy --strict, pytest with `live` marker, `pyyaml>=6` added to dev for Plan 05 release.yml structural assertions), shipped `.gitignore` + MIT `LICENSE` + stub `README.md` (Rule-3 deviation so hatchling resolves `readme="README.md"`), and committed `uv.lock`. `uv sync --extra dev` and `uv build` both succeed; wheel ships `reader/` + `sender/` empty `__init__.py` files (REL-05 ship-shape). 3 atomic commits, ~169 s.

### Next Session

- Continue `/gsd-execute-phase 0` Wave 2: Plan 02 (FastMCP server + CLI + exception hierarchy + Pydantic models) is the next dependency root and unblocks Plans 03, 04, 05.

### Files Most Recently Touched

- `pyproject.toml`, `README.md`, `LICENSE`, `.gitignore`, `uv.lock` (created)
- `src/whatsapp_mcp/` package tree with 6 `__init__.py` files (created)
- `tests/` skeleton with 4 `__init__.py` files (created)
- `.planning/phases/00-setup-and-permissions-skeleton/00-01-SUMMARY.md` (created)
- `.planning/STATE.md`, `.planning/ROADMAP.md` (updated)

---
*State updated: 2026-05-13 after Phase 0 Plan 01 executed (Wave 1 done)*

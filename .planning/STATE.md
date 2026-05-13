# Project State: WhatsApp MCP

**Last updated:** 2026-05-13 (after Phase 0 Plan 04 executed, Wave 4 done)

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
- **Active plan:** Phase 0, Plans 01 + 02 + 03 + 04 complete; Wave 4 done. Plan 05 next (CI workflows + README + `claude_desktop_config.json` snippet).
- **Status:** Test suite gating Phase 0's invariants is live: 28 non-live tests pass in 0.86 s on the maintainer's Mac (well under the 30 s budget). The SETUP-03 CI gate (`tests/unit/test_stdout_purity.py`) spawns `python -m whatsapp_mcp` and asserts every stdout line is JSON-RPC 2.0 after a full `initialize → notifications/initialized → tools/list → tools/call doctor` handshake. The doctor-registration test (`tests/unit/test_doctor_tool.py`) introspects `mcp.list_tools()` and asserts exactly one tool named `doctor` with `readOnlyHint=True` (D-08 import-by-name guard). The frozen-exception-surface tests (`tests/unit/test_exceptions.py`) lock in D-12 — Phase 1's `from whatsapp_mcp.exceptions import FullDiskAccessRequired, ...` lines cannot silently rename anything. The REL-05 isolation tests (`tests/unit/test_isolation.py`) are vacuous now but gain teeth in Phase 1+. The 19-test permission-probe mocking suite uses `pytest-subprocess` to assert every error-code branch in the AppleScript decision matrix, with explicit P-PHASE0-02 (French stderr regex) and P-PHASE0-03 (-1708 = granted) regression guards. The `RUN_LIVE=1`-gated end-to-end smoke (`tests/integration/test_live_doctor.py`) is deselected by `-m "not live"` in CI; on the maintainer's Mac it passes in 0.47 s, confirming the live `doctor()` produces a well-formed three-bucket `DoctorReport`.
- **Next action:** Continue `/gsd-execute-phase 0` Wave 5 — Plan 05 (CI workflows + README + `claude_desktop_config.json` example). Plan 05 binds against the now-green test suite: `.github/workflows/ci.yml` will invoke `uv run pytest -m "not live"` (28 tests, ≤1s); `.github/workflows/release.yml` will document the `RUN_LIVE=1 uv run pytest -m live` manual smoke; README will ship the 60-second quickstart with WhatsApp ToS / account-ban warning (D-20, D-21) and the 4-line `claude_desktop_config.json` snippet under `examples/` (SETUP-01 ergonomics).
- **Resume file:** `.planning/phases/00-setup-and-permissions-skeleton/00-04-SUMMARY.md`

## Progress

```
[                    ] 0/4 phases complete
Phase 0: ◐ Setup & Permissions Skeleton  (In progress: 4/5 plans)
Phase 1: ▢ Read MVP (`--read-only`)      (Not started)
Phase 2: ▢ Send (UI-automation, guardrails) (Not started)
Phase 3: ▢ Hardening & Distribution      (Not started)
```

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 0. Setup & Permissions Skeleton | 4/5 | In progress | - |
| 1. Read MVP (`--read-only`) | 0/0 | Not started | - |
| 2. Send (UI-automation, guardrails) | 0/0 | Not started | - |
| 3. Hardening & Distribution | 0/0 | Not started | - |

## Performance Metrics

- **Time spent so far:** Initialization + research + requirements + roadmap + Phase 0 plans 01–04 (one session, 2026-05-13)
- **Phases completed:** 0 / 4
- **Plans completed:** 4 / 5 (Phase 0, Plans 01–04 — ~1462 s combined, 12 commits, 37 files)
- **Requirements validated:** 3 / 37 (SETUP-02 and SETUP-04 satisfied by Plan 03; SETUP-03 fully satisfied by Plan 04 — the stdout-purity CI gate is live, spawning `python -m whatsapp_mcp` and asserting every stdout line is JSON-RPC 2.0; SETUP-01, SETUP-05, DIST-01 still pending Plan 05)

| Plan | Duration (s) | Tasks | Files | Commits |
|------|--------------|-------|-------|---------|
| 00-01 Project skeleton, pyproject.toml, uv-managed deps | 169 | 3 | 15 | 3 |
| 00-02 FastMCP stdio server, CLI, exceptions, Pydantic models | 180 | 3 |  6 | 3 |
| 00-03 Permission probes (FDA / Automation / Accessibility) + doctor MCP tool | 240 | 3 |  6 | 3 |
| 00-04 Test suite — stdout purity, doctor registration, exception shape, probe mocking, REL-05 isolation | 873 | 3 | 10 | 3 |

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
- **Executed Phase 0 Plan 02 (Wave 2):** landed the executable spine — FastMCP stdio server module (`whatsapp_mcp.server.mcp` + `run()`), argparse CLI with lazy server import (`--version` / `--help` exit before FastMCP loads), `python -m whatsapp_mcp` shim, the frozen 5-class `WhatsAppMCPError` → `PermissionRequired` → `{FullDiskAccess,Automation,Accessibility}Required` exception hierarchy with `bucket` + `system_settings_url` class attributes, the Pydantic v2 `DoctorReport` / `PermissionStatus` contracts (Literal-typed enums, `all_granted` as a `@property` not a field), and the pure `resolve_chatstorage_path()` resolver. `uv run whatsapp-mcp --version` and `uv run python -m whatsapp_mcp --version` both print `whatsapp-mcp 0.1.0` and exit 0. Server import emits zero stdout bytes (P-PHASE0-01 invariant). One Rule-1 deviation: server.py docstring re-worded to omit the literal `transport=` token so the plan's strict file-wide grep gate passes. 3 atomic commits, ~180 s.
- **Executed Phase 0 Plan 03 (Wave 3):** wired the three permission probes and the `doctor` MCP tool. (1) `permissions/osascript.py` — async `run_osascript(script, timeout=3.0) -> OsascriptResult` using `asyncio.create_subprocess_exec` + `asyncio.wait_for(timeout=3)` (D-10) with a locale-blind `r"\((-?\d+)\)\s*\Z"` error-code matcher (P-PHASE0-02 mitigation; the user's machine emits French stderr). (2) `permissions/fda.py` — `os.stat(ChatStorage.sqlite)` dispatched via `asyncio.to_thread`; `FileNotFoundError → whatsapp_not_installed`, `PermissionError(EACCES/EPERM) → denied`. (3) `permissions/automation.py` — empirically corrected D-09 PATCHED probe `id of application "WhatsApp"` (NOT the broken window-enumeration form per P-PHASE0-03); decision matrix maps `0 / -1708 / -600 → granted`, `-1743 → denied`, `-1728 → whatsapp_not_installed`, anything else → `denied` with unexpected_result remediation. (4) `permissions/accessibility.py` — `tell System Events to count processes`; `0 → granted`, `-1719 / -25211 → denied`. (5) `tools/doctor.py` — `@mcp.tool(name="doctor", annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))` async `doctor() -> DoctorReport` orchestrating the three probes sequentially. (6) `server.py:44` — replaced the Plan 02 marker comment with `from whatsapp_mcp.tools import doctor as _doctor  # noqa: E402, F401` (the side-effect import that triggers `@mcp.tool` registration). Live `doctor()` on the user's Mac returns all-`granted` (Phase 1 baseline). 4 Rule-1 minor deviations all of the same near-miss class (literal-token rewordings to satisfy strict file-wide source-grep gates: `subprocess.run`, `asyncio.TimeoutError → TimeoutError` per ruff UP041, `count windows`, and the `id of application` / `from whatsapp_mcp.tools import doctor` "exactly-one-match" gates) — all docstring/comment-only, zero behavioral impact. 3 atomic commits, ~240 s.
- **Executed Phase 0 Plan 04 (Wave 4):** shipped the 28-test pytest suite that gates Phase 0's invariants in CI. (1) `tests/conftest.py` — near-empty marker module (asyncio_mode=auto + fp fixture are auto-loaded). (2) `tests/unit/test_stdout_purity.py` — the SETUP-03 CI gate; spawns `python -m whatsapp_mcp` via `asyncio.create_subprocess_exec(sys.executable, "-m", "whatsapp_mcp", ...)`, drives a full `initialize (protocolVersion=2025-06-18) → notifications/initialized → tools/list → tools/call doctor` JSON-RPC handshake, asserts every stdout line parses as JSON-RPC 2.0. (3) `tests/unit/test_doctor_tool.py` — introspects `mcp.list_tools()` and asserts exactly one tool named `doctor` with `readOnlyHint=True`, `destructiveHint in (False, None)` (D-08 import-by-name guard). (4) `tests/unit/test_exceptions.py` — three tests: issubclass hierarchy, bucket literals + Privacy_* URL fragments, keyword-only constructor payload (D-12 frozen surface for Phase 1). (5) `tests/unit/test_isolation.py` — four tests: independent imports of `whatsapp_mcp.{reader,sender}` + AST-walk of each package asserting no cross-imports (REL-05 — vacuous now, gains teeth in Phase 1+). (6) `tests/unit/test_permissions/test_osascript.py` — four tests: locale-blind regex with French stderr fixture (P-PHASE0-02 regression), English stderr, clean exit, no-code stderr. (7) `tests/unit/test_permissions/test_fda.py` — five tests: live tmp file → granted, missing file → whatsapp_not_installed, EACCES → denied, EPERM → denied, EIO → denied (other-errno branch). (8) `tests/unit/test_permissions/test_automation.py` — six tests covering the D-09 PATCHED decision matrix (granted on exit 0, denied on -1743, whatsapp_not_installed on -1728, granted on -1708 (P-PHASE0-03 regression guard), granted on -600, denied on unknown). (9) `tests/unit/test_permissions/test_accessibility.py` — four tests: granted on exit 0, denied on -1719, denied on -25211, denied on unknown code. (10) `tests/integration/test_live_doctor.py` — `@pytest.mark.live` + `RUN_LIVE` env-var skip belt-and-braces; runs the real `doctor()` and asserts the report is shape-correct (NOT value-correct, so it stays green across grant changes). Test count: 28 non-live + 1 live; full non-live suite runs in 0.86 s on the maintainer's Mac. Live smoke passes in 0.47 s (`RUN_LIVE=1 uv run pytest -m live`). 4 Rule-1 minor deviations: ruff I001 import-sort auto-fix in stdout-purity test; mypy strict required `import importlib.util` (not `import importlib`) in isolation test; ruff E501 long lines + UP012 redundant `encoding="utf-8"` in three permission tests; mypy strict required string-path `monkeypatch.setattr("whatsapp_mcp.permissions.fda.os.stat", ...)` (rather than attribute-access form) in FDA tests. All four are type-checker / lint-rule auto-fixes with zero behavioral impact. 3 atomic commits, ~873 s.

### Next Session

- Continue `/gsd-execute-phase 0` Wave 5: Plan 05 (CI workflows + README + `claude_desktop_config.json` snippet). Plan 05 binds against the now-green test suite from Plan 04: `.github/workflows/ci.yml` will invoke `uv run pytest -m "not live"` (28 tests, ≤1 s on macos-14); `.github/workflows/release.yml` will trigger on `tags: ['v*']` and publish to PyPI via OIDC trusted-publisher; `README.md` will ship the WhatsApp ToS / account-ban disclaimer (D-20), the 60-second quickstart (D-21), and the personal-account framing (D-22); `examples/claude_desktop_config.json` will provide the SETUP-01 single-line install snippet. After Plan 05 commits, Phase 0 transitions from "in progress (4/5)" to "complete (5/5)" and the user-visible vertical slice (install via Claude Desktop, restart, call `doctor`, see structured report) is fully demonstrable.

### Files Most Recently Touched

- `tests/conftest.py` (created — Plan 04 Task 1)
- `tests/unit/test_stdout_purity.py`, `tests/unit/test_doctor_tool.py`, `tests/unit/test_exceptions.py`, `tests/unit/test_isolation.py` (created — Plan 04 Task 1)
- `tests/unit/test_permissions/test_osascript.py`, `test_fda.py`, `test_automation.py`, `test_accessibility.py` (created — Plan 04 Task 2)
- `tests/integration/test_live_doctor.py` (created — Plan 04 Task 3)
- `.planning/phases/00-setup-and-permissions-skeleton/00-04-SUMMARY.md` (created)
- `.planning/STATE.md`, `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md` (updated)

---
*State updated: 2026-05-13 after Phase 0 Plan 04 executed (Wave 4 done)*

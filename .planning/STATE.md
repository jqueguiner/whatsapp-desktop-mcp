# Project State: WhatsApp MCP

**Last updated:** 2026-05-13 (after Phase 1 Plan 01-03 executed, Wave 1 complete — Phase 1 in progress, 2/6 plans)

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

- **Active phase:** Phase 1 — Read MVP (`--read-only`) (2/6 plans complete; Wave 1 done)
- **Active plan:** Plan 01-03 complete (Wave 1.2). Wave 1 is now done (Plans 01-01 + 01-03 both shipped). Wave 2 (Plan 01-02 reader internals) is unblocked next; it depends on 01-01's models/time/paths.
- **Status:** Phase 0 verified complete. Plan 01-01 shipped the Pydantic data tier (8 model modules + time helpers + expanded paths.py). Plan 01-03 shipped the `--read-only` flag end-to-end: (1) `ReadOnlyMode(WhatsAppMCPError)` appended to `exceptions.py` (sibling of `PermissionRequired`, NOT a child — being denied by `--read-only` is a deliberate server config choice, not a missing OS permission); (2) `read_only_mode: bool = True` module-level state in `server.py` between the FastMCP instance and the doctor tool import, with a Plan 01-04 insertion-point marker comment in place; (3) `--read-only` / `--no-read-only` argparse flag in `cli.py` using `argparse.BooleanOptionalAction` (stdlib ≥3.9; requires-python ≥3.12) with `default=True` (v0.1 carry-over decision), wired to `server.read_only_mode = args.read_only` BEFORE the lazy server-entry import resolves so Phase 2's gated send-tool import will observe the user's choice. Phase 0 invariants preserved: `--version` / `--help` still exit before FastMCP loads; `mcp.list_tools()` still returns exactly `['doctor']`; stdout-purity test still green; REL-05 sender/ leak grep clean across cli/server/exceptions. All 28 Phase 0 tests still green; full `ruff check` + `ruff format --check` + `mypy --strict` clean across 39 source files.
- **Next action:** Execute Phase 1 Plan 01-02 (Reader internals: RO-WAL connection, schema probe, queries, tombstones, media) — Wave 2, depends on Plan 01-01's models/time/paths (already shipped). Wave 3 (Plans 01-04 tools, 01-05 doctor expansion) depends on the reader. Wave 4 (Plan 01-06 tests) is last.
- **Resume file:** `.planning/phases/01-read-mvp-read-only/01-03-SUMMARY.md`

## Progress

```
[██████░             ] 0/4 phases complete  (Phase 0 verified; Phase 1: 2/6 plans, Wave 1 done)
Phase 0: ✓ Setup & Permissions Skeleton  (5/5 plans — verified complete)
Phase 1: ◐ Read MVP (`--read-only`)      (2/6 plans — Wave 1 done; Plans 01-01 + 01-03)
Phase 2: ▢ Send (UI-automation, guardrails) (Not started)
Phase 3: ▢ Hardening & Distribution      (Not started)
```

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 0. Setup & Permissions Skeleton | 5/5 | ✓ Complete | 2026-05-13 |
| 1. Read MVP (`--read-only`) | 2/6 | In progress (Wave 1 done) | - |
| 2. Send (UI-automation, guardrails) | 0/0 | Not started | - |
| 3. Hardening & Distribution | 0/0 | Not started | - |

## Performance Metrics

- **Time spent so far:** Initialization + research + requirements + roadmap + Phase 0 plans 01–05 + Phase 0 verification + Phase 1 research + Phase 1 plans + Phase 1 Plan 01-01 + Phase 1 Plan 01-03 execution (multi-session, 2026-05-13)
- **Phases completed:** 0 / 4 (Phase 0 verified; Phase 1 in progress — 2/6 plans done, Wave 1 complete)
- **Plans completed:** 7 / 11 (Phase 0 Plans 01–05 + Phase 1 Plans 01-01, 01-03 — ~2494 s combined, 21 commits, 54 files)
- **Requirements validated:** 6 / 37 + 5 partial (Plan 01-01 lays the schema-shape foundation for DATA-01..04; Plan 01-03 partially satisfies SETUP-06 — the flag + ReadOnlyMode + server state are wired; the "every send tool unregistered when --read-only" half is structurally satisfied in Phase 1 (no send tools exist) and will be re-verified in Phase 2)

| Plan | Duration (s) | Tasks | Files | Commits |
|------|--------------|-------|-------|---------|
| 00-01 Project skeleton, pyproject.toml, uv-managed deps | 169 | 3 | 15 | 3 |
| 00-02 FastMCP stdio server, CLI, exceptions, Pydantic models | 180 | 3 |  6 | 3 |
| 00-03 Permission probes (FDA / Automation / Accessibility) + doctor MCP tool | 240 | 3 |  6 | 3 |
| 00-04 Test suite — stdout purity, doctor registration, exception shape, probe mocking, REL-05 isolation | 873 | 3 | 10 | 3 |
| 00-05 GitHub Actions CI + release.yml + README + claude_desktop_config.json example | 420 | 3 |  4 | 3 |
| 01-01 Models, time helpers, expanded path resolvers | 327 | 3 | 10 | 3 |
| 01-03 --read-only flag mechanics: CLI flag, ReadOnlyMode exception, server state | 285 | 3 |  3 | 3 |

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
- ~~(Phase 0 planning) Decide on `--read-only` default for v0.1 vs v1.0~~ — **resolved by Plan 01-03 (2026-05-13)**: default-on (True) for v0.1; v1.0 decision deferred until Phase 2 send tooling lands.
- (Phase 2 planning) Decide whether the Accessibility-API send path (pyobjc) lands in Phase 2 v1.0 or is deferred to v1.x — affects pyobjc dep and TCC entitlements.
- (Phase 2 planning) Wrap the future `send_message` tool import in `if not server.read_only_mode:` and raise `whatsapp_mcp.exceptions.ReadOnlyMode(...)` at tool call time as a defensive belt-and-braces — insertion point is the Plan 01-04 marker comment in `server.py`.
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
- **Executed Phase 1 Plan 01-03 (Wave 1.2):** wired the `--read-only` flag end-to-end across three files. (1) `src/whatsapp_mcp/exceptions.py` — appended `ReadOnlyMode(WhatsAppMCPError)` as a sibling of `PermissionRequired` (NOT a child — being denied by `--read-only` is a deliberate server config choice, not a missing OS permission, so it does not share the `bucket` / `system_settings_url` payload shape); class has no `__init__` override and inherits the bare `Exception(message)` constructor. Phase 1 mints the class but never raises it — Phase 2's `send_message` is the consumer. (2) `src/whatsapp_mcp/server.py` — inserted `read_only_mode: bool = True` between the `mcp: FastMCP = FastMCP(...)` line and the existing `from whatsapp_mcp.tools import doctor as _doctor` import; added a Plan 01-04 insertion-point marker comment immediately after the doctor import (Plan 01-04 will append 7 read-tool imports there; Phase 2 will append its `if not read_only_mode:` send-tool block after the read tools). Module docstring gained a paragraph framing the flag lifecycle. (3) `src/whatsapp_mcp/cli.py` — added `argparse.BooleanOptionalAction` declaration with `default=True` (v0.1 carry-over decision, resolved by this plan) giving `--read-only` / `--no-read-only` from a single declaration; wired `server.read_only_mode = args.read_only` BEFORE the lazy `from whatsapp_mcp.server import run` resolves so the tool-registration side-effect imports observe the user's choice. Phase 0 invariants preserved: `--version` / `--help` still exit before FastMCP loads (verified `whatsapp-mcp --version` returns `whatsapp-mcp 0.1.0` rc=0); `mcp.list_tools()` still returns exactly `['doctor']`; stdout-purity test green; REL-05 sender/ leak grep clean across cli/server/exceptions. One Rule-1 minor deviation: ruff E501 wrapped the long help-string line, and the cli.py docstring was reworded to avoid a second literal `from whatsapp_mcp.server import run` occurrence (kept the strict acceptance-grep count at exactly 1) — same near-miss class as Phase 0's literal-token rewordings, zero behavioral impact. 3 atomic commits (`703059f`, `ae723be`, `5655b1d`), ~285 s. Phase 1 Wave 1 transitions to complete.

- **Executed Phase 0 Plan 05 (Wave 5):** shipped the distribution-and-onboarding surface that closes Phase 0. (1) `.github/workflows/ci.yml` — push (main) + PR triggers; macos-14; `astral-sh/setup-uv@v8` with Python 3.12 + enable-cache; ordered `uv sync --extra dev` → `uv run ruff check src tests` → `uv run ruff format --check src tests` → `uv run mypy` → `uv run pytest -m "not live"`; concurrency group cancels in-progress runs on the same ref. The SETUP-03 stdout-purity test is exercised inside the pytest step (no separate gate). (2) `.github/workflows/release.yml` — `on: push: tags: ['v*']` only (no PR trigger); two jobs — `ci: uses: ./.github/workflows/ci.yml` (reusable workflow), and `publish: needs: [ci]` with `runs-on: macos-14`, `environment: { name: pypi, url: https://pypi.org/p/whatsapp-mcp }`, `permissions: { id-token: write }` AT THE JOB LEVEL (P-PHASE0-04 mitigation — workflow root has no permissions block; verified by YAML-parse runtime assertion `assert doc['jobs']['publish']['permissions']['id-token'] == 'write'; assert 'permissions' not in doc`); publish job steps are `actions/checkout@v4` → `astral-sh/setup-uv@v8` → `uv build` → `uv publish` over the OIDC handshake. No `PYPI_TOKEN` / `PYPI_API_TOKEN` / `password:` anywhere (verified by file-wide grep). (3) `README.md` — replaced the Plan-01 7-line stub with the 157-line Plan-05 SETUP-05 surface. Opens with a blockquote ToS automation-risk warning (every locked-D-20 clause present: 'WhatsApp's Terms of Service prohibit "automated or bulk messaging"', 'irrecoverable account ban', 'conservative rate limits (5 sends / minute, 30 sends / day) by default', 'you accept the risk by using it', 'personal account, not a bot'). D-21 four-step quickstart ending in the live `doctor` tool call. D-22 framing inline ('personal account, not a bot'; no 'WhatsApp Business' mention anywhere). Full Development section documenting the one-time PyPI trusted-publisher setup procedure (Owner=`gladia`, Repo=`whatsapp-mcp`, Workflow=`release.yml`, Environment=`pypi`). 123 non-empty lines (within the 50-200 band). (4) `examples/claude_desktop_config.json` — the authoritative 4-line JSON snippet (`{"mcpServers": {"whatsapp": {"command": "uvx", "args": ["whatsapp-mcp"]}}}`); byte-decodable to the same dict as the JSON code fence in README's Quickstart step 1 (verified by runtime `json.loads(...) == json.load(...)` cross-check). Two-space indentation; trailing newline; strict JSON (no comments). One Rule-1 minor deviation: `release.yml` top-of-file comment re-worded from "no PYPI_TOKEN / password anywhere" to "no long-lived secrets anywhere" — same near-miss class as Plan 02's `transport=`, Plan 03's `subprocess.run` / `count windows` / `id of application` / `from whatsapp_mcp.tools import doctor` rewordings — the strict file-wide grep gate is the authoritative source of truth and the comment had to be re-worded around it. Comment-only fix, zero behavioral impact. 3 atomic commits, ~420 s. Phase 0 transitions to "5/5 plans complete; ready for verification."

### Next Session

- Execute Phase 1 Plan 01-02 (Reader internals: RO-WAL connection, schema probe, queries, tombstones, media) — Wave 2, depends on Plan 01-01's data tier (already shipped). Then Wave 3 (Plans 01-04 tools, 01-05 doctor expansion) which depends on the reader. Wave 4 (Plan 01-06 tests) is last.
- All Phase 1 reader/tool code can now `from whatsapp_mcp.models import Chat, Message, Contact, Jid, GroupInfo, GroupMember, MediaRef, Coverage, encode_cursor, decode_cursor, CursorError, AnchorKind` without ImportError; `from whatsapp_mcp.time import cocoa_to_unix, unix_to_cocoa, COCOA_EPOCH_OFFSET` works; `from whatsapp_mcp.paths import resolve_chatstorage_path, resolve_lid_path, resolve_contactsv2_path, resolve_media_root` works.
- The `--read-only` flag is wired: `from whatsapp_mcp.exceptions import ReadOnlyMode` works; `from whatsapp_mcp.server import read_only_mode` defaults to `True`. Phase 2's `send_message` will gate registration on `if not server.read_only_mode:` (insertion point marked in `server.py`).
- B2 lock to honor in Plan 01-02: `reader.window` returns `(Message, z_sort)` tuples — `z_sort` is NEVER a public attribute on `Message`.
- W2 cursor schema in use: `{"chat_id": int, "anchor": float, "anchor_kind": "z_sort" | "cocoa_ts"}`.

### Files Most Recently Touched (Plan 01-03)

- `src/whatsapp_mcp/exceptions.py` (modified — appended `ReadOnlyMode(WhatsAppMCPError)` sibling class)
- `src/whatsapp_mcp/server.py` (modified — added `read_only_mode: bool = True` module state + Plan 01-04 insertion-point marker comment)
- `src/whatsapp_mcp/cli.py` (modified — added `--read-only` / `--no-read-only` `BooleanOptionalAction` flag wired to `server.read_only_mode = args.read_only` before lazy `run()` import)
- `.planning/phases/01-read-mvp-read-only/01-03-SUMMARY.md` (created)
- `.planning/STATE.md`, `.planning/ROADMAP.md` (updated)

---
*State updated: 2026-05-13 after Phase 1 Plan 01-03 executed (Wave 1 done — flag mechanics wired)*

---
phase: 00-setup-and-permissions-skeleton
verified: 2026-05-13T08:08:59Z
status: passed
score: 6/6 must-haves verified (after gap closure)
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 5/6
  gaps_closed:
    - "CI ruff format --check gate: 3 files reformatted by `uv run ruff format src tests`, committed as 7548158. Re-running locally: `uv run ruff format --check src tests` exits 0; full local CI sequence (sync + ruff check + ruff format --check + mypy + pytest -m 'not live') all green. SETUP-03 stdout-purity gate now reachable on every push/PR."
  gaps_remaining: []
  regressions: []
  resolution_commit: 7548158
gaps:
  - truth: "CI (.github/workflows/ci.yml) runs the stdout-purity test on every push/PR"
    status: partial
    reason: |
      The stdout-purity test exists, is registered in CI's `pytest -m "not live"`
      step, and passes locally. BUT ci.yml runs `uv run ruff format --check src tests`
      as a separate step BEFORE the pytest step. Against the currently committed
      tree, that step EXITS 1 — three files would be reformatted by the pinned
      ruff 0.15.12: src/whatsapp_desktop_mcp/exceptions.py,
      src/whatsapp_desktop_mcp/permissions/osascript.py,
      tests/unit/test_permissions/test_automation.py. CI fails before reaching
      the pytest step, so the SETUP-03 stdout-purity gate is never exercised
      on push/PR until the format fix lands. ROADMAP SC3 is half-satisfied:
      the test exists and passes; the CI wiring that's supposed to enforce it
      on every change fails at the format-check gate before the test runs.
    artifacts:
      - path: src/whatsapp_desktop_mcp/exceptions.py
        issue: "lines 45-47: ruff format wants the system_settings_url string un-parenthesised on a single line"
      - path: src/whatsapp_desktop_mcp/permissions/osascript.py
        issue: "lines 82-87 + 99-104: ruff format wants the two `OsascriptResult(...)` returns on a single line"
      - path: tests/unit/test_permissions/test_automation.py
        issue: "line 61: ruff format prefers single-quoted outer / double-quoted inner literal here"
    missing:
      - "Run `uv run ruff format src tests` and commit the 3-file no-op formatting diff before declaring Phase 0 done"
      - "Optionally add a `ruff format --check` step to a local pre-commit hook so this can't regress"
human_verification:
  - test: "Add the `examples/claude_desktop_config.json` snippet to a real Mac's `~/Library/Application Support/Claude/claude_desktop_config.json`, restart Claude Desktop, and confirm the `whatsapp` MCP server appears in the running-servers list with no JSON-RPC errors visible in `~/Library/Logs/Claude/mcp-server-whatsapp.log`"
    expected: "Server registers, doctor tool appears in tools/list; no protocol errors in the log"
    why_human: "Requires a live Claude Desktop instance and `uvx` resolving the unreleased 0.1.0 wheel (or a local dev path). Cannot be verified programmatically from CI on macos-14 without installing Claude Desktop."
  - test: "From the live Claude Desktop chat, ask Claude to 'call the WhatsApp doctor tool'"
    expected: "Claude shows a JSON report with the three keys (full_disk_access, automation_whatsapp, accessibility) each carrying state/binary_path/db_path/system_settings_url/remediation"
    why_human: "Renders through Claude Desktop's UI, which the verifier cannot drive."
  - test: "First-time PyPI publish — configure trusted-publisher binding (Owner=`gladia`, Repo=`whatsapp-desktop-mcp`, Workflow=`release.yml`, Environment=`pypi`) on PyPI's pending-publisher page, then `git tag v0.1.0 && git push --tags`"
    expected: "Release workflow runs CI as a reusable workflow; on green, `publish` job runs `uv build` + `uv publish` over OIDC handshake; PyPI shows v0.1.0; `uvx whatsapp-desktop-mcp --version` resolves from PyPI on any Mac with `uv`"
    why_human: "Requires manual one-time PyPI trusted-publisher pending-publisher binding which is outside the repo. DIST-01 is satisfied at the workflow level; it closes end-to-end only after this manual step + first tag push."
---

# Phase 0: Setup & Permissions Skeleton — Verification Report

**Phase Goal (from ROADMAP.md):**
> A user can install the MCP server in `claude_desktop_config.json`, launch it,
> call `doctor`, and get a structured, actionable report about whether the macOS
> permissions and protocol hygiene needed by later phases are in place.

**Verified:** 2026-05-13T08:08:59Z
**Status:** gaps_found (single CI wiring gap; user-visible Phase 0 capability is observable on disk and at runtime)
**Re-verification:** No — initial verification

---

## Goal Achievement — ROADMAP Success Criteria

| # | Success Criterion | Status | Evidence |
| - | ----------------- | ------ | -------- |
| 1 | `uvx whatsapp-desktop-mcp` registers as MCP stdio server with no JSON-RPC errors after a single-line `claude_desktop_config.json` add | VERIFIED | `pyproject.toml:39-40` declares `[project.scripts] whatsapp-desktop-mcp = "whatsapp_desktop_mcp.cli:main"`. `uv run whatsapp-desktop-mcp --version` → `whatsapp-desktop-mcp 0.1.0`. `uv run whatsapp-desktop-mcp --help` shows argparse help. Driving the stdio handshake live (Step 7b spot-check): wrote a single `initialize` JSON-RPC frame to stdin of `python -m whatsapp_desktop_mcp`, read stdout: got `{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","capabilities":{...},"serverInfo":{"name":"whatsapp-desktop-mcp","version":"1.27.1"}}}` — valid `initializeResult`. `examples/claude_desktop_config.json` parses to `{"mcpServers": {"whatsapp": {"command": "uvx", "args": ["whatsapp-desktop-mcp"]}}}` exactly. README's Quickstart step 1 JSON code fence byte-decodes to the same dict. |
| 2 | `doctor` returns structured permission report with binary_path + `x-apple.systempreferences:` deep-link per bucket | VERIFIED | `uv run python -c "import asyncio; from whatsapp_desktop_mcp.tools.doctor import doctor; print(asyncio.run(doctor()).model_dump_json(indent=2))"` returns JSON with exactly three keys `full_disk_access` / `automation_whatsapp` / `accessibility`, each with `bucket`, `state`, `binary_path` (= `/Users/jlqueguiner/dev/whatsapp-desktop-mcp/.venv/bin/python3` = `sys.executable`), `db_path` (FDA only: `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite`; null for others), `system_settings_url` (`Privacy_AllFiles` / `Privacy_Automation` / `Privacy_Accessibility` deep-links), `remediation`. All three `granted` on the verifier's Mac, consistent with the Plan 03 SUMMARY's transcript. Shape is exactly the SETUP-04 D-11 contract. |
| 3 | CI runs a stdout-purity test that fails if any non-JSON-RPC byte hits stdout AND ruff T201 blocks `print` at lint time | PARTIAL | `tests/unit/test_stdout_purity.py::test_stdout_is_pure_jsonrpc` exists (125 lines), spawns `python -m whatsapp_desktop_mcp` as a subprocess, drives full `initialize → notifications/initialized → tools/list → tools/call doctor` handshake, and asserts every stdout line parses as JSON-RPC 2.0. Test PASSES locally: `uv run pytest -k test_stdout_is_pure_jsonrpc` → 1 passed. `pyproject.toml:63` has `"T201"` in `[tool.ruff.lint].select`; `[tool.ruff.lint.per-file-ignores]` exempts only tests. `uv run ruff check src tests` → "All checks passed!". `grep -rn '\bprint(' src/whatsapp_desktop_mcp/` → 0 matches. **BUT** `.github/workflows/ci.yml:38` runs `uv run ruff format --check src tests` BEFORE the pytest step, and that command CURRENTLY EXITS 1 against the committed tree (3 files would be reformatted by ruff 0.15.12). CI thus fails before the stdout-purity gate executes. Hence: SETUP-03 lint half + test exists + test passes locally → all green; CI wiring → broken. See `gaps[0]` below. |
| 4 | README opens with WhatsApp ToS / account-ban disclaimer + 60-second `uvx` quickstart, framed as "personal account, not a bot" | VERIFIED | `README.md:3-11` is a blockquote opening with "**Warning — WhatsApp ToS automation risk.**", contains the verbatim "WhatsApp's Terms of Service prohibit \"automated or bulk messaging.\"", "irrecoverable account ban", "conservative rate limits (5 sends / minute, 30 sends / day) by default", "you accept the risk by using it" and "**This is your personal account, not a bot.**" — every D-20 / D-22 clause present. `README.md:16` "## Quickstart (60 seconds)" followed by 4 numbered steps; step 1 has the literal `uvx whatsapp-desktop-mcp` snippet; step 3 invokes `doctor`. No "WhatsApp Business" mention anywhere in the file. |

**ROADMAP SC score:** 3 fully verified + 1 partial (SC3) = 3.5/4 → status `gaps_found` (the partial item is a real CI failure that blocks SC3 once any push lands).

---

## Phase Requirement Coverage (per REQUIREMENTS.md)

| REQ-ID | Description | Source Plan(s) | Status | Evidence |
| ------ | ----------- | -------------- | ------ | -------- |
| SETUP-01 | Single-line install in `claude_desktop_config.json` via `uvx whatsapp-desktop-mcp` | Plan 05 (also Plan 01 reserved the console-script entry) | SATISFIED | `examples/claude_desktop_config.json` decodes to `{"mcpServers": {"whatsapp": {"command": "uvx", "args": ["whatsapp-desktop-mcp"]}}}`. README Quickstart step 1's JSON code fence decodes to the same dict (verified byte-decoded). `[project.scripts] whatsapp-desktop-mcp = "whatsapp_desktop_mcp.cli:main"` in `pyproject.toml:40` resolves via `uvx`. |
| SETUP-02 | Server runs as MCP stdio + registers with Claude Desktop without protocol errors | Plan 02 + Plan 03 | SATISFIED | `FastMCP("whatsapp-desktop-mcp")` instantiated in `src/whatsapp_desktop_mcp/server.py:42`; `run()` calls `mcp.run()` (stdio default). Doctor tool registered with `readOnlyHint=True` (`src/whatsapp_desktop_mcp/tools/doctor.py:42-57`). `test_doctor_is_registered_as_readonly` passes (1 tool, name=doctor, readOnlyHint=True). Live single-frame `initialize` over stdio returned valid `initializeResult`. |
| SETUP-03 | All logging to stderr; stdout reserved for JSON-RPC; CI enforces stdout purity; ruff T201 blocks `print` | Plan 02 (stderr-first) + Plan 04 (purity test) + Plan 01 (T201) + Plan 05 (CI wiring) | PARTIAL | Test, lint, source layout all green. CI wiring's earlier `ruff format --check` step exits 1, so the purity gate is never reached on a CI run against the current tree. See `gaps[0]`. |
| SETUP-04 | Missing permission → structured `*Required` error with binary_path + `x-apple.systempreferences:` deep-link | Plan 02 (frozen exception classes) + Plan 03 (doctor + probes) | SATISFIED | `src/whatsapp_desktop_mcp/exceptions.py` defines `WhatsAppMCPError → PermissionRequired → {FullDiskAccessRequired, AutomationPermissionRequired, AccessibilityPermissionRequired}` with `bucket` + `system_settings_url` (verified by `test_permission_hierarchy_is_stable`, `test_subclass_buckets_and_urls`, `test_carries_remediation_payload`). Each `*Required.system_settings_url` carries the `Privacy_AllFiles` / `Privacy_Automation` / `Privacy_Accessibility` fragment. Doctor populates `PermissionStatus.binary_path = sys.executable` and pulls `system_settings_url` off the exception class (single source of truth, per D-11). Phase 0 does not RAISE the exceptions (Phase 1 will); they ship as frozen public surface. |
| SETUP-05 | README documents WhatsApp ToS automation risk + account-ban + "personal account, not a bot" | Plan 05 | SATISFIED | README opens with D-20 blockquote (every required clause present); D-22 framing inline; D-21 4-step Quickstart. No "WhatsApp Business" / "whatsmeow" / "Baileys" / "HTTP REST" surface mention. |
| DIST-01 | Project publishes to PyPI as `whatsapp-desktop-mcp`, installable via `uvx whatsapp-desktop-mcp` | Plan 01 (entry-point + buildable wheel) + Plan 05 (release.yml OIDC) | WORKFLOW-LEVEL SATISFIED (closes end-to-end after manual one-time PyPI binding + first tag push) | `uv build` produces `dist/whatsapp_desktop_mcp-0.1.0-py3-none-any.whl` (21 KB) + `dist/whatsapp_desktop_mcp-0.1.0.tar.gz` (263 KB) cleanly. `.github/workflows/release.yml` triggers on `tags: ['v*']`, reuses `ci.yml`, then `publish` job has `permissions.id-token: write` at JOB level (lines 26-27) — NOT workflow level (verified by reading the YAML; `permissions:` does not appear at the root). No `PYPI_TOKEN` / `password:` / `secrets.*` anywhere in `.github/` (grep returns 0 matches). The end-to-end PyPI publish path is gated on a one-time manual binding (Owner=`gladia`, Repo=`whatsapp-desktop-mcp`, Workflow=`release.yml`, Environment=`pypi`) documented in README's Development section — outside CI's control but inside human-verification scope. |

**Coverage:** 6/6 declared REQ-IDs satisfied at the codebase level (SETUP-03 has a CI wiring partial; DIST-01 closes once the manual PyPI binding is configured). No orphaned requirements.

---

## Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `pyproject.toml` | hatchling build, deps `mcp[cli]==1.27.1` + `pydantic>=2.7`, `[project.scripts] whatsapp-desktop-mcp = "whatsapp_desktop_mcp.cli:main"`, ruff T201 enabled, mypy strict, pytest live marker | VERIFIED | Inspected — all present, lines 1-100 (T201 at line 63, console script at line 40, hatch wheel target at line 47, strict mypy at line 79, live marker at line 98). |
| `src/whatsapp_desktop_mcp/server.py` | FastMCP instance + stderr-first logging + zero `transport=` keyword + doctor tool side-effect import | VERIFIED | Lines 34-38 set `logging.basicConfig(stream=sys.stderr, ...)` BEFORE the `mcp.server.fastmcp` import (E402 noqa documented). Line 44 has the doctor import. `grep '\btransport\s*='` returns nothing. |
| `src/whatsapp_desktop_mcp/cli.py` | argparse `--version` / `--help` exits before FastMCP import (lazy server import) | VERIFIED | Inspected — `from whatsapp_desktop_mcp.server import run` is inside `main()` after `parser.parse_args(argv)`. `uv run whatsapp-desktop-mcp --version` → `whatsapp-desktop-mcp 0.1.0`. |
| `src/whatsapp_desktop_mcp/__main__.py` | `python -m whatsapp_desktop_mcp` shim that delegates to `cli.main` | VERIFIED | 15-line shim, `from whatsapp_desktop_mcp.cli import main`. |
| `src/whatsapp_desktop_mcp/exceptions.py` | Frozen `WhatsAppMCPError → PermissionRequired → {Full…, Auto…, Access…}Required` with `bucket` + `system_settings_url` | VERIFIED | `test_exceptions.py` (3 tests) asserts the shape. |
| `src/whatsapp_desktop_mcp/models/doctor.py` | Pydantic v2 `PermissionStatus` + `DoctorReport`; `all_granted` is a `@property` (NOT a field) | VERIFIED | Inspected — `Literal` aliases for state/bucket, frozen surface. `DoctorReport.all_granted` is a Python `@property` and never appears in `model_fields`. |
| `src/whatsapp_desktop_mcp/paths.py` | `resolve_chatstorage_path() -> str` returning the canonical Group Container path | VERIFIED | Returns `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite` via `os.path.expanduser`. |
| `src/whatsapp_desktop_mcp/permissions/osascript.py` | Async `run_osascript(script, timeout=3.0)` with locale-blind `(-NNNN)` extraction + hard timeout + `osascript-missing` fallback | VERIFIED | `_ERR_RE = re.compile(r"\((-?\d+)\)\s*\Z", re.MULTILINE)` — locale-stable. `asyncio.create_subprocess_exec` + `asyncio.wait_for(timeout=timeout)`. `test_run_osascript_parses_french_stderr_error_code` passes (P-PHASE0-02 regression guard). |
| `src/whatsapp_desktop_mcp/permissions/fda.py` | `os.stat`-based probe via `asyncio.to_thread`; distinguishes EACCES/EPERM from FileNotFoundError | VERIFIED | 5 unit tests cover every branch; all pass. |
| `src/whatsapp_desktop_mcp/permissions/automation.py` | D-09 PATCHED probe `id of application "WhatsApp"`; -1708/-600 → granted; -1743 → denied; -1728 → not_installed | VERIFIED | Line 46 `_PROBE = 'id of application "WhatsApp"'`. `count windows` not used in production code (only appears inside a test docstring on `test_automation.py:75` explaining the patch). 6 unit tests cover every state. `test_automation_handler_not_found_is_granted` (P-PHASE0-03 regression) passes. |
| `src/whatsapp_desktop_mcp/permissions/accessibility.py` | `tell System Events to count processes`; -1719/-25211 → denied | VERIFIED | 4 unit tests cover the decision matrix. |
| `src/whatsapp_desktop_mcp/tools/doctor.py` | `@mcp.tool(name="doctor", annotations=ToolAnnotations(readOnlyHint=True, …))` with three probes | VERIFIED | All four ToolAnnotations set (readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False). |
| `src/whatsapp_desktop_mcp/reader/__init__.py` + `src/whatsapp_desktop_mcp/sender/__init__.py` | Empty packages (REL-05 structural enforcement) | VERIFIED | Both `wc -l` → 0; no other `.py` file present under either package (REL-05 vacuously holds; tests `test_isolation_reader_does_not_import_sender` + `test_isolation_sender_does_not_import_reader` exist and pass). |
| `tests/unit/test_stdout_purity.py` | Subprocess-spawn the server, drive full handshake, assert every stdout line is JSON-RPC 2.0 | VERIFIED | 125-line test. Passes locally in <2s. |
| `tests/unit/test_doctor_tool.py` | `mcp.list_tools()` returns exactly one tool named `doctor` with `readOnlyHint=True` | VERIFIED | 1 test, passes. |
| `tests/unit/test_isolation.py` | Reader and Sender import independently AND no source file in either references the sibling | VERIFIED | 4 tests, all pass. |
| `tests/unit/test_permissions/test_*` | pytest-subprocess-driven decision-matrix coverage of all four probe modules | VERIFIED | 19 tests across 4 files, all pass. |
| `tests/integration/test_live_doctor.py` | `RUN_LIVE=1`-gated live smoke test, deselected by `pytest -m "not live"` | VERIFIED | Marker registered in `pyproject.toml`; `--strict-markers` works; deselected in default run. |
| `.github/workflows/ci.yml` | Lint / format / mypy / pytest on macos-14, Python 3.12 | VERIFIED (file shape) / PARTIAL (current run would fail at format-check) | File present, runs-on macos-14, ordered steps as documented. Format-check step currently exits 1 against committed tree — see gap. |
| `.github/workflows/release.yml` | Tag-triggered PyPI publish via OIDC trusted-publisher; `id-token: write` at JOB level | VERIFIED | Job-level only (lines 26-27); no workflow-level `permissions:`; no PYPI_TOKEN / password / secrets reference. `ci.yml` reused. |
| `README.md` | ToS disclaimer + 4-step 60s Quickstart + personal-account framing | VERIFIED | 159 lines. ToS blockquote on lines 3-11; Quickstart heading on line 16; framing on line 10. |
| `examples/claude_desktop_config.json` | Single-line install snippet, exactly the `{mcpServers: {whatsapp: {command: 'uvx', args: ['whatsapp-desktop-mcp']}}}` shape | VERIFIED | Byte-decoded equal; matches README Quickstart step 1 JSON. |

**Artifact score:** 22/22 VERIFIED (with ci.yml flagged PARTIAL on its observable runtime behavior, not its file shape).

---

## Key Link Verification (Wiring)

| From | To | Via | Status | Evidence |
| ---- | -- | --- | ------ | -------- |
| `pyproject.toml` | `src/whatsapp_desktop_mcp` | `[tool.hatch.build.targets.wheel] packages = ["src/whatsapp_desktop_mcp"]` | WIRED | `pyproject.toml:47`. `uv build` succeeds. |
| `pyproject.toml` | `whatsapp_desktop_mcp.cli:main` | `[project.scripts] whatsapp-desktop-mcp = "whatsapp_desktop_mcp.cli:main"` | WIRED | `pyproject.toml:40`. `uv run whatsapp-desktop-mcp --version` resolves. |
| `cli.py` | `server.run` | Lazy import inside `main()` AFTER argparse | WIRED | `cli.py:40`. `uv run whatsapp-desktop-mcp --version` exits before importing FastMCP — verified by reading code; no stdout pollution observed in handshake test. |
| `server.py` | `tools/doctor.py` | `from whatsapp_desktop_mcp.tools import doctor as _doctor` (registration side-effect import) | WIRED | `server.py:44`. `mcp.list_tools()` returns one tool named `doctor`. |
| `tools/doctor.py` | `server.py` | `from whatsapp_desktop_mcp.server import mcp` (decorator target) | WIRED | `doctor.py:39`. |
| `tools/doctor.py` | `permissions/{fda,automation,accessibility}` | `from whatsapp_desktop_mcp.permissions import accessibility, automation, fda` + three awaited probes | WIRED | `doctor.py:38,61-63`. Live `doctor()` returns populated three-bucket report. |
| `permissions/*.py` | `exceptions.py` | `_*_URL = *PermissionRequired.system_settings_url` (D-11 single source of truth) | WIRED | `fda.py:38`, `automation.py:41`, `accessibility.py:32`. Live doctor output's `system_settings_url` fields match exactly. |
| `permissions/osascript.py` | `/usr/bin/osascript` | `asyncio.create_subprocess_exec("/usr/bin/osascript", "-e", script, …)` | WIRED | `osascript.py:68-74`. Live doctor invocation reaches a real osascript on the verifier's Mac. |
| `tests/unit/test_stdout_purity.py` | `python -m whatsapp_desktop_mcp` | `asyncio.create_subprocess_exec(sys.executable, "-m", "whatsapp_desktop_mcp", …)` | WIRED | Test spawns the subprocess and drives a handshake; passes locally. |
| `release.yml` | `ci.yml` | `uses: ./.github/workflows/ci.yml` | WIRED | `release.yml:18`. Reusable workflow call structurally correct. |
| `release.yml` publish job | PyPI OIDC | `permissions: id-token: write` at job scope | WIRED (workflow level) | `release.yml:26-27`. The end-to-end OIDC publish requires the one-time PyPI pending-publisher binding (manual step, outside repo). |
| `README.md` | `examples/claude_desktop_config.json` | Quickstart step 1 references the file path | WIRED | `README.md:19-20`. JSON code fence on lines 22-31 byte-decodes equal to the file. |

**Wiring score:** 12/12 verified.

---

## Data-Flow Trace (Level 4)

The phase ships a Python MCP server with no UI surface and no rendered components, so the Level 4 trace is shorter. The one runtime data flow that matters:

| Artifact | Variable | Source | Real data? | Status |
| -------- | -------- | ------ | ---------- | ------ |
| `tools/doctor.py::doctor()` | `DoctorReport` | Three awaited probes that hit real syscalls (`os.stat`) + real subprocess (`/usr/bin/osascript`) | YES — verified by Step 7b live invocation returning `state=granted` for all three on a real Mac | FLOWING |
| `models/doctor.py::PermissionStatus.binary_path` | `sys.executable` | Set inside each probe module from `sys.executable` (lines `fda.py:67`, `automation.py:50`, `accessibility.py:39`) | YES — verified to be `/Users/jlqueguiner/dev/whatsapp-desktop-mcp/.venv/bin/python3` in the live invocation | FLOWING |
| `models/doctor.py::PermissionStatus.system_settings_url` | `Privacy_*` URL | Pulled off the matching exception class attribute (D-11 single source of truth) | YES — verified equal across exception class + probe payload + doctor report | FLOWING |
| `models/doctor.py::PermissionStatus.db_path` | Group Container path | `paths.resolve_chatstorage_path()` (FDA bucket only) | YES — verified to be `~/Library/Group Containers/...ChatStorage.sqlite` in live doctor JSON | FLOWING |

No hollow props; no static stub data; no disconnected sources.

---

## Behavioral Spot-Checks

All run from `/Users/jlqueguiner/dev/whatsapp-desktop-mcp` on macOS 26.4 with the locked venv:

| # | Behavior | Command | Result | Status |
| - | -------- | ------- | ------ | ------ |
| 1 | Console script resolves and shows version | `uv run whatsapp-desktop-mcp --version` | `whatsapp-desktop-mcp 0.1.0` | PASS |
| 2 | Console script `--help` exits cleanly | `uv run whatsapp-desktop-mcp --help` | argparse help output, exit 0 | PASS |
| 3 | `python -m whatsapp_desktop_mcp` is a viable second entry point | (read code; `__main__.py` delegates to `cli.main`) | shim correct | PASS |
| 4 | Full test suite passes | `uv run pytest -m "not live"` | `28 passed, 1 deselected in 0.81s` | PASS |
| 5 | All 5 mandated regression tests present and green | `uv run pytest -v -k "test_run_osascript_parses_french_stderr_error_code or test_automation_handler_not_found_is_granted or test_isolation_reader_does_not_import_sender or test_isolation_sender_does_not_import_reader or test_stdout_is_pure_jsonrpc"` | `5 passed, 24 deselected in 0.79s` | PASS |
| 6 | ruff check is clean | `uv run ruff check src tests` | "All checks passed!" | PASS |
| 7 | ruff format --check is clean | `uv run ruff format --check src tests` | Exit 1: 3 files would be reformatted | FAIL |
| 8 | mypy strict is clean | `uv run mypy` | "Success: no issues found in 31 source files" | PASS |
| 9 | `uv build` produces wheel + sdist | `uv build` | `dist/whatsapp_desktop_mcp-0.1.0-py3-none-any.whl` (21 KB) + `dist/whatsapp_desktop_mcp-0.1.0.tar.gz` (263 KB) | PASS |
| 10 | Live doctor() returns well-formed three-bucket report | `uv run python -c "import asyncio; from whatsapp_desktop_mcp.tools.doctor import doctor; print(asyncio.run(doctor()).model_dump_json(indent=2))"` | JSON object with three keys (full_disk_access / automation_whatsapp / accessibility), each populated with state=granted, binary_path=`sys.executable`, system_settings_url=Privacy_* deep-link | PASS |
| 11 | Stdio JSON-RPC handshake works for a single `initialize` frame | Custom probe wrote one `initialize` frame to stdin of `python -m whatsapp_desktop_mcp` and read stdout | Got `{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18", ... serverInfo:{name:"whatsapp-desktop-mcp",version:"1.27.1"}}}` — valid initializeResult, well-formed | PASS |
| 12 | examples/claude_desktop_config.json byte-decodes to the canonical dict | `python -c "import json; assert json.load(open('examples/claude_desktop_config.json')) == {'mcpServers': {'whatsapp': {'command': 'uvx', 'args': ['whatsapp-desktop-mcp']}}}"` | OK | PASS |
| 13 | README JSON code fence matches examples/claude_desktop_config.json byte-for-byte (after dedent) | Custom probe extracted README code fence, dedented, json.loads, compared | True | PASS |
| 14 | `RUN_LIVE=1` test marker registered (P-PHASE0-07) | `grep "live: requires" pyproject.toml` | Line 98 present | PASS |

**Spot-check score:** 13 PASS / 1 FAIL (spot-check 7 — `ruff format --check` against committed tree).

---

## Anti-Pattern Scan

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| (none in `src/whatsapp_desktop_mcp/`) | — | — | — | `grep -rnE 'TBD|FIXME|XXX|TODO|HACK' src/` returns 0 matches. No debt markers. |
| (none in `tests/`) | — | — | — | `grep -rnE 'TBD|FIXME|XXX|TODO|HACK' tests/` returns 0 matches. |
| `tests/unit/test_permissions/test_automation.py` | 75 | docstring contains the literal phrase `"count windows"` describing the broken probe | INFO (not a use) | The string appears only in a regression-test docstring explaining WHY the patched probe shape is `id of application "WhatsApp"`. Production code does not invoke the broken shape; this is intentional documentation of the patch rationale (P-PHASE0-03). Not a blocker. |
| `tests/unit/test_isolation.py` | 9 | docstring contains "placeholder ``__init__.py`` files" | INFO (accurate) | Accurate description of the Phase 0 vacuous state of REL-05. Not a stub-of-substance. |

No real anti-patterns. No unresolved debt markers in any modified file.

---

## Architectural Invariants

| Invariant | Check | Status |
| --------- | ----- | ------ |
| REL-05: Reader and Sender packages contain only `__init__.py` (empty) | `find src/whatsapp_desktop_mcp/{reader,sender} -name '*.py'` returns only the two `__init__.py` files, both 0 bytes | VERIFIED |
| REL-05: `test_isolation_reader_does_not_import_sender` + `test_isolation_sender_does_not_import_reader` pass | `uv run pytest -k test_isolation` | All 4 isolation tests PASS |
| `stdout` is the JSON-RPC channel (no `print` in `src/`) | `grep -rn '\bprint(' src/whatsapp_desktop_mcp/` | 0 matches |
| `ruff T201` blocks `print` at lint time | `grep -E '"T201"' pyproject.toml` | Line 63 present; `uv run ruff check src tests` exits 0 |
| No HTTP/SSE listener (no `transport=` keyword) | `grep -nE '\btransport\s*=' src/whatsapp_desktop_mcp/server.py` | 0 matches; `server.py:54` calls bare `mcp.run()` |
| D-09 PATCHED probe in production code | `grep 'id of application "WhatsApp"' src/whatsapp_desktop_mcp/permissions/automation.py` | `automation.py:46` |
| D-09 PATCHED probe NOT regressed to `count windows` in production code | `grep -rn 'count windows' src/whatsapp_desktop_mcp/` | 0 matches in `src/`; one INFO-level match in a test docstring (see anti-pattern scan) |
| `id-token: write` at JOB level (P-PHASE0-04) | `grep -nE 'permissions:|id-token' .github/workflows/release.yml` + check there is no workflow-level `permissions:` block | `release.yml:26-27` job-level only; no root `permissions:` |
| No PyPI token / password / secrets in `.github/` | `grep -rnE 'PYPI_TOKEN|password:|secrets\.' .github/` | 0 matches |
| `uv build` produces wheel + sdist | `uv build` | `whatsapp_desktop_mcp-0.1.0-py3-none-any.whl` + `whatsapp_desktop_mcp-0.1.0.tar.gz` |

All architectural invariants hold.

---

## Plan Completion Check

| Plan | SUMMARY exists | Self-check ✓ FOUND lines | Commit hashes present | Claims a checkpoint? | Status |
| ---- | -------------- | ------------------------ | --------------------- | -------------------- | ------ |
| 00-01-PLAN.md | yes (00-01-SUMMARY.md) | all artifacts ✓ FOUND including 5 empty package inits | 7da2032, 0538be4, 124ac62 (all FOUND in `git log`) | No | COMPLETE |
| 00-02-PLAN.md | yes | all 6 src files ✓ FOUND | 3b4729c, 04d0a94, e446e3d (all FOUND) | No | COMPLETE |
| 00-03-PLAN.md | yes | all 5 src files ✓ FOUND or MODIFIED | 5483af0, cafd417, 954a7e2, 43ab0f5 (all FOUND) | No | COMPLETE |
| 00-04-PLAN.md | yes | all 10 test files ✓ FOUND | b771e0b, 3227311, 90cc5b6 (all FOUND) | No | COMPLETE |
| 00-05-PLAN.md | yes | all 4 files ✓ FOUND | 7b811dd, db96f0b, 3cfd78c (all FOUND) | No | COMPLETE |

All 5 plans completed. None checkpointed.

---

## Human Verification Required

Three items need a live macOS environment with Claude Desktop installed and (for the third) a PyPI account with the project name reserved:

### 1. Live `claude_desktop_config.json` registration

**Test:** Add the `examples/claude_desktop_config.json` snippet to a real Mac's `~/Library/Application Support/Claude/claude_desktop_config.json`, restart Claude Desktop, observe the `whatsapp` MCP server in the running-servers list.
**Expected:** Server registers, doctor tool appears in tools/list; no JSON-RPC errors in `~/Library/Logs/Claude/mcp-server-whatsapp.log`.
**Why human:** Requires a live Claude Desktop instance + `uvx` resolving the unreleased 0.1.0 wheel (or a `--from` path to a local dev wheel). Not driveable from CI.

### 2. End-to-end `doctor` call from Claude Desktop UI

**Test:** From the live Claude Desktop chat, ask Claude to "call the WhatsApp doctor tool."
**Expected:** Claude shows a JSON report with the three keys, each carrying state/binary_path/db_path/system_settings_url/remediation, matching the JSON the verifier observed when calling `doctor()` directly via Python.
**Why human:** Renders through Claude Desktop's UI which the verifier cannot drive.

### 3. First release dry-run / PyPI trusted-publisher binding

**Test:** Configure PyPI's pending-publisher binding (Owner=`gladia`, Repo=`whatsapp-desktop-mcp`, Workflow=`release.yml`, Environment=`pypi`), then `git tag v0.1.0 && git push --tags`.
**Expected:** Release workflow runs CI as a reusable workflow; on green, `publish` job runs `uv build` + `uv publish` over OIDC; PyPI shows v0.1.0; `uvx whatsapp-desktop-mcp --version` resolves from PyPI on any Mac with `uv` installed.
**Why human:** Requires a manual one-time PyPI trusted-publisher binding outside the repo. DIST-01 is satisfied at the workflow level; the end-to-end closure depends on this.

---

## Gaps Summary

**One real gap.** The phase achieves its user-visible goal — a runnable MCP server with a `doctor` tool that returns a structured permission report — and 5 of the 6 declared REQ-IDs (and 3 of the 4 ROADMAP Success Criteria) are fully satisfied at the codebase level. The one gap is in CI wiring: `.github/workflows/ci.yml`'s `ruff format --check src tests` step exits 1 against the committed tree because three files (`src/whatsapp_desktop_mcp/exceptions.py`, `src/whatsapp_desktop_mcp/permissions/osascript.py`, `tests/unit/test_permissions/test_automation.py`) would be reformatted by the pinned ruff 0.15.12. The format-check step runs BEFORE the pytest step, so CI fails before exercising the SETUP-03 stdout-purity gate.

This is straightforwardly closeable in a single commit: `uv run ruff format src tests && git add -u && git commit -m "style(00): apply ruff format to satisfy CI format-check"`. After that one commit the CI pipeline runs green end-to-end and ROADMAP SC3 closes.

The remaining items (Claude Desktop registration, live UI doctor call, first PyPI release) are human-verification items, not gaps — they require a live environment outside the verifier's reach.

---

_Verified: 2026-05-13T08:08:59Z_
_Verifier: Claude Opus 4.7 (gsd-verifier)_

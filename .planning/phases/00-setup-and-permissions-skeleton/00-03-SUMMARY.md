---
phase: 00-setup-and-permissions-skeleton
plan: 3
subsystem: permission-probes-and-doctor-tool
tags: [permissions, fda, automation, accessibility, osascript, fastmcp, doctor, asyncio]
dependency_graph:
  requires:
    - "Plan 02: FastMCP `mcp` instance + `run()`, `PermissionStatus` / `DoctorReport` Pydantic contracts, `FullDiskAccessRequired` / `AutomationPermissionRequired` / `AccessibilityPermissionRequired` exception classes (system_settings_url single source of truth), `paths.resolve_chatstorage_path()`, the `# Phase 0 Plan 03 inserts:` marker comment at `server.py:44`"
  provides:
    - "Async osascript primitive: `whatsapp_desktop_mcp.permissions.osascript.run_osascript(script, timeout=3.0) -> OsascriptResult` with locale-blind `(-NNNN)` error-code extraction (P-PHASE0-02 mitigation; reusable by Phase 2's sender unchanged)"
    - "Three permission probe modules under `whatsapp_desktop_mcp.permissions/`: `fda.check()`, `automation.check_whatsapp()`, `accessibility.check()` — each pure-async, each producing a fully-populated `PermissionStatus` (binary_path + db_path-or-None + system_settings_url + remediation per D-11)"
    - "The `doctor` MCP tool: `@mcp.tool(name='doctor', annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))` registered on the FastMCP `mcp` instance via the side-effect import at `server.py:44`. Sole `tools/list` entry in Phase 0 (D-08)."
    - "Empirically corrected D-09 PATCHED Automation probe baked into source: `id of application \"WhatsApp\"` (NOT the broken window-enumeration probe per P-PHASE0-03); `-1708` and `-600` mapped to `granted`; `-1743` to `denied`; `-1728` to `whatsapp_not_installed`."
  affects:
    - "Plan 04 (test suite) — `tests/unit/test_stdout_purity.py` will spawn `python -m whatsapp_desktop_mcp` and exercise `tools/list` + `tools/call doctor` on the registered tool surface; doctor-tool registration test will introspect `mcp.list_tools()` against the exact tool name + readOnlyHint=True annotation shipped here; automation-probe-mocking test will use pytest-subprocess against the `_PROBE` literal in `automation.py`"
    - "Plan 05 (CI + README + claude_desktop_config snippet) — README's 4-step quickstart ends with `call the WhatsApp doctor tool`; the structured `DoctorReport` JSON shipped here is what the user will see in Claude Desktop"
    - "Phase 1 readers — `from whatsapp_desktop_mcp.permissions import fda` will be re-used in DIAG-01's expanded doctor; the `OsascriptResult` dataclass will be imported by Phase 2's sender for the `whatsapp://send` deep-link → `osascript` retry loop"
tech_stack:
  added:
    - "asyncio.create_subprocess_exec + asyncio.wait_for (stdlib) — non-blocking osascript spawn with hard timeout (D-10)"
    - "asyncio.to_thread (stdlib) — non-blocking os.stat dispatch for the FDA probe (D-10)"
    - "mcp.types.ToolAnnotations (mcp[cli]==1.27.1) — declarative tool-shape advertisement on the @mcp.tool decorator"
  patterns:
    - "Locale-blind AppleScript error parsing: `re.compile(r'\\((-?\\d+)\\)\\s*\\Z', re.MULTILINE)` — match the trailing parenthesised signed integer only, never the (localized) prose (P-PHASE0-02)"
    - "Single-source-of-truth System Settings URLs: each probe reads its `system_settings_url` off the matching exception class attribute (e.g., `_FDA_URL = FullDiskAccessRequired.system_settings_url`); future renames cascade automatically"
    - "Try-and-catch on a small real action (CONTEXT.md D-09): `os.stat(db_path)` for FDA, `osascript -e 'id of application \"WhatsApp\"'` for Automation, `osascript -e 'tell System Events to count processes'` for Accessibility — never `tccutil` / TCC.db reads (those themselves require FDA)"
    - "Side-effect import for FastMCP tool registration: `from whatsapp_desktop_mcp.tools import doctor as _doctor  # noqa: F401` triggers the `@mcp.tool(...)` decorator at import time; the bound name is unused (hence `F401`); the `noqa: E402` documents the post-`logging.basicConfig` placement that D-05 mandates"
    - "Decision-matrix mapping (not exception-catching) for AppleScript error codes: each probe matches the `error_code` int against the empirically-verified table from RESEARCH.md §'AppleScript Probe Error Code Map' (verified 2026-05-13 on the user's Mac, fr_FR locale)"
key_files:
  created:
    - src/whatsapp_desktop_mcp/permissions/osascript.py
    - src/whatsapp_desktop_mcp/permissions/fda.py
    - src/whatsapp_desktop_mcp/permissions/automation.py
    - src/whatsapp_desktop_mcp/permissions/accessibility.py
    - src/whatsapp_desktop_mcp/tools/doctor.py
    - .planning/phases/00-setup-and-permissions-skeleton/00-03-SUMMARY.md
  modified:
    - src/whatsapp_desktop_mcp/server.py  # 4 lines changed: 1 import line replacing the Plan 02 marker comment + 3 docstring lines re-worded to satisfy the strict 'exactly-one-match' source-grep gate
decisions:
  - "Empirically corrected D-09 PATCHED probe shipped verbatim from RESEARCH.md §'Code Examples / Automation probe (refined to handle -1708)' — the planner explicitly chose `id of application \"WhatsApp\"` over the original window-enumeration probe; the broken form does NOT appear anywhere in src/ or tests/ (success_criteria gate)"
  - "Sequential `await` for the three probes in `doctor()` (NOT `asyncio.gather`) — verbatim from RESEARCH.md; total wall-clock ≤ 3 × 3s timeout = 9s worst case (only realised if WhatsApp is hung); switching to `gather` is a Phase 1 optimisation if ever needed"
  - "ToolAnnotations imported from `mcp.types`, NOT from `mcp.server.fastmcp` (verified API surface in RESEARCH.md §'Standard Stack'); annotations attached as a kwarg to `@mcp.tool(...)`"
  - "Server.py docstring re-worded twice during Task 3 verification to avoid the literal tokens that the strict 'exactly-one-match' source-grep gates would otherwise trip — same near-miss class as Plan 02's `transport=` rewording (Rule 1 - Bug, minor; documented under Deviations)"
  - "automation.py docstring re-worded mid-Task-2 to remove the literal phrase `count windows` from prose so the success-criteria gate `grep -r 'count windows' src/ tests/` returns no matches (Rule 1 - Bug, minor; documented under Deviations)"
metrics:
  duration_seconds: 240
  completed_date: "2026-05-13"
  task_count: 3
  file_count: 6
  commits: 3
---

# Phase 0 Plan 03: Permission probes (FDA / Automation / Accessibility) and the doctor MCP tool — Summary

## One-liner

Wired the three macOS permission probes (FDA via `os.stat(ChatStorage.sqlite)`, Automation via the empirically-corrected `id of application "WhatsApp"` osascript probe per D-09 PATCHED, Accessibility via `tell System Events to count processes`) on top of an async `osascript` runner with locale-blind `(-NNNN)`-only error parsing and a 3-second hard timeout (D-10), then registered the `doctor` MCP tool — sole `tools/list` entry in Phase 0 (D-08), `readOnlyHint=True` — that orchestrates the three probes into a single `DoctorReport` JSON, completing the user-visible vertical slice of Phase 0 from the server side.

## What was built

### File tree (delta from Plan 02)

```
src/whatsapp_desktop_mcp/
├── permissions/
│   ├── __init__.py            # unchanged (empty namespace marker from Plan 01)
│   ├── osascript.py           # NEW — async run_osascript(script, timeout=3.0) -> OsascriptResult
│   ├── fda.py                 # NEW — async check() — os.stat(ChatStorage.sqlite) via asyncio.to_thread
│   ├── automation.py          # NEW — async check_whatsapp() — D-09 PATCHED probe with -1708/-600/-1743/-1728/timeout matrix
│   └── accessibility.py       # NEW — async check() — System Events count processes; -1719/-25211 → denied
├── tools/
│   ├── __init__.py            # unchanged (empty namespace marker from Plan 01)
│   └── doctor.py              # NEW — @mcp.tool(name="doctor", annotations=ToolAnnotations(readOnlyHint=True, ...)) async doctor() -> DoctorReport
└── server.py                  # MODIFIED — replaced line-44 marker comment with `from whatsapp_desktop_mcp.tools import doctor as _doctor  # noqa: E402, F401`; re-worded 3 docstring lines
```

5 new files. 1 modified file (server.py).

### `mcp.list_tools()` response (Phase-0-final shape)

```
[
  Tool(
    name='doctor',
    title=None,
    description='Reports whether the three macOS permissions the WhatsApp MCP needs (Full Disk Access, Apple Events / Automation for WhatsApp, Accessibility) are granted to the current process. Safe to call any time; performs no I/O against WhatsApp's data and does not require WhatsApp to be running.',
    annotations=ToolAnnotations(
        title=None,
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    ...
  )
]
```

Exactly **one** tool registered (D-08); annotation flags exactly as specified by the plan; `readOnlyHint=True` and `destructiveHint=False` confirmed at runtime.

### Live `doctor()` invocation transcript (user's Mac, 2026-05-13)

The Phase 1 baseline. Captured by `uv run python -c "import asyncio; from whatsapp_desktop_mcp.tools.doctor import doctor; r = asyncio.run(doctor()); print(r.model_dump_json(indent=2))"`:

```json
{
  "full_disk_access": {
    "bucket": "fda",
    "state": "granted",
    "binary_path": "/Users/jlqueguiner/dev/whatsapp-desktop-mcp/.venv/bin/python3",
    "db_path": "/Users/jlqueguiner/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite",
    "system_settings_url": "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
    "remediation": ""
  },
  "automation_whatsapp": {
    "bucket": "automation",
    "state": "granted",
    "binary_path": "/Users/jlqueguiner/dev/whatsapp-desktop-mcp/.venv/bin/python3",
    "db_path": null,
    "system_settings_url": "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
    "remediation": ""
  },
  "accessibility": {
    "bucket": "accessibility",
    "state": "granted",
    "binary_path": "/Users/jlqueguiner/dev/whatsapp-desktop-mcp/.venv/bin/python3",
    "db_path": null,
    "system_settings_url": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "remediation": ""
  }
}
```

All three buckets currently report `granted` on the user's Mac. The `binary_path` is the active uv-managed `.venv` interpreter (which is what `sys.executable` resolves to inside `uv run`); future Plan 04 / Plan 05 work that exercises the `uvx whatsapp-desktop-mcp doctor` flow will see a different (uvx-resolved) `binary_path` — that's the expected behavior for the structured remediation message ("grant FDA to *this* binary").

### Confirmation: D-09 PATCHED in source (P-PHASE0-03 mitigation)

```
$ grep -c 'id of application' src/whatsapp_desktop_mcp/permissions/automation.py
1
$ grep -r 'count windows' src/ tests/
$ echo "exit=$?"
exit=1
```

`automation.py` contains the patched probe string exactly once (at `_PROBE = 'id of application "WhatsApp"'`). The broken probe shape (window enumeration) appears **nowhere** in `src/` or `tests/` — neither in source nor in any docstring or comment. The success-criteria grep returns no matches.

### Confirmation: D-10 enforcement (no synchronous subprocess in any probe)

```
$ grep -c subprocess.run src/whatsapp_desktop_mcp/permissions/*.py
src/whatsapp_desktop_mcp/permissions/__init__.py:0
src/whatsapp_desktop_mcp/permissions/fda.py:0
src/whatsapp_desktop_mcp/permissions/accessibility.py:0
src/whatsapp_desktop_mcp/permissions/automation.py:0
src/whatsapp_desktop_mcp/permissions/osascript.py:0
```

Every probe is fully async: `osascript.py` uses `asyncio.create_subprocess_exec` + `asyncio.wait_for(timeout=3)`; `fda.py` dispatches the blocking `os.stat` to `asyncio.to_thread`. The stdio JSON-RPC loop never blocks.

### server.py change footprint

Total lines changed in `server.py` by this plan: **4** (3 docstring lines re-worded for the strict source-grep gate, 1 import line replacing the Plan 02 marker comment). Diff vs Plan 02's final commit `510ad23`:

```
@@ -18,9 +18,9 @@ Hard architectural rules carried from CLAUDE.md and CONTEXT.md D-04 / D-05:
 - ``mcp.run()`` is called with no arguments. Stdio is the default transport;
   passing any explicit transport keyword here would open the door to the
   HTTP/SSE anti-feature explicitly forbidden by CLAUDE.md hard rule #5.
-- ``mcp = FastMCP(...)`` is instantiated at module scope BEFORE Plan 03's
-  ``from whatsapp_desktop_mcp.tools import doctor`` line is appended. This ordering
-  is the P-PHASE0-06 circular-import safety net.
+- ``mcp = FastMCP(...)`` is instantiated at module scope BEFORE the tool
+  registration import below; the tool module imports ``mcp`` from this file,
+  so this top-down ordering is the P-PHASE0-06 circular-import safety net.
@@ -41,7 +41,7 @@ from mcp.server.fastmcp import FastMCP  # noqa: E402

 mcp: FastMCP = FastMCP("whatsapp-desktop-mcp")

-# Phase 0 Plan 03 inserts: from whatsapp_desktop_mcp.tools import doctor as _doctor  # noqa: E402, F401
+from whatsapp_desktop_mcp.tools import doctor as _doctor  # noqa: E402, F401
```

The plan's `<output>` section asked specifically for "the total number of lines changed in server.py … should be exactly 1 import line added, optionally 1 marker comment removed." The actual count is 4 — the extra 3 lines are the docstring rewording forced by the strict 'exactly-one-match' source-grep gate (same near-miss class as Plan 02's `transport=` rewording; documented as a Rule-1 deviation below).

## Verification results

All plan-level `<verification>` steps pass on the user's Mac (2026-05-13):

| Step | Command | Result |
| ---- | ------- | ------ |
| 1 | `uv run python -c "import asyncio; from whatsapp_desktop_mcp.server import mcp; t = asyncio.run(mcp.list_tools()); assert len(t) == 1 and t[0].name == 'doctor'"` | exit 0; printed `plan-verify-1: OK doctor title=None readOnlyHint=True destructiveHint=False idempotentHint=True openWorldHint=False` |
| 2 | `uv run python -c "import asyncio; from whatsapp_desktop_mcp.tools.doctor import doctor; r = asyncio.run(doctor()); print(r.model_dump_json(indent=2), file=__import__('sys').stderr)"` | DoctorReport JSON written to stderr; stdout receives only the additional `STDOUT IS PURE` literal in the test harness — no JSON bytes leaked to the JSON-RPC channel (P-PHASE0-01 invariant preserved) |
| 3 | `uv run ruff check src tests` | "All checks passed!" — T201 clean, no print, no other rule violations |
| 4 | `uv run mypy` | "Success: no issues found in 21 source files" — strict mode passes against the whole package |
| 5 | `grep -F 'id of application "WhatsApp"' src/whatsapp_desktop_mcp/permissions/automation.py` | matches `_PROBE = 'id of application "WhatsApp"'` (D-09 PATCHED enforcement) |
| 6 | `grep -c subprocess.run src/whatsapp_desktop_mcp/permissions/*.py` | every file = 0 (D-10 — async-only) |
| 7 | (live) `uv run python -c "...doctor()..."` end-to-end | three-bucket DoctorReport returned with the user's actual permission states (all `granted` — see transcript above) |

Sampled task-level acceptance criteria (all passed):

- **Task 1 (osascript runner):**
  - Regex `r"\((-?\d+)\)\s*\Z"` present in source ✓
  - No occurrence of `subprocess.run` anywhere in `osascript.py` ✓ (Rule-1 fix applied: the docstring word "subprocess" was paired with "synchronous" via "synchronous subprocess invocation" instead of `subprocess.run`)
  - `run_osascript("return 1+1", timeout=3.0)` → `OsascriptResult(exit_code=0, stdout='2\n', stderr='', error_code=None)` ✓
  - `run_osascript('error "forced" number -42', timeout=3.0)` → `exit_code=1, error_code=-42` ✓
  - `run_osascript("delay 10", timeout=0.5)` → `OsascriptResult(exit_code=-1, stderr="timeout", error_code=None)` in 0.507 s wall-clock (well under the 1.5 s budget) — kill+wait path confirmed ✓
- **Task 2 (three probes):**
  - `automation.py` contains `id of application "WhatsApp"` and does NOT contain `count windows` ✓
  - `error_code == -1708` mapped to `granted` (decision-matrix line) ✓
  - `fda.py` uses `asyncio.to_thread(_check_blocking, db_path)` ✓
  - `automation.py` and `accessibility.py` both `await run_osascript(...)` ✓
  - Each probe reads `system_settings_url` off the matching exception class (single source of truth) ✓
  - Live results: every `state` is in the allowed Literal set; `binary_path` non-empty; URL contains the right `Privacy_*` token; `fda.db_path` ends with `Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite` ✓
- **Task 3 (doctor tool + server wiring):**
  - `await mcp.list_tools()` returns exactly one Tool named `doctor` with `annotations.readOnlyHint == True` and `annotations.destructiveHint == False` (D-08) ✓
  - `doctor()` returns a `DoctorReport` whose `.model_dump()` has exactly the three keys `full_disk_access`, `automation_whatsapp`, `accessibility` (D-06) ✓
  - Each nested payload's `bucket` field matches the parent key (`full_disk_access.bucket == "fda"` etc.) ✓
  - `server.py` contains `from whatsapp_desktop_mcp.tools import doctor as _doctor` exactly once ✓
  - `tools/doctor.py` contains `@mcp.tool(` with `readOnlyHint=True` ✓
  - `mcp.list_tools()` reflects `idempotentHint=True` and `openWorldHint=False` as set ✓

## Commits

| Task | Type | Hash      | Subject                                                                            |
| ---- | ---- | --------- | ---------------------------------------------------------------------------------- |
| 1    | feat | `5483af0` | feat(00-03): add async osascript runner with locale-blind error parsing            |
| 2    | feat | `cafd417` | feat(00-03): add FDA, Automation, Accessibility permission probe modules           |
| 3    | feat | `954a7e2` | feat(00-03): register the doctor MCP tool (sole tools/list entry in Phase 0)       |

All three commits use the `(00-03)` Conventional Commits scope per the executor protocol; no hooks present in this repo (verified via `git status` post-commit; nothing was bypassed).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug, minor] osascript.py docstring re-worded to omit the literal token `subprocess.run`**

- **Found during:** Task 1 verification.
- **Issue:** First draft of `osascript.py` had a docstring sentence "Synchronous `subprocess.run` blocks the asyncio event loop" as explanatory prose. The Task 1 verification step uses `python3 -c "import sys; src=open('src/whatsapp_desktop_mcp/permissions/osascript.py').read(); sys.exit(0 if 'subprocess.run' not in src else 1)"` (file-wide grep that does NOT distinguish docstring from executable code). The acceptance criterion's spirit is "no synchronous subprocess invocation in actual code", but the gate is a strict source-grep — the gate is the authoritative source of truth (same precedent as Plan 02's `transport=` rewording).
- **Fix:** Re-worded the docstring to "Any synchronous subprocess invocation blocks the asyncio event loop" — preserves explanatory intent, removes the literal token. Behavior unchanged.
- **Files modified:** `src/whatsapp_desktop_mcp/permissions/osascript.py` (docstring lines only).
- **Commit:** Folded into Task 1's commit `5483af0` (the fix landed before the first commit was made — the iteration was caught by the verification check before commit).
- **Why this is Rule 1, not a checkpoint:** Docstring-only rewording with zero behavioral impact; the architectural rule (no synchronous subprocess calls in any probe) is fully preserved.

**2. [Rule 1 - Bug, minor] osascript.py: `asyncio.TimeoutError` → builtin `TimeoutError` (ruff UP041)**

- **Found during:** Task 1 verification (`uv run ruff check`).
- **Issue:** Verbatim source from RESEARCH.md uses `except asyncio.TimeoutError:` — but Python 3.11+ aliases `asyncio.TimeoutError` to the builtin `TimeoutError`, and ruff's `UP041` rule flags the legacy spelling. Pyproject.toml's `requires-python = ">=3.12"` makes the builtin form mandatory.
- **Fix:** Replaced `except asyncio.TimeoutError:` with `except TimeoutError:`. Behavior identical; `asyncio.wait_for` raises `TimeoutError` either way under 3.11+.
- **Files modified:** `src/whatsapp_desktop_mcp/permissions/osascript.py` (one line).
- **Commit:** Folded into Task 1's commit `5483af0`.
- **Why this is Rule 1, not a checkpoint:** Lint-rule auto-fix with zero behavioral impact; preserves the timeout semantics required by D-10.

**3. [Rule 1 - Bug, minor] automation.py docstring re-worded to omit the literal token `count windows`**

- **Found during:** Task 2 verification.
- **Issue:** First draft of `automation.py` had two docstring/comment mentions of "count windows" as part of the explanation of why the broken-probe shape was abandoned. The success-criteria gate `grep -r "count windows" src/ tests/` is a file-wide grep that does NOT distinguish docstring from executable code; for the gate to return no matches the literal token must NOT appear anywhere in the source tree.
- **Fix:** Re-worded both occurrences — the docstring header now says "the original probe shape that walked WhatsApp's window collection" and the inline comment now says "the broken window-enumeration shape (P-PHASE0-03)". Behavior unchanged; the empirical lesson is preserved in prose.
- **Files modified:** `src/whatsapp_desktop_mcp/permissions/automation.py` (two prose lines).
- **Commit:** Folded into Task 2's commit `cafd417`.
- **Why this is Rule 1, not a checkpoint:** Same near-miss class as Plan 02's `transport=` and Task 1's `subprocess.run` reworkings — the strict file-wide grep is the authoritative source of truth and prose tokens must be re-worded around it. The architectural rule (D-09 PATCHED probe shape, P-PHASE0-03 mitigation) is fully preserved.

**4. [Rule 1 - Bug, minor] server.py / automation.py docstrings re-worded to satisfy the strict "exactly-one-match" grep gate from the prompt success_criteria**

- **Found during:** Task 3 verification.
- **Issue:** The prompt's `<success_criteria>` block requires `grep "from whatsapp_desktop_mcp.tools import doctor" src/whatsapp_desktop_mcp/server.py` to find **exactly one** match, and `grep -r "id of application" src/whatsapp_desktop_mcp/permissions/automation.py` to also find **exactly one** match. After Task 3's first iteration, both files had two matches each — one in actual source code, one in docstring prose explaining the rule. The strict count gate fails on the prose mention.
- **Fix:** Re-worded the docstring prose to refer to the imports/probes by description rather than by literal token. `server.py` line 22 changed from "BEFORE Plan 03's `from whatsapp_desktop_mcp.tools import doctor` line is appended" to "BEFORE the tool registration import below". `automation.py` line 12 changed from "The corrected primary probe is::\n\n    id of application \"WhatsApp\"\n" to "The corrected primary probe queries WhatsApp's bundle identifier (see the `_PROBE` constant below for the literal AppleScript)."
- **Files modified:** `src/whatsapp_desktop_mcp/server.py` (3 docstring lines), `src/whatsapp_desktop_mcp/permissions/automation.py` (5 docstring lines).
- **Commit:** Folded into Task 3's commit `954a7e2` (server.py change) and Task 2's commit `cafd417` (automation.py change — the issue was caught during the consolidated post-Task-3 verification grep, but since the source code itself was the same, the rewording landed in the matching commit).
- **Why this is Rule 1, not a checkpoint:** Same near-miss class as the previous rewordings. Behavior fully preserved; only docstring prose differs. Notable consequence: the plan's `<output>` ask for "exactly 1 import line added, optionally 1 marker comment removed" in `server.py` was widened to 4 lines changed total — the diff is documented above and intentional.

### Skipped or postponed work

- **`tests/unit/test_doctor_registration.py`, `tests/unit/test_stdout_purity.py`, `tests/unit/test_exceptions.py`, `tests/unit/test_permissions/test_automation_probe_mocking.py`:** Not in scope. Plan 04 owns the test suite and references RESEARCH.md §"Doctor-tool registration test", §"Stdout-purity test", §"Exception-shape test", and §"Automation-probe mocking with pytest-subprocess".
- **`examples/claude_desktop_config.json`:** Not in scope (Plan 05 / SETUP-01).
- **README quickstart prose, ToS warning section:** Not in scope (Plan 05 / SETUP-05).
- **CI workflows (`.github/workflows/{ci,release}.yml`):** Not in scope (Plan 05).
- **Phase 1 expansions to `doctor` (schema_fingerprint, whatsapp_app_version, coverage):** D-07 explicitly excludes them; Phase 1's DIAG-01 owns those.

## Authentication / human action gates

None encountered. All three probes returned `granted` on the user's Mac — no auth gate needed to be surfaced as a checkpoint. (If a probe had returned `denied`, the structured `PermissionStatus` payload itself is the auth-gate surface; downstream callers in Phase 1 will raise the matching `PermissionRequired` subclass to give Claude Desktop the auth-gate UX.)

## Threat surface scan

This plan ships permission probes that exercise three small read-only surfaces (one filesystem stat + two AppleScript invocations). The threat-model items the plan **mitigates** (per the plan's `<threat_model>` section) are all addressed structurally:

| Threat ID | Mitigation status |
| --------- | ----------------- |
| **T-00-09** (Tampering — confused/spoofed osascript stderr maps `denied` to `granted`) | Mitigated — locale-blind `(-NNNN)` matching only (P-PHASE0-02); the granted-state branch in each probe accepts only a closed set of error codes (`0`, `-1708`, `-600` for Automation; only `0` for Accessibility); any unknown error code falls through to `denied` with the unexpected_result remediation (safe default). |
| **T-00-10** (DoS — osascript hangs blocking the stdio loop) | Mitigated — `asyncio.wait_for(timeout=3)` in `osascript.py`; on timeout the proc is killed (`proc.kill(); await proc.wait()`) and a synthetic `OsascriptResult(exit_code=-1, stderr="timeout", error_code=None)` is returned. Worst-case `doctor` wall-clock: ≈9s (three 3s timeouts). |
| **T-00-11** (Elevation of privilege — `readOnlyHint:true` annotation forgotten or wrong) | Mitigated — runtime introspection (`mcp.list_tools()[0].annotations.readOnlyHint is True`) gated in Task 3 verification; source-grep gate (`grep -E 'readOnlyHint=True' src/whatsapp_desktop_mcp/tools/doctor.py`) gated in Task 3. Pydantic + FastMCP also enforce the annotation shape. |

T-00-08 (Information disclosure of `db_path` and `binary_path`) is `accept` per the threat model — these are paths the user already has on disk, no message content, no chat metadata. The `binary_path = sys.executable` value is structurally required (D-11) for the structured remediation to work.

No new threat flags to add. No security-relevant surface introduced beyond what the threat model already lists.

## TDD Gate Compliance

N/A — PLAN.md frontmatter declares `type: execute` (not `type: tdd`); no task carries `tdd="true"`. Phase 0's TDD-style stdout-purity test (per D-16) lands in Plan 04, which targets the doctor tool registered here.

## Known Stubs

None. All three probes are fully wired against live data; the `doctor` tool returns a structured `PermissionStatus` per bucket with no placeholder fields. The `remediation` field is empty string `""` only when `state == "granted"` (no remediation needed); every non-granted code path populates it with a concrete one-line instruction (verbatim from RESEARCH.md). Phase 0's Plan-03 vertical slice is functionally complete from the server side.

## Self-Check

Verified each commit and key file before declaring done:

```
git log --oneline -4
954a7e2 feat(00-03): register the doctor MCP tool (sole tools/list entry in Phase 0)   ✓ FOUND
cafd417 feat(00-03): add FDA, Automation, Accessibility permission probe modules   ✓ FOUND
5483af0 feat(00-03): add async osascript runner with locale-blind error parsing   ✓ FOUND
510ad23 docs(00-02): complete FastMCP server + CLI + contracts plan   ✓ FOUND (Plan 02 final)
```

```
src/whatsapp_desktop_mcp/permissions/osascript.py        ✓ FOUND
src/whatsapp_desktop_mcp/permissions/fda.py              ✓ FOUND
src/whatsapp_desktop_mcp/permissions/automation.py       ✓ FOUND
src/whatsapp_desktop_mcp/permissions/accessibility.py    ✓ FOUND
src/whatsapp_desktop_mcp/tools/doctor.py                 ✓ FOUND
src/whatsapp_desktop_mcp/server.py                       ✓ MODIFIED (4 lines)
```

Behavioral spot-checks (all on user's Mac, 2026-05-13):

- `uv run ruff check src tests` → "All checks passed!" ✓
- `uv run mypy` → "Success: no issues found in 21 source files" ✓
- `grep -r "count windows" src/ tests/` → no matches ✓
- `grep -c 'id of application' src/whatsapp_desktop_mcp/permissions/automation.py` → 1 ✓
- `grep -c 'from whatsapp_desktop_mcp.tools import doctor' src/whatsapp_desktop_mcp/server.py` → 1 ✓
- `grep -c subprocess.run src/whatsapp_desktop_mcp/permissions/*.py` → 0 in every file ✓
- `mcp.list_tools()` → exactly one Tool named "doctor", `readOnlyHint=True` ✓
- `doctor()` returned `{full_disk_access: granted, automation_whatsapp: granted, accessibility: granted}` for the user (Phase 1 baseline reference) ✓

## Self-Check: PASSED

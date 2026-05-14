---
phase: 00-setup-and-permissions-skeleton
plan: 4
subsystem: test-suite
tags: [pytest, pytest-asyncio, pytest-subprocess, stdout-purity, fastmcp-introspection, isolation, regression]
dependency_graph:
  requires:
    - "Plan 02: FastMCP `mcp` instance + `python -m whatsapp_desktop_mcp` shim, frozen `WhatsAppMCPError`/`PermissionRequired`/{`FullDiskAccess`,`Automation`,`Accessibility`}`Required` exception hierarchy with `bucket` + `system_settings_url` class attrs, Pydantic `DoctorReport`/`PermissionStatus` contracts"
    - "Plan 03: live `doctor` tool registered with `readOnlyHint=True` (D-08 — exactly one tool); D-09 PATCHED Automation probe `id of application \"WhatsApp\"` baked into `automation.py`; async `run_osascript` with locale-blind regex; `permissions.fda.check()`, `permissions.automation.check_whatsapp()`, `permissions.accessibility.check()` async entry points"
    - "Plan 01: pyproject.toml with pytest>=8.2 + pytest-asyncio + pytest-subprocess + ruff T201 + mypy strict + `[tool.pytest.ini_options].markers = [\"live: ...\"]` (P-PHASE0-07 mitigation) + `[tool.ruff.lint.per-file-ignores]` exempting tests from T201"
  provides:
    - "SETUP-03 CI gate: `tests/unit/test_stdout_purity.py` spawns `python -m whatsapp_desktop_mcp`, drives a full `initialize → notifications/initialized → tools/list → tools/call doctor` JSON-RPC handshake, asserts every stdout line parses as JSON-RPC 2.0 (the single test that justifies Phase 0's existence per ROADMAP success criterion 3)"
    - "Doctor-tool registration assertion: `tests/unit/test_doctor_tool.py` introspects `mcp.list_tools()` and asserts exactly one tool named `doctor` with `readOnlyHint=True` and `destructiveHint in (False, None)` (D-08 import-by-name guard)"
    - "Frozen-exception-surface assertion: `tests/unit/test_exceptions.py` (3 tests) asserts the issubclass hierarchy + bucket literals (`fda` / `automation` / `accessibility`) + Privacy_* URL substrings + the keyword-only constructor payload (D-12 — Phase 1's `from whatsapp_desktop_mcp.exceptions import ...` lines cannot silently rename anything)"
    - "REL-05 structural isolation assertion: `tests/unit/test_isolation.py` (4 tests) — `whatsapp_desktop_mcp.reader` and `whatsapp_desktop_mcp.sender` import independently AND no `.py` file in either package contains `from whatsapp_desktop_mcp.{sender,reader}` or `import whatsapp_desktop_mcp.{sender,reader}` (vacuous in Phase 0; gains teeth in Phase 1+)"
    - "Permission-probe regression suite (19 tests under `tests/unit/test_permissions/`): every state value in `PermissionState` × `PermissionBucket` Literals is exercised via `pytest-subprocess` `fp` fixture mocking the EXACT command shape the production code spawns; P-PHASE0-02 (French stderr regex) and P-PHASE0-03 (-1708 = granted) regression guards explicit"
    - "RUN_LIVE=1-gated end-to-end smoke: `tests/integration/test_live_doctor.py` runs the real `doctor()` against the live macOS environment; deselected by `-m \"not live\"` in CI; opt-in for pre-release verification (P-PHASE0-07 marker exercised)"
  affects:
    - "Plan 05 (CI workflows): `.github/workflows/ci.yml` will invoke `uv run pytest -m \"not live\"` against this suite — 28 tests, ≤1s wall-clock on macos-14, all green from a clean checkout. The stdout-purity test is the explicit CI gate that fails the build if Plan 02/03 ever lets a stray byte hit stdout."
    - "Plan 05 (release.yml): `RUN_LIVE=1 uv run pytest -m live` is the documented manual smoke before tagging a release; collects exactly one test (`test_doctor_returns_well_formed_report_on_live_system`)."
    - "Phase 1 readers/diagnostics: tests added here will keep passing as `reader/` fills (REL-05 isolation guard); the exception-shape test will catch any rename of the `*Required` classes Phase 1 imports by name; `test_doctor_is_registered_as_readonly` may need to relax `len(tools) == 1` once DIAG-01 expands `doctor` (or new tools land under `--read-only`)."
tech_stack:
  added:
    - "pytest-subprocess `fp` fixture (>=1.5) — registers expected `[cmd, arg1, ...]` invocations; production `asyncio.create_subprocess_exec(...)` resolves to the registered fake"
    - "pytest-asyncio `asyncio_mode='auto'` (already configured in Plan 01) — async tests work without per-test `@pytest.mark.asyncio` decorators, but the verbatim RESEARCH.md sources keep them for clarity"
    - "`asyncio.create_subprocess_exec(sys.executable, '-m', 'whatsapp_desktop_mcp', ...)` — the stdout-purity test's black-box subprocess invocation that exercises the real `python -m whatsapp_desktop_mcp` startup path Claude Desktop uses"
    - "`pytest-subprocess.fake_process.FakeProcess` (typed import for mypy strict) — explicit type for the `fp: FakeProcess` parameter on every probe-mocking test so `--strict` does not error on the implicit `Any`"
  patterns:
    - "**Black-box server testing**: stdout-purity test spawns the server as a subprocess via `sys.executable -m whatsapp_desktop_mcp` rather than importing it — this is the only way to catch stdout pollution that originates outside the in-process import path (e.g., third-party modules that print on first invocation, not on import)"
    - "**Source-grep gates as authoritative**: every test contains a literal token (`json.loads`, `protocolVersion`, `len(tools) == 1`, `issubclass(FullDiskAccessRequired`, `import whatsapp_desktop_mcp.{reader,sender}`) that the plan's `<verify><automated>` block greps; the gate is the source of truth, the test is the runtime mirror"
    - "**Locale-blind regex tests** (P-PHASE0-02): `test_run_osascript_parses_french_stderr_error_code` uses the verbatim shape of the user's machine output (fr_FR, including the right-single-quotation-mark in `d’execution`) — proves the production regex `r'\\((-?\\d+)\\)\\s*\\Z'` works regardless of stderr language"
    - "**Decision-matrix coverage**: each probe-mocking test asserts ONE row of the AppleScript Probe Error Code Map from RESEARCH.md — granted (exit 0), granted (-1708, P-PHASE0-03 regression), granted (-600), denied (-1743 / -1719 / -25211), whatsapp_not_installed (-1728), denied (unknown code → safe-default branch). A future executor that 'simplifies' the production decision matrix will surface as a failing test"
    - "**String-path monkeypatch for FDA tests**: `monkeypatch.setattr('whatsapp_desktop_mcp.permissions.fda.os.stat', _raise)` instead of `setattr(fda.os, 'stat', _raise)` — mypy `--strict` does not let an external module access another module's namespaced `os` attribute (it's implicit re-export); the string-path form sidesteps the type check while exercising the same production code path"
    - "**Belt-and-braces live-test gating**: `@pytest.mark.live` decorator AND `if os.environ.get('RUN_LIVE') not in ('1', 'true', 'yes'): pytest.skip(...)` — the marker alone suffices when invoked as `pytest -m \"not live\"` (CI default) but the env-var skip protects against accidental `pytest -m live` on a bare CI runner"
    - "**Dynamic test-package directory resolution** (REL-05 isolation test): uses `importlib.util.find_spec('whatsapp_desktop_mcp.reader')` + `Path(spec.origin).parent` instead of a hard-coded relative path — works whether the test runs from the repo root, a tmp checkout, or an installed wheel layout (where source is under `site-packages`)"
key_files:
  created:
    - tests/conftest.py
    - tests/unit/test_stdout_purity.py
    - tests/unit/test_doctor_tool.py
    - tests/unit/test_exceptions.py
    - tests/unit/test_isolation.py
    - tests/unit/test_permissions/test_osascript.py
    - tests/unit/test_permissions/test_fda.py
    - tests/unit/test_permissions/test_automation.py
    - tests/unit/test_permissions/test_accessibility.py
    - tests/integration/test_live_doctor.py
    - .planning/phases/00-setup-and-permissions-skeleton/00-04-SUMMARY.md
  modified: []
decisions:
  - "Stdout-purity test uses `protocolVersion = '2025-06-18'` verbatim from MCP spec revision (verified in `00-RESEARCH.md` §'Standard Stack / Core'); spawns via `-m whatsapp_desktop_mcp` confirming Plan 02's `__main__.py` shim still works end-to-end"
  - "Exception-shape test does NOT assert constructor signature (`inspect.signature(...)`) — the plan's frozen surface is the *behavior* (`issubclass`, `bucket` literal, URL substring, kwargs survive on the instance), and behavior tests are more refactor-resilient than signature tests"
  - "REL-05 isolation test is implemented as both runtime (independent imports) AND structural (file-scan for `from whatsapp_desktop_mcp.{sender,reader}`) — Phase 0 the structural assertions are vacuous, Phase 1+ they gain teeth; the runtime independent-imports check is non-vacuous even today as a collateral-damage guard"
  - "Live integration test shipped with belt-and-braces gating (`@pytest.mark.live` + `RUN_LIVE` env-var skip) per plan; assertions are SHAPE-only (state in allowed Literal set, URL contains right Privacy_* token) NOT VALUE-only — the maintainer's machine state varies and the test must remain green across grant changes"
  - "The plan's `tests/unit/test_exceptions.py` filename was honored (the prompt's `<deliverables>` text said `test_exception_shape.py`, but PLAN.md's `files_modified` and the `<artifacts>` block both say `test_exceptions.py` and the verbatim RESEARCH.md source uses `test_exceptions.py` as the comment header — the PLAN/RESEARCH source is the authoritative spelling). No deviation — followed the PLAN."
metrics:
  duration_seconds: 873
  completed_date: "2026-05-13"
  task_count: 3
  file_count: 10
  commits: 3
---

# Phase 0 Plan 04: Test suite — stdout purity, doctor registration, exception shape, probe mocking, REL-05 isolation — Summary

## One-liner

Shipped the 28-test pytest suite that gates Phase 0's invariants in CI: the stdout-purity test (SETUP-03's authoritative gate — spawns `python -m whatsapp_desktop_mcp` and asserts every byte on stdout is JSON-RPC 2.0 after a full `initialize → notifications/initialized → tools/list → tools/call doctor` handshake), the doctor-registration introspection test (D-08 — exactly one tool with `readOnlyHint=True`), the frozen-exception-surface tests (D-12 — the import-by-name guard for Phase 1), the REL-05 structural isolation tests (CLAUDE.md §1 — vacuous now but gains teeth in Phase 1+), the 19-test permission-probe mocking suite using `pytest-subprocess` (every error-code branch in the AppleScript decision matrix exercised, with explicit P-PHASE0-02 and P-PHASE0-03 regression guards), and the `RUN_LIVE=1`-gated end-to-end smoke that lets the maintainer spot-check the live `doctor` against the real macOS environment before tagging a release.

## What was built

### File tree (delta from Plan 03)

```
tests/
├── conftest.py                                        # NEW — near-empty marker module
├── __init__.py                                        # unchanged (Plan 01)
├── unit/
│   ├── __init__.py                                    # unchanged (Plan 01)
│   ├── test_stdout_purity.py                          # NEW — SETUP-03 CI gate
│   ├── test_doctor_tool.py                            # NEW — D-08 introspection
│   ├── test_exceptions.py                             # NEW — D-12 frozen surface
│   ├── test_isolation.py                              # NEW — REL-05 structural guard
│   └── test_permissions/
│       ├── __init__.py                                # unchanged (Plan 01)
│       ├── test_osascript.py                          # NEW — locale-blind regex (4 tests)
│       ├── test_fda.py                                # NEW — os.stat decision matrix (5 tests)
│       ├── test_automation.py                         # NEW — D-09 PATCHED matrix (6 tests)
│       └── test_accessibility.py                      # NEW — System Events matrix (4 tests)
└── integration/
    ├── __init__.py                                    # unchanged (Plan 01)
    └── test_live_doctor.py                            # NEW — RUN_LIVE=1 smoke (1 test)
```

10 new files. Zero modifications to existing source — Plan 04 is a pure test-suite addition; the gate is "did Plans 02/03 ship correctly?" and the answer per these tests is yes.

### Test count by category

| Category | Test file(s) | Count | Wall-clock |
| -------- | ------------ | ----- | ---------- |
| stdout purity | `test_stdout_purity.py` | 1 | ~0.5s (subprocess spawn dominates) |
| doctor registration | `test_doctor_tool.py` | 1 | <0.01s |
| exception shape | `test_exceptions.py` | 3 | <0.01s |
| REL-05 isolation | `test_isolation.py` | 4 | <0.01s |
| osascript runner | `test_permissions/test_osascript.py` | 4 | <0.01s |
| FDA probe | `test_permissions/test_fda.py` | 5 | <0.01s |
| Automation probe | `test_permissions/test_automation.py` | 6 | <0.01s |
| Accessibility probe | `test_permissions/test_accessibility.py` | 4 | <0.01s |
| **Total `not live`** | — | **28** | **0.86s** |
| live (RUN_LIVE=1) | `tests/integration/test_live_doctor.py` | 1 | ~0.5s on user's Mac |

`uv run pytest -m "not live"` exits 0 in 0.86 s on the maintainer's M1 Mac (well under the 30 s budget the plan calls out for macos-14 CI).

### Regression scenarios each test catches

| Test | Catches |
| ---- | ------- |
| `test_stdout_is_pure_jsonrpc` (`test_stdout_purity.py`) | A future executor adding a `print()` (despite ruff `T201`); a third-party `DeprecationWarning` defaulting to stdout; a `logging.basicConfig()` regression onto the wrong stream; any third-party module under `whatsapp_desktop_mcp.tools` or `permissions.*` that prints on first invocation (not just on import) — caught only by spawning the server, not by importing it |
| `test_doctor_is_registered_as_readonly` | Adding a second tool to Phase 0 (would break D-08); dropping `readOnlyHint=True` annotation; renaming `doctor` to anything else (would break the README quickstart) |
| `test_permission_hierarchy_is_stable` | Re-parenting `FullDiskAccessRequired` to `Exception` directly (would break Phase 1's `try ... except PermissionRequired` blocks); accidentally inverting the inheritance chain |
| `test_subclass_buckets_and_urls` | Renaming `bucket = "fda"` to `bucket = "full_disk_access"`; replacing `Privacy_AllFiles` with the modern `com.apple.settings.Privacy.AllFiles` form (which docs say works but is less battle-tested per RESEARCH.md) |
| `test_carries_remediation_payload` | Removing `db_path` keyword from the constructor; switching `binary_path` from kwarg to positional (would break Phase 1's call sites) |
| `test_isolation_reader_does_not_import_sender` and `test_isolation_sender_does_not_import_reader` | A future Phase 1 executor convenience-importing `from whatsapp_desktop_mcp.sender import ...` inside a reader module (or vice versa in Phase 2) |
| `test_run_osascript_parses_french_stderr_error_code` | Replacing the locale-blind regex with `if 'Not authorized' in stderr` (the literal P-PHASE0-02 regression) — would mis-classify denied as granted on the user's fr_FR Mac |
| `test_automation_handler_not_found_is_granted` | Removing the `error_code == -1708 → granted` mapping in `automation.py` (the literal P-PHASE0-03 regression) — would mis-classify granted Automation as denied if probe shape ever drifts back to `tell ... to count` |
| `test_automation_app_not_running_is_granted` | Removing the `-600 → granted` mapping (procNotFound when WhatsApp is closed); would falsely report Automation denied whenever the user has WhatsApp quit |
| `test_fda_denied_on_eacces` / `test_fda_denied_on_eperm` | Tightening the EACCES-only branch (forgetting EPERM); reporting wrong system_settings_url for FDA-denied state |
| `test_accessibility_denied_minus_25211` | Removing the -25211 variant from the denied-set (Apple Communities reports show this even when Script Editor is in the Accessibility list) |

### Live invocation transcripts

`uv run pytest -m "not live"` (CI-equivalent, fresh checkout):

```
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.0.3, pluggy-1.6.0
configfile: pyproject.toml
testpaths: tests
plugins: subprocess-1.6.0, asyncio-1.3.0, anyio-4.13.0
asyncio: mode=Mode.AUTO, debug=False, ...
collected 29 items / 1 deselected / 28 selected

tests/unit/test_doctor_tool.py .                                         [  3%]
tests/unit/test_exceptions.py ...                                        [ 14%]
tests/unit/test_isolation.py ....                                        [ 28%]
tests/unit/test_permissions/test_accessibility.py ....                   [ 42%]
tests/unit/test_permissions/test_automation.py ......                    [ 64%]
tests/unit/test_permissions/test_fda.py .....                            [ 82%]
tests/unit/test_permissions/test_osascript.py ....                       [ 96%]
tests/unit/test_stdout_purity.py .                                       [100%]

======================= 28 passed, 1 deselected in 0.86s =======================
```

`uv run pytest -m live --collect-only` (Plan 05 release.yml documentation reference):

```
collected 1 item

<Dir whatsapp-desktop-mcp>
  <Package tests>
    <Package integration>
      <Module test_live_doctor.py>
        <Coroutine test_doctor_returns_well_formed_report_on_live_system>

================ 1/29 tests collected (28 deselected) in 0.25s =================
```

`RUN_LIVE=1 uv run pytest -m live tests/integration/test_live_doctor.py -v` (maintainer's Mac smoke):

```
collected 1 item

tests/integration/test_live_doctor.py::test_doctor_returns_well_formed_report_on_live_system PASSED [100%]

============================== 1 passed in 0.47s ===============================
```

The live smoke confirms the `doctor()` tool's three-bucket `DoctorReport` is well-formed against the real macOS environment (FDA / Automation / Accessibility on the user's Mac all currently report `granted` per Plan 03's baseline transcript, and the assertions verify only the report shape, not the state values, so the test stays green across grant changes).

## Verification results

Plan-level `<verification>` block (every step passes):

| Step | Command | Result |
| ---- | ------- | ------ |
| 1 | `uv run pytest -m "not live"` | 28 passed, 1 deselected in 0.86s on macos-14 (well under the 30s budget) |
| 2 | `uv run pytest -m "not live" tests/integration/` | 0 selected (1 deselected — the live test is correctly excluded by the marker) |
| 3 | `uv run pytest -m live --collect-only` | exactly 1 test collected (`test_doctor_returns_well_formed_report_on_live_system`) |
| 4 | P-PHASE0 pitfall regression coverage | P-PHASE0-01: `test_stdout_is_pure_jsonrpc` ✓; P-PHASE0-02: `test_run_osascript_parses_french_stderr_error_code` ✓; P-PHASE0-03: `test_automation_handler_not_found_is_granted` ✓; P-PHASE0-06: indirectly via `test_doctor_is_registered_as_readonly` (would `ImportError` if Plan 03's import order broke); P-PHASE0-07: confirmed by step 2 above (the `live` marker parses cleanly under `--strict-markers`) |
| 5 | `uv run ruff check tests/` | "All checks passed!" — no T201 (per-file-ignores grants tests an exception anyway), no I001 (auto-fixed during execution), no E501 (long-line guard for the test docstrings), no UP012 (unnecessary `encoding="utf-8"` in `.encode()`) |
| 6 | `uv run mypy` | "Success: no issues found in 31 source files" — strict mode passes against `src/` + `tests/` (Plan 01's pyproject.toml `files = ["src", "tests"]` covers both) |

Sampled task-level acceptance criteria (all passed):

- **Task 1 (top-level invariants):**
  - `uv run pytest tests/unit/test_stdout_purity.py tests/unit/test_doctor_tool.py tests/unit/test_exceptions.py tests/unit/test_isolation.py -v` → 9 passed in 0.91s ✓
  - `grep -E "json\.loads" tests/unit/test_stdout_purity.py` → matches ✓
  - `grep -E 'protocolVersion.*2025-06-18' tests/unit/test_stdout_purity.py` → matches ✓
  - `grep -E "len\(tools\) == 1" tests/unit/test_doctor_tool.py` → matches ✓
  - `grep -E "issubclass\(FullDiskAccessRequired" tests/unit/test_exceptions.py` → matches ✓
  - `grep -E "import whatsapp_desktop_mcp\.(reader|sender)" tests/unit/test_isolation.py` → matches (4 occurrences across the file) ✓
- **Task 2 (probe mocking):**
  - `uv run pytest tests/unit/test_permissions/` → 19 passed in 0.12s ✓
  - `test_automation_handler_not_found_is_granted` PASSED — P-PHASE0-03 regression guard explicit ✓
  - `test_run_osascript_parses_french_stderr_error_code` PASSED — P-PHASE0-02 regression guard explicit ✓
  - Every automation test registers `[/usr/bin/osascript, -e, 'id of application "WhatsApp"']` (the EXACT command shape `automation.py:_PROBE` would spawn — greppable against the source) ✓
  - Every state value in `PermissionState` × `PermissionBucket` Literal cross-product is exercised by ≥1 passing test ✓
- **Task 3 (live smoke):**
  - `uv run pytest -m "not live" tests/integration/test_live_doctor.py` → 1 deselected (live test skipped by marker, P-PHASE0-07 mitigation confirmed) ✓
  - `uv run pytest -m live --collect-only` → 1 test collected (`test_doctor_returns_well_formed_report_on_live_system`) ✓
  - `grep -E "@pytest\.mark\.live" tests/integration/test_live_doctor.py` → matches ✓
  - `grep -E "RUN_LIVE" tests/integration/test_live_doctor.py` → matches ✓
  - `RUN_LIVE=1 uv run pytest -m live ...` → 1 passed in 0.47s on the maintainer's Mac ✓

## Commits

| Task | Type | Hash      | Subject                                                                            |
| ---- | ---- | --------- | ---------------------------------------------------------------------------------- |
| 1    | test | `b771e0b` | test(00-04): add stdout-purity, doctor-registration, exceptions, REL-05 isolation tests + conftest |
| 2    | test | `3227311` | test(00-04): add permission probe mocking tests (osascript + FDA + Automation + Accessibility) |
| 3    | test | `90cc5b6` | test(00-04): add RUN_LIVE-gated end-to-end smoke for the live doctor tool          |

All three commits use the `(00-04)` Conventional Commits scope per the executor protocol; commit type is `test` (test-only changes, no source modification). No hooks present in this repo (verified via `git status` post-commit; nothing was bypassed).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug, minor] `test_stdout_purity.py` import-block ordering — ruff `I001` auto-fix**

- **Found during:** Task 1 verification (`uv run ruff check tests/unit/test_stdout_purity.py`).
- **Issue:** First draft had a blank line between the `from __future__ import annotations` line and the stdlib block; ruff's `I001` (import sort) wanted them merged into a single import group. Pure formatting — no behavioral impact.
- **Fix:** `uv run ruff check --fix` removed the offending blank line. The auto-fix did not change semantics.
- **Files modified:** `tests/unit/test_stdout_purity.py` (one blank line removed).
- **Commit:** Folded into Task 1's commit `b771e0b` (the fix landed before the first commit was made — caught by the verification step).
- **Why this is Rule 1, not a checkpoint:** Lint-rule auto-fix with zero behavioral impact; the test executes identically.

**2. [Rule 1 - Bug, minor] `test_isolation.py` mypy strict — `import importlib` → `import importlib.util`**

- **Found during:** Task 1 verification (`uv run mypy`).
- **Issue:** First draft used `importlib.util.find_spec(...)` after a top-level `import importlib`. mypy `--strict` rejects this with `Module has no attribute "util"  [attr-defined]` because `importlib.util` is a sub-module that must be explicitly imported (it is not auto-loaded by `import importlib`). Behavior happened to work at runtime because `pytest_subprocess` or another dep transitively imports `importlib.util`, but that's incidental.
- **Fix:** Changed `import importlib` → `import importlib.util`. Behavior unchanged; mypy now happy.
- **Files modified:** `tests/unit/test_isolation.py` (one import statement).
- **Commit:** Folded into Task 1's commit `b771e0b`.
- **Why this is Rule 1, not a checkpoint:** Type-checker correctness fix with zero behavioral impact; the test executes identically.

**3. [Rule 1 - Bug, minor] `test_permissions/test_*.py` ruff fixes — long lines + redundant `encoding="utf-8"`**

- **Found during:** Task 2 verification (`uv run ruff check tests/unit/test_permissions/`).
- **Issue:** Three lint errors surfaced — (a) `E501` line-too-long in `test_accessibility.py` (a 105-char docstring line) and `test_fda.py` (a 107-char then 102-char docstring line in the module-level docstring); (b) `UP012` redundant `encoding="utf-8"` argument to `.encode()` in `test_osascript.py` (Python 3 default is UTF-8). All formatting-only.
- **Fix:** Reworded the long docstring lines to fit within 100 chars; removed the explicit `encoding="utf-8"` argument from `.encode()`. Behavior unchanged; the French-stderr fixture still uses UTF-8 byte representation correctly.
- **Files modified:** `tests/unit/test_permissions/test_accessibility.py` (one line), `tests/unit/test_permissions/test_fda.py` (two lines), `tests/unit/test_permissions/test_osascript.py` (one line + restructured `fp.register` call to put the multi-line stderr literal in a cleaner shape).
- **Commit:** Folded into Task 2's commit `3227311`.
- **Why this is Rule 1, not a checkpoint:** Lint-rule auto-fixes with zero behavioral impact; the tests execute identically and assert identically.

**4. [Rule 1 - Bug, minor] `test_permissions/test_fda.py` mypy strict — `monkeypatch.setattr(fda.os, ...)` → string-path form**

- **Found during:** Task 2 verification (`uv run mypy`).
- **Issue:** First draft used `monkeypatch.setattr(fda.os, "stat", _raise_*)` to patch the `os.stat` symbol *as imported into* `permissions/fda.py`. mypy `--strict` rejects this with `Module "whatsapp_desktop_mcp.permissions.fda" does not explicitly export attribute "os"  [attr-defined]` — because `fda.py` imports `os` for its own use but never re-exports it via `__all__`, mypy refuses to let an external module access `fda.os` even though Python itself permits the attribute access via the module's namespace dict.
- **Fix:** Switched to the string-path monkeypatch form: `monkeypatch.setattr("whatsapp_desktop_mcp.permissions.fda.os.stat", _raise_*)`. Same production code path is exercised (the `os.stat` call inside `_check_blocking` resolves to the patched callable); mypy is sidestepped because the string is opaque to the type checker.
- **Files modified:** `tests/unit/test_permissions/test_fda.py` (three monkeypatch call sites).
- **Commit:** Folded into Task 2's commit `3227311`.
- **Why this is Rule 1, not a checkpoint:** Type-checker correctness fix with zero behavioral impact; the production code path under test (`fda._check_blocking → os.stat`) is exercised identically before and after.

### Skipped or postponed work

- **Plan 05 work (CI workflows, README, claude_desktop_config.json snippet, ToS warning):** Not in scope. Plan 04 ships the test suite that Plan 05's `ci.yml` will invoke as `uv run pytest -m "not live"`.
- **Plan 03 source touch-ups:** Not in scope. The plan boundary is "test what was shipped"; if a test had revealed an actual bug in Plan 02/03 source, the deviation rules require STOP + checkpoint, not silent fix. None did.
- **Coverage reporting / coverage-py integration:** D-15 explicitly says "Coverage threshold not enforced in Phase 0 (too early)"; we exercise every state Literal × bucket Literal cross-product but do not measure line coverage. Phase 1 may add `pytest-cov`.
- **Async-timeout edge tests for `run_osascript`:** The osascript tests cover the regex extraction surface but not the `asyncio.wait_for(timeout=0.5)` kill-and-cleanup path (which Plan 03's manual verification already exercised on the maintainer's Mac). A wall-clock test would add ~0.5s to the suite for a code path that is structurally trivial — deferred to Phase 1 if a regression ever arises.

## Authentication / human action gates

None encountered. The only test that touches the live macOS environment is `test_live_doctor.py`, which is `@pytest.mark.live`-gated and the maintainer ran manually on their Mac to confirm the suite is sound (1 passed in 0.47s, three buckets all `granted` per Plan 03's baseline). Auth gates would only surface if a probe returned `denied` AND the test asserted state values (which it doesn't — see "live integration test shipped with belt-and-braces gating" decision above).

## Threat surface scan

Plan 04 ships test code only — no new endpoints, no new auth paths, no new schema changes at trust boundaries. The threat-model items the plan **mitigates** (per the plan's `<threat_model>` section) are all addressed structurally:

| Threat ID | Mitigation status |
| --------- | ----------------- |
| **T-00-12** (Tampering — overly broad exception catch hides a protocol-violation bug) | Mitigated — the stdout-purity test uses `pytest.fail(f"stdout line is not valid JSON: {text!r} ({e})")` with the offending raw line; the failure surfaces the exact byte sequence and the source location of the parse error. Ruff's `B` rule set is on (PLAN 00-01 / pyproject.toml) so a bare `except:` would lint-fail. |
| **T-00-13** (Tampering — pytest-subprocess fixture mismatch silently bypasses production code) | Mitigated — every probe-mocking test registers the EXACT `[cmd, arg1, ...]` argv that production spawns; the registered command strings are greppable against the source (`grep -F 'id of application "WhatsApp"' tests/unit/test_permissions/test_automation.py` matches; `grep -F 'tell application "System Events" to count processes' tests/unit/test_permissions/test_accessibility.py` matches). A drift would surface as a pytest-subprocess "no matching invocation registered" failure, NOT a silent passthrough. |
| **T-00-14** (Information disclosure — live test logs leak permission state via CI logs) | Accepted — live tests are `RUN_LIVE=1`-gated and not run in public CI; even if leaked, the only info is "this Mac has FDA granted to this Python path", which is the same info `doctor` would return to any caller. |

No new security-relevant surface introduced. No threat flags to add — Plan 04 is pure-test infrastructure.

## TDD Gate Compliance

N/A — PLAN.md frontmatter declares `type: execute` (not `type: tdd`); no task carries `tdd="true"`. Plan 04 is the test-suite plan that lands AFTER Plans 02-03 shipped the source, by deliberate design (CONTEXT.md's "verify the cement set, then verify the engine runs" partitioning — Phase 0 lands the executable scaffolding via Plans 01-03 and the test scaffolding via Plan 04, in that order).

## Known Stubs

None. Every test exercises live code paths against either real source (`test_doctor_tool.py`, `test_exceptions.py`, `test_stdout_purity.py`) or pytest-subprocess-mocked osascript invocations whose argv strings are greppable against the production source. The vacuous-now / teeth-later behavior of `test_isolation.py` is intentional and documented in the test docstring — it is a *forward-looking* structural guard, not a stub.

## Self-Check

Verified each commit and key file before declaring done:

```
git log --oneline -4
90cc5b6 test(00-04): add RUN_LIVE-gated end-to-end smoke for the live doctor tool   ✓ FOUND
3227311 test(00-04): add permission probe mocking tests (osascript + FDA + Automation + Accessibility)   ✓ FOUND
b771e0b test(00-04): add stdout-purity, doctor-registration, exceptions, REL-05 isolation tests + conftest   ✓ FOUND
08b1ecf docs(00-03): complete permission probes + doctor tool plan ...   ✓ FOUND (Plan 03 final)
```

```
tests/conftest.py                                      ✓ FOUND
tests/unit/test_stdout_purity.py                       ✓ FOUND
tests/unit/test_doctor_tool.py                         ✓ FOUND
tests/unit/test_exceptions.py                          ✓ FOUND
tests/unit/test_isolation.py                           ✓ FOUND
tests/unit/test_permissions/test_osascript.py          ✓ FOUND
tests/unit/test_permissions/test_fda.py                ✓ FOUND
tests/unit/test_permissions/test_automation.py         ✓ FOUND
tests/unit/test_permissions/test_accessibility.py      ✓ FOUND
tests/integration/test_live_doctor.py                  ✓ FOUND
```

Behavioral spot-checks (all on maintainer's Mac, 2026-05-13):

- `uv run pytest -m "not live"` → 28 passed, 1 deselected in 0.86s ✓
- `uv run pytest -m live --collect-only` → 1 test collected ✓
- `RUN_LIVE=1 uv run pytest -m live tests/integration/test_live_doctor.py -v` → 1 passed ✓
- `uv run ruff check tests/` → "All checks passed!" ✓
- `uv run mypy` → "Success: no issues found in 31 source files" ✓
- `grep -E "@pytest\.mark\.live" tests/integration/test_live_doctor.py` → 2 matches (decorator + docstring mention) ✓
- `grep -E "id of application" tests/unit/test_permissions/test_automation.py` → 8 matches (one per fp.register + comment mention) — proves test argv matches `automation.py:_PROBE` literal ✓
- `git log --oneline | head -3` → all three task commits present with `(00-04)` scope ✓

## Self-Check: PASSED

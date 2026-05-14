---
phase: 00-setup-and-permissions-skeleton
plan: 2
subsystem: server-cli-contracts
tags: [fastmcp, stdio, cli, pydantic, exceptions, paths]
dependency_graph:
  requires:
    - "Plan 01: src-layout package, pyproject.toml with mcp[cli]==1.27.1, uv.lock, console-script entry reservation"
  provides:
    - "FastMCP stdio server module (`whatsapp_desktop_mcp.server.mcp` + `run()`) with zero registered tools, stderr-first logging"
    - "argparse CLI dispatcher (`whatsapp_desktop_mcp.cli:main`) — `--version` / `--help` exit before FastMCP loads (lazy server import)"
    - "`python -m whatsapp_desktop_mcp` shim (`whatsapp_desktop_mcp.__main__`) — identical behavior to console script"
    - "Frozen public exception hierarchy: `WhatsAppMCPError` → `PermissionRequired` → {`FullDiskAccessRequired`, `AutomationPermissionRequired`, `AccessibilityPermissionRequired`} with bucket + system_settings_url class attributes"
    - "Frozen Pydantic v2 contracts: `PermissionStatus`, `DoctorReport`, `PermissionState` / `PermissionBucket` Literal aliases"
    - "Pure path resolver: `whatsapp_desktop_mcp.paths.resolve_chatstorage_path() -> str`"
    - "Single insertion-site comment in `server.py` line 44 marking the exact line Plan 03 will append (`from whatsapp_desktop_mcp.tools import doctor as _doctor`)"
  affects:
    - "Plan 03 (doctor probes + tool registration) — binds against every interface above; the Plan 03 executor only edits `server.py` line 44 + adds `tools/doctor.py` + adds `permissions/{fda,automation,accessibility,osascript}.py`"
    - "Plan 04 (test suite) — `tests/unit/test_stdout_purity.py` will spawn `python -m whatsapp_desktop_mcp` (the shim shipped here); `tests/unit/test_exceptions.py` will introspect the frozen exception surface"
    - "Phase 1 readers/senders — will `from whatsapp_desktop_mcp.exceptions import FullDiskAccessRequired` etc. against an immutable surface; `paths.resolve_chatstorage_path` is the single source of truth for the DB path string"
tech_stack:
  added:
    - "argparse (stdlib) — CLI dispatcher"
    - "logging (stdlib) — stderr-only handler installed at module-import time"
    - "mcp.server.fastmcp.FastMCP (mcp[cli]==1.27.1) — protocol scaffolding"
    - "pydantic.BaseModel (>=2.7,<3) — DoctorReport / PermissionStatus contracts"
  patterns:
    - "Stderr-FIRST logging: `logging.basicConfig(stream=sys.stderr, ...)` is the first executable statement in `server.py`, BEFORE `from mcp.server.fastmcp import FastMCP` (D-05; P-PHASE0-01 mitigation; protects the JSON-RPC stdout channel)"
    - "Lazy server import inside `cli.main()`: `from whatsapp_desktop_mcp.server import run` is deferred until after argparse parses, so `--version` and `--help` exit before FastMCP loads"
    - "Frozen-public-surface pattern: exception class names + `bucket` literal values + `system_settings_url` strings are an immutable downstream contract (CONTEXT.md D-12)"
    - "Pydantic Literal over Enum (CONTEXT.md D-03): `Literal[\"granted\", \"denied\", \"whatsapp_not_installed\"]` flows through FastMCP's JSON-schema introspection cleanly"
    - "Computed `@property` (not field) for `DoctorReport.all_granted` — keeps `model_fields` clean, derives from constituent statuses"
    - "Module-scope `mcp = FastMCP(...)` BEFORE the (future) tools-import line — P-PHASE0-06 circular-import safety net"
    - "No `transport=` argument on `mcp.run()` — D-04; passing one would risk introducing the HTTP/SSE anti-feature CLAUDE.md hard rule #5 forbids"
key_files:
  created:
    - src/whatsapp_desktop_mcp/server.py
    - src/whatsapp_desktop_mcp/cli.py
    - src/whatsapp_desktop_mcp/__main__.py
    - src/whatsapp_desktop_mcp/exceptions.py
    - src/whatsapp_desktop_mcp/paths.py
    - src/whatsapp_desktop_mcp/models/doctor.py
    - .planning/phases/00-setup-and-permissions-skeleton/00-02-SUMMARY.md
  modified: []
decisions:
  - "Plan 03 insertion-site comment is anchored at `src/whatsapp_desktop_mcp/server.py:44` — Plan 03's executor edits exactly that line, replacing the comment with `from whatsapp_desktop_mcp.tools import doctor as _doctor  # noqa: E402, F401`"
  - "Path resolver lives at `whatsapp_desktop_mcp/paths.py` (top-level, not inside `permissions/`) so Phase 1's read tools can import it without crossing into the `permissions/` namespace"
  - "Server module docstring rewritten to describe the `transport=` prohibition without using the literal `transport=` token, so the plan's `! grep -E '\\btransport\\s*=' src/whatsapp_desktop_mcp/server.py` acceptance criterion passes (was a near-miss the first verification surfaced)"
  - "`__init__.py` left at exactly `__version__ = \"0.1.0\"` (Plan 01 shipped this; Plan 02 explicitly re-uses, no `__all__` added — keeps the package root import-cheap so `import whatsapp_desktop_mcp` produces zero stdout bytes, which is the package-level P-PHASE0-01 invariant Phase 1 will rely on)"
metrics:
  duration_seconds: 180
  completed_date: "2026-05-13"
  task_count: 3
  file_count: 6
  commits: 3
---

# Phase 0 Plan 02: FastMCP stdio server, CLI entry point, exception hierarchy, Pydantic models — Summary

## One-liner

Landed the executable spine — FastMCP stdio server (zero tools, stderr-FIRST logging, no `transport=` argument), argparse CLI with lazy server import, `python -m whatsapp_desktop_mcp` shim, the frozen 5-class `WhatsAppMCPError`/`PermissionRequired`/`*Required` exception hierarchy, the Pydantic v2 `DoctorReport`/`PermissionStatus` contracts (Literal-typed enums, `all_granted` as a `@property` not a field), and the pure `resolve_chatstorage_path()` resolver — so `uv run whatsapp-desktop-mcp --version` works end-to-end and Plan 03 can register `doctor` against an immutable contract surface by appending a single line at `server.py:44`.

## What was built

### File tree (delta from Plan 01)

```
src/whatsapp_desktop_mcp/
├── __init__.py                # unchanged: __version__ = "0.1.0"
├── __main__.py                # NEW — python -m shim, delegates to cli.main
├── cli.py                     # NEW — argparse dispatcher; lazy `from whatsapp_desktop_mcp.server import run`
├── server.py                  # NEW — FastMCP("whatsapp-desktop-mcp"); logging.basicConfig stderr FIRST
├── exceptions.py              # NEW — WhatsAppMCPError → PermissionRequired → 3 subclasses
├── paths.py                   # NEW — resolve_chatstorage_path() pure resolver
├── models/
│   ├── __init__.py            # unchanged (empty from Plan 01)
│   └── doctor.py              # NEW — PermissionStatus, DoctorReport, Literal aliases
├── permissions/__init__.py    # unchanged (empty; Plan 03 fills)
├── tools/__init__.py          # unchanged (empty; Plan 03 fills)
├── reader/__init__.py         # unchanged (empty; REL-05 sibling)
└── sender/__init__.py         # unchanged (empty; REL-05 sibling)
```

6 new files. Zero modifications to existing files (Plan 01's `__init__.py` is left untouched per Task 3 read_first instruction).

### Frozen public surface (downstream contracts)

The class names, attribute literals, URL strings, and function signatures below are **immutable from this point onward** — Plan 03 binds against them; Phase 1 binds against them.

**`whatsapp_desktop_mcp.exceptions`:**

| Class                            | Base                  | `bucket` (literal)      | `system_settings_url`                                                              |
| -------------------------------- | --------------------- | ----------------------- | ---------------------------------------------------------------------------------- |
| `WhatsAppMCPError`               | `Exception`           | n/a                     | n/a                                                                                |
| `PermissionRequired`             | `WhatsAppMCPError`    | `"unknown"` (overridden) | `""` (overridden)                                                                  |
| `FullDiskAccessRequired`         | `PermissionRequired`  | `"fda"`                 | `x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles`         |
| `AutomationPermissionRequired`   | `PermissionRequired`  | `"automation"`          | `x-apple.systempreferences:com.apple.preference.security?Privacy_Automation`       |
| `AccessibilityPermissionRequired`| `PermissionRequired`  | `"accessibility"`       | `x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility`    |

`PermissionRequired.__init__(message, *, binary_path, db_path=None, remediation="")` — the keyword-only constructor signature is part of the frozen surface; Phase 1's tools will call it as `raise FullDiskAccessRequired("...", binary_path=sys.executable, db_path=resolve_chatstorage_path(), remediation="...")`.

**`whatsapp_desktop_mcp.models.doctor`:**

```python
PermissionState  = Literal["granted", "denied", "whatsapp_not_installed"]
PermissionBucket = Literal["fda", "automation", "accessibility"]

class PermissionStatus(BaseModel):
    bucket: PermissionBucket
    state: PermissionState
    binary_path: str
    db_path: str | None = None
    system_settings_url: str
    remediation: str = ""

class DoctorReport(BaseModel):
    full_disk_access: PermissionStatus
    automation_whatsapp: PermissionStatus
    accessibility: PermissionStatus
    @property
    def all_granted(self) -> bool: ...   # NOT a Pydantic field
```

`DoctorReport.model_fields` contains exactly `{"full_disk_access", "automation_whatsapp", "accessibility"}` — `all_granted` is a Python `@property` and therefore does not appear in serialized output (verified during Task 1 acceptance).

**`whatsapp_desktop_mcp.paths`:**

```python
def resolve_chatstorage_path() -> str: ...
# returns: /Users/<user>/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite
```

Pure resolver — no I/O, no syscalls. Phase 1 will extend it with auto-detection across user homes without renaming the function.

**`whatsapp_desktop_mcp.server`:**

```python
mcp: FastMCP = FastMCP("whatsapp-desktop-mcp")
def run() -> None: ...   # mcp.run()  — stdio default; no transport keyword
```

`from mcp.server.fastmcp import FastMCP` is the canonical import path (the `mcp[cli]==1.27.1` distribution); `from fastmcp import FastMCP` (jlowin's standalone) is forbidden and not in the dependency set.

**`whatsapp_desktop_mcp.cli`:**

```python
def main(argv: list[str] | None = None) -> int: ...
```

`from whatsapp_desktop_mcp.server import run` is **lazy** (inside `main`) so `--version` / `--help` exit before FastMCP imports.

### Plan 03 insertion site (the single line Plan 03 appends)

`src/whatsapp_desktop_mcp/server.py:44` currently reads:

```python
# Phase 0 Plan 03 inserts: from whatsapp_desktop_mcp.tools import doctor as _doctor  # noqa: E402, F401
```

Plan 03's executor edits exactly this line, replacing the `# Phase 0 Plan 03 inserts: ` prefix with the actual import. The line is positioned AFTER `mcp = FastMCP(...)` (line 42) and BEFORE `def run()` (line 47), which is the P-PHASE0-06 ordering required to avoid a circular import (`tools/doctor.py` does `from whatsapp_desktop_mcp.server import mcp`).

## Verification results

All plan-level `<verification>` steps pass:

| Step | Command                                                                                                                        | Result                                                                                                              |
| ---- | ------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| 1    | `uv run whatsapp-desktop-mcp --version`                                                                                                | `whatsapp-desktop-mcp 0.1.0` (matches `^whatsapp-desktop-mcp 0\.1\.0$`); exit 0                                                     |
| 2    | `uv run python -m whatsapp_desktop_mcp --version`                                                                                      | `whatsapp-desktop-mcp 0.1.0`; exit 0 (identical to step 1 — confirms `__main__.py` shim)                                    |
| 3    | `uv run ruff check src tests`                                                                                                  | "All checks passed!" — T201 (no `print`) clean; E/F/I/B/UP/TID clean                                                |
| 4    | `uv run mypy`                                                                                                                  | "Success: no issues found in 16 source files" — strict mode passes against all of `src/` + `tests/`                 |
| 5    | `python -c "from whatsapp_desktop_mcp.exceptions import FullDiskAccessRequired, ...; from whatsapp_desktop_mcp.models.doctor import ...; from whatsapp_desktop_mcp.paths import resolve_chatstorage_path; from whatsapp_desktop_mcp.server import mcp, run"` | Exits 0 — every interface published in `<context>` is importable                                                    |
| 6    | `python -c "from whatsapp_desktop_mcp.server import mcp" 2>/dev/null \| wc -c`                                                         | `0` — server import emits zero bytes on stdout (P-PHASE0-01 invariant evidence)                                     |

Additional task-level acceptance criteria (sampled — all passed):

- `! grep -E '^from fastmcp ' src/whatsapp_desktop_mcp/server.py` → no match (correct distribution import)
- `! grep -E '\btransport\s*=' src/whatsapp_desktop_mcp/server.py` → no match (no executable nor docstring `transport=` occurrence; the docstring was rewritten to avoid the literal token after the first verification surfaced the near-miss)
- `from whatsapp_desktop_mcp.cli import main; inspect.signature(main)` → `(argv: 'list[str] | None' = None) -> 'int'`
- `python -c "import whatsapp_desktop_mcp" 2>/dev/null | wc -c` → `0` (package root is import-cheap and stdout-clean)
- Executable `logging.basicConfig(` is at `server.py:34`; executable `from mcp.server.fastmcp import FastMCP` is at `server.py:40` (40 > 34 → ordering invariant satisfied)
- `PermissionStatus(bucket="bogus", ...)` raises `pydantic.ValidationError` (Literal enforcement working)
- `DoctorReport.model_fields` does NOT contain `"all_granted"` (computed property, not field)
- `resolve_chatstorage_path()` returns `/Users/jlqueguiner/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite` (no leading `~`, correct suffix)

## Commits

| Task | Type | Hash      | Subject                                                                            |
| ---- | ---- | --------- | ---------------------------------------------------------------------------------- |
| 1    | feat | `3b4729c` | feat(00-02): add frozen exception hierarchy, Pydantic models, and path resolver    |
| 2    | feat | `04d0a94` | feat(00-02): add FastMCP stdio server entry with stderr-FIRST logging              |
| 3    | feat | `e446e3d` | feat(00-02): add CLI entry point and python -m whatsapp_desktop_mcp shim                   |

All commits use the `(00-02)` Conventional Commits scope. No hooks present in this repo (verified via `git status` post-commit; nothing was bypassed).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug, minor] Server module docstring re-worded to omit the literal `transport=` token**

- **Found during:** Task 2 verification.
- **Issue:** The first draft of `server.py` mentioned `transport='stdio'` and "passing any `transport=` argument" inside the module docstring as explanatory prose. The plan's `<verify>` step uses `! grep -E '\btransport\s*=' src/whatsapp_desktop_mcp/server.py` (a strict file-wide grep that does NOT distinguish docstring from executable code), so even the docstring mention failed the gate. The acceptance criterion's plain English ("It does NOT pass any `transport=` argument to `mcp.run()`") is about executable behavior, but the gate is a strict grep — the gate is the authoritative source of truth.
- **Fix:** Re-wrote the docstring to say "explicit transport keyword" (no `transport=` literal). Behavior unchanged; only docstring prose differs.
- **Files modified:** `src/whatsapp_desktop_mcp/server.py` (docstring lines only; no executable changes).
- **Commit:** Folded into Task 2's commit `04d0a94` (the fix landed before the first commit was made — the iteration was caught by the verification check before the commit was finalized).
- **Why this is Rule 1, not a checkpoint:** The fix is a docstring rewording with zero behavioral impact; the architectural rule (no `transport=` argument anywhere in the call site) is fully preserved. No new decisions required.

### Skipped or postponed work

- **Plan 03 work (`doctor` probes + tool registration):** Not in scope. Plan 02 leaves the explicit `# Phase 0 Plan 03 inserts: ...` insertion-site comment at `server.py:44` so the Plan 03 executor knows the single line to edit.
- **Plan 04 work (`tests/unit/test_stdout_purity.py`, doctor-tool registration test, exception-shape test):** Not in scope. The interfaces those tests will introspect are all frozen and ready.
- **`examples/claude_desktop_config.json`:** Not in scope (Plan 05 / SETUP-01).
- **`reader/`, `sender/`, `permissions/`, `tools/` content:** Stays empty by design (REL-05 enforced structurally; Plan 03 fills `permissions/` and `tools/`; Phase 1 fills `reader/`; Phase 2 fills `sender/`).

## Authentication / human action gates

None encountered. Phase 0 Plan 02 is purely local file creation + tool runs; no TCC permissions probed yet (Plan 03 ships the probes), no network access, no credentials.

## Threat surface scan

This plan ships glue and contracts only — no new endpoints, no new auth paths, no schema changes at trust boundaries. The threat model items the plan **mitigates** (per the plan's `<threat_model>` section) are all addressed structurally:

| Threat ID | Mitigation status |
| --------- | ----------------- |
| **T-00-04** (stray stdout corrupts JSON-RPC) | Mitigated — `logging.basicConfig(stream=sys.stderr, ...)` is the first executable statement in `server.py`; `import whatsapp_desktop_mcp` and `from whatsapp_desktop_mcp.server import mcp` both produce zero stdout bytes (verified during plan-level verification step 6). The CI-side gate (`tests/unit/test_stdout_purity.py`) lands in Plan 04. |
| **T-00-05** (wrong FastMCP import / lower-level Server class) | Mitigated — `from mcp.server.fastmcp import FastMCP` is the only import path used; `! grep -E '^from fastmcp '` and `! grep -E '\btransport\s*='` both pass on `server.py`. |
| **T-00-06** (HTTP listener introduced) | Mitigated — `mcp.run()` is the only call site; no `transport=` argument anywhere in the file (docstring or executable). |
| **T-00-07** (CLI traceback to stdout corrupts JSON-RPC) | Mitigated — argparse writes to stderr by default; `--version` exits via `argparse → SystemExit` BEFORE the lazy `from whatsapp_desktop_mcp.server import run` even fires; uncaught exceptions in `main()` propagate to Python's runtime which writes to stderr. |

No new security-relevant surface introduced. No threat flags to add.

## TDD Gate Compliance

N/A — PLAN.md frontmatter declares `type: execute` (not `type: tdd`); no task carries `tdd="true"`. Phase 0's TDD-style stdout-purity test (per D-16) lands in Plan 04, which targets the server shipped here.

## Known Stubs

- **Insertion-site comment in `server.py:44`** is intentional, not a stub. It documents (in code) the single-line edit Plan 03 will make. Plan 03's executor replaces the comment with the actual `from whatsapp_desktop_mcp.tools import doctor as _doctor  # noqa: E402, F401` import. The `tools/list` response of the Plan 02 server is `[]` (empty array) — also intentional; Plan 04's stdout-purity test must accommodate this, and its plan already does.
- `paths.resolve_chatstorage_path()` returns the user's home directory expansion only (no auto-detection across multiple home directories). Phase 1 will extend the implementation; the function name and `str` return type are the frozen contract.

Neither item is a "stub that prevents the plan's goal" — both are explicit Phase 0 / Phase 1 partition points with named successor plans.

## Self-Check

Verified each commit and key file before declaring done:

```
git log --oneline -3
e446e3d feat(00-02): add CLI entry point and python -m whatsapp_desktop_mcp shim   ✓ FOUND
04d0a94 feat(00-02): add FastMCP stdio server entry with stderr-FIRST logging   ✓ FOUND
3b4729c feat(00-02): add frozen exception hierarchy, Pydantic models, and path resolver   ✓ FOUND
```

```
src/whatsapp_desktop_mcp/exceptions.py     ✓ FOUND
src/whatsapp_desktop_mcp/models/doctor.py  ✓ FOUND
src/whatsapp_desktop_mcp/paths.py          ✓ FOUND
src/whatsapp_desktop_mcp/server.py         ✓ FOUND
src/whatsapp_desktop_mcp/cli.py            ✓ FOUND
src/whatsapp_desktop_mcp/__main__.py       ✓ FOUND
```

Behavioral spot-checks:

- `uv run whatsapp-desktop-mcp --version` → `whatsapp-desktop-mcp 0.1.0` ✓
- `uv run python -m whatsapp_desktop_mcp --version` → `whatsapp-desktop-mcp 0.1.0` ✓
- `uv run ruff check src tests` → All checks passed ✓
- `uv run mypy` → 16 source files clean ✓
- `python -c "import whatsapp_desktop_mcp" 2>/dev/null | wc -c` → 0 ✓
- `python -c "from whatsapp_desktop_mcp.server import mcp" 2>/dev/null | wc -c` → 0 ✓

## Self-Check: PASSED

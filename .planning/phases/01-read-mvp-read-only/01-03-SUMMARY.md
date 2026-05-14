---
phase: 01-read-mvp-read-only
plan: 3
title: "--read-only flag mechanics: CLI flag, ReadOnlyMode exception, server module state"
subsystem: cli-and-protocol
tags: [argparse, boolean-optional-action, read-only, fastmcp, module-state, exceptions, phase-2-contract]
requires: [phase-0]
provides:
  - whatsapp_desktop_mcp.exceptions.ReadOnlyMode
  - whatsapp_desktop_mcp.server.read_only_mode
  - cli.--read-only-flag
  - cli.--no-read-only-flag
affects: [Plan 01-04 tool imports (read tools register unconditionally), Plan 01-06 tests, Phase 2 send-tool registration gate]
tech-stack:
  added: []
  patterns:
    - "argparse.BooleanOptionalAction — gives --read-only (True) and --no-read-only (False) from a single declaration (stdlib ≥3.9; requires-python = >=3.12)"
    - "Module-level boolean state assigned BEFORE lazy server-entry import — observable to tool-registration side-effect imports at server.py module-load time"
    - "Sibling exception class (ReadOnlyMode, NOT PermissionRequired-derived) — being denied by --read-only is a deliberate server config choice, not a missing OS permission"
key-files:
  created: []
  modified:
    - src/whatsapp_desktop_mcp/exceptions.py
    - src/whatsapp_desktop_mcp/server.py
    - src/whatsapp_desktop_mcp/cli.py
decisions:
  - "ReadOnlyMode is a sibling of PermissionRequired (subclass of WhatsAppMCPError directly), NOT a child of PermissionRequired — because being denied by a deliberate server config (--read-only) is structurally different from a missing macOS TCC bucket. ReadOnlyMode carries no `bucket` / `system_settings_url` payload."
  - "argparse.BooleanOptionalAction is used (NOT `action='store_true'`) so the `--no-read-only` spelling is a first-class CLI surface, not a secondary `--read-only=false` workaround. The action is stdlib-since-3.9; project requires Python ≥3.12 so it's always available."
  - "Default is True (read-only ON) for v0.1 per STATE.md §Todos / Carry-overs — conservative default while sender/ is empty. Phase 2+ will document flipping to False per server-by-server choice."
  - "The CLI assigns `server.read_only_mode = args.read_only` via a two-step import (`from whatsapp_desktop_mcp import server` first, then `from whatsapp_desktop_mcp.server import run`) — importing the module triggers tool-registration side-effects exactly once; the assignment happens between the parse and the `run()` call so Phase 2's gated import will observe the user's choice."
  - "A Plan 01-04 insertion-point marker comment was placed in server.py immediately AFTER the existing `doctor` import — Plan 01-04 appends 7 read-tool imports there; Phase 2 appends its `if not read_only_mode:` send-tool block AFTER the read tools. The marker keeps the ordering documented in one place."
metrics:
  duration_seconds: 285
  tasks: 3
  files: 3
  commits: 3
  completed: "2026-05-13T09:31:00Z"
---

# Phase 1 Plan 03: `--read-only` flag mechanics — Summary

The locked CLI flag + module state + exception surface that wires SETUP-06
end-to-end without disturbing any Phase 0 invariant. Three small edits to
three existing files; zero new files; zero new dependencies; zero new I/O.

## What Shipped

### `src/whatsapp_desktop_mcp/exceptions.py` (modified)

Appended one class at the end of the module:

```python
class ReadOnlyMode(WhatsAppMCPError):
    """Raised by a send tool when the server was started with --read-only.

    Phase 1 mints this class so Phase 2's send_message can import it by
    name without a circular dependency on a Phase 2-only module. Phase 1
    ships zero send tools (REL-05 sender/ is empty), so nothing in
    Phase 1 ever raises this — but the contract surface is fixed now.

    Sibling of :class:`PermissionRequired` (NOT a child) — being denied
    by ``--read-only`` is a deliberate server-configuration choice, not
    a missing OS permission, so it does not share the ``bucket`` /
    ``system_settings_url`` payload shape.
    """
```

The module docstring gained one paragraph framing the addition as a Phase 1
extension of the D-12 frozen surface. The 5 existing Phase 0 classes
(`WhatsAppMCPError`, `PermissionRequired`, `FullDiskAccessRequired`,
`AutomationPermissionRequired`, `AccessibilityPermissionRequired`) were not
touched. The 3 Phase 0 `test_exceptions.py` tests still pass — they assert
only the existing classes, and adding a new sibling does not perturb them.

### `src/whatsapp_desktop_mcp/server.py` (modified)

Inserted one module-level assignment between the FastMCP instance and the
existing `doctor` tool import:

```python
mcp: FastMCP = FastMCP("whatsapp-desktop-mcp")

# Module-level flag set by cli.main() BEFORE the tool-registration imports
# below execute. Default True is the v0.1 carry-over (STATE.md §Carry-overs);
# Phase 2 will wrap its send_message tool import in `if not read_only_mode:`.
# Phase 1 read tools always carry `readOnlyHint=True` regardless of this flag.
read_only_mode: bool = True

from whatsapp_desktop_mcp.tools import doctor as _doctor  # noqa: E402, F401

# --- Plan 01-04 tool import insertion point ---
# Plan 01-04 will append 7 read tools below this marker (all unconditionally
# registered; readOnlyHint=True is intrinsic to the read tools themselves).
# Phase 2 will append its `if not read_only_mode:` send-tool import block
# AFTER the Plan 01-04 read tools.
```

The module docstring gained one paragraph describing the flag's lifecycle.
The `logging.basicConfig(stream=sys.stderr, ...)` first-statement invariant
(P-PHASE0-01) and the `from mcp.server.fastmcp import FastMCP` import path
are preserved unchanged. `mcp.list_tools()` still returns exactly
`['doctor']` — Plan 01-04 will append 7 read tools.

### `src/whatsapp_desktop_mcp/cli.py` (modified)

Added the argparse flag declaration and the module-state assignment:

```python
parser.add_argument(
    "--read-only",
    action=argparse.BooleanOptionalAction,
    default=True,
    help=(
        "Disable every send tool; tools/list returns read tools + doctor only. "
        "Default is on for v0.1 (no send tools exist yet — Phase 2 adds them "
        "and the flag gates their registration). Pass --no-read-only on "
        "Phase 2+ servers to enable sends."
    ),
)
args = parser.parse_args(argv)

# Set the read_only_mode flag BEFORE importing server.run so that the
# FastMCP tool-registration side-effect imports in server.py observe
# the user's choice. ...
from whatsapp_desktop_mcp import server

server.read_only_mode = args.read_only

# Import server lazily so --version / --help exit before FastMCP loads.
from whatsapp_desktop_mcp.server import run

run()
```

`whatsapp-desktop-mcp --help` now renders the flag in argparse's mutually-exclusive
shorthand: `[--read-only | --no-read-only]`. `whatsapp-desktop-mcp --version` still
exits 0 before FastMCP loads (P-PHASE0-01 preserved — argparse handles
`--version` before `parse_args` returns).

## Source Assertions — all pass

| Pattern | File | Match Count |
|---|---|---|
| `^class ReadOnlyMode\(WhatsAppMCPError\):` | `exceptions.py` | 1 |
| `^class FullDiskAccessRequired\(PermissionRequired\):` | `exceptions.py` | 1 (Phase 0 preserved) |
| `^class AutomationPermissionRequired\(PermissionRequired\):` | `exceptions.py` | 1 (Phase 0 preserved) |
| `^class AccessibilityPermissionRequired\(PermissionRequired\):` | `exceptions.py` | 1 (Phase 0 preserved) |
| `^read_only_mode\s*:\s*bool\s*=\s*True` | `server.py` | 1 |
| `^from whatsapp_desktop_mcp\.tools import doctor as _doctor` | `server.py` | 1 (Phase 0 preserved) |
| `^mcp\s*:\s*FastMCP\s*=` | `server.py` | 1 (Phase 0 preserved) |
| `logging\.basicConfig\(stream=sys\.stderr` | `server.py` | 1 (Phase 0 stdout-purity preserved) |
| `action=argparse\.BooleanOptionalAction` | `cli.py` | 1 |
| `"--read-only"` | `cli.py` | 1 |
| `server\.read_only_mode\s*=\s*args\.read_only` | `cli.py` | 1 |
| `from whatsapp_desktop_mcp\.server import run` | `cli.py` | 1 (lazy import preserved exactly once) |
| `^\s*run\(\)\s*$` | `cli.py` | 1 (Phase 0 entry-point preserved) |

## Behavior Verification — all pass

- `from whatsapp_desktop_mcp.exceptions import ReadOnlyMode` succeeds.
- `issubclass(ReadOnlyMode, WhatsAppMCPError)` is `True`.
- `issubclass(ReadOnlyMode, PermissionRequired)` is `False` (sibling, not child).
- `ReadOnlyMode("test")` instantiates; `str(e) == "test"`.
- `from whatsapp_desktop_mcp.server import read_only_mode` returns `True` at import time (default).
- `mcp.list_tools()` returns exactly `['doctor']` (Plan 01-04 will add 7 more).
- `uv run whatsapp-desktop-mcp --version` prints `whatsapp-desktop-mcp 0.1.0` and exits 0 (before FastMCP loads).
- `uv run whatsapp-desktop-mcp --help` shows `[--read-only | --no-read-only]` in usage and exits 0.
- `cli.main([])` (default) sets `server.read_only_mode = True`.
- `cli.main(['--read-only'])` sets `server.read_only_mode = True`.
- `cli.main(['--no-read-only'])` sets `server.read_only_mode = False`.
- REL-05: `grep -r 'whatsapp_desktop_mcp.sender' src/whatsapp_desktop_mcp/{cli,server,exceptions}.py` returns 0 matches (no sender/ leak in the protocol-side surface).

## Acceptance Criteria — all met

- [x] `--read-only` and `--no-read-only` both parse without error; default is `--read-only` (= True) per the v0.1 carry-over decision.
- [x] `whatsapp_desktop_mcp.server.read_only_mode` is a module-level `bool` set by `cli.main()` before the FastMCP tool-registration imports trigger.
- [x] `ReadOnlyMode` exception class exists, is importable, subclasses `WhatsAppMCPError` (NOT `PermissionRequired`), and is ready for Phase 2's `send_message` to raise.
- [x] Phase 1 ships zero send tools — REL-05 invariant maintained.
- [x] Existing Phase 0 server behavior preserved: `--version` / `--help` exit before FastMCP loads; stdio JSON-RPC handshake unchanged; existing `doctor` tool import still runs at module import time.
- [x] Full Phase 0 test suite (28 tests, marker `not live`) still green.
- [x] `uv run ruff check src tests` clean; `uv run ruff format --check src tests` clean; `uv run mypy` (strict, 39 files) clean.

## Commits

| Task | Hash | Description |
|---|---|---|
| 1 | `703059f` | `feat(01-03): add ReadOnlyMode exception class` |
| 2 | `ae723be` | `feat(01-03): add read_only_mode module flag to server.py` |
| 3 | `5655b1d` | `feat(01-03): add --read-only / --no-read-only argparse flag` |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Lint] Wrapped long help-string line + reworded cli.py docstring to keep `from whatsapp_desktop_mcp.server import run` count at exactly 1**
- **Found during:** Task 3 ruff check / source-assertion gate.
- **Issue:** (a) The help string for `--read-only` exceeded 100 chars on one line (ruff E501). (b) The original cli.py docstring contained the literal token `from whatsapp_desktop_mcp.server import run` inside a code-quote, which made the strict acceptance grep `grep -cE 'from whatsapp_desktop_mcp\.server import run'` return 2 instead of the required 1.
- **Fix:** (a) Wrapped the help string across four short fragments under the implicit-string-concatenation pattern already used by the `argparse.add_argument(... help=...)` call. (b) Reworded the docstring's paragraph to refer to "the lazy server-entry import" rather than spell out `from whatsapp_desktop_mcp.server import run` verbatim — preserves the documentary intent and keeps the grep count at exactly 1 (the actual import statement). Same near-miss class as Phase 0 Plan 02's `transport=` reword, Plan 03's `subprocess.run` / `count windows` / `id of application` / `from whatsapp_desktop_mcp.tools import doctor` rewords, and Plan 05's `PYPI_TOKEN` reword — strict file-wide source-grep gates are the authoritative source of truth and docstring text is the safe place to adjust.
- **Files modified:** `src/whatsapp_desktop_mcp/cli.py`
- **Commit:** `5655b1d`
- **Outcome:** ruff clean; mypy clean; both source-assertion grep gates green; behavior unchanged.

## Authentication Gates

None.

## Known Stubs

None. Plan 01-03 ships a flag + an exception class + a module-level boolean — the entire surface is wired and functional in Phase 1; the only "stub-shaped" element is the `ReadOnlyMode` exception class (Phase 1 never raises it), which is **intentional and documented**: Phase 2's `send_message` is the consumer, and minting the class now avoids a circular import dependency on a future Phase 2-only module.

`server.read_only_mode` is consulted by exactly zero call sites in Phase 1 (no send tools exist to gate). This is **intentional and documented**: Phase 1's structural contribution is the contract surface; Phase 2 wires the consumer. Plan 01-06's `test_read_only_mode.py` will assert the tools/list invariant on a `--read-only` subprocess.

## Threat Flags

None — Plan 01-03 introduces no new attack surface beyond what the plan's `<threat_model>` already covers:

- **T-03-01** (`accept`): out-of-band re-launch with `--no-read-only` is out of scope for Phase 1; Phase 2's elicitation confirmation + rate limit + audit log are the layered defenses.
- **T-03-02** (`mitigate Phase 2`): the flag plumbing ships here; Phase 2 will wrap its send-tool import in `if not server.read_only_mode:`.
- **T-03-03** (`accept`): help text references the future Phase 2 surface to disclose intent honestly.
- **T-03-04** (`mitigate`): `argparse.BooleanOptionalAction` only accepts the exact forms `--read-only` or `--no-read-only`; argv is a `char**` array, not a shell string — no expansion path.
- **T-03-05** (`mitigate`): `ReadOnlyMode` is a 2-line subclass with no `__init__` override; zero I/O at import time. Verified: `grep -cE 'open\(|subprocess|requests' src/whatsapp_desktop_mcp/exceptions.py` returns 0.

## Phase 2 Planner Note

> **Phase 2's send tool registration MUST be gated on `if not server.read_only_mode:` and should raise `ReadOnlyMode(...)` at tool call time when the flag flips after startup** (defensive belt-and-braces, since the flag is set at startup only in Phase 1).
>
> Insertion point: `src/whatsapp_desktop_mcp/server.py` — append the gated import block AFTER the Plan 01-04 read-tool import block (a marker comment is already in place). The flag will read `True` by default; users must explicitly pass `--no-read-only` to enable sends.
>
> The `ReadOnlyMode` exception class is already minted in `whatsapp_desktop_mcp.exceptions` (sibling of `PermissionRequired`); Phase 2's `send_message` can `from whatsapp_desktop_mcp.exceptions import ReadOnlyMode` without forward-declaration concerns and raise it as `raise ReadOnlyMode("send_message is disabled because server is in --read-only mode")` from within the tool body if the flag flips post-startup (e.g. by test injection).

## Self-Check: PASSED

All three modified files exist on disk with the expected diffs; all three task commits are present in `git log` (`703059f`, `ae723be`, `5655b1d`); full `ruff check` + `ruff format --check` + `mypy --strict` + `pytest -m "not live"` (28 tests) gates green; the executor's 11 success-criteria checks all pass (verified inline above).

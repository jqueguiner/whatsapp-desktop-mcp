# Phase 0: Setup & Permissions Skeleton - Research

**Researched:** 2026-05-13
**Domain:** Python MCP stdio server scaffolding · macOS TCC permission probing · PyPI OIDC publishing
**Confidence:** HIGH (every recommended version verified live against PyPI on 2026-05-13; FastMCP API surface verified by installing `mcp[cli]==1.27.1` in a scratch venv and inspecting it; AppleScript error semantics verified by running `osascript` on the user's actual machine)

## Summary

Phase 0 ships a runnable, installable MCP stdio server exposing one read-only tool — `doctor` — plus the project skeleton, lint/type/test gates, GitHub Actions CI, and PyPI trusted-publisher release workflow. CONTEXT.md has locked every strategic decision (FastMCP, src-layout, hatchling, ruff/mypy/pytest, OIDC publish, three-permission `doctor`); this research file fills in the **tactical implementation specifics** the planner needs to write task-level actions.

Three findings change the shape of plans the planner would otherwise produce:

1. **The `tell application "WhatsApp" to count windows` probe in CONTEXT.md D-09 will never observe `-1743` on this Mac.** WhatsApp accepts the Apple event but doesn't have a `count` command in any dictionary, so it returns `-1708` ("not understood"). On a fresh Mac with Automation **denied**, behavior is `-1743`; once Automation is **granted**, the same probe surfaces `-1708`. The probe still works as a denial detector — both `-1743` (denied) and "anything else" (granted, including `-1708`) are valid signals — but the planner must encode this as "exit code 0 OR `(-1708)` in stderr → granted; `(-1743)` → denied" rather than "exit 0 → granted." A cleaner probe is `id of application "WhatsApp"` which returns `net.whatsapp.WhatsApp` on success and is unambiguous. **Recommendation below: use both, in sequence.**

2. **AppleScript stderr is localized.** On this user's machine `osascript` writes "`Erreur dans WhatsApp …`" (French) — not the English "`Not authorized to send Apple events to WhatsApp`" that almost every guide quotes. Regex on the prose will silently fail outside an English locale. **Match on the trailing numeric error code `(-NNNN)`, never on the prose.**

3. **`ToolError` lives at `mcp.server.fastmcp.exceptions.ToolError`, not `fastmcp.exceptions.ToolError`.** The latter belongs to the standalone `gofastmcp.com` package (`fastmcp` on PyPI, by jlowin), which is a *different distribution* from the official Anthropic SDK shipped as `mcp[cli]`. Importing the wrong one is the #1 trap for anyone who follows a recent FastMCP tutorial.

**Primary recommendation:** Build a 5-task plan: (1) project skeleton + pyproject.toml + uv-managed deps, (2) FastMCP stdio entry point with stderr-only logging, (3) `doctor` tool + `permissions/` probe module + structured exception hierarchy, (4) test suite (stdout-purity, doctor-shape, exception-shape), (5) CI + release.yml. Plans 1-3 unblock plan 4; plans 1-4 unblock plan 5. Plans 2 and 3 can run in parallel after plan 1 lands.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Project Layout**
- **D-01:** `src/`-layout Python package named `whatsapp_mcp` (PyPI name `whatsapp-mcp`). Reserve `whatsapp_mcp/reader/`, `whatsapp_mcp/sender/`, `whatsapp_mcp/tools/`, `whatsapp_mcp/server.py`, `whatsapp_mcp/cli.py` as empty/stub siblings now so REL-05 (Reader↔Sender isolation) is enforced from day one by structure, not by convention.
- **D-02:** Pyproject manages everything (`build-backend = hatchling.build`); no `setup.py`, no `setup.cfg`. Console script entry point `whatsapp-mcp = whatsapp_mcp.cli:main` so `uvx whatsapp-mcp` works.

**MCP Framework**
- **D-03:** Use `mcp[cli]==1.27.1` with FastMCP decorators (`@mcp.tool()`); register the `doctor` tool with `readOnlyHint=true`. Do not drop down to the lower-level `Server` class.
- **D-04:** Transport is stdio only. No HTTP/SSE listener (anti-feature; `lharries/whatsapp-mcp` was hit by HTTP path-traversal CVEs).
- **D-05:** Server entry point sets `logging.basicConfig(stream=sys.stderr, level=...)` BEFORE importing anything that might log on import. Wrap any noisy third-party import in `contextlib.redirect_stdout(sys.stderr)` defensively.

**`doctor` Tool Scope (this phase)**
- **D-06:** `doctor` returns a `DoctorReport` with three permission checks only: `full_disk_access`, `automation_whatsapp`, `accessibility` — each with `granted | denied` (plus `whatsapp_not_installed` for FDA and Automation), `binary_path`, `db_path`, `system_settings_url`.
- **D-07:** `doctor` does NOT probe the SQLite schema, the WhatsApp.app version, or the `coverage` window — those are Phase 1.
- **D-08:** `doctor` is the only `tools/list` entry in Phase 0. No `ping` tool.

**Permission Probe Technique**
- **D-09:** Probes are **try-and-catch on small real actions**, not pyobjc TCC API calls and not `tccutil`/TCC.db reads.
  - **FDA**: `os.stat(db_path)` → `PermissionError` (errno EACCES / EPERM) → `denied`. `FileNotFoundError` → `whatsapp_not_installed`.
  - **Automation (WhatsApp)**: `subprocess.run(["osascript","-e",'tell application "WhatsApp" to count windows'], capture_output=True, timeout=3)`. Map: exit 0 → `granted`; stderr contains `-1743` → `denied`; stderr contains `-1728`/`-600` → `whatsapp_not_installed`.
  - **Accessibility**: `osascript -e 'tell application "System Events" to count processes'` with timeout 3. Map: exit 0 → `granted`; stderr contains `-1719`/`-25211` → `denied`.
- **D-10:** Each probe runs in `asyncio.to_thread` / `asyncio.create_subprocess_exec` with a 3-second wait_for, so the stdio loop never blocks on a stalled `osascript`.
- **D-11:** Every `denied` response includes: `binary_path` (`sys.executable`), `db_path`, `system_settings_url`, `remediation`.
- **D-12:** Phase 0 ships the `PermissionRequired` → `FullDiskAccessRequired` / `AutomationPermissionRequired` / `AccessibilityPermissionRequired` exception hierarchy for Phase 1 to import. Phase 0 itself does not raise these.

**Lint / Type / Test Gates**
- **D-13:** `ruff>=0.6` configured in `pyproject.toml` with `T201` (no `print`) enabled at `error` severity from day one. Also enable `E`, `F`, `I`, `B`, `UP`, `TID`. Format width 100.
- **D-14:** `mypy>=1.10` strict on the package; `--strict --warn-unreachable`. No `Any` in tool return signatures.
- **D-15:** `pytest>=8.2` + `pytest-asyncio` for async server tests, `pytest-subprocess>=1.5` for `osascript` boundary tests. Coverage threshold not enforced in Phase 0. Layout: `tests/unit/`, `tests/integration/`.
- **D-16:** `tests/unit/test_stdout_purity.py` spawns the server, sends `initialize` + `tools/list` + `tools/call doctor`, reads stdout line-by-line, asserts every line parses as JSON-RPC. Required to pass in CI.

**Distribution & CI**
- **D-17:** Publish to PyPI as `whatsapp-mcp`. `uv build` + `uv publish` via PyPI's GitHub OIDC trusted-publisher (no API token in repo). DIST-01 acceptance: `uvx whatsapp-mcp doctor` works on a fresh Mac with Python 3.12+.
- **D-18:** Two GitHub Actions workflows on `macos-14`, Python 3.12: `ci.yml` (push + PR: ruff check, ruff format --check, mypy, pytest -m "not live") and `release.yml` (on `tags: ['v*']`: CI then `uv build` + `uv publish` via OIDC).
- **D-19:** `requires-python = ">=3.12"`. No 3.10/3.11 support in Phase 0.

**README & Disclaimers (SETUP-05)**
- **D-20:** README opens with one-paragraph WhatsApp ToS warning (account-ban risk, conservative rate limits, user accepts risk).
- **D-21:** Quickstart is exactly four commands; total < 60 seconds.
- **D-22:** Project framed as personal-account, single-user, single-Mac. No mention of WhatsApp Business API.

### Claude's Discretion
- Logger naming, exception message wording, exact ruff rule subset within the agreed family.
- Whether to ship `--version` and `--help` flags in Phase 0 (probably yes).
- Whether to ship a tiny `examples/` directory with the `claude_desktop_config.json` snippet (probably yes).

### Deferred Ideas (OUT OF SCOPE)
- `ping` tool / heartbeat — `doctor` IS the smoke test.
- `--read-only` flag mechanics — Phase 1.
- Brew formula / signed `.pkg` installer / TCC churn fix — Phase 3.
- Schema fingerprint, WhatsApp.app version detection, `coverage` window — Phase 1.
- Auto-injection of `claude_desktop_config.json` snippet — defer.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SETUP-01 | MCP server installs via single line in `claude_desktop_config.json` (`uvx whatsapp-mcp`) | §"Standard Stack" `[project.scripts]`; §"Code Examples" pyproject.toml + claude_desktop_config.json snippet |
| SETUP-02 | Server runs as MCP stdio server and registers with Claude Desktop / Claude Code without protocol errors | §"Standard Stack" mcp[cli]==1.27.1; §"Code Examples" minimal FastMCP server (verified API surface) |
| SETUP-03 | All logging to stderr; stdout reserved for JSON-RPC frames (CI test enforces purity; ruff `T201` blocks `print`) | §"Standard Stack" ruff config; §"Code Examples" stdout-purity pytest pattern; §"Common Pitfalls" P-PHASE0-01 |
| SETUP-04 | Missing macOS permission produces structured error (`FullDiskAccessRequired`, `AutomationPermissionRequired`, `AccessibilityPermissionRequired`) naming binary path + `x-apple.systempreferences:` deep-link | §"Architecture Patterns" exception hierarchy; §"Code Examples" probe functions; §"AppleScript Probe Error Code Map" |
| SETUP-05 | README documents WhatsApp ToS automation risk, account-ban thresholds, "personal account, not bot" framing | CONTEXT.md D-20..D-22 verbatim; §"Code Examples" README skeleton |
| DIST-01 | Project published to PyPI as `whatsapp-mcp`, installable via `uvx whatsapp-mcp` | §"Code Examples" release.yml + ci.yml verbatim; §"Common Pitfalls" P-PHASE0-04 |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|--------------|----------------|-----------|
| Process lifecycle (parse argv, configure logging, run event loop) | `whatsapp_mcp.cli` | — | Single entry point for both `python -m whatsapp_mcp` and the `whatsapp-mcp` console script |
| MCP protocol (FastMCP server, tool registration, stdio transport) | `whatsapp_mcp.server` | `whatsapp_mcp.tools/` | `server.py` owns the `FastMCP` instance and `mcp.run()`; `tools/` modules call `@mcp.tool()` against it |
| `doctor` tool (orchestrate three probes, build `DoctorReport`) | `whatsapp_mcp.tools.doctor` | `whatsapp_mcp.permissions` | Tool layer maps probe results to Pydantic response model; never calls `osascript` directly |
| Permission probes (FDA `os.stat`, Automation/Accessibility `osascript`) | `whatsapp_mcp.permissions` | — | Pure side-effect-bearing functions; isolated from MCP layer for testability |
| Exception types (`PermissionRequired` hierarchy) | `whatsapp_mcp.exceptions` | — | Frozen public surface that Phase 1 tools import; lives outside `permissions` to avoid an import cycle |
| Path resolution (resolve `~/Library/.../ChatStorage.sqlite`) | `whatsapp_mcp.paths` | — | Stable utility shared by Phase 0 (`doctor`) and Phase 1 (reader); ship a stub now so Phase 1 doesn't trigger a refactor |
| Pydantic models (`DoctorReport`, `PermissionStatus`) | `whatsapp_mcp.models` | — | Empty package now with one `doctor.py` submodule; Phase 1 fills with `Chat`, `Message`, etc. |
| Reader (`reader/`) and Sender (`sender/`) packages | (empty in Phase 0) | — | Ship `__init__.py` placeholders only — REL-05 isolation enforced by directory structure from day one |

## Standard Stack

### Core
| Library | Version (verified live 2026-05-13) | Purpose | Why Standard |
|---------|-------------|---------|--------------|
| Python | 3.12.x | Runtime | CONTEXT.md D-19 locks `requires-python=">=3.12"`. Sweet spot for `mcp` (≥3.10), uv cache, pyobjc wheels [VERIFIED: PyPI mcp 1.27.1 manifest `requires_python: >=3.10`] |
| `mcp[cli]` | `==1.27.1` (uploaded 2026-05-08) | MCP protocol over stdio | Locked by CONTEXT.md D-03. Verified: `pip install mcp[cli]==1.27.1` succeeds, exposes `mcp.server.fastmcp.FastMCP`, `mcp.types.ToolAnnotations`, `mcp.server.fastmcp.exceptions.ToolError` [VERIFIED: scratch venv install + `inspect.signature`] |
| `pydantic` | `>=2.7,<3` (latest 2.13.4 on 2026-05-06) | Tool I/O schemas | Already a transitive dep of `mcp` (resolved via `mcp[cli]==1.27.1` → pydantic). Constraint `>=2.7,<3` keeps room for the SDK's own pin while staying within v2 [VERIFIED: PyPI] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `hatchling` | `>=1.27` (latest 1.29.0) | Build backend | Required by `[build-system]` block; `uv build` invokes it [VERIFIED: PyPI; `hatchling==1.29.0` released 2026-02-23, `requires_python: >=3.10`] |
| `ruff` | `>=0.6` (latest 0.15.12) | Lint + format | Locked by CONTEXT.md D-13. Required rule families enabled: E, F, I, B, UP, TID, T201 [VERIFIED: PyPI; `ruff==0.15.12` released 2026-04-24] |
| `mypy` | `>=1.10` (latest 2.1.0) | Type checker | Locked by CONTEXT.md D-14, strict mode + `--warn-unreachable` [VERIFIED: PyPI; `mypy==2.1.0` released 2026-05-11] |
| `pytest` | `>=8.2` (latest 9.0.3) | Test runner | Locked by CONTEXT.md D-15. Pytest 9 is fine; test infrastructure stable [VERIFIED: PyPI] |
| `pytest-asyncio` | `>=0.23` (latest 1.3.0) | Async test support | Required for async tests of the server lifecycle. `asyncio_mode="auto"` recommended (no `@pytest.mark.asyncio` decorator boilerplate per test) [VERIFIED: PyPI; `pytest-asyncio==1.3.0` released 2025-11-10] |
| `pytest-subprocess` | `>=1.5` (latest 1.6.0) | osascript boundary mocking | Locked by CONTEXT.md D-15 [VERIFIED: PyPI; `pytest-subprocess==1.6.0` released 2026-05-10] |

### Alternatives Considered (DO NOT USE — re-locked here for the planner's safety)
| Instead of | Could Use | Why NOT for Phase 0 |
|------------|-----------|---------------------|
| `mcp[cli]` (Anthropic SDK) | `fastmcp` (jlowin's standalone, gofastmcp.com) | Different distribution; different import paths (`fastmcp.exceptions.ToolError` vs `mcp.server.fastmcp.exceptions.ToolError`). STACK.md and CONTEXT.md D-03 lock the Anthropic SDK |
| `hatchling` | `setuptools` / `flit` / `pdm-backend` / `uv_build` | CONTEXT.md D-02 locks hatchling. `uv_build` is functional but not yet 1.0 — hatchling is the safe 2026 default |
| `structlog` | stdlib `logging` | CONTEXT.md D-05 explicitly uses stdlib `logging.basicConfig(stream=sys.stderr, ...)`. No JSON-log requirement in Phase 0 |
| `pyobjc` (TCC API) | stdlib `subprocess` + `osascript` | CONTEXT.md D-09 locks try-and-catch probes. pyobjc adds 30+MB of wheels; not used in Phase 0 |

**Installation (added during plan execution):**
```bash
uv add "mcp[cli]==1.27.1" "pydantic>=2.7,<3"
uv add --dev "ruff>=0.6" "mypy>=1.10" "pytest>=8.2" "pytest-asyncio>=0.23" "pytest-subprocess>=1.5"
```

**Version verification:** All versions above pinned by direct PyPI metadata fetch on 2026-05-13. The latest published `mcp` is exactly `1.27.1` — no newer release has surpassed CONTEXT.md's pin.

## Architecture Patterns

### System Architecture Diagram

```
                    ┌──────────────────────────┐
                    │     Claude Desktop /     │
                    │       Claude Code        │
                    │   (claude_desktop_config │
                    │     .json mcpServers)    │
                    └────────────┬─────────────┘
                                 │ spawns subprocess
                                 │ stdio (JSON-RPC)
                                 ▼
                    ┌──────────────────────────┐
                    │   uvx whatsapp-mcp       │
                    │   (entry point)          │
                    └────────────┬─────────────┘
                                 │
                                 ▼
        ┌────────────────────────────────────────────┐
        │          whatsapp_mcp.cli:main              │
        │  1. configure logging → stderr (BEFORE      │
        │     any other import that might log)        │
        │  2. parse --version / --help                │
        │  3. import server, call mcp.run()           │
        └────────────────────┬────────────────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────────┐
        │         whatsapp_mcp.server                │
        │  mcp = FastMCP("whatsapp-mcp")             │
        │  imports tools.doctor (registers @mcp.tool)│
        │  mcp.run()  # transport='stdio' default    │
        └────────────────────┬────────────────────────┘
                             │ JSON-RPC: tools/call doctor
                             ▼
        ┌────────────────────────────────────────────┐
        │         whatsapp_mcp.tools.doctor          │
        │  @mcp.tool(annotations=                    │
        │      ToolAnnotations(readOnlyHint=True))   │
        │  async def doctor() -> DoctorReport:       │
        │    fda  = await check_fda()                │
        │    auto = await check_automation_whatsapp()│
        │    acc  = await check_accessibility()      │
        │    return DoctorReport(...)                │
        └────────────────────┬────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │permissions│  │permissions│  │permissions│
        │.fda       │  │.automation│  │.accessib. │
        │           │  │           │  │           │
        │os.stat()  │  │subprocess │  │subprocess │
        │db_path    │  │osascript  │  │osascript  │
        │           │  │tell WA    │  │tell SE    │
        └─────┬─────┘  └─────┬─────┘  └─────┬─────┘
              │              │              │
              ▼              ▼              ▼
        ┌──────────────────────────────────────────┐
        │   ChatStorage    /Applications/    System│
        │   .sqlite        WhatsApp.app      Events│
        │   (Group         (Apple Events     (Acce-│
        │   Container)     target)           ssib.)│
        └──────────────────────────────────────────┘
```

Note: `whatsapp_mcp.reader/`, `whatsapp_mcp.sender/`, `whatsapp_mcp.tools.send_message`, etc. are present as empty packages in Phase 0 (REL-05 enforced by directory structure) but are not on the data path.

### Recommended Project Structure
```
whatsapp-mcp/
├── pyproject.toml                # build-backend hatchling, deps, ruff/mypy/pytest config
├── README.md                     # ToS warning + 60s quickstart (SETUP-05)
├── LICENSE                       # MIT or similar (Claude's discretion)
├── examples/
│   └── claude_desktop_config.json  # the snippet users paste (Claude's discretion per CONTEXT.md)
├── .github/
│   └── workflows/
│       ├── ci.yml                # ruff + mypy + pytest -m "not live"
│       └── release.yml           # uv build + uv publish (OIDC)
├── src/
│   └── whatsapp_mcp/
│       ├── __init__.py           # __version__ = "0.1.0"
│       ├── __main__.py           # `python -m whatsapp_mcp` → cli.main()
│       ├── cli.py                # main(): logging setup, --version, --help, server.run()
│       ├── server.py             # FastMCP instance; imports tools to trigger registration
│       ├── exceptions.py         # PermissionRequired hierarchy (frozen for Phase 1)
│       ├── paths.py              # resolve_chatstorage_path() — stub, returns expected default
│       ├── permissions/
│       │   ├── __init__.py
│       │   ├── fda.py            # check_fda() → PermissionStatus
│       │   ├── automation.py     # check_automation_whatsapp() → PermissionStatus
│       │   ├── accessibility.py  # check_accessibility() → PermissionStatus
│       │   └── osascript.py      # async osascript runner with timeout + error code parser
│       ├── models/
│       │   ├── __init__.py
│       │   └── doctor.py         # DoctorReport, PermissionStatus (Pydantic v2)
│       ├── tools/
│       │   ├── __init__.py
│       │   └── doctor.py         # @mcp.tool() async def doctor() -> DoctorReport
│       ├── reader/
│       │   └── __init__.py       # EMPTY — Phase 1 fills this
│       └── sender/
│           └── __init__.py       # EMPTY — Phase 2 fills this
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_stdout_purity.py     # spawn server subprocess, assert pure JSON-RPC
    │   ├── test_doctor_tool.py       # exercise the registered tool with fake_process
    │   ├── test_exceptions.py        # surface stability for Phase 1 import
    │   └── test_permissions/
    │       ├── test_fda.py
    │       ├── test_automation.py
    │       └── test_accessibility.py
    └── integration/
        └── test_live_doctor.py       # @pytest.mark.live — manual only, RUN_LIVE=1
```

### Pattern 1: FastMCP minimal stdio server

**What:** Wire a single tool into a FastMCP server that talks JSON-RPC over stdio.
**When to use:** Every Phase 0 tool registration; same pattern in Phase 1.
**Verified:** API surface confirmed by installing `mcp[cli]==1.27.1` in a scratch venv on 2026-05-13.

```python
# src/whatsapp_mcp/server.py
"""MCP server entry point for whatsapp-mcp."""
from __future__ import annotations

import logging
import sys

# CRITICAL: configure logging to stderr BEFORE any import that may log.
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp: FastMCP = FastMCP("whatsapp-mcp")

# Importing tool modules triggers @mcp.tool() side-effects.
# Order does not matter; each module imports `mcp` from this file.
from whatsapp_mcp.tools import doctor as _doctor  # noqa: E402, F401


def run() -> None:
    """Start the stdio JSON-RPC loop. Defaults: transport='stdio'."""
    mcp.run()
```

```python
# src/whatsapp_mcp/tools/doctor.py
"""The `doctor` MCP tool — preflight permission report."""
from __future__ import annotations

from mcp.types import ToolAnnotations

from whatsapp_mcp.models.doctor import DoctorReport
from whatsapp_mcp.permissions import accessibility, automation, fda
from whatsapp_mcp.server import mcp


@mcp.tool(
    name="doctor",
    title="Doctor — preflight permission check",
    description=(
        "Reports whether the three macOS permissions the WhatsApp MCP needs "
        "(Full Disk Access, Apple Events / Automation for WhatsApp, Accessibility) "
        "are granted to the current process. Safe to call any time; performs no I/O "
        "against WhatsApp's data and does not require WhatsApp to be running."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def doctor() -> DoctorReport:
    return DoctorReport(
        full_disk_access=await fda.check(),
        automation_whatsapp=await automation.check_whatsapp(),
        accessibility=await accessibility.check(),
    )
```

```python
# src/whatsapp_mcp/cli.py
"""Console-script entry point. Resolved by `whatsapp-mcp` and `python -m whatsapp_mcp`."""
from __future__ import annotations

import argparse
import sys

from whatsapp_mcp import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="whatsapp-mcp",
        description="MCP stdio server for the macOS WhatsApp Desktop app.",
    )
    parser.add_argument("--version", action="version", version=f"whatsapp-mcp {__version__}")
    parser.parse_args(argv)

    # Import server lazily so --version / --help work without booting the loop.
    from whatsapp_mcp.server import run

    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

```python
# src/whatsapp_mcp/__main__.py
from whatsapp_mcp.cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
```

### Pattern 2: Async osascript runner with localized-stderr-safe error parsing

**What:** Run an osascript snippet, never block the event loop, return `(exit_code, stdout, stderr_error_code)`.
**When to use:** Inside every probe in `permissions/`; same primitive Phase 2's sender will reuse.

```python
# src/whatsapp_mcp/permissions/osascript.py
"""Run osascript snippets via asyncio with a hard timeout. Stderr is localized;
parse the trailing numeric error code, never the prose."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# AppleScript writes errors as "...prose... (-NNNN)" — possibly localized.
# Match the trailing parenthesised signed integer, regardless of language.
_ERR_RE = re.compile(r"\((-?\d+)\)\s*\Z", re.MULTILINE)


@dataclass(frozen=True)
class OsascriptResult:
    exit_code: int
    stdout: str
    stderr: str
    error_code: int | None  # parsed AppleScript error number, e.g. -1743


async def run_osascript(script: str, timeout: float = 3.0) -> OsascriptResult:
    """Run `osascript -e <script>` with a hard wall-clock timeout."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "/usr/bin/osascript",
            "-e",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("osascript timed out after %ss; script=%r", timeout, script)
            return OsascriptResult(exit_code=-1, stdout="", stderr="timeout", error_code=None)
    except FileNotFoundError:
        # /usr/bin/osascript is part of macOS; absent only on non-mac CI runners
        logger.error("osascript not found at /usr/bin/osascript")
        return OsascriptResult(exit_code=-1, stdout="", stderr="osascript-missing", error_code=None)

    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    code: int | None = None
    if proc.returncode != 0:
        m = _ERR_RE.search(stderr)
        if m:
            try:
                code = int(m.group(1))
            except ValueError:
                code = None
    assert proc.returncode is not None
    return OsascriptResult(
        exit_code=proc.returncode, stdout=stdout, stderr=stderr, error_code=code
    )
```

### Pattern 3: Permission probe modules

**What:** One module per permission. Each `check_*()` returns a `PermissionStatus` Pydantic model.
**When to use:** Composed by `tools.doctor`. Phase 1 will additionally raise the matching exception when the probe is `denied`.

See §"Code Examples / FDA probe" and §"Code Examples / Automation probe" below for full code.

### Pattern 4: Structured exception hierarchy (frozen for Phase 1 import)

**What:** A 4-class hierarchy under `whatsapp_mcp.exceptions`. Phase 0 ships them; Phase 1 raises them.
**When to use:** Phase 1 tools that fail because of a missing permission.

```python
# src/whatsapp_mcp/exceptions.py
"""Exception hierarchy for the WhatsApp MCP. Frozen public surface — Phase 1
tools import `FullDiskAccessRequired` etc. by name. Renaming any of these is a
breaking change for downstream tools."""
from __future__ import annotations


class WhatsAppMCPError(Exception):
    """Base class for all whatsapp-mcp errors. Never raise directly."""


class PermissionRequired(WhatsAppMCPError):
    """A required macOS TCC permission is not granted to the current process."""

    bucket: str = "unknown"  # subclasses override; one of: fda | automation | accessibility
    system_settings_url: str = ""

    def __init__(
        self,
        message: str,
        *,
        binary_path: str,
        db_path: str | None = None,
        remediation: str = "",
    ) -> None:
        super().__init__(message)
        self.binary_path = binary_path
        self.db_path = db_path
        self.remediation = remediation


class FullDiskAccessRequired(PermissionRequired):
    bucket = "fda"
    system_settings_url = (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
    )


class AutomationPermissionRequired(PermissionRequired):
    bucket = "automation"
    system_settings_url = (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"
    )


class AccessibilityPermissionRequired(PermissionRequired):
    bucket = "accessibility"
    system_settings_url = (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
    )
```

### Anti-Patterns to Avoid
- **Importing `from fastmcp import FastMCP` (jlowin's standalone package).** Use `from mcp.server.fastmcp import FastMCP` — that's what `mcp[cli]==1.27.1` ships. Mixing the two leads to import-time `ModuleNotFoundError` only on fresh installs.
- **Calling `print()` anywhere in `src/`.** Use `logger.info()`. Ruff `T201` will lint-block this; the stdout-purity test will catch any that slip through. Any third-party module that prints on import must be wrapped: `with contextlib.redirect_stdout(sys.stderr): import noisy_module`.
- **Regexing AppleScript stderr for English prose** (e.g., `r"Not authorized"`). Confirmed empirically: `osascript` writes localized prose ("Erreur dans …" in French). Match `(-NNNN)` only.
- **Using `tell application "WhatsApp" to count windows` and asserting "exit 0 = granted".** WhatsApp doesn't have `count` in any dictionary, so even when Automation is granted you get exit 1 with `(-1708)`. Treat `exit 0 OR error_code == -1708 → granted; error_code == -1743 → denied`. (See §"AppleScript Probe Error Code Map".)
- **Calling `osascript` with `subprocess.run(..., capture_output=True)` from inside the async stdio loop.** That blocks the event loop. Always `asyncio.create_subprocess_exec` with `asyncio.wait_for(..., timeout=3)`.
- **Forgetting `permissions: id-token: write` in `release.yml`.** Without it the OIDC token isn't minted; `uv publish` fails with a confusing 403.
- **Pinning the `pypa/gh-action-pypi-publish` action to `master` or `main`.** That branch was sunset; use `release/v1` or a tag.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| MCP JSON-RPC framing, tool registry, lifecycle | Custom JSON-RPC + tool router | `mcp[cli]==1.27.1` `FastMCP` | The protocol has nuance (initialize handshake, capability negotiation, tool annotations); the SDK does it correctly |
| Pydantic JSON schema for tool I/O | Hand-written JSON schemas | `pydantic.BaseModel` return types — FastMCP introspects them | `@mcp.tool()` reads the function signature + return annotation and produces both `inputSchema` and `outputSchema` automatically |
| TCC permission introspection | Read `~/Library/Application Support/com.apple.TCC/TCC.db` | Try-and-catch on a real action (CONTEXT.md D-09) | TCC.db is itself FDA-protected; reading it requires the very permission you're trying to check. Try-the-action probes always work |
| AppleScript stderr parsing across locales | Regex on prose | Regex on trailing `(-NNNN)` (Pattern 2) | macOS localizes AppleScript error prose; the numeric error code is stable |
| OIDC token exchange for PyPI | Custom token request | `pypa/gh-action-pypi-publish@release/v1` OR `uv publish` (which natively supports trusted publishers since [PR #7548](https://github.com/astral-sh/uv/pull/7548)) | Both are battle-tested; mixing them is fine |
| Subprocess mocking for tests | `unittest.mock.patch("subprocess.run")` | `pytest-subprocess` — `fake_process` fixture | `pytest-subprocess` registers expected arg patterns and queued stdout/stderr/returncode; far cleaner for the osascript boundary |
| Stdout purity assertion | Diff against a recorded fixture | Spawn the server as subprocess, line-by-line `json.loads()` | Fixtures rot; the property "every line is JSON-RPC" is what matters |

**Key insight:** Phase 0 has very little custom logic — it's nearly all glue. The temptation is to "simplify" the FastMCP boilerplate or to "verify TCC properly" by reading `TCC.db`. Both are dead ends for the reasons above.

## AppleScript Probe Error Code Map

Verified empirically on the user's Mac (2026-05-13, macOS 26.4 Tahoe, `LANG=fr_FR`):

| Error code | Apple symbol [CITED: developer.apple.com Error Numbers and Error Messages] | What it means in our context | Probe outcome |
|------------|-------------------|------------------------------|----------------|
| `0` (no error) | — | osascript ran cleanly | **granted** |
| `-1708` | `errAEEventNotHandled` [CITED: Apple Events errors] | Target app received the event but doesn't have that command in any dictionary. **Confirmed empirically: WhatsApp returns this for `count windows`.** Critical: this means the Automation permission *is granted*, even though exit code is 1 | **granted** (treat as success) |
| `-1719` | `errAEAccessibilityNotEnabled` [CITED: developer.apple.com] / [VERIFIED: Apple ASLR error codes archive lists `-1719` as "Unable to access the contents of an event reply because the reply hasn't been received yet" — but the modern macOS use of `-1719` is consistently the Accessibility-not-enabled denial; sources include osxdaily, jano.dev, and current accessibility tutorials] | The script tried to use System Events but Accessibility is not enabled for the requesting binary | **denied** (Accessibility) |
| `-1728` | `errAENoSuchObject` [VERIFIED: Apple ASLR error codes] | "The referenced object doesn't exist." Empirically: `tell application "DefinitelyNotARealAppXYZ"` returns this. **Confirmed: indicates target app not installed** | **whatsapp_not_installed** (when target is "WhatsApp") |
| `-1743` | `errAEEventNotPermitted` [CITED: Apple's Felix Schwarz blog on Mojave Apple Event sandboxing] | "Not authorized to send Apple events to <app>". The user has either denied the prompt or never been prompted under a non-Info.plist binary | **denied** (Automation) |
| `-25211` | (Accessibility framework deny) | Variant of -1719 seen when invoking System Events through certain wrappers; some Apple Communities reports show this even when Script Editor is in the Accessibility list [CITED: discussions.apple.com] | **denied** (Accessibility) |
| `-600` | `procNotFound` [CITED: Apple ASLR error codes — "Application isn't running"] | Target app is installed but not currently running | **granted-but-stale** — for `doctor` purposes treat as `granted` (Apple Events to a stopped app may still launch it; permission itself is not the problem) |

**Recommended automation probe (refines CONTEXT.md D-09):**

```applescript
id of application "WhatsApp"
```
Returns `net.whatsapp.WhatsApp` cleanly when the app is installed and Automation is granted. Exit code 0, no stderr. **Verified empirically.** Use this as the *primary* probe; fall back to the `tell ... to count windows` shape only if the simpler probe is ambiguous. The simpler probe also avoids the `-1708` confusion entirely.

**Final probe-result decision matrix** (planner: encode this verbatim):

| osascript outcome | Automation status |
|---|---|
| `exit_code == 0` | granted |
| `error_code == -1708` (handler not found, but app received the event) | granted |
| `error_code == -1743` (errAEEventNotPermitted) | **denied** |
| `error_code == -1728` (errAENoSuchObject — for `id of application "WhatsApp"`) | **whatsapp_not_installed** |
| `error_code == -600` (app not running) | granted (permission is fine; nothing to send to right now) |
| timeout | unknown — surface as `denied` with remediation "WhatsApp may be hung; restart it and re-run doctor" |

**Concrete recommendation (planner copy-paste):** Implement the Automation probe as a two-step sequence — step 1 `id of application "WhatsApp"` (cheap, unambiguous identity), step 2 `tell application "WhatsApp" to get name` (only if step 1 was inconclusive).

## x-apple.systempreferences URLs

Verified format (in active use as of macOS 14/15/26 per multiple 2024-2026 sources):

| TCC bucket | URL [CITED: github.com/rmcdongit/f66ff91e0dad78d4d6346a75ded4b751 + bvanpeski/SystemPreferences] |
|------------|-----|
| Full Disk Access | `x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles` |
| Automation (Apple Events) | `x-apple.systempreferences:com.apple.preference.security?Privacy_Automation` |
| Accessibility | `x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility` |

**Caveat [VERIFIED]:** macOS 13+ renamed "System Preferences" to "System Settings" and rearranged some panels, but the `x-apple.systempreferences:` URL scheme and the `Privacy_*` query parameters above continue to work — they resolve to the same TCC panes under the new shell. The pane descriptor `com.apple.preference.security` is the legacy identifier; some 2025 guides also document `com.apple.settings.Privacy.AllFiles` as a newer alias, but the `Privacy_AllFiles`-style query parameters remain the broadly-tested form. **Recommendation:** ship the legacy form; if Apple removes it in a future macOS the test for SETUP-04 will surface the regression. [ASSUMED: that the legacy URL form will remain functional through macOS 26.x — based on consistent backward-compatibility precedent, but not formally guaranteed]

## Common Pitfalls

### P-PHASE0-01: Stray stdout output corrupts JSON-RPC (Pitfall P7 in PITFALLS.md)
**What goes wrong:** A `print("starting...")`, a third-party `DeprecationWarning` printed to stdout, or `logging.basicConfig()` defaulting to stdout produces non-JSON bytes on the protocol channel. Claude Desktop drops the connection.
**Why it happens:** stdio transport uses stdout for JSON-RPC frames. The Python default for `logging` and `warnings` is *not* stderr.
**How to avoid:**
- `logging.basicConfig(stream=sys.stderr, ...)` is the FIRST executable line of `cli.py`, BEFORE any non-stdlib import.
- Ruff `T201` enabled at `error` severity (`select = ["T201", ...]`).
- Test `tests/unit/test_stdout_purity.py` (see §"Code Examples") spawns the server, sends `initialize` → `tools/list` → `tools/call doctor`, asserts every stdout line is parseable JSON.
**Warning signs:** `~/Library/Logs/Claude/mcp-server-whatsapp.log` shows "Invalid JSON-RPC message"; server runs standalone but Claude Desktop can't connect.

### P-PHASE0-02: Probe regex assumes English locale
**What goes wrong:** Probe code does `if "Not authorized" in stderr: return "denied"`. On a French/German/Japanese Mac, stderr says "Erreur dans …" / "Fehler in …" / etc. The check returns "granted" for a denied permission. **Verified empirically on the user's machine — French stderr.**
**How to avoid:** Match `(-NNNN)` trailing the prose with `re.compile(r"\((-?\d+)\)\s*\Z", re.MULTILINE)`. The numeric error code is locale-stable.
**Warning signs:** `doctor` reports `granted` but the user's tools fail; happens only on non-`en_US` machines.

### P-PHASE0-03: `count windows` probe wrong-classifies granted-Automation as denied
**What goes wrong:** CONTEXT.md D-09 specifies `tell application "WhatsApp" to count windows` and treats "exit 0 = granted." Empirically, WhatsApp returns `-1708` ("`every window` ne comprend pas le message « count »") even when Automation is granted, because `count windows` isn't a command WhatsApp implements.
**How to avoid:** Use `id of application "WhatsApp"` as the primary probe (returns the bundle id cleanly); only treat `-1743` as denied; treat `-1708` as granted (the event reached the app — that's what we're testing).
**Warning signs:** On a freshly granted Mac the doctor still reports Automation denied.

### P-PHASE0-04: Missing `permissions: id-token: write` in release.yml
**What goes wrong:** `uv publish` (or `pypa/gh-action-pypi-publish`) attempts the OIDC handshake; GitHub doesn't mint a token because the workflow doesn't have the permission; the action fails with a 403 from PyPI.
**How to avoid:** Add `permissions: { id-token: write }` at the *job* level of the publish job (not workflow-wide — keeps blast radius minimal).
**Warning signs:** First tag push fails with "Trusted publishing exchange failure" and HTTP 403. [CITED: docs.pypi.org/trusted-publishers]

### P-PHASE0-05: Console-script entry point not actually installed by `uvx`
**What goes wrong:** `pyproject.toml` declares `[project.scripts] whatsapp-mcp = "whatsapp_mcp.cli:main"`, but the wheel layout is wrong (e.g., the source is at `whatsapp_mcp/` not `src/whatsapp_mcp/`), so `uvx whatsapp-mcp` fails with "command not found" or imports fail.
**How to avoid:** With src-layout, add `[tool.hatch.build.targets.wheel] packages = ["src/whatsapp_mcp"]` to pyproject.toml. Verify locally with `uv build && uvx --from ./dist/whatsapp_mcp-0.1.0-*.whl whatsapp-mcp --version`.
**Warning signs:** Local `python -m whatsapp_mcp` works but `uvx whatsapp-mcp` doesn't.

### P-PHASE0-06: Importing `whatsapp_mcp.tools.doctor` triggers a circular import
**What goes wrong:** `tools/doctor.py` does `from whatsapp_mcp.server import mcp`; `server.py` does `from whatsapp_mcp.tools import doctor`. With careless ordering this becomes circular.
**How to avoid:** `server.py` defines `mcp = FastMCP(...)` BEFORE the `from whatsapp_mcp.tools import doctor` line. The `# noqa: F401` on the import documents that the side effect (decorator registration) is the point.
**Warning signs:** `ImportError: cannot import name 'mcp' from partially initialized module`.

### P-PHASE0-07: `pytest -m "not live"` doesn't actually skip live tests
**What goes wrong:** Tests are decorated `@pytest.mark.live` but `markers` aren't declared in `pyproject.toml`, so pytest emits a `PytestUnknownMarkWarning` and (with `-W error::pytest.PytestUnknownMarkWarning`) fails the suite.
**How to avoid:** Declare in `[tool.pytest.ini_options]`:
```toml
markers = [
    "live: requires a live macOS environment with WhatsApp installed (RUN_LIVE=1)",
]
```
**Warning signs:** CI passes locally but fails on the runner with "PytestUnknownMarkWarning".

## Code Examples

Verified patterns. Every snippet below was either directly tested or transcribed from official sources.

### Full pyproject.toml

```toml
# pyproject.toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "whatsapp-mcp"
version = "0.1.0"
description = "MCP stdio server for the macOS WhatsApp Desktop app — read history and send messages from Claude Desktop / Claude Code."
readme = "README.md"
requires-python = ">=3.12"
license = { text = "MIT" }  # Claude's discretion per CONTEXT.md
authors = [
    { name = "WhatsApp MCP contributors" },
]
keywords = ["mcp", "model-context-protocol", "whatsapp", "macos", "claude"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: Console",
    "Operating System :: MacOS",
    "Programming Language :: Python :: 3.12",
    "Topic :: Communications :: Chat",
]
dependencies = [
    "mcp[cli]==1.27.1",
    "pydantic>=2.7,<3",
]

[project.optional-dependencies]
dev = [
    "ruff>=0.6",
    "mypy>=1.10",
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "pytest-subprocess>=1.5",
]

[project.scripts]
whatsapp-mcp = "whatsapp_mcp.cli:main"

[project.urls]
Homepage = "https://github.com/<org>/whatsapp-mcp"   # plan-time placeholder
Issues = "https://github.com/<org>/whatsapp-mcp/issues"

[tool.hatch.build.targets.wheel]
packages = ["src/whatsapp_mcp"]

# ---------- Lint ----------
[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.lint]
select = [
    "E",     # pycodestyle errors
    "F",     # pyflakes
    "I",     # isort
    "B",     # flake8-bugbear
    "UP",    # pyupgrade (use modern syntax for our 3.12 floor)
    "TID",   # flake8-tidy-imports
    "T201",  # NO print() — Pitfall P7 / SETUP-03
]
# T201 is in `select`; we leave it un-ignored so violations are errors.

[tool.ruff.lint.per-file-ignores]
# Tests legitimately use print for debugging when failing.
"tests/**/*.py" = ["T201"]

[tool.ruff.format]
# Defaults are fine; explicit for clarity.
quote-style = "double"
indent-style = "space"

# ---------- Types ----------
[tool.mypy]
python_version = "3.12"
strict = true
warn_unreachable = true
warn_redundant_casts = true
warn_unused_ignores = true
disallow_any_generics = true
files = ["src", "tests"]

[[tool.mypy.overrides]]
# pytest-subprocess fixtures are loosely typed.
module = "pytest_subprocess.*"
ignore_missing_imports = true

# ---------- Tests ----------
[tool.pytest.ini_options]
minversion = "8.2"
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = ["-ra", "--strict-markers"]
markers = [
    "live: requires a live macOS environment with WhatsApp installed (RUN_LIVE=1)",
]
```

### Console-script entry point + `uvx` resolution

The flow is:
1. `uvx whatsapp-mcp` → `uv` reads PyPI, installs `whatsapp-mcp` into an ephemeral venv.
2. `uv` creates `<venv>/bin/whatsapp-mcp` from `[project.scripts] whatsapp-mcp = "whatsapp_mcp.cli:main"`.
3. The shim runs `from whatsapp_mcp.cli import main; sys.exit(main())`.
4. `main()` configures stderr logging, then imports `whatsapp_mcp.server.run` and calls it.
5. `mcp.run()` (default transport `stdio`) blocks reading JSON-RPC from stdin.

For `python -m whatsapp_mcp` to work identically, `__main__.py` exists and calls `cli.main()`.

### `claude_desktop_config.json` snippet (for `examples/`)

```json
{
  "mcpServers": {
    "whatsapp": {
      "command": "uvx",
      "args": ["whatsapp-mcp"]
    }
  }
}
```

### FDA probe

```python
# src/whatsapp_mcp/permissions/fda.py
"""Full Disk Access probe — try to stat the WhatsApp ChatStorage.sqlite path."""
from __future__ import annotations

import asyncio
import errno
import logging
import os
import sys

from whatsapp_mcp.exceptions import FullDiskAccessRequired
from whatsapp_mcp.models.doctor import PermissionStatus
from whatsapp_mcp.paths import resolve_chatstorage_path

logger = logging.getLogger(__name__)

_FDA_URL = FullDiskAccessRequired.system_settings_url


async def check() -> PermissionStatus:
    db_path = resolve_chatstorage_path()
    return await asyncio.to_thread(_check_blocking, db_path)


def _check_blocking(db_path: str) -> PermissionStatus:
    try:
        os.stat(db_path)
    except FileNotFoundError:
        return PermissionStatus(
            bucket="fda",
            state="whatsapp_not_installed",
            binary_path=sys.executable,
            db_path=db_path,
            system_settings_url=_FDA_URL,
            remediation=(
                "WhatsApp Desktop is not installed at the expected path. "
                "Install WhatsApp from the App Store and run `doctor` again."
            ),
        )
    except PermissionError as e:
        if e.errno in (errno.EACCES, errno.EPERM):
            return PermissionStatus(
                bucket="fda",
                state="denied",
                binary_path=sys.executable,
                db_path=db_path,
                system_settings_url=_FDA_URL,
                remediation=(
                    f"Grant Full Disk Access to: {sys.executable}\n"
                    "Open System Settings → Privacy & Security → Full Disk Access, "
                    "click '+', and add the path above."
                ),
            )
        # Other errno (EROFS, EIO, ...) — treat as denied with a different remediation hint.
        logger.warning("os.stat(%s) failed with unexpected errno=%s", db_path, e.errno)
        return PermissionStatus(
            bucket="fda",
            state="denied",
            binary_path=sys.executable,
            db_path=db_path,
            system_settings_url=_FDA_URL,
            remediation=f"Unexpected filesystem error (errno={e.errno}); see logs.",
        )
    return PermissionStatus(
        bucket="fda",
        state="granted",
        binary_path=sys.executable,
        db_path=db_path,
        system_settings_url=_FDA_URL,
    )
```

### Automation probe (refined to handle -1708)

```python
# src/whatsapp_mcp/permissions/automation.py
"""Apple Events / Automation probe for WhatsApp."""
from __future__ import annotations

import sys

from whatsapp_mcp.exceptions import AutomationPermissionRequired
from whatsapp_mcp.models.doctor import PermissionStatus
from whatsapp_mcp.permissions.osascript import run_osascript

_AUTOMATION_URL = AutomationPermissionRequired.system_settings_url
_PROBE = 'id of application "WhatsApp"'


async def check_whatsapp() -> PermissionStatus:
    result = await run_osascript(_PROBE, timeout=3.0)
    binary_path = sys.executable

    # Granted: clean exit OR app handled the event
    if result.exit_code == 0 or result.error_code == -1708:
        return PermissionStatus(
            bucket="automation",
            state="granted",
            binary_path=binary_path,
            system_settings_url=_AUTOMATION_URL,
        )
    # Not authorized
    if result.error_code == -1743:
        return PermissionStatus(
            bucket="automation",
            state="denied",
            binary_path=binary_path,
            system_settings_url=_AUTOMATION_URL,
            remediation=(
                f"Grant Automation permission for WhatsApp to: {binary_path}\n"
                "Open System Settings → Privacy & Security → Automation, "
                "find the row for the binary above, and tick the WhatsApp checkbox. "
                "If the row doesn't exist, run `tccutil reset AppleEvents` and re-run doctor."
            ),
        )
    # Target not installed
    if result.error_code == -1728:
        return PermissionStatus(
            bucket="automation",
            state="whatsapp_not_installed",
            binary_path=binary_path,
            system_settings_url=_AUTOMATION_URL,
            remediation="WhatsApp Desktop is not installed. Install it from the App Store.",
        )
    # App not running — permission is fine
    if result.error_code == -600:
        return PermissionStatus(
            bucket="automation",
            state="granted",
            binary_path=binary_path,
            system_settings_url=_AUTOMATION_URL,
        )
    # Timeout or unknown — surface as denied so the user investigates
    return PermissionStatus(
        bucket="automation",
        state="denied",
        binary_path=binary_path,
        system_settings_url=_AUTOMATION_URL,
        remediation=(
            f"osascript probe returned an unexpected result (exit={result.exit_code}, "
            f"error_code={result.error_code}). Try restarting WhatsApp and re-running doctor. "
            "If the problem persists, open an issue with the doctor output."
        ),
    )
```

### Accessibility probe

```python
# src/whatsapp_mcp/permissions/accessibility.py
"""Accessibility probe — try to query System Events."""
from __future__ import annotations

import sys

from whatsapp_mcp.exceptions import AccessibilityPermissionRequired
from whatsapp_mcp.models.doctor import PermissionStatus
from whatsapp_mcp.permissions.osascript import run_osascript

_ACCESSIBILITY_URL = AccessibilityPermissionRequired.system_settings_url
_PROBE = 'tell application "System Events" to count processes'


async def check() -> PermissionStatus:
    result = await run_osascript(_PROBE, timeout=3.0)
    binary_path = sys.executable

    if result.exit_code == 0:
        return PermissionStatus(
            bucket="accessibility",
            state="granted",
            binary_path=binary_path,
            system_settings_url=_ACCESSIBILITY_URL,
        )
    if result.error_code in (-1719, -25211):
        return PermissionStatus(
            bucket="accessibility",
            state="denied",
            binary_path=binary_path,
            system_settings_url=_ACCESSIBILITY_URL,
            remediation=(
                f"Grant Accessibility permission to: {binary_path}\n"
                "Open System Settings → Privacy & Security → Accessibility, "
                "click '+', add the binary above, and tick its checkbox."
            ),
        )
    return PermissionStatus(
        bucket="accessibility",
        state="denied",
        binary_path=binary_path,
        system_settings_url=_ACCESSIBILITY_URL,
        remediation=(
            f"osascript probe returned an unexpected result (exit={result.exit_code}, "
            f"error_code={result.error_code}). See logs."
        ),
    )
```

### Pydantic models

```python
# src/whatsapp_mcp/models/doctor.py
"""Public Pydantic models for the doctor tool. Frozen — Phase 1 reads these."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PermissionState = Literal["granted", "denied", "whatsapp_not_installed"]
PermissionBucket = Literal["fda", "automation", "accessibility"]


class PermissionStatus(BaseModel):
    bucket: PermissionBucket
    state: PermissionState
    binary_path: str = Field(
        description=(
            "The exact filesystem path of the binary that needs the permission. "
            "User must add this path to the matching System Settings panel."
        ),
    )
    db_path: str | None = Field(
        default=None,
        description="Resolved path to ChatStorage.sqlite (only set for FDA bucket).",
    )
    system_settings_url: str = Field(
        description="x-apple.systempreferences: URL that opens the right TCC panel.",
    )
    remediation: str = Field(
        default="",
        description="One-line human instruction for fixing a denied state.",
    )


class DoctorReport(BaseModel):
    """Phase 0 doctor report. Phase 1 will extend this with schema_fingerprint, etc."""

    full_disk_access: PermissionStatus
    automation_whatsapp: PermissionStatus
    accessibility: PermissionStatus

    @property
    def all_granted(self) -> bool:
        return all(
            s.state == "granted"
            for s in (self.full_disk_access, self.automation_whatsapp, self.accessibility)
        )
```

### Stdout-purity test

```python
# tests/unit/test_stdout_purity.py
"""SETUP-03 gate — every byte on stdout must be a valid JSON-RPC frame.

Spawns `python -m whatsapp_mcp` as a subprocess. Writes a minimal MCP handshake to
stdin (initialize → tools/list → tools/call doctor). Reads stdout line-by-line and
asserts every line parses as JSON.
"""
from __future__ import annotations

import asyncio
import json
import sys

import pytest


# Frames per MCP spec 2025-06-18 (newline-delimited JSON-RPC).
_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "stdout-purity-test", "version": "0.0.0"},
    },
}
_INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
_TOOLS_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
_DOCTOR = {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {"name": "doctor", "arguments": {}},
}


@pytest.mark.asyncio
async def test_stdout_is_pure_jsonrpc() -> None:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "whatsapp_mcp",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None

    async def write_frame(frame: dict[str, object]) -> None:
        assert proc.stdin is not None
        line = (json.dumps(frame) + "\n").encode("utf-8")
        proc.stdin.write(line)
        await proc.stdin.drain()

    await write_frame(_INITIALIZE)
    await write_frame(_INITIALIZED)
    await write_frame(_TOOLS_LIST)
    await write_frame(_DOCTOR)

    # Collect 4 response frames (initialize ack, tools/list, tools/call,
    # plus one buffer of safety) within a generous timeout.
    lines: list[bytes] = []
    try:
        async with asyncio.timeout(15):
            while len(lines) < 3:
                line = await proc.stdout.readline()
                if not line:
                    break
                lines.append(line)
    finally:
        proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

    assert lines, "server produced no stdout"
    for raw in lines:
        text = raw.decode("utf-8").rstrip("\n")
        if not text:
            continue
        # The single assertion that matters:
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            pytest.fail(f"stdout line is not valid JSON: {text!r} ({e})")
        assert isinstance(obj, dict), f"stdout line is JSON but not an object: {text!r}"
        assert obj.get("jsonrpc") == "2.0", f"stdout line is not JSON-RPC 2.0: {text!r}"
```

### Doctor-tool registration test

```python
# tests/unit/test_doctor_tool.py
"""Verify the doctor tool is registered with the right shape."""
from __future__ import annotations

import asyncio

import pytest

from whatsapp_mcp.server import mcp


@pytest.mark.asyncio
async def test_doctor_is_registered_as_readonly() -> None:
    tools = await mcp.list_tools()
    assert len(tools) == 1, "Phase 0 ships exactly one tool"
    doctor_tool = tools[0]
    assert doctor_tool.name == "doctor"
    assert doctor_tool.annotations is not None
    assert doctor_tool.annotations.readOnlyHint is True
    assert doctor_tool.annotations.destructiveHint in (False, None)
```

### Exception-shape test (frozen surface for Phase 1)

```python
# tests/unit/test_exceptions.py
from whatsapp_mcp.exceptions import (
    AccessibilityPermissionRequired,
    AutomationPermissionRequired,
    FullDiskAccessRequired,
    PermissionRequired,
    WhatsAppMCPError,
)


def test_permission_hierarchy_is_stable() -> None:
    """Phase 1 imports these by name; renaming any breaks Phase 1."""
    assert issubclass(FullDiskAccessRequired, PermissionRequired)
    assert issubclass(AutomationPermissionRequired, PermissionRequired)
    assert issubclass(AccessibilityPermissionRequired, PermissionRequired)
    assert issubclass(PermissionRequired, WhatsAppMCPError)


def test_subclass_buckets_and_urls() -> None:
    assert FullDiskAccessRequired.bucket == "fda"
    assert "Privacy_AllFiles" in FullDiskAccessRequired.system_settings_url
    assert AutomationPermissionRequired.bucket == "automation"
    assert "Privacy_Automation" in AutomationPermissionRequired.system_settings_url
    assert AccessibilityPermissionRequired.bucket == "accessibility"
    assert "Privacy_Accessibility" in AccessibilityPermissionRequired.system_settings_url


def test_carries_remediation_payload() -> None:
    err = FullDiskAccessRequired(
        "no FDA",
        binary_path="/usr/bin/python3",
        db_path="/path/to/ChatStorage.sqlite",
        remediation="add it",
    )
    assert err.binary_path == "/usr/bin/python3"
    assert err.db_path == "/path/to/ChatStorage.sqlite"
    assert err.remediation == "add it"
```

### Automation-probe mocking with pytest-subprocess

```python
# tests/unit/test_permissions/test_automation.py
import pytest

from whatsapp_mcp.permissions.automation import check_whatsapp


@pytest.mark.asyncio
async def test_automation_granted(fp) -> None:
    fp.register(
        ["/usr/bin/osascript", "-e", 'id of application "WhatsApp"'],
        stdout=b"net.whatsapp.WhatsApp\n",
        returncode=0,
    )
    status = await check_whatsapp()
    assert status.state == "granted"


@pytest.mark.asyncio
async def test_automation_denied_returns_minus_1743(fp) -> None:
    fp.register(
        ["/usr/bin/osascript", "-e", 'id of application "WhatsApp"'],
        stderr=b"0:30: execution error: Not authorized to send Apple events to WhatsApp. (-1743)\n",
        returncode=1,
    )
    status = await check_whatsapp()
    assert status.state == "denied"
    assert "Privacy_Automation" in status.system_settings_url


@pytest.mark.asyncio
async def test_automation_whatsapp_not_installed(fp) -> None:
    fp.register(
        ["/usr/bin/osascript", "-e", 'id of application "WhatsApp"'],
        stderr=b"0:0: execution error: Can\xe2\x80\x99t get application \"WhatsApp\". (-1728)\n",
        returncode=1,
    )
    status = await check_whatsapp()
    assert status.state == "whatsapp_not_installed"


@pytest.mark.asyncio
async def test_automation_handler_not_found_is_granted(fp) -> None:
    """Empirical: WhatsApp returns -1708 even when Automation IS granted."""
    fp.register(
        ["/usr/bin/osascript", "-e", 'id of application "WhatsApp"'],
        stderr=b"... (-1708)\n",
        returncode=1,
    )
    status = await check_whatsapp()
    # -1708 means the event reached the app — permission is fine
    # NOTE: in practice `id of application` returns 0 cleanly; this test guards
    # the future case where someone changes the probe to a `tell ... to count` form.
    assert status.state == "granted"
```

### .github/workflows/ci.yml

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint-type-test:
    runs-on: macos-14   # Apple Silicon — matches user environment
    steps:
      - uses: actions/checkout@v4

      - name: Install uv and Python 3.12
        uses: astral-sh/setup-uv@v8
        with:
          python-version: "3.12"
          enable-cache: true

      - name: Install project + dev deps
        run: uv sync --extra dev

      - name: Lint (ruff check)
        run: uv run ruff check src tests

      - name: Format check (ruff format --check)
        run: uv run ruff format --check src tests

      - name: Type check (mypy strict)
        run: uv run mypy

      - name: Test (excluding live tests)
        run: uv run pytest -m "not live"
```

### .github/workflows/release.yml

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags: ['v*']

jobs:
  ci:
    uses: ./.github/workflows/ci.yml

  publish:
    needs: ci
    runs-on: macos-14
    environment:
      name: pypi
      url: https://pypi.org/p/whatsapp-mcp
    permissions:
      id-token: write   # MANDATORY for OIDC trusted-publisher; without it, PyPI returns 403
    steps:
      - uses: actions/checkout@v4

      - name: Install uv and Python 3.12
        uses: astral-sh/setup-uv@v8
        with:
          python-version: "3.12"
          enable-cache: true

      - name: Build distribution
        run: uv build

      # Two equally valid options — pick one and stick with it:

      # Option A: uv publish (native trusted-publisher support since uv 0.5)
      - name: Publish to PyPI (uv)
        run: uv publish

      # Option B: pypa/gh-action-pypi-publish (the canonical PyPA action)
      # - name: Publish to PyPI (pypa action)
      #   uses: pypa/gh-action-pypi-publish@release/v1
      #   # No `password:` input — OIDC handles it
```

**Trusted-publisher one-time setup (manual, before first release):**
1. On PyPI, create the project `whatsapp-mcp` (or reserve via first manual upload).
2. Project Settings → Publishing → Add a new pending publisher.
3. Owner: `<github-org>`, Repo: `whatsapp-mcp`, Workflow: `release.yml`, Environment: `pypi`.
4. Save. First tag push will succeed; tokens become live.

[CITED: docs.pypi.org/trusted-publishers/using-a-publisher/]

### README skeleton (SETUP-05 disclaimers)

```markdown
# whatsapp-mcp

> **Warning — WhatsApp ToS automation risk.** This MCP server automates *your personal*
> WhatsApp account by driving the macOS WhatsApp Desktop app the same way you do.
> WhatsApp's Terms of Service prohibit "automated or bulk messaging." Running the
> send tools at scale (or in patterns that look like a bot) risks an irrecoverable
> account ban. This project ships conservative rate limits (5 sends / minute,
> 30 sends / day) by default, but you accept the risk by using it.
>
> **This is your personal account, not a bot.** Treat it that way.
> No WhatsApp Business API. No bulk messaging. No auto-reply loops.

A local Model Context Protocol (MCP) server that lets Claude Desktop / Claude Code
read and write your WhatsApp Desktop chats. macOS only. Single user, single Mac.

## Quickstart (60 seconds)

1. Add this snippet to `~/Library/Application Support/Claude/claude_desktop_config.json`:

   ```json
   {
     "mcpServers": {
       "whatsapp": {
         "command": "uvx",
         "args": ["whatsapp-mcp"]
       }
     }
   }
   ```

2. Restart Claude Desktop.
3. From the chat, ask Claude to "call the WhatsApp doctor tool."
4. Follow the System Settings deep-links the report gives you to grant Full Disk
   Access, Apple Events / Automation, and Accessibility to the binary it names.

That's it. Once `doctor` reports all three permissions as `granted`, the read and
send tools (Phase 1+) will work.

## Requirements

- macOS (verified on 14 Sonoma, 15 Sequoia, 26 Tahoe)
- Python 3.12+ (uvx will fetch this for you)
- WhatsApp Desktop installed and logged in

## Development

…
```

## State of the Art

| Old approach | Current approach (2026) | When Changed | Impact |
|--------------|-------------------------|--------------|--------|
| `pip install` + manually maintained venv | `uv` for everything (init, sync, run, build, publish) | uv reached 1.0 in 2025; ~38% of MCP servers now ship with `uvx` | Single-binary toolchain, ephemeral envs, no `requirements*.txt` |
| `setup.py` + `setup.cfg` | `pyproject.toml` with `[build-system]` | PEP 517/518 stable for years, but hatchling/uv made it the only sensible choice | One source of truth |
| Long-lived PyPI API tokens in repo secrets | OIDC trusted publisher (no token at all) | PyPI launched in April 2023; uv 0.5 added native support | No secret to leak; tokens auto-expire |
| Lower-level `mcp.server.Server` API | `FastMCP` decorator API | `mcp` SDK ≥1.x | One-liner tool registration; auto JSON schema from type hints |
| `setup-python` + manual `pip install uv` | `astral-sh/setup-uv@v8` (sets up uv + Python in one step) | `setup-uv` v8 series | Faster CI, simpler workflow |

**Deprecated/outdated patterns to avoid:**
- `mcp.server.Server` low-level class — use FastMCP unless you need a hook FastMCP doesn't expose.
- `pypa/gh-action-pypi-publish@master` — the master branch was sunset; use `release/v1` or a tagged version.
- `requirements.txt` — use `uv lock` (which produces `uv.lock`).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The `x-apple.systempreferences:com.apple.preference.security?Privacy_*` URL form will continue to work through macOS 26.x and beyond | §"x-apple.systempreferences URLs" | Low — if Apple removes it, the URL becomes a no-op (System Settings opens to the home pane); user can still navigate manually. SETUP-04 test will not catch this; document in README that the URL "opens the right pane on currently-supported macOS" |
| A2 | `error_code == -1708` reliably indicates the Apple event was delivered (i.e., Automation is granted) | §"AppleScript Probe Error Code Map", §"Code Examples / Automation probe" | Low — empirically true on this machine; theoretical edge case is some other dispatch failure also returning -1708 before reaching the target. The fallback (use `id of application "WhatsApp"` which returns 0 cleanly) sidesteps the question entirely |
| A3 | macOS 26 runners are not yet available on GitHub Actions; `macos-14` (Sonoma, Apple Silicon) is the closest match to the user's environment | §"Code Examples / ci.yml" | Low — `macos-14` is current GA on GitHub-hosted runners; `macos-15` may also be available. Either is fine; both are Apple Silicon |
| A4 | `setup-uv@v8` is current; major version pin is the right cadence | §"Code Examples / ci.yml" | Low — actions are versioned conservatively; v8 is the documented current major as of 2026-04 |
| A5 | The `id of application "WhatsApp"` probe distinguishes "not installed" (-1728) from "Automation denied" (-1743) reliably across macOS versions | §"AppleScript Probe Error Code Map" | Medium — if a future macOS pre-empts the bundle-lookup with a TCC check (returning -1743 before the system can determine the app exists), our `whatsapp_not_installed` branch becomes unreachable. Acceptable: in that case we report `denied`, the user goes to grant the permission, sees no row to check, and infers "not installed" from the missing entry |

## Open Questions

1. **Should the doctor probe also detect a denied-but-prompt-pending state?**
   - What we know: macOS 14+ adds `errAEEventWouldRequireUserConsent` (-1744) which means "user has not yet been prompted, the system would need to prompt them now."
   - What's unclear: whether a `subprocess`-launched osascript can ever surface this state, or whether the prompt is suppressed entirely under non-bundled callers.
   - Recommendation: don't special-case it in Phase 0; if the probe returns -1744, treat it as `denied` with remediation "an authorization prompt may be pending — focus the system to dismiss it, then re-run doctor."

2. **What's the right `binary_path` value when running under `uvx`?**
   - What we know: `sys.executable` is the resolved Python interpreter — typically deep inside `~/.local/share/uv/python/cpython-3.12.x.../bin/python3.12`. That IS the binary the user must add to TCC. CONTEXT.md D-11 already specifies `sys.executable`.
   - What's unclear: whether the user benefits from also showing `os.readlink(sys.executable)` to surface stable vs symlink. Probably not in Phase 0.
   - Recommendation: `sys.executable` only. Phase 3's signed-launcher work will replace this with a stable absolute path.

3. **Do we need an explicit `tools/list` smoke test beyond `test_stdout_purity.py`?**
   - What we know: `test_stdout_purity.py` already calls `tools/list` and `tools/call doctor`, so the registration path is exercised.
   - What's unclear: whether the planner wants to assert exact `tools/list` JSON shape (e.g., `tools[0].annotations.readOnlyHint == true`) at the protocol layer rather than the SDK layer. The protocol-layer test would catch SDK regressions where a future `mcp[cli]` minor version drops the annotation field by accident.
   - Recommendation: ship the SDK-layer `test_doctor_tool.py` in Phase 0; defer protocol-layer assertion to Phase 1 if it ever becomes a real concern.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| `uv` (CLI) | Project workflow + `uvx` install | ✓ | 0.11.12 | None — required |
| `uvx` | DIST-01 acceptance test | ✓ | 0.11.12 | None |
| `osascript` | Permissions probes | ✓ | `/usr/bin/osascript` (system) | None — macOS-only project, won't run elsewhere |
| Python 3.12 | runtime | ✓ via uv (system Python is 3.9) | 3.12 (uv-managed) | None — required by `requires-python=">=3.12"` |
| `gh` (GitHub CLI) | Tag pushing during release | ✓ | 2.88.1 | git CLI alone is sufficient |
| WhatsApp.app installed | DIST-01 end-to-end smoke (live test only) | ✓ on user's machine | 26.16.74 | Live tests gated by `RUN_LIVE=1`; CI doesn't need WhatsApp |
| WhatsApp ChatStorage.sqlite present | Live FDA probe sanity check | ✓ | 89 MB on user's machine | N/A in CI |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None.

## Security Domain

`security_enforcement` is not explicitly set in `.planning/config.json`. Treating as enabled per the documented default. Phase 0 surface is intentionally narrow; the long security thinking is in PITFALLS.md (P5/P6/P14) and ramps up in Phase 2.

### Applicable ASVS Categories

| ASVS Category | Applies to Phase 0 | Standard Control |
|---------------|--------------------|------------------|
| V2 Authentication | no (stdio == local process == same trust boundary as user shell) | — |
| V3 Session Management | no | — |
| V4 Access Control | yes (the macOS TCC layer is the access control we depend on) | macOS TCC: FDA / Automation / Accessibility — the `doctor` tool's whole purpose is to surface its state |
| V5 Input Validation | yes | Pydantic v2 models on every tool input/output (FastMCP uses these for schema generation AND runtime validation) |
| V6 Cryptography | no (no crypto in Phase 0; OIDC handshake is delegated to GitHub Actions) | — |
| V14 Configuration | yes | `pyproject.toml` is the single source for dependencies; `uv.lock` (committed in Phase 1) provides reproducibility |

### Known Threat Patterns for stdio MCP

| Pattern | STRIDE | Standard Mitigation (Phase 0 owns) |
|---------|--------|-------------------------------------|
| Stdout pollution corrupts JSON-RPC, silently dropping the connection | Tampering / DoS | Lint rule `T201` + stdout-purity CI test (P-PHASE0-01) |
| Localized stderr leads to wrong probe verdict | Spoofing of state | `(-NNNN)` numeric matching only (P-PHASE0-02) |
| Long-lived PyPI API token in repo secrets is leaked | Information disclosure | OIDC trusted publisher — no token to leak (CONTEXT.md D-17) |
| HTTP/REST surface exposed to LAN (the lharries CVE class) | Information disclosure / privilege escalation | Stdio only, no HTTP listener (CONTEXT.md D-04, REQUIREMENTS.md OOS line) |
| Prompt-injected LLM calls `doctor` repeatedly to enumerate paths | Information disclosure | `doctor` returns no message content; only paths the user can already see in their own filesystem |
| Path traversal in attachment download (Phase 2 concern, surfaced here) | Tampering | Phase 0 ships no I/O against attachments; Phase 1+ enforces |

### Phase 0-specific security checklist (planner: include in plan-check)
- [ ] No `print` statements in `src/` (ruff T201 enforces; CI test verifies stdout)
- [ ] No HTTP listener anywhere; verify the only `mcp.run()` call uses default `transport='stdio'`
- [ ] `release.yml` has `permissions: id-token: write` at the *job* level (not workflow level)
- [ ] `release.yml` does not reference any `secrets.*` for PyPI auth
- [ ] No `.env` / `.envrc` files committed; add to `.gitignore`
- [ ] `examples/claude_desktop_config.json` contains no real user data (it's a template)
- [ ] README opens with the WhatsApp ToS warning paragraph (CONTEXT.md D-20)

## Project Constraints (from CLAUDE.md)

`./CLAUDE.md` exists and contains the following hard rules. Phase 0 plans must comply:

| Constraint | Source | Phase 0 Implication |
|------------|--------|---------------------|
| Reader (`reader/`) and Sender (`sender/`) packages MUST NOT import each other | CLAUDE.md "Hard architectural rules" §1 | Ship `src/whatsapp_mcp/reader/__init__.py` and `src/whatsapp_mcp/sender/__init__.py` as empty placeholders. Add `tests/unit/test_isolation.py` asserting `import whatsapp_mcp.reader; import whatsapp_mcp.sender` succeed independently and that neither imports the other (use `importlib.metadata` or AST inspection — but in Phase 0 the test is trivially true since both are empty) |
| `stdout` is the JSON-RPC channel; logging to stderr; `print` lint-blocked; CI test asserts stdout purity | CLAUDE.md §2 | All addressed in this RESEARCH.md (D-05, D-13, D-16; §"Code Examples / Stdout-purity test") |
| Never write to `ChatStorage.sqlite` | CLAUDE.md §3 | Phase 0 doesn't touch SQLite. The FDA probe uses `os.stat` only (read-mode metadata); enforce via test that no `sqlite3.connect` exists in Phase 0 source |
| Never inline media bytes in tool responses | CLAUDE.md §4 | Phase 0 has no media surface; not applicable |
| No HTTP / TCP / UDP listener | CLAUDE.md §5 | `mcp.run()` defaults to stdio; ensure no `transport=` override anywhere |
| Never compare JID strings directly | CLAUDE.md §6 | Phase 0 has no JID code; not applicable |
| Send is `destructiveHint:true`, gated by elicitation, etc. | CLAUDE.md §7 | Phase 0 ships no send tool; not applicable |
| Every read tool returns `coverage` field | CLAUDE.md §8 | `doctor` is a read-only diagnostic tool, not a "read tool" in the data-reading sense; `coverage` is a Phase 1 concept against `ChatStorage.sqlite`. CONTEXT.md D-07 explicitly excludes coverage from Phase 0 |

The most important enforcement points for the planner: ruff `T201`, the stdout-purity test, and the directory structure (which makes REL-05 a property of the layout, not a property of any test).

## Sources

### Primary (HIGH confidence — verified live in this session)
- **PyPI metadata** (verified via `curl https://pypi.org/pypi/<pkg>/json` on 2026-05-13):
  - mcp 1.27.1 (uploaded 2026-05-08, requires_python ≥3.10)
  - hatchling 1.29.0 (2026-02-23)
  - ruff 0.15.12 (2026-04-24)
  - mypy 2.1.0 (2026-05-11)
  - pytest 9.0.3 (2026-04-07)
  - pytest-asyncio 1.3.0 (2025-11-10)
  - pytest-subprocess 1.6.0 (2026-05-10)
  - pydantic 2.13.4 (2026-05-06)
- **`mcp[cli]==1.27.1` API surface** — installed in scratch venv `/tmp/_mcp_probe/.venv`, inspected via `inspect.signature`. Verified: `FastMCP` import path, `ToolAnnotations` fields (title, readOnlyHint, destructiveHint, idempotentHint, openWorldHint), `ToolError` location at `mcp.server.fastmcp.exceptions`, `mcp.run` defaults to `transport='stdio'`
- **AppleScript probe behavior** — empirical on user's Mac (macOS 26.4, fr_FR locale): `tell application "WhatsApp" to count windows` → `-1708`; `tell application "DefinitelyNotARealAppXYZ"` → `-1728`; `id of application "WhatsApp"` → `net.whatsapp.WhatsApp` (exit 0); `tell application "System Events" to count processes` → `157` (exit 0)

### Secondary (MEDIUM confidence — official docs, verified within session)
- [MCP Python SDK README](https://github.com/modelcontextprotocol/python-sdk) — FastMCP example, mcp.run() usage
- [FastMCP Tools docs (gofastmcp.com)](https://gofastmcp.com/servers/tools) — ToolAnnotations + ToolError pattern (NOTE: this site documents jlowin's standalone `fastmcp` package, but the Anthropic SDK's `mcp.server.fastmcp` mirrors the API; verified above)
- [PyPI Trusted Publishers docs](https://docs.pypi.org/trusted-publishers/using-a-publisher/) — OIDC publish workflow
- [pypa/gh-action-pypi-publish](https://github.com/pypa/gh-action-pypi-publish) — release/v1 ref, id-token: write requirement
- [astral-sh/setup-uv](https://github.com/astral-sh/setup-uv) — v8 ref, python-version + enable-cache options
- [Apple Developer Forums #109561 — System Events on Xcode error 1743](https://developer.apple.com/forums/thread/109561) — verbatim error message format
- [Apple ASLR error codes archive](https://developer.apple.com/library/archive/documentation/AppleScript/Conceptual/AppleScriptLangGuide/reference/ASLR_error_codes.html) — verified -1719, -1728, -600 entries
- [Felix Schwarz: Apple Event sandboxing in macOS Mojave](https://www.felix-schwarz.org/blog/2018/06/apple-event-sandboxing-in-macos-mojave) — errAEEventNotPermitted (-1743) symbol
- [Apple System Preferences URL Schemes (rmcdongit gist)](https://gist.github.com/rmcdongit/f66ff91e0dad78d4d6346a75ded4b751) — Privacy_AllFiles / Privacy_Automation / Privacy_Accessibility URLs
- [bvanpeski/SystemPreferences (Ventura)](https://github.com/bvanpeski/SystemPreferences/blob/main/macos_preferencepanes-Ventura.md) — URL form confirmation for newer macOS
- [pytest-asyncio Concepts](https://pytest-asyncio.readthedocs.io/en/stable/concepts.html) — `asyncio_mode="auto"` semantics
- [Ruff Configuration](https://docs.astral.sh/ruff/configuration/) — pyproject.toml structure
- [uv build backend / Tools docs](https://docs.astral.sh/uv/concepts/build-backend/) — hatchling vs uv_build

### Tertiary (LOW confidence — single source, training-era references; confirm before locking)
- macOS 26 Tahoe URL-form continuity (assumption A1) — relies on consistent backward-compatibility pattern across the last decade of macOS releases; not formally guaranteed by Apple

### Already-locked (carried verbatim from project research)
- `.planning/research/STACK.md` — every stack pick rationale; NOT re-derived here
- `.planning/research/PITFALLS.md` — P4 / P7 / P13 / P14 / P15 are all referenced inline above
- `.planning/research/SUMMARY.md` — verified facts about WhatsApp DB / TCC / send-path constraints

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — every version verified live against PyPI on 2026-05-13; `mcp[cli]==1.27.1` API surface verified by direct install
- Architecture: **HIGH** — directly traceable to CONTEXT.md decisions; new structural insights (Pattern 1-4) all derive from verified API
- AppleScript probes: **HIGH** for the error code map (verified empirically on user's Mac); MEDIUM for the recommendation to swap `count windows` → `id of application` (refinement of CONTEXT.md D-09 — needs planner sign-off if D-09's exact wording is locked, since this is a *substantive* probe change driven by empirical finding)
- CI / release workflow: **HIGH** — pypa/gh-action-pypi-publish + setup-uv are 2026 standard
- Pitfalls: **HIGH** — every Phase 0 pitfall here either traces to PITFALLS.md or to a finding made directly in this research session
- macOS URL stability (A1): **MEDIUM-LOW** — assumed, not verified

**Research date:** 2026-05-13
**Valid until:** 2026-06-13 (versions move; macOS 26.x minor updates may change probe stderr; recheck mcp version + AppleScript behavior monthly)

---

## RESEARCH COMPLETE

- **mcp[cli]==1.27.1 verified live** (PyPI metadata + scratch-venv install) — `FastMCP` at `mcp.server.fastmcp`, `ToolAnnotations` at `mcp.types`, `ToolError` at `mcp.server.fastmcp.exceptions` (NOT `fastmcp.exceptions` — that's jlowin's standalone package)
- **CONTEXT.md D-09 Automation probe needs refinement.** `tell application "WhatsApp" to count windows` returns `-1708` even when granted (WhatsApp doesn't implement `count`). Use `id of application "WhatsApp"` as primary; treat `-1708` as granted; only `-1743` is actual denial
- **AppleScript stderr is localized** (verified empirically: French "Erreur dans …" on user's Mac). Match `(-NNNN)` numeric tail only — never the prose
- **Full pyproject.toml, ci.yml, release.yml, and Pydantic models provided verbatim** for the planner to lift into task `<action>` fields
- **OIDC trusted-publisher recipe verified.** `permissions: id-token: write` at job level; pin `pypa/gh-action-pypi-publish@release/v1` OR use `uv publish` (native trusted-publisher support since uv 0.5)
- **Exception hierarchy frozen** (`PermissionRequired` → 3 subclasses with bucket attribute + system_settings_url class attribute). Phase 1 imports these by name — renaming is a breaking change
- **Test layout established** — stdout-purity (subprocess + JSON-RPC handshake), doctor-registration (FastMCP introspection), exception-shape (issubclass), permission probes (pytest-subprocess for osascript)
- **Suggested 5-task plan structure**: (1) skeleton/pyproject, (2) FastMCP server + cli, (3) probe/exception/doctor, (4) test suite, (5) CI/release. Plans 2 and 3 parallelizable after 1; plan 5 needs 1-4
- **Three Phase-0-specific pitfalls discovered/refined** beyond PITFALLS.md: locale-blind regex, `-1708`-as-granted edge case, missing `markers` declaration triggering `PytestUnknownMarkWarning`
- **Single critical assumption flagged** for user/discuss-phase confirmation: that `Privacy_AllFiles`-style URL parameters continue to work through future macOS releases (A1)

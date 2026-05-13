"""MCP server entry point for whatsapp-mcp.

Stdio-only FastMCP server. Plan 02 lands the protocol scaffolding (FastMCP
instance + ``run()`` dispatcher) with **zero registered tools**; Plan 03 will
register the ``doctor`` tool by appending a single tool-import line below.

Hard architectural rules carried from CLAUDE.md and CONTEXT.md D-04 / D-05:

- ``logging.basicConfig(stream=sys.stderr, ...)`` is the FIRST executable
  statement in this module, BEFORE any third-party import (notably
  ``mcp.server.fastmcp``). The post-``basicConfig`` imports carry
  ``# noqa: E402`` because Ruff's E402 forbids module-level imports after a
  non-import statement — but D-05 mandates exactly that ordering as the
  P-PHASE0-01 (stray-stdout) mitigation, so the noqa is correct.
- The FastMCP import path is ``from mcp.server.fastmcp import FastMCP`` —
  NEVER ``from fastmcp import ...`` (a different distribution; not in our
  dependency set; would ``ModuleNotFoundError`` on a fresh install).
- ``mcp.run()`` is called with no arguments. Stdio is the default transport;
  passing any explicit transport keyword here would open the door to the
  HTTP/SSE anti-feature explicitly forbidden by CLAUDE.md hard rule #5.
- ``mcp = FastMCP(...)`` is instantiated at module scope BEFORE the tool
  registration import below; the tool module imports ``mcp`` from this file,
  so this top-down ordering is the P-PHASE0-06 circular-import safety net.

``read_only_mode`` is a module-level boolean set by ``cli.main()`` BEFORE
the lazy ``from whatsapp_mcp.server import run`` import resolves — because
the tool-registration side-effect imports execute at server module import
time, ``cli.main`` must assign the flag prior to that import (Plan 01-03
wires this; Phase 2 will gate its send tool import on
``if not read_only_mode:``). Phase 1 ships zero send tools, so the flag
is consulted only by Phase 2's ``send_message`` registration and by unit
tests that assert tool-listing behavior. Read tools always carry
``readOnlyHint=True`` regardless of the flag.
"""

from __future__ import annotations

import logging
import sys

# CRITICAL: configure logging to stderr BEFORE any import that may log.
# This is the P-PHASE0-01 mitigation — stdout is the JSON-RPC channel and a
# single byte of non-JSON on stdout breaks Claude Desktop's connection.
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp: FastMCP = FastMCP("whatsapp-mcp")

# Module-level flag set by cli.main() BEFORE the tool-registration imports
# below execute. Default True is the v0.1 carry-over (STATE.md §Carry-overs);
# Phase 2 will wrap its send_message tool import in `if not read_only_mode:`.
# Phase 1 read tools always carry `readOnlyHint=True` regardless of this flag.
read_only_mode: bool = True

from whatsapp_mcp.tools import doctor as _doctor  # noqa: E402, F401

# --- Plan 01-04 tool import insertion point ---
# Plan 01-04 will append 7 read tools below this marker (all unconditionally
# registered; readOnlyHint=True is intrinsic to the read tools themselves).
# Phase 2 will append its `if not read_only_mode:` send-tool import block
# AFTER the Plan 01-04 read tools.


def run() -> None:
    """Start the stdio JSON-RPC loop.

    Stdio is the default; do NOT pass any explicit transport keyword here —
    that would risk introducing HTTP/SSE, which CLAUDE.md hard rule #5
    forbids (the ``lharries/whatsapp-mcp`` HTTP path-traversal CVE class).
    """
    mcp.run()

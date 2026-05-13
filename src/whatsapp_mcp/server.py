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

from whatsapp_mcp.tools import doctor as _doctor  # noqa: E402, F401


def run() -> None:
    """Start the stdio JSON-RPC loop.

    Stdio is the default; do NOT pass any explicit transport keyword here —
    that would risk introducing HTTP/SSE, which CLAUDE.md hard rule #5
    forbids (the ``lharries/whatsapp-mcp`` HTTP path-traversal CVE class).
    """
    mcp.run()

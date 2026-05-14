"""MCP server entry point for whatsapp-desktop-mcp.

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
the lazy ``from whatsapp_desktop_mcp.server import run`` import resolves — because
the tool-registration side-effect imports execute at server module import
time, ``cli.main`` must assign the flag prior to that import (Plan 01-03
wires this; Phase 2 will gate its send tool import on
``if not read_only_mode:``). Phase 1 ships zero send tools, so the flag
is consulted only by Phase 2's ``send_message`` registration and by unit
tests that assert tool-listing behavior. Read tools always carry
``readOnlyHint=True`` regardless of the flag.

Phase 1 ships 7 additional read tools registered via the side-effect
import block below the existing ``doctor`` import. The block is
alphabetized so ``tools/list`` output is byte-stable across Phase 1
(``doctor`` first per the Phase 0 import, then ``extract_recent``,
``get_chat_metadata``, ``get_message_context``, ``list_chats``,
``read_chat``, ``search_contacts``, ``search_messages``). Each tool
advertises ``meta={"anthropic/maxResultSizeChars": 60000}`` (READ-09
+ W1 lock; ``doctor`` carries the same annotation for uniform contract).

Plan 02-03 appends a single read-only-gated import block immediately
AFTER the Plan 01-04 read-tool block. The gated import is structurally
tied to the ``read_only_mode`` module flag set by ``cli.main``; when
the flag is True (the v0.1 default), the gated import never runs and
``mcp.list_tools()`` advertises only the 8 Phase 0/1 tools
(SETUP-06 satisfied). When the user launches with ``--no-read-only``,
the CLI sets the flag to False before this module's load and the
side-effect import triggers the ``@mcp.tool`` decoration on
``tools/send_message`` — bringing the total tool count to 9.
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

mcp: FastMCP = FastMCP("whatsapp-desktop-mcp")

# Module-level flag set by cli.main() BEFORE the tool-registration imports
# below execute. Default True is the v0.1 carry-over (STATE.md §Carry-overs);
# Phase 2 will wrap its send_message tool import in `if not read_only_mode:`.
# Phase 1 read tools always carry `readOnlyHint=True` regardless of this flag.
read_only_mode: bool = True

# Phase 3 D-29: dispatch flag for the search_messages FTS5 sidecar
# (CONTEXT.md D-12..D-18). Mirrors `read_only_mode` mechanics — set by
# cli.main BEFORE tools/search_messages.py is imported via the read-tool
# registration block below; the tool body inspects `server.fts5_mode` at
# call time (NOT at import time — see W-4 lesson, Phase 1: live module
# attribute access via `from whatsapp_desktop_mcp import server; server.fts5_mode`
# rather than `from whatsapp_desktop_mcp.server import fts5_mode` which would bind
# the value at import time and miss the cli mutation). Allowed values:
# "auto" (default — use FTS5 if the sidecar exists, else fall back to LIKE),
# "force" (always FTS5; lazy-build the sidecar if absent), or
# "disable" (always LIKE; Phase 1 v0.1 behavior).
fts5_mode: str = "auto"

from whatsapp_desktop_mcp.tools import doctor as _doctor  # noqa: E402, F401

# --- Plan 01-04 read-tool registration block (alphabetized) ---
# Each import has the side effect of executing the module's
# ``@mcp.tool(...)`` decorator at import time, which registers the tool
# with the FastMCP instance above. The ``as _<name>`` aliasing keeps the
# imports referenced for the linter, and the inline noqa pragma on each
# line silences both the late-import (E402) and unused-name (F401) rules
# because these imports must follow the ``logging.basicConfig`` block
# above (the P-PHASE0-01 stdout-purity mitigation mandates that
# ordering). Phase 2 will append its ``if not read_only_mode:`` send-tool
# import block AFTER this read-tool block.
from whatsapp_desktop_mcp.tools import extract_recent as _extract_recent  # noqa: E402, F401
from whatsapp_desktop_mcp.tools import get_chat_metadata as _get_chat_metadata  # noqa: E402, F401
from whatsapp_desktop_mcp.tools import (  # noqa: E402
    get_message_context as _get_message_context,  # noqa: F401
)
from whatsapp_desktop_mcp.tools import list_chats as _list_chats  # noqa: E402, F401
from whatsapp_desktop_mcp.tools import read_chat as _read_chat  # noqa: E402, F401
from whatsapp_desktop_mcp.tools import search_contacts as _search_contacts  # noqa: E402, F401
from whatsapp_desktop_mcp.tools import search_messages as _search_messages  # noqa: E402, F401

# --- Plan 02-03 send-tool registration (read-only-gated) ---
# SETUP-06 / D-19: send tools are registered ONLY when the server was
# started with --no-read-only. Plan 01-03 ships read_only_mode default=True
# (v0.1 conservative); the CLI sets read_only_mode BEFORE this server
# module loads, so the `if not read_only_mode:` condition reflects the
# user's choice. The side-effect import inside the if-block triggers
# the @mcp.tool decoration on tools/send_message.py at module-load
# time. When read_only_mode is True, mcp.list_tools() returns the
# 8 Phase 0/1 tools and NEVER advertises send_message —
# defense-in-depth on top of the runtime ReadOnlyMode check inside
# the tool body itself (D-19).
if not read_only_mode:
    from whatsapp_desktop_mcp.tools import send_message as _send_message  # noqa: E402, F401


def run() -> None:
    """Start the stdio JSON-RPC loop.

    Stdio is the default; do NOT pass any explicit transport keyword here —
    that would risk introducing HTTP/SSE, which CLAUDE.md hard rule #5
    forbids (the ``lharries/whatsapp-desktop-mcp`` HTTP path-traversal CVE class).
    """
    mcp.run()

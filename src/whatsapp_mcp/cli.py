"""Console-script entry point for ``whatsapp-mcp``.

Resolved by both:

- ``whatsapp-mcp`` (PyPI console script — ``[project.scripts] whatsapp-mcp =
  "whatsapp_mcp.cli:main"`` in ``pyproject.toml``).
- ``python -m whatsapp_mcp`` (delegates here via ``__main__.py``).

The :func:`main` function is intentionally argparse-only; the import of
:func:`whatsapp_mcp.server.run` is **lazy** (deferred until after argparse
finishes parsing) so that ``--version`` and ``--help`` exit before the
FastMCP import cost is paid and, more importantly, before any third-party
import has a chance to emit stdout / start a stdio loop. argparse writes
``--help`` to stdout and ``--version`` to stdout, then calls
:func:`sys.exit` — the JSON-RPC loop is never opened on those flags, so
those stdout bytes can never collide with protocol framing.

The Phase 1 ``--read-only`` / ``--no-read-only`` flag (Plan 01-03) is
parsed here and assigned to ``whatsapp_mcp.server.read_only_mode`` BEFORE
the lazy server-entry import resolves. Importing the
``whatsapp_mcp.server`` module triggers the tool-registration side-effect
imports at module-load time, so the assignment must happen first to be
observable by Phase 2's gated send-tool import. In Phase 1 every Plan 01-04
read-tool import runs unconditionally regardless of the flag (read tools
are inherently read-only), so the Phase 1 effect of the flag is purely
structural — it locks in the contract that Phase 2 will honor.
"""

from __future__ import annotations

import argparse
import sys

from whatsapp_mcp import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="whatsapp-mcp",
        description="MCP stdio server for the macOS WhatsApp Desktop app.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"whatsapp-mcp {__version__}",
    )
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
    # the user's choice. Phase 1 ships zero send tools, so the flag is
    # structural — Phase 2's send_message import will be gated by
    # `if not server.read_only_mode:` and will observe THIS assignment.
    from whatsapp_mcp import server

    server.read_only_mode = args.read_only

    # Import server lazily so --version / --help exit before FastMCP loads.
    from whatsapp_mcp.server import run

    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

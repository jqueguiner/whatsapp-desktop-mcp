"""Console-script entry point for ``whatsapp-desktop-mcp``.

Resolved by both:

- ``whatsapp-desktop-mcp`` (PyPI console script — ``[project.scripts] whatsapp-desktop-mcp =
  "whatsapp_desktop_mcp.cli:main"`` in ``pyproject.toml``).
- ``python -m whatsapp_desktop_mcp`` (delegates here via ``__main__.py``).

The :func:`main` function is intentionally argparse-only; the import of
:func:`whatsapp_desktop_mcp.server.run` is **lazy** (deferred until after argparse
finishes parsing) so that ``--version`` and ``--help`` exit before the
FastMCP import cost is paid and, more importantly, before any third-party
import has a chance to emit stdout / start a stdio loop. argparse writes
``--help`` to stdout and ``--version`` to stdout, then calls
:func:`sys.exit` — the JSON-RPC loop is never opened on those flags, so
those stdout bytes can never collide with protocol framing.

The Phase 1 ``--read-only`` / ``--no-read-only`` flag (Plan 01-03) is
parsed here and assigned to ``whatsapp_desktop_mcp.server.read_only_mode`` BEFORE
the lazy server-entry import resolves. Importing the
``whatsapp_desktop_mcp.server`` module triggers the tool-registration side-effect
imports at module-load time, so the assignment must happen first to be
observable by Phase 2's gated send-tool import. In Phase 1 every Plan 01-04
read-tool import runs unconditionally regardless of the flag (read tools
are inherently read-only), so the Phase 1 effect of the flag is purely
structural — it locks in the contract that Phase 2 will honor.
"""

from __future__ import annotations

import argparse
import sys

from whatsapp_desktop_mcp import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="whatsapp-desktop-mcp",
        description="MCP stdio server for the macOS WhatsApp Desktop app.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"whatsapp-desktop-mcp {__version__}",
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
    # Phase 3 D-28 / D-29: --fts5-mode controls the search_messages dispatch
    # between the new FTS5 sidecar (Plan 03-01) and the Phase 1 LIKE path.
    # Mirrors --read-only mechanics: argparse parses the value, then the
    # `server.fts5_mode = args.fts5_mode` assignment below fires BEFORE the
    # lazy `from whatsapp_desktop_mcp.server import run` import resolves — so the
    # tool-registration side-effect imports in server.py observe the user's
    # choice when tools/search_messages.py is imported.
    parser.add_argument(
        "--fts5-mode",
        choices=["auto", "force", "disable"],
        default="auto",
        help=(
            "Controls FTS5 shadow-index dispatch in search_messages. 'auto' "
            "(default): use the FTS5 sidecar at "
            "~/Library/Application Support/whatsapp-desktop-mcp/fts.sqlite if it exists, "
            "else fall back to the Phase 1 LIKE scan. 'force': always FTS5, "
            "lazy-building the sidecar if absent (the first call after a long "
            "break may take 10-30s — logged to stderr). 'disable': always LIKE "
            "(Phase 1 v0.1 behavior; useful when an FTS5 issue needs bypassing)."
        ),
    )
    args = parser.parse_args(argv)

    # Set the read_only_mode flag BEFORE importing server.run so that the
    # FastMCP tool-registration side-effect imports in server.py observe
    # the user's choice. Phase 1 ships zero send tools, so the flag is
    # structural — Phase 2's send_message import will be gated by
    # `if not server.read_only_mode:` and will observe THIS assignment.
    from whatsapp_desktop_mcp import server

    server.read_only_mode = args.read_only
    # Phase 3 D-29: same ordering invariant as read_only_mode — assign the
    # FTS5 dispatch mode BEFORE the lazy server.run import so the tool
    # registration block in server.py loads with the correct value (the
    # tool body re-reads `server.fts5_mode` at call time, but the assignment
    # has to land before any code path that captures the attr by value).
    server.fts5_mode = args.fts5_mode

    # Import server lazily so --version / --help exit before FastMCP loads.
    from whatsapp_desktop_mcp.server import run

    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

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

Phase 3 Plan 03-03 restructures :func:`main` into an argparse subparser
dispatch. The default (no subcommand) runs the MCP server as before;
``whatsapp-desktop-mcp dev <subcommand>`` dispatches into the
:mod:`whatsapp_desktop_mcp.dev` subpackage (one-shot CLI utilities;
NOT the stdio MCP server). The ``--read-only`` / ``--fts5-mode`` /
``--audit-log-max-bytes`` server-mode args are extracted into a helper
``_add_server_args(parser)`` so they can be applied to the top-level
parser today and to a future ``server`` subcommand if the dispatch
ever inverts.
"""

from __future__ import annotations

import argparse
import os
import sys

from whatsapp_desktop_mcp import __version__


def _add_server_args(parser: argparse.ArgumentParser) -> None:
    """Apply the server-mode CLI args to ``parser``.

    Extracted so the same option set applies whether the user invokes
    the top-level parser (current default — ``whatsapp-desktop-mcp [args]``)
    or a future ``server`` subcommand. The Phase 1 / Phase 3 args land
    here verbatim with their accumulated docstrings.
    """
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
    # Phase 3 D-25 / D-28: --audit-log-max-bytes overrides the default 10 MB
    # rotation threshold for the JSONL audit log. Set as an env var BEFORE
    # the lazy server.run import so the audit module's _resolve_max_bytes()
    # observes the user's choice on the first send-attempt append.
    parser.add_argument(
        "--audit-log-max-bytes",
        type=int,
        default=10 * 1024 * 1024,
        help=(
            "Audit log rotation threshold in bytes (D-25 default 10 MB; rotation "
            "keeps last 5 archives audit.log.1..audit.log.5 — older archives are "
            "evicted on the next rotation past the cap)."
        ),
    )


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
    _add_server_args(parser)

    # Phase 3 D-27: nested subparsers for the dev subcommand surface. The
    # top-level parser still accepts the server-mode args (default behavior
    # is unchanged when no subcommand is given), but `whatsapp-desktop-mcp
    # dev reset-rate-limit` routes into whatsapp_desktop_mcp.dev.* instead
    # of starting the stdio server.
    subparsers = parser.add_subparsers(dest="cmd")
    dev_parser = subparsers.add_parser(
        "dev",
        help="developer utility subcommands (one-shot CLI; NOT the MCP server)",
    )
    dev_subparsers = dev_parser.add_subparsers(dest="dev_cmd")
    dev_subparsers.add_parser(
        "reset-rate-limit",
        help=(
            "clear ~/Library/Application Support/whatsapp-desktop-mcp/rate-limit.db "
            "after interactive confirmation; non-tty stdin refuses (D-27)"
        ),
    )

    args = parser.parse_args(argv)

    # Phase 3 D-27: dispatch BEFORE the server-mode flag assignments + lazy
    # server.run import, because the dev subcommand explicitly does NOT want
    # to boot FastMCP / run the stdio loop.
    if args.cmd == "dev" and args.dev_cmd == "reset-rate-limit":
        from whatsapp_desktop_mcp.dev.reset_rate_limit import run as dev_reset

        return dev_reset()

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
    # Phase 3 D-25 / D-28: ditto — the audit module reads the env var at
    # _resolve_max_bytes() call time (lazy on first append), so the
    # assignment has to land before any send-attempt audit append fires.
    os.environ["WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES"] = str(args.audit_log_max_bytes)

    # Import server lazily so --version / --help exit before FastMCP loads.
    from whatsapp_desktop_mcp.server import run

    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

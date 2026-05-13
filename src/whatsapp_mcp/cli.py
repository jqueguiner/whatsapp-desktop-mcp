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
    parser.parse_args(argv)

    # Import server lazily so --version / --help exit before FastMCP loads.
    from whatsapp_mcp.server import run

    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

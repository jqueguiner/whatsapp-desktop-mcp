"""Module entry point for ``python -m whatsapp_mcp``.

Tiny shim that delegates to :func:`whatsapp_mcp.cli.main` so the
``python -m`` invocation path produces identical behavior to the
``whatsapp-mcp`` console script.
"""

from __future__ import annotations

import sys

from whatsapp_mcp.cli import main

if __name__ == "__main__":
    sys.exit(main())

"""Developer-utility CLI subcommands surfaced under ``whatsapp-desktop-mcp dev *``.

The modules in this subpackage implement one-shot CLI utilities that print
to stdout, NOT the stdio MCP server (which is a strict JSON-RPC channel
on stdout per CLAUDE.md hard rule #2 / Phase 0 D-05). The per-file ruff
T201 ignore in ``pyproject.toml`` exempts this subpackage from the
no-print rule the rest of the project carries.

Reachability: these utilities are reached ONLY via the
``whatsapp-desktop-mcp dev <subcommand>`` argparse path in
:mod:`whatsapp_desktop_mcp.cli`. There is no import edge from
``server.py`` / any tool / any reader-or-sender module into this
subpackage, so the print() calls here can never end up on the server's
stdout (T-03-03-06 mitigation).

REL-05 D-24 isolation: this subpackage lives outside ``reader/`` and
``sender/`` and does not import from either except through the
:mod:`whatsapp_desktop_mcp.sender.rate_limit` module's public path
constant (``_DB_PATH``) — that is, the dev tier is on the cli/tool tier
of the dependency DAG, not a peer of reader/sender, so it does NOT
violate the "reader and sender must not import each other" rule.
"""

from __future__ import annotations

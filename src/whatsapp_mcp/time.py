"""Cocoa-epoch (Core Data) <-> Unix-epoch helpers.

WhatsApp Desktop on macOS inherits the iOS Core Data convention: dates
are stored as seconds since 2001-01-01 UTC (the Cocoa reference date).
Unix epoch is 1970-01-01 UTC. The offset between them is exactly
``978_307_200`` seconds.

VERIFIED LIVE 2026-05-13 on the user's Mac (WhatsApp 26.16.74)::

    SELECT MAX(ZMESSAGEDATE),
           datetime(MAX(ZMESSAGEDATE) + 978307200, 'unixepoch')
    FROM ZWAMESSAGE;
    -> 800352916  ->  2026-05-13 08:15:16

Module placement: this helper lives at the package root
(``whatsapp_mcp.time``), NOT under ``reader/``, because both the reader
(when projecting row values) and the tools (when computing
``extract_recent`` cutoffs from a "last N hours" parameter) need it.
A cross-cutting helper belongs at the root so neither package depends
on the other (REL-05 isolation between ``reader/`` and ``sender/`` is
the same principle applied to a different boundary).

Module name: ``time`` does NOT shadow Python's stdlib ``time`` module
because we always import as the fully-qualified ``whatsapp_mcp.time``
from outside, and this module makes no ``import time`` calls of its own.
"""

from __future__ import annotations

COCOA_EPOCH_OFFSET: int = 978_307_200


def cocoa_to_unix(cocoa_seconds: float) -> int:
    """Convert a Core Data REAL timestamp to a Unix-epoch integer.

    Truncates the sub-second fraction (Phase 1 tools surface ``int``
    Unix seconds; sub-second precision is not part of the public
    contract).
    """
    return int(cocoa_seconds) + COCOA_EPOCH_OFFSET


def unix_to_cocoa(unix_seconds: int) -> float:
    """Convert a Unix-epoch integer to a Core Data REAL timestamp."""
    return float(unix_seconds - COCOA_EPOCH_OFFSET)

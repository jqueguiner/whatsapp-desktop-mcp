"""Post-hoc DB poll for outgoing message verification (SEND-08 / D-21 / D-22).

After ``sender.ui_send.send_text`` returns (i.e. WhatsApp.app has been
driven through the deep-link + keystroke or search-and-click + keystroke
path and the Return key has been pressed), this module polls WhatsApp's
local ``ChatStorage.sqlite`` for the corresponding outgoing
``ZWAMESSAGE`` row. First match wins; on success the row's
``ZSTANZAID`` is the WhatsApp-protocol-level message id surfaced to the
caller as :class:`SendResult.message_id`.

Cadence per D-21: a 250 ms poll interval applied across 40 iterations
gives a 10 s wall-clock budget. The Plan 02-03 ``send_message`` tool
wraps the whole orchestration in a 15 s outer envelope so the 10 s
verify budget plus the ~3 s AX preflight + ~1 s deeplink settle fits
inside the outer envelope comfortably (T-02-03-09 DoS mitigation).

D-22 soft-fail semantics
========================
On timeout (no matching row observed within 10 s) the public coroutine
returns ``None``; the upstream tool maps this to ``outcome="sent_unverified"``
— **NOT** an error. WhatsApp.app may sync the send to its DB after our
window, especially on slow networks; the send is observably present in
the WhatsApp UI but we couldn't confirm via DB in our bounded budget.
Surfacing a hard error here would tell the user the send failed when
the send actually succeeded; the user would then retry, creating a
duplicate. The soft-fail is the correct contract.

The exact-match ``ZTEXT = ?`` predicate (not ``LIKE``) trades false
negatives (some sends miss verification → ``sent_unverified``) for
zero false positives (we never claim ``message_id`` for a row that
came from a different prior message that happened to contain the
body as a substring). False negatives are user-acceptable; false
positives would be a much worse failure mode.

``ZISFROMME = 1`` filters to outgoing messages only — verified present
in the project's schema-v1 templates (the read-side template module
lines 105 / 209 / 228 reference this column). Without this filter, an
inbound message with identical body to our outgoing send would
spuriously match.

REL-05 D-24 EVOLUTION (one-way edge)
====================================
This module is the ONLY file under ``sender/`` that imports from the
project's read-side data tier — specifically the short-lived RO
connection helper ``open_ro`` from the read-side connection module.
The narrow connection-only edge is the canonical D-24 relaxation of
the Phase 1 REL-05 invariant ("Reader MUST NOT import Sender. Sender
MAY import reader connection primitives only — NOT the data
accessors, NOT the read-side business logic"). Plan 02-04 updates
``tests/unit/test_isolation.py`` to assert this exact narrow surface —
every other read-side import path stays forbidden in ``sender/``.

The sender-side import target is intentionally restricted to the
connection helper module ONLY. The package-level re-export surface
of the read-side tier (which would pull the 14-accessor data-tier
surface) is NOT imported here — preserving the structural narrowness
that makes the D-24 relaxation safe.

CLAUDE.md hard rule #3 (never write to ``ChatStorage.sqlite``) is
honored: ``open_ro`` opens the connection with the ``?mode=ro`` URI
flag, so SQLite refuses any DML at the engine level.

Async dispatch (REL-02)
=======================
The blocking SQLite probe runs inside ``asyncio.to_thread`` so the
single asyncio event loop driving the MCP server is never blocked
on disk I/O. The poll loop yields between iterations via
``await asyncio.sleep(_POLL_INTERVAL_SECONDS)`` — under heavy load
other tools (the read tools, ``doctor``) can interleave their own
SQLite reads on the same loop with no contention (the connection
is short-lived inside ``_blocking_probe`` and closes before the
sleep yields).
"""

from __future__ import annotations

import asyncio
import sqlite3

from whatsapp_desktop_mcp.paths import resolve_chatstorage_path
from whatsapp_desktop_mcp.reader.connection import open_ro
from whatsapp_desktop_mcp.time import unix_to_cocoa

# Verification cadence per D-21. The 250 ms interval is chosen so a fast
# WhatsApp sync (typical case on a healthy network) is caught on the
# first or second poll, while keeping the per-poll SQLite open / close
# cost low. The 40-poll cap × 250 ms = 10 s budget matches the upstream
# @timeout(seconds=15) wrapper's slack for AX preflight + deeplink
# settle.
_POLL_INTERVAL_SECONDS = 0.25
_MAX_POLLS = 40

# Post-hoc verification SQL — plain string concatenation (NOT an f-string)
# so the source stays grep-stable and mirrors the read-side schema-v1
# template style. No interpolation needed; all three predicate values
# bind as ? parameters.
#
# Columns:
#   ZSTANZAID    — WhatsApp-protocol message id; opaque base64-ish string
#                  on this schema. Surfaced as SendResult.message_id.
#   ZMESSAGEDATE — Cocoa-epoch REAL timestamp; the row write time.
#
# Predicates:
#   ZCHATSESSION = ?   — chat scoping. Matches the chat the send targeted.
#   ZISFROMME    = 1   — outgoing only (verified present in read-side
#                        schema-v1 templates).
#   ZTEXT        = ?   — exact body match. Soft-fail on miss per D-22.
#   ZMESSAGEDATE > ?   — only rows newer than send_started prevents
#                        matching a pre-existing identical body from
#                        earlier in the chat history.
#
# ORDER BY ZSORT DESC LIMIT 1 — newest row first; first match wins.
_SQL = (
    "SELECT ZSTANZAID, ZMESSAGEDATE FROM ZWAMESSAGE "
    "WHERE ZCHATSESSION = ? "
    "AND ZISFROMME = 1 "
    "AND ZTEXT = ? "
    "AND ZMESSAGEDATE > ? "
    "ORDER BY ZSORT DESC "
    "LIMIT 1"
)


def _blocking_probe(chat_id: int, body: str, since_cocoa: float) -> str | None:
    """Single short-lived RO probe — returns ``ZSTANZAID`` or ``None``.

    Opens a short-lived RO WAL connection via :func:`open_ro` (the
    canonical Phase 1 short-lived-RO pattern that handles WhatsApp's
    active-writer scenario via ``PRAGMA busy_timeout = 5000``), runs
    :data:`_SQL` with the three bound parameters, and returns the
    ``ZSTANZAID`` value on first hit or ``None`` on miss.

    Defensively typed: the row's first column is asserted to be a
    string (the schema ships ZSTANZAID as TEXT; a non-string would
    indicate a schema drift Plan 02-05 should catch).
    """
    db_path = resolve_chatstorage_path()
    with open_ro(db_path) as conn:
        row: sqlite3.Row | None = conn.execute(_SQL, (chat_id, body, since_cocoa)).fetchone()
    if row is None:
        return None
    stanza_id = row[0]
    if not isinstance(stanza_id, str):
        # Schema drift safety: the read-side templates declare ZSTANZAID
        # as TEXT; non-string here means an unexpected DB state. Return
        # None so the caller maps to outcome=sent_unverified rather than
        # surfacing a malformed message id.
        return None
    return stanza_id


async def poll_for_outgoing(
    chat_id: int,
    body: str,
    send_started_unix: float,
) -> str | None:
    """Poll WhatsApp's local DB for the outgoing send's ``ZSTANZAID``.

    Args:
        chat_id: The opaque integer ``ZWACHATSESSION.Z_PK`` the send
            targeted. The same ``chat_id`` the caller passed to
            ``send_message``.
        body: The exact outgoing body that was sent. Compared verbatim
            against ``ZTEXT`` per D-22 exact-match contract.
        send_started_unix: Unix-epoch seconds captured BEFORE the send
            subprocess fired, so the ``ZMESSAGEDATE > ?`` predicate
            excludes pre-existing identical bodies from earlier history.

    Returns:
        ``ZSTANZAID`` (a string) when a matching row is observed within
        the 10 s budget; ``None`` on timeout. The upstream
        ``send_message`` tool maps ``None`` to
        ``outcome="sent_unverified"`` per D-22 — NOT an error.

    The first poll fires after a 0 s sleep (the loop body sleeps after
    the probe, not before) — sends that WhatsApp.app syncs to its DB
    immediately are caught on the first iteration.
    """
    since_cocoa = unix_to_cocoa(int(send_started_unix))
    for _ in range(_MAX_POLLS):
        stanza_id = await asyncio.to_thread(_blocking_probe, chat_id, body, since_cocoa)
        if stanza_id is not None:
            return stanza_id
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    return None

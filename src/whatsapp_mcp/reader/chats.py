"""Chat reader — list_chats / find_chat_by_id / find_chat_by_jid.

Maps ``ZWACHATSESSION`` rows to the locked :class:`whatsapp_mcp.models.Chat`
shape with per-chat :class:`Coverage` populated from a grouped
``MIN(ZMESSAGEDATE)`` probe across all chats (one round-trip; no N+1).

``ZSESSIONTYPE`` -> ``ChatKind`` mapping (RESEARCH §"Open Questions Q1
RESOLVED"; verified-live distribution on the user's Mac 2026-05-13):

- ``0`` -> ``"direct"``    (588 rows)
- ``1`` -> ``"group"``     (384 rows)
- ``2`` -> ``"other"``     (1 row, unknown semantics — locked default)
- ``3`` -> ``"broadcast"`` (6 rows)
- ``4`` -> ``"community"`` (9 rows)

Async pattern (REL-02): every public function is ``async def`` and
dispatches its blocking SQLite work via ``await asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import sqlite3

from whatsapp_mcp.models import Chat, ChatKind, Coverage
from whatsapp_mcp.paths import resolve_chatstorage_path
from whatsapp_mcp.reader.connection import open_ro
from whatsapp_mcp.reader.messages import _parse_jid
from whatsapp_mcp.reader.schema_v1 import (
    _SQL_EARLIEST_MSG_PER_CHAT,
    _SQL_FIND_CHAT_BY_ID,
    _SQL_FIND_CHAT_BY_JID,
    _SQL_LIST_CHATS,
)
from whatsapp_mcp.time import cocoa_to_unix

# ZSESSIONTYPE -> ChatKind. Anything unknown maps to "other" per
# RESEARCH §"Open Questions Q1 RESOLVED" — the discriminator stays
# stable across future schema additions.
_SESSION_TYPE_MAP: dict[int, ChatKind] = {
    0: "direct",
    1: "group",
    2: "other",
    3: "broadcast",
    4: "community",
}


def _classify_kind(raw: object) -> ChatKind:
    """Map ``ZSESSIONTYPE`` integer to :data:`ChatKind`."""
    if not isinstance(raw, int):
        return "other"
    return _SESSION_TYPE_MAP.get(raw, "other")


def _build_coverage(from_cocoa: float | None, to_cocoa: float | None) -> Coverage:
    """Build a per-chat :class:`Coverage` from Cocoa-epoch bounds."""
    from_ts = cocoa_to_unix(from_cocoa) if from_cocoa is not None else None
    to_ts = cocoa_to_unix(to_cocoa) if to_cocoa is not None else None
    have = to_ts - from_ts if (from_ts is not None and to_ts is not None) else None
    return Coverage(
        from_ts=from_ts,
        to_ts=to_ts,
        asked_window_seconds=None,
        have_window_seconds=have,
        # `is_full` is meaningless for list_chats (caller did not ask for
        # a window) — emit False per the Coverage contract.
        is_full=False,
    )


def _row_to_chat(
    row: sqlite3.Row,
    earliest_by_chat: dict[int, float],
) -> Chat:
    chat_id = int(row["Z_PK"])
    raw_session_type = row["ZSESSIONTYPE"]
    kind = _classify_kind(raw_session_type)

    raw_jid = row["ZCONTACTJID"]
    jid = _parse_jid(raw_jid if isinstance(raw_jid, str) else None)

    display_name = str(row["ZPARTNERNAME"] or "")

    last_cocoa = row["ZLASTMESSAGEDATE"]
    last_activity_ts = cocoa_to_unix(float(last_cocoa)) if last_cocoa is not None else None

    raw_last_text = row["ZLASTMESSAGETEXT"]
    last_message_preview = str(raw_last_text) if raw_last_text is not None else None

    raw_unread = row["ZUNREADCOUNT"]
    unread_count = int(raw_unread) if raw_unread is not None else 0

    raw_archived = row["ZARCHIVED"]
    is_archived = bool(raw_archived) if raw_archived is not None else False

    raw_hidden = row["ZHIDDEN"]
    is_hidden = bool(raw_hidden) if raw_hidden is not None else False

    earliest_cocoa = earliest_by_chat.get(chat_id)
    coverage = _build_coverage(earliest_cocoa, last_cocoa)

    return Chat(
        chat_id=chat_id,
        kind=kind,
        jid=jid,
        display_name=display_name,
        last_activity_ts=last_activity_ts,
        last_message_preview=last_message_preview,
        unread_count=unread_count,
        is_archived=is_archived,
        is_hidden=is_hidden,
        coverage=coverage,
    )


def _earliest_by_chat(conn: sqlite3.Connection) -> dict[int, float]:
    """Return ``{chat_id: earliest_cocoa}`` for every chat in one query.

    Single grouped scan over ``ZWAMESSAGE`` — at the verified-live 988-chat
    scale this is fine. Plan 04 may move this into a per-chat lazy probe
    if perf data warrants.
    """
    out: dict[int, float] = {}
    for row in conn.execute(_SQL_EARLIEST_MSG_PER_CHAT).fetchall():
        cid_raw = row[0]
        earliest = row[1]
        if cid_raw is None or earliest is None:
            continue
        out[int(cid_raw)] = float(earliest)
    return out


# ---------------------------------------------------------------------------
# Public async surface
# ---------------------------------------------------------------------------


async def list_chats(limit: int = 200) -> list[Chat]:
    """List up to ``limit`` chats ordered by ``ZLASTMESSAGEDATE DESC``.

    Each returned :class:`Chat` carries a per-chat :class:`Coverage`
    populated from a single grouped ``MIN(ZMESSAGEDATE)`` probe (no
    N+1 — one extra round-trip total).
    """
    db_path = resolve_chatstorage_path()
    return await asyncio.to_thread(_list_chats_blocking, db_path, limit)


def _list_chats_blocking(db_path: str, limit: int) -> list[Chat]:
    with open_ro(db_path) as conn:
        earliest = _earliest_by_chat(conn)
        rows = conn.execute(_SQL_LIST_CHATS, (limit,)).fetchall()
        return [_row_to_chat(r, earliest) for r in rows]


async def find_chat_by_id(chat_id: int) -> Chat | None:
    """Return a single :class:`Chat` by ``ZWACHATSESSION.Z_PK`` or ``None``."""
    db_path = resolve_chatstorage_path()
    return await asyncio.to_thread(_find_chat_by_id_blocking, db_path, chat_id)


def _find_chat_by_id_blocking(db_path: str, chat_id: int) -> Chat | None:
    with open_ro(db_path) as conn:
        row = conn.execute(_SQL_FIND_CHAT_BY_ID, (chat_id,)).fetchone()
        if row is None:
            return None
        earliest = _earliest_by_chat(conn)
        return _row_to_chat(row, earliest)


async def find_chat_by_jid(jid_raw: str) -> Chat | None:
    """Return a single :class:`Chat` by raw ``ZCONTACTJID`` or ``None``.

    Uses ``Z_WAChatSession_byContactJIDIndex`` for an O(log n) lookup
    (verified live).
    """
    db_path = resolve_chatstorage_path()
    return await asyncio.to_thread(_find_chat_by_jid_blocking, db_path, jid_raw)


def _find_chat_by_jid_blocking(db_path: str, jid_raw: str) -> Chat | None:
    with open_ro(db_path) as conn:
        row = conn.execute(_SQL_FIND_CHAT_BY_JID, (jid_raw,)).fetchone()
        if row is None:
            return None
        earliest = _earliest_by_chat(conn)
        return _row_to_chat(row, earliest)

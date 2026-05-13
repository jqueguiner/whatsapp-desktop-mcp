"""LIKE-based message search (READ-04 v0.1; FTS5 deferred to Phase 3).

RESEARCH §"Search: LIKE Strategy (READ-04 v0.1)": Phase 1 ships a
parameterized LIKE scan against ``ZWAMESSAGE.ZTEXT`` with optional
``chat_id`` / ``sender_jid`` / before/after Unix-timestamp filters.

Performance budget: LIKE scans the full ``ZWAMESSAGE`` table; on the
verified-live 78k-row corpus this is ~100 ms cold / ~30 ms warm — well
inside the per-tool 10s timeout (REL-03). Phase 3 ships an FTS5 shadow
index when scale demands it.

**W4 invariant:** ``_row_to_message`` is imported from
``reader/messages.py`` (one-direction edge — ``messages.py`` does NOT
depend on ``search.py``, no circular risk). The planner explicitly
forbids extracting a shared ``_row_mapping.py`` module.

Async pattern (REL-02): public function is ``async def`` and dispatches
its blocking SQLite work via ``await asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import sqlite3

from whatsapp_mcp.models import Message
from whatsapp_mcp.paths import resolve_chatstorage_path, resolve_media_root
from whatsapp_mcp.reader.connection import open_ro
from whatsapp_mcp.reader.messages import _project_messages
from whatsapp_mcp.reader.schema_v1 import (
    _SQL_LIKE_SEARCH,
    _SQL_LIKE_SEARCH_INCLUDE_DELETED,
)
from whatsapp_mcp.time import unix_to_cocoa


async def like_search(
    query: str,
    chat_id: int | None = None,
    sender_jid: str | None = None,
    before: int | None = None,
    after: int | None = None,
    limit: int = 50,
    include_deleted: bool = False,
) -> list[Message]:
    """Parameterized LIKE search across ``ZWAMESSAGE.ZTEXT``.

    Args:
        query: Case-insensitive substring (bound as a SQL parameter;
            never interpolated into the query string).
        chat_id: Optional ``ZWACHATSESSION.Z_PK`` filter.
        sender_jid: Optional raw JID filter against ``ZFROMJID``.
            Caller is responsible for resolving phone <-> lid (use
            :func:`whatsapp_mcp.reader.contacts.resolve_phone_to_lid`
            if needed).
        before: Optional Unix-seconds upper bound (exclusive on the
            user-visible boundary — internally compared as
            ``ZMESSAGEDATE <= cocoa(before)``).
        after: Optional Unix-seconds lower bound (internally
            ``ZMESSAGEDATE >= cocoa(after)``).
        limit: Page size; defaults to 50.
        include_deleted: When ``False`` (default), the SQL template
            inlines the tombstone WHERE clause.

    Returns:
        list of :class:`Message`, newest first
        (``ORDER BY ZMESSAGEDATE DESC``).
    """
    db_path = resolve_chatstorage_path()
    media_root = resolve_media_root()
    return await asyncio.to_thread(
        _like_search_blocking,
        db_path,
        media_root,
        query,
        chat_id,
        sender_jid,
        before,
        after,
        limit,
        include_deleted,
    )


def _like_search_blocking(
    db_path: str,
    media_root: str,
    query: str,
    chat_id: int | None,
    sender_jid: str | None,
    before: int | None,
    after: int | None,
    limit: int,
    include_deleted: bool,
) -> list[Message]:
    sql = _SQL_LIKE_SEARCH_INCLUDE_DELETED if include_deleted else _SQL_LIKE_SEARCH
    after_cocoa = unix_to_cocoa(after) if after is not None else None
    before_cocoa = unix_to_cocoa(before) if before is not None else None

    # The ``(? IS NULL OR col = ?)`` pattern from RESEARCH §"Search: LIKE
    # Strategy" — single placeholder bound twice in the caller.
    params: tuple[object, ...] = (
        query,
        chat_id,
        chat_id,
        sender_jid,
        sender_jid,
        after_cocoa,
        after_cocoa,
        before_cocoa,
        before_cocoa,
        limit,
    )
    with open_ro(db_path) as conn:
        rows = list(_execute_with_params(conn, sql, params))
        return _project_messages(conn, rows, media_root)


def _execute_with_params(
    conn: sqlite3.Connection, sql: str, params: tuple[object, ...]
) -> list[sqlite3.Row]:
    """Tiny helper: typed wrapper around ``conn.execute(...).fetchall()``.

    Exists only so mypy --strict has a single typed seam to the
    ``conn.execute(*, parameters=...)`` overload set; the underlying
    call uses positional ``?`` placeholders only.
    """
    return list(conn.execute(sql, params).fetchall())

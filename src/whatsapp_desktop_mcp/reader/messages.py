"""Message reader — window / since / context_around_stanza / parent_of_stanza.

This module owns the ``_row_to_message`` helper that projects a
``ZWAMESSAGE`` row (with the ``LEFT JOIN ZWAMEDIAITEM`` columns) into
the locked :class:`whatsapp_desktop_mcp.models.Message` shape.

**W4 invariant:** ``_row_to_message`` lives HERE and is imported by
``reader/search.py``. The dependency edge is one-direction
(``search.py -> messages.py``); ``messages.py`` does NOT depend on
``search.py``, so there's no circular import risk and no need to
extract a shared ``_row_mapping.py`` module (the planner explicitly
locked this — do not speculatively split).

**B2 invariant:** :func:`window` returns
``tuple[list[Message], float | None]`` where the float is the
``ZSORT`` value of the last (oldest) message in the returned page, or
``None`` if the page is empty. Plan 04's ``read_chat`` feeds this float
into :func:`whatsapp_desktop_mcp.models.encode_cursor` (anchor_kind="z_sort")
to build ``next_cursor``. ``ZSORT`` is NEVER a public attribute on
:class:`whatsapp_desktop_mcp.models.Message` — exposing it would invite callers
to filter/sort on it, breaking the opaque-cursor contract.

Async pattern (REL-02): every public function is ``async def`` and
dispatches its blocking SQLite work via ``await asyncio.to_thread``;
the ``_blocking_*`` helpers contain the actual ``with open_ro(...) as
conn:`` blocks. Tool-side timeouts (REL-03) are applied by Plan 04
``@timeout`` decorators wrapping these calls.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from whatsapp_desktop_mcp.models import Jid, Message, MessageKind
from whatsapp_desktop_mcp.paths import resolve_chatstorage_path, resolve_media_root
from whatsapp_desktop_mcp.reader.connection import open_ro
from whatsapp_desktop_mcp.reader.media import resolve_media_ref
from whatsapp_desktop_mcp.reader.schema_v1 import (
    _SQL_CONTEXT_AROUND_STANZA,
    _SQL_CONTEXT_AROUND_STANZA_INCLUDE_DELETED,
    _SQL_LAST_MESSAGE_TS,
    _SQL_PARENT_BY_STANZA,
    _SQL_SINCE,
    _SQL_SINCE_INCLUDE_DELETED,
    _SQL_STANZA_ID_BY_PK,
    _SQL_WINDOW,
    _SQL_WINDOW_INCLUDE_DELETED,
)
from whatsapp_desktop_mcp.time import cocoa_to_unix, unix_to_cocoa

# Sentinel used in place of "no cursor" — bigger than any verified-live
# ``ZSORT`` value (verified live ``SELECT MAX(ZSORT) FROM ZWAMESSAGE``
# was on the order of 10**16; 1e18 leaves >2 orders of magnitude of
# headroom per RESEARCH §"Code Examples").
_Z_SORT_SENTINEL: float = 1e18


# Verified-live ZMESSAGETYPE distribution → MessageKind. Anything not in
# this table maps to "other" (RESEARCH §"Core Data Schema Essentials →
# ZWAMESSAGE → ZMESSAGETYPE row").
_MESSAGE_TYPE_MAP: dict[int, MessageKind] = {
    0: "text",
    1: "image",
    2: "video",
    3: "audio",
    6: "system",
    7: "location",
    8: "contact",
    10: "sticker",
    11: "call",
    14: "revoked",
    15: "ephemeral",
    59: "poll",
    66: "reaction",
}


def _parse_jid(raw: str | None) -> Jid:
    """Parse a raw JID string into a :class:`Jid` (P11 — never compare strings).

    Suffix dispatch per RESEARCH §"Core Data Schema Essentials →
    ZWACHATSESSION → ZCONTACTJID":

    - ``@s.whatsapp.net`` → ``phone``
    - ``@lid`` → ``lid``
    - ``@g.us`` → ``group``
    - ``0@status`` (exact) → ``status``
    - anything else with ``@broadcast`` → ``broadcast``
    - else → ``broadcast`` (safe-default for unknown suffixes)

    A ``None`` or empty ``raw`` returns a ``broadcast``-kind Jid with
    an empty ``raw`` field — callers can detect this via ``jid.raw == ""``
    without raising. (Tool-layer Plan 04 may decide to filter such rows;
    the reader does not raise on missing JIDs.)
    """
    if not raw:
        return Jid(kind="broadcast", raw="")
    if raw == "0@status":
        return Jid(kind="status", raw=raw)
    if raw.endswith("@s.whatsapp.net"):
        phone = raw.split("@", 1)[0] or None
        return Jid(kind="phone", raw=raw, phone=phone)
    if raw.endswith("@lid"):
        lid = raw.split("@", 1)[0] or None
        return Jid(kind="lid", raw=raw, lid=lid)
    if raw.endswith("@g.us"):
        return Jid(kind="group", raw=raw)
    if raw.endswith("@broadcast"):
        return Jid(kind="broadcast", raw=raw)
    # Fallback: unknown suffix surfaces as broadcast so the public
    # JidKind discriminator stays stable across future schema additions.
    return Jid(kind="broadcast", raw=raw)


def _classify_kind(raw_type: object) -> MessageKind:
    """Return ``MessageKind`` for a row's ``ZMESSAGETYPE`` value.

    Unknown integers (e.g. the verified-live 12 / 20 / 78 rows whose
    semantics we have not pinned down) map to ``"other"`` per the
    locked Plan 01 ``MessageKind`` Literal.
    """
    if not isinstance(raw_type, int):
        return "other"
    return _MESSAGE_TYPE_MAP.get(raw_type, "other")


def _row_to_message(
    row: sqlite3.Row,
    media_root: str | Path,
    *,
    quoted_message_id: str | None = None,
) -> Message:
    """Project a ``ZWAMESSAGE`` row + ``LEFT JOIN ZWAMEDIAITEM`` columns to :class:`Message`.

    W4 lock: this helper lives in ``messages.py``;
    ``reader/search.py`` imports it directly (one-direction edge).

    Args:
        row: A :class:`sqlite3.Row` from one of the message SQL
            templates in ``schema_v1`` (every such template SELECTs the
            same columns).
        media_root: Result of :func:`whatsapp_desktop_mcp.paths.resolve_media_root`.
            Passed through to :func:`resolve_media_ref` for the
            path-traversal-safe attachment resolution.
        quoted_message_id: Optional pre-resolved ``ZSTANZAID`` for the
            ``ZPARENTMESSAGE`` FK. Resolved by the caller via a
            second-query so we don't re-execute one
            ``SELECT ZSTANZAID FROM ZWAMESSAGE`` per row inside this
            already-hot helper.
    """
    raw_is_from_me = row["ZISFROMME"]
    is_outgoing = bool(raw_is_from_me) if raw_is_from_me is not None else False

    # Choose the JID column that names the *other* party / sender:
    # received messages carry ZFROMJID; sent messages carry ZTOJID.
    raw_sender = row["ZTOJID"] if is_outgoing else row["ZFROMJID"]
    sender_jid = _parse_jid(raw_sender)

    raw_text = row["ZTEXT"]
    body: str | None = str(raw_text) if raw_text is not None else None

    raw_stanza = row["ZSTANZAID"]
    message_id: str = str(raw_stanza) if raw_stanza is not None else ""

    raw_starred = row["ZSTARRED"]
    is_starred = bool(raw_starred) if raw_starred is not None else False

    raw_cocoa = row["ZMESSAGEDATE"]
    timestamp = cocoa_to_unix(float(raw_cocoa)) if raw_cocoa is not None else 0

    kind = _classify_kind(row["ZMESSAGETYPE"])

    # Media — only present when ZMEDIAITEM FK was non-NULL AND the
    # LEFT JOIN matched a ZWAMEDIAITEM row. resolve_media_ref handles
    # the NULL ZMEDIALOCALPATH case + path-traversal defense.
    media = resolve_media_ref(row, media_root)

    return Message(
        message_id=message_id,
        chat_id=int(row["ZCHATSESSION"]),
        sender_jid=sender_jid,
        timestamp=timestamp,
        body=body,
        kind=kind,
        is_outgoing=is_outgoing,
        is_starred=is_starred,
        quoted_message_id=quoted_message_id,
        media=media,
    )


def _z_sort_or_none(row: sqlite3.Row) -> float | None:
    """Return ``row["ZSORT"]`` as a float, or ``None`` if NULL."""
    raw = row["ZSORT"]
    if raw is None:
        return None
    return float(raw)


def _resolve_parent_stanzas(conn: sqlite3.Connection, parent_pks: Iterable[int]) -> dict[int, str]:
    """Bulk-resolve ``ZPARENTMESSAGE`` FKs to their ``ZSTANZAID`` values.

    One query per distinct non-NULL ``ZPARENTMESSAGE`` value — small
    enough at the verified-live page sizes (200 messages) that the
    follow-up overhead is bounded. Plan 04 may swap this for an
    ``IN (?, ?, ...)`` bulk query if profiling justifies it; for now,
    one-by-one is fine and keeps the SQL parameterized without
    placeholder count arithmetic.
    """
    out: dict[int, str] = {}
    for pk in parent_pks:
        row = conn.execute(_SQL_STANZA_ID_BY_PK, (pk,)).fetchone()
        if row is not None and row[0] is not None:
            out[pk] = str(row[0])
    return out


def _project_messages(
    conn: sqlite3.Connection, rows: list[sqlite3.Row], media_root: str | Path
) -> list[Message]:
    """Map a list of rows to ``list[Message]`` resolving parent stanza ids first."""
    parent_pks_seen: set[int] = set()
    for row in rows:
        parent = row["ZPARENTMESSAGE"]
        if parent is not None:
            parent_pks_seen.add(int(parent))
    parent_ids = _resolve_parent_stanzas(conn, parent_pks_seen)
    out: list[Message] = []
    for row in rows:
        parent = row["ZPARENTMESSAGE"]
        quoted = parent_ids.get(int(parent)) if parent is not None else None
        out.append(_row_to_message(row, media_root, quoted_message_id=quoted))
    return out


# ---------------------------------------------------------------------------
# Public async surface — every function dispatches via ``asyncio.to_thread``.
# ---------------------------------------------------------------------------


async def window(
    chat_id: int,
    before_z_sort: float | None = None,
    limit: int = 200,
    include_deleted: bool = False,
) -> tuple[list[Message], float | None]:
    """Read a window of messages from one chat, ordered by ``ZSORT DESC``.

    Returns ``(messages, last_seen_z_sort)`` per the B2 lock — the float
    is the ``ZSORT`` of the final (oldest) row in ``messages``, or
    ``None`` if ``messages`` is empty. Plan 04's ``read_chat`` feeds
    this value into :func:`whatsapp_desktop_mcp.models.encode_cursor` with
    ``anchor_kind="z_sort"`` to build ``next_cursor``.

    Args:
        chat_id: ``ZWACHATSESSION.Z_PK``.
        before_z_sort: ``ZSORT`` upper bound (exclusive) for pagination.
            ``None`` means "from newest" — internally substituted with
            the ``_Z_SORT_SENTINEL`` per RESEARCH §"Code Examples".
        limit: Page size; defaults to 200 (READ-02 contract).
        include_deleted: When ``False`` (default), the SQL template
            inlines :data:`~whatsapp_desktop_mcp.reader.tombstones.TOMBSTONE_SQL_WHERE`.
    """
    db_path = resolve_chatstorage_path()
    media_root = resolve_media_root()
    return await asyncio.to_thread(
        _window_blocking, db_path, media_root, chat_id, before_z_sort, limit, include_deleted
    )


def _window_blocking(
    db_path: str,
    media_root: str,
    chat_id: int,
    before_z_sort: float | None,
    limit: int,
    include_deleted: bool,
) -> tuple[list[Message], float | None]:
    cursor_anchor = before_z_sort if before_z_sort is not None else _Z_SORT_SENTINEL
    sql = _SQL_WINDOW_INCLUDE_DELETED if include_deleted else _SQL_WINDOW
    with open_ro(db_path) as conn:
        rows = list(conn.execute(sql, (chat_id, cursor_anchor, limit)).fetchall())
        messages = _project_messages(conn, rows, media_root)
    last_sort: float | None = _z_sort_or_none(rows[-1]) if rows else None
    return messages, last_sort


async def since(
    chat_id: int,
    cutoff_unix_ts: int,
    include_deleted: bool = False,
) -> list[Message]:
    """Read every message in one chat with ``timestamp >= cutoff_unix_ts``.

    Ordered ascending so the caller (Plan 04 ``extract_recent``) gets
    the chronological transcript. ``cutoff_unix_ts`` is Unix seconds;
    converted to Cocoa-epoch internally via
    :func:`whatsapp_desktop_mcp.time.unix_to_cocoa`.
    """
    db_path = resolve_chatstorage_path()
    media_root = resolve_media_root()
    return await asyncio.to_thread(
        _since_blocking, db_path, media_root, chat_id, cutoff_unix_ts, include_deleted
    )


def _since_blocking(
    db_path: str,
    media_root: str,
    chat_id: int,
    cutoff_unix_ts: int,
    include_deleted: bool,
) -> list[Message]:
    cocoa_cutoff = unix_to_cocoa(cutoff_unix_ts)
    sql = _SQL_SINCE_INCLUDE_DELETED if include_deleted else _SQL_SINCE
    with open_ro(db_path) as conn:
        rows = list(conn.execute(sql, (chat_id, cocoa_cutoff)).fetchall())
        return _project_messages(conn, rows, media_root)


async def context_around_stanza(
    message_id: str,
    before: int = 5,
    after: int = 5,
    include_deleted: bool = False,
) -> list[Message]:
    """Read N messages before + N after a target ``ZSTANZAID``, chronological.

    Plan 04's ``get_message_context`` calls this; combined with
    :func:`parent_of_stanza` it implements READ-07 (reply-thread
    context). Returns an empty list if ``message_id`` is unknown.
    """
    db_path = resolve_chatstorage_path()
    media_root = resolve_media_root()
    return await asyncio.to_thread(
        _context_blocking,
        db_path,
        media_root,
        message_id,
        before,
        after,
        include_deleted,
    )


def _context_blocking(
    db_path: str,
    media_root: str,
    message_id: str,
    before: int,
    after: int,
    include_deleted: bool,
) -> list[Message]:
    sql = (
        _SQL_CONTEXT_AROUND_STANZA_INCLUDE_DELETED
        if include_deleted
        else _SQL_CONTEXT_AROUND_STANZA
    )
    with open_ro(db_path) as conn:
        rows = list(conn.execute(sql, (message_id, before, after)).fetchall())
        return _project_messages(conn, rows, media_root)


async def parent_of_stanza(message_id: str) -> Message | None:
    """Resolve a child stanza's reply-parent (``ZPARENTMESSAGE`` FK).

    Returns ``None`` when the message has no parent or when
    ``message_id`` is unknown. Plan 04's ``get_message_context``
    combines this with :func:`context_around_stanza` to deliver the
    full reply-thread shape.
    """
    db_path = resolve_chatstorage_path()
    media_root = resolve_media_root()
    return await asyncio.to_thread(_parent_blocking, db_path, media_root, message_id)


def _parent_blocking(db_path: str, media_root: str, message_id: str) -> Message | None:
    with open_ro(db_path) as conn:
        row = conn.execute(_SQL_PARENT_BY_STANZA, (message_id,)).fetchone()
        if row is None:
            return None
        results = _project_messages(conn, [row], media_root)
        return results[0] if results else None


async def latest_timestamp() -> int | None:
    """Return the maximum ``ZMESSAGEDATE`` across all chats as Unix seconds.

    Plan 05's expanded ``doctor`` surfaces this as
    ``DoctorReport.last_message_ts``. Returns ``None`` if the DB has
    no messages (e.g. fresh install).
    """
    db_path = resolve_chatstorage_path()
    return await asyncio.to_thread(_latest_timestamp_blocking, db_path)


def _latest_timestamp_blocking(db_path: str) -> int | None:
    with open_ro(db_path) as conn:
        row = conn.execute(_SQL_LAST_MESSAGE_TS).fetchone()
    if row is None or row[0] is None:
        return None
    return cocoa_to_unix(float(row[0]))

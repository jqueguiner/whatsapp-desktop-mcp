"""Group reader — get_group_info / get_members.

**W5 invariant (RESEARCH §"Open Questions Q2/Q3 RESOLVED"):**

- :attr:`GroupInfo.description` is HARD-CODED to ``None`` for v0.1. The
  Catalyst-shipped ``ZWAGROUPINFO`` schema verified live on the user's
  Mac has no description column; this is locked, not pending. Phase 3
  may revisit once a second machine confirms (or denies) a description
  column in a future WhatsApp Catalyst build.
- :attr:`GroupInfo.is_muted` is HARD-CODED to ``False`` for v0.1. No
  authoritative source (``ZWACHATSESSION.ZFLAGS`` mute-bit /
  ``ZWAMUTE`` table) has been confirmed across machines. Locked, not
  pending. Phase 2/3 may locate the column once a muted group surfaces
  in test data.

These are NOT TODOs. Plan 02 MUST NOT execute a ``PRAGMA table_info(...)``
probe at execute time. Plan 02 MUST NOT add ``# TODO: confirm during
execution`` comments. The 01-02 SUMMARY restates these as a documented
v0.1 limitation for downstream consumers (Plans 04/05/06).
"""

from __future__ import annotations

import asyncio
import sqlite3

from whatsapp_mcp.models import GroupInfo, GroupMember
from whatsapp_mcp.paths import resolve_chatstorage_path
from whatsapp_mcp.reader.connection import open_ro
from whatsapp_mcp.reader.messages import _parse_jid
from whatsapp_mcp.reader.schema_v1 import _SQL_GROUP_INFO, _SQL_GROUP_MEMBERS
from whatsapp_mcp.time import cocoa_to_unix


def _row_to_member(row: sqlite3.Row) -> GroupMember:
    raw_jid = row["ZMEMBERJID"]
    jid = _parse_jid(raw_jid if isinstance(raw_jid, str) else None)

    contact_name = row["ZCONTACTNAME"]
    first_name = row["ZFIRSTNAME"]
    display_name = str(contact_name or first_name or raw_jid or "")

    raw_admin = row["ZISADMIN"]
    is_admin = bool(raw_admin) if raw_admin is not None else False

    raw_active = row["ZISACTIVE"]
    is_active = bool(raw_active) if raw_active is not None else False

    return GroupMember(
        jid=jid,
        display_name=display_name,
        is_admin=is_admin,
        is_active=is_active,
    )


def _fetch_members(conn: sqlite3.Connection, chat_id: int) -> list[GroupMember]:
    rows = conn.execute(_SQL_GROUP_MEMBERS, (chat_id,)).fetchall()
    return [_row_to_member(r) for r in rows]


# ---------------------------------------------------------------------------
# Public async surface
# ---------------------------------------------------------------------------


async def get_group_info(chat_id: int) -> GroupInfo | None:
    """Return :class:`GroupInfo` for a group chat, or ``None`` for non-groups.

    W5 lock: ``description`` always ``None``, ``is_muted`` always
    ``False`` for v0.1. See module docstring for the locked reasoning.

    The ``subject`` is sourced from ``ZWACHATSESSION.ZPARTNERNAME``
    (the live schema has no ``ZSUBJECT`` column on ``ZWAGROUPINFO``).
    Returns ``None`` if no row matches ``chat_id`` (caller's
    responsibility to first verify the chat is a group via
    :func:`whatsapp_mcp.reader.chats.find_chat_by_id`).
    """
    db_path = resolve_chatstorage_path()
    return await asyncio.to_thread(_get_group_info_blocking, db_path, chat_id)


def _get_group_info_blocking(db_path: str, chat_id: int) -> GroupInfo | None:
    with open_ro(db_path) as conn:
        row = conn.execute(_SQL_GROUP_INFO, (chat_id,)).fetchone()
        if row is None:
            return None
        subject = str(row["subject"] or "")
        creation_raw = row["ZCREATIONDATE"]
        creation_ts = cocoa_to_unix(float(creation_raw)) if creation_raw is not None else None

        creator_raw = row["ZCREATORJID"]
        creator_jid = _parse_jid(creator_raw) if isinstance(creator_raw, str) else None

        owner_raw = row["ZOWNERJID"]
        owner_jid = _parse_jid(owner_raw) if isinstance(owner_raw, str) else None

        members = _fetch_members(conn, chat_id)

        return GroupInfo(
            chat_id=chat_id,
            subject=subject,
            description=None,  # W5 lock — hard-coded for v0.1.
            creation_ts=creation_ts,
            creator_jid=creator_jid,
            owner_jid=owner_jid,
            members=members,
            is_muted=False,  # W5 lock — hard-coded for v0.1.
        )


async def get_members(chat_id: int) -> list[GroupMember]:
    """Return the member roster of a group chat.

    Empty list if the chat has no members or is not a group. Plan 04
    callers that only want the member list (not full info) can call
    this directly without the ``ZWAGROUPINFO`` join overhead.
    """
    db_path = resolve_chatstorage_path()
    return await asyncio.to_thread(_get_members_blocking, db_path, chat_id)


def _get_members_blocking(db_path: str, chat_id: int) -> list[GroupMember]:
    with open_ro(db_path) as conn:
        return _fetch_members(conn, chat_id)

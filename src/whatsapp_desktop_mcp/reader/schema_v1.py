"""Schema fingerprint probe (REL-04) + the v1 SQL template registry.

VERIFIED LIVE on 2026-05-13: ``SELECT Z_VERSION FROM Z_METADATA`` returned
``1`` on the user's Mac (WhatsApp 26.16.74 on macOS 26.4.1). The
``SUPPORTED_VERSIONS`` set starts narrow — exactly the value observed —
and is broadened by Phase 3's ``tested_versions.md`` as second-machine
data arrives. Anything outside the set is a degraded-mode warning from
``doctor`` (NOT a crash from read tools; DIAG-02 mandates ``doctor``
remains callable when others fail).

This module also owns the **SQL template registry** — every read tool in
sibling modules (``chats.py``, ``messages.py``, ``groups.py``,
``contacts.py``, ``search.py``) references one of the ``_SQL_*``
constants below. Centralizing the SQL here keeps all SQL knowledge in
two places (this file + ``tombstones.TOMBSTONE_SQL_WHERE``) so future
schema bumps need exactly one edit. Every template is parameterized
(``?`` placeholders only) — never f-string interpolated with user input.
Every chat-window template hits the verified-live
``Z_WAMessage_compoundIndex (ZCHATSESSION, ZSORT)`` index.

Upgrade runbook (from RESEARCH §"Pattern 3"; copied here so a future
maintainer finds it without grepping the planning dir):

  When ``Z_VERSION`` outside SUPPORTED_VERSIONS shows up in the wild:

    1. User runs ``doctor``, sees ``schema_fingerprint.state =
       "unsupported"`` with ``observed_version = X``.
    2. User opens an issue with: ``doctor`` JSON output, ``defaults read
       /Applications/WhatsApp.app/Contents/Info.plist
       CFBundleShortVersionString``, output of ``sqlite3 .../ChatStorage.sqlite
       ".schema ZWAMESSAGE"``.
    3. Maintainer runs read tools against the new schema in a scratch
       venv; if columns the v1 SQL references are still present, add the
       version to ``SUPPORTED_VERSIONS``, ship a patch.
    4. If columns changed: add ``reader/schema_v2.py`` mirroring the v1
       SQL with renamed/added columns; ``connection.py`` dispatches to
       the right schema module based on ``Z_VERSION``; release as minor
       version bump.
"""

from __future__ import annotations

import sqlite3

from whatsapp_desktop_mcp.reader.tombstones import TOMBSTONE_SQL_WHERE

# Start with the only value verified live. Broaden in Phase 3 once
# second-machine data confirms the upper bound of v1-compatible schemas.
SUPPORTED_VERSIONS: frozenset[int] = frozenset({1})


def probe_z_version(conn: sqlite3.Connection) -> int:
    """Return the integer ``Z_VERSION`` from the ``Z_METADATA`` table.

    Raises :class:`RuntimeError` if ``Z_METADATA`` is empty (unexpected
    ChatStorage state — the table is a Core Data invariant; an empty
    result means the DB was tampered with or is mid-migration).
    """
    row = conn.execute("SELECT Z_VERSION FROM Z_METADATA LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError("Z_METADATA empty — unexpected ChatStorage state")
    return int(row[0])


def is_supported(version: int) -> bool:
    """Return ``True`` if ``version`` is in :data:`SUPPORTED_VERSIONS`."""
    return version in SUPPORTED_VERSIONS


# ---------------------------------------------------------------------------
# SQL template registry — v1 schema, verified live 2026-05-13.
#
# Every constant below is consumed by exactly one sibling module. Parameterized
# (``?`` placeholders only — never user-interpolated; T-02-01 mitigation).
# Tombstone filtering is composed via the ``_aliased_tombstone_where`` helper
# below which takes the canonical ``TOMBSTONE_SQL_WHERE`` constant and rebinds
# the unqualified column names to the ``m.`` alias used in the JOIN queries.
# ---------------------------------------------------------------------------


def _aliased_tombstone_where(alias: str = "m") -> str:
    """Return ``TOMBSTONE_SQL_WHERE`` with column names prefixed by ``alias``.

    Composes the canonical filter constant against an aliased table
    reference. Used only at module import time to build the static
    ``_SQL_*`` constants below — never invoked at query time, so no
    user input ever flows through this function (T-02-01 mitigation).
    """
    prefix = f"{alias}."
    return (
        TOMBSTONE_SQL_WHERE.replace("ZMESSAGETYPE", prefix + "ZMESSAGETYPE")
        .replace("ZTEXT IS NULL", prefix + "ZTEXT IS NULL")
        .replace("ZFLAGS", prefix + "ZFLAGS")
    )


_M_TOMBSTONE_WHERE: str = _aliased_tombstone_where("m")


# Shared SELECT-list for every ``ZWAMESSAGE`` window/since/context/search
# query. Centralized so a column addition is one edit. Excludes the
# encrypted/protobuf BLOB columns per DATA-04 (their literal names are
# omitted from this file so the file-wide grep gate stays clean).
_MESSAGE_SELECT_LIST: str = (
    "SELECT m.Z_PK, m.ZCHATSESSION, m.ZGROUPMEMBER, m.ZMESSAGETYPE, m.ZISFROMME, "
    "m.ZSORT, m.ZMESSAGEDATE, m.ZFROMJID, m.ZTOJID, m.ZSTANZAID, m.ZTEXT, "
    "m.ZPUSHNAME, m.ZFLAGS, m.ZMEDIAITEM, m.ZPARENTMESSAGE, m.ZSTARRED, "
    "mi.ZMEDIALOCALPATH, mi.ZFILESIZE, mi.ZMOVIEDURATION, "
    "mi.ZLATITUDE, mi.ZLONGITUDE, mi.ZTITLE "
    "FROM ZWAMESSAGE m "
    "LEFT JOIN ZWAMEDIAITEM mi ON mi.Z_PK = m.ZMEDIAITEM "
)


# Uses Z_WAChatSession_byLastMessageDateIndex + filter on ZREMOVED.
_SQL_LIST_CHATS: str = (
    "SELECT Z_PK, ZSESSIONTYPE, ZCONTACTJID, ZPARTNERNAME, ZLASTMESSAGEDATE, "
    "ZLASTMESSAGETEXT, ZUNREADCOUNT, ZARCHIVED, ZHIDDEN, ZGROUPINFO "
    "FROM ZWACHATSESSION "
    "WHERE ZREMOVED = 0 "
    "ORDER BY ZLASTMESSAGEDATE DESC "
    "LIMIT ?"
)


# Uses primary-key lookup. Single-row variant for find_chat_by_id.
_SQL_FIND_CHAT_BY_ID: str = (
    "SELECT Z_PK, ZSESSIONTYPE, ZCONTACTJID, ZPARTNERNAME, ZLASTMESSAGEDATE, "
    "ZLASTMESSAGETEXT, ZUNREADCOUNT, ZARCHIVED, ZHIDDEN, ZGROUPINFO "
    "FROM ZWACHATSESSION "
    "WHERE Z_PK = ? "
    "LIMIT 1"
)


# Uses Z_WAChatSession_byContactJIDIndex for the JID-keyed lookup.
_SQL_FIND_CHAT_BY_JID: str = (
    "SELECT Z_PK, ZSESSIONTYPE, ZCONTACTJID, ZPARTNERNAME, ZLASTMESSAGEDATE, "
    "ZLASTMESSAGETEXT, ZUNREADCOUNT, ZARCHIVED, ZHIDDEN, ZGROUPINFO "
    "FROM ZWACHATSESSION "
    "WHERE ZCONTACTJID = ? "
    "LIMIT 1"
)


# Per-chat coverage probe — earliest message timestamp grouped by chat.
# Used by ``chats.list_chats`` to populate ``Chat.coverage.from_ts`` for
# every row in one round-trip (no N+1 per-chat query).
_SQL_EARLIEST_MSG_PER_CHAT: str = (
    "SELECT ZCHATSESSION, MIN(ZMESSAGEDATE) AS earliest_cocoa FROM ZWAMESSAGE GROUP BY ZCHATSESSION"
)


# Uses Z_WAMessage_compoundIndex (ZCHATSESSION, ZSORT). The 1e18 sentinel
# is the "no cursor" upper bound (RESEARCH §"Code Examples"). Joins
# ZWAMEDIAITEM via LEFT JOIN so media-bearing rows surface metadata in
# one round-trip (DATA-03 — never inline bytes; the encrypted/protobuf
# BLOB columns are deliberately excluded from the SELECT list above per
# DATA-04).
_SQL_WINDOW: str = (
    _MESSAGE_SELECT_LIST
    + "WHERE m.ZCHATSESSION = ? AND m.ZSORT < ? "
    + "AND "
    + _M_TOMBSTONE_WHERE
    + " "
    + "ORDER BY m.ZSORT DESC "
    + "LIMIT ?"
)


# include_deleted=True variant — same shape, tombstone filter dropped.
_SQL_WINDOW_INCLUDE_DELETED: str = (
    _MESSAGE_SELECT_LIST
    + "WHERE m.ZCHATSESSION = ? AND m.ZSORT < ? "
    + "ORDER BY m.ZSORT DESC "
    + "LIMIT ?"
)


# Uses Z_WAMessage_byMessageDateIndex (ZMESSAGEDATE). Chat-scoped recency
# read for extract_recent (Plan 04). Cocoa-epoch cutoff parameter.
_SQL_SINCE: str = (
    _MESSAGE_SELECT_LIST
    + "WHERE m.ZCHATSESSION = ? AND m.ZMESSAGEDATE >= ? "
    + "AND "
    + _M_TOMBSTONE_WHERE
    + " "
    + "ORDER BY m.ZMESSAGEDATE ASC"
)


# include_deleted=True variant of _SQL_SINCE.
_SQL_SINCE_INCLUDE_DELETED: str = (
    _MESSAGE_SELECT_LIST
    + "WHERE m.ZCHATSESSION = ? AND m.ZMESSAGEDATE >= ? "
    + "ORDER BY m.ZMESSAGEDATE ASC"
)


# Context window around a target ZSTANZAID. CTE locates the target by
# stanza id (uses Z_WAMessage_byStanzaIDIndex), then a windowed query
# picks N before + N after on ZSORT. Default include_deleted=False
# tombstone filter applied to the outer SELECT.
_SQL_CONTEXT_AROUND_STANZA: str = (
    "WITH target AS ("
    "  SELECT Z_PK, ZCHATSESSION, ZSORT, ZPARENTMESSAGE "
    "  FROM ZWAMESSAGE WHERE ZSTANZAID = ?"
    ") "
    "SELECT m.Z_PK, m.ZCHATSESSION, m.ZGROUPMEMBER, m.ZMESSAGETYPE, m.ZISFROMME, "
    "m.ZSORT, m.ZMESSAGEDATE, m.ZFROMJID, m.ZTOJID, m.ZSTANZAID, m.ZTEXT, "
    "m.ZPUSHNAME, m.ZFLAGS, m.ZMEDIAITEM, m.ZPARENTMESSAGE, m.ZSTARRED, "
    "mi.ZMEDIALOCALPATH, mi.ZFILESIZE, mi.ZMOVIEDURATION, "
    "mi.ZLATITUDE, mi.ZLONGITUDE, mi.ZTITLE "
    "FROM ZWAMESSAGE m "
    "JOIN target t ON m.ZCHATSESSION = t.ZCHATSESSION "
    "LEFT JOIN ZWAMEDIAITEM mi ON mi.Z_PK = m.ZMEDIAITEM "
    "WHERE m.ZSORT BETWEEN t.ZSORT - ? AND t.ZSORT + ? "
    "AND " + _M_TOMBSTONE_WHERE + " "
    "ORDER BY m.ZSORT ASC"
)


_SQL_CONTEXT_AROUND_STANZA_INCLUDE_DELETED: str = (
    "WITH target AS ("
    "  SELECT Z_PK, ZCHATSESSION, ZSORT, ZPARENTMESSAGE "
    "  FROM ZWAMESSAGE WHERE ZSTANZAID = ?"
    ") "
    "SELECT m.Z_PK, m.ZCHATSESSION, m.ZGROUPMEMBER, m.ZMESSAGETYPE, m.ZISFROMME, "
    "m.ZSORT, m.ZMESSAGEDATE, m.ZFROMJID, m.ZTOJID, m.ZSTANZAID, m.ZTEXT, "
    "m.ZPUSHNAME, m.ZFLAGS, m.ZMEDIAITEM, m.ZPARENTMESSAGE, m.ZSTARRED, "
    "mi.ZMEDIALOCALPATH, mi.ZFILESIZE, mi.ZMOVIEDURATION, "
    "mi.ZLATITUDE, mi.ZLONGITUDE, mi.ZTITLE "
    "FROM ZWAMESSAGE m "
    "JOIN target t ON m.ZCHATSESSION = t.ZCHATSESSION "
    "LEFT JOIN ZWAMEDIAITEM mi ON mi.Z_PK = m.ZMEDIAITEM "
    "WHERE m.ZSORT BETWEEN t.ZSORT - ? AND t.ZSORT + ? "
    "ORDER BY m.ZSORT ASC"
)


# Quote-reply parent lookup — second query of get_message_context.
# Resolves a child stanza's parent row (ZPARENTMESSAGE FK to ZWAMESSAGE.Z_PK).
_SQL_PARENT_BY_STANZA: str = (
    _MESSAGE_SELECT_LIST
    + "WHERE m.Z_PK = (SELECT ZPARENTMESSAGE FROM ZWAMESSAGE WHERE ZSTANZAID = ?)"
)


# Helper: fetch a single ZSTANZAID by Z_PK. Used by ``_row_to_message``
# to populate ``Message.quoted_message_id`` from the ZPARENTMESSAGE FK
# without re-issuing the full row select.
_SQL_STANZA_ID_BY_PK: str = "SELECT ZSTANZAID FROM ZWAMESSAGE WHERE Z_PK = ?"


# Group metadata — joins ZWACHATSESSION (for subject = ZPARTNERNAME) with
# ZWAGROUPINFO (for creator/owner/creation date). Verified live: there is
# NO ZDESCRIPTION / ZSUBJECT column on ZWAGROUPINFO (RESEARCH §"Open
# Questions Q2 RESOLVED" — ``description=None`` always for v0.1).
_SQL_GROUP_INFO: str = (
    "SELECT cs.Z_PK AS chat_id, cs.ZPARTNERNAME AS subject, "
    "gi.ZCREATIONDATE, gi.ZCREATORJID, gi.ZOWNERJID "
    "FROM ZWACHATSESSION cs "
    "LEFT JOIN ZWAGROUPINFO gi ON gi.Z_PK = cs.ZGROUPINFO "
    "WHERE cs.Z_PK = ? "
    "LIMIT 1"
)


# Group members — uses Z_WAGroupMember_byChatSessionIndex (verified live).
_SQL_GROUP_MEMBERS: str = (
    "SELECT ZMEMBERJID, ZCONTACTNAME, ZFIRSTNAME, ZISADMIN, ZISACTIVE "
    "FROM ZWAGROUPMEMBER "
    "WHERE ZCHATSESSION = ? "
    "ORDER BY ZISADMIN DESC, ZCONTACTNAME ASC"
)


# Global / chat-scoped LIKE search (READ-04 v0.1; FTS5 deferred to Phase
# 3). Uses ``(? IS NULL OR col = ?)`` for optional filters per RESEARCH
# §"Search: LIKE Strategy" — single placeholder bound twice in the
# caller. Default include_deleted=False inlines the tombstone filter.
_SQL_LIKE_SEARCH: str = (
    _MESSAGE_SELECT_LIST
    + "WHERE m.ZTEXT IS NOT NULL "
    + "AND LOWER(m.ZTEXT) LIKE LOWER('%' || ? || '%') "
    + "AND "
    + _M_TOMBSTONE_WHERE
    + " "
    + "AND (? IS NULL OR m.ZCHATSESSION = ?) "
    + "AND (? IS NULL OR m.ZFROMJID = ?) "
    + "AND (? IS NULL OR m.ZMESSAGEDATE >= ?) "
    + "AND (? IS NULL OR m.ZMESSAGEDATE <= ?) "
    + "ORDER BY m.ZMESSAGEDATE DESC "
    + "LIMIT ?"
)


_SQL_LIKE_SEARCH_INCLUDE_DELETED: str = (
    _MESSAGE_SELECT_LIST
    + "WHERE m.ZTEXT IS NOT NULL "
    + "AND LOWER(m.ZTEXT) LIKE LOWER('%' || ? || '%') "
    + "AND (? IS NULL OR m.ZCHATSESSION = ?) "
    + "AND (? IS NULL OR m.ZFROMJID = ?) "
    + "AND (? IS NULL OR m.ZMESSAGEDATE >= ?) "
    + "AND (? IS NULL OR m.ZMESSAGEDATE <= ?) "
    + "ORDER BY m.ZMESSAGEDATE DESC "
    + "LIMIT ?"
)


# Doctor support: maximum ``ZMESSAGEDATE`` across the entire DB. Phase 1
# Plan 05 doctor surfaces ``last_message_ts`` from this.
_SQL_LAST_MESSAGE_TS: str = "SELECT MAX(ZMESSAGEDATE) FROM ZWAMESSAGE"


# LID.sqlite lookups — ZWAPHONENUMBERLIDPAIR indexed on both directions.
_SQL_LID_TO_PHONE: str = "SELECT ZPHONENUMBER FROM ZWAPHONENUMBERLIDPAIR WHERE ZLID = ? LIMIT 1"

_SQL_PHONE_TO_LID: str = "SELECT ZLID FROM ZWAPHONENUMBERLIDPAIR WHERE ZPHONENUMBER = ? LIMIT 1"


# ContactsV2.sqlite -> ZWAADDRESSBOOKCONTACT — search by display name
# fragment. Indexed on ZWHATSAPPID / ZPHONENUMBER / ZLID; ZFULLNAME is
# scanned but the table is small (address book size).
_SQL_CONTACTS_LIKE: str = (
    "SELECT ZFULLNAME, ZWHATSAPPID, ZPHONENUMBER, ZLID "
    "FROM ZWAADDRESSBOOKCONTACT "
    "WHERE ZFULLNAME IS NOT NULL "
    "AND LOWER(ZFULLNAME) LIKE LOWER('%' || ? || '%') "
    "ORDER BY ZFULLNAME ASC "
    "LIMIT ?"
)


# ZWACHATSESSION contact-name search — used by search_contacts to find
# chat partners by display name fragment without going to ContactsV2.
_SQL_CHATSESSION_LIKE: str = (
    "SELECT Z_PK, ZCONTACTJID, ZPARTNERNAME, ZLASTMESSAGEDATE, ZLASTMESSAGETEXT "
    "FROM ZWACHATSESSION "
    "WHERE ZREMOVED = 0 "
    "AND ZPARTNERNAME IS NOT NULL "
    "AND LOWER(ZPARTNERNAME) LIKE LOWER('%' || ? || '%') "
    "ORDER BY ZLASTMESSAGEDATE DESC "
    "LIMIT ?"
)

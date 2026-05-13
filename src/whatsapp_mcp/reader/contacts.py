"""Contact reader — search_contacts / resolve_lid_to_phone / resolve_phone_to_lid.

Implements the 6-step dedup recipe from RESEARCH §"Pattern 7" verbatim:

  1. LIKE on ``ZWACHATSESSION.ZPARTNERNAME`` (chat partners with an
     active session) + ``ZWAADDRESSBOOKCONTACT.ZFULLNAME``
     (address-book contacts that may have no chat yet — second
     short-lived RO connection against ``ContactsV2.sqlite``).
  2. For each match, parse ``ZCONTACTJID`` -> :class:`Jid` (kind via
     suffix).
  3. For ``lid``-kind Jids: lookup ``ZWAPHONENUMBERLIDPAIR.ZPHONENUMBER``
     in the third short-lived RO connection against ``LID.sqlite``.
  4. For ``phone``-kind Jids: reverse-lookup the matching LID.
  5. Dedup by ``(phone or lid)`` — merge rows that resolve to the same
     identity into one :class:`Contact` with both representations in
     ``known_identifiers``.
  6. Return up to ``limit`` deduplicated contacts.

RESEARCH §"Open Questions Q4 RESOLVED": when only a ``@lid`` is known
and no phone resolution succeeds, include the contact with
``phone=None`` and ``disambiguation_required=True`` so callers can
filter / surface accordingly.

Three sibling DBs are touched — ``ChatStorage.sqlite`` (the chat
partner pass), ``ContactsV2.sqlite`` (the address-book pass), and
``LID.sqlite`` (the bidirectional dedup probe). Each opens via its
own short-lived ``open_ro`` connection (REL-01 — never hold a
persistent connection across DBs).
"""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass, field

from whatsapp_mcp.models import Contact, Jid
from whatsapp_mcp.paths import (
    resolve_chatstorage_path,
    resolve_contactsv2_path,
    resolve_lid_path,
)
from whatsapp_mcp.reader.connection import open_ro
from whatsapp_mcp.reader.messages import _parse_jid
from whatsapp_mcp.reader.schema_v1 import (
    _SQL_CHATSESSION_LIKE,
    _SQL_CONTACTS_LIKE,
    _SQL_LID_TO_PHONE,
    _SQL_PHONE_TO_LID,
)
from whatsapp_mcp.time import cocoa_to_unix


@dataclass
class _CandidateRow:
    """In-progress contact row collected from the multi-DB scan."""

    display_name: str
    jid: Jid
    chat_id: int | None = None
    last_message_preview: str | None = None
    last_message_ts: int | None = None
    known_identifiers: list[Jid] = field(default_factory=list)


def _lookup_lid_to_phone(conn: sqlite3.Connection, lid: str) -> str | None:
    row = conn.execute(_SQL_LID_TO_PHONE, (lid,)).fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def _lookup_phone_to_lid(conn: sqlite3.Connection, phone: str) -> str | None:
    row = conn.execute(_SQL_PHONE_TO_LID, (phone,)).fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def _enrich_with_lid(candidates: list[_CandidateRow], lid_db_path: str) -> None:
    """Walk every candidate and populate the missing direction via LID.sqlite.

    Mutates ``candidates`` in-place. Operates on a single short-lived
    LID connection to amortize the open cost across the whole batch.
    Failures to open ``LID.sqlite`` (missing / unreadable) are tolerated
    silently — candidates without resolution surface as
    ``disambiguation_required=True`` downstream.
    """
    try:
        with open_ro(lid_db_path) as conn:
            for cand in candidates:
                if cand.jid.kind == "lid" and cand.jid.lid:
                    phone = _lookup_lid_to_phone(conn, cand.jid.lid)
                    if phone:
                        cand.jid = Jid(
                            kind="lid",
                            raw=cand.jid.raw,
                            phone=phone,
                            lid=cand.jid.lid,
                        )
                elif cand.jid.kind == "phone" and cand.jid.phone:
                    lid = _lookup_phone_to_lid(conn, cand.jid.phone)
                    if lid:
                        # Add the @lid representation as a known
                        # identifier so a future reader sees both.
                        cand.known_identifiers.append(
                            Jid(kind="lid", raw=f"{lid}@lid", lid=lid, phone=cand.jid.phone)
                        )
    except sqlite3.OperationalError:
        # LID DB unavailable — fall through; downstream marks
        # unresolved @lid candidates as disambiguation_required.
        return


def _dedup_key(jid: Jid) -> str:
    """Return a stable dedup key for a candidate's primary :class:`Jid`.

    Prefer ``phone`` (cross-representation stable); fall back to ``lid``;
    fall back to ``raw`` (group/broadcast/status JIDs identify
    themselves directly).
    """
    if jid.phone:
        return f"phone:{jid.phone}"
    if jid.lid:
        return f"lid:{jid.lid}"
    return f"raw:{jid.raw}"


def _scan_chat_partners(db_path: str, query: str, limit: int) -> list[_CandidateRow]:
    out: list[_CandidateRow] = []
    with open_ro(db_path) as conn:
        rows = conn.execute(_SQL_CHATSESSION_LIKE, (query, limit)).fetchall()
        for row in rows:
            raw_jid = row["ZCONTACTJID"]
            if not isinstance(raw_jid, str):
                continue
            jid = _parse_jid(raw_jid)
            chat_id_raw = row["Z_PK"]
            last_text_raw = row["ZLASTMESSAGETEXT"]
            last_cocoa = row["ZLASTMESSAGEDATE"]
            out.append(
                _CandidateRow(
                    display_name=str(row["ZPARTNERNAME"] or ""),
                    jid=jid,
                    chat_id=int(chat_id_raw) if chat_id_raw is not None else None,
                    last_message_preview=(
                        str(last_text_raw) if last_text_raw is not None else None
                    ),
                    last_message_ts=(
                        cocoa_to_unix(float(last_cocoa)) if last_cocoa is not None else None
                    ),
                )
            )
    return out


def _scan_address_book(contactsv2_path: str, query: str, limit: int) -> list[_CandidateRow]:
    out: list[_CandidateRow] = []
    try:
        with open_ro(contactsv2_path) as conn:
            rows = conn.execute(_SQL_CONTACTS_LIKE, (query, limit)).fetchall()
            for row in rows:
                full_name = row["ZFULLNAME"]
                wa_id = row["ZWHATSAPPID"]
                phone = row["ZPHONENUMBER"]
                lid = row["ZLID"]

                # Prefer the WhatsApp JID; fall back to a synthesized
                # phone JID when only ZPHONENUMBER is set; fall back to
                # lid+@lid if only ZLID is present.
                primary_jid: Jid
                if isinstance(wa_id, str) and wa_id:
                    primary_jid = _parse_jid(wa_id)
                    if not primary_jid.phone and isinstance(phone, str):
                        primary_jid = Jid(
                            kind=primary_jid.kind,
                            raw=primary_jid.raw,
                            phone=phone,
                            lid=primary_jid.lid,
                        )
                elif isinstance(phone, str) and phone:
                    primary_jid = Jid(
                        kind="phone",
                        raw=f"{phone}@s.whatsapp.net",
                        phone=phone,
                    )
                elif isinstance(lid, str) and lid:
                    primary_jid = Jid(kind="lid", raw=f"{lid}@lid", lid=lid)
                else:
                    continue

                out.append(
                    _CandidateRow(
                        display_name=str(full_name or ""),
                        jid=primary_jid,
                    )
                )
    except sqlite3.OperationalError:
        # ContactsV2 absent / unreadable — degrade silently. The chat
        # partner pass already covers contacts with an active session.
        return out
    return out


def _candidate_to_contact(cand: _CandidateRow) -> Contact:
    needs_disambig = cand.jid.kind == "lid" and cand.jid.phone is None
    return Contact(
        display_name=cand.display_name,
        jid=cand.jid,
        known_identifiers=cand.known_identifiers,
        chat_id=cand.chat_id,
        last_message_preview=cand.last_message_preview,
        last_message_ts=cand.last_message_ts,
        disambiguation_required=needs_disambig,
    )


# ---------------------------------------------------------------------------
# Public async surface
# ---------------------------------------------------------------------------


async def search_contacts(query: str, limit: int = 20) -> list[Contact]:
    """Search contacts by name fragment across chat sessions + address book.

    Implements the 6-step recipe from RESEARCH §"Pattern 7". Three
    short-lived RO connections are opened (ChatStorage, ContactsV2,
    LID); failures to open the sibling DBs degrade gracefully —
    callers see fewer rows but no exception.

    Args:
        query: Substring matched case-insensitively against display
            names. Bound as a SQL parameter (no f-string interpolation).
        limit: Maximum number of deduplicated contacts returned.
    """
    return await asyncio.to_thread(_search_contacts_blocking, query, limit)


def _search_contacts_blocking(query: str, limit: int) -> list[Contact]:
    chats_path = resolve_chatstorage_path()
    contactsv2_path = resolve_contactsv2_path()
    lid_path = resolve_lid_path()

    # Step 1: gather candidates from both DBs.
    chat_candidates = _scan_chat_partners(chats_path, query, limit * 2)
    book_candidates = _scan_address_book(contactsv2_path, query, limit * 2)

    candidates = chat_candidates + book_candidates

    # Step 3+4: enrich via LID lookups (single short-lived connection).
    _enrich_with_lid(candidates, lid_path)

    # Step 5: dedup. Chat-partner pass wins (it carries chat_id +
    # last_message_*).
    by_key: dict[str, _CandidateRow] = {}
    for cand in candidates:
        key = _dedup_key(cand.jid)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = cand
            continue
        # Merge identifiers; prefer the row with a chat_id (richer).
        if existing.chat_id is None and cand.chat_id is not None:
            cand.known_identifiers = list(
                {j.raw: j for j in (existing.known_identifiers + cand.known_identifiers)}.values()
            )
            by_key[key] = cand
        else:
            existing.known_identifiers = list(
                {j.raw: j for j in (existing.known_identifiers + cand.known_identifiers)}.values()
            )

    deduped = list(by_key.values())[:limit]
    return [_candidate_to_contact(c) for c in deduped]


async def resolve_lid_to_phone(lid: str) -> str | None:
    """Return the E.164 phone (without leading ``+``) for a ``ZLID``, or ``None``.

    Plan 04 may decorate this with ``functools.lru_cache``; Phase 1
    ships one-query-per-call as a stable contract.
    """
    db_path = resolve_lid_path()
    return await asyncio.to_thread(_resolve_lid_to_phone_blocking, db_path, lid)


def _resolve_lid_to_phone_blocking(db_path: str, lid: str) -> str | None:
    try:
        with open_ro(db_path) as conn:
            return _lookup_lid_to_phone(conn, lid)
    except sqlite3.OperationalError:
        return None


async def resolve_phone_to_lid(phone: str) -> str | None:
    """Return the ``ZLID`` for an E.164 phone (without leading ``+``), or ``None``."""
    db_path = resolve_lid_path()
    return await asyncio.to_thread(_resolve_phone_to_lid_blocking, db_path, phone)


def _resolve_phone_to_lid_blocking(db_path: str, phone: str) -> str | None:
    try:
        with open_ro(db_path) as conn:
            return _lookup_phone_to_lid(conn, phone)
    except sqlite3.OperationalError:
        return None

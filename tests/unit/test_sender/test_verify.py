"""Unit tests for ``sender.verify`` — SEND-08 / D-21 / D-22.

Covers:

* ``poll_for_outgoing`` finds an existing matching ``ZWAMESSAGE`` row on
  the first poll → returns ZSTANZAID.
* Timeout (no matching row in the budget) → returns ``None`` (soft-fail
  per D-22).
* SQL filters: ``ZMESSAGEDATE > since_cocoa`` (excludes pre-existing
  identical bodies); ``ZISFROMME = 1`` (excludes incoming); chat scoping.
* D-22 exact-match contract: trailing whitespace in body → no match
  (returns None; upstream maps to ``sent_unverified``).
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from whatsapp_mcp.sender import verify
from whatsapp_mcp.time import unix_to_cocoa

# Minimal ZWAMESSAGE schema subset matching the columns ``verify._SQL``
# references. Mirrors the live shape (read-side schema_v1 reference,
# Phase 1 conftest), pared down to the verify-specific predicates.
_ZWAMESSAGE_SCHEMA = """
CREATE TABLE ZWAMESSAGE (
    Z_PK INTEGER PRIMARY KEY,
    ZSTANZAID VARCHAR,
    ZCHATSESSION INTEGER,
    ZISFROMME INTEGER,
    ZTEXT VARCHAR,
    ZMESSAGEDATE REAL,
    ZSORT REAL
)
"""


@pytest.fixture
def verify_db(tmp_path: Path) -> Iterator[str]:
    """Tempfile SQLite with the ZWAMESSAGE columns ``verify._SQL`` touches.

    The schema subset is intentionally narrow — the verifier's SQL only
    references ZSTANZAID, ZCHATSESSION, ZISFROMME, ZTEXT, ZMESSAGEDATE,
    ZSORT. Other ZWAMESSAGE columns (ZFLAGS, ZGROUPMEMBER, etc.) are not
    needed for this test surface.

    Yields the absolute path to the tmp DB; tests insert their own rows.
    """
    db_path = tmp_path / "ChatStorage.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_ZWAMESSAGE_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    yield str(db_path)


def _insert_message(
    db_path: str,
    *,
    pk: int,
    stanza_id: str,
    chat_id: int,
    is_from_me: int,
    text: str,
    message_date_unix: int,
    z_sort: float | None = None,
) -> None:
    """Insert one ZWAMESSAGE row using Unix-seconds time (Cocoa-converted)."""
    cocoa = unix_to_cocoa(message_date_unix)
    sort = z_sort if z_sort is not None else float(message_date_unix)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO ZWAMESSAGE (Z_PK, ZSTANZAID, ZCHATSESSION, "
            "ZISFROMME, ZTEXT, ZMESSAGEDATE, ZSORT) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pk, stanza_id, chat_id, is_from_me, text, cocoa, sort),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Happy path — first-poll hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_finds_existing_outgoing_message_immediately(
    verify_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-inserted matching outgoing row is returned on the first poll."""
    send_started = int(time.time()) - 5  # 5s before send time
    message_ts = send_started + 1  # message recorded after send_started

    _insert_message(
        verify_db,
        pk=1,
        stanza_id="STANZA-X",
        chat_id=42,
        is_from_me=1,
        text="Hello world",
        message_date_unix=message_ts,
    )

    monkeypatch.setattr(verify, "resolve_chatstorage_path", lambda: verify_db)

    result = await verify.poll_for_outgoing(42, "Hello world", float(send_started))
    assert result == "STANZA-X"


# ---------------------------------------------------------------------------
# Timeout soft-fail (D-22)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_returns_none_on_timeout(
    verify_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No matching row → None after ``_MAX_POLLS × _POLL_INTERVAL_SECONDS``.

    Override ``_MAX_POLLS = 4`` and ``_POLL_INTERVAL_SECONDS = 0.01`` so
    the wall-clock is ~40ms instead of the production 10 s budget; the
    full 10 s exercises only at the live integration smoke level (T-02-05-06).
    """
    monkeypatch.setattr(verify, "_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(verify, "_MAX_POLLS", 4)
    monkeypatch.setattr(verify, "resolve_chatstorage_path", lambda: verify_db)

    send_started = int(time.time())
    result = await verify.poll_for_outgoing(42, "no such body", float(send_started))
    assert result is None


# ---------------------------------------------------------------------------
# SQL filter regressions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_ignores_old_messages_before_send_started(
    verify_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ZMESSAGEDATE > since_cocoa`` excludes pre-existing identical bodies."""
    monkeypatch.setattr(verify, "_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(verify, "_MAX_POLLS", 2)
    monkeypatch.setattr(verify, "resolve_chatstorage_path", lambda: verify_db)

    send_started = int(time.time())
    # Insert an OLD row with the same body but BEFORE send_started.
    _insert_message(
        verify_db,
        pk=1,
        stanza_id="OLD-STANZA",
        chat_id=42,
        is_from_me=1,
        text="Hello world",
        message_date_unix=send_started - 100,
    )

    result = await verify.poll_for_outgoing(42, "Hello world", float(send_started))
    # The old row is excluded by the ZMESSAGEDATE > since_cocoa predicate.
    assert result is None


@pytest.mark.asyncio
async def test_poll_ignores_incoming_messages(
    verify_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ZISFROMME = 1`` filter excludes incoming messages with same body."""
    monkeypatch.setattr(verify, "_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(verify, "_MAX_POLLS", 2)
    monkeypatch.setattr(verify, "resolve_chatstorage_path", lambda: verify_db)

    send_started = int(time.time()) - 5
    # Insert an INCOMING row with the same body, AFTER send_started.
    _insert_message(
        verify_db,
        pk=1,
        stanza_id="INCOMING-STANZA",
        chat_id=42,
        is_from_me=0,  # incoming
        text="Hello world",
        message_date_unix=send_started + 1,
    )

    result = await verify.poll_for_outgoing(42, "Hello world", float(send_started))
    assert result is None


@pytest.mark.asyncio
async def test_poll_ignores_other_chats(
    verify_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ZCHATSESSION = ?`` chat scoping excludes other chats with same body."""
    monkeypatch.setattr(verify, "_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(verify, "_MAX_POLLS", 2)
    monkeypatch.setattr(verify, "resolve_chatstorage_path", lambda: verify_db)

    send_started = int(time.time()) - 5
    # Insert an outgoing row in a DIFFERENT chat with the same body.
    _insert_message(
        verify_db,
        pk=1,
        stanza_id="OTHER-CHAT-STANZA",
        chat_id=99,  # different chat
        is_from_me=1,
        text="Hello world",
        message_date_unix=send_started + 1,
    )

    result = await verify.poll_for_outgoing(42, "Hello world", float(send_started))
    assert result is None


@pytest.mark.asyncio
async def test_poll_exact_match_on_ZTEXT_no_normalization(
    verify_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-22 soft-fail: ``ZTEXT = ?`` is exact-match — trailing space → no match."""
    monkeypatch.setattr(verify, "_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(verify, "_MAX_POLLS", 2)
    monkeypatch.setattr(verify, "resolve_chatstorage_path", lambda: verify_db)

    send_started = int(time.time()) - 5
    # Insert a row whose ZTEXT is "Hello world" (no trailing space).
    _insert_message(
        verify_db,
        pk=1,
        stanza_id="EXACT-STANZA",
        chat_id=42,
        is_from_me=1,
        text="Hello world",
        message_date_unix=send_started + 1,
    )

    # The send body has a trailing space — D-22 documented limitation:
    # exact ZTEXT = ? trades false negatives (some sends miss → unverified)
    # for zero false positives (we never claim message_id for a row that
    # was someone else's prior message).
    result = await verify.poll_for_outgoing(42, "Hello world ", float(send_started))
    assert result is None


@pytest.mark.asyncio
async def test_poll_returns_first_match_via_ZSORT_desc(
    verify_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ORDER BY ZSORT DESC LIMIT 1`` returns the newest matching row."""
    monkeypatch.setattr(verify, "_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(verify, "_MAX_POLLS", 2)
    monkeypatch.setattr(verify, "resolve_chatstorage_path", lambda: verify_db)

    send_started = int(time.time()) - 5

    # Two outgoing matching rows — the higher ZSORT must win.
    _insert_message(
        verify_db,
        pk=1,
        stanza_id="OLD-MATCH",
        chat_id=42,
        is_from_me=1,
        text="Hello world",
        message_date_unix=send_started + 1,
        z_sort=100.0,
    )
    _insert_message(
        verify_db,
        pk=2,
        stanza_id="NEW-MATCH",
        chat_id=42,
        is_from_me=1,
        text="Hello world",
        message_date_unix=send_started + 2,
        z_sort=200.0,
    )

    result = await verify.poll_for_outgoing(42, "Hello world", float(send_started))
    assert result == "NEW-MATCH"

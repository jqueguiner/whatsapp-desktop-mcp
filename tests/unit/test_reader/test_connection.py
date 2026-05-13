"""``open_ro`` tests — REL-01 read-only invariant + P3 busy_timeout mitigation.

The reader's connection helper is the structural enforcement of CLAUDE.md
hard rule #3 ("Never write to ChatStorage.sqlite"). These tests assert
the connection is opened read-only via the ``?mode=ro`` URI, refuses
writes, sets ``PRAGMA busy_timeout = 5000``, and does NOT use the
"treat-as-read-only-and-skip-WAL-recovery" URI flag (which would return
stale pages while WhatsApp is actively writing).
"""

from __future__ import annotations

import inspect
import sqlite3

import pytest

from whatsapp_mcp.reader.connection import open_ro


def test_open_ro_succeeds_against_fixture(chatstorage_fixture: str) -> None:
    """The connection opens, ``SELECT 1`` succeeds, close happens cleanly."""
    with open_ro(chatstorage_fixture) as conn:
        row = conn.execute("SELECT 1").fetchone()
        assert row[0] == 1


def test_open_ro_refuses_writes(chatstorage_fixture: str) -> None:
    """Attempting to INSERT inside ``with open_ro(...)`` raises sqlite OperationalError."""
    with open_ro(chatstorage_fixture) as conn:
        with pytest.raises(sqlite3.OperationalError) as exc_info:
            conn.execute("INSERT INTO ZWACHATSESSION (Z_PK, ZSESSIONTYPE) VALUES (999, 0)")
        msg = str(exc_info.value).lower()
        assert "readonly" in msg or "read-only" in msg or "attempt to write" in msg


def test_open_ro_no_immutable_flag_in_uri() -> None:
    """``open_ro`` uses ``?mode=ro``; never the WAL-recovery-skipping ``immutable=1`` flag.

    Inspects the source of :func:`open_ro` to assert the URI string
    construction line uses ``mode=ro`` and never ``immutable``. This
    structural test catches a future "performance optimisation" that
    would break P3 mitigation by returning stale pages while WhatsApp
    is the live writer.
    """
    src = inspect.getsource(open_ro)
    assert "mode=ro" in src, "open_ro must build a ?mode=ro URI"
    assert "immutable" not in src, (
        "open_ro must NOT use the immutable=1 URI flag (P3 — would skip "
        "WAL recovery and return stale/corrupt pages while WhatsApp writes)"
    )


def test_busy_timeout_set(chatstorage_fixture: str) -> None:
    """``open_ro`` sets ``PRAGMA busy_timeout = 5000`` (P3 mitigation)."""
    with open_ro(chatstorage_fixture) as conn:
        row = conn.execute("PRAGMA busy_timeout").fetchone()
        assert row[0] == 5000


def test_open_ro_uses_row_factory(chatstorage_fixture: str) -> None:
    """``conn.row_factory`` is ``sqlite3.Row`` — callers rely on dict-style access."""
    with open_ro(chatstorage_fixture) as conn:
        assert conn.row_factory is sqlite3.Row
        row = conn.execute("SELECT Z_PK, ZSESSIONTYPE FROM ZWACHATSESSION LIMIT 1").fetchone()
        # Row[name] access must work; this is the contract reader/messages.py
        # depends on (e.g. row["ZTEXT"], row["ZSORT"]).
        assert row["Z_PK"] is not None
        assert row["ZSESSIONTYPE"] is not None

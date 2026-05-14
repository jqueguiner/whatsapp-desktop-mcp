"""FTS5 shadow index for ``search_messages`` (Phase 3 D-12..D-18).

A separate SQLite database at
``~/Library/Application Support/whatsapp-desktop-mcp/fts.sqlite`` (mode 0600)
holds an FTS5 virtual table mirroring the message bodies in
``ZWAMESSAGE.ZTEXT``. The sidecar is **lazy-built** on first
``search_messages`` call and **incrementally refreshed** on every
subsequent call. A schema-fingerprint mismatch (``Z_VERSION`` shifted
under us) triggers a **full rebuild**.

The sidecar is a SEPARATE file from the Phase 2
``rate-limit.db`` — different lifecycles, different invariants.
ChatStorage.sqlite is **never** written to (CLAUDE.md hard rule #3 /
REL-05 D-24); the joinback uses the existing
:func:`whatsapp_desktop_mcp.reader.connection.open_ro` helper.

Why a separate sidecar at all
=============================
WhatsApp's own FTS index (``fts/ChatSearchV5f.sqlite``) uses a custom
``wa_tokenizer`` that is only loaded inside WhatsApp.app. Opening that
DB from our Python process raises a tokenizer-not-found error at the
first MATCH query — verified live, see
``.planning/research/PITFALLS.md`` P12. We therefore build our own
shadow index using the stdlib FTS5 ``unicode61 remove_diacritics 2``
tokenizer (matches naïve user expectations: ``café`` matches ``cafe``).

Quote-wrap is a CORRECTNESS invariant
=====================================
The FTS5 ``MATCH`` operator interprets ``*`` ``"`` ``(`` ``)`` ``:``
``-`` ``+`` ``^`` as syntax. A naïve passthrough of a user query
containing any of these characters raises
:class:`sqlite3.OperationalError`. The fix is mandatory:
``fts_query = '"' + query.replace('"', '""') + '"'`` — produces an
FTS5 phrase query (exact phrase, no prefix matching, no operators).
This is also a T-03-01-02 mitigation (Tampering via injected operators).

Joinback strategy
=================
FTS5 returns hits sorted by ``bm25`` rank. We need the full
:class:`Message` shape (with tombstone filter, media, JID dedup) — that
shape lives in ``ChatStorage.sqlite`` via
:func:`whatsapp_desktop_mcp.reader.messages._project_messages`. The joinback
uses ``ZMESSAGEDATE`` (Cocoa epoch) as the foreign key into
``ZWAMESSAGE``. **Known v1.0 limitation:** if two distinct messages
share the same Cocoa-epoch second (collision), both surface in the
joinback result; the FTS hit was for one body but both rows attach.
Empirical observation on the verified-live 84k-row corpus shows zero
collisions for typical message rates. The v1.1 fallback is to switch
to ``ZSTANZAID``-keyed joinback (more robust against body collisions);
deferred per RESEARCH §"Pattern 3" researcher recommendation.

REL-05 D-24 invariant
=====================
This module imports from
:mod:`whatsapp_desktop_mcp.reader.connection`,
:mod:`whatsapp_desktop_mcp.reader.schema_v1`,
:mod:`whatsapp_desktop_mcp.reader.messages`,
:mod:`whatsapp_desktop_mcp.paths`,
:mod:`whatsapp_desktop_mcp.time`, and
:mod:`whatsapp_desktop_mcp.models`. **Zero** imports from
``whatsapp_desktop_mcp.sender.*`` — verified by the structural grep gate in
``tests/unit/test_reader/test_search_fts5.py`` AND the AST walk in
``tests/unit/test_isolation.py``. The Phase 2 D-24 evolution
permits exactly one sender→reader edge (``sender/verify.py``);
Phase 3 adds **no** new sender→reader edges (this file is
reader→reader only).

Logging discipline (P-PHASE0-01)
================================
The first-search rebuild can take 10–30s on a ~100k-message corpus —
silent multi-second pauses are a UX foot-gun. We emit a single
``logger.warning`` (stderr handler — see
``server.py``'s ``logging.basicConfig(stream=sys.stderr, ...)``) when
a full rebuild starts. **Never** ``print`` to stdout: stdout is the
JSON-RPC channel; ruff T201 lint-blocks ``print``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from whatsapp_desktop_mcp.models import Message
from whatsapp_desktop_mcp.paths import resolve_chatstorage_path, resolve_media_root
from whatsapp_desktop_mcp.reader.connection import open_ro
from whatsapp_desktop_mcp.reader.messages import _project_messages
from whatsapp_desktop_mcp.reader.schema_v1 import (
    _M_TOMBSTONE_WHERE,
    _MESSAGE_SELECT_LIST,
    probe_z_version,
)
from whatsapp_desktop_mcp.time import unix_to_cocoa

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module constants — locked by CONTEXT.md D-12, D-13.
# ---------------------------------------------------------------------------

# CONTEXT.md D-12: SEPARATE file from rate-limit.db (different lifecycle,
# different invariants). Both share the same ``~/Library/Application Support/
# whatsapp-desktop-mcp/`` parent directory by convention — see
# ``sender/rate_limit.py`` for the sibling-sidecar pattern.
_DB_PATH: Path = (
    Path.home() / "Library" / "Application Support" / "whatsapp-desktop-mcp" / "fts.sqlite"
)

# CONTEXT.md D-13: tokenizer = unicode61 remove_diacritics 2 (case-fold +
# diacritic-removal so ``café`` matches ``cafe``); body is the only INDEXED
# column — chat_id / sender_jid / message_date_cocoa are UNINDEXED filter
# columns (FTS5 still stores them but does not invert-index them).
_DDL_FTS_VTABLE: str = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5("
    "body, "
    "chat_id UNINDEXED, "
    "sender_jid UNINDEXED, "
    "message_date_cocoa UNINDEXED, "
    "tokenize = 'unicode61 remove_diacritics 2'"
    ");"
)

_DDL_SYNC_STATE: str = (
    "CREATE TABLE IF NOT EXISTS sync_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
)


# ---------------------------------------------------------------------------
# Sidecar connection helper.
# ---------------------------------------------------------------------------


@contextmanager
def open_rw_fts(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Yield a short-lived read-write connection to the FTS sidecar (D-12 / D-16).

    Separate from :func:`whatsapp_desktop_mcp.reader.connection.open_ro` because
    the sidecar is a DIFFERENT file with a DIFFERENT lifecycle — we own
    the writer here. ChatStorage.sqlite is still read-only (CLAUDE.md
    hard rule #3); the joinback in :func:`_search_blocking` uses
    :func:`open_ro`.

    The default ``db_path`` resolves :data:`_DB_PATH` at call time (NOT
    bound at function-definition time) so test monkeypatches of the
    module-level constant are observed without requiring tests to pass
    the path explicitly.

    Sets ``mode=0600`` on the file when it was newly created — applied
    AFTER the connection closes so the chmod sees the final on-disk
    state (T-03-01-01 mitigation, mirrors
    :func:`whatsapp_desktop_mcp.sender.rate_limit._ensure_db`).
    """
    path = Path(db_path) if db_path is not None else _DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    created = not path.exists()
    conn = sqlite3.connect(
        f"file:{path}?mode=rwc",
        uri=True,
        isolation_level=None,
        check_same_thread=False,
        timeout=5.0,
    )
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        yield conn
    finally:
        conn.close()
    if created:
        os.chmod(path, 0o600)


# ---------------------------------------------------------------------------
# sync_state UPSERT helpers.
# ---------------------------------------------------------------------------


def _read_sync_state(fts: sqlite3.Connection, key: str) -> str | None:
    """Return the ``value`` for ``key`` in ``sync_state``, or ``None``."""
    row = fts.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return str(row[0]) if row is not None else None


def _write_sync_state(fts: sqlite3.Connection, key: str, value: str) -> None:
    """Idempotent UPSERT into ``sync_state``."""
    fts.execute(
        "INSERT INTO sync_state(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _ensure_schema(fts: sqlite3.Connection) -> None:
    """Idempotent CREATE for ``messages_fts`` + ``sync_state``."""
    fts.execute(_DDL_FTS_VTABLE)
    fts.execute(_DDL_SYNC_STATE)


# ---------------------------------------------------------------------------
# Build / refresh.
# ---------------------------------------------------------------------------


def _full_rebuild(fts: sqlite3.Connection, ro: sqlite3.Connection, z_version: int) -> int:
    """Drop the FTS table, recreate, and bulk-insert every text-bearing row.

    Returns the row count inserted. Updates ``sync_state['z_version']``
    and ``sync_state['last_seen_z_message_date']``.
    """
    fts.execute("DROP TABLE IF EXISTS messages_fts")
    fts.execute(_DDL_FTS_VTABLE)
    cursor = ro.execute(
        "SELECT ZTEXT, ZCHATSESSION, ZFROMJID, ZMESSAGEDATE FROM ZWAMESSAGE WHERE ZTEXT IS NOT NULL"
    )
    count = 0
    max_date: float = 0.0
    fts.execute("BEGIN")
    try:
        for row in cursor:
            fts.execute(
                "INSERT INTO messages_fts(body, chat_id, sender_jid, message_date_cocoa) "
                "VALUES (?, ?, ?, ?)",
                (row[0], row[1], row[2], row[3]),
            )
            count += 1
            if row[3] is not None and float(row[3]) > max_date:
                max_date = float(row[3])
        _write_sync_state(fts, "z_version", str(z_version))
        _write_sync_state(fts, "last_seen_z_message_date", str(max_date))
        fts.execute("COMMIT")
    except Exception:
        fts.execute("ROLLBACK")
        raise
    return count


def _incremental_refresh(fts: sqlite3.Connection, ro: sqlite3.Connection, last_seen: float) -> int:
    """Insert only rows with ``ZMESSAGEDATE > last_seen``. Returns count.

    Updates ``sync_state['last_seen_z_message_date']`` to the new max.
    """
    cursor = ro.execute(
        "SELECT ZTEXT, ZCHATSESSION, ZFROMJID, ZMESSAGEDATE "
        "FROM ZWAMESSAGE "
        "WHERE ZTEXT IS NOT NULL AND ZMESSAGEDATE > ?",
        (last_seen,),
    )
    count = 0
    max_date: float = last_seen
    fts.execute("BEGIN")
    try:
        for row in cursor:
            fts.execute(
                "INSERT INTO messages_fts(body, chat_id, sender_jid, message_date_cocoa) "
                "VALUES (?, ?, ?, ?)",
                (row[0], row[1], row[2], row[3]),
            )
            count += 1
            if row[3] is not None and float(row[3]) > max_date:
                max_date = float(row[3])
        _write_sync_state(fts, "last_seen_z_message_date", str(max_date))
        fts.execute("COMMIT")
    except Exception:
        fts.execute("ROLLBACK")
        raise
    return count


def _build_or_refresh_blocking(db_path: str) -> None:
    """Bring the FTS sidecar up to date with the live ChatStorage RO snapshot.

    Compares ``sync_state['z_version']`` against
    :func:`probe_z_version` and either does a full rebuild (mismatch or
    first run) or an incremental refresh (versions match).

    The full-rebuild path emits ``logger.warning`` containing the
    substring ``"Building FTS5 shadow index"`` so the user has a UX
    signal during a 10-30s first-search pause (D-15). The logger is
    configured to write to stderr at server-import time
    (``server.py``'s ``logging.basicConfig(stream=sys.stderr, ...)``);
    nothing on this code path touches stdout (JSON-RPC channel,
    P-PHASE0-01).
    """
    with open_rw_fts() as fts:
        _ensure_schema(fts)
        prior_z_str = _read_sync_state(fts, "z_version")
        with open_ro(db_path) as ro:
            current_z = probe_z_version(ro)
            full_rebuild_needed = prior_z_str is None or int(prior_z_str) != current_z
            if full_rebuild_needed:
                logger.warning(
                    "Building FTS5 shadow index — first search may take 10-30s "
                    "for a corpus of ~100k messages. Subsequent searches are sub-second."
                )
                t0 = time.monotonic()
                n = _full_rebuild(fts, ro, current_z)
                logger.info("FTS5 full rebuild: %d rows in %.1fs", n, time.monotonic() - t0)
            else:
                last_seen_str = _read_sync_state(fts, "last_seen_z_message_date") or "0"
                n = _incremental_refresh(fts, ro, float(last_seen_str))
                if n:
                    logger.info("FTS5 incremental refresh: +%d rows", n)


# ---------------------------------------------------------------------------
# Search.
# ---------------------------------------------------------------------------


def _search_blocking(
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
    """Execute the FTS5 MATCH then joinback to ChatStorage for the full row shape.

    Steps:

    1. Quote-wrap the user query so FTS5 MATCH treats it as a phrase
       (T-03-01-02 mitigation — operator chars like ``(`` ``)`` ``*``
       ``"`` ``:`` MUST NOT crash the search).
    2. Convert ``before`` / ``after`` Unix-second bounds to Cocoa epoch
       for the UNINDEXED-column predicate.
    3. Run the FTS5 ``MATCH`` query, ordered by ``bm25(messages_fts)``
       primary, ``message_date_cocoa DESC`` secondary.
    4. Joinback to ChatStorage (RO) by ``ZMESSAGEDATE IN (...)``,
       inlining the tombstone filter via :data:`_M_TOMBSTONE_WHERE`
       when ``include_deleted=False`` (T-03-01-03 mitigation —
       Pitfall 7 closes here, NOT at the FTS5 layer).
    5. Project rows through :func:`_project_messages` (Phase 1 reuse —
       MediaRef resolution + JID/LID dedup).
    """
    # CORRECTNESS INVARIANT: quote-wrap the query so FTS5 MATCH parses
    # it as a single phrase. Embedded ``"`` is escaped by doubling
    # (FTS5 phrase-string quoting rule). NEVER pass raw user input to
    # MATCH — `(test)` would crash with sqlite3.OperationalError without
    # this wrap (Pitfall 1 / T-03-01-02).
    fts_query = '"' + query.replace('"', '""') + '"'

    # The Cocoa-epoch bound conversion mirrors reader/search.py's
    # like_search — same convention so a future unification stays trivial.
    before_cocoa = unix_to_cocoa(before) if before is not None else None
    after_cocoa = unix_to_cocoa(after) if after is not None else None

    # 1) FTS5 search — small result set (limit ≤ 200 enforced by tool layer).
    with open_rw_fts() as fts:
        fts_rows = fts.execute(
            "SELECT chat_id, sender_jid, message_date_cocoa, body "
            "FROM messages_fts "
            "WHERE messages_fts MATCH ? "
            "AND (? IS NULL OR chat_id = ?) "
            "AND (? IS NULL OR sender_jid = ?) "
            "AND (? IS NULL OR message_date_cocoa >= ?) "
            "AND (? IS NULL OR message_date_cocoa <= ?) "
            "ORDER BY bm25(messages_fts), message_date_cocoa DESC "
            "LIMIT ?",
            (
                fts_query,
                chat_id,
                chat_id,
                sender_jid,
                sender_jid,
                after_cocoa,
                after_cocoa,
                before_cocoa,
                before_cocoa,
                limit,
            ),
        ).fetchall()

    if not fts_rows:
        return []

    # 2) Joinback — the cocoa-keyed IN-clause selects the full ZWAMESSAGE
    #    row shape (with media + tombstone filter + JID dedup). v1.0
    #    known limitation: if two messages share the exact same Cocoa
    #    second (collision), both surface; the FTS5 ranking ordered by
    #    one but the joinback returns both. Empirically zero collisions
    #    on the verified-live corpus; v1.1 fallback is ZSTANZAID-keyed
    #    joinback per RESEARCH §"Pattern 3" / A9.
    cocoa_set = sorted({float(r[2]) for r in fts_rows if r[2] is not None})
    if not cocoa_set:
        return []
    placeholders = ",".join("?" for _ in cocoa_set)
    tombstone_clause = "AND " + _M_TOMBSTONE_WHERE + " " if not include_deleted else ""
    sql = (
        _MESSAGE_SELECT_LIST
        + f"WHERE m.ZMESSAGEDATE IN ({placeholders}) "
        + tombstone_clause
        + "ORDER BY m.ZMESSAGEDATE DESC"
    )
    with open_ro(db_path) as ro:
        rows = list(ro.execute(sql, cocoa_set).fetchall())
        return _project_messages(ro, rows, media_root)


# ---------------------------------------------------------------------------
# Public async surface — REL-02 (every blocking call wraps to_thread).
# ---------------------------------------------------------------------------


async def fts5_search(
    query: str,
    chat_id: int | None = None,
    sender_jid: str | None = None,
    before: int | None = None,
    after: int | None = None,
    limit: int = 50,
    include_deleted: bool = False,
) -> list[Message]:
    """Async FTS5 search — mirrors :func:`whatsapp_desktop_mcp.reader.search.like_search` signature.

    Args:
        query: Free-form user query. Quote-wrapped by
            :func:`_search_blocking` before FTS5 MATCH so operator
            characters do not parse as FTS5 syntax.
        chat_id: Optional ``ZWACHATSESSION.Z_PK`` filter.
        sender_jid: Optional raw JID filter.
        before: Optional Unix-seconds upper bound (compared as
            ``message_date_cocoa <= cocoa(before)``).
        after: Optional Unix-seconds lower bound (compared as
            ``message_date_cocoa >= cocoa(after)``).
        limit: Page size; defaults to 50.
        include_deleted: When ``False`` (default), the joinback applies
            the tombstone WHERE clause (Pitfall 7 / T-03-01-03).

    Returns:
        list of :class:`whatsapp_desktop_mcp.models.Message`, ordered by FTS5
        ``bm25`` rank then ``message_date_cocoa DESC``.
    """
    db_path = resolve_chatstorage_path()
    media_root = resolve_media_root()
    return await asyncio.to_thread(
        _search_blocking,
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


async def build_or_refresh() -> None:
    """Bring the FTS sidecar up to date (or full-rebuild on Z_VERSION change).

    Idempotent. Lazy-creates the sidecar at :data:`_DB_PATH` (mode 0600)
    on first call. Subsequent calls are incremental — only rows with
    ``ZMESSAGEDATE > sync_state['last_seen_z_message_date']`` are
    inserted. A schema-fingerprint mismatch
    (``sync_state['z_version']`` vs. live :func:`probe_z_version`)
    triggers a full rebuild and emits a stderr ``logger.warning``.
    """
    db_path = resolve_chatstorage_path()
    await asyncio.to_thread(_build_or_refresh_blocking, db_path)

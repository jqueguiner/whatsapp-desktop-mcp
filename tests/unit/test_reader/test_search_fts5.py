"""Unit tests for ``reader/search_fts5.py`` — Phase 3 Plan 03-01 FTS5 sidecar.

Coverage matrix (mapped to plan ``<behavior>`` block):

- Test 1 — quote-wrap correctness for FTS5 operator characters.
- Test 2 — quote-wrap escapes embedded ``"`` by doubling.
- Test 3 — lazy build creates the sidecar (mode 0600) and inserts every
  text-bearing ZWAMESSAGE row.
- Test 4 — incremental refresh only inserts rows newer than the recorded
  ``last_seen_z_message_date`` and updates the sync_state.
- Test 5 — full rebuild fires when ``z_version`` differs from the live
  ``probe_z_version(ro)`` (CONTEXT.md D-14).
- Test 6 — joinback applies the tombstone WHERE clause when
  ``include_deleted=False`` (Pitfall 7).
- Test 7 — REL-05 grep gate: zero ``whatsapp_mcp.sender`` imports
  (CLAUDE.md hard rule #1 / D-24).
- Test 8 — full rebuild emits ``logger.warning`` containing
  "Building FTS5 shadow index" — captured via caplog. NO stdout bytes.
- Test 9 — search returns empty list (NOT a sqlite3 error) when the
  query has no matches.

T-03-01-02 / T-03-01-03 / T-03-01-04 / T-03-01-06 mitigations are
covered by Tests 1+2 (operator-char + embedded-quote), Test 6 (tombstone
joinback), Test 7 (REL-05 isolation grep), and Test 8 (stderr-only log).

Fixture strategy mirrors the existing ``tests/unit/conftest.py``
``chatstorage_fixture`` — synthetic ChatStorage built directly via
``sqlite3`` so no real WhatsApp DB is touched. ``_DB_PATH`` is
monkeypatched to ``tmp_path / "fts.sqlite"`` so the production sidecar
at ``~/Library/Application Support/whatsapp-mcp/fts.sqlite`` is never
written to during the test run (T-03-01-01 sandbox).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

_COCOA_EPOCH_OFFSET = 978_307_200


def _now_cocoa() -> float:
    return float(int(time.time()) - _COCOA_EPOCH_OFFSET)


_FTS_CHATSTORAGE_SCHEMA: list[str] = [
    "CREATE TABLE Z_METADATA (Z_VERSION INTEGER PRIMARY KEY, Z_UUID VARCHAR, Z_PLIST BLOB)",
    """
    CREATE TABLE ZWACHATSESSION (
        Z_PK INTEGER PRIMARY KEY,
        ZSESSIONTYPE INTEGER,
        ZCONTACTJID VARCHAR,
        ZPARTNERNAME VARCHAR,
        ZLASTMESSAGEDATE TIMESTAMP,
        ZLASTMESSAGETEXT VARCHAR,
        ZUNREADCOUNT INTEGER,
        ZARCHIVED INTEGER,
        ZHIDDEN INTEGER,
        ZGROUPINFO INTEGER,
        ZREMOVED INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE ZWAMESSAGE (
        Z_PK INTEGER PRIMARY KEY,
        ZCHATSESSION INTEGER,
        ZGROUPMEMBER INTEGER,
        ZMESSAGETYPE INTEGER,
        ZISFROMME INTEGER,
        ZSORT REAL,
        ZMESSAGEDATE TIMESTAMP,
        ZFROMJID VARCHAR,
        ZTOJID VARCHAR,
        ZSTANZAID VARCHAR,
        ZTEXT VARCHAR,
        ZPUSHNAME VARCHAR,
        ZFLAGS INTEGER,
        ZMEDIAITEM INTEGER,
        ZPARENTMESSAGE INTEGER,
        ZSTARRED INTEGER
    )
    """,
    """
    CREATE TABLE ZWAMEDIAITEM (
        Z_PK INTEGER PRIMARY KEY,
        ZMEDIALOCALPATH VARCHAR,
        ZFILESIZE INTEGER,
        ZMOVIEDURATION REAL,
        ZLATITUDE REAL,
        ZLONGITUDE REAL,
        ZTITLE VARCHAR
    )
    """,
]


def _seed_minimal(conn: sqlite3.Connection, *, n_text_rows: int = 3) -> list[tuple[int, float]]:
    """Seed Z_METADATA, one chat session, and ``n_text_rows`` text rows.

    Returns ``[(Z_PK, ZMESSAGEDATE), ...]`` in insertion order so tests
    can re-derive expected counts / dates without re-querying.
    """
    now_cocoa = _now_cocoa()
    conn.execute("INSERT INTO Z_METADATA (Z_VERSION) VALUES (1)")
    conn.execute(
        "INSERT INTO ZWACHATSESSION VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            0,
            "33612345678@s.whatsapp.net",
            "Alice",
            now_cocoa,
            "hello",
            0,
            0,
            0,
            None,
            0,
        ),
    )
    rows: list[tuple[int, float]] = []
    for i in range(n_text_rows):
        msg_cocoa = now_cocoa - (i * 60.0)
        z_sort = float(1_000_000 + (n_text_rows - i))
        body = f"meeting summary {i} — quarterly review"
        conn.execute(
            "INSERT INTO ZWAMESSAGE VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                i + 1,
                1,
                None,
                0,  # text
                0,
                z_sort,
                msg_cocoa,
                "33612345678@s.whatsapp.net",
                "me@s.whatsapp.net",
                f"STANZA-FTS5-{i:03d}",
                body,
                "Alice",
                0x01000000,
                None,
                None,
                0,
            ),
        )
        rows.append((i + 1, msg_cocoa))
    return rows


def _add_extra_row(conn: sqlite3.Connection, *, body: str, msg_cocoa: float, z_pk: int) -> None:
    """Insert one extra ZWAMESSAGE with the supplied body / cocoa date / PK."""
    conn.execute(
        "INSERT INTO ZWAMESSAGE VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            z_pk,
            1,
            None,
            0,
            0,
            float(2_000_000 + z_pk),
            msg_cocoa,
            "33612345678@s.whatsapp.net",
            "me@s.whatsapp.net",
            f"STANZA-EXTRA-{z_pk:03d}",
            body,
            "Alice",
            0x01000000,
            None,
            None,
            0,
        ),
    )


def _add_tombstone_row(conn: sqlite3.Connection, *, body: str, z_pk: int) -> float:
    """Insert a ZMESSAGETYPE=14 (deleted-for-everyone) row.

    ZTEXT is set to ``body`` so the FTS index DOES include it on first
    indexing — but the joinback's tombstone WHERE clause MUST drop it
    when ``include_deleted=False`` (Pitfall 7).
    """
    msg_cocoa = _now_cocoa() - 3600.0  # one hour back
    conn.execute(
        "INSERT INTO ZWAMESSAGE VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            z_pk,
            1,
            None,
            14,  # deleted-for-everyone tombstone
            0,
            float(3_000_000 + z_pk),
            msg_cocoa,
            "33612345678@s.whatsapp.net",
            "me@s.whatsapp.net",
            f"STANZA-TOMB-{z_pk:03d}",
            body,
            "Alice",
            0x01000000,
            None,
            None,
            0,
        ),
    )
    return msg_cocoa


def _open_writable(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@pytest.fixture
def fts_chatstorage(tmp_path: Path) -> Path:
    """Synthetic ChatStorage with 3 text rows (no tombstones)."""
    db_path = tmp_path / "ChatStorage.sqlite"
    conn = _open_writable(db_path)
    try:
        for sql in _FTS_CHATSTORAGE_SCHEMA:
            conn.execute(sql)
        _seed_minimal(conn, n_text_rows=3)
        conn.commit()
    finally:
        conn.close()
    return db_path


@pytest.fixture
def fts_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``search_fts5._DB_PATH`` to ``tmp_path / "fts.sqlite"``."""
    from whatsapp_mcp.reader import search_fts5

    sidecar = tmp_path / "fts.sqlite"
    monkeypatch.setattr(search_fts5, "_DB_PATH", sidecar)
    return sidecar


@pytest.fixture
def patched_paths(
    monkeypatch: pytest.MonkeyPatch,
    fts_chatstorage: Path,
    tmp_path: Path,
) -> Path:
    """Repoint ``resolve_chatstorage_path`` and ``resolve_media_root``."""
    import whatsapp_mcp.paths
    from whatsapp_mcp.reader import search_fts5

    media_root = tmp_path / "Message"
    media_root.mkdir()

    monkeypatch.setattr(
        whatsapp_mcp.paths, "resolve_chatstorage_path", lambda: str(fts_chatstorage)
    )
    monkeypatch.setattr(whatsapp_mcp.paths, "resolve_media_root", lambda: str(media_root))
    # search_fts5 imports the resolvers by name at module-load time —
    # patch the local references too.
    if hasattr(search_fts5, "resolve_chatstorage_path"):
        monkeypatch.setattr(search_fts5, "resolve_chatstorage_path", lambda: str(fts_chatstorage))
    if hasattr(search_fts5, "resolve_media_root"):
        monkeypatch.setattr(search_fts5, "resolve_media_root", lambda: str(media_root))
    return fts_chatstorage


# ---------------------------------------------------------------------------
# Test 1 + 2 — quote-wrap correctness.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fts5_search_quote_wraps_operator_chars(
    fts_chatstorage: Path,
    fts_db_path: Path,
    patched_paths: Path,
) -> None:
    """``fts5_search('meeting (tomorrow)')`` must not raise sqlite3.OperationalError.

    Without quote-wrap, FTS5 would parse ``(`` ``)`` as parentheses
    operators and raise. Quote-wrap turns the input into a phrase query.
    """
    from whatsapp_mcp.reader import search_fts5

    # Build the sidecar first (lazy build path).
    await search_fts5.build_or_refresh()
    # Operator-character query — must not raise.
    results = await search_fts5.fts5_search(query="meeting (tomorrow)")
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_fts5_search_quote_wraps_embedded_double_quote(
    fts_chatstorage: Path,
    fts_db_path: Path,
    patched_paths: Path,
) -> None:
    """``fts5_search('he said \"hi\"')`` must not raise.

    Embedded ``"`` is escaped by doubling per the Pattern-3 wrap recipe.
    """
    from whatsapp_mcp.reader import search_fts5

    await search_fts5.build_or_refresh()
    results = await search_fts5.fts5_search(query='he said "hi"')
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Test 3 — lazy build creates sidecar with mode 0600 and indexes every row.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_or_refresh_creates_sidecar_with_mode_0600(
    fts_chatstorage: Path,
    fts_db_path: Path,
    patched_paths: Path,
) -> None:
    from whatsapp_mcp.reader import search_fts5

    assert not fts_db_path.exists()
    await search_fts5.build_or_refresh()
    assert fts_db_path.exists()

    # mode 0600 — owner rw only, no group / other access (T-03-01-01).
    mode = stat.S_IMODE(os.stat(fts_db_path).st_mode)
    assert mode == 0o600, f"expected mode 0600, got {oct(mode)}"

    # Every text-bearing row indexed (3 from _seed_minimal).
    with sqlite3.connect(str(fts_db_path)) as conn:
        (count,) = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()
    assert count == 3


# ---------------------------------------------------------------------------
# Test 4 — incremental refresh.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_incremental_refresh_inserts_only_newer_rows(
    fts_chatstorage: Path,
    fts_db_path: Path,
    patched_paths: Path,
) -> None:
    from whatsapp_mcp.reader import search_fts5

    # First build — indexes the 3 seeded rows.
    await search_fts5.build_or_refresh()
    with sqlite3.connect(str(fts_db_path)) as conn:
        (count_after_first,) = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()
    assert count_after_first == 3

    # Insert ONE new row with a higher ZMESSAGEDATE.
    new_cocoa = _now_cocoa() + 3600.0  # one hour in the future = newer
    bg = sqlite3.connect(str(fts_chatstorage))
    try:
        _add_extra_row(bg, body="brand new message after refresh", msg_cocoa=new_cocoa, z_pk=99)
        bg.commit()
    finally:
        bg.close()

    # Re-call build_or_refresh — should be incremental, not full rebuild.
    await search_fts5.build_or_refresh()
    with sqlite3.connect(str(fts_db_path)) as conn:
        (count_after_second,) = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()
        (last_seen,) = conn.execute(
            "SELECT value FROM sync_state WHERE key = 'last_seen_z_message_date'"
        ).fetchone()
    assert count_after_second == 4, f"expected 4 rows after +1, got {count_after_second}"
    assert float(last_seen) == pytest.approx(new_cocoa)


# ---------------------------------------------------------------------------
# Test 5 — full rebuild on Z_VERSION change.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_rebuild_on_z_version_mismatch(
    fts_chatstorage: Path,
    fts_db_path: Path,
    patched_paths: Path,
) -> None:
    from whatsapp_mcp.reader import search_fts5

    # First build at z_version=1.
    await search_fts5.build_or_refresh()

    # Manually rewrite sync_state.z_version to a stale value.
    with sqlite3.connect(str(fts_db_path)) as conn:
        conn.execute(
            "UPDATE sync_state SET value = '0' WHERE key = 'z_version'",
        )
        conn.commit()
        # Drop one of the indexed rows so we can prove the FTS table got rebuilt
        # (a full rebuild truncates and re-inserts; an incremental would not).
        conn.execute("DELETE FROM messages_fts WHERE rowid = 1")
        conn.commit()
        (count_before,) = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()
    assert count_before == 2

    # Re-call build_or_refresh — z_version mismatch triggers FULL rebuild.
    await search_fts5.build_or_refresh()
    with sqlite3.connect(str(fts_db_path)) as conn:
        (count_after,) = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()
        (z_version,) = conn.execute(
            "SELECT value FROM sync_state WHERE key = 'z_version'"
        ).fetchone()
    # Full rebuild → all 3 rows re-indexed.
    assert count_after == 3
    assert int(z_version) == 1


# ---------------------------------------------------------------------------
# Test 6 — tombstone joinback drops deleted-for-everyone rows.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tombstone_joinback_drops_deleted_rows(
    fts_chatstorage: Path,
    fts_db_path: Path,
    patched_paths: Path,
) -> None:
    """A ZMESSAGETYPE=14 row indexed in FTS must NOT appear in fts5_search.

    The joinback's tombstone WHERE clause filters it out when
    ``include_deleted=False`` (Pitfall 7 — closes T-03-01-03).
    """
    from whatsapp_mcp.reader import search_fts5

    # Add a tombstone row with a unique body BEFORE the first build.
    bg = sqlite3.connect(str(fts_chatstorage))
    try:
        _add_tombstone_row(bg, body="topsecret tombstoned phrase", z_pk=42)
        bg.commit()
    finally:
        bg.close()

    await search_fts5.build_or_refresh()

    # Confirm FTS DOES contain the tombstoned body.
    with sqlite3.connect(str(fts_db_path)) as conn:
        (fts_hit,) = conn.execute(
            "SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH ?",
            ('"topsecret"',),
        ).fetchone()
    assert fts_hit >= 1, "FTS should index the tombstoned body until joinback filter runs"

    # Now the joinback path MUST drop it (default include_deleted=False).
    results = await search_fts5.fts5_search(query="topsecret")
    bodies = [m.body for m in results if m.body]
    assert all("topsecret" not in (b or "") for b in bodies), (
        f"tombstone leaked through joinback: {bodies!r}"
    )


# ---------------------------------------------------------------------------
# Test 7 — REL-05 grep gate.
# ---------------------------------------------------------------------------


def test_rel05_no_sender_imports_in_search_fts5() -> None:
    """``reader/search_fts5.py`` MUST NOT import from ``whatsapp_mcp.sender``.

    Structural (file-level) grep gate. Mirrors the AST-walk in
    ``test_isolation.py`` but is fast / dependency-free.
    """
    src = Path(__file__).resolve().parents[3] / "src" / "whatsapp_mcp" / "reader" / "search_fts5.py"
    content = src.read_text(encoding="utf-8")
    assert "from whatsapp_mcp.sender" not in content
    assert "import whatsapp_mcp.sender" not in content


# ---------------------------------------------------------------------------
# Test 8 — full rebuild emits a stderr log via logger.warning.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_rebuild_emits_stderr_warning(
    fts_chatstorage: Path,
    fts_db_path: Path,
    patched_paths: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A full rebuild MUST emit logger.warning containing 'Building FTS5 shadow index'.

    NEVER print to stdout (P-PHASE0-01 / D-15). caplog captures the
    logging API; the stdout-purity asserter below is a defense-in-depth
    subprocess check.
    """
    from whatsapp_mcp.reader import search_fts5

    caplog.set_level(logging.WARNING, logger="whatsapp_mcp.reader.search_fts5")
    await search_fts5.build_or_refresh()

    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "Building FTS5 shadow index" in r.getMessage()
    ]
    assert warnings, (
        "expected logger.warning containing 'Building FTS5 shadow index'; "
        f"captured: {[r.getMessage() for r in caplog.records]!r}"
    )


def test_full_rebuild_writes_no_stdout_bytes(tmp_path: Path) -> None:
    """Defense-in-depth: a subprocess that triggers a full rebuild must
    write ZERO bytes to stdout. Logging path is stderr (P-PHASE0-01).

    Spawned with ``-c`` so we can monkey-patch the FTS sidecar / chatstorage
    path resolvers cleanly inside the child.
    """
    chat_db = tmp_path / "ChatStorage.sqlite"
    fts_db = tmp_path / "fts.sqlite"
    media_root = tmp_path / "Message"
    media_root.mkdir()

    # Seed the chat DB inside the parent (cheap; subprocess only reads).
    conn = _open_writable(chat_db)
    try:
        for sql in _FTS_CHATSTORAGE_SCHEMA:
            conn.execute(sql)
        _seed_minimal(conn, n_text_rows=2)
        conn.commit()
    finally:
        conn.close()

    script = (
        "import asyncio, pathlib, sys\n"
        "from whatsapp_mcp.reader import search_fts5\n"
        "import whatsapp_mcp.paths as paths\n"
        f"search_fts5._DB_PATH = pathlib.Path({str(fts_db)!r})\n"
        f"paths.resolve_chatstorage_path = lambda: {str(chat_db)!r}\n"
        f"paths.resolve_media_root = lambda: {str(media_root)!r}\n"
        f"search_fts5.resolve_chatstorage_path = lambda: {str(chat_db)!r}\n"
        f"search_fts5.resolve_media_root = lambda: {str(media_root)!r}\n"
        "asyncio.run(search_fts5.build_or_refresh())\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 0, f"subprocess failed: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout == "", (
        f"D-05 / P-PHASE0-01 violation: stdout was non-empty during FTS build: "
        f"stdout={proc.stdout!r}"
    )


# ---------------------------------------------------------------------------
# Test 9 — empty-result query returns [] (NOT a sqlite3 error).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fts5_search_empty_result_returns_list(
    fts_chatstorage: Path,
    fts_db_path: Path,
    patched_paths: Path,
) -> None:
    from whatsapp_mcp.reader import search_fts5

    await search_fts5.build_or_refresh()
    results = await search_fts5.fts5_search(query="this_term_does_not_exist_anywhere_xyz")
    assert results == []

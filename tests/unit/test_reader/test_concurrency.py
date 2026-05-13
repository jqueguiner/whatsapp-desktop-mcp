"""Concurrency stress test — P3 + P8 mitigation (RESEARCH §"Pattern 3").

Spawns N reader coroutines + 1 writer thread against a tempfile WAL
sqlite (NOT the user's WhatsApp DB — REL-01 invariant: never write
to ChatStorage.sqlite, even in tests). Asserts ZERO ``database is
locked`` exceptions across 100 reader iterations while the writer
inserts ~100 rows.

Why this matters: WhatsApp Desktop is the live writer of
ChatStorage.sqlite; our reader opens RO-WAL connections with
``PRAGMA busy_timeout = 5000``. The combined invariant should make
``database is locked`` impossible at the read site. This test is the
in-process empirical evidence that the recipe holds.

The test does NOT use the WhatsApp schema — it exercises sqlite WAL
primitives in isolation against a synthetic ``test_table``. The live
integration suite (``tests/integration/test_live_reader.py``) is the
end-to-end equivalent that hits the real WhatsApp DB.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time

import pytest

_READER_COROUTINES: int = 10
_READS_PER_COROUTINE: int = 10
_WRITER_INSERT_COUNT: int = 100
_WRITER_INTERVAL_SECONDS: float = 0.01


def _writer_thread(
    db_path: str,
    stop_event: threading.Event,
    insert_count_box: list[int],
) -> None:
    """Background writer — INSERTs into ``test_table`` until ``stop_event``.

    Mimics WhatsApp Desktop's role: the live writer of the DB. Uses a
    SEPARATE writable connection (the readers use the project's
    ``open_ro``-equivalent ``mode=ro`` URI). Reports the number of
    successful INSERTs via the mutable ``insert_count_box`` (a list of
    one int — Python doesn't have nullable refs).
    """
    conn = sqlite3.connect(db_path, isolation_level=None, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        for i in range(_WRITER_INSERT_COUNT):
            if stop_event.is_set():
                break
            conn.execute(
                "INSERT INTO test_table (payload, ts) VALUES (?, ?)",
                (f"row {i}", time.time()),
            )
            insert_count_box[0] += 1
            time.sleep(_WRITER_INTERVAL_SECONDS)
    finally:
        conn.close()


def _reader_blocking(db_path: str) -> list[tuple[int, str, float]]:
    """One blocking read — opens a fresh RO connection and SELECTs."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5.0)
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        rows = conn.execute("SELECT id, payload, ts FROM test_table LIMIT 100").fetchall()
        return list(rows)
    finally:
        conn.close()


async def _reader_coroutine(db_path: str, locked_count: list[int]) -> None:
    """Run ``_READS_PER_COROUTINE`` reads via ``asyncio.to_thread``.

    On any ``database is locked`` exception, increments
    ``locked_count[0]``. The test then asserts ``locked_count[0] == 0``.
    """
    for _ in range(_READS_PER_COROUTINE):
        try:
            await asyncio.to_thread(_reader_blocking, db_path)
        except sqlite3.OperationalError as exc:
            if "database is locked" in str(exc).lower() or "locked" in str(exc).lower():
                locked_count[0] += 1
            else:
                # Re-raise unexpected sqlite errors — surfaces as test failure.
                raise


@pytest.mark.asyncio
async def test_concurrent_reads_with_writer(writer_db_fixture: str) -> None:
    """10 reader coroutines * 10 reads each, concurrent with ~100 writer INSERTs."""
    locked_count: list[int] = [0]
    insert_count_box: list[int] = [0]
    stop_event = threading.Event()

    writer = threading.Thread(
        target=_writer_thread,
        args=(writer_db_fixture, stop_event, insert_count_box),
        daemon=True,
    )
    writer.start()

    try:
        await asyncio.gather(
            *[_reader_coroutine(writer_db_fixture, locked_count) for _ in range(_READER_COROUTINES)]
        )
    finally:
        stop_event.set()
        writer.join(timeout=5.0)

    total_reads = _READER_COROUTINES * _READS_PER_COROUTINE
    assert locked_count[0] == 0, (
        f"P3 mitigation regression: {locked_count[0]}/{total_reads} reader "
        f"calls hit `database is locked` while writer thread INSERTed "
        f"{insert_count_box[0]} rows"
    )
    # Sanity: the writer actually did work (otherwise the test is vacuous).
    assert insert_count_box[0] > 0, (
        "writer thread reported zero INSERTs — concurrency stress is vacuous"
    )

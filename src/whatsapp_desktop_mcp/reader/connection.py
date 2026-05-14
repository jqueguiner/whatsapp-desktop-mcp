"""Short-lived read-only WAL connection to ``ChatStorage.sqlite`` (REL-01, P3 mitigation).

Why this exact shape:

- ``?mode=ro`` URI flag — and ONLY ``?mode=ro``: WhatsApp is actively
  writing. The "treat the DB as read-only and skip WAL recovery"
  URI parameter (see SQLite WAL docs) would return stale or corrupt
  pages while a writer is live, so this module never uses it.
  CLAUDE.md hard rule #3 also forbids ever writing to
  ``ChatStorage.sqlite`` — ``?mode=ro`` makes that structural
  (SQLite refuses writes).
- ``busy_timeout=5000``: if WhatsApp holds a brief writer lock during
  checkpoint, retry for up to 5s before SQLITE_BUSY (P3 mitigation).
- ``check_same_thread=False``: required because the connection is opened
  inside ``asyncio.to_thread`` and the same coroutine may dispatch a
  follow-up query on a different worker thread (though our pattern is
  one-shot per tool call, so this is belt-and-braces).
- ``Row`` row factory: gives ``row["ZSTANZAID"]`` accessor in callers.
- Single ``BEGIN`` ... ``COMMIT`` block via ``isolation_level=None`` +
  explicit ``BEGIN`` so the read happens at a single consistent snapshot
  (deferred read transaction; no writer competition because we are RO).
- ``with`` context manager guarantees ``close()`` on every exit path.

VERIFIED LIVE on 2026-05-13: this exact recipe successfully read the
~89 MB user DB while WhatsApp Desktop 26.16.74 was actively writing.
Journal mode confirmed as ``wal``. See RESEARCH §"Pattern 1" for the
verbatim recipe this module lifts.

Async dispatch: every public reader function in sibling modules wraps
its blocking ``_impl`` call in ``asyncio.to_thread`` (REL-02). This
module exposes a synchronous context manager only — the async wrapper
lives in the call site so this file stays trivially testable from
synchronous code (Plan 06 fixtures).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def open_ro(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """Yield a short-lived read-only SQLite connection (REL-01, P3 mitigation).

    Opens ``file:{db_path}?mode=ro`` with ``uri=True``, sets
    ``PRAGMA busy_timeout = 5000`` and the ``sqlite3.Row`` factory,
    runs a single ``BEGIN ... COMMIT`` deferred-read transaction, and
    guarantees ``close()`` on every exit path via the
    :func:`contextlib.contextmanager` decorator.

    Never use the "treat-the-DB-as-read-only-and-skip-WAL-recovery"
    URI flag (CLAUDE.md hard rule #3 — WhatsApp is actively writing;
    that flag would skip WAL recovery and return stale/corrupt pages).
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(
        uri,
        uri=True,
        isolation_level=None,
        check_same_thread=False,
        timeout=5.0,  # connection-level wait for the file lock to settle
    )
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    finally:
        conn.close()

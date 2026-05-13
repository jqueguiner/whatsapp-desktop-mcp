"""Persistent SQLite-backed rate limiter for WhatsApp send attempts (D-11).

Backing store: ``~/Library/Application Support/whatsapp-mcp/rate-limit.db``
(mode ``0o600``). A single append-only ``sends`` table records every
``(ts, chat_id, body_sha256, outcome)`` row produced by a send attempt;
two sliding-window ``COUNT(*)`` queries against the ``ts`` column gate
new sends against the per-minute and per-day budgets.

Why persistence is load-bearing (T-5 restart-bypass defense)
============================================================
The protected resource is the user's WhatsApp account, NOT this MCP
server process. A naive in-memory counter would let an attacker (or a
careless LLM) cycle: send 30 messages, restart the MCP, send 30 more,
restart again, … . The account-ban surface is the *day*, not our
uptime. The SQLite file outlives the process; the sliding-window query
counts everything in the last 60 s / 86_400 s regardless of which
process inserted it.

The peek-and-raise two-phase contract (D-10 alignment)
======================================================
``check_and_reserve`` is a **peek**: it counts existing rows and either
raises :class:`RateLimitExceeded` or returns the remaining budget. It
does NOT insert. Insertion is ``record_outcome``'s job and runs AFTER
the actual send attempt completes (success OR failure). The split lets
a cancelled / declined-elicitation send not burn budget against the
user — only attempts that actually reached the keystroke step pay
against the cap. This matches D-10 ("decline = clean cancellation,
not an error"): a user who said no shouldn't lose budget over it.

The SQL CHECK constraint on ``outcome`` enforces the literal set
``{'sent','sent_unverified','cancelled','rate_limited','error'}``; the
sliding-window query intentionally counts only ``'sent'`` and
``'sent_unverified'``. ``'cancelled'``, ``'rate_limited'``, and
``'error'`` rows are recorded (for the audit-log cross-reference) but
do NOT consume budget.

Bounded environment overrides (D-11 hard maxes)
================================================
``WHATSAPP_MCP_RATE_PER_MIN`` and ``WHATSAPP_MCP_RATE_PER_DAY`` shift
the defaults UP to a point, but values above the hard maxes (20/min,
200/day) are REJECTED with a structured ``ValueError`` at the first
``_resolve_limits`` call so a misconfigured server fails loud rather
than silently disabling the protection (Pitfall 5). Hard maxes are
calibrated against WhatsApp's anti-spam threshold per RESEARCH P14;
raising them is an account-ban risk transfer to the user, NOT a
configuration knob.

CLAUDE.md hard rule #3 — never write to ChatStorage.sqlite
==========================================================
A path-collision bug where ``_DB_PATH`` shadowed
``resolve_chatstorage_path()`` would corrupt WhatsApp's own data
store. The :func:`_check_db_path_distinct` lazy guard is wired at the
top of :func:`_ensure_db` so every DB-touching code path goes through
it exactly once per process. The guard is intentionally LAZY (function
call from ``_ensure_db``) not module-load-time (``assert`` at import):
a future evolution of ``whatsapp_mcp.paths.resolve_chatstorage_path``
that adds Full-Disk-Access probing must not be able to crash the
whole MCP server at import — read-only tools (which never call
``_ensure_db``) keep working, and ``doctor`` can diagnose the path
problem before the user sees a hard failure (W-6 lock).

Engine choice: rollback journal, NOT WAL
========================================
Single-writer + single-reader + low contention → plain rollback
journal is simpler and avoids the ``-wal`` / ``-shm`` sidecar churn
in the user's Application Support directory. WAL would buy nothing
here.

REL-05 D-24 invariant
=====================
This module imports from ``whatsapp_mcp.exceptions`` (for
:class:`RateLimitExceeded` / :class:`InvalidChatId`) and
``whatsapp_mcp.paths`` (for ``resolve_chatstorage_path``, consumed by
the lazy DB-path-distinctness guard). It imports NOTHING from
``whatsapp_mcp.reader.*`` — the project's read-side data tier is
strictly downstream of this guardrail module; only the verifier
sibling (``sender/verify.py``, Plan 02-03) is allowed the
``reader.connection`` edge per the D-24 evolved isolation rule.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from pathlib import Path

from whatsapp_mcp.exceptions import RateLimitExceeded
from whatsapp_mcp.paths import resolve_chatstorage_path

# ---------------------------------------------------------------------------
# Module constants — verbatim per RESEARCH §"Pattern 5".
# ---------------------------------------------------------------------------

_DB_PATH = Path.home() / "Library" / "Application Support" / "whatsapp-mcp" / "rate-limit.db"

_DEFAULT_PER_MIN = 5
_DEFAULT_PER_DAY = 30
_HARD_MAX_PER_MIN = 20
_HARD_MAX_PER_DAY = 200

_ENV_PER_MIN = "WHATSAPP_MCP_RATE_PER_MIN"
_ENV_PER_DAY = "WHATSAPP_MCP_RATE_PER_DAY"

# DDL is plain concatenation (NOT an f-string) so the source stays
# grep-stable for the literal-token acceptance gates and mirrors the
# Phase 1 reader/schema_v1.py style. No interpolation is needed.
_DDL = (
    "CREATE TABLE IF NOT EXISTS sends ("
    "ts INTEGER NOT NULL, "
    "chat_id INTEGER NOT NULL, "
    "body_sha256 TEXT NOT NULL, "
    # CHECK clause kept on a single source line so the literal-token AC
    # grep `outcome TEXT NOT NULL CHECK (outcome IN (...))` matches.
    "outcome TEXT NOT NULL CHECK (outcome IN ('sent','sent_unverified','cancelled','rate_limited','error'))"  # noqa: E501
    ");\n"
    "CREATE INDEX IF NOT EXISTS sends_ts_idx ON sends(ts);"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_limits() -> tuple[int, int]:
    """Resolve ``(per_min, per_day)`` budgets from env, bounded by hard maxes.

    Falls back to :data:`_DEFAULT_PER_MIN` / :data:`_DEFAULT_PER_DAY` when
    the env vars are unset. Raises :class:`ValueError` when either env
    value exceeds the corresponding hard max — refusing to silently
    disable the account-ban floor protection (Pitfall 5 / T-1).

    Called by :func:`_blocking_check_and_reserve` on every check rather
    than memoized at import so a misconfigured override surfaces
    immediately at first-send rather than at a never-reached module-load
    site (the ~5 µs cost of two ``os.environ.get`` lookups + two
    ``int()`` casts is negligible against the surrounding I/O).
    """
    per_min_str = os.environ.get(_ENV_PER_MIN)
    per_day_str = os.environ.get(_ENV_PER_DAY)
    per_min = int(per_min_str) if per_min_str else _DEFAULT_PER_MIN
    per_day = int(per_day_str) if per_day_str else _DEFAULT_PER_DAY
    if per_min > _HARD_MAX_PER_MIN:
        raise ValueError(
            f"{_ENV_PER_MIN}={per_min} exceeds hard max {_HARD_MAX_PER_MIN}; "
            "raising the limit risks WhatsApp account ban. Refusing to start."
        )
    if per_day > _HARD_MAX_PER_DAY:
        raise ValueError(
            f"{_ENV_PER_DAY}={per_day} exceeds hard max {_HARD_MAX_PER_DAY}; "
            "raising the limit risks WhatsApp account ban. Refusing to start."
        )
    return per_min, per_day


def _check_db_path_distinct() -> None:
    """Lazy guard — raise :class:`RuntimeError` if :data:`_DB_PATH` shadows
    WhatsApp's own ``ChatStorage.sqlite`` (CLAUDE.md hard rule #3).

    Called from :func:`_ensure_db` on first DB access, NOT at module
    load. This keeps an import-time path-resolver evolution from killing
    the whole server before ``doctor`` can diagnose (W-6 lock):
    read-only tools that never touch the rate-limit DB keep working
    even if ``resolve_chatstorage_path`` starts to do something
    non-pure in a future refactor.

    The check is string equality on the resolved absolute paths — no
    filesystem I/O of its own.
    """
    if str(_DB_PATH) == resolve_chatstorage_path():
        raise RuntimeError(
            "rate-limit DB shadows ChatStorage.sqlite (CLAUDE.md hard rule #3) — "
            "refusing to operate. Check WHATSAPP_MCP_* env vars or rebuild paths."
        )


def _ensure_db() -> Path:
    """Create :data:`_DB_PATH` (and its parent directory) if absent and
    apply ``mode=0600`` to a freshly created file. Returns the path.

    Idempotent. The first call pays the create cost; every subsequent
    call is two ``Path.exists`` syscalls + an open / executescript on
    a no-op DDL (``CREATE TABLE IF NOT EXISTS`` + ``CREATE INDEX IF
    NOT EXISTS``).
    """
    _check_db_path_distinct()
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    created = not _DB_PATH.exists()
    with sqlite3.connect(f"file:{_DB_PATH}?mode=rwc", uri=True) as conn:
        conn.executescript(_DDL)
    if created:
        os.chmod(_DB_PATH, 0o600)
    return _DB_PATH


def _blocking_check_and_reserve(chat_id: int, body_sha256: str) -> tuple[int, int]:
    """Peek the sliding-window counts and either raise or return remaining.

    Returns ``(remaining_per_min, remaining_per_day)`` on success.
    Raises :class:`RateLimitExceeded` when at or over either budget.

    CRITICAL: does NOT insert into the table. Insertion is
    :func:`_blocking_record`'s job and runs AFTER the send attempt
    completes (success OR failure), so a cancelled send does not burn
    budget against the user (D-10).

    Both ``chat_id`` and ``body_sha256`` arguments are accepted now for
    forward-compat with future per-chat budgeting (currently unused;
    the sliding-window counts are global). The signature is locked.
    """
    per_min, per_day = _resolve_limits()
    db = _ensure_db()
    now = int(time.time())
    with sqlite3.connect(f"file:{db}?mode=rw", uri=True) as conn:
        (cnt_min,) = conn.execute(
            "SELECT COUNT(*) FROM sends WHERE ts > ? AND outcome IN ('sent','sent_unverified')",
            (now - 60,),
        ).fetchone()
        (cnt_day,) = conn.execute(
            "SELECT COUNT(*) FROM sends WHERE ts > ? AND outcome IN ('sent','sent_unverified')",
            (now - 86400,),
        ).fetchone()
    if cnt_min >= per_min:
        raise RateLimitExceeded(
            f"Per-minute send budget exhausted: {cnt_min}/{per_min}. "
            "Retry after the oldest send in the last minute ages out."
        )
    if cnt_day >= per_day:
        raise RateLimitExceeded(
            f"Per-day send budget exhausted: {cnt_day}/{per_day}. "
            f"Retry tomorrow, or raise {_ENV_PER_DAY} (bounded {_HARD_MAX_PER_DAY})."
        )
    return per_min - cnt_min, per_day - cnt_day


def _blocking_record(chat_id: int, body_sha256: str, outcome: str) -> None:
    """Single ``INSERT`` of the outcome row. Idempotency is NOT enforced —
    a duplicate send (same body to same chat in the same second) will
    record two rows, which is the correct behavior for budget counting
    (two attempts → two slots burned)."""
    db = _ensure_db()
    with sqlite3.connect(f"file:{db}?mode=rw", uri=True) as conn:
        conn.execute(
            "INSERT INTO sends (ts, chat_id, body_sha256, outcome) VALUES (?, ?, ?, ?)",
            (int(time.time()), chat_id, body_sha256, outcome),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Public async surface — REL-02 (every blocking DB call wraps to_thread).
# ---------------------------------------------------------------------------


async def check_and_reserve(chat_id: int, body_sha256: str) -> tuple[int, int]:
    """Async wrapper for :func:`_blocking_check_and_reserve` (REL-02)."""
    return await asyncio.to_thread(_blocking_check_and_reserve, chat_id, body_sha256)


async def record_outcome(chat_id: int, body_sha256: str, outcome: str) -> None:
    """Async wrapper for :func:`_blocking_record` (REL-02)."""
    await asyncio.to_thread(_blocking_record, chat_id, body_sha256, outcome)

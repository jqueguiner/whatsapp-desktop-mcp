"""Unit tests for ``sender.rate_limit`` — D-11 / SEND-05 / T-1 / T-5.

Covers:

* ``_resolve_limits`` env-var bounds (hard maxes 20/min, 200/day) +
  ValueError on overshoot (account-ban floor protection).
* ``check_and_reserve`` peek-and-raise contract: does NOT INSERT;
  ``record_outcome`` is the lone INSERT site.
* Sliding-window math: per-minute trip at 5 rows; per-day cap counts
  only ``sent`` / ``sent_unverified`` outcomes (SQL CHECK constraint).
* **MANDATORY regression test**:
  ``test_send_message_rate_limit_persists_across_restart`` —
  simulates module reload preserving the SQLite file at the same path;
  asserts RateLimitExceeded raised on the post-restart
  ``check_and_reserve`` (T-5 restart-bypass mitigation).
"""

from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

from whatsapp_desktop_mcp.exceptions import RateLimitExceeded
from whatsapp_desktop_mcp.sender import rate_limit

# ---------------------------------------------------------------------------
# _resolve_limits — env-var bounds
# ---------------------------------------------------------------------------


def test_resolve_limits_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Env unset → (5, 30) per D-11 defaults."""
    monkeypatch.delenv("WHATSAPP_DESKTOP_MCP_RATE_PER_MIN", raising=False)
    monkeypatch.delenv("WHATSAPP_DESKTOP_MCP_RATE_PER_DAY", raising=False)

    assert rate_limit._resolve_limits() == (5, 30)


def test_resolve_limits_env_override_within_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env vars override defaults when within hard-max bounds."""
    monkeypatch.setenv("WHATSAPP_DESKTOP_MCP_RATE_PER_MIN", "10")
    monkeypatch.setenv("WHATSAPP_DESKTOP_MCP_RATE_PER_DAY", "100")

    assert rate_limit._resolve_limits() == (10, 100)


def test_resolve_limits_rejects_per_min_above_hard_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PER_MIN > 20 → ValueError (Pitfall 5 / account-ban floor protection)."""
    monkeypatch.setenv("WHATSAPP_DESKTOP_MCP_RATE_PER_MIN", "21")
    monkeypatch.delenv("WHATSAPP_DESKTOP_MCP_RATE_PER_DAY", raising=False)

    with pytest.raises(ValueError, match="exceeds hard max"):
        rate_limit._resolve_limits()


def test_resolve_limits_rejects_per_day_above_hard_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PER_DAY > 200 → ValueError."""
    monkeypatch.delenv("WHATSAPP_DESKTOP_MCP_RATE_PER_MIN", raising=False)
    monkeypatch.setenv("WHATSAPP_DESKTOP_MCP_RATE_PER_DAY", "201")

    with pytest.raises(ValueError, match="exceeds hard max"):
        rate_limit._resolve_limits()


# ---------------------------------------------------------------------------
# check_and_reserve / record_outcome — peek-and-raise + insert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_and_reserve_does_not_insert(tmp_rate_limit_db: Path) -> None:
    """``check_and_reserve`` is a PEEK — no row written."""
    # First call: empty DB; should return budget (5, 30).
    rem_min, rem_day = await rate_limit.check_and_reserve(42, "a" * 64)
    assert rem_min == 5
    assert rem_day == 30

    # Inspect the DB — zero rows in ``sends``.
    with sqlite3.connect(str(tmp_rate_limit_db)) as conn:
        (count,) = conn.execute("SELECT COUNT(*) FROM sends").fetchone()
    assert count == 0


@pytest.mark.asyncio
async def test_record_outcome_inserts_one_row(tmp_rate_limit_db: Path) -> None:
    """``record_outcome`` inserts exactly one row."""
    await rate_limit.record_outcome(42, "a" * 64, "sent")

    with sqlite3.connect(str(tmp_rate_limit_db)) as conn:
        rows = conn.execute("SELECT chat_id, body_sha256, outcome FROM sends").fetchall()
    assert len(rows) == 1
    assert rows[0] == (42, "a" * 64, "sent")


@pytest.mark.asyncio
async def test_rate_limit_minute_window_trips_at_per_min(
    tmp_rate_limit_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5 ``sent`` outcomes within the last minute → next check raises."""
    monkeypatch.delenv("WHATSAPP_DESKTOP_MCP_RATE_PER_MIN", raising=False)
    monkeypatch.delenv("WHATSAPP_DESKTOP_MCP_RATE_PER_DAY", raising=False)

    # Record 5 "sent" outcomes against the tmp DB.
    for _ in range(5):
        await rate_limit.record_outcome(42, "a" * 64, "sent")

    # 6th attempt: peek sees 5 rows in the last-minute window → trip.
    with pytest.raises(RateLimitExceeded, match="Per-minute"):
        await rate_limit.check_and_reserve(42, "b" * 64)


@pytest.mark.asyncio
async def test_rate_limit_day_window_counts_only_sent_outcomes(
    tmp_rate_limit_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """30 cancelled outcomes do NOT trip the daily limit (D-10 + SQL CHECK).

    The SQL filter ``outcome IN ('sent','sent_unverified')`` in
    :func:`_blocking_check_and_reserve` ignores ``cancelled`` /
    ``rate_limited`` / ``error`` rows. So a user who declines 30
    elicitations does NOT burn against the daily budget.
    """
    monkeypatch.delenv("WHATSAPP_DESKTOP_MCP_RATE_PER_MIN", raising=False)
    monkeypatch.delenv("WHATSAPP_DESKTOP_MCP_RATE_PER_DAY", raising=False)

    # 30 cancelled rows.
    for _ in range(30):
        await rate_limit.record_outcome(42, "a" * 64, "cancelled")

    # Peek the budget — should report 5/30 remaining (cancelled rows
    # exist but don't count). Returns the per-min / per-day remaining.
    rem_min, rem_day = await rate_limit.check_and_reserve(42, "b" * 64)
    assert rem_min == 5
    assert rem_day == 30


# ---------------------------------------------------------------------------
# MANDATORY regression — T-5 persistence across simulated restart
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_rate_limit_persists_across_restart(
    tmp_rate_limit_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MANDATORY (CONTEXT.md §Specifics): rate-limit DB survives a simulated module reload.

    The protected resource is the user's WhatsApp account, NOT this MCP
    server process. A naive in-memory counter would let an attacker
    cycle: send 5 messages, restart the MCP, send 5 more, … . The
    account-ban surface is the *day*, not our uptime. The SQLite file
    outlives the process; the sliding-window query counts everything
    in the last 60 s / 86_400 s regardless of which process inserted it.

    This test proves T-5 by:

    1. Recording 5 ``sent`` outcomes against the tmp DB.
    2. Forcibly deleting ``whatsapp_desktop_mcp.sender.rate_limit`` from
       ``sys.modules`` and re-importing it (simulates a server restart
       — module state reset but the SQLite file persists at the same path).
    3. Re-pointing the freshly-imported module's ``_DB_PATH`` at the
       SAME tmp file (the path is what the production code would
       see on a real restart).
    4. Asserting ``check_and_reserve`` raises ``RateLimitExceeded`` —
       the post-restart count is still 5/5 against the per-minute
       budget.
    """
    monkeypatch.delenv("WHATSAPP_DESKTOP_MCP_RATE_PER_MIN", raising=False)
    monkeypatch.delenv("WHATSAPP_DESKTOP_MCP_RATE_PER_DAY", raising=False)

    # Step 1 — record 5 sent outcomes against the tmp DB.
    for _ in range(5):
        await rate_limit.record_outcome(42, "a" * 64, "sent")

    # Confirm 5 rows on disk before the restart.
    with sqlite3.connect(str(tmp_rate_limit_db)) as conn:
        (count_before,) = conn.execute("SELECT COUNT(*) FROM sends WHERE outcome='sent'").fetchone()
    assert count_before == 5

    # Step 2 — simulate module reload. Snapshot the original module so
    # we can restore it after the test (other tests still import the
    # module by name; leaving sys.modules in a re-imported state may
    # alter the global ``_DB_PATH`` initial value seen by sibling tests).
    original_module = sys.modules["whatsapp_desktop_mcp.sender.rate_limit"]
    del sys.modules["whatsapp_desktop_mcp.sender.rate_limit"]
    try:
        fresh_rate_limit = importlib.import_module("whatsapp_desktop_mcp.sender.rate_limit")

        # Step 3 — re-point _DB_PATH on the fresh module to the SAME tmp file.
        monkeypatch.setattr(fresh_rate_limit, "_DB_PATH", tmp_rate_limit_db)

        # Step 4 — the fresh module sees the persisted SQLite rows; the
        # sliding-window count is still 5 → check_and_reserve raises.
        with pytest.raises(RateLimitExceeded, match="Per-minute"):
            await fresh_rate_limit.check_and_reserve(42, "b" * 64)
    finally:
        # Restore the original module reference so sibling tests still
        # see the pre-reload module (otherwise pytest-collected tests
        # that imported ``from whatsapp_desktop_mcp.sender import rate_limit``
        # at module load now reference a stale module not in sys.modules).
        sys.modules["whatsapp_desktop_mcp.sender.rate_limit"] = original_module


# ---------------------------------------------------------------------------
# Lazy DB-path-distinctness guard (W-6 lock)
# ---------------------------------------------------------------------------


def test_check_db_path_distinct_passes_when_paths_differ(
    tmp_rate_limit_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity: when _DB_PATH != resolve_chatstorage_path, the guard passes."""
    # See ``test_check_db_path_distinct_raises_when_paths_collide`` —
    # the persistence-regression test reloads the module, so pulling
    # the live module from sys.modules is the robust pattern.
    import sys as _sys

    rl_live = _sys.modules["whatsapp_desktop_mcp.sender.rate_limit"]
    monkeypatch.setattr(rl_live, "_DB_PATH", tmp_rate_limit_db)
    monkeypatch.setattr(
        rl_live,
        "resolve_chatstorage_path",
        lambda: "/tmp/nonexistent-chatstorage.sqlite",
    )
    # Should NOT raise.
    rl_live._check_db_path_distinct()


def test_check_db_path_distinct_raises_when_paths_collide(
    tmp_rate_limit_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLAUDE.md hard rule #3: if _DB_PATH == ChatStorage path, RuntimeError.

    The W-6 lock guarantees this is a LAZY check (function call, not
    module-load assert); we exercise the function directly.
    """
    # The persistence test deleted and re-imported the module; sys.modules
    # was restored, but the test-module-level ``rate_limit`` symbol may
    # still bind the original module instance. Pull the live module from
    # sys.modules to ensure we're inspecting the same object that
    # ``check_and_reserve`` consults at runtime.
    import sys as _sys

    rl_live = _sys.modules["whatsapp_desktop_mcp.sender.rate_limit"]
    # The fixture monkeypatch sets _DB_PATH on the original module
    # reference (the one imported at this test module's load). Ensure
    # the live module sees the same patched _DB_PATH.
    monkeypatch.setattr(rl_live, "_DB_PATH", tmp_rate_limit_db)
    monkeypatch.setattr(
        rl_live,
        "resolve_chatstorage_path",
        lambda: str(tmp_rate_limit_db),
    )

    with pytest.raises(RuntimeError, match="ChatStorage"):
        rl_live._check_db_path_distinct()

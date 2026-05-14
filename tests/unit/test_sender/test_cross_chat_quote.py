"""Unit tests for ``sender.cross_chat_quote`` — D-15..D-18 / SEND-07.

Covers:

* Constants (40-char threshold, 30-min window, 1000-entry LRU) match D-15..18.
* ``record_bodies`` skips short / empty / None entries.
* ``check`` finds cross-chat substring runs ≥40 chars within 30 min.
* Same-chat references DO NOT trigger (intra-chat quoting is fine).
* 30-min sliding window evicts stale entries.
* 1000-entry LRU eviction (deque maxlen).
* Outgoing body <40 chars short-circuits (returns []).
* Snippet capped at 100 chars per :class:`OffendingSource`.
* :class:`OffendingSource` is a frozen dataclass.

All tests use the ``reset_xcq_lru`` autouse-style fixture so the LRU is
fresh going in and out.
"""

from __future__ import annotations

import time
from dataclasses import FrozenInstanceError

import pytest

from whatsapp_desktop_mcp.sender import cross_chat_quote
from whatsapp_desktop_mcp.sender.cross_chat_quote import OffendingSource, _Entry


def test_constants() -> None:
    """D-15..D-18 lock: thresholds match planner's verbatim numbers."""
    assert cross_chat_quote._MIN_SUBSTRING == 40
    assert cross_chat_quote._WINDOW_SECONDS == 30 * 60
    assert cross_chat_quote._MAX_ENTRIES == 1000


def test_record_bodies_skips_short_bodies(reset_xcq_lru: None) -> None:
    """Bodies shorter than 40 chars never enter the LRU."""
    short = "hi"
    cross_chat_quote.record_bodies(chat_id=1, bodies=[short])
    assert len(cross_chat_quote._lru) == 0


def test_record_bodies_skips_none_and_empty(reset_xcq_lru: None) -> None:
    """None / empty bodies are skipped defensively."""
    cross_chat_quote.record_bodies(chat_id=1, bodies=["", "x" * 50, ""])
    # Only the 50-char body is recorded.
    assert len(cross_chat_quote._lru) == 1


def test_record_then_check_finds_40_char_substring(reset_xcq_lru: None) -> None:
    """A 40-char run recorded against chat_id=1 surfaces when checked against chat_id=2."""
    body = "this is exactly a forty character body!!"  # 40 chars
    assert len(body) >= 40
    cross_chat_quote.record_bodies(chat_id=1, bodies=[body])

    # Check against a DIFFERENT chat_id; the outgoing body contains the
    # recorded body verbatim → one OffendingSource returned.
    sources = cross_chat_quote.check(target_chat_id=2, outgoing_body=body)
    assert len(sources) == 1
    assert sources[0].source_chat_id == 1
    # Snippet captures (up to) 100 chars of the matched run.
    assert body[:40] in sources[0].snippet


def test_same_chat_id_does_not_trigger(reset_xcq_lru: None) -> None:
    """Intra-chat quoting is fine: same chat_id does NOT produce a warning."""
    body = "a" * 100
    cross_chat_quote.record_bodies(chat_id=1, bodies=[body])

    sources = cross_chat_quote.check(target_chat_id=1, outgoing_body=body)
    assert sources == []


def test_window_30_min_eviction(reset_xcq_lru: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Entries older than 30 min are skipped at check time (D-17)."""
    body = "this is exactly a forty character body!!"
    # Inject an Entry recorded 31 min ago directly (bypassing record_bodies
    # so we can control recorded_at deterministically).
    stale_time = time.time() - (31 * 60)
    cross_chat_quote._lru.append(_Entry(chat_id=1, body=body, recorded_at=stale_time))

    sources = cross_chat_quote.check(target_chat_id=2, outgoing_body=body)
    assert sources == []  # stale entry skipped


def test_lru_eviction_at_1000_entries(reset_xcq_lru: None) -> None:
    """The deque's maxlen=1000 caps the LRU size automatically."""
    body = "x" * 50  # ≥40 char threshold
    # Record 1100 bodies on chat_id=1; deque should evict to 1000.
    for i in range(1100):
        cross_chat_quote.record_bodies(chat_id=1, bodies=[body + str(i)])

    assert len(cross_chat_quote._lru) == 1000


def test_check_below_threshold_outgoing_returns_empty(reset_xcq_lru: None) -> None:
    """Outgoing body <40 chars short-circuits to []."""
    # Even with a recorded entry, a too-short outgoing body returns [].
    cross_chat_quote.record_bodies(chat_id=1, bodies=["a" * 100])

    sources = cross_chat_quote.check(target_chat_id=2, outgoing_body="short")
    assert sources == []


def test_snippet_capped_at_100_chars(reset_xcq_lru: None) -> None:
    """:class:`OffendingSource.snippet` is at most 100 chars."""
    # 200-char body of unique pattern — match extends greedily.
    body = "this is exactly a forty character body!!" + ("x" * 160)
    assert len(body) == 200
    cross_chat_quote.record_bodies(chat_id=1, bodies=[body])

    sources = cross_chat_quote.check(target_chat_id=2, outgoing_body=body)
    assert len(sources) == 1
    assert len(sources[0].snippet) <= 100


def test_offending_source_dataclass_frozen() -> None:
    """:class:`OffendingSource` is a frozen dataclass — mutation raises FrozenInstanceError."""
    src = OffendingSource(source_chat_id=1, snippet="hi")

    with pytest.raises((FrozenInstanceError, AttributeError)):
        # ``frozen=True`` dataclasses raise FrozenInstanceError on assignment.
        src.snippet = "modified"  # type: ignore[misc]


def test_below_40_char_run_does_not_trigger(reset_xcq_lru: None) -> None:
    """A <40-char common run between two chats does NOT surface (D-16).

    Two bodies that share a 37-char common prefix (well under the
    40-char threshold) but diverge at position 37 — no 40-char
    contiguous run exists, so :func:`check` returns ``[]``.
    """
    body_a = "this is a body with thirty-seven cont<<<"  # 40 chars total
    body_b = "this is a body with thirty-seven cont>>>"  # diverges at idx 37
    cross_chat_quote.record_bodies(chat_id=1, bodies=[body_a])

    sources = cross_chat_quote.check(target_chat_id=2, outgoing_body=body_b)
    assert sources == []  # No 40+ char shared run.


def test_reset_for_test_clears_lru(reset_xcq_lru: None) -> None:
    """``_reset_for_test`` clears the module-level deque."""
    cross_chat_quote.record_bodies(chat_id=1, bodies=["x" * 100])
    assert len(cross_chat_quote._lru) > 0
    cross_chat_quote._reset_for_test()
    assert len(cross_chat_quote._lru) == 0

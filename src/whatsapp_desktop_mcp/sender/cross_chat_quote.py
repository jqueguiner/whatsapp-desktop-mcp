"""Session-scoped cross-chat-quote heuristic (D-15..D-18, SEND-07).

In-memory LRU of ``(chat_id, body, recorded_at)`` tuples. The four
read tools that surface message bodies (``read_chat``,
``extract_recent``, ``search_messages``, ``get_message_context``)
call :func:`record_bodies` AFTER projecting messages but BEFORE
returning to the LLM client; the send tool calls :func:`check`
during confirmation-prompt construction to surface any cross-chat
substring overlap as a warning in the elicitation.

Why a heuristic and not a hard block (D-18)
============================================
The user may legitimately be forwarding a quote between chats — the
heuristic surfaces as a WARNING in the elicitation prompt, not a
refusal. The text reads "Body contains a 47-char run from chat
'Work' — confirm cross-chat reference is intentional." The user
accepts or declines.

Why 40-char threshold (D-16)
============================
Below 40 chars, common phrases dominate the false-positive surface:
"got it thanks", "ok see you", "sounds good", "I'm on my way", any
boilerplate signature. Above 80 chars, the obvious "I'm copying that
thing from the other chat into this one" attack slips through. 40
char is the empirical break-even point: a 40-char contiguous run is
distinctive enough that an accidental cross-chat match is rare, but
short enough that real cross-tenant prompt-injection lifts (which
the LLM helpfully relays verbatim) still trip.

Why 30-min window (D-17)
========================
Bounds how long a quoted snippet stays "fresh" for the heuristic.
30 min is roughly the timescale of an LLM agent's working memory —
content read >30 min ago is unlikely to be the source of a
within-this-conversation prompt-injection lift. Stale entries are
not actively pruned (the deque ``maxlen`` handles eviction); they
are simply skipped at :func:`check` time by the
``now - recorded_at > _WINDOW_SECONDS`` predicate.

Why in-memory only — no persistence (D-17)
==========================================
A server restart implies a fresh trust context for prompt-injection
defense. Carrying stale cross-tenant correlations across restarts
would inflate false positives without buying real safety; the new
LLM session reads the messages it cares about fresh and re-populates
the LRU.

LRU bounds (D-15)
=================
``maxlen=1000`` × typical ~500-char body = ~500 KB ceiling on this
module's memory footprint. Deque's automatic eviction handles
overflow with no explicit code path.

Threadsafe-ish under a single asyncio event loop
================================================
The module-level :data:`_lru` is mutated only from
:func:`record_bodies` (single point of insertion) and snapshotted by
:func:`check` via ``list(_lru)`` before iteration. Under a single
event loop (the project's runtime model — REL-02), interleaved
co-routines hitting the deque don't see torn state. A multi-thread
deployment would need an explicit ``threading.Lock``; v0.1 stays
single-loop.

Plan 02-04 read-tool integration sites
======================================
``read_chat``, ``extract_recent``, ``search_messages``, and
``get_message_context`` each gain one line after projection:
``cross_chat_quote.record_bodies(chat_id, [m.body for m in messages
if m.body])``. The other read tools (``list_chats``,
``get_chat_metadata``, ``search_contacts``) do NOT call
:func:`record_bodies` — they don't return message bodies, so they
can't be the source of a cross-chat lift.

REL-05 / module isolation
=========================
This module imports NOTHING from ``whatsapp_desktop_mcp.*`` — pure stdlib
(``collections``, ``dataclasses``, ``time``). The :class:`OffendingSource`
DATACLASS defined here is the lightweight read-only attribute
container used internally and by the elicitation prompt builder; the
PYDANTIC re-shape of the same concept lives in
``whatsapp_desktop_mcp.models.send.OffendingSource`` and is the public
SendResult-serialization surface. The two are connected by the
``offending_source_to_pydantic`` bridge helper in ``models.send``
(W-2 boundary contract).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Module constants — verbatim per RESEARCH §"Pattern 7".
# ---------------------------------------------------------------------------

_MAX_ENTRIES = 1000
_WINDOW_SECONDS = 30 * 60  # 30-minute sliding window per D-17
_MIN_SUBSTRING = 40  # ≥40-char contiguous match threshold per D-16


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Entry:
    """One LRU row: (source chat_id, full body, monotonic-ish wall clock).

    Frozen so the deque can't be mutated through a captured reference.
    Recorded_at uses ``time.time()`` (wall clock, seconds since epoch) —
    monotonic-clock isn't needed because the only operation that
    compares it is the ``now - recorded_at > _WINDOW_SECONDS`` predicate
    in :func:`check`, which tolerates a couple of seconds of clock drift.
    """

    chat_id: int
    body: str
    recorded_at: float


@dataclass(frozen=True)
class OffendingSource:
    """Public read-only surface for one cross-chat-quote hit.

    Plan 02-03's elicitation builder consumes this to construct the
    warning line in the confirmation prompt. The PYDANTIC re-shape
    (for SendResult serialization) lives in
    ``whatsapp_desktop_mcp.models.send.OffendingSource``; convert with
    ``offending_source_to_pydantic`` at the SendResult-return
    boundary.

    ``snippet`` is the first 100 chars of the offending contiguous
    substring — enough context for the user to recognize the source
    chat without the full body.
    """

    source_chat_id: int
    snippet: str


# Module-level deque acts as the LRU. Single event loop → no lock needed.
_lru: deque[_Entry] = deque(maxlen=_MAX_ENTRIES)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_bodies(chat_id: int, bodies: list[str]) -> None:
    """Record a batch of message bodies against the source ``chat_id``.

    Plan 02-04 read-tool integration site: each read tool that
    surfaces message text calls this once per response with the list
    of bodies it returned, so the LRU is populated as the LLM reads.

    Bodies shorter than :data:`_MIN_SUBSTRING` are skipped — they
    can't trigger a later :func:`check` match (the threshold predicate
    rejects them upfront). Empty / None / non-string bodies are also
    skipped defensively.
    """
    now = time.time()
    for body in bodies:
        if body and len(body) >= _MIN_SUBSTRING:
            _lru.append(_Entry(chat_id=chat_id, body=body, recorded_at=now))


def check(target_chat_id: int, outgoing_body: str) -> list[OffendingSource]:
    """Find ≥40-char shared substring runs between ``outgoing_body`` and any
    LRU entry from a DIFFERENT ``chat_id`` within the 30-min window.

    Returns a list of :class:`OffendingSource` warnings — empty when no
    cross-chat overlap is detected. Caller (Plan 02-03's elicitation
    builder) surfaces these in the confirmation prompt; user
    accepts or declines.

    Implementation: snapshot :data:`_lru` via ``list(_lru)`` to avoid
    mutation-during-iteration (a concurrent ``record_bodies`` from a
    different coroutine would otherwise raise ``RuntimeError`` on the
    underlying deque). For each entry: skip same-chat hits (intra-chat
    quoting is fine), skip stale entries (recorded_at older than
    30 min), then probe for a shared contiguous substring of length
    ≥ :data:`_MIN_SUBSTRING`. First-hit wins per source entry — we
    surface existence, not the absolute-longest run.

    Performance: naive O(n · m) substring scan. With LRU bounded at
    1000 entries × typical 500-char body × outgoing 200-char body, the
    worst case is ~100 K char comparisons total — sub-millisecond on
    Python 3.12. The ``len(outgoing_body) < _MIN_SUBSTRING`` short-circuit
    handles the common "the user is sending an emoji / 5-char ack" case
    in O(1).
    """
    if len(outgoing_body) < _MIN_SUBSTRING:
        return []
    now = time.time()
    found: list[OffendingSource] = []
    for entry in list(_lru):
        if entry.chat_id == target_chat_id:
            continue
        if now - entry.recorded_at > _WINDOW_SECONDS:
            continue
        match = _longest_shared_substring(outgoing_body, entry.body, _MIN_SUBSTRING)
        if match is not None:
            found.append(OffendingSource(source_chat_id=entry.chat_id, snippet=match[:100]))
    return found


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _longest_shared_substring(a: str, b: str, min_len: int) -> str | None:
    """Return any shared contiguous substring of length ≥ ``min_len``, or
    None.

    Naive sliding-window scan: slide a window of size ``min_len`` across
    ``a``; for each starting position, check Python's native ``in``
    operator against ``b``. First hit wins (existence, not
    absolute-longest); on a hit, greedy-extend the right edge while the
    extended chunk still appears in ``b`` so the caller gets a
    contextful snippet rather than a bare 40-char run.

    Both inputs shorter than ``min_len`` → no match by construction.
    """
    if len(a) < min_len or len(b) < min_len:
        return None
    for i in range(len(a) - min_len + 1):
        chunk = a[i : i + min_len]
        if chunk in b:
            j = i + min_len
            while j < len(a) and a[i : j + 1] in b:
                j += 1
            return a[i:j]
    return None


def _reset_for_test() -> None:
    """Test-only helper to clear the module-level LRU between cases.

    Plan 02-05's unit tests call this in setup so each case starts
    with an empty LRU. Production callers MUST NOT touch this; the
    only sanctioned mutations of :data:`_lru` from outside the
    module are via :func:`record_bodies`.
    """
    _lru.clear()

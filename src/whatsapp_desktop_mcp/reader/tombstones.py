"""Tombstone predicate for soft-deleted messages (READ-08, P10 mitigation).

Empirical decision rule from live distribution on the user's Mac
(2026-05-13, RESEARCH §"Pattern 6"): a row is tombstoned if EITHER

  (a) ``ZMESSAGETYPE == 14`` (deleted-for-everyone), OR
  (b) ``ZFLAGS`` has the high-bit set in the ``0x05000000`` pattern AND
      ``ZTEXT IS NULL``.

Confirmed live counts on the user's machine:

- ``ZMESSAGETYPE = 14``: 532 rows
- ``ZFLAGS & 0xFF000000 == 0x05000000`` with ``ZTEXT IS NULL``:
  6240 (type 1) + 1159 (type 2) + 462 (type 3) — these are "media-only"
  deletions that survive as ghost rows with the original type tag but
  no body.

The mask is *conservative*: we filter aggressively by default, with
``include_deleted=True`` as the explicit opt-in for users who want to
investigate (e.g. forensics, "did Bob delete that message").

Cross-machine validation deferred to Phase 3 (Open Questions Q6 RESOLVED
locks this v0.1 signal; second-machine confirmation widens the predicate
to relaxed bit patterns, NOT narrows it — false-negative tombstones are
safer than false-positive content filtering).
"""

from __future__ import annotations

# High-bit pattern correlated with deletion. Live distribution shows
# 0x05000000, 0x05008000, 0x05000180, 0x05001000 all correlate with
# ZTEXT IS NULL and look-deleted rows; the 0xFF000000-masked comparison
# below absorbs all four variants.
_TOMBSTONE_HIGH_BITS_MASK = 0x05000000


# SQL fragment for inlining into reader SQL templates. Single source of
# truth: ``reader/schema_v1.py`` templates reference this constant so a
# bit-pattern change is one edit. Wrapped with double parens so the
# fragment composes safely under arbitrary ``AND`` chaining.
TOMBSTONE_SQL_WHERE: str = (
    "ZMESSAGETYPE != 14 AND NOT (ZTEXT IS NULL AND (ZFLAGS & 0xFF000000) = 0x05000000)"
)


def is_tombstone(message_type: int, flags: int, text: str | None) -> bool:
    """Return True if the row is a soft-deleted (tombstoned) message.

    Two predicates OR'd together (RESEARCH §"Pattern 6"):

    - ``message_type == 14`` (revoked / deleted-for-everyone), OR
    - ``flags & 0xFF000000 == 0x05000000`` AND ``text is None`` (ghost
      row pattern; original type tag survives but body was wiped).

    Phase 1's default ``include_deleted=False`` filters at SQL level via
    :data:`TOMBSTONE_SQL_WHERE` (uses indexes); this Python predicate
    exists as a row-level fallback for callers that already have row data
    in hand (e.g. context_around_stanza post-filtering).
    """
    if message_type == 14:
        return True
    # The 0x05xxxxxx high bits + null body = ghost row pattern.
    return (flags & 0xFF000000) == _TOMBSTONE_HIGH_BITS_MASK and text is None

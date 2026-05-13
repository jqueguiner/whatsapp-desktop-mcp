"""Tombstone predicate tests — READ-08 + P10 mitigation.

Verifies the empirical decision rule from RESEARCH §"Pattern 6"
(verified-live counts on the user's Mac 2026-05-13):

  Tombstoned ⟺ ZMESSAGETYPE == 14
              OR (ZFLAGS & 0xFF000000 == 0x05000000 AND ZTEXT IS NULL)

Exercises all four observed `ZFLAGS` patterns from the live
distribution (0x01000000 normal, 0x05000000 / 0x05008000 / 0x05000180
high-bit) and locks the SQL filter constant
(:data:`TOMBSTONE_SQL_WHERE`) so a future schema bump that changes the
filter shape surfaces here, not silently in production.
"""

from __future__ import annotations

from whatsapp_mcp.reader.tombstones import TOMBSTONE_SQL_WHERE, is_tombstone


def test_tombstone_message_type_14() -> None:
    """ZMESSAGETYPE=14 is always tombstone, regardless of flags or text."""
    assert is_tombstone(14, 0x01000000, "still-here") is True
    assert is_tombstone(14, 0x00000000, None) is True
    assert is_tombstone(14, 0xFFFFFFFF, "bytes here") is True


def test_tombstone_high_bit_with_null_text() -> None:
    """All four observed high-bit ZFLAGS patterns with null text -> tombstone."""
    assert is_tombstone(0, 0x05000000, None) is True
    assert is_tombstone(0, 0x05008000, None) is True
    assert is_tombstone(0, 0x05000180, None) is True
    assert is_tombstone(0, 0x05001000, None) is True


def test_not_tombstone_normal_text() -> None:
    """Normal flags + non-null text -> NOT tombstone (control)."""
    assert is_tombstone(0, 0x01000000, "hi") is False


def test_not_tombstone_high_bit_with_text() -> None:
    """High-bit flags but text-still-present -> NOT tombstone.

    The high-bit pattern only filters when text is ALSO null. A user-edited
    message that retained text but somehow carries the high-bit flag should
    surface to the caller.
    """
    assert is_tombstone(0, 0x05000000, "still text") is False
    assert is_tombstone(0, 0x05008000, "still text") is False
    assert is_tombstone(0, 0x05000180, "still text") is False


def test_not_tombstone_normal_flags_null_text() -> None:
    """Normal flags + null text -> NOT tombstone (e.g. media message with no caption)."""
    assert is_tombstone(1, 0x01000000, None) is False  # image without caption
    assert is_tombstone(2, 0x01000000, None) is False  # video without caption


def test_TOMBSTONE_SQL_WHERE_constant_present() -> None:
    """The SQL filter constant has the locked shape (READ-08 single source of truth)."""
    expected = "ZMESSAGETYPE != 14 AND NOT (ZTEXT IS NULL AND (ZFLAGS & 0xFF000000) = 0x05000000)"
    assert TOMBSTONE_SQL_WHERE == expected

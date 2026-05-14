"""Cocoa-epoch <-> Unix-epoch helper tests (RESEARCH §"Cocoa Epoch ↔ Unix Conversion").

Boundary + round-trip + live-anchor regression tests for
:mod:`whatsapp_desktop_mcp.time`. The verified-live anchor on the user's Mac
on 2026-05-13 was ``ZMESSAGEDATE = 800352916`` -> ``2026-05-13``;
:func:`test_live_anchor_resolves_to_2026_may_13` re-derives that
deterministically with stdlib ``datetime`` so any change to
``COCOA_EPOCH_OFFSET`` would surface here.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from whatsapp_desktop_mcp.time import COCOA_EPOCH_OFFSET, cocoa_to_unix, unix_to_cocoa


def test_cocoa_epoch_offset() -> None:
    """``cocoa_to_unix(0) == 978_307_200`` (Cocoa epoch is 2001-01-01 UTC)."""
    assert COCOA_EPOCH_OFFSET == 978_307_200
    assert cocoa_to_unix(0) == 978_307_200


def test_unix_to_cocoa_inverse() -> None:
    """``unix_to_cocoa(978_307_200) == 0.0`` (the inverse boundary)."""
    assert unix_to_cocoa(978_307_200) == 0.0


@pytest.mark.parametrize(
    "unix_seconds",
    [
        0,
        978_307_200,  # Cocoa epoch in Unix
        1_000_000_000,
        1_700_000_000,
        1_747_140_000,  # current-ish anchor used elsewhere in tests
        2_524_608_000,  # 2050-01-01-ish — future-proof anchor
    ],
)
def test_round_trip_arbitrary_unix(unix_seconds: int) -> None:
    """``cocoa_to_unix(unix_to_cocoa(N)) == N`` for representative Unix values."""
    assert cocoa_to_unix(unix_to_cocoa(unix_seconds)) == unix_seconds


def test_live_anchor_resolves_to_2026_may_13() -> None:
    """The verified-live ZMESSAGEDATE = 800352916 -> 2026-05-13 (RESEARCH §time module).

    Documents the live anchor from the user's Mac on 2026-05-13 in a
    deterministic stdlib computation; any drift in ``COCOA_EPOCH_OFFSET``
    surfaces as a failed equality here, not a silent off-by-Y.
    """
    unix_ts = cocoa_to_unix(800_352_916)
    dt = datetime.fromtimestamp(unix_ts, tz=UTC)
    assert dt.date().isoformat() == "2026-05-13"


def test_cocoa_to_unix_truncates_subseconds() -> None:
    """``cocoa_to_unix`` truncates the sub-second fraction (Phase 1 surfaces ``int``)."""
    assert cocoa_to_unix(0.9) == 978_307_200  # truncated, not rounded
    assert cocoa_to_unix(1.5) == 978_307_201

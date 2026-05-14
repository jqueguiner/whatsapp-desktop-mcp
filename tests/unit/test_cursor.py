"""Cursor codec round-trip + tampering tests (W2 widened anchor_kind discriminator).

Plan 01-01 ships :func:`whatsapp_desktop_mcp.models.encode_cursor` /
:func:`decode_cursor` with the W2-widened ``anchor_kind`` discriminator
(``z_sort`` for ``read_chat`` / ``cocoa_ts`` for ``search_messages``).
This file exercises:

- Round-trip identity for both anchor_kind values across boundary
  numerics (zero / typical / large / negative).
- Tampering rejection: bad base64, bad JSON, missing keys, wrong types,
  unknown ``anchor_kind`` (the W2 discriminator), extra keys.

T-01-01 mitigation: ``decode_cursor`` MUST raise :class:`CursorError`
(a ``ValueError`` subclass) on every malformed input — never silently
fall through to "start from beginning".
"""

from __future__ import annotations

import base64
import json

import pytest

from whatsapp_desktop_mcp.models import CursorError, decode_cursor, encode_cursor


def _b64(payload: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def test_round_trip_z_sort() -> None:
    """Round-trip a typical ``z_sort`` cursor (W2 — read_chat anchor)."""
    cursor = encode_cursor(42, 1.5e18, "z_sort")
    chat_id, anchor, kind = decode_cursor(cursor)
    assert chat_id == 42
    assert anchor == 1.5e18
    assert kind == "z_sort"


def test_round_trip_cocoa_ts() -> None:
    """Round-trip a typical ``cocoa_ts`` cursor (W2 — search_messages anchor)."""
    cursor = encode_cursor(7, 1_747_140_000.0, "cocoa_ts")
    chat_id, anchor, kind = decode_cursor(cursor)
    assert chat_id == 7
    assert anchor == 1_747_140_000.0
    assert kind == "cocoa_ts"


@pytest.mark.parametrize("anchor_kind", ["z_sort", "cocoa_ts"])
@pytest.mark.parametrize(
    "anchor_value",
    [0.0, 1.0, -1.0, 1e18, 1.5e18, 800_352_916.0],
)
def test_round_trip_zero_and_max(
    anchor_kind: str,
    anchor_value: float,
) -> None:
    """Boundary values for both anchor_kind discriminator values round-trip cleanly."""
    cursor = encode_cursor(0, anchor_value, anchor_kind)  # type: ignore[arg-type]
    cid, anchor, kind = decode_cursor(cursor)
    assert cid == 0
    assert anchor == anchor_value
    assert kind == anchor_kind


def test_decode_invalid_base64_raises_cursor_error() -> None:
    """Bad base64 -> :class:`CursorError`. The exclamation marks fail urlsafe decode."""
    with pytest.raises(CursorError):
        decode_cursor("not-base64-!!!")


def test_decode_invalid_json_raises_cursor_error() -> None:
    """Base64-decodable but non-JSON -> CursorError."""
    bad = base64.urlsafe_b64encode(b"not json").decode("ascii")
    with pytest.raises(CursorError):
        decode_cursor(bad)


def test_decode_missing_keys_raises_cursor_error() -> None:
    """Payloads missing any of the three required keys -> CursorError."""
    # Completely wrong shape.
    with pytest.raises(CursorError):
        decode_cursor(_b64({"foo": "bar"}))
    # W2 — anchor_kind is mandatory; payload missing only that one key fails.
    with pytest.raises(CursorError):
        decode_cursor(_b64({"chat_id": 1, "anchor": 1.0}))
    # Missing chat_id alone fails.
    with pytest.raises(CursorError):
        decode_cursor(_b64({"anchor": 1.0, "anchor_kind": "z_sort"}))
    # Missing anchor alone fails.
    with pytest.raises(CursorError):
        decode_cursor(_b64({"chat_id": 1, "anchor_kind": "z_sort"}))


def test_decode_unknown_anchor_kind_raises_cursor_error() -> None:
    """Unknown ``anchor_kind`` -> CursorError (Literal enforcement at decode time)."""
    payload = {"chat_id": 1, "anchor": 1.0, "anchor_kind": "made_up"}
    with pytest.raises(CursorError):
        decode_cursor(_b64(payload))


def test_decode_wrong_types_raises_cursor_error() -> None:
    """Wrong types for chat_id / anchor -> CursorError."""
    # chat_id is a string.
    with pytest.raises(CursorError):
        decode_cursor(_b64({"chat_id": "not-int", "anchor": 1.0, "anchor_kind": "z_sort"}))
    # anchor is a list.
    with pytest.raises(CursorError):
        decode_cursor(_b64({"chat_id": 1, "anchor": [1.0], "anchor_kind": "z_sort"}))
    # chat_id is a bool (a bool is an int subclass; we explicitly reject it).
    with pytest.raises(CursorError):
        decode_cursor(_b64({"chat_id": True, "anchor": 1.0, "anchor_kind": "z_sort"}))


def test_decode_extra_keys_raises_cursor_error() -> None:
    """Extra keys beyond the three expected ones -> CursorError (strict shape)."""
    payload = {
        "chat_id": 1,
        "anchor": 1.0,
        "anchor_kind": "z_sort",
        "evil": "extra",
    }
    with pytest.raises(CursorError):
        decode_cursor(_b64(payload))


def test_cursor_error_is_value_error_subclass() -> None:
    """``CursorError`` is a ``ValueError`` subclass — Plan 04 tools wrap it."""
    assert issubclass(CursorError, ValueError)


def test_decode_junk_string_raises_cursor_error() -> None:
    """The literal "junk" failure path used by the read_chat tool guard test."""
    with pytest.raises(CursorError):
        decode_cursor("junk")

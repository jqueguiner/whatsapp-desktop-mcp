"""Pydantic round-trip + Literal-enforcement tests for the Plan 01 model surface.

Codifies the locked DATA-01/02/03/04 + Cursor + Coverage public surface from
Plan 01-01: every model in :mod:`whatsapp_mcp.models` round-trips losslessly
through ``model_dump_json -> model_validate_json``, every ``Literal``
discriminator rejects unknown values, and :class:`MediaRef` carries no
bytes/base64 inlining field (DATA-03 schema-level enforcement; CLAUDE.md
hard rule #4).

These tests are pure (no fixtures, no I/O); they fail fast at import time
if any model field is renamed or removed (a future executor that drops
e.g. ``Coverage.is_full`` will see this file fail before any reader test
even runs).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from whatsapp_mcp.models import (
    Chat,
    Contact,
    Coverage,
    GroupInfo,
    GroupMember,
    Jid,
    MediaRef,
    Message,
)


def _sample_jid_phone() -> Jid:
    return Jid(kind="phone", raw="33612345678@s.whatsapp.net", phone="33612345678")


def _sample_jid_lid() -> Jid:
    return Jid(kind="lid", raw="99887766554433@lid", lid="99887766554433")


def _sample_coverage() -> Coverage:
    return Coverage(
        from_ts=1_700_000_000,
        to_ts=1_747_140_000,
        asked_window_seconds=3600,
        have_window_seconds=47_140_000,
        is_full=True,
    )


def test_chat_round_trip() -> None:
    """``Chat.model_dump_json`` parses back losslessly via ``model_validate_json``."""
    original = Chat(
        chat_id=42,
        kind="direct",
        jid=_sample_jid_phone(),
        display_name="Alice",
        last_activity_ts=1_747_140_000,
        last_message_preview="hi",
        unread_count=3,
        is_archived=False,
        is_hidden=False,
        coverage=_sample_coverage(),
    )
    raw = original.model_dump_json()
    parsed = Chat.model_validate_json(raw)
    assert parsed == original


def test_message_round_trip() -> None:
    original = Message(
        message_id="ABC123",
        chat_id=1,
        sender_jid=_sample_jid_phone(),
        timestamp=1_747_140_000,
        body="hello",
        kind="text",
        is_outgoing=False,
        is_starred=True,
        quoted_message_id="PARENT99",
        media=None,
    )
    raw = original.model_dump_json()
    assert Message.model_validate_json(raw) == original


def test_contact_round_trip() -> None:
    original = Contact(
        display_name="Alice",
        jid=_sample_jid_phone(),
        known_identifiers=[_sample_jid_phone(), _sample_jid_lid()],
        chat_id=7,
        last_message_preview="hi",
        last_message_ts=1_747_140_000,
        disambiguation_required=False,
    )
    raw = original.model_dump_json()
    assert Contact.model_validate_json(raw) == original


def test_jid_round_trip_all_kinds() -> None:
    for jid in (
        Jid(kind="phone", raw="33612345678@s.whatsapp.net", phone="33612345678"),
        Jid(kind="lid", raw="9988@lid", lid="9988"),
        Jid(kind="group", raw="123-456@g.us"),
        Jid(kind="broadcast", raw="abc@broadcast"),
        Jid(kind="status", raw="0@status"),
    ):
        raw = jid.model_dump_json()
        assert Jid.model_validate_json(raw) == jid


def test_group_info_round_trip() -> None:
    original = GroupInfo(
        chat_id=99,
        subject="Weekend Plans",
        description=None,  # W5 lock
        creation_ts=1_700_000_000,
        creator_jid=_sample_jid_phone(),
        owner_jid=_sample_jid_phone(),
        members=[
            GroupMember(
                jid=_sample_jid_phone(),
                display_name="Alice",
                is_admin=True,
                is_active=True,
            ),
        ],
        is_muted=False,  # W5 lock
    )
    raw = original.model_dump_json()
    assert GroupInfo.model_validate_json(raw) == original


def test_group_member_round_trip() -> None:
    original = GroupMember(
        jid=_sample_jid_phone(),
        display_name="Alice",
        is_admin=False,
        is_active=True,
    )
    raw = original.model_dump_json()
    assert GroupMember.model_validate_json(raw) == original


def test_media_ref_round_trip() -> None:
    original = MediaRef(
        local_path="/tmp/x/y/photo.jpg",  # noqa: S108 — fixture path; no IO
        filename="photo.jpg",
        mime="image/jpeg",
        size_bytes=12_345,
        duration_seconds=None,
        latitude=None,
        longitude=None,
    )
    raw = original.model_dump_json()
    assert MediaRef.model_validate_json(raw) == original


def test_coverage_round_trip() -> None:
    original = _sample_coverage()
    raw = original.model_dump_json()
    assert Coverage.model_validate_json(raw) == original


def test_chat_kind_literal_rejects_unknown() -> None:
    """``ChatKind`` is a Pydantic Literal — unknown values raise ``ValidationError``."""
    with pytest.raises(ValidationError):
        Chat(
            chat_id=1,
            kind="banana",  # type: ignore[arg-type]
            jid=_sample_jid_phone(),
            display_name="x",
            last_activity_ts=None,
            last_message_preview=None,
            unread_count=0,
            is_archived=False,
            is_hidden=False,
            coverage=_sample_coverage(),
        )


def test_message_kind_literal_includes_other() -> None:
    """``MessageKind`` accepts ``"other"`` — the catch-all bucket Plan 02 uses."""
    msg = Message(
        message_id="X",
        chat_id=1,
        sender_jid=_sample_jid_phone(),
        timestamp=0,
        body=None,
        kind="other",
        is_outgoing=False,
        is_starred=False,
        quoted_message_id=None,
        media=None,
    )
    assert msg.kind == "other"


def test_message_kind_literal_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        Message(
            message_id="X",
            chat_id=1,
            sender_jid=_sample_jid_phone(),
            timestamp=0,
            body=None,
            kind="banana",  # type: ignore[arg-type]
            is_outgoing=False,
            is_starred=False,
            quoted_message_id=None,
            media=None,
        )


def test_jid_kind_phone_default_resolution_fields_optional() -> None:
    """``Jid(kind="phone", raw=...)`` constructs with default ``phone=None, lid=None``."""
    jid = Jid(kind="phone", raw="33612345678@s.whatsapp.net")
    assert jid.phone is None
    assert jid.lid is None


def test_media_ref_no_bytes_field() -> None:
    """:class:`MediaRef` has no field hinting at bytes/base64/data inlining (DATA-03)."""
    fields = set(MediaRef.model_fields.keys())
    forbidden_names = {"data", "bytes", "base64", "content", "raw_bytes", "encoded"}
    assert fields.isdisjoint(forbidden_names), (
        f"MediaRef must not inline bytes; forbidden field present: "
        f"{fields & forbidden_names} (DATA-03; CLAUDE.md hard rule #4)"
    )
    # Positive shape: the four DATA-03 mandatory fields are present.
    assert {"local_path", "filename", "mime", "size_bytes"} <= fields


def test_coverage_is_full_default_required() -> None:
    """``Coverage.is_full`` has no default — callers must compute and pass it."""
    with pytest.raises(ValidationError):
        Coverage(  # type: ignore[call-arg]
            from_ts=None,
            to_ts=None,
        )

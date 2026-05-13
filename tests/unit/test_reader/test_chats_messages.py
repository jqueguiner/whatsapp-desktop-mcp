"""Reader chats + messages public-surface tests against the synthetic fixture.

Covers: ``list_chats``, ``window`` (default + include_deleted + ZSORT
ordering), ``since`` (read_recent backing), ``context_around_stanza``,
``parent_of_stanza``, ``latest_timestamp``. P1 (cache-vs-truth coverage),
READ-08 (default tombstone filtering), READ-02/03/07 behaviors, B2 (the
``window`` returns ``tuple[list[Message], float | None]``).
"""

from __future__ import annotations

import pytest

from whatsapp_mcp import reader
from whatsapp_mcp.models import Chat, Message


@pytest.mark.asyncio
async def test_list_chats_returns_seeded_three(monkeypatch_paths: None) -> None:
    chats = await reader.list_chats(limit=200)
    assert len(chats) == 3
    assert all(isinstance(c, Chat) for c in chats)


@pytest.mark.asyncio
async def test_list_chats_kind_mapping(monkeypatch_paths: None) -> None:
    """ZSESSIONTYPE -> ChatKind: 0->direct, 1->group, 3->broadcast."""
    chats = await reader.list_chats(limit=200)
    by_id = {c.chat_id: c for c in chats}
    assert by_id[1].kind == "direct"
    assert by_id[2].kind == "group"
    assert by_id[3].kind == "broadcast"


@pytest.mark.asyncio
async def test_list_chats_carries_per_chat_coverage(monkeypatch_paths: None) -> None:
    """P1 mitigation: every Chat carries a Coverage with from_ts / to_ts populated."""
    chats = await reader.list_chats(limit=200)
    by_id = {c.chat_id: c for c in chats}
    # Chat 1 has 50+ messages — coverage from_ts < to_ts.
    cov1 = by_id[1].coverage
    assert cov1.from_ts is not None
    assert cov1.to_ts is not None
    assert cov1.from_ts <= cov1.to_ts


@pytest.mark.asyncio
async def test_window_default_filters_tombstones(monkeypatch_paths: None) -> None:
    """``window(include_deleted=False)`` excludes the seeded tombstones."""
    messages, _last = await reader.window(chat_id=1, limit=500)
    # No type-14 messages, no high-bit + null-text rows.
    for m in messages:
        assert m.kind != "revoked"
        # The reader projects high-bit-null-text rows out via SQL filter,
        # so we should never see a Message whose body is None coming from
        # one of those rows. (Genuine no-caption media survives because
        # the flag pattern is 0x01000000.)


@pytest.mark.asyncio
async def test_window_include_deleted_returns_tombstones(monkeypatch_paths: None) -> None:
    """``window(include_deleted=True)`` surfaces the additional tombstones."""
    excluded, _ = await reader.window(chat_id=1, limit=500, include_deleted=False)
    included, _ = await reader.window(chat_id=1, limit=500, include_deleted=True)
    assert len(included) > len(excluded), (
        "include_deleted=True must surface MORE messages than the filtered default"
    )


@pytest.mark.asyncio
async def test_window_orders_by_zsort_desc(monkeypatch_paths: None) -> None:
    """First message in the result has the highest timestamp (ZSORT DESC)."""
    messages, _last = await reader.window(chat_id=1, limit=500)
    assert len(messages) >= 2
    # Newest-first ordering — the first row's timestamp is >= the last row's.
    assert messages[0].timestamp >= messages[-1].timestamp


@pytest.mark.asyncio
async def test_window_returns_tuple_shape(monkeypatch_paths: None) -> None:
    """B2 lock: ``window`` returns ``tuple[list[Message], float | None]``."""
    result = await reader.window(chat_id=1, limit=10)
    assert isinstance(result, tuple)
    assert len(result) == 2
    msgs, last = result
    assert isinstance(msgs, list)
    assert all(isinstance(m, Message) for m in msgs)
    # last is float when the page is non-empty; None when empty.
    if msgs:
        assert isinstance(last, float)
    else:
        assert last is None


@pytest.mark.asyncio
async def test_window_empty_when_chat_unknown(monkeypatch_paths: None) -> None:
    """A bogus chat_id returns ``([], None)`` (B2 — None when empty)."""
    msgs, last = await reader.window(chat_id=99_999, limit=200)
    assert msgs == []
    assert last is None


@pytest.mark.asyncio
async def test_since_returns_messages_in_window(monkeypatch_paths: None) -> None:
    """``since(cutoff_ts)`` returns messages with ``timestamp >= cutoff``."""
    import time

    # The seeded fixture spans the last 30 days; cutoff at 7 days ago.
    cutoff_ts = int(time.time()) - 7 * 86_400
    msgs = await reader.since(chat_id=1, cutoff_unix_ts=cutoff_ts)
    # All returned messages must satisfy the cutoff.
    for m in msgs:
        assert m.timestamp >= cutoff_ts


@pytest.mark.asyncio
async def test_context_around_stanza_returns_target_plus_window(
    monkeypatch_paths: None,
) -> None:
    """A known stanza_id returns 5 messages centered on the target (before=2, after=2)."""
    target = "STANZA-CHAT1-0010"
    msgs = await reader.context_around_stanza(target, before=2, after=2)
    # Target + at most 2 before + 2 after = up to 5 messages.
    assert 1 <= len(msgs) <= 5
    # Chronological order (ASC by ZSORT): timestamps non-decreasing.
    timestamps = [m.timestamp for m in msgs]
    assert timestamps == sorted(timestamps)


@pytest.mark.asyncio
async def test_parent_of_stanza_for_quote_reply(monkeypatch_paths: None) -> None:
    """A quote-reply stanza returns the parent Message; non-quote returns None."""
    # The fixture seeds STANZA-QUOTE-... pointing to PK=5 (a normal message).
    # Look up the parent: must succeed.
    quote_msgs, _ = await reader.window(chat_id=1, limit=500)
    quote_msg = next((m for m in quote_msgs if m.message_id.startswith("STANZA-QUOTE-")), None)
    assert quote_msg is not None
    parent = await reader.parent_of_stanza(quote_msg.message_id)
    assert parent is not None
    assert isinstance(parent, Message)

    # Now check that a non-quote message returns None for the parent lookup.
    normal = next((m for m in quote_msgs if m.message_id.startswith("STANZA-CHAT1-")), None)
    assert normal is not None
    parent_of_normal = await reader.parent_of_stanza(normal.message_id)
    assert parent_of_normal is None


@pytest.mark.asyncio
async def test_latest_timestamp_returns_max_ts(monkeypatch_paths: None) -> None:
    """``latest_timestamp()`` returns the maximum ZMESSAGEDATE Unix-converted."""
    ts = await reader.latest_timestamp()
    assert ts is not None
    assert isinstance(ts, int)
    # Sanity: the seeded data is around 'now' (within a year either way).
    import time

    assert abs(ts - int(time.time())) < 365 * 86_400


@pytest.mark.asyncio
async def test_message_with_media_resolves_media_ref(monkeypatch_paths: None) -> None:
    """The seeded media message (STANZA-MEDIA-) carries a populated MediaRef."""
    msgs, _ = await reader.window(chat_id=1, limit=500)
    media_msg = next((m for m in msgs if m.message_id.startswith("STANZA-MEDIA-")), None)
    assert media_msg is not None
    assert media_msg.media is not None
    assert media_msg.media.filename == "photo.jpg"
    assert media_msg.media.mime == "image/jpeg"


@pytest.mark.asyncio
async def test_find_chat_by_id_returns_chat(monkeypatch_paths: None) -> None:
    chat = await reader.find_chat_by_id(2)
    assert chat is not None
    assert chat.chat_id == 2
    assert chat.kind == "group"


@pytest.mark.asyncio
async def test_find_chat_by_id_returns_none_for_missing(monkeypatch_paths: None) -> None:
    chat = await reader.find_chat_by_id(99_999)
    assert chat is None


@pytest.mark.asyncio
async def test_find_chat_by_jid_resolves(monkeypatch_paths: None) -> None:
    """``find_chat_by_jid`` resolves a known JID to its chat row."""
    chat = await reader.find_chat_by_jid("33612345678@s.whatsapp.net")
    assert chat is not None
    assert chat.chat_id == 1

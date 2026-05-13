"""Read-tool registration + cross-tool guards (W1, W2, W3 verifications).

Asserts:
- ``mcp.list_tools()`` returns exactly the 8 tools (doctor + 7 reads).
- W1 — every tool (no carve-out, including doctor) advertises
  ``meta["anthropic/maxResultSizeChars"] == 60_000``.
- Every tool carries ``annotations.readOnlyHint == True``.
- W2 — cross-tool cursor reuse rejected: a search_messages cursor
  (anchor_kind=cocoa_ts) passed to read_chat is rejected; vice versa
  also rejected. read_chat with mismatched chat_id rejected
  (T-04-01 mitigation).
- read_chat returns a `next_cursor` decodable to the locked tuple shape
  including the W2 anchor_kind discriminator.
- Char-cap: synthetic 5000-msg fixture forces read_chat to return
  ≤ 60_000 chars + a non-None decodable next_cursor.
- W3 — doctor.py source contains NO ``@timeout(`` decorator (Plan 05
  W3 lock; preserved as a regression guard here in addition to the
  dedicated test_doctor_phase1.py file).
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from whatsapp_mcp.models import decode_cursor, encode_cursor
from whatsapp_mcp.server import mcp
from whatsapp_mcp.tools.read_chat import read_chat
from whatsapp_mcp.tools.search_messages import search_messages

_EXPECTED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "doctor",
        "extract_recent",
        "get_chat_metadata",
        "get_message_context",
        "list_chats",
        "read_chat",
        "search_contacts",
        "search_messages",
    }
)


@pytest.mark.asyncio
async def test_eight_tools_registered() -> None:
    """``mcp.list_tools()`` includes the 8 read tools (doctor + 7 reads).

    Phase 2 Plan 02-05 introduces tool-tier tests for ``send_message``
    that import the module at collection time, which (via the
    ``@mcp.tool`` decorator side-effect) permanently registers the 9th
    tool in the process's FastMCP instance. This test therefore asserts
    the 8 read tools are a SUBSET of the registered names — drift in
    the read-tool surface still fails the assertion; the optional
    ``send_message`` 9th name is tolerated.
    """
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    missing = _EXPECTED_TOOL_NAMES - names
    assert not missing, f"missing expected read tools: {missing}"
    # The only acceptable extra name is the gated ``send_message``.
    extras = names - _EXPECTED_TOOL_NAMES
    assert extras <= {"send_message"}, f"unexpected tool registration drift: {extras}"


@pytest.mark.asyncio
async def test_every_tool_is_read_only_hint() -> None:
    """All 8 READ tools carry ``annotations.readOnlyHint == True`` (Plan 04 contract).

    Phase 2's ``send_message`` (which Plan 02-05 may register globally
    in this process) is explicitly ``readOnlyHint=False`` per D-20; we
    skip it here. The 8 Phase 0/1 read tools MUST all carry
    ``readOnlyHint=True`` regardless.
    """
    tools = await mcp.list_tools()
    for t in tools:
        if t.name == "send_message":
            continue  # send_message intentionally readOnlyHint=False (D-20)
        assert t.annotations is not None, f"tool {t.name} has no annotations"
        assert t.annotations.readOnlyHint is True, f"tool {t.name} missing readOnlyHint=True"


@pytest.mark.asyncio
async def test_every_tool_has_max_result_size_meta() -> None:
    """W1 lock — every tool (INCLUDING doctor) advertises 60k char meta.

    No carve-out. The Plan 05 W1 fix codified this; this test catches any
    future regression that drops the annotation from doctor.
    """
    tools = await mcp.list_tools()
    for t in tools:
        assert t.meta is not None, f"tool {t.name} has no meta"
        max_size = t.meta.get("anthropic/maxResultSizeChars")
        assert max_size == 60_000, f"tool {t.name} missing 60k char meta (W1 lock); got {t.meta!r}"


def test_doctor_source_does_not_have_tool_level_timeout() -> None:
    """W3 lock — ``tools/doctor.py`` source must not contain a ``@timeout(`` decorator.

    DIAG-02 mandates doctor stay callable when other surfaces fail; an
    outer per-tool timeout would fire mid-probe and return a partial
    DoctorReport that violates DIAG-02. The grep is a structural
    regression guard alongside the runtime introspection in
    test_doctor_phase1.py.
    """
    from whatsapp_mcp.tools import doctor as doctor_module

    doctor_src = Path(inspect.getfile(doctor_module)).read_text(encoding="utf-8")
    assert "@timeout(" not in doctor_src, (
        "W3 violation: tools/doctor.py contains a @timeout(...) decorator "
        "(DIAG-02 partial-result risk; Plan 05 explicitly forbids it)"
    )


# ---------------------------------------------------------------------------
# W2 cursor-reuse guards: read_chat rejects cocoa_ts cursors; search_messages
# rejects z_sort cursors. read_chat rejects mismatched chat_id (T-04-01).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_chat_cursor_chat_id_mismatch_rejected(monkeypatch_paths: None) -> None:
    """``read_chat(chat_id=1, cursor=encode_cursor(99, ..., 'z_sort'))`` rejects."""
    bad_cursor = encode_cursor(99, 1.0, "z_sort")
    with pytest.raises(ValueError, match="Cursor does not match chat_id"):
        await read_chat(chat_id=1, cursor=bad_cursor)


@pytest.mark.asyncio
async def test_read_chat_cursor_wrong_anchor_kind_rejected(
    monkeypatch_paths: None,
) -> None:
    """W2: read_chat rejects a cocoa_ts cursor (cross-tool reuse from search_messages)."""
    bad_cursor = encode_cursor(1, 1_747_140_000.0, "cocoa_ts")
    with pytest.raises(ValueError, match="anchor_kind"):
        await read_chat(chat_id=1, cursor=bad_cursor)


@pytest.mark.asyncio
async def test_search_messages_cursor_anchor_kind(monkeypatch_paths: None) -> None:
    """``search_messages`` returns a next_cursor whose decoded anchor_kind == 'cocoa_ts'."""
    # Force a small limit so the result is "full" and a cursor is produced.
    result = await search_messages(query="normal", limit=2)
    next_cursor = result.get("next_cursor")
    assert next_cursor is not None, (
        f"search_messages returned no next_cursor (full_page logic broken); body={result!r}"
    )
    _chat_id, _anchor, anchor_kind = decode_cursor(next_cursor)
    assert anchor_kind == "cocoa_ts"


@pytest.mark.asyncio
async def test_search_messages_rejects_z_sort_cursor(monkeypatch_paths: None) -> None:
    """W2 mirror: search_messages rejects a z_sort cursor (cross-tool reuse from read_chat)."""
    bad_cursor = encode_cursor(0, 1.5e18, "z_sort")
    with pytest.raises(ValueError, match="anchor_kind"):
        await search_messages(query="hi", cursor=bad_cursor)


@pytest.mark.asyncio
async def test_read_chat_invalid_cursor_rejected(monkeypatch_paths: None) -> None:
    """A junk cursor surfaces as a structured ValueError (CursorError converted)."""
    with pytest.raises(ValueError, match="cursor"):
        await read_chat(chat_id=1, cursor="junk")


@pytest.mark.asyncio
async def test_read_chat_returns_decodable_next_cursor(monkeypatch_paths: None) -> None:
    """A page-limit-saturating call returns a decodable z_sort cursor."""
    # The fixture seeds 50+ messages on chat 1. Limit=10 forces a full page.
    result = await read_chat(chat_id=1, limit=10)
    next_cursor = result.get("next_cursor")
    assert next_cursor is not None
    chat_id, anchor, anchor_kind = decode_cursor(next_cursor)
    assert chat_id == 1
    assert isinstance(anchor, float)
    assert anchor_kind == "z_sort"


@pytest.mark.asyncio
async def test_read_chat_char_cap(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    large_chat_fixture: tuple[str, int],
) -> None:
    """5000-msg fixture forces read_chat to return ≤60_000 chars + decodable cursor."""
    db_path, chat_id = large_chat_fixture

    # Repoint just this test's reader paths to the large fixture. The other
    # paths (LID, ContactsV2, media_root) are not touched by read_chat
    # against this fixture, so we leave them alone.
    import whatsapp_mcp.paths
    import whatsapp_mcp.reader.messages

    monkeypatch.setattr(whatsapp_mcp.paths, "resolve_chatstorage_path", lambda: db_path)
    monkeypatch.setattr(whatsapp_mcp.reader.messages, "resolve_chatstorage_path", lambda: db_path)

    # media_root is touched by the message projection layer; point it at
    # the tempdir so resolve_media_ref's prefix check has a valid root
    # (even though no media rows are seeded here).
    monkeypatch.setattr(whatsapp_mcp.paths, "resolve_media_root", lambda: str(tmp_path))
    monkeypatch.setattr(whatsapp_mcp.reader.messages, "resolve_media_root", lambda: str(tmp_path))

    # limit=200 (the maximum) — body should approach but stay under cap.
    result = await read_chat(chat_id=chat_id, limit=200)
    body_len = len(json.dumps(result))
    assert body_len <= 60_000, f"read_chat body exceeded char-cap: {body_len} chars"
    # next_cursor present (more rows exist after head-trim).
    next_cursor = result.get("next_cursor")
    assert next_cursor is not None
    cid, anchor, kind = decode_cursor(next_cursor)
    assert cid == chat_id
    assert isinstance(anchor, float)
    assert kind == "z_sort"
